"""The Claude Code hook entry: `scripts/jam hook <name>`, run by the platform.

Fail-open. A hook must never block a session or a tool call, so it never exits
with 2. Every failure it can handle ends in exit 0 and leaves only the exception
type on stderr, and an unusable payload is not a failure: the notice is still
printed, without the session id, and the guard stays silent. Only a crash, the
alarm or a vanished reader leave no output, and the alarm ends a hung hook by
signal, so that exit status is not 0.

Four handlers, all registered, all synchronous, all bounded by an in-process
alarm that goes off before the platform's timeout in hooks/hooks.json (a test
holds each alarm below the timeout of its entry):

- `notice` (SessionStart) prints the notice. It does no file access at all, so a
  stuck disk cannot delay the first response and a bug in `prune` cannot cost
  the notice.
- `prune` (SessionStart) sweeps stale notes from the registry, and stale deny
  claims, hour slots, start records, worker marks and spawn tickets, and prints
  nothing. Only the two guard sweeps are capped and share the one-second budget;
  the note sweep has neither, so only the alarm bounds it. A failure in one sweep
  does not stop the others.
- `adopt` (SessionStart) records the directory the session started in and, unless
  the session continues or copies one (`resume`, `clear`, `compact` or `fork`),
  takes the spawn ticket of that directory as the session's worker mark. It
  prints nothing.
- `guard` (PreToolUse, for the four edit tools) denies, once per session and
  repository, an edit of a file in a repository other than the one the session
  started in (D6, D14). Its entry ends in `|| exit 0`, so a script that cannot
  be opened, which makes Python exit with 2, does not block the edit. Allowing
  prints nothing at all: the normal permission flow stays in force, and the hook
  never prints an allow, an ask or a defer.

The registry, the sweep and the guard's modules are imported inside the handlers
that use them: they are the slow part of a start, and `notice` needs none of them.
"""

from __future__ import annotations

import contextlib
import io
import os
import posixpath
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Final, Optional

from ..errors import InvalidRequest, RegistryError
from . import claude_env, hook_io, notice

# Derived from this file's own place in the tree (<root>/src/jam/harness); compose.PLUGIN_ROOT is the same directory, pinned equal by a test.
# No resolve() here: the launcher already hands over a resolved src path, and a path lookup must not run before the alarm or inside the notice.
PLUGIN_ROOT: Final = Path(__file__).parents[3]

# What `prune` may spend on each directory it sweeps (the guard's state and the spawn tickets), counted in entries looked at. The guard's figure is
# 20 slots an hour for thirty days, doubled, with room for the deny claims; the ticket directory has no throttle, so there it is a bound only.
SWEEP_LIMIT: Final = 20 * 24 * 30 * 2
# The budget, counted from the start of the hook, leaves the rest of the alarm for the sweeps and for exiting.
PRUNE_BUDGET: Final = 1.0
# The sources of a session that continues or copies one already started; they take no spawn ticket. A live --bg worker's
# first start reported `startup`, and `claude --bg --resume` started a copy that reported `fork` (D14). A resume with no
# other flag, made 20 seconds or more after a stop, kept the id and reported `resume`, and `/clear` reported `clear`
# (2026-10-28, D14); an unknown source takes one.
RESUMED: Final = ("resume", "clear", "compact", "fork")

# Evaluated at import time, so this alias stays on `Optional` for Python 3.9.
Handler = Callable[[dict[str, Any], Mapping[str, str]], Optional[str]]


def notice_text(payload: dict[str, Any], env: Mapping[str, str]) -> str:
    """The notice for the session in `payload`; the source, cwd and transcript path are deliberately not read."""
    prefix = notice.invocation_prefix(str(PLUGIN_ROOT), claude_env.data_dir(None, env))
    return notice.session_notice(prefix, payload.get("session_id"))


def prune(payload: dict[str, Any], env: Mapping[str, str]) -> Optional[str]:
    """Delete notes, guard files and spawn tickets older than the age limit; nothing to say, whatever happens.

    The three sweeps always run, in the order notes, guard files, tickets. Each one
    sits in a `finally` of the one before, so a bug in one cannot keep the next from
    running, and the bug is still reported.
    """
    directory = claude_env.data_dir(None, env)
    if directory is None:
        return None
    deadline = time.monotonic() + PRUNE_BUDGET
    try:
        _notes_pruned(directory)
    finally:
        try:
            _guard_files_pruned(directory, deadline)
        finally:
            _tickets_pruned(directory, deadline)
    return None


def _notes_pruned(directory: str) -> None:
    from ..registry import Registry

    with contextlib.suppress(InvalidRequest, RegistryError, OSError):  # a relative path, a damaged registry and a full disk are all "not now"
        Registry(directory).prune()


def _guard_files_pruned(directory: str, deadline: float) -> None:
    from .. import claims

    _swept(claims.state_dir(directory), claims.is_state_name, deadline)  # None for a relative path, which would follow the working directory


def _tickets_pruned(directory: str, deadline: float) -> None:
    from .. import tickets

    _swept(tickets.pending_dir(directory), tickets.is_ticket_name, deadline)  # None for a relative path, which would follow the working directory


def _swept(swept_dir: Optional[str], accept: Callable[[str], bool], deadline: float) -> None:
    """Sweep `swept_dir` by `accept` and the registry's age limit; nothing to do when there is no such directory."""
    from .. import sweep
    from ..registry import STALE_AFTER

    if swept_dir is None:
        return
    sweep.swept(swept_dir, accept, STALE_AFTER, time.time(), SWEEP_LIMIT, deadline)


