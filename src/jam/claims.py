"""The guard's state files: create-once deny claims, hour slots, and the readers of two marks other code writes.

Everything lives in one directory under the plugin data directory. A claim is an
empty file created with `O_EXCL`, so of any number of racing creators exactly one
wins, with no lock, no polling and no read-modify-write. Nothing is ever
updated. The files are disposable: a missing one only means one more nudge, and
only the age of a file decides when it is swept (see `is_claim_name`).

Nothing here raises. A data directory that is missing, relative or not writable,
and an id or key that is not safe in a file name, all answer "no claim" or "no
record", which the guard reads as "stay quiet": a guard that cannot remember
what it has said must not speak.

macOS and Linux only. Stdlib only and cheap to import: this module is on the path
of every edit.
"""

from __future__ import annotations

import os
import re
from typing import Final, Optional

from .files import read_small
from .session import ID_PATTERN, is_id

STATE_DIR: Final = "guard-v1"
SLOTS_PER_HOUR: Final = 20  # the machine-wide limit of denies in one clock hour
MAX_RECORD: Final = 4096 + 1  # a path of at most 4096 bytes and its line feed

_KEY = re.compile(r"[0-9a-f]{16}")
# The fixed-width suffix is what keeps a session id with dots unambiguous: ids admit dots, the key never has any.
_CLAIM_NAME = re.compile(rf"denied\.(?:{ID_PATTERN.pattern})\.[0-9a-f]{{16}}|slot\.[0-9]+\.[0-9]{{1,2}}")


def state_dir(data_dir: object) -> Optional[str]:
    """The guard's directory below an absolute data directory, or None for anything else (a relative path would follow the working directory)."""
    path = os.fspath(data_dir) if isinstance(data_dir, (str, os.PathLike)) else None
    if not isinstance(path, str) or "\0" in path or not os.path.isabs(path):
        return None
    return os.path.join(path, STATE_DIR)


def is_claim_name(name: object) -> bool:
    """True for the name of a deny claim or an hour slot: the files that pile up and are swept by age."""
    return isinstance(name, str) and _CLAIM_NAME.fullmatch(name) is not None


class Claims:
    def __init__(self, data_dir: object):
        """Remember where the files live. Does no I/O: directories appear on the first claim, and an unusable `data_dir` makes every method answer "nothing"."""
        self._dir = state_dir(data_dir)

    def worker_marked(self, session_id: object) -> bool:
        """True when the session carries the mark of a session that was started on purpose. One lstat; written by other code."""
        return self._exists(_named("worker", session_id))

    def start_recorded(self, session_id: object) -> Optional[str]:
        """The directory the session started in, as recorded, or None when there is no complete record of an absolute path.

        A record counts only when it ends with its line feed, so a half-written
        one reads as absent. Written by other code.
        """
        name = _named("start", session_id)
        if self._dir is None or name is None:
            return None
        try:
            return _path_line(read_small(os.path.join(self._dir, name), MAX_RECORD))
        except OSError:
            return None

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

    def _exists(self, name: Optional[str]) -> bool:
        if self._dir is None or name is None:
            return False
        try:
            os.lstat(os.path.join(self._dir, name))
        except OSError:  # absent, or not to be looked at: either way nothing is known to exist
            return False
        return True

    def _claimed(self, names: list[str]) -> bool:
        """Create the first of `names` that does not exist yet. True only when this call created it."""
        if self._dir is None or not names:
            return False
        directory = self._ensured(self._dir)
        if directory is None:
            return False
        for name in names:
            outcome = _created(os.path.join(directory, name))
            if outcome is not False:  # created, or failed in a way that makes the next name no better
                return outcome is True
        return False

    @staticmethod
    def _ensured(directory: str) -> Optional[str]:
        # One call per level: makedirs applies `mode` to the last level only, so the data directory
        # would otherwise follow the umask. Ancestors above it belong to the platform and are left alone.
        try:
            for level in (os.path.dirname(directory), directory):
                os.makedirs(level, mode=0o700, exist_ok=True)
        except OSError:
            return None
        return directory


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


def _created(path: str) -> Optional[bool]:
    """Create `path` as an empty private file: True if this call made it, False if it was there, None if it cannot be made."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    except OSError:
        return None
    os.close(fd)
    return True


def _path_line(data: Optional[bytes]) -> Optional[str]:
    """The absolute path in `data` when it is exactly one path and its line feed, else None."""
    if data is None or not data.endswith(b"\n") or b"\0" in data:
        return None
    path = os.fsdecode(data[:-1])
    return path if os.path.isabs(path) else None
