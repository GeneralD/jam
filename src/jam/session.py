"""The harness-neutral view of a session. Stdlib only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
