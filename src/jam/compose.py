"""The composition root: the one place that picks the Claude Code adapter, the registry and the spawn tickets.

Everything here is lazy. Building a Runtime does no I/O, and neither does the
factory it holds until the core is used, because the platform may start the MCP
server more than once per session start.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final, Optional

from .errors import InvalidRequest, RegistryError
from .harness import claude_env, claude_hooks, devin_env
from .harness.claude import ClaudeHarness, Runner
from .harness.devin import DevinHarness
from .operations import Runtime
from .registry import Registry
from .service import Jam
from .tickets import Tickets

PLUGIN_ROOT: Final = Path(__file__).resolve().parent.parent.parent
MANIFEST: Final = Path(".claude-plugin") / "plugin.json"
MAX_MANIFEST_BYTES: Final = 64 * 1024
NO_DATA_DIR: Final = "no data directory: pass --data-dir before the command (the SessionStart notice gives the full command line)"


class UnavailableRegistry:
    """Stands in for the registry when there is no usable data directory.

    It raises RegistryError, which the service already turns into a `problem`
    next to a result that is still correct, so the registry stays an annotation layer.
    """

    def __init__(self, reason: str):
        self._reason = reason

    def record(self, key: str) -> Any:
        raise RegistryError(self._reason)

    def update(self, key: str, change: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        raise RegistryError(self._reason)


def registry_for(directory: Optional[str]) -> Any:
    """The registry for a directory; the reason it cannot be used is path-free."""
    if directory is None:
        return UnavailableRegistry(NO_DATA_DIR)
    try:
        return Registry(directory)
    except InvalidRequest as exc:
        return UnavailableRegistry(str(exc))


def _harness_parts(env: Mapping[str, str]) -> tuple:
    """The environment module and adapter for the harness this session runs on.

    Claude markers win when both sets are present: a Devin session's variables
    are inherited by every process it spawns (a Claude session among them),
    while Claude's per-session variables only exist inside Claude itself.
    """
    for env_module, harness_type in ((claude_env, ClaudeHarness), (devin_env, DevinHarness)):
        if env_module.detect(env):
            return env_module, harness_type
    return claude_env, ClaudeHarness


def _harness(harness_type: type, runner: Optional[Runner], env: Mapping[str, str]) -> Any:
    """The adapter. Claude Code's reads transcripts under the configuration directory this environment names (D20)."""
    if harness_type is ClaudeHarness:
        return ClaudeHarness(runner=runner, config_dir=claude_env.config_dir(env))
    return harness_type(runner=runner)


def build_runtime(data_dir_flag: Optional[str], env: Mapping[str, str], runner: Optional[Runner] = None) -> Runtime:
    """A Runtime over the real adapter. `runner` is the seam that keeps tests from starting sessions.

    The MCP server's `instructions` are the session notice without the session id
    line, from the hook's own function and for the data directory resolved here,
    so the two texts cannot drift; in the one foreground session checked on
    Claude Code 2.1.309, a session that had only reloaded the plugin had the
    text (D12, #31).
    """
    env_module, harness_type = _harness_parts(env)
    directory = env_module.data_dir(data_dir_flag, env)
    return Runtime(
        lambda: Jam(_harness(harness_type, runner, env), registry_for(directory), Tickets(directory)),
        lambda: env_module.identity(env),
        lambda: claude_hooks.server_instructions(directory),
    )


def manifest_document(root: Path) -> object:
    """The parsed manifest, read with a size bound; ValueError or OSError when it cannot be."""
    with open(Path(root) / MANIFEST, "rb") as manifest:
        raw = manifest.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("the plugin manifest is too large")
    return json.loads(raw.decode("utf-8"))


def plugin_version(root: Path = PLUGIN_ROOT) -> str:
    """The version in the plugin manifest (its only home), or 'unknown' for anything unusable."""
    try:
        document = manifest_document(root)
    except (OSError, ValueError, RecursionError):
        return "unknown"
    version = document.get("version") if isinstance(document, dict) else None
    return version if isinstance(version, str) else "unknown"
