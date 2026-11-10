"""How a Claude Code transcript reads, for `peek` (D20).

The transcript is the real record of a session: a JSONL file named after its
`sessionId`, in a directory under `projects` of the configuration directory.
Nothing native reads it turn by turn (`claude logs` shows a terminal redraw), so
this is the one module that knows its record shapes, as observed on 2.1.309. It
keeps what the session said and the names of the tools it used; what those tools
took and returned, and what the session thought, stay here. Reading is bounded
and nothing is written.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import reduce
from pathlib import Path
from typing import Any, Final, Optional

from ..session import Peeked, Session, Turn, is_id

# A long session writes megabytes of request records between two turns, so the window is far larger than the turns it is read for.
MAX_TAIL_BYTES: Final = 16 * 1024 * 1024
NO_TRANSCRIPT: Final = "no transcript was found for this session"
UNREADABLE: Final = "the transcript of this session could not be read"
_NO_START: Final = Turn(None, None, "", (), None)
# What the harness wrote into the conversation without an origin starts with a tag or an interrupt marker; a peer's message
# without one starts with its wrapper (both seen up to 2.1.309).
_HARNESS_MARKS: Final = ("<", "[Request interrupted by user")
_PEER_WRAPPER: Final = "Another Claude session sent"


def path_of(config_dir: str, session_id: str) -> Optional[Path]:
    """The transcript of `session_id`, the newest where several directories hold one, or None.

    It is looked up by file name and not by the session's directory: the
    directory that holds the file follows the session's working directory (one
    that entered a worktree had it under the worktree's), so the `cwd` that
    `list` shows cannot be trusted to name it.
    """
    return max(Path(config_dir, "projects").glob(f"*/{session_id}.jsonl"), key=_modified, default=None)


def _modified(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:  # gone since the directory was read
        return 0.0


def tail(path: Path, limit: int = MAX_TAIL_BYTES) -> list[bytes]:
    """The lines in the last `limit` bytes of the file, without the one the start of that window cuts.

    Split on the newline alone: a JSON string may hold any other separator.
    """
    with open(path, "rb") as transcript:
        size = transcript.seek(0, 2)
        transcript.seek(max(0, size - limit))
        lines = transcript.read(limit).split(b"\n")
    return lines if size <= limit else lines[1:]


def records(lines: Iterable[bytes]) -> list[Mapping[str, Any]]:
    """The JSON objects among `lines`. Anything else, a half-written last line for one, is skipped."""
    parsed = (_parsed(line) for line in lines)
    return [record for record in parsed if record is not None]


def _parsed(line: bytes) -> Optional[Mapping[str, Any]]:
    try:
        value = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, Mapping) else None


def turns_of(found: Iterable[Mapping[str, Any]]) -> tuple[Turn, ...]:
    """The turns in `found`, oldest first. Replies before the first prompt are a turn whose start is out of reach."""
    return reduce(_advanced, found, ())


def _advanced(turns: tuple[Turn, ...], record: Mapping[str, Any]) -> tuple[Turn, ...]:
    started = _started(record)
    if started is not None:
        return (*turns, started)
    if record.get("type") != "assistant" or record.get("isSidechain"):
        return turns
    return (*turns[:-1], _extended(turns[-1] if turns else _NO_START, record))


def _started(record: Mapping[str, Any]) -> Optional[Turn]:
    """The turn a record starts, or None: tool results, subagents, summaries and the harness's own notes start none."""
    if record.get("isSidechain"):
        return None
    if record.get("type") == "attachment":
        return _queued(record.get("attachment"), record)
    if record.get("type") != "user" or record.get("isCompactSummary") or "toolUseResult" in record:
        return None
    origin = record.get("origin")
    kind = _kind(origin)
    if kind == "peer":
        return _peer(origin, record)
    if record.get("isMeta") or kind not in (None, "human"):
        return None
    words = _words(_content(record))
    said_by = "user" if kind == "human" else _said_by(words)
    return None if said_by is None else _turn(said_by, words, record)


def _queued(attachment: object, record: Mapping[str, Any]) -> Optional[Turn]:
    """The turn a message that reached a busy session starts: Claude Code writes it as an attachment, not as a prompt."""
    if not isinstance(attachment, Mapping) or attachment.get("type") != "queued_command" or attachment.get("commandMode") != "prompt":
        return None
    origin = attachment.get("origin")
    kind = _kind(origin)
    if kind == "peer":
        return _peer(origin, record)
    return _turn("user", _words(attachment.get("prompt")), record) if kind == "human" else None


def _kind(origin: object) -> object:
    return origin.get("kind") if isinstance(origin, Mapping) else None


def _peer(origin: Mapping[str, Any], record: Mapping[str, Any]) -> Optional[Turn]:
    """A peer's message, by its body. A subagent handing its work back is no peer, and starts no turn."""
    return None if origin.get("handback") else _turn("peer", origin.get("body"), record)


def _said_by(words: str) -> Optional[str]:
    """Who said a prompt that has no origin, as its text shows; None for what the harness wrote."""
    lead = words.lstrip()
    if lead.startswith(_HARNESS_MARKS):
        return None
    return "peer" if lead.startswith(_PEER_WRAPPER) else "user"


def _turn(origin: str, prompt: object, record: Mapping[str, Any]) -> Optional[Turn]:
    return Turn(origin, prompt, "", (), _timestamp(record)) if isinstance(prompt, str) and prompt.strip() else None


def _extended(turn: Turn, record: Mapping[str, Any]) -> Turn:
    """`turn` with one more `assistant` record: its text and the tools named, nothing the tools carried."""
    content = _content(record)
    blocks = [block for block in content if isinstance(block, Mapping)] if isinstance(content, list) else []
    said = [block["text"] for block in blocks if block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip()]
    names = [block["name"] for block in blocks if block.get("type") == "tool_use" and isinstance(block.get("name"), str)]
    return Turn(
        turn.origin,
        turn.prompt,
        "\n\n".join(filter(None, (turn.reply, *said))),
        tuple(dict.fromkeys((*turn.tools, *names))),
        _timestamp(record) or turn.at,
    )


def _content(record: Mapping[str, Any]) -> object:
    message = record.get("message")
    return message.get("content") if isinstance(message, Mapping) else None


def _words(content: object) -> str:
    """The text of a message's content, which is a string or a list of blocks."""
    if isinstance(content, str):
        return content
    blocks = content if isinstance(content, list) else []
    return "\n".join(block["text"] for block in blocks if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str))


def _timestamp(record: Mapping[str, Any]) -> Optional[str]:
    stamp = record.get("timestamp")
    return stamp if isinstance(stamp, str) else None


def peeked(row: Session, config_dir: Optional[str], count: int) -> Peeked:
    """`row` and its last `count` turns. No transcript, or one that cannot be read, is an answer, and it names no path."""
    path = path_of(config_dir, row.session_id) if config_dir is not None and is_id(row.session_id) else None
    if path is None:
        return Peeked(row, (), NO_TRANSCRIPT)
    try:
        found = turns_of(records(tail(path)))
    except OSError:
        return Peeked(row, (), UNREADABLE)
    return Peeked(row, found[max(len(found) - count, 0) :])
