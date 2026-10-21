"""The spawn tickets: a ticket that `spawn` leaves before the harness runs, so that the first session start in the spawned directory can be told apart from any other.

A ticket is an empty private file in the `pending-v1` directory, named
`<dir16>.<nonce16>`. `dir16` is the first sixteen hex digits of the SHA-256 of the
real path the session starts in, and `nonce16` is random, so tickets never collide.
`spawn` writes one before the harness runs and withdraws it if the harness raises.
The first session start in that directory that has no mark yet claims the freshest
ticket of it by moving the ticket to the worker mark of the session (any session
start can claim, not only a spawned worker; the harness adapter decides which starts
continue or copy a session already started and so take no ticket). A ticket is
claimed only within 300 seconds of its writing, and `prune` sweeps any ticket older
than thirty days.

Stdlib only. `hashlib` and `secrets` are imported inside the functions that need
them, because the start of every session runs this module.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import re
import stat
from typing import Final, Optional

from .claims import Claims
from .errors import RegistryError
from .files import absolute_path, created, ensured, real_directory, subdirectory
from .session import is_id

PENDING_DIR: Final = "pending-v1"
FRESH_SECONDS: Final = 300.0  # the age a ticket may have and still be claimed
MAX_CANDIDATES: Final = 8  # the moves one session start may try
SCAN_LIMIT: Final = 1024  # the entries of the ticket directory one session start may look at
NONCE_BYTES: Final = 8
NOT_WRITTEN: Final = "the spawn ticket could not be written"

_NAME = re.compile(r"[0-9a-f]{16}\.[0-9a-f]{16}")


def dir_key(cwd: object) -> Optional[str]:
    """The first sixteen hex digits of the SHA-256 of the real path of `cwd`, or None when `cwd` is not an absolute path the file system can name.

    The same directory gives the same key when both name it the same way after realpath, through a link or not. realpath keeps
    letter case, so on a case-insensitive file system two spellings that differ only in case give two keys, which costs a lost mark (D14).
    """
    path = absolute_path(cwd)
    if path is None:
        return None
    import hashlib  # imported here: the start of every session runs this module

    return hashlib.sha256(os.fsencode(os.path.realpath(path))).hexdigest()[:16]


def is_ticket_name(name: object) -> bool:
    """True for the name of a ticket: sixteen lower-case hex digits, a dot and sixteen more."""
    return isinstance(name, str) and _NAME.fullmatch(name) is not None


def pending_dir(data_dir: object) -> Optional[str]:
    """The ticket directory below an absolute data directory, or None for anything else (a relative path would follow the working directory)."""
    return subdirectory(data_dir, PENDING_DIR)


def candidates(data_dir: object, cwd: object, now: float) -> list[str]:
    """The tickets of the directory `cwd` that a session start may claim, freshest first.

    At most `MAX_CANDIDATES`, each written no more than `FRESH_SECONDS` before
    `now`, found among at most `SCAN_LIMIT` entries of the ticket directory. A
    ticket dated after `now` counts as fresh.
    """
    directory = pending_dir(data_dir)
    key = dir_key(cwd)
    if directory is None or key is None or not real_directory(directory):
        return []
    return [path for _, path in sorted(_aged(directory, key, now))[:MAX_CANDIDATES]]


def claim_mark(data_dir: object, session_id: object, cwd: object, now: float) -> bool:
    """Turn the freshest ticket of `cwd` into the worker mark of `session_id`: True only when this call did so.

    Nothing is claimed when the session has its mark already, and nothing is listed
    or claimed for a session id that is not valid. A ticket that another session
    takes first is passed over, and any other failure ends the attempts after one move.
    """
    book = Claims(data_dir)
    if not is_id(session_id) or book.worker_marked(session_id):
        return False
    outcomes = (book.mark_worker(session_id, path) for path in candidates(data_dir, cwd, now))
    return next((outcome for outcome in outcomes if outcome is not False), False) is True


class Tickets:
    def __init__(self, data_dir: object):
        """Remember where the tickets go. Does no I/O: the directory appears with the first ticket, and an unusable `data_dir` makes `issue` answer None."""
        self._dir = pending_dir(data_dir)

    def issue(self, cwd: object) -> Optional[str]:
        """Create the ticket of a session that will start in `cwd` and return its path. None when there is no usable data directory.

        Raises RegistryError, with a message that names no path, when a data
        directory is usable but the ticket cannot be written: `cwd` is not an
        absolute path, the ticket directory is not a real directory, or the file
        cannot be made.
        """
        if self._dir is None:
            return None
        return _written(self._dir, dir_key(cwd))

    def withdraw(self, ticket: str) -> None:
        """Remove the ticket at `ticket` if it is still there. Only a failure other than its absence is raised."""
        with contextlib.suppress(FileNotFoundError):
            os.unlink(ticket)


def _written(directory: str, key: Optional[str]) -> str:
    """Create a ticket for `key` in `directory`, made when it is missing, and return its path; RegistryError when that is not possible."""
    made = ensured(directory)
    path = None if made is None or key is None else os.path.join(made, f"{key}.{_nonce()}")
    if path is None or created(path) is not True:
        raise RegistryError(NOT_WRITTEN)
    return path


def _nonce() -> str:
    import secrets  # imported here: the start of every session runs this module

    return secrets.token_hex(NONCE_BYTES)


def _aged(directory: str, key: str, now: float) -> list[tuple[float, str]]:
    """The age and the path of each fresh ticket of `key` among the first `SCAN_LIMIT` entries of `directory`; empty when the directory cannot be read."""
    try:
        with os.scandir(directory) as scan:
            entries = list(itertools.islice(scan, SCAN_LIMIT))
    except OSError:
        return []
    aged = [(_age(entry, key, now), os.path.join(directory, entry.name)) for entry in entries]
    return [(age, path) for age, path in aged if age is not None]


def _age(entry: os.DirEntry, key: str, now: float) -> Optional[float]:
    """How many seconds before `now` the entry was written, when it is a regular ticket of `key` no older than FRESH_SECONDS; None otherwise.

    A link, a directory and any other name are none of these.
    """
    if not is_ticket_name(entry.name) or not entry.name.startswith(key + "."):
        return None
    try:
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    age = now - info.st_mtime
    return age if stat.S_ISREG(info.st_mode) and age <= FRESH_SECONDS else None
