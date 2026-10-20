"""The Claude Code hook entry: `scripts/jam hook <name>`, run by the platform on SessionStart.

Fail-open. A hook must never block a session, so it never exits with 2. Every
failure it can handle ends in exit 0 and leaves only the exception type on
stderr, and an unusable payload is not a failure: the notice is still printed,
without the session id. Only a crash, the alarm or a vanished reader leave no
output, and the alarm ends a hung hook by signal, so that exit status is not 0.

Two hooks, both synchronous, both bounded by an in-process alarm that goes off
before the platform's timeout in hooks/hooks.json:

- `notice` prints the notice. It does no file access at all, so a stuck disk
  cannot delay the first response and a bug in `prune` cannot cost the notice.
- `prune` sweeps stale notes from the registry and prints nothing.

The registry is imported inside `prune`: its modules are the slow part of a
start, and `notice` does not need them.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Final, Optional

from ..errors import InvalidRequest, RegistryError
from . import claude_env, hook_io, notice

# Derived from this file's own place in the tree (<root>/src/jam/harness); compose.PLUGIN_ROOT is the same directory, pinned equal by a test.
PLUGIN_ROOT: Final = Path(__file__).resolve().parents[3]

# Evaluated at import time, so this alias stays on `Optional` for Python 3.9.
Handler = Callable[[dict[str, Any], Mapping[str, str]], Optional[str]]


def notice_text(payload: dict[str, Any], env: Mapping[str, str]) -> str:
    """The notice for the session in `payload`; the source, cwd and transcript path are deliberately not read."""
    prefix = notice.invocation_prefix(str(PLUGIN_ROOT), claude_env.data_dir(None, env))
    return notice.session_notice(prefix, payload.get("session_id"))


def prune(payload: dict[str, Any], env: Mapping[str, str]) -> Optional[str]:
    """Delete notes older than the registry's age limit; nothing to say, whatever happens."""
    directory = claude_env.data_dir(None, env)
    if directory is None:
        return None
    from ..registry import Registry

    with contextlib.suppress(InvalidRequest, RegistryError, OSError):  # a relative path, a damaged registry and a full disk are all "not now"
        Registry(directory).prune()
    return None


@dataclass(frozen=True)
class Hook:
    handler: Handler
    alarm: int  # seconds; below the timeout of the same hook in hooks/hooks.json, which a test pins


HOOKS: Final = {"notice": Hook(notice_text, 3), "prune": Hook(prune, 2)}


def run(hook: Hook, stdin: IO[bytes], env: Mapping[str, str], stdout: IO[str]) -> None:
    text = hook.handler(hook_io.payload_from(stdin), env)
    if text is not None:
        hook_io.emitted(stdout, hook_io.hook_output(text))


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
