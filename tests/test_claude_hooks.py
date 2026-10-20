"""Tests for the Claude Code hook entry: the dispatcher and the `notice` and `prune` handlers.

Everything runs in process with injected streams, environment and alarm, so no
test arms a real alarm, touches a real plugin data directory or starts claude.
"""

from __future__ import annotations

import collections
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

from test_claude_env import RecordingEnv
from test_operations import SESSION_ID, lazy

hooks = lazy("jam.harness.claude_hooks")
compose = lazy("jam.compose")

SRC = Path(__file__).resolve().parent.parent / "src"
DATA_VAR = "CLAUDE_PLUGIN_DATA"
DAY = 24 * 3600.0
FILE_FUNCTIONS = ("os.stat", "os.lstat", "os.scandir", "os.listdir", "os.mkdir", "os.makedirs", "os.access", "os.getcwd", "builtins.open", "io.open")


def payload(**fields):
    base = {"session_id": SESSION_ID, "transcript_path": "/work/t/aaaa1111.jsonl", "cwd": "/work/app", "permission_mode": "default", "hook_event_name": "SessionStart", "source": "startup"}
    return json.dumps({**base, **fields}).encode("utf-8")


Result = collections.namedtuple("Result", "code out err alarms")


def run(*argv, stdin=None, env=None, stdout=None):
    out, err, alarms = io.StringIO(), io.StringIO(), []
    code = hooks.main(list(argv), env={} if env is None else env, stdin=io.BytesIO(payload() if stdin is None else stdin), stdout=out if stdout is None else stdout, stderr=err, arm=alarms.append)
    return Result(code, out.getvalue(), err.getvalue(), alarms)


def context_of(result):
    """The notice text of a result that carries exactly one envelope line."""
    if not (result.out.endswith("\n") and result.out.count("\n") == 1):
        raise AssertionError(f"not exactly one line: {result.out!r}")
    parsed = json.loads(result.out)
    if list(parsed) != ["hookSpecificOutput"] or parsed["hookSpecificOutput"]["hookEventName"] != "SessionStart":
        raise AssertionError(f"not a SessionStart envelope: {parsed!r}")
    return parsed["hookSpecificOutput"]["additionalContext"]


class BrokenStdout:
    def write(self, text):
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self):
        raise BrokenPipeError(32, "Broken pipe")


class DispatchTest(unittest.TestCase):
    def test_no_name_and_an_unknown_name_do_nothing_and_arm_nothing(self):
        for argv in ((), ("bogus",), ("bogus", "--x"), ("notice-ish",), ("",)):
            with self.subTest(argv=argv):
                result = run(*argv)
                self.assertEqual((result.code, result.out, result.err, result.alarms), (0, "", "", []))

    def test_the_table_holds_exactly_the_two_hooks_of_this_change(self):
        self.assertEqual(sorted(hooks.HOOKS), ["notice", "prune"])

    def test_each_hook_arms_its_own_alarm_and_cancels_it_at_the_end(self):
        self.assertEqual(run("notice").alarms, [3, 0])
        self.assertEqual(run("prune").alarms, [2, 0])


# stdin the notice must survive: it is printed whenever the handler runs to completion, whatever the payload (D13, "Fail open").
BAD_STDIN = {
    "empty": b"",
    "whitespace": b" \n\t ",
    "array": b"[]",
    "string": b'"x"',
    "not utf-8": b"\xff\xfe\x00{",
    "truncated": b'{"session_id":',
    "oversized": b'{"session_id":"' + b"a" * (256 * 1024) + b'"}',
    "deeply nested": b"[" * 200000,
}


