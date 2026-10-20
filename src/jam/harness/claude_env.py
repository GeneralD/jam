"""The only module that names Claude Code environment variables.

Every resolver takes the environment as an argument, so they are pure and never
touch `os.environ`. Only the variables named below are ever read: other session
variables exist and one of them is a credential. `HOME` is the one that is not
the platform's, and it is read only to find the default configuration directory.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from pathlib import PurePath
from typing import Final, Optional

from ..errors import HarnessError
from ..session import Identity, is_id

DATA_DIR_VAR: Final = "CLAUDE_PLUGIN_DATA"
SESSION_ID_VAR: Final = "CLAUDE_CODE_SESSION_ID"
JOB_DIR_VAR: Final = "CLAUDE_JOB_DIR"
PROJECT_DIR_VAR: Final = "CLAUDE_PROJECT_DIR"
CONFIG_DIR_VAR: Final = "CLAUDE_CONFIG_DIR"
HOME_VAR: Final = "HOME"


def data_dir(flag: Optional[str], env: Mapping[str, str]) -> Optional[str]:
    """The data directory: a non-empty flag, else the platform's variable, else None."""
    return flag or env.get(DATA_DIR_VAR) or None


def project_dir(env: Mapping[str, str]) -> Optional[str]:
    """The directory the session started in, as the platform reports it, or None when the variable is unset, empty or not an absolute path.

    It does not move when the session changes directory or enters a worktree.
    """
    return _absolute(env.get(PROJECT_DIR_VAR))


def config_dir(env: Mapping[str, str]) -> Optional[str]:
    """The configuration directory: the platform's variable when it is an absolute path, else `.claude` below the home directory, else None."""
    chosen = _absolute(env.get(CONFIG_DIR_VAR))
    if chosen is not None:
        return chosen
    home = _absolute(env.get(HOME_VAR))
    return None if home is None else posixpath.join(home, ".claude")


def _absolute(value: object) -> Optional[str]:
    return value if isinstance(value, str) and "\0" not in value and posixpath.isabs(value) else None


def identity(env: Mapping[str, str]) -> Identity:
    """The calling session's ids; the message names the variable and never shows its value.

    The short id is the name of the job directory when that is a valid id. It is
    never cut from the session id, because no prefix relation between the two is
    documented.
    """
    session_id = env.get(SESSION_ID_VAR)
    if not is_id(session_id):
        raise HarnessError(f"{SESSION_ID_VAR} is not set to a valid session id")
    short = PurePath(env.get(JOB_DIR_VAR) or "").name
    return Identity(session_id, short if is_id(short) else None)
