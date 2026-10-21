"""The guard's state files: create-once deny claims, hour slots, the start record of a session and its worker mark.

Everything lives in one directory under the plugin data directory. A claim is an
empty file created with `O_EXCL`, so of any number of racing creators exactly one
wins, with no lock, no polling and no read-modify-write. Nothing is ever
updated. The files are disposable: a missing one only means one more nudge, and
only the age of a file decides when it is swept (see `is_state_name`).

The start record is written once per session by the session start, and the
worker mark is made by renaming a spawn ticket (see `tickets`) into place. The
guard reads both as facts about the session.

Nothing here raises. A data directory that is missing, relative or not writable,
a state directory that is not a real directory (a link in its place would carry
every claim, every record and every read to wherever it points), and an id or key
that is not safe in a file name, all answer "no claim" or "no record", which the
guard reads as "stay quiet": a guard that cannot remember what it has said must
not speak. The data directory above the state directory belongs to the platform
and is not checked; the check that guards the state directory is `files.real_directory`.

macOS and Linux only. Stdlib only and cheap to import: this module is on the path
of every edit.
"""

from __future__ import annotations

import os
import re
from typing import Final, Optional

from .files import absolute_path, created, ensured, read_small, real_directory, subdirectory
from .session import ID_PATTERN, is_id

STATE_DIR: Final = "guard-v1"
SLOTS_PER_HOUR: Final = 20  # the machine-wide limit of denies in one clock hour
MAX_RECORD: Final = 4096  # the start record in all: a path of at most 4095 bytes and its line feed

_KEY = re.compile(r"[0-9a-f]{16}")
# The fixed-width suffix is what keeps a session id with dots unambiguous: ids admit dots, the key never has any.
_CLAIM_NAME = re.compile(rf"denied\.(?:{ID_PATTERN.pattern})\.[0-9a-f]{{16}}|slot\.[0-9]+\.[0-9]{{1,2}}")
_MARK_NAME = re.compile(rf"(?:start|worker)\.(?:{ID_PATTERN.pattern})")


def state_dir(data_dir: object) -> Optional[str]:
    """The guard's directory below an absolute data directory, or None for anything else (a relative path would follow the working directory)."""
    return subdirectory(data_dir, STATE_DIR)


def is_state_name(name: object) -> bool:
    """True for the name of a file the guard keeps: a deny claim, an hour slot, a start record or a worker mark. The sweep removes these by age."""
    return isinstance(name, str) and (_CLAIM_NAME.fullmatch(name) is not None or _MARK_NAME.fullmatch(name) is not None)