class FailOpenTest(unittest.TestCase):
    def test_the_notice_survives_every_unusable_payload_and_only_loses_the_id_line(self):
        for name, stdin in BAD_STDIN.items():
            with self.subTest(stdin=name):
                result = run("notice", stdin=stdin)
                self.assertEqual((result.code, result.err), (0, ""))
                text = context_of(result)
                self.assertIn("Run jam through Bash exactly as: ", text)
                self.assertNotIn("This session id", text)

    def test_prune_prints_nothing_whatever_the_payload(self):
        for name, stdin in BAD_STDIN.items():
            with self.subTest(stdin=name):
                result = run("prune", stdin=stdin)
                self.assertEqual((result.code, result.out, result.err), (0, "", ""))

    def test_a_broken_stdout_is_exit_zero_with_only_the_type_name_on_stderr(self):
        result = run("notice", stdout=BrokenStdout())
        self.assertEqual((result.code, result.err), (0, "BrokenPipeError\n"))
        self.assertEqual(result.alarms, [3, 0])

    def test_a_session_with_neither_stdout_nor_stderr_is_still_exit_zero(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):  # descriptors 1 and 2 closed before the interpreter started
            code = hooks.main(["notice"], env={}, stdin=io.BytesIO(payload()), arm=lambda seconds: None)
        self.assertEqual(code, 0)

    def test_a_raising_handler_is_exit_zero_silent_and_leaks_only_the_type(self):
        def boom(payload, env):
            raise RuntimeError("secret detail in /some/private/path")

        for name in ("notice", "prune"):
            with self.subTest(hook=name), mock.patch.dict(hooks.HOOKS, {name: hooks.Hook(boom, 3)}):
                result = run(name)
                self.assertEqual((result.code, result.out, result.err), (0, "", "RuntimeError\n"))
                self.assertEqual(result.alarms, [3, 0])

    def test_the_exit_code_is_never_two_the_blocking_one(self):
        for argv in (("notice",), ("prune",), ("bogus",), ()):
            for stdin in BAD_STDIN.values():
                self.assertEqual(run(*argv, stdin=stdin).code, 0)


class NoticeHandlerTest(unittest.TestCase):
    def test_it_prints_one_envelope_with_the_session_id_the_plugin_root_and_the_data_dir(self):
        text = context_of(run("notice", env={DATA_VAR: "/var/jam data"}))
        self.assertIn(f"This session id: {SESSION_ID}", text)
        self.assertIn(f"python3 -I {hooks.PLUGIN_ROOT}/scripts/jam --data-dir '/var/jam data' COMMAND", text)

    def test_it_is_the_same_for_every_source_including_one_not_known_yet(self):
        env = {DATA_VAR: "/var/jam"}
        texts = {source: context_of(run("notice", env=env, stdin=payload(source=source))) for source in ("startup", "resume", "clear", "compact", "fork", "from-the-future", 7, None)}
        self.assertEqual(len(set(texts.values())), 1, texts.keys())

    def test_it_works_without_the_data_dir_variable(self):
        text = context_of(run("notice"))
        self.assertIn("No usable data directory was found", text)
        self.assertNotIn("--data-dir", text.split("\n")[1])

    def test_it_ignores_every_variable_but_the_data_dir(self):
        env = {"CLAUDE_PLUGIN_ROOT": "/elsewhere", "CLAUDE_CODE_SESSION_ACCESS_TOKEN": "planted-token", DATA_VAR: "/var/jam"}
        text = context_of(run("notice", env=env))
        self.assertNotIn("/elsewhere", text)
        self.assertNotIn("planted-token", text)

    def test_a_session_id_that_is_not_an_id_is_left_out(self):
        for value in ("../etc", "a b", 5, None, ["x"]):
            with self.subTest(value=value):
                self.assertNotIn("This session id", context_of(run("notice", stdin=payload(session_id=value))))

    def test_it_touches_no_file_at_all_and_does_not_create_the_data_dir(self):
        root = hooks.PLUGIN_ROOT  # import everything before the file functions are taken away
        with tempfile.TemporaryDirectory() as scratch:
            missing = os.path.join(scratch, "not", "there")
            with contextlib.ExitStack() as stack:
                for name in FILE_FUNCTIONS:
                    stack.enter_context(mock.patch(name, side_effect=AssertionError(f"{name} was called")))
                result = run("notice", env={DATA_VAR: missing})
            self.assertEqual(result.err, "")
            self.assertIn(missing, context_of(result))
            self.assertIn(str(root), context_of(result))
            self.assertFalse(os.path.exists(os.path.join(scratch, "not")))


