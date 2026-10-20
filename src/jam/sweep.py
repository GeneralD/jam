"""An age sweep for a directory of disposable files: remove the old regular files whose names a predicate accepts.

It never raises for a reason on disk. A directory that is missing or cannot be
listed has nothing to sweep, an entry that vanishes is skipped, and any other
error ends the sweep with what it had done so far, because the files are only
clutter and the next run will try again. Two bounds keep it cheap on a hook's
tight budget: a cap on how many entries are looked at, and a deadline.

Stdlib only, apart from the age rule it shares with the registry.
"""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Callable
from itertools import islice
from typing import Optional

from .registry import expired


def swept(
    directory: str,
    accept: Callable[[str], bool],
    max_age: float,
    now: float,
    limit: int,
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Delete the regular files in `directory` that `accept` takes by name and that are older than `max_age`; return how many went.

    `now` is wall-clock time, the one file times are compared with, and a file
    dated in the future never expires. `deadline` is on `clock` (monotonic by
    default) and is checked before each entry. Links, directories and every other
    kind of entry are left alone, whatever their name and age.
    """
    removed = 0
    for entry in _listed(directory, limit):
        if clock() >= deadline:
            break
        outcome = _removed(entry, accept, max_age, now)
        if outcome is None:
            break
        removed += outcome
    return removed


def _listed(directory: str, limit: int) -> list[os.DirEntry[str]]:
    """At most `limit` entries of `directory`; none when it cannot be listed."""
    try:
        with os.scandir(directory) as scan:
            return list(islice(scan, limit))
    except OSError:
        return []


def _removed(entry: os.DirEntry[str], accept: Callable[[str], bool], max_age: float, now: float) -> Optional[int]:
    """1 if the entry was removed, 0 if it was left or already gone, None if something went wrong that ends the sweep."""
    if not accept(entry.name):
        return 0
    try:
        info = entry.stat(follow_symlinks=False)
    except FileNotFoundError:  # removed since the listing
        return 0
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or not expired(info.st_mtime, now, max_age):
        return 0
    try:
        os.unlink(entry.path)
    except FileNotFoundError:
        return 0
    except OSError:
        return None
    return 1
