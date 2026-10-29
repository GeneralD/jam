"""The only module that names Devin CLI environment variables.

Every resolver takes the environment as an argument, so they are pure and never
touch `os.environ`. Only the variables named below are ever read. `HOME` is
read only to find the default configuration directory, as in `claude_env`.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from typing import Final, Optional

from ..errors import HarnessError
from ..session import Identity

DATA_DIR_VAR: Final = "PLUGIN_DATA"
PROJECT_DIR_VAR: Final = "DEVIN_PROJECT_DIR"
PLUGIN_ROOT_VAR: Final = "DEVIN_PLUGIN_ROOT"
AGENT_VAR: Final = "AI_AGENT"
HOME_VAR: Final = "HOME"


def detect(env: Mapping[str, str]) -> bool:
    """True when the environment belongs to a Devin session or a Devin hook process."""
    return env.get(AGENT_VAR, "").startswith("devin") or bool(env.get(PROJECT_DIR_VAR)) or bool(env.get(DATA_DIR_VAR))


def data_dir(flag: Optional[str], env: Mapping[str, str]) -> Optional[str]:
    """The data directory: a non-empty flag, else the platform's variable, else None."""
    return flag or env.get(DATA_DIR_VAR) or None


def project_dir(env: Mapping[str, str]) -> Optional[str]:
    """The directory the session started in, as the platform reports it, or None."""
    return _absolute(env.get(PROJECT_DIR_VAR))


def config_dir(env: Mapping[str, str]) -> Optional[str]:
    """The configuration directory: Devin reads `~/.devin`, so it is the home-joined path or None."""
    home = _absolute(env.get(HOME_VAR))
    return None if home is None else posixpath.join(home, ".devin")


def _absolute(value: object) -> Optional[str]:
    return value if isinstance(value, str) and "\0" not in value and posixpath.isabs(value) else None


def identity(env: Mapping[str, str]) -> Identity:
    """There is no session-id variable outside hooks on Devin, so whoami cannot answer.

    Devin exposes ids like `hail-mare` through the hook payload and
    `devin list`, but a Bash run inside a session carries no equivalent of
    CLAUDE_CODE_SESSION_ID. Refusing beats guessing: a wrong id is worse than
    none (D12).
    """
    raise HarnessError(
        "this harness exposes no session id to the calling process; match your row in `list` by cwd instead"
    )
