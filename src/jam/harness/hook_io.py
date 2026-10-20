"""The plumbing every Claude Code hook shares: the SessionStart envelope, the capped stdin read, the alarm and quiet streams.

Stdlib only, and the one module of jam it imports, `jam.streams`, is stdlib only
too, so a hook starts about as fast as the interpreter does.
"""

from __future__ import annotations

import contextlib
import json
import signal
from collections.abc import Callable
from typing import IO, Any, Final, Optional

from ..streams import silenced

MAX_STDIN: Final = 256 * 1024


def hook_output(text: str) -> str:
    """The SessionStart envelope as one ASCII line, without its newline.

    `additionalContext` must be nested in `hookSpecificOutput`: at the top level
    the platform silently ignores it.
    """
    envelope = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    return json.dumps(envelope, ensure_ascii=True, separators=(",", ":"))


def decoded(raw: bytes) -> dict[str, Any]:
    """The JSON object in `raw`, or {} for anything else (not UTF-8, not JSON, deeply nested, not an object)."""
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        return {}
    return value if isinstance(value, dict) else {}


def payload_from(stream: IO[bytes], limit: int = MAX_STDIN) -> dict[str, Any]:
    """The hook payload on `stream`, or {} when it is oversized, unreadable, not yet written or not a JSON object.

    It asks for one byte more than `limit` and never more, so a runaway writer
    cannot grow this process. A non-blocking pipe that has nothing yet answers
    None instead of waiting, and that is an empty payload like any other.
    """
    try:
        raw = stream.read(limit + 1) or b""
    except (OSError, ValueError):  # a closed or broken stdin
        return {}
    return decoded(raw) if len(raw) <= limit else {}


def arm_alarm(seconds: int, alarm: Callable[[int], object] = signal.alarm) -> None:
    """Have the kernel end this process after `seconds`; 0 cancels.

    SIGALRM gets its default disposition, which terminates the process, and is
    unblocked. An ignored signal and a blocked one are both inherited across exec,
    and either would silently void the bound.
    """
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGALRM})
    alarm(seconds)


def emitted(stream: IO[str], line: str) -> None:
    """Write `line` and a newline, and flush at once; a failed write raises after the stream is silenced.

    Whatever the error is (a reader that has gone, a descriptor that cannot be
    written to, a full disk), the failed flush left the line in the buffer and
    the interpreter would try again at exit and exit with status 120.
    """
    try:
        stream.write(line + "\n")
        stream.flush()
    except OSError:  # BrokenPipeError is one
        silenced(stream)
        raise


def reported(stream: Optional[IO[str]], error: BaseException) -> None:
    """Say which kind of error ended the hook, and nothing else: a message can hold a path or a payload fragment."""
    if stream is None:  # descriptor 2 was closed before the interpreter started
        return
    with contextlib.suppress(OSError, ValueError):  # nobody may be listening to stderr either
        stream.write(type(error).__name__ + "\n")
        stream.flush()