def adopt(payload: dict[str, Any], env: Mapping[str, str]) -> Optional[str]:
    """Record the directory the session started in, then take the spawn ticket of that directory as the session's worker mark.

    The record comes first and the mark is taken in a `finally`: a failure in the
    record does not cost the mark, and a failure in the mark is still reported
    after the record is written.
    """
    directory = claude_env.data_dir(None, env)
    if directory is None:
        return None
    from .. import claims

    session_id, cwd = payload.get("session_id"), payload.get("cwd")
    try:
        claims.Claims(directory).record_start(session_id, cwd)
    finally:
        _mark_taken(directory, session_id, cwd, payload.get("source"))
    return None


def _mark_taken(directory: str, session_id: object, cwd: object, source: object) -> None:
    """Take the freshest spawn ticket of `cwd` as the mark of the session, unless the source says the session continues or copies one."""
    from .. import tickets

    if source in RESUMED:
        return
    tickets.claim_mark(directory, session_id, cwd, time.time())


# The tool calls that edit a file, and the input fields that name it, in the order they are tried.
# MultiEdit is in no documentation page that was checked, so nothing may depend on the platform sending it; a payload of that name is read like an Edit.
EDIT_FIELDS: Final = {"Edit": ("file_path",), "Write": ("file_path",), "MultiEdit": ("file_path",), "NotebookEdit": ("notebook_path", "file_path")}


def edit_target(payload: dict[str, Any]) -> Optional[str]:
    """The absolute path the tool call in `payload` writes to, or None when it is no edit or names no usable path.

    A relative path is joined to the call's working directory, which is used for
    nothing else: it moves with every `cd` and says nothing about where the session started.
    """
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input")
    fields = EDIT_FIELDS.get(tool) if isinstance(tool, str) else None
    if fields is None or not isinstance(tool_input, dict):
        return None
    named = next((tool_input[field] for field in fields if field in tool_input), None)
    if not isinstance(named, str) or not named or "\0" in named:
        return None
    return named if posixpath.isabs(named) else _joined(payload.get("cwd"), named)


def _joined(cwd: object, relative: str) -> Optional[str]:
    return posixpath.join(cwd, relative) if isinstance(cwd, str) and "\0" not in cwd and posixpath.isabs(cwd) else None


def edit_denial(payload: dict[str, Any], env: Mapping[str, str]) -> Optional[str]:
    """The reason to deny the edit in `payload`, or None to leave the call to the normal permission flow."""
    target = edit_target(payload)
    data_dir = claude_env.data_dir(None, env)
    if target is None or data_dir is None:
        return None
    from .. import guard

    effects = _live_effects(data_dir)
    if effects is None:
        return None
    edit = guard.Edit(payload.get("session_id"), target, claude_env.project_dir(env), claude_env.config_dir(env))
    denial = guard.decide(edit, effects)
    return None if denial is None else notice.deny_reason(denial.root)


def _live_effects(data_dir: str) -> Optional[Any]:
    """The guard's effects over the real files, claims and clock, or None when there is nowhere to remember what was said (a relative data directory would follow the working directory)."""
    from .. import claims, guard, repos

    if claims.state_dir(data_dir) is None:  # a hook that cannot remember what it has said must not speak
        return None
    book = claims.Claims(data_dir)
    return guard.Effects(
        worker_marked=book.worker_marked,
        start_recorded=book.start_recorded,
        resolved=repos.resolved,
        repo_of=repos.repo_of,
        pair_claimed=book.pair_claimed,
        hour=_clock_hour,
        throttled=book.throttled,
        ignored=repos.ignored,
        claim_pair=book.claim_pair,
        claim_slot=book.claim_slot,
    )


def _clock_hour() -> int:
    return int(time.time() // 3600)  # a whole number: the slots treat any other kind of value as no hour at all, and the guard would never deny


@dataclass(frozen=True)
class Hook:
    handler: Handler
    alarm: int  # seconds; below the timeout of the same hook in hooks/hooks.json, which a test pins
    envelope: Callable[[str], str] = hook_io.hook_output  # what the text of the handler is wrapped in
    stdin_cap: int = hook_io.MAX_STDIN  # bytes of stdin that are read; a longer input is an empty payload


HOOKS: Final = {
    "adopt": Hook(adopt, 3),
    "notice": Hook(notice_text, 3),
    "prune": Hook(prune, 2),
    "guard": Hook(edit_denial, 2, hook_io.denial_output, hook_io.MAX_EDIT_STDIN),
}


def run(hook: Hook, stdin: IO[bytes], env: Mapping[str, str], stdout: IO[str]) -> None:
    text = hook.handler(hook_io.payload_from(stdin, hook.stdin_cap), env)
    if text is not None:
        hook_io.emitted(stdout, hook.envelope(text))


def main(
    argv: list[str],
    env: Optional[Mapping[str, str]] = None,
    stdin: Optional[IO[bytes]] = None,
    stdout: Optional[IO[str]] = None,
    stderr: Optional[IO[str]] = None,
    arm: Callable[[int], object] = hook_io.arm_alarm,
) -> int:
    """Run the hook named by `argv[0]` and return its exit code, always 0. Everything it touches can be passed in.

    A missing or unknown name does nothing, so a newer hooks.json meeting an older
    plugin, or the reverse, stays quiet. `arm` is the seam that keeps tests from
    arming a real alarm.
    """
    hook = HOOKS.get(argv[0]) if argv else None
    if hook is None:
        return 0
    env = os.environ if env is None else env
    stdin = getattr(sys.stdin, "buffer", io.BytesIO()) if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    arm(hook.alarm)
    try:
        run(hook, stdin, env, stdout)
    except Exception as exc:  # fail open: whatever went wrong, the session goes on
        hook_io.reported(stderr, exc)
    finally:
        arm(0)
    return 0
