"""Test helper: real git in a sandbox that cannot see the developer's configuration.

Nothing run through here signs a commit, prompts or reaches a network, and
`HOME` and `XDG_CONFIG_HOME` point at a directory the test owns, so neither a
global nor a system configuration decides the outcome.
"""

from __future__ import annotations

import os
import shutil
import subprocess

GIT = shutil.which("git")
# Every run may commit, so these always go in front of the subcommand.
COMMIT_FLAGS = ("-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main")


def home_env(home):
    """The minimal environment for a process that looks for the user's git configuration under `home`."""
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home), "XDG_CONFIG_HOME": str(home)}


def sandbox_env(home):
    """`home_env` plus the switches that remove the global and system configuration and every prompt."""
    return {**home_env(home), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


def git(home, cwd, *args):
    """Run git in `cwd` inside the sandbox and return its stdout; a failure raises with git's own message."""
    done = subprocess.run(
        [GIT, *COMMIT_FLAGS, *args],
        cwd=str(cwd),
        env=sandbox_env(home),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed with {done.returncode}: {done.stderr}")
    return done.stdout
