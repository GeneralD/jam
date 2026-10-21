"""Tests for the guard half of the `prune` hook: stale deny claims and hour slots go, and the registry sweep is untouched.

Same harness as the other hook tests: everything in process, the environment
injected, no alarm armed. The data directory is always a temp directory.
"""

from __future__ import annotations

import inspect
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

from test_claude_hooks import DAY, DATA_VAR, run
from test_operations import lazy

hooks = lazy("jam.harness.claude_hooks")
registry = lazy("jam.registry")
claims = lazy("jam.claims")
sweep = lazy("jam.sweep")

SID = "aaaa1111-0000-4000-8000-000000000001"
KEY = "0123456789abcdef"
STALE = f"denied.{SID}.{KEY}"
SLOT = "slot.490000.3"


class PruneGuardTestCase(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.data, True)
        self.state = self.data / "guard-v1"
        self.sessions = self.data / "sessions-v1"

    def planted(self, directory, name, days):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text('{"spawned":true}\n' if directory == self.sessions else "", encoding="utf-8")
        moment = time.time() - days * DAY
        os.utime(path, (moment, moment))
        return path

    def pruned(self, **kwargs):
        return run("prune", env={DATA_VAR: str(self.data)}, **kwargs)

    def listing(self):
        return sorted(str(path.relative_to(self.data)) for path in self.data.rglob("*"))


class SweepTest(PruneGuardTestCase):
    def test_stale_deny_claims_and_hour_slots_go_and_recent_ones_stay_and_nothing_is_printed(self):
        gone = [self.planted(self.state, STALE, 31), self.planted(self.state, SLOT, 31)]
        kept = [self.planted(self.state, f"denied.{SID}.fedcba9876543210", 1), self.planted(self.state, "slot.490001.0", 1)]
        result = self.pruned()
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertEqual([path.exists() for path in gone], [False, False])
        self.assertEqual([path.exists() for path in kept], [True, True])

    def test_the_registry_notes_are_swept_in_the_same_run(self):
        note = self.planted(self.sessions, "aaaa1111.json", 31)
        claim = self.planted(self.state, STALE, 31)
        self.pruned()
        self.assertEqual((note.exists(), claim.exists()), (False, False))

    def test_only_claim_names_are_swept_and_directories_and_links_are_not(self):
        keep = [self.planted(self.state, name, 90) for name in ("notes.txt", f"denied.{SID}.short", f"denied.{SID}.{KEY.upper()}", "slot.490000", "slot.490000.100")]
        directory = self.state / "slot.1.2"
        directory.mkdir()
        os.utime(directory, (time.time() - 90 * DAY,) * 2)
        link = self.state / "slot.1.3"
        link.symlink_to(keep[0])
        self.pruned()
        self.assertTrue(all(path.exists() for path in keep))
        self.assertTrue(directory.is_dir())
        self.assertTrue(link.is_symlink())

    def test_the_age_limit_is_the_registrys_thirty_days(self):
        self.assertEqual(registry.STALE_AFTER, 30 * DAY)
        inside = self.planted(self.state, STALE, 29)
        outside = self.planted(self.state, SLOT, 31)
        self.pruned()
        self.assertEqual((inside.exists(), outside.exists()), (True, False))

    def test_it_creates_nothing_when_there_is_no_state_directory(self):
        self.data.mkdir(exist_ok=True)
        before = self.listing()
        self.assertEqual(self.pruned().err, "")
        self.assertEqual(self.listing(), before)
        self.assertFalse(self.state.exists())

    def test_no_data_dir_and_an_unusable_one_do_nothing(self):
        claim = self.planted(self.state, STALE, 90)
        for env in ({}, {DATA_VAR: ""}, {DATA_VAR: str(self.data / "absent")}):
            with self.subTest(env=env):
                result = run("prune", env=env)
                self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertTrue(claim.exists())
        self.assertFalse((self.data / "absent").exists())

    def test_a_relative_data_dir_is_never_resolved_against_the_working_directory(self):
        work = self.data / "work"
        claim = self.planted(work / "rel" / "guard-v1", STALE, 90)
        note = self.planted(work / "rel" / "sessions-v1", "aaaa1111.json", 90)
        previous = os.getcwd()
        os.chdir(work)
        self.addCleanup(os.chdir, previous)
        result = run("prune", env={DATA_VAR: "rel"})
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertEqual((claim.exists(), note.exists()), (True, True))

    def test_a_state_directory_that_is_a_regular_file_is_left_alone_without_a_word(self):
        self.data.mkdir(exist_ok=True)
        self.state.write_text("not a directory", encoding="utf-8")
        result = self.pruned()
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertEqual(self.state.read_text(encoding="utf-8"), "not a directory")


