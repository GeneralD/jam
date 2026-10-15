"""Errors shared by the core and the adapters. Stdlib only."""

from __future__ import annotations


class HarnessError(Exception):
    """The harness failed or answered in a way jam cannot use."""


class InvalidRequest(HarnessError, ValueError):
    """The caller's arguments were rejected before anything was run."""


class WorkspaceNotTrusted(HarnessError):
    """The harness refuses to start a session in a directory the owner has not trusted."""

    def __init__(self, path: str):
        super().__init__(
            f"workspace not trusted: run the agent once in {path}, accept the trust prompt, then retry"
        )
        self.path = path


class UnparseableOutput(HarnessError):
    """The command succeeded but its output was not in a recognised shape.

    A session may exist even so, so the raw output is kept for the caller.
    """

    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


class StillListed(HarnessError):
    """A session that was removed still shows up in the harness listing."""

    def __init__(self, session_id: str):
        super().__init__(f"session {session_id} is still listed after removal")
        self.session_id = session_id
