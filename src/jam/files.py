"""Two small checks on paths that someone else may have planted: a bounded read of a file, and whether a directory is a real one. Stdlib only."""

from __future__ import annotations

import os
import stat
from typing import Optional, Union


def read_small(path: str, limit: int) -> Optional[bytes]:
    """The content of the regular file at `path`, or None when it is not a regular file or holds more than `limit` bytes.

    The file is opened without following a link and without waiting, so a named
    pipe planted under the name cannot hold the caller. An OSError, a missing
    file included, is not hidden: the caller decides what an absence means.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as handle:  # buffered, so one call reads up to the limit even if the OS hands it over in pieces
            data = handle.read(limit + 1)
    finally:
        os.close(fd)
    return data if len(data) <= limit else None


def real_directory(path: Union[str, os.PathLike[str]]) -> bool:
    """True when `path` is itself a directory, and False for a link, even one that leads to a directory, and for anything else, including a path that is not there.

    Only the last level is looked at: a link among its ancestors is followed. The
    answer is one `lstat` taken before the caller uses the directory, so a link
    planted in the gap between the two is not seen. That gap is accepted (time of
    check to time of use): the places this guards are inside the user's own plugin
    data directory, where only the same user can plant a link. Never raises for a path.
    """
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except (OSError, ValueError):  # absent, not to be looked at, or a NUL in the name
        return False