class LinkedDirectoryTest(PruneGuardTestCase):
    """A link in place of a state directory carries no sweep to its target, and the hook still ends quietly with exit 0."""

    def test_a_guard_directory_that_is_a_link_is_not_swept_through(self):
        outside = self.data / "outside"
        stale = self.planted(outside, STALE, 90)
        self.state.symlink_to(outside)
        result = self.pruned()
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertTrue(stale.exists())

    def test_a_registry_directory_that_is_a_link_is_not_pruned_through_and_the_guard_sweep_still_runs(self):
        outside = self.data / "outside"
        note = self.planted(outside, "aaaa1111.json", 90)
        self.sessions.symlink_to(outside)
        claim = self.planted(self.state, STALE, 31)
        result = self.pruned()
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertTrue(note.exists())
        self.assertFalse(claim.exists())


class WiringTest(PruneGuardTestCase):
    def test_the_sweep_is_handed_the_state_directory_the_claim_predicate_the_thirty_days_the_clock_a_cap_and_a_deadline(self):
        signature = inspect.signature(sweep.swept)  # the real one, before the patch
        with mock.patch("jam.sweep.swept", return_value=0) as swept:
            before = time.monotonic()
            self.pruned()
            after = time.monotonic()
        (given,) = [signature.bind(*call.args, **call.kwargs).arguments for call in swept.call_args_list if Path(call.args[0]) == self.state]
        self.assertEqual(given["directory"], str(self.state))
        self.assertIs(given["accept"], claims.is_state_name)
        self.assertEqual(given["max_age"], registry.STALE_AFTER)
        self.assertLess(abs(given["now"] - time.time()), 60)
        self.assertEqual(given["limit"], hooks.SWEEP_LIMIT)
        self.assertTrue(before + hooks.PRUNE_BUDGET <= given["deadline"] <= after + hooks.PRUNE_BUDGET)

    def test_the_cap_covers_everything_the_throttle_lets_pile_up_in_thirty_days_and_the_budget_is_below_the_alarm(self):
        self.assertGreaterEqual(hooks.SWEEP_LIMIT, claims.SLOTS_PER_HOUR * 24 * 30)
        self.assertLess(hooks.PRUNE_BUDGET, hooks.HOOKS["prune"].alarm)
        self.assertEqual(self.pruned().alarms, [2, 0])


class IndependenceTest(PruneGuardTestCase):
    """A failure in either sweep must not stop the other."""

    def setUp(self):
        super().setUp()
        self.note = self.planted(self.sessions, "aaaa1111.json", 31)
        self.claim = self.planted(self.state, STALE, 31)

    def test_a_failing_registry_sweep_does_not_stop_the_guard_sweep(self):
        for failure in (OSError(5, "Input/output error"), RuntimeError("bug")):
            with self.subTest(failure=type(failure).__name__), mock.patch("jam.registry.Registry.prune", side_effect=failure):
                self.claim.write_text("")
                os.utime(self.claim, (time.time() - 31 * DAY,) * 2)
                result = self.pruned()
                self.assertEqual(result.code, 0)
                self.assertFalse(self.claim.exists())
                self.assertTrue(self.note.exists())

    def test_a_failing_guard_sweep_does_not_stop_the_registry_sweep(self):
        for failure in (OSError(5, "Input/output error"), RuntimeError("bug")):
            with self.subTest(failure=type(failure).__name__), mock.patch("jam.sweep.swept", side_effect=failure):
                self.note.write_text("{}\n")
                os.utime(self.note, (time.time() - 31 * DAY,) * 2)
                result = self.pruned()
                self.assertEqual((result.code, result.out), (0, ""))
                self.assertFalse(self.note.exists())
                self.assertTrue(self.claim.exists())

    def test_an_unexpected_failure_is_still_reported_by_its_type_only(self):
        with mock.patch("jam.registry.Registry.prune", side_effect=RuntimeError("secret detail in /some/private/path")):
            self.assertEqual(self.pruned().err, "RuntimeError\n")
        with mock.patch("jam.sweep.swept", side_effect=RuntimeError("secret detail in /some/private/path")):
            self.assertEqual(self.pruned().err, "RuntimeError\n")


if __name__ == "__main__":
    unittest.main()
