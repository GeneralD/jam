"""Tests for the guard handler's state and failure modes: claims on disk, the throttle, git's answers, bad input, the reason text.

The claims are the real ones on a temp directory and the clock is the real one
unless a test says otherwise: a fake of either could not show that the hour is a
whole number or that a file name is built the way the readers expect.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unittest
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

import gitrepo
from guardcase import ALARMS, CONFIG_VAR, HOME_VAR, PROJECT_VAR, GuardCase, edit_payload, real_ignored
from test_claude_env import RecordingEnv
from test_claude_hooks import BAD_STDIN, DATA_VAR, BrokenStdout, run
from test_operations import SESSION_ID

HOUR = 490000


def key_of(path):
    return hashlib.sha256(os.fsencode(str(path))).hexdigest()[:16]


class DenialStateTest(GuardCase):
    def test_a_denial_leaves_the_pair_claim_and_the_first_slot_of_the_current_hour(self):
        before = int(time.time() // 3600)
        self.assertDenied(self.guarded(), self.other)
        after = int(time.time() // 3600)
        names = self.claim_files()
        self.assertEqual(names[0], f"denied.{SESSION_ID}.{key_of(self.other / '.git')}")
        slot = re.fullmatch(r"slot\.(\d+)\.0", names[1])
        self.assertTrue(slot and before <= int(slot.group(1)) <= after, names)
        self.assertEqual(len(names), 2)

    def test_the_identical_reissue_is_silent_and_never_reaches_git_again(self):
        self.assertDenied(self.guarded(), self.other)
        self.assertSilent(self.guarded())
        self.ignored.assert_called_once_with(self.target)  # the resolved path of the edit, asked about once

    def test_another_file_of_the_same_repository_is_silent_after_the_denial(self):
        self.assertDenied(self.guarded(), self.other)
        self.assertSilent(self.write_to(self.other / "docs" / "readme.md"))

    def test_a_second_repository_is_denied_once_more_and_a_second_session_once_for_the_first(self):
        third = self.plain("third")
        self.assertDenied(self.guarded(), self.other)
        self.assertDenied(self.write_to(third / "f.txt"), third)
        self.assertDenied(self.guarded(session_id="session-two"), self.other)
        self.assertSilent(self.guarded(session_id="session-two"))

    def test_the_denial_is_printed_after_the_claims_exist_so_a_lost_line_cannot_come_back(self):
        result = self.run_with_broken_stdout()
        self.assertEqual((result.code, result.out, result.err), (0, "", "BrokenPipeError\n"))
        self.assertEqual(len(self.claim_files()), 2)
        self.assertSilent(self.guarded())

    def test_directories_are_private_and_files_are_readable_by_the_owner_only_whatever_the_umask(self):
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)
        self.assertDenied(self.guarded(), self.other)
        self.assertEqual(self.data.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        for name in self.claim_files():
            with self.subTest(name=name):
                self.assertEqual((self.state / name).stat().st_mode & 0o777, 0o600)

    def run_with_broken_stdout(self):
        return run("guard", stdin=edit_payload("Write", {"file_path": self.target}), env={DATA_VAR: str(self.data), PROJECT_VAR: str(self.app)}, stdout=BrokenStdout())


class IgnoredPathTest(GuardCase):
    def test_a_path_git_ignores_is_silent_and_burns_no_claim(self):
        self.ignored.return_value = True
        self.assertSilent(self.guarded())
        self.assertEqual(self.claim_files(), [])

    def test_a_path_git_cannot_judge_is_silent_and_burns_no_claim(self):
        self.ignored.return_value = None
        self.assertSilent(self.guarded())
        self.assertEqual(self.claim_files(), [])

    def test_a_failure_in_git_is_exit_zero_with_only_the_type_and_no_claim(self):
        self.ignored.side_effect = RuntimeError("secret detail in /some/private/path")
        result = self.guarded()
        self.assertEqual((result.code, result.out, result.err, result.alarms), (0, "", "RuntimeError\n", ALARMS))
        self.assertEqual(self.claim_files(), [])

    def test_the_claim_was_not_burned_so_the_same_edit_is_denied_once_git_says_it_is_not_ignored(self):
        self.ignored.return_value = True
        self.assertSilent(self.guarded())
        self.ignored.return_value = False
        self.assertDenied(self.guarded(), self.other)


@unittest.skipIf(gitrepo.GIT is None, "git is not installed")
class RealGitTest(GuardCase):
    """The one place the handler meets a real git: a sandbox that cannot see the developer's configuration answers `check-ignore`."""

    def test_an_ignored_path_is_silent_and_a_path_git_would_track_is_denied(self):
        home = self.root / "home"
        home.mkdir()
        repository = self.root / "real"
        repository.mkdir()
        gitrepo.git(home, repository, "init", "-q")
        (repository / ".gitignore").write_text("*.log\n", encoding="utf-8")
        self.ignored.side_effect = lambda path: real_ignored(path, base_env=gitrepo.home_env(home))
        self.assertSilent(self.write_to(repository / "build.log"))
        self.assertEqual(self.claim_files(), [])
        self.assertDenied(self.write_to(repository / "src" / "index.ts"), repository)