class EnvironmentReadsTest(unittest.TestCase):
    """One of the CLAUDE_* session variables is a credential; a hook reads the data dir variable and nothing else."""

    def test_each_hook_reads_only_the_data_dir_variable(self):
        for name in ("notice", "prune"):
            with self.subTest(hook=name), tempfile.TemporaryDirectory() as scratch:
                env = RecordingEnv({DATA_VAR: os.path.join(scratch, "data"), "CLAUDE_CODE_SESSION_ACCESS_TOKEN": "planted-token", "CLAUDE_CODE_SESSION_ID": SESSION_ID, "CLAUDE_PLUGIN_ROOT": "/elsewhere"})
                result = run(name, env=env)
                self.assertEqual((result.code, result.err), (0, ""))
                self.assertEqual(set(env.reads), {DATA_VAR})


class PruneHandlerTest(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.data, True)
        self.sessions = self.data / "sessions-v1"

    def note(self, name, days):
        self.sessions.mkdir(exist_ok=True)
        path = self.sessions / f"{name}.json"
        path.write_text('{"spawned":true}\n', encoding="utf-8")
        moment = time.time() - days * DAY
        os.utime(path, (moment, moment))
        return path

    def listing(self):
        return sorted(str(path.relative_to(self.data)) for path in self.data.rglob("*"))

    def test_only_the_note_older_than_thirty_days_goes_and_nothing_is_printed(self):
        old, recent = self.note("aaaa1111", 31), self.note("bbbb2222", 1)
        result = run("prune", env={DATA_VAR: str(self.data)})
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_no_data_dir_a_relative_one_and_a_missing_registry_do_nothing_and_create_nothing(self):
        before = self.listing()
        for env in ({}, {DATA_VAR: ""}, {DATA_VAR: "relative/dir"}, {DATA_VAR: str(self.data)}, {DATA_VAR: str(self.data / "absent")}):
            with self.subTest(env=env):
                result = run("prune", env=env)
                self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertEqual(self.listing(), before)
        self.assertFalse((self.data / "absent").exists())

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "a permission bit does not stop root")
    def test_an_unreadable_registry_is_left_alone_without_a_word(self):
        kept = self.note("aaaa1111", 90)
        self.sessions.chmod(0)
        self.addCleanup(self.sessions.chmod, 0o700)  # registered after the rmtree, so it runs before it
        result = run("prune", env={DATA_VAR: str(self.data)})
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.sessions.chmod(0o700)
        self.assertTrue(kept.exists())


class PluginRootTest(unittest.TestCase):
    def test_the_two_derivations_of_the_plugin_root_agree(self):
        self.assertEqual(hooks.PLUGIN_ROOT, compose.PLUGIN_ROOT)

    def test_the_root_holds_the_launcher_the_notice_points_at(self):
        self.assertTrue((hooks.PLUGIN_ROOT / "scripts" / "jam").is_file())

    def test_importing_the_hook_and_building_the_notice_resolves_no_path(self):
        # Path resolution happens before the alarm is armed, or inside the notice, so it would be outside the bound: refuse it in a fresh interpreter.
        script = "\n".join([
            "import os.path, pathlib, sys",
            "def refused(*args, **kwargs):",
            "    raise AssertionError('a path was resolved')",
            "pathlib.Path.resolve = refused",
            "os.path.realpath = refused",
            "sys.path.insert(0, sys.argv[1])",
            "from jam.harness import claude_hooks",
            "claude_hooks.notice_text({}, {})",
        ])
        done = subprocess.run([sys.executable, "-I", "-c", script, str(SRC)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


class ImportGraphTest(unittest.TestCase):
    HEAVY = ("argparse", "subprocess", "tempfile", "jam.cli", "jam.compose", "jam.mcp", "jam.operations", "jam.service", "jam.registry")

    def test_importing_the_hook_entry_loads_none_of_the_heavy_modules(self):
        code = "import sys\nsys.path.insert(0, sys.argv[1])\nimport jam.harness.claude_hooks\nprint(' '.join(n for n in sys.argv[2:] if n in sys.modules))\n"
        proc = subprocess.run([sys.executable, "-I", "-c", code, str(SRC), *self.HEAVY], capture_output=True, text=True, timeout=60)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertEqual(proc.stdout.strip(), "", "these modules slow the hook down or break its isolation")


if __name__ == "__main__":
    unittest.main()
