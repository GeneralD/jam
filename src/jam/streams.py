"""What the command line and the hook plumbing both need from a stream that can no longer be written to.

Stdlib only, and it imports nothing else of jam, so a hook can use it without loading the command line.
"""

from __future__ import annotations

import contextlib
import os
from typing import IO


def silenced(stream: IO[str]) -> None:
    """Point the descriptor of a stream that can no longer be written to (its reader has gone, say) at /dev/null.

    The write that failed left its text in the buffer, and the interpreter would
    flush it again at exit, fail again, print a notice and exit with status 120.
    """
    with contextlib.suppress(AttributeError, OSError, ValueError):  # a StringIO, a closed file or a bare object has no descriptor to point away
        with open(os.devnull, "wb") as null:
            os.dup2(null.fileno(), stream.fileno())
