"""Launcher-level tests for `hook guard`: the command hooks/hooks.json declares, run through a shell as the platform runs it.

No Claude Code session is started. The only `git` on the PATH of these runs is a
script that logs how it was called and answers with an exit code the test sets,
so no test depends on the git of the machine, and a run that logs nothing has
started no process. HOME is a temp directory too.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from guardcase import edit_payload
from test_hook_launcher import HookLauncherTestCase
from test_hook_wiring import GUARD_COMMAND, LAUNCH
from test_launcher import ROOT, SESSION_ID

HEAVY = ("argparse", "subprocess", "tempfile", "hashlib", "jam.cli", "jam.compose", "jam.mcp", "jam.operations", "jam.service", "jam.registry", "jam.sweep")


class GuardLauncherTestCase(HookLauncherTestCase):
    def setUp(self):
        super().setUp()
        self.app, self.other = (self.root / name for name in ("app", "other"))
        for repository in (self.app, self.other):
            (repository / ".git").mkdir(parents=True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.target = str(self.other / "src" / "index.ts")
        self.git_log, self.git_exit = self.root / "git.log", self.root / "git.exit"
        self.git_exit.write_text("1", encoding="utf-8")  # exit 1 is git's "not ignored"
        self.install("git", f"printf '%s|%s\\n' \"$(pwd -P)\" \"$*\" >> {shlex.quote(str(self.git_log))}\nexit \"$(cat {shlex.quote(str(self.git_exit))})\"\n")
        self.install("python3", f'exec {shlex.quote(sys.executable)} "$@"\n')  # a closed PATH would otherwise decide which python3 the command meets

    def install(self, name, body):
        script = self.bin / name
        script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        script.chmod(0o755)

    def hook_env(self, **extra):
        usual = {"CLAUDE_PLUGIN_ROOT": str(ROOT), "CLAUDE_PLUGIN_DATA": str(self.data), "CLAUDE_PROJECT_DIR": str(self.app), "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home)}
        return self.env(**{**usual, **extra})

    def call(self, path=None, **fields):
        return edit_payload("Write", {"file_path": path or self.target, "content": "export {}\n"}, cwd=str(self.app), **fields)

    def through_sh(self, stdin, command=GUARD_COMMAND, env=None, shell="sh"):
        return subprocess.run([shell, "-c", command], input=stdin, capture_output=True, cwd=str(self.root), env=self.hook_env() if env is None else env, timeout=60)

    def git_calls(self):
        return self.git_log.read_text(encoding="utf-8").splitlines() if self.git_log.exists() else []

    def claims(self):
        return sorted(os.listdir(self.data / "guard-v1")) if (self.data / "guard-v1").is_dir() else []

    def tree(self, *roots):
        return sorted(str(path) for root in roots for path in root.rglob("*"))


class GuardCommandTest(GuardLauncherTestCase):
    def test_garbage_stdin_is_exit_zero_with_nothing_printed_and_no_process_started(self):
        for stdin in (b"", b"not json", b"[]", b'{"tool_name":', b"\xff\xfe"):
            with self.subTest(stdin=stdin):
                proc = self.through_sh(stdin)
                self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, b"", b""))
        self.assertEqual(self.git_calls(), [])

    def test_a_foreign_write_is_denied_with_one_line_and_the_same_call_again_passes_in_silence(self):
        first = self.through_sh(self.call())
        self.assertEqual((first.returncode, first.stderr), (0, b""))
        self.assertEqual(first.stdout.count(b"\n"), 1)
        envelope = json.loads(first.stdout)
        self.assertEqual(list(envelope), ["hookSpecificOutput"])
        decision = envelope["hookSpecificOutput"]
        self.assertEqual((decision["hookEventName"], decision["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn(f"({self.other})", decision["permissionDecisionReason"])
        self.assertIn("mcp__plugin_jam_jam__spawn", decision["permissionDecisionReason"])
        second = self.through_sh(self.call())
        self.assertEqual((second.returncode, second.stdout, second.stderr), (0, b"", b""))
        self.assertEqual(self.git_calls(), [f"{self.other}|-c core.fsmonitor=false check-ignore -q -- {self.target}"])  # asked once, in the nearest existing directory

    def test_a_denial_leaves_private_claims_in_the_data_directory_and_nothing_in_either_repository(self):
        before = self.tree(self.app, self.other)
        self.assertTrue(self.through_sh(self.call()).stdout)
        self.assertEqual(self.tree(self.app, self.other), before)
        self.assertEqual(len(self.claims()), 2)
        self.assertEqual((self.data / "guard-v1").stat().st_mode & 0o777, 0o700)

    def test_an_edit_inside_the_start_repository_prints_nothing_and_starts_no_process(self):
        proc = self.through_sh(self.call(str(self.app / "src" / "new.ts")))
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, b"", b""))
        self.assertEqual(self.git_calls(), [])
        self.assertEqual(self.claims(), [])

    def test_a_path_git_ignores_is_silent_and_burns_no_claim_so_a_changed_answer_is_denied(self):
        self.git_exit.write_text("0", encoding="utf-8")
        ignored = self.through_sh(self.call())
        self.assertEqual((ignored.returncode, ignored.stdout, ignored.stderr), (0, b"", b""))
        self.assertEqual(self.claims(), [])
        self.git_exit.write_text("1", encoding="utf-8")
        self.assertTrue(self.through_sh(self.call()).stdout)

    def test_a_git_that_fails_is_silent(self):
        for code in ("128", "2", "7"):
            with self.subTest(code=code):
                self.git_exit.write_text(code, encoding="utf-8")
                proc = self.through_sh(self.call())
                self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, b"", b""))
        self.assertEqual(self.claims(), [])

    def test_a_machine_without_git_is_silent(self):
        (self.bin / "git").unlink()
        proc = self.through_sh(self.call(), env=self.hook_env(PATH=str(self.bin)), shell="/bin/sh")
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, b"", b""))
        self.assertEqual(self.claims(), [])

    def test_a_payload_over_the_cap_is_silent_and_exit_zero(self):
        proc = self.through_sh(edit_payload("Write", {"file_path": self.target, "content": "x" * (8 * 1024 * 1024)}, cwd=str(self.app)))
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, b"", b""))
        self.assertEqual(self.git_calls(), [])

    def test_the_allow_path_loads_none_of_the_heavy_modules(self):
        proc = self.jam("hook", "guard", stdin=self.call(str(self.app / "src" / "new.ts")), env=self.hook_env(), flags=("-I", "-X", "importtime"))
        self.assertExit(proc, 0)
        imported = [line.rsplit("|", 1)[-1].strip() for line in proc.err.splitlines() if line.startswith("import time:")]
        self.assertIn("jam.guard", imported)
        for name in HEAVY:
            with self.subTest(module=name):
                self.assertNotIn(name, imported)

    def test_the_hook_does_not_use_the_session_id_of_the_environment_or_the_job_directory(self):
        proc = self.through_sh(self.call(), env=self.hook_env(CLAUDE_CODE_SESSION_ID="other-session", CLAUDE_JOB_DIR=str(self.root / "jobs" / "zzzz9999")))
        self.assertIn(f"denied.{SESSION_ID}.", "".join(self.claims()))
        self.assertTrue(proc.stdout)


class GuardWrapperTest(GuardLauncherTestCase):
    def test_a_stdin_that_never_closes_ends_by_the_alarm_and_the_wrapper_turns_the_signal_into_exit_zero(self):
        proc = subprocess.Popen(["sh", "-c", GUARD_COMMAND], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(self.root), env=self.hook_env())
        self.addCleanup(self.reap, proc)
        self.assertEqual(proc.wait(timeout=4), 0)
        self.assertEqual(proc.stdout.read(), b"")

    def test_a_plugin_root_that_is_gone_is_exit_zero_with_the_wrapper_and_exit_two_without_it(self):
        # The trap the wrapper exists for: Python exits with 2 when it cannot open the script, and 2 is the code that blocks a tool call.
        gone = self.hook_env(CLAUDE_PLUGIN_ROOT=str(self.root / "gone"))
        wrapped = self.through_sh(self.call(), env=gone)
        self.assertEqual((wrapped.returncode, wrapped.stdout), (0, b""))
        bare = self.through_sh(self.call(), command=LAUNCH + "guard", env=gone)
        self.assertEqual((bare.returncode, bare.stdout), (2, b""))

    def test_a_plugin_root_the_shell_would_misparse_is_denied_once_and_only_a_pasted_placeholder_would_block(self):
        # #15: the shell expands the exported root and never parses its name. A platform that pastes `${...}` in, as the plugins reference describes, finds none
        # in the entry; the braced form it replaced would then hand the shell the name itself, and a parse error exits 2 before `||` (D14).
        root = self.awkward_root()
        env = self.hook_env(CLAUDE_PLUGIN_ROOT=str(root))
        first = self.through_sh(self.call(), env=env)
        self.assertEqual((first.returncode, first.stderr), (0, b""))
        self.assertEqual(json.loads(first.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        second = self.through_sh(self.call(), env=env)
        self.assertEqual((second.returncode, second.stdout, second.stderr), (0, b"", b""))
        self.assertEqual(GUARD_COMMAND.replace("${CLAUDE_PLUGIN_ROOT}", str(root)), GUARD_COMMAND)
        braced = GUARD_COMMAND.replace("$CLAUDE_PLUGIN_ROOT", "${CLAUDE_PLUGIN_ROOT}")
        pasted = self.through_sh(self.call(), command=braced.replace("${CLAUDE_PLUGIN_ROOT}", str(root)), env=env)
        self.assertEqual((pasted.returncode, pasted.stdout), (2, b""))

    def test_an_interpreter_that_is_not_there_is_exit_zero_with_the_wrapper(self):
        (self.bin / "python3").unlink()
        proc = self.through_sh(self.call(), env=self.hook_env(PATH=str(self.bin)), shell="/bin/sh")
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))


if __name__ == "__main__":
    unittest.main()
