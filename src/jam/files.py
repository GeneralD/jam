"""A bounded read of a small file that someone else may have planted. Stdlib only."""

from __future__ import annotations

import os
import stat
from typing import Optional


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
