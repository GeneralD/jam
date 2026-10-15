"""The service that composes a harness with the registry. Stdlib only.

The harness decides which sessions exist; the registry only annotates them. A
registry failure therefore never hides a harness result: after a spawn the
session id is always returned, and a listing degrades to un-annotated rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import RegistryError
from .registry import Record, Registry, spawned_marked
from .session import Session, Spawned


class Harness(Protocol):
    def spawn(
        self, cwd: str | Path, prompt: str, name: str | None = None, permission_mode: str | None = None
    ) -> Spawned: ...

    def list(self, include_exited: bool = False, cwd: str | None = None) -> list[Session]: ...

    def stop(self, session_id: str) -> Session | None: ...


@dataclass(frozen=True)
class SpawnResult:
    spawned: Spawned
    problem: str | None  # set when the session started but jam could not note it


@dataclass(frozen=True)
class Listed:
    session: Session
    record: Record | None  # None means "unknown", not "not spawned by jam"


@dataclass(frozen=True)
class Listing:
    sessions: tuple[Listed, ...]
    problem: str | None  # why the registry could not be used; harness failures raise instead


def joined(sessions: Sequence[Session], records: Mapping[str, Record | None]) -> tuple[Listed, ...]:
    """Harness rows in harness order, each with its note if one exists. Notes without a row are dropped."""
    return tuple(Listed(session, records.get(session.id)) for session in sessions)


def failure_reason(exc: Exception) -> str:
    """Only a RegistryError may carry its message; any other message could hold a path."""
    return str(exc) if isinstance(exc, RegistryError) else type(exc).__name__


class Jam:
    def __init__(self, harness: Harness, registry: Registry):
        self._harness = harness
        self._registry = registry

    def spawn(
        self, cwd: str | Path, prompt: str, name: str | None = None, permission_mode: str | None = None
    ) -> SpawnResult:
        """Start a session, then note that jam started it.

        Harness failures propagate and nothing is noted. Once the session exists,
        no registry failure may hide its id, and the registry lock is never held
        while the harness runs.
        """
        spawned = self._harness.spawn(cwd, prompt, name, permission_mode)
        return SpawnResult(spawned, self._recorded(spawned.id))

    def list(self, include_exited: bool = False, cwd: str | None = None) -> Listing:
        sessions = self._harness.list(include_exited, cwd)
        try:
            records = {session.id: self._registry.record(session.id) for session in sessions}
        except RegistryError as exc:
            return Listing(joined(sessions, {}), str(exc))
        return Listing(joined(sessions, records), None)

    def stop(self, session_id: str) -> Session | None:
        # A stopped session stays in the full listing, so its note stays true.
        return self._harness.stop(session_id)

    def _recorded(self, session_id: str) -> str | None:
        try:
            self._registry.update(session_id, spawned_marked)
        except Exception as exc:  # noqa: BLE001
            # Deliberately broad, and only here: the worker already exists and the
            # return value is the only way its id reaches the caller. A bug in the
            # registry must not turn a successful spawn into an exception, because
            # the caller would then respawn. The exception type is kept in the text.
            return f"could not record {session_id}: {failure_reason(exc)}"
        return None
