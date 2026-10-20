"""Smoke tests for `python -I scripts/jam hook ...`, run in a subprocess the way the platform runs a hook.

A fake `claude` is the only one on PATH and none of these tests starts a session.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from test_launcher import LAUNCHER, ROOT, SESSION_ID, LauncherTestCase
from test_operations import lazy
from test_plugin_structure import HOOKS_JSON, load_json

notice = lazy("jam.harness.notice")

SAMPLE = json.dumps(
    {
        "session_id": SESSION_ID,
        "transcript_path": "/work/t/aaaa1111.jsonl",
        "cwd": "/work/app",
        "permission_mode": "default",
        "hook_event_name": "SessionStart",
        "source": "startup",
    }
).encode("utf-8")


def envelope(text):
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}


def hook_command(name):
    """The literal command string the platform would run for `hook <name>`."""
    commands = [hook["command"] for groups in load_json(HOOKS_JSON)["hooks"].values() for group in groups for hook in group["hooks"]]
    (command,) = [command for command in commands if command.endswith(f" hook {name}")]
    return command


class HookLauncherTestCase(LauncherTestCase):
    def setUp(self):
        super().setUp()
        self.data = self.root / "jam data"

    def silent(self, proc):
        self.assertExit(proc, 0)
        self.assertEqual((proc.out, proc.err), ("", ""))

    def hook_with(self, name, **options):
        """`hook <name>` fed SAMPLE, with the streams and the child setup of the platform replaced by `options`."""
        return subprocess.run(
            [sys.executable, "-I", str(LAUNCHER), "hook", name],
            **{"input": SAMPLE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "cwd": str(self.root), "env": self.env(), "timeout": 60, **options},
        )


class NoticeTest(HookLauncherTestCase):
    def test_it_prints_exactly_one_envelope_line_and_nothing_on_stderr(self):
        proc = self.jam("hook", "notice", stdin=SAMPLE, env=self.env(CLAUDE_PLUGIN_DATA=str(self.data)))
        self.assertExit(proc, 0)
        self.assertEqual(proc.err, "")
        self.assertTrue(proc.out.endswith("\n") and proc.out.count("\n") == 1, proc.out)
        prefix = f"python3 -I {shlex.quote(str(ROOT / 'scripts' / 'jam'))} --data-dir {shlex.quote(str(self.data))}"
        self.assertEqual(json.loads(proc.out), envelope(notice.session_notice(prefix, SESSION_ID)))

    def test_without_the_data_dir_variable_it_still_prints_the_notice(self):
        proc = self.jam("hook", "notice", stdin=SAMPLE)
        self.assertExit(proc, 0)
        self.assertIn("No usable data directory was found", json.loads(proc.out)["hookSpecificOutput"]["additionalContext"])

    def test_empty_and_garbled_stdin_still_get_the_notice_without_the_id_line(self):
        for stdin in (b"", b"not json", b"[]"):
            with self.subTest(stdin=stdin):
                proc = self.jam("hook", "notice", stdin=stdin)
                self.assertExit(proc, 0)
                text = json.loads(proc.out)["hookSpecificOutput"]["additionalContext"]
                self.assertNotIn("This session id", text)

    def test_decoy_modules_in_the_working_directory_are_ignored(self):
        decoy = self.root / "decoy"
        decoy.mkdir()
        (decoy / "json.py").write_text("raise ImportError('decoy json was imported')\n", encoding="utf-8")
        proc = self.jam("hook", "notice", stdin=SAMPLE, cwd=decoy)
        self.assertExit(proc, 0)
        self.assertNotIn("decoy", proc.out + proc.err)

    def test_the_notice_path_never_loads_the_command_line_or_the_registry(self):
        proc = self.jam("hook", "notice", stdin=SAMPLE, flags=("-I", "-X", "importtime"))
        self.assertExit(proc, 0)
        imported = [line.rsplit("|", 1)[-1].strip() for line in proc.err.splitlines() if line.startswith("import time:")]
        self.assertIn("jam.harness.claude_hooks", imported)
        for name in ("jam.cli", "jam.compose", "jam.mcp", "jam.operations", "jam.service", "jam.registry", "argparse", "subprocess", "tempfile"):
            with self.subTest(module=name):
                self.assertNotIn(name, imported)

    def test_a_reader_that_has_gone_is_not_an_error_and_leaves_no_traceback(self):
        proc = self.jam_without_reader("hook", "notice", stdin=SAMPLE)
        self.assertEqual(proc.returncode, 0, proc.err)
        self.assertIn(proc.err, ("", "BrokenPipeError\n"))

    def test_a_stdin_with_nothing_written_yet_still_gets_the_notice_without_the_id_line(self):
        reader, writer = os.pipe()  # the writer stays open and silent, so a non-blocking read answers None instead of waiting
        os.set_blocking(reader, False)
        try:
            proc = self.hook_with("notice", input=None, stdin=reader)
        finally:
            os.close(reader)
            os.close(writer)
        self.assertEqual((proc.returncode, proc.stderr), (0, b""))
        text = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Run jam through Bash exactly as: ", text)
        self.assertNotIn("This session id", text)

    def test_a_stdout_that_cannot_be_written_is_exit_zero_with_only_the_type_on_stderr(self):
        readonly = self.root / "readonly.txt"
        readonly.write_text("", encoding="utf-8")
        with readonly.open("rb") as stdout:  # the flush of the notice fails with EBADF, not with a broken pipe
            proc = self.hook_with("notice", stdout=stdout)
        self.assertEqual((proc.returncode, proc.stderr), (0, b"OSError\n"))

    def test_a_session_with_descriptors_one_and_two_closed_is_still_exit_zero(self):
        for name in ("notice", "prune"):
            with self.subTest(hook=name):
                proc = self.hook_with(name, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=lambda: (os.close(1), os.close(2)))
                self.assertEqual(proc.returncode, 0)


class QuietTest(HookLauncherTestCase):
    def test_hook_alone_and_an_unknown_hook_do_nothing_and_exit_zero(self):
        self.silent(self.jam("hook", stdin=SAMPLE))
        self.silent(self.jam("hook", "bogus", "--x", stdin=SAMPLE))

    def test_hook_is_recognised_only_as_the_first_argument(self):
        self.assertExit(self.jam("--data-dir", str(self.data), "hook", "notice", stdin=SAMPLE), 2)

    def test_an_unknown_ordinary_command_is_still_a_usage_error(self):
        self.assertExit(self.jam("bogus"), 2)

    def test_the_help_does_not_list_the_hook_verb(self):
        proc = self.jam("--help")
        self.assertExit(proc, 0)
        self.assertNotIn("hook", proc.out)


class PruneTest(HookLauncherTestCase):
    def test_it_removes_only_notes_older_than_thirty_days_and_prints_nothing(self):
        sessions = self.data / "sessions-v1"
        sessions.mkdir(parents=True)
        old, recent = sessions / "aaaa1111.json", sessions / "bbbb2222.json"
        for path, days in ((old, 31), (recent, 1)):
            path.write_text('{"spawned":true}\n', encoding="utf-8")
            moment = time.time() - days * 24 * 3600
            os.utime(path, (moment, moment))
        self.silent(self.jam("hook", "prune", stdin=SAMPLE, env=self.env(CLAUDE_PLUGIN_DATA=str(self.data))))
        self.assertEqual((old.exists(), recent.exists()), (False, True))

    def test_without_a_data_dir_it_does_nothing(self):
        self.silent(self.jam("hook", "prune", stdin=SAMPLE))
        self.assertEqual(list(self.root.glob("jam data*")), [])


class AlarmTest(HookLauncherTestCase):
    def test_a_stdin_that_never_closes_ends_the_hook_by_the_alarm_and_not_by_a_handler(self):
        proc = self.hung("notice")
        self.assertEqual(proc.wait(timeout=10), -signal.SIGALRM)
        self.assertEqual(proc.stdout.read(), b"")

    def test_the_alarm_ends_prune_too(self):
        proc = self.hung("prune")
        self.assertEqual(proc.wait(timeout=10), -signal.SIGALRM)

    def test_an_inherited_ignore_of_the_alarm_signal_does_not_defeat_it(self):
        proc = self.hung("notice", ignore_alarm=True)
        self.assertEqual(proc.wait(timeout=10), -signal.SIGALRM)

    def test_an_inherited_block_of_the_alarm_signal_does_not_defeat_it_either(self):
        for name in ("notice", "prune"):
            with self.subTest(hook=name):
                proc = self.hung(name, ignore_alarm=True, block_alarm=True)
                self.assertEqual(proc.wait(timeout=10), -signal.SIGALRM)

    def hung(self, name, ignore_alarm=False, block_alarm=False):
        """A running hook whose stdin is never written to or closed; the child may start with the alarm signal ignored and blocked."""

        def inherited():
            if ignore_alarm:
                signal.signal(signal.SIGALRM, signal.SIG_IGN)
            if block_alarm:
                signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})

        proc = subprocess.Popen(
            [sys.executable, "-I", str(LAUNCHER), "hook", name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.root),
            env=self.env(CLAUDE_PLUGIN_DATA=str(self.data)),
            preexec_fn=inherited,
        )
        self.addCleanup(self.reap, proc)
        return proc


class PlatformCommandTest(HookLauncherTestCase):
    """The very strings in hooks/hooks.json, run through a shell the way the platform runs them."""

    def run_through_sh(self, name):
        wrapper = self.bin / "python3"  # a closed PATH would otherwise decide which python3 these commands meet
        wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        return subprocess.run(
            ["sh", "-c", hook_command(name)],
            input=SAMPLE,
            capture_output=True,
            cwd=str(self.root),
            env=self.env(CLAUDE_PLUGIN_ROOT=str(ROOT), CLAUDE_PLUGIN_DATA=str(self.data)),
            timeout=60,
        )

    def test_the_notice_command_exits_zero_and_prints_valid_json_naming_this_plugins_launcher(self):
        proc = self.run_through_sh("notice")
        self.assertEqual((proc.returncode, proc.stderr), (0, b""))
        text = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(shlex.quote(str(ROOT / "scripts" / "jam")), text)

    def test_the_prune_command_exits_zero_and_prints_nothing(self):
        proc = self.run_through_sh("prune")
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, b"", b""))


if __name__ == "__main__":
    unittest.main()
