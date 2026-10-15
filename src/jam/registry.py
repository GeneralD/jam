"""Jam's own notes about sessions: one small JSON file per session.

The harness is the source of truth for which sessions exist. This registry only
adds what the harness cannot tell us (today: which sessions jam spawned), keyed
by the harness's short session id. It is disposable: every reader treats a
missing or damaged note as "no note", and only the age of a file decides when it
is swept.

macOS and Linux only (it uses ``fcntl.flock``) and the data directory must be on
a local filesystem, where ``flock`` is reliable. Only ``update`` takes the lock;
reads, ``remove`` and ``prune`` never do, so a hook can call them within a tight
time budget.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .errors import InvalidRequest, RegistryError
from .session import is_id

SESSIONS_DIR: Final = "sessions-v1"
LOCK_NAME: Final = "sessions-v1.lock"
STALE_AFTER: Final = 30 * 24 * 3600.0
DEFAULT_LOCK_TIMEOUT: Final = 0.5
MAX_BYTES: Final = 64 * 1024
_POLL_SECONDS: Final = 0.01


@dataclass(frozen=True)
class Record:
    spawned: bool = False

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Record:
        return cls(spawned=raw.get("spawned") is True)


def spawned_marked(raw: dict[str, Any]) -> dict[str, Any]:
    return {**raw, "spawned": True}


def encoded(raw: dict[str, Any]) -> bytes:
    return (json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def decoded(data: bytes) -> dict[str, Any] | None:
    """The JSON object in `data`, or None for anything else (damaged, deeply nested, not an object)."""
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        return None
    return value if isinstance(value, dict) else None


def expired(mtime: float, now: float, max_age: float) -> bool:
    """True when a file is older than `max_age`; a modification time in the future never expires."""
    return now - mtime > max_age


class Registry:
    def __init__(self, data_dir: str | os.PathLike[str], lock_timeout: float = DEFAULT_LOCK_TIMEOUT):
        """Remember where the notes live. Does no I/O: directories appear on the first update."""
        if not isinstance(data_dir, (str, os.PathLike)) or not Path(data_dir).is_absolute():
            raise InvalidRequest("the registry data directory must be an absolute path")
        self._root = Path(data_dir)
        self._dir = self._root / SESSIONS_DIR
        self._lock_timeout = _seconds(lock_timeout)

    def record(self, key: str) -> Record | None:
        """The note for `key`, or None when there is none, it is damaged, or the key is not an id.

        An unreadable file (permissions, I/O error) is a RegistryError, not an absence.
        """
        if not is_id(key):
            return None
        raw = self._loaded(self._path(key))
        return None if raw is None else Record.from_json(raw)

    def update(self, key: str, change: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """Read the note, apply the pure function `change`, and write the result atomically.

        Unknown keys in the stored note reach `change` untouched, so a newer
        writer's fields survive an older one. Writers should only add their own keys.
        """
        key = self._valid_key(key)
        path = self._path(key)
        try:
            # One call per level: makedirs applies `mode` to the last level only, so
            # the data directory would otherwise follow the umask. Ancestors above it
            # belong to the platform and are left alone.
            for directory in (self._root, self._dir):
                os.makedirs(directory, mode=0o700, exist_ok=True)
        except OSError as exc:
            raise _unavailable("create", exc) from None
        with self._locked():
            data = encoded(change(dict(self._loaded(path) or {})))
            self._written(key, path, data)

    def remove(self, key: str) -> None:
        """Delete the note if there is one. Takes no lock; a racing update may bring it back, which is harmless."""
        path = self._path(self._valid_key(key))
        try:
            os.unlink(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise _unavailable("remove from", exc) from None

    def prune(self, max_age: float = STALE_AFTER, now: float | None = None) -> int:
        """Delete notes (and orphaned temp files) older than `max_age`; return how many went."""
        current = time.time() if now is None else now
        try:
            with os.scandir(self._dir) as scan:
                entries = list(scan)
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise _unavailable("scan", exc) from None
        return sum(_unlinked(entry.path) for entry in entries if _prunable(entry, current, max_age))

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    @staticmethod
    def _valid_key(key: str) -> str:
        if not is_id(key):
            raise InvalidRequest(f"invalid session id: {key!r}")
        return key

    def _loaded(self, path: Path) -> dict[str, Any] | None:
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _unavailable("read", exc) from None
        return decoded(data) if len(data) <= MAX_BYTES else None

    def _written(self, key: str, path: Path, data: bytes) -> None:
        try:
            fd, temp = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=self._dir)
        except OSError as exc:
            raise _unavailable("write", exc) from None
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temp, path)
        except OSError as exc:
            _discarded(temp)
            raise _unavailable("write", exc) from None
        except BaseException:
            _discarded(temp)
            raise

    @contextmanager
    def _locked(self) -> Iterator[None]:
        # A fresh descriptor per call: flock excludes other descriptors even in
        # the same process, which a shared one would not.
        try:
            fd = os.open(self._root / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            raise _unavailable("open the lock of", exc) from None
        try:
            _acquired(fd, time.monotonic() + self._lock_timeout)
            yield
        finally:
            os.close(fd)  # closing releases the lock, also if the holder dies


def _seconds(value: object) -> float:
    """`value` as a finite, non-negative number of seconds; NaN and infinity would never reach a deadline."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequest("the lock timeout must be a non-negative number of seconds")
    try:
        seconds = float(value)
    except OverflowError:  # an int too large for a float
        raise InvalidRequest("the lock timeout must be a non-negative number of seconds") from None
    if not math.isfinite(seconds) or seconds < 0:
        raise InvalidRequest("the lock timeout must be a non-negative number of seconds")
    return seconds


def _acquired(fd: int, deadline: float) -> None:
    """Take the exclusive lock, polling until `deadline`. The one imperative loop here:
    flock has no timeout of its own and a blocking wait would hang a hook."""
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise RegistryError("session registry is busy") from None
            time.sleep(_POLL_SECONDS)
        except OSError as exc:
            raise _unavailable("lock", exc) from None


def _prunable(entry: os.DirEntry[str], now: float, max_age: float) -> bool:
    name = entry.name
    is_note = name.endswith(".json") and is_id(name[: -len(".json")])
    is_orphan_temp = name.startswith(".") and name.endswith(".tmp")
    if not (is_note or is_orphan_temp):
        return False
    try:
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    return not entry.is_dir(follow_symlinks=False) and expired(info.st_mtime, now, max_age)


def _unlinked(path: str) -> int:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise _unavailable("prune", exc) from None
    return 1


def _discarded(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _unavailable(action: str, exc: OSError) -> RegistryError:
    """A RegistryError that names the action and the OS reason, never a path."""
    return RegistryError(f"cannot {action} the session registry: {exc.strerror or 'OS error'}")
