"""Small file-system helpers for paths that someone else may have planted: a bounded read of a file, whether a directory is a real one, and the creation of private files and directories. Stdlib only."""

from __future__ import annotations

import contextlib
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


def _make_private(level: str) -> None:
    """Make `level` a directory at mode 0700 when this call makes it; one that is there already, a link included, is left alone.

    mkdir is atomic, so of any number of racing creators exactly one sees the new directory and only that one chmods it: the umask clears bits from the mode given to mkdir.
    """
    try:
        os.mkdir(level, 0o700)
    except FileExistsError:
        return
    os.chmod(level, 0o700)


def ensured(directory: str) -> Optional[str]:
    """Create `directory` and its parent if needed, mode 0700 whatever the umask, and return it when it is a real directory; None when it cannot be made or is a link.

    Each level this call makes is chmodded to 0700, since the umask clears bits from
    the mode mkdir is given. Ancestors above the parent belong to the platform: they are made at the
    umask's mode and left alone.
    """
    parent = os.path.dirname(directory)
    try:
        os.makedirs(os.path.dirname(parent), exist_ok=True)
        for level in (parent, directory):
            _make_private(level)
    except OSError:
        return None
    return directory if real_directory(directory) else None  # makedirs accepts a link to a directory; nothing is made through one


def created(path: str, data: bytes = b"") -> Optional[bool]:
    """Create `path` as a private file (mode 0600 whatever the umask) holding `data`: True if this call made it, False if it was there already (a link included), None if it cannot be made, and then no file is left behind.

    The file is opened with O_EXCL and O_NOFOLLOW, so of any number of racing creators exactly one gets True,
    and a link planted under the name is never followed.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    except OSError:
        return None
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)  # the open applies the umask, which may have cleared bits
            handle.write(data)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(path)  # a half-written file must not stand for the record: the next attempt starts from nothing
        return None
    return True


def absolute_path(value: object) -> Optional[str]:
    """`value` as an absolute path string the file system can name, or None: no NUL, and no unpaired surrogate, which has no encoding. A path-like object is read as its string; anything else is None."""
    path = os.fspath(value) if isinstance(value, (str, os.PathLike)) else None
    if not isinstance(path, str) or "\0" in path or not os.path.isabs(path):
        return None
    try:
        os.fsencode(path)
    except ValueError:  # UnicodeEncodeError: a lone surrogate that the file system's encoding cannot carry
        return None
    return path


def subdirectory(data_dir: object, name: str) -> Optional[str]:
    """`name` below an absolute data directory, or None for anything else (a relative path would follow the working directory)."""
    base = absolute_path(data_dir)
    return None if base is None else os.path.join(base, name)
