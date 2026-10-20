"""Which repository a path belongs to, found by reading files, and whether git ignores the path.

Identity never starts a process: it walks up from the path and reads the `.git`
entry it meets. `ignored` is the one place that does start one, and it runs only
once everything cheaper has not settled the question. Stdlib only, and
`hashlib` and `subprocess` are imported where they are used, because both cost
start-up time on the path every edit takes.

Every function is total over what a hostile or broken tree can throw at it:
anything unreadable, oversized or malformed is "not a repository" or "unknown",
never an error. Only a path that is not a string, not absolute or holding NUL is
refused up front, and that is answered with None too.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from itertools import islice
from typing import Any, Final, Optional

from .files import read_small

MAX_LEVELS: Final = 64  # directories looked at on the way up, the start included
MAX_READ: Final = 4096
IGNORE_TIMEOUT: Final = 1.0
GITDIR_PREFIX: Final = b"gitdir:"


@dataclass(frozen=True)
class Repo:
    """A repository as a path sees it. Two repos are equal when they share a common git directory, whatever their working trees."""

    root: str = field(compare=False)  # the directory holding `.git`; a linked worktree has its own
    identity: str  # the real path of the common git directory, shared by a repository and its linked worktrees

    def key(self) -> str:
        """Sixteen lowercase hex digits naming the identity, safe in a file name."""
        import hashlib

        return hashlib.sha256(os.fsencode(self.identity)).hexdigest()[:16]


def resolved(path: object) -> Optional[str]:
    """`path` with every link followed as far as it exists and the rest appended unchecked, or None for anything but an absolute string without NUL, or when the tree changes under the lookup.

    An edit may create the directories it needs, so a target that does not exist
    yet still has a place.
    """
    target = _absolute(path)
    if target is None:
        return None
    try:
        return os.path.realpath(target)
    except (OSError, ValueError):  # a link swapped for something else while it was being followed
        return None


def nearest_directory(path: str) -> str:
    """The deepest directory at or above the absolute `path` that exists."""
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def repo_of(path: object) -> Optional[Repo]:
    """The repository `path` belongs to, or None when it belongs to none, or when that cannot be told."""
    target = resolved(path)
    if target is None:
        return None
    try:
        return _repo_above(nearest_directory(target))
    except OSError:  # one unreadable entry ends the walk: an unknown is not a repository
        return None


def ignored(
    path: object,
    runner: Optional[Callable[..., Any]] = None,
    base_env: Optional[Mapping[str, str]] = None,
) -> Optional[bool]:
    """Ask git whether `path` is ignored: True if so, False if not, None when git cannot say.

    Only False lets a caller go on. None covers a timeout, a missing git, a path
    outside the repository its directory belongs to, a repository git does not
    trust, and every other exit code. `runner` takes the place of `subprocess.run`
    and `base_env` of the process environment; both exist for tests.

    The user's own git configuration still applies, so their global excludes
    count. What is removed is every `GIT_*` variable, a repository's own
    `core.fsmonitor`, which could name a command to run, and every PATH entry that
    is empty or relative, which would look for `git` inside the tree itself.
    """
    import subprocess

    target = _absolute(path)
    if target is None:
        return None
    run = subprocess.run if runner is None else runner
    try:
        done = run(
            ["git", "-c", "core.fsmonitor=false", "check-ignore", "-q", "--", target],
            cwd=nearest_directory(target),
            env=_git_environment(os.environ if base_env is None else base_env),
            timeout=IGNORE_TIMEOUT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError, ValueError):  # ValueError: an argument git cannot be given
        return None
    return {0: True, 1: False}.get(done.returncode)


def _absolute(path: object) -> Optional[str]:
    """`path` itself when it is an absolute string without NUL, else None."""
    return path if isinstance(path, str) and "\0" not in path and os.path.isabs(path) else None


def _git_environment(base: Mapping[str, str]) -> dict[str, str]:
    kept = {name: value for name, value in base.items() if not name.startswith("GIT_")}
    return {**kept, "PATH": _absolute_search_path(base.get("PATH", "")), "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}


def _absolute_search_path(search: str) -> str:
    """The absolute entries of a PATH value, in order, or the platform default when none is left.

    The command runs inside the tree it is asked about, and an empty or relative
    entry is looked up in the child's own directory, so it would let that tree
    supply the `git` to run. The result is never empty: `""` splits to one empty
    entry, which is the current directory again.
    """
    entries = [entry for entry in search.split(os.pathsep) if os.path.isabs(entry)]
    return os.pathsep.join(entries) or os.defpath


def _ancestry(directory: str) -> Iterator[str]:
    while True:
        yield directory
        parent = os.path.dirname(directory)
        if parent == directory:
            return
        directory = parent


def _repo_above(start: str) -> Optional[Repo]:
    """The repository whose `.git` is the first one found at `start` or above it, within the level bound."""
    for directory in islice(_ancestry(start), MAX_LEVELS):
        try:
            info = os.lstat(os.path.join(directory, ".git"))
        except FileNotFoundError:
            continue
        return _repo_at(directory, info)
    return None


def _repo_at(directory: str, info: os.stat_result) -> Optional[Repo]:
    git_dir = _git_dir(directory, info)
    if git_dir is None or not os.path.isdir(git_dir):
        return None
    identity = _common_dir(git_dir)
    return None if identity is None else Repo(directory, identity)


def _git_dir(directory: str, info: os.stat_result) -> Optional[str]:
    """Where `.git` leads: itself when it is a directory, the path it names when it is a pointer file, else nowhere."""
    dot_git = os.path.join(directory, ".git")
    if stat.S_ISDIR(info.st_mode):
        return os.path.realpath(dot_git)
    if not stat.S_ISREG(info.st_mode):  # a link, a pipe, a socket: git itself would not call this a repository either
        return None
    data = read_small(dot_git, MAX_READ)
    if data is None or b"\0" in data or not data.startswith(GITDIR_PREFIX):
        return None
    named = data.split(b"\n", 1)[0][len(GITDIR_PREFIX):].strip()
    return os.path.realpath(os.path.join(directory, os.fsdecode(named))) if named else None


def _common_dir(git_dir: str) -> Optional[str]:
    """The git directory shared with the repository's other worktrees: the one `commondir` names, else `git_dir` itself."""
    try:
        data = read_small(os.path.join(git_dir, "commondir"), MAX_READ)
    except FileNotFoundError:
        return git_dir
    named = b"" if data is None or b"\0" in data else data.split(b"\n", 1)[0].strip()
    return os.path.realpath(os.path.join(git_dir, os.fsdecode(named))) if named else None
