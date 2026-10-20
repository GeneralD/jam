"""The only module that names Claude Code environment variables.

Both resolvers take the environment as an argument, so they are pure and never
touch `os.environ`. Only the variables named below are ever read: other session
variables exist and one of them is a credential.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePath
from typing import Final, Optional

from ..errors import HarnessError
from ..session import Identity, is_id

DATA_DIR_VAR: Final = "CLAUDE_PLUGIN_DATA"
SESSION_ID_VAR: Final = "CLAUDE_CODE_SESSION_ID"
JOB_DIR_VAR: Final = "CLAUDE_JOB_DIR"


def data_dir(flag: Optional[str], env: Mapping[str, str]) -> Optional[str]:
    """The data directory: a non-empty flag, else the platform's variable, else None."""
    return flag or env.get(DATA_DIR_VAR) or None


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
