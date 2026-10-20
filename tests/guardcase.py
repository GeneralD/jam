"""Test helper: a base class for the guard handler tests, with real temporary repositories and a git that cannot be started.

The repositories are hand-built `.git` layouts in a temp directory, and every
`.git` outside it is hidden, so what sits above the temp directory (a checkout, a
dotfiles repository) cannot decide an outcome. `jam.repos.ignored` is replaced for
the whole test, so a test that forgets to say what git answers still starts no process.
"""

from __future__ import annotations

import json
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)
from jam.repos import ignored as real_ignored  # noqa: F401  (re-exported: taken before any test replaces it)

from test_claude_hooks import DATA_VAR, run
from test_operations import SESSION_ID, lazy
from test_repos import RepoTestCase

notice = lazy("jam.harness.notice")

PROJECT_VAR, CONFIG_VAR, HOME_VAR = "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR", "HOME"
ALARMS = [2, 0]  # armed at the start of the hook and cancelled at the end
CONTENT = "export {}\n"
DEFAULT, MISSING = object(), object()  # a tool input left to the helper, and one left out of the payload altogether


def edit_payload(tool, tool_input, **fields):
    """The stdin of a PreToolUse call as the platform sends it, with some fields replaced."""
    base = {
        "session_id": SESSION_ID,
        "transcript_path": "/work/t/aaaa1111.jsonl",
        "cwd": "/work/app",
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_01ABC123",
    }
    document = {**base, **fields}
    if tool_input is MISSING:
        del document["tool_input"]
    return json.dumps(document).encode("utf-8")


def denial_line(root):
    """The one line a denial prints: the envelope is spelled out here, and the reason text is pinned word for word in test_notice."""
    envelope = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": notice.deny_reason(root)}}
    return json.dumps(envelope, ensure_ascii=True, separators=(",", ":")) + "\n"


class GuardCase(RepoTestCase):
    """A session that started in `app` and writes into `other/src/index.ts`; git says nothing is ignored."""

    def setUp(self):
        super().setUp()
        self.hidden_above_root()
        patched = mock.patch("jam.repos.ignored", return_value=False)
        self.ignored = patched.start()
        self.addCleanup(patched.stop)
        self.data = self.root / "data"
        self.app = self.plain("app")
        self.other = self.plain("other")
        self.target = str(self.other / "src" / "index.ts")

    @property
    def state(self):
        return self.data / "guard-v1"

    def fresh(self):
        """A session id nobody has used in this test: a session is denied once per repository, so a second denial needs a second session."""
        self.sessions = getattr(self, "sessions", 0) + 1
        return f"session-{self.sessions}"

    def guarded(self, tool_input=DEFAULT, tool="Write", env=None, **fields):
        """Run the guard hook on one call; `env` adds to (or, with None values, removes from) the usual environment."""
        tool_input = {"file_path": self.target, "content": CONTENT} if tool_input is DEFAULT else tool_input
        environment = {DATA_VAR: str(self.data), PROJECT_VAR: str(self.app), **(env or {})}
        return run("guard", stdin=edit_payload(tool, tool_input, **fields), env={key: value for key, value in environment.items() if value is not None})

    def write_to(self, path, **kwargs):
        return self.guarded({"file_path": str(path), "content": CONTENT}, **kwargs)

    def assertDenied(self, result, root):
        self.assertEqual((result.code, result.err, result.alarms), (0, "", ALARMS))
        self.assertEqual(result.out, denial_line(str(root)))

    def assertSilent(self, result):
        """An allowed edit: nothing on either stream, exit 0. The guard never prints an allow, an ask or a defer."""
        self.assertEqual((result.code, result.out, result.err, result.alarms), (0, "", "", ALARMS))

    def record_start(self, session_id, path, ending="\n"):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / f"start.{session_id}").write_text(f"{path}{ending}", encoding="utf-8")

    def claim_files(self):
        return sorted(path.name for path in self.state.iterdir()) if self.state.is_dir() else []
