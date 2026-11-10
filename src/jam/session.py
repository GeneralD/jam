"""The harness-neutral view of a session. Stdlib only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

# Ids become file names and argv entries, so this pattern must never admit "/",
# NUL, or a leading "." or "-".
ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def is_id(value: object) -> bool:
    """True only for a string that is a safe session id; any other type is not one."""
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


# A model is an alias ("sonnet") or a full id. It becomes an argv entry, so it never starts with "-" (D18).
MODEL_PATTERN: Final = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]{0,63}")
EFFORTS: Final = ("low", "medium", "high", "xhigh", "max")


def is_model(value: object) -> bool:
    """True only for a string that can name a model without reading as a flag."""
    return isinstance(value, str) and MODEL_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class SpawnOptions:
    """What the spawning caller chose for the new session. None leaves it to the owner's settings (D18)."""

    model: str | None = None
    effort: str | None = None
    subagent_model: str | None = None


NO_OPTIONS: Final = SpawnOptions()

# The value a removal refusal names to delete work that exists nowhere else: a commit and the worktree's id (D17).
# It goes back as an argv entry, so it starts with a hexadecimal digit and holds no space.
DISCARD_PATTERN: Final = re.compile(r"[0-9a-f]{40,64}@[A-Za-z0-9_-]{1,64}")
NO_DISCARD: Final = "this harness keeps no unpushed work to discard; pass no discard_unpushed"


def is_discard_value(value: object) -> bool:
    """True only for a string in the form a refusal over unpushed commits names."""
    return isinstance(value, str) and DISCARD_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class Spawned:
    id: str
    name: str | None


@dataclass(frozen=True)
class Identity:
    """Who the calling session is, as the harness environment reports it."""

    session_id: str  # the full session id
    id: str | None  # the short id, or None when the environment does not carry it


@dataclass(frozen=True)
class Session:
    id: str | None  # the short id every management command takes; None for a foreground session, which none of them reaches (#47)
    session_id: str  # the full session id, as hooks report it
    name: str
    cwd: str
    kind: str  # passed through; new kinds must not break listing
    state: str | None  # passed through, not an enum on purpose; None where the row has no string state, and for a foreground session
    status: str | None = None  # absent for sessions that are no longer running
    pid: int | None = None
    started_at: int | None = None

    @classmethod
    def from_agent(cls, row: dict[str, Any]) -> Session | None:
        """Build a Session from one `agents --json` row, or None if the row names no session.

        A row with a usable `id` is a background session. A row without one but
        with a `sessionId` is a foreground session, which the listing shows with no
        `id` and no `state` (observed on 2.1.309): it comes back read-only, with
        `id` and `state` None and the rest as reported, so a peer can find its
        name (#47). Its `state` is None even if a row reports one, since the
        background stack whose state that is does not hold the session. A row
        with neither names nothing and is dropped.
        """
        short, session_id = _text(row, "id"), _text(row, "sessionId")
        if not short and not session_id:
            return None
        pid, started = row.get("pid"), row.get("startedAt")
        return cls(
            id=short or None,
            session_id=session_id,
            name=_text(row, "name"),
            cwd=_text(row, "cwd"),
            kind=_text(row, "kind"),
            state=row["state"] if short and isinstance(row.get("state"), str) else None,
            status=row["status"] if isinstance(row.get("status"), str) else None,
            pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else None,
            started_at=started if isinstance(started, int) and not isinstance(started, bool) else None,
        )


@dataclass(frozen=True)
class Turn:
    """One turn of a session as `peek` shows it (D20): what started it, what the session answered, and the tools it named."""

    origin: str | None  # "user" for a prompt, "peer" for a message from another session; None where the start is out of reach
    prompt: str | None  # None where the start is out of reach
    reply: str  # the session's text answers, joined; "" when it has said nothing yet
    tools: tuple[str, ...]  # the names of the tools it used, each once, in the order first used
    at: str | None  # the timestamp of the turn's last record, as the harness wrote it


@dataclass(frozen=True)
class Peeked:
    """What `peek` returns: the session's row and its last turns, oldest first."""

    session: Session
    turns: tuple[Turn, ...]
    problem: str | None = None  # why no turn could be read; None when the transcript was read, even one with no turn in it


def _text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""
