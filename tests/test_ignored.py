"""Tests for the check-ignore wrapper: the one place the guard starts a process.

Most tests inject the runner and look at what it was asked to run. The real-git
tests pass a base environment whose `HOME` and `XDG_CONFIG_HOME` point at a
directory they own, so the developer's global excludes cannot decide the outcome.
"""

from __future__ import annotations

import collections
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

import gitrepo
from test_operations import lazy

repos = lazy("jam.repos")

Call = collections.namedtuple("Call", "argv kwargs")


class FakeRunner:
    """Answers with a canned exit code, or raises a canned error, and remembers every call."""

    def __init__(self, returncode=1, error=None):
        self.returncode, self.error, self.calls = returncode, error, []

    def __call__(self, argv, **kwargs):
        self.calls.append(Call(list(argv), kwargs))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(argv, self.returncode)


class TempTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)


class OutcomeTest(TempTestCase):
    def outcome(self, **runner_options):
        runner = FakeRunner(**runner_options)
        return repos.ignored(str(self.root / "f.txt"), runner=runner, base_env={})

    def test_exit_zero_is_ignored_and_exit_one_is_not(self):
        self.assertIs(self.outcome(returncode=0), True)
        self.assertIs(self.outcome(returncode=1), False)

    def test_every_other_exit_code_is_none(self):
        for code in (2, 3, 127, 128, 129, 255, -9, -14):
            with self.subTest(code=code):
                self.assertIsNone(self.outcome(returncode=code))

    def test_a_timeout_a_missing_git_and_any_other_failure_to_run_are_none(self):
        failures = [
            subprocess.TimeoutExpired(["git"], 1.0),
            FileNotFoundError(2, "No such file or directory", "git"),
            PermissionError(13, "Permission denied", "git"),
            NotADirectoryError(20, "Not a directory"),
            subprocess.SubprocessError("boom"),
            ValueError("embedded null byte"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.assertIsNone(self.outcome(error=failure))

    def test_a_failure_that_is_a_bug_in_the_caller_is_not_swallowed(self):
        with self.assertRaises(RuntimeError):
            self.outcome(error=RuntimeError("bug"))

    def test_what_is_not_an_absolute_path_without_nul_is_none_and_nothing_is_run(self):
        runner = FakeRunner()
        for bad in ("", "relative/f.txt", "a\0b", None, 5, b"/x"):
            with self.subTest(bad=repr(bad)):
                self.assertIsNone(repos.ignored(bad, runner=runner, base_env={}))
        self.assertEqual(runner.calls, [])


class InvocationTest(TempTestCase):
    def setUp(self):
        super().setUp()
        (self.root / "a").mkdir()
        self.target = str(self.root / "a" / "missing" / "deeper" / "f.txt")
        self.runner = FakeRunner()
        self.base = {"PATH": "/opt/jam/bin", "HOME": "/work/user", "XDG_CONFIG_HOME": "/work/user/.cfg", "LANG": "C"}

    def call(self, base=None):
        repos.ignored(self.target, runner=self.runner, base_env=self.base if base is None else base)
        (call,) = self.runner.calls
        return call

    def test_it_asks_check_ignore_quietly_with_the_fsmonitor_off_and_the_path_after_a_double_dash(self):
        self.assertEqual(self.call().argv, ["git", "-c", "core.fsmonitor=false", "check-ignore", "-q", "--", self.target])

    def test_it_runs_in_the_nearest_existing_directory_of_the_path(self):
        self.assertEqual(self.call().kwargs["cwd"], str(self.root / "a"))

    def test_it_waits_one_second_and_gives_the_process_no_streams(self):
        kwargs = self.call().kwargs
        self.assertEqual(kwargs["timeout"], 1.0)
        for stream in ("stdin", "stdout", "stderr"):
            with self.subTest(stream=stream):
                self.assertEqual(kwargs[stream], subprocess.DEVNULL)

    def test_it_starts_exactly_one_process_for_one_question(self):
        self.call()
        self.assertEqual(len(self.runner.calls), 1)

    def test_the_environment_has_no_git_variable_and_the_two_that_keep_git_quiet(self):
        seeded = {**self.base, "GIT_DIR": "/elsewhere", "GIT_INDEX_FILE": "/elsewhere/index", "GIT_WORK_TREE": "/elsewhere", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "1", "GIT_EXTERNAL_DIFF": "x"}
        env = self.call(seeded).kwargs["env"]
        self.assertEqual(sorted(name for name in env if name.startswith("GIT_")), ["GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT"])
        self.assertEqual((env["GIT_OPTIONAL_LOCKS"], env["GIT_TERMINAL_PROMPT"]), ("0", "0"))

    def test_every_other_variable_goes_through_so_the_users_own_configuration_still_applies(self):
        env = self.call().kwargs["env"]
        for name, value in self.base.items():
            with self.subTest(name=name):
                self.assertEqual(env[name], value)

    def test_the_base_environment_is_the_process_environment_unless_one_is_given(self):
        with mock.patch.dict(os.environ, {"GIT_DIR": "/elsewhere", "JAM_PROBE": "kept"}):
            repos.ignored(self.target, runner=self.runner)
        env = self.runner.calls[0].kwargs["env"]
        self.assertNotIn("GIT_DIR", env)
        self.assertEqual(env["JAM_PROBE"], "kept")

    def test_the_given_base_environment_is_not_modified(self):
        seeded = {**self.base, "GIT_DIR": "/elsewhere"}
        before = dict(seeded)
        self.call(seeded)
        self.assertEqual(seeded, before)

    def test_the_search_path_keeps_its_absolute_entries_in_order_and_drops_the_others(self):
        # An empty or relative entry is looked up in the child's own directory, which is inside the tree being asked about.
        cases = {
            "/opt/jam/bin:/usr/bin": "/opt/jam/bin:/usr/bin",
            ":/opt/jam/bin": "/opt/jam/bin",
            "/opt/jam/bin:": "/opt/jam/bin",
            "/opt/jam/bin::/usr/bin": "/opt/jam/bin:/usr/bin",
            "./node_modules/.bin:/opt/jam/bin": "/opt/jam/bin",
            "bin:/opt/jam/bin:.": "/opt/jam/bin",
            "../bin:/opt/jam/bin:~/bin": "/opt/jam/bin",
        }
        for given, kept in cases.items():
            with self.subTest(path=given):
                self.assertEqual(self.call({**self.base, "PATH": given}).kwargs["env"]["PATH"], kept)
            self.runner.calls.clear()

    def test_without_an_absolute_entry_the_search_path_is_the_default_one_and_never_empty(self):
        # An empty string would split to one empty entry, which is the current directory again.
        for given in ("", ":", ".", "bin", "./bin:../bin:", None):
            with self.subTest(path=given):
                base = {name: value for name, value in self.base.items() if name != "PATH"}
                path = self.call(base if given is None else {**base, "PATH": given}).kwargs["env"]["PATH"]
                self.assertEqual(path, os.defpath)
                self.assertTrue(all(os.path.isabs(entry) for entry in path.split(os.pathsep)))
            self.runner.calls.clear()

    def test_without_a_runner_it_is_subprocess_run_that_runs(self):
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertIs(repos.ignored(self.target, base_env={}), True)
        self.assertEqual(run.call_args.args[0][:2], ["git", "-c"])


@unittest.skipIf(os.name != "posix", "the executable bit and the search path are POSIX")
class PlantedGitTest(TempTestCase):
    """A repository must not be able to supply the `git` that is run to ask about it: the question runs inside its tree."""

    def setUp(self):
        super().setUp()
        self.home = self.root / "home"
        self.home.mkdir()
        self.marker = self.root / "marker"
        self.tree = self.root / "tree"
        (self.tree / "bin").mkdir(parents=True)

    def plant(self, directory):
        script = directory / "git"
        script.write_text(f'#!/bin/sh\n: > "{self.marker}"\nexit 1\n', encoding="utf-8")
        script.chmod(0o755)

    def ask(self, search):
        self.marker.unlink(missing_ok=True)  # one subtest's marker must not be taken for the next one's
        base = {"PATH": search, "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}
        return repos.ignored(str(self.tree / "f.txt"), base_env=base)

    def test_a_git_in_the_tree_is_never_run_through_an_empty_or_relative_search_path_entry(self):
        self.plant(self.tree)
        self.plant(self.tree / "bin")
        for search in (":/opt/jam/absent", "/opt/jam/absent:", "/opt/jam/absent::/opt/jam/absent", ".:/opt/jam/absent", "bin:/opt/jam/absent", "./bin:/opt/jam/absent", "", ":", "bin"):
            with self.subTest(path=search):
                self.ask(search)
                self.assertFalse(self.marker.exists())

    def test_the_planted_script_is_what_a_search_path_entry_naming_its_directory_runs(self):
        # Control: the plant works, so the absence of the marker above means something.
        self.plant(self.tree / "bin")
        self.assertIs(self.ask(str(self.tree / "bin")), False)
        self.assertTrue(self.marker.exists())


@unittest.skipIf(gitrepo.GIT is None, "git is not installed")
class AgainstRealGitTest(TempTestCase):
    def setUp(self):
        super().setUp()
        self.home = self.root / "home"
        self.home.mkdir()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        gitrepo.git(self.home, self.repo, "init", "-q")
        (self.repo / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
        (self.repo / "tracked.txt").write_text("x\n", encoding="utf-8")
        gitrepo.git(self.home, self.repo, "add", ".")
        gitrepo.git(self.home, self.repo, "commit", "-q", "-m", "first")
        self.base = gitrepo.home_env(self.home)

    def ignored(self, relative):
        return repos.ignored(str(self.repo / relative), base_env=self.base)

    def test_an_ignored_path_is_true_and_a_tracked_or_plain_one_is_false(self):
        (self.repo / "build").mkdir()
        self.assertIs(self.ignored("debug.log"), True)
        self.assertIs(self.ignored("build/out.bin"), True)
        self.assertIs(self.ignored("tracked.txt"), False)
        self.assertIs(self.ignored("untracked.txt"), False)
        self.assertIs(self.ignored("src/new/deeper/file.ts"), False)

    def test_the_users_own_global_excludes_decide_what_is_ignored(self):
        (self.home / "git").mkdir()
        (self.home / "git" / "ignore").write_text("*.scratch\n", encoding="utf-8")
        self.assertIs(self.ignored("notes.scratch"), True)

    def test_a_path_outside_the_repository_of_its_directory_is_none(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        gitrepo.git(self.home, elsewhere, "init", "-q")
        # The command runs in `elsewhere`, whose repository does not contain the path it is asked about.
        outside = str(self.repo / "debug.log")
        with mock.patch("jam.repos.nearest_directory", return_value=str(elsewhere)):
            self.assertIsNone(repos.ignored(outside, base_env=self.base))

    def test_a_fsmonitor_command_named_by_the_repository_is_never_run(self):
        marker = self.root / "marker"
        script = self.root / "fsmonitor.sh"
        script.write_text(f'#!/bin/sh\ntouch "{marker}"\nprintf "\\0"\n', encoding="utf-8")
        script.chmod(0o755)
        gitrepo.git(self.home, self.repo, "config", "core.fsmonitor", str(script))
        # Control: without the override this very command does run the script, so the check below can fail.
        subprocess.run([gitrepo.GIT, "check-ignore", "-q", "--", str(self.repo / "tracked.txt")], cwd=str(self.repo), env=gitrepo.sandbox_env(self.home), stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        if not marker.exists():
            self.skipTest("this git does not run the fsmonitor command for check-ignore")
        marker.unlink()
        self.assertIs(self.ignored("tracked.txt"), False)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