class Claims:
    def __init__(self, data_dir: object):
        """Remember where the files live. Does no I/O: directories appear on the first write, and an unusable `data_dir` makes every method answer "nothing"."""
        self._dir = state_dir(data_dir)

    def worker_marked(self, session_id: object) -> bool:
        """True when the session carries the mark of a session that took a spawn ticket. Two lstats: one of the state directory, one of the mark."""
        return self._exists(_named("worker", session_id))

    def start_recorded(self, session_id: object) -> Optional[str]:
        """The directory the session started in, as recorded, or None when there is no complete record of an absolute path.

        A record counts only when it ends with its line feed, so a half-written
        one reads as absent. Written by `record_start`.
        """
        name = _named("start", session_id)
        directory = None if name is None else self._looked_in()
        if directory is None or name is None:
            return None
        try:
            return _path_line(read_small(os.path.join(directory, name), MAX_RECORD))
        except OSError:
            return None

    def record_start(self, session_id: object, directory: object) -> bool:
        """Create the start record of the session: the real path of `directory` and a line feed. True only for the call that wrote it.

        A record that is there already is kept as it is. A directory that is not an
        absolute path the file system can name, or whose record would not fit in `MAX_RECORD` bytes, writes
        nothing and creates nothing, and so does an id that is not safe in a file name.
        """
        name = _named("start", session_id)
        record = _record(directory)
        return name is not None and record is not None and self._claimed([name], record)

    def mark_worker(self, session_id: object, source: object) -> Optional[bool]:
        """Rename the spawn ticket at `source` to the worker mark of the session.

        True when it was renamed. False when the ticket is gone, because another
        session took it first. None when nothing could be done: a bad id or source,
        a state directory that cannot be used, or any other failure.
        """
        name = _named("worker", session_id)
        if name is None or absolute_path(source) is None:
            return None
        directory = self._ensured()
        if directory is None:
            return None
        try:
            os.rename(source, os.path.join(directory, name))
        except FileNotFoundError:
            return False
        except OSError:
            return None
        return True

    def pair_claimed(self, session_id: object, key: object) -> bool:
        """True when this session has already been denied for the repository with this key. A read; it claims nothing."""
        return self._exists(_pair(session_id, key))

    def claim_pair(self, session_id: object, key: object) -> bool:
        """Take the one claim of a (session, repository) pair. True only for the single caller that created it.

        False means the pair was taken already, by this process, a parallel one or
        an earlier run of the same session, or that no claim can be made at all.
        """
        name = _pair(session_id, key)
        return name is not None and self._claimed([name])

    def throttled(self, hour: object) -> bool:
        """True when the last slot of the clock `hour` is taken, which is when all of them are, since they are taken in order."""
        names = _slots(hour)
        return self._exists(names[-1] if names else None)

    def claim_slot(self, hour: object) -> bool:
        """Take the next free one of the SLOTS_PER_HOUR slots of the clock `hour` (whole hours since the epoch). False when none is free or none can be taken."""
        return self._claimed(_slots(hour))

    def _looked_in(self) -> Optional[str]:
        """The state directory when there is one and it is a real directory, else None: a link in its place reads as an absence."""
        return self._dir if self._dir is not None and real_directory(self._dir) else None

    def _exists(self, name: Optional[str]) -> bool:
        directory = None if name is None else self._looked_in()
        if directory is None or name is None:
            return False
        try:
            os.lstat(os.path.join(directory, name))
        except OSError:  # absent, or not to be looked at: either way nothing is known to exist
            return False
        return True

    def _claimed(self, names: list[str], data: bytes = b"") -> bool:
        """Create the first of `names` that does not exist yet, holding `data`. True only when this call created it."""
        if not names:
            return False
        directory = self._ensured()
        if directory is None:
            return False
        outcomes = (created(os.path.join(directory, name), data) for name in names)
        return next((outcome for outcome in outcomes if outcome is not False), False) is True  # a failure makes the next name no better

    def _ensured(self) -> Optional[str]:
        """The state directory, made when it is missing; None when there is none that is a real directory."""
        return None if self._dir is None else ensured(self._dir)


def _named(kind: str, session_id: object) -> Optional[str]:
    return f"{kind}.{session_id}" if is_id(session_id) else None


def _pair(session_id: object, key: object) -> Optional[str]:
    if not is_id(session_id) or not isinstance(key, str) or _KEY.fullmatch(key) is None:
        return None
    return f"denied.{session_id}.{key}"


def _slots(hour: object) -> list[str]:
    """The names of the slots of the clock `hour` in the order they are taken; none for an hour that is not a whole number since the epoch."""
    if not isinstance(hour, int) or isinstance(hour, bool) or hour < 0:
        return []
    return [f"slot.{hour}.{number}" for number in range(SLOTS_PER_HOUR)]


def _record(directory: object) -> Optional[bytes]:
    """The start record for `directory`: its real path and a line feed, or None when it is not an absolute path the file system can name or would not fit in MAX_RECORD bytes."""
    path = absolute_path(directory)
    if path is None:
        return None
    record = os.fsencode(os.path.realpath(path)) + b"\n"
    return record if len(record) <= MAX_RECORD else None


def _path_line(data: Optional[bytes]) -> Optional[str]:
    """The absolute path in `data` when it is exactly one path and its line feed, else None."""
    if data is None or not data.endswith(b"\n") or b"\0" in data:
        return None
    path = os.fsdecode(data[:-1])
    return path if os.path.isabs(path) else None
