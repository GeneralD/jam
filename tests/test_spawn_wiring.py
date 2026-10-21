"""End to end: a spawn writes its ticket, the worker's first session start turns it into the mark, and the guard then lets that session edit a foreign repository.

The spawn runs in process through the real harness with a fake runner, so no
session starts. The session start and the guard run as `python3 -I scripts/jam
hook ...` subprocesses, the way the platform runs them, with the fake `git` of
test_guard_launcher on the PATH. The repositories are hand-built `.git` layouts.
Also pinned here: the structure of hooks/hooks.json for the three session start
hooks, and the import graph of the `adopt` path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from jam.registry import Registry
from jam.service import Jam
from test_claude_harness import FakeRunner, ok
from test_guard_launcher import GuardLauncherTestCase
from test_hook_wiring import LAUNCH, entries
from test_launcher import SESSION_ID
from test_operations import lazy
from test_plugin_structure import HOOKS_JSON, command_problems, load_json

hooks = lazy("jam.harness.claude_hooks")
tickets = lazy("jam.tickets")
claude_harness = lazy("jam.harness.claude")

WORKER_SHORT_ID = "cccc3333"
OTHER_SESSION = "bbbb2222-0000-4000-8000-000000000002"
# hashlib is allowed on this path: the start of a session computes the directory key, lazily, as the design says.
HEAVY = ("argparse", "subprocess", "tempfile", "jam.cli", "jam.compose", "jam.mcp", "jam.operations", "jam.service", "jam.registry", "jam.sweep", "jam.guard", "jam.repos")
SRC = support.SRC


class SpawnToMarkTest(GuardLauncherTestCase):
    def setUp(self):
        super().setUp()
        self.link = self.root / "app-link"
        self.link.symlink_to(self.app)  # the spawner names the repository through a link; the worker's start names the real path
        self.runner = FakeRunner(ok(stdout=f"backgrounded · {WORKER_SHORT_ID} · worker-c\n"))
        self.jam_in_process = Jam(claude_harness.ClaudeHarness(runner=self.runner), Registry(str(self.data)), tickets.Tickets(str(self.data)))

    def spawn(self):
        return self.jam_in_process.spawn(str(self.link), "the brief")

    def session_start(self, sid, cwd, source="startup"):
        return json.dumps({"session_id": sid, "cwd": cwd, "source": source, "hook_event_name": "SessionStart"}).encode("utf-8")

    def adopt(self, sid=SESSION_ID, cwd=None, source="startup"):
        return self.jam("hook", "adopt", stdin=self.session_start(sid, str(self.app) if cwd is None else cwd, source), env=self.hook_env())

    def test_before_its_first_session_start_the_worker_is_denied_like_any_session(self):
        self.spawn()
        proc = self.through_sh(self.call())
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.startswith(b'{"hookSpecificOutput"'), proc.stdout)

    def test_the_worker_after_its_first_session_start_edits_the_foreign_repository_in_silence(self):
        self.spawn()
        adopted = self.adopt()
        self.assertExit(adopted, 0)
        self.assertEqual((adopted.out, adopted.err), ("", ""))
        proc = self.through_sh(self.call())
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, b"", b""))

    def test_a_session_without_the_mark_is_still_denied_once_and_the_spawn_left_no_claim_behind(self):
        self.spawn()
        self.adopt()
        denied = self.through_sh(self.call(session_id=OTHER_SESSION))
        self.assertEqual(denied.returncode, 0)
        self.assertIn(b"permissionDecision", denied.stdout)
        self.assertEqual(os.listdir(self.data / "pending-v1"), [])

    def test_the_start_record_of_the_worker_is_the_real_directory_even_when_spawned_through_a_link(self):
        self.spawn()
        self.adopt()
        self.assertEqual((self.data / "guard-v1" / f"start.{SESSION_ID}").read_bytes(), os.fsencode(os.path.realpath(self.app)) + b"\n")
        self.assertEqual(sorted(os.listdir(self.data / "guard-v1")), sorted([f"start.{SESSION_ID}", f"worker.{SESSION_ID}"]))

    def test_a_clear_after_the_spawn_does_not_take_the_ticket_and_the_worker_stays_denied(self):
        self.spawn()
        self.adopt(source="clear")
        self.assertEqual(len(os.listdir(self.data / "pending-v1")), 1)
        proc = self.through_sh(self.call())
        self.assertIn(b"permissionDecision", proc.stdout)

    def test_the_adopt_hook_loads_none_of_the_heavy_modules(self):
        proc = self.jam(
            "hook", "adopt", stdin=self.session_start(SESSION_ID, str(self.app)), env=self.hook_env(), flags=("-I", "-X", "importtime")
        )
        self.assertExit(proc, 0)
        imported = [line.rsplit("|", 1)[-1].strip() for line in proc.err.splitlines() if line.startswith("import time:")]
        self.assertIn("jam.harness.claude_hooks", imported)
        for name in HEAVY:
            with self.subTest(module=name):
                self.assertNotIn(name, imported)

    def test_loading_the_hook_module_imports_neither_the_hash_nor_the_random_module(self):
        code = "import sys\nsys.path.insert(0, sys.argv[1])\nimport jam.harness.claude_hooks\nprint(' '.join(n for n in ('hashlib', 'secrets') if n in sys.modules))\n"
        proc = subprocess.run([sys.executable, "-I", "-c", code, str(SRC)], capture_output=True, text=True, timeout=60)
        self.assertEqual((proc.returncode, proc.stdout.strip(), proc.stderr), (0, "", ""))


class HooksJsonTest(unittest.TestCase):
    def setUp(self):
        self.document = load_json(HOOKS_JSON)
        self.groups = self.document["hooks"]["SessionStart"]

    def test_the_session_start_hooks_are_exactly_three_groups_and_no_other_event_is_declared(self):
        self.assertEqual(set(self.document["hooks"]), {"SessionStart"})
        self.assertEqual(len(self.groups), 3)

    def test_the_adopt_group_has_no_matcher_and_a_timeout_of_five_seconds(self):
        (group,) = [group for group in self.groups if group["hooks"][0]["command"].endswith(" hook adopt")]
        self.assertNotIn("matcher", group)
        (hook,) = group["hooks"]
        self.assertEqual((hook["type"], hook["command"], hook["timeout"]), ("command", LAUNCH + "adopt", 5))
        self.assertEqual(command_problems(hook["command"]), [])

    def test_the_alarm_of_adopt_goes_off_before_its_timeout(self):
        self.assertLess(hooks.HOOKS["adopt"].alarm, 5)

    def test_the_declared_entries_are_the_three_session_start_commands(self):
        self.assertEqual({entry[2] for entry in entries(self.document)}, {LAUNCH + "notice", LAUNCH + "prune", LAUNCH + "adopt"})


if __name__ == "__main__":
    unittest.main()