class MemoryLessTest(GuardCase):
    """A hook that cannot remember what it said never speaks."""

    def test_an_unset_empty_or_relative_data_directory_is_silent_and_creates_nothing(self):
        for value in (None, "", "relative/data"):
            with self.subTest(value=value):
                self.assertSilent(self.guarded(env={DATA_VAR: value}))
        self.assertFalse(os.path.exists("relative"))
        self.assertFalse(self.data.exists())
        self.ignored.assert_not_called()

    def test_a_data_directory_that_cannot_be_created_is_silent(self):
        self.data.write_text("a file where the directory should be", encoding="utf-8")
        self.assertSilent(self.guarded())

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "a permission bit does not stop root")
    def test_a_data_directory_that_cannot_be_written_is_silent(self):
        self.data.mkdir(mode=0o500)
        self.addCleanup(self.data.chmod, 0o700)
        self.assertSilent(self.guarded())
        self.assertEqual(os.listdir(self.data), [])


class ExemptionTest(GuardCase):
    def test_a_session_with_the_worker_mark_is_silent_before_any_path_or_git_work(self):
        # D14-1: the whole-session exemption is one clause of the decision.
        self.state.mkdir(parents=True)
        (self.state / f"worker.{SESSION_ID}").write_bytes(b"")
        self.assertSilent(self.guarded())
        self.ignored.assert_not_called()
        self.assertEqual(self.claim_files(), [f"worker.{SESSION_ID}"])

    def test_the_mark_belongs_to_its_session_alone(self):
        self.state.mkdir(parents=True)
        (self.state / f"worker.{SESSION_ID}").write_bytes(b"")
        self.assertDenied(self.guarded(session_id="session-two"), self.other)

    def test_a_full_hour_makes_the_guard_silent_before_git_is_asked(self):
        # D14-2: the throttle is the slot clauses of the decision over one constant in the claims.
        hour = int(time.time() // 3600)
        self.state.mkdir(parents=True)
        for number in (hour, hour + 1):  # the clock may tick over while the test runs
            (self.state / f"slot.{number}.19").write_bytes(b"")
        self.assertSilent(self.guarded())
        self.ignored.assert_not_called()

    def test_twenty_denials_fill_an_hour_and_the_twenty_first_passes_until_the_next_hour(self):
        with mock.patch("jam.harness.claude_hooks.time.time", return_value=HOUR * 3600 + 5.5):  # a float, as the real clock gives
            denied = [self.guarded(session_id=self.fresh()).out != "" for _ in range(21)]
            self.assertEqual(denied, [True] * 20 + [False])
            self.assertEqual(sorted(name for name in self.claim_files() if name.startswith("slot.")), sorted(f"slot.{HOUR}.{number}" for number in range(20)))
        with mock.patch("jam.harness.claude_hooks.time.time", return_value=(HOUR + 1) * 3600):
            self.assertDenied(self.guarded(session_id=self.fresh()), self.other)


class FailOpenTest(GuardCase):
    def test_every_unusable_payload_is_exit_zero_with_nothing_printed_and_nothing_created(self):
        for name, stdin in BAD_STDIN.items():
            with self.subTest(stdin=name):
                result = run("guard", stdin=stdin, env={DATA_VAR: str(self.data), PROJECT_VAR: str(self.app)})
                self.assertEqual((result.code, result.out, result.err, result.alarms), (0, "", "", ALARMS))
        self.assertFalse(self.data.exists())

    def test_the_stdin_cap_of_the_guard_is_eight_mebibytes_and_not_the_notices_quarter_mebibyte(self):
        big = edit_payload("Write", {"file_path": self.target, "content": "x" * (300 * 1024)})
        self.assertDenied(run("guard", stdin=big, env={DATA_VAR: str(self.data), PROJECT_VAR: str(self.app)}), self.other)
        huge = edit_payload("Write", {"file_path": self.target, "content": "x" * (8 * 1024 * 1024)})
        self.assertSilent(run("guard", stdin=huge, env={DATA_VAR: str(self.data), PROJECT_VAR: str(self.app)}))

    def test_a_failing_decision_is_exit_zero_with_only_the_type_on_stderr(self):
        with mock.patch("jam.guard.decide", side_effect=RuntimeError("secret detail in /some/private/path")):
            result = self.guarded()
        self.assertEqual((result.code, result.out, result.err, result.alarms), (0, "", "RuntimeError\n", ALARMS))

    def test_only_the_four_documented_variables_are_ever_read(self):
        # The config variable is left unset so that the home directory, its fallback, is read too.
        environment = {DATA_VAR: str(self.data), PROJECT_VAR: str(self.app), HOME_VAR: str(self.root / "home"), "CLAUDE_CODE_SESSION_ACCESS_TOKEN": "planted-token"}
        env = RecordingEnv(environment)
        result = run("guard", stdin=edit_payload("Write", {"file_path": self.target}), env=env)
        self.assertDenied(result, self.other)
        self.assertEqual(set(env.reads), {DATA_VAR, PROJECT_VAR, CONFIG_VAR, HOME_VAR})


class ReasonTest(GuardCase):
    def reason_of(self, result):
        return json.loads(result.out)["hookSpecificOutput"]["permissionDecisionReason"]

    def test_the_reason_names_the_root_is_short_and_has_no_control_character(self):
        reason = self.reason_of(self.guarded())
        self.assertIn(f"({self.other})", reason)
        self.assertLess(len(reason), 900)
        self.assertIsNone(re.search(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]", reason))

    def test_a_root_with_a_line_feed_in_its_name_is_replaced_by_the_constant_phrase(self):
        odd = self.plain("odd\nname")
        reason = self.reason_of(self.write_to(odd / "f.txt"))
        self.assertIn("(the repository containing the file)", reason)
        self.assertNotIn("odd", reason)

    def test_a_root_with_a_c1_control_or_a_line_separator_or_a_bidi_mark_in_its_name_is_replaced_by_the_constant_phrase(self):
        for number, char in enumerate(("\x85", "\x9b", "\u2028", "\u202e")):
            with self.subTest(char=f"U+{ord(char):04X}"):
                odd = self.plain(f"odd{number}{char}name")
                reason = self.reason_of(self.write_to(odd / "f.txt"))
                self.assertIn("(the repository containing the file)", reason)
                self.assertNotIn("odd", reason)

    def test_a_root_of_more_than_two_hundred_characters_is_replaced_by_the_constant_phrase(self):
        long = self.plain("x" * 210)
        self.assertGreater(len(str(long)), 200)
        self.assertIn("(the repository containing the file)", self.reason_of(self.write_to(long / "f.txt")))

    def test_a_denial_is_one_ascii_line_with_a_single_line_feed(self):
        out = self.guarded().out
        self.assertEqual((out.count("\n"), out.endswith("\n"), out.isascii()), (1, True, True))


if __name__ == "__main__":
    unittest.main()
