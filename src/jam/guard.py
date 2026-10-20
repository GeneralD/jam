"""The foreign-repository guard's decision: should this edit be denied, once, with a pointer to delegation?

An edit is foreign when it lands in a repository other than the one the session
started in. The first such edit of a session is denied, with a reason that points
to delegation, and the same edit sent again passes (D6, D14).

`decide` takes the steps below in order, cheapest first. A step that lets the edit
through returns before the next one runs, so the costly ones (reading `.git`
entries, asking git, writing claims) are reached only by an edit that would
otherwise be denied. Every read and every write goes through the `Effects` it is
handed: the live ones are `claims.Claims` and `repos`, wired by the hook adapter,
and the tests pass fakes that log their calls.

    2. the session id is usable in a file name
    3. the session was started by jam itself (D14-1)
    4. the target resolves to a place
    5. the start directory is known: the platform's own record, else the session's
    6. the target is not inside the start directory, nor inside the configuration directory (D14-3)
    7. the session started in a repository (D14-5), the target is in one, and not the same one (D14-6)
    8. this session has not been denied for that repository yet
    9. the clock hour still has a free slot (D14-2)
   10. git does not ignore the target
   11. the pair (session, repository) is claimed, by this call alone
   12. an hour slot is claimed (D14-2)
   13. deny

Step 1, which tool calls are edits at all, and where the path sits in a call, belong
to the adapter. So does everything that names the harness. Each default the owner
may reject is one clause marked with its D14 number, so that removing it is a
one-clause change. The exception is D14-2, the throttle: steps 9 and 12 go
together, with its members of `Effects`, because the hour is checked before git
is asked and the slot is claimed after the pair.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from .repos import Repo
from .session import is_id


@dataclass(frozen=True)
class Edit:
    """An edit as the adapter read it from a tool call."""

    session_id: object  # as reported; it becomes part of file names, so it is checked here
    target: object  # the path the edit names; absolute, which a relative path is made by the adapter
    project_dir: Optional[str]  # where the platform says the session started, when it says
    config_dir: Optional[str]  # the harness's configuration directory, whose files are never denied


@dataclass(frozen=True)
class Denial:
    root: str  # the working-tree root of the repository the edit would land in


@dataclass(frozen=True)
class Effects:
    worker_marked: Callable[[str], bool]
    start_recorded: Callable[[str], Optional[str]]
    resolved: Callable[[object], Optional[str]]
    repo_of: Callable[[str], Optional[Repo]]
    pair_claimed: Callable[[str, str], bool]
    hour: Callable[[], int]  # whole hours since the epoch, a real int
    throttled: Callable[[int], bool]
    ignored: Callable[[str], Optional[bool]]
    claim_pair: Callable[[str, str], bool]
    claim_slot: Callable[[int], bool]


def decide(edit: Edit, fx: Effects) -> Optional[Denial]:
    """The denial for `edit`, or None to let it through; a denial has been claimed before it is returned, so it is given at most once."""
    found = _foreign(edit, fx)
    if found is None:
        return None
    target, repo = found
    return _spoken(edit.session_id, target, repo, fx)


def _foreign(edit: Edit, fx: Effects) -> Optional[tuple[str, Repo]]:
    """Steps 2 to 7, which read only: the resolved target and the repository it is in, if it leaves the one the session started in."""
    session = edit.session_id
    if not is_id(session):
        return None
    if fx.worker_marked(session):  # D14-1
        return None
    target = fx.resolved(edit.target)
    if target is None:
        return None
    start = _start_directory(session, edit.project_dir, fx)
    if start is None or _within(target, start):
        return None
    if _in_config_dir(target, edit.config_dir, fx):  # D14-3
        return None
    started_in = fx.repo_of(start)
    if started_in is None:  # D14-5
        return None
    repo = fx.repo_of(target)
    if repo is None or repo == started_in:  # D14-6: equality is by git directory, so a submodule is its own repository
        return None
    return target, repo


def _spoken(session: str, target: str, repo: Repo, fx: Effects) -> Optional[Denial]:
    """Steps 8 to 13: the denial, unless it was given already, the hour is full, git ignores the target or a claim is lost."""
    key = repo.key()
    if fx.pair_claimed(session, key):
        return None
    hour = fx.hour()
    if fx.throttled(hour):  # D14-2
        return None
    if fx.ignored(target) is not False:  # only a definite "not ignored" goes on; ignored, unknown and failed all stay quiet
        return None
    if not fx.claim_pair(session, key):
        return None
    if not fx.claim_slot(hour):  # D14-2
        return None
    return Denial(repo.root)


def _start_directory(session: str, project_dir: Optional[str], fx: Effects) -> Optional[str]:
    """Step 5: the real path of the platform's record of the start, else of the session's own record. Never the working directory of the call, which moves."""
    recorded = project_dir or fx.start_recorded(session)
    return None if recorded is None else fx.resolved(recorded)


def _in_config_dir(target: str, config_dir: Optional[str], fx: Effects) -> bool:
    root = None if config_dir is None else fx.resolved(config_dir)
    return root is not None and _within(target, root)


def _within(path: str, root: str) -> bool:
    """True for `root` itself and anything below it; `/work/app2` is not below `/work/app`."""
    return path == root or path.startswith(root.rstrip("/") + "/")
