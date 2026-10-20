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
    id: str  # the short id every management command takes
    session_id: str  # the full session id, as hooks report it
    name: str
    cwd: str
    kind: str  # passed through; new kinds must not break listing
    state: str  # passed through; not an enum on purpose
    status: str | None = None  # absent for sessions that are no longer running
    pid: int | None = None
    started_at: int | None = None

    @classmethod
    def from_agent(cls, row: dict[str, Any]) -> Session | None:
        """Build a Session from one `agents --json` row, or None if it has no usable id."""
        session_id = row.get("id")
        if not isinstance(session_id, str) or not session_id:
            return None
        pid, started = row.get("pid"), row.get("startedAt")
        return cls(
            id=session_id,
            session_id=_text(row, "sessionId"),
            name=_text(row, "name"),
            cwd=_text(row, "cwd"),
            kind=_text(row, "kind"),
            state=_text(row, "state"),
            status=row["status"] if isinstance(row.get("status"), str) else None,
            pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else None,
            started_at=started if isinstance(started, int) and not isinstance(started, bool) else None,
        )


def _text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""
