"""Tests for the `prune` sweep of the spawn tickets and of the start record and worker mark: thirty days, the same entry cap, one deadline, and independent sweeps.

Same harness as the other hook tests: everything in process, the environment
injected, no alarm armed, and a temp directory as the data directory.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

from test_claude_hooks import DATA_VAR, DAY, run
from test_operations import lazy

claims = lazy("jam.claims")
hooks = lazy("jam.harness.claude_hooks")
sweep = lazy("jam.sweep")
tickets = lazy("jam.tickets")

SID = "aaaa1111-0000-4000-8000-000000000001"
OTHER_SID = "bbbb2222-0000-4000-8000-000000000002"
KEY = "0123456789abcdef"
NONCE = "fedcba9876543210"


class MarksPruneCase(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.data, True)
        self.pending = self.data / "pending-v1"
        self.state = self.data / "guard-v1"
        self.sessions = self.data / "sessions-v1"

    def planted(self, directory, name, days):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(b"")
        moment = time.time() - days * DAY
        os.utime(path, (moment, moment))
        return path

    def pruned(self):
        return run("prune", env={DATA_VAR: str(self.data)})


class ThirtyDaysTest(MarksPruneCase):
    def test_tickets_start_records_and_marks_older_than_thirty_days_are_swept_and_nothing_is_printed(self):
        gone = [
            self.planted(self.pending, f"{KEY}.{NONCE}", 31),
            self.planted(self.state, f"start.{SID}", 31),
            self.planted(self.state, f"worker.{SID}", 31),
        ]
        result = self.pruned()
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertEqual([path.exists() for path in gone], [False, False, False])

    def test_fresh_ones_and_foreign_names_are_kept(self):
        kept = [
            self.planted(self.pending, f"{KEY}.{NONCE}", 1),
            self.planted(self.state, f"start.{SID}", 1),
            self.planted(self.state, f"worker.{OTHER_SID}", 1),
            self.planted(self.pending, "notes.txt", 90),
            self.planted(self.pending, f"{KEY}.{NONCE}.tmp", 90),
            self.planted(self.pending, f"{KEY}.{NONCE[:-1]}", 90),  # one hex digit short; upper case would be this same file on a case-insensitive volume
            self.planted(self.state, "worker.", 90),
            self.planted(self.state, "start.-x", 90),
        ]
        self.pruned()
        self.assertEqual([path.exists() for path in kept], [True] * len(kept))

    def test_a_ticket_directory_that_is_a_link_is_not_swept_through(self):
        outside = self.data / "outside"
        stale = self.planted(outside, f"{KEY}.{NONCE}", 90)
        self.data.mkdir(exist_ok=True)
        self.pending.symlink_to(outside)
        self.assertEqual(self.pruned().err, "")
        self.assertTrue(stale.exists())

    def test_the_age_limit_is_the_registrys_thirty_days_for_the_new_kinds_too(self):
        inside = self.planted(self.pending, f"{KEY}.{NONCE}", 29)
        outside = self.planted(self.state, f"start.{SID}", 31)
        self.pruned()
        self.assertEqual((inside.exists(), outside.exists()), (True, False))


class IndependenceTest(MarksPruneCase):
    """A failure in one sweep must not stop the others, and each failure is reported by its type only."""

    def failing_for(self, name):
        real = sweep.swept

        def swept(directory, *args, **kwargs):
            if str(directory).endswith(name):
                raise RuntimeError("bug in /some/private/path")
            return real(directory, *args, **kwargs)

        return swept

    def test_a_failing_ticket_sweep_stops_neither_the_guard_sweep_nor_the_registry_sweep(self):
        note = self.planted(self.sessions, f"{SID}.json", 31)
        mark = self.planted(self.state, f"worker.{SID}", 31)
        ticket = self.planted(self.pending, f"{KEY}.{NONCE}", 31)
        with mock.patch("jam.sweep.swept", new=self.failing_for("pending-v1")):
            result = self.pruned()
        self.assertEqual((result.code, result.out, result.err), (0, "", "RuntimeError\n"))
        self.assertEqual((note.exists(), mark.exists(), ticket.exists()), (False, False, True))

    def test_a_failing_guard_sweep_stops_neither_the_ticket_sweep_nor_the_registry_sweep(self):
        note = self.planted(self.sessions, f"{SID}.json", 31)
        mark = self.planted(self.state, f"worker.{SID}", 31)
        ticket = self.planted(self.pending, f"{KEY}.{NONCE}", 31)
        with mock.patch("jam.sweep.swept", new=self.failing_for("guard-v1")):
            result = self.pruned()
        self.assertEqual((result.code, result.out, result.err), (0, "", "RuntimeError\n"))
        self.assertEqual((note.exists(), mark.exists(), ticket.exists()), (False, True, False))

    def test_a_failing_registry_sweep_stops_neither_the_guard_nor_the_ticket_sweep(self):
        mark = self.planted(self.state, f"worker.{SID}", 31)
        ticket = self.planted(self.pending, f"{KEY}.{NONCE}", 31)
        with mock.patch("jam.registry.Registry.prune", side_effect=OSError(5, "Input/output error")):
            result = self.pruned()
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertEqual((mark.exists(), ticket.exists()), (False, False))


class WiringTest(MarksPruneCase):
    """The two directories are swept with the same entry cap, the same age, and one deadline shared between them."""

    def test_the_guard_and_the_ticket_sweeps_share_one_deadline_and_their_own_predicates(self):
        calls = []

        def recording(directory, accept, max_age, now, limit, deadline, clock=time.monotonic):
            calls.append((Path(directory).name, accept, max_age, limit, deadline))
            return 0

        before = time.monotonic()
        with mock.patch("jam.sweep.swept", side_effect=recording):
            self.pruned()
        after = time.monotonic()
        by_name = {name: (accept, max_age, limit, deadline) for name, accept, max_age, limit, deadline in calls}
        self.assertEqual(sorted(by_name), ["guard-v1", "pending-v1"])
        guard, pending = by_name["guard-v1"], by_name["pending-v1"]
        self.assertIs(guard[0], claims.is_state_name)
        self.assertIs(pending[0], tickets.is_ticket_name)
        self.assertEqual(guard[1:3], (30 * DAY, hooks.SWEEP_LIMIT))
        self.assertEqual(pending[1:3], (30 * DAY, hooks.SWEEP_LIMIT))
        self.assertEqual(guard[3], pending[3])
        self.assertTrue(before + hooks.PRUNE_BUDGET <= guard[3] <= after + hooks.PRUNE_BUDGET)

    def test_the_notes_guard_and_ticket_sweeps_run_in_the_documented_order(self):
        order = []
        notes = mock.patch("jam.registry.Registry.prune", side_effect=lambda *args, **kwargs: order.append("notes"))
        swept = mock.patch("jam.sweep.swept", side_effect=lambda directory, *args, **kwargs: order.append(Path(directory).name) or 0)
        with notes, swept:
            self.pruned()
        self.assertEqual(order, ["notes", "guard-v1", "pending-v1"])

    def test_the_budget_stays_below_the_alarm_of_prune(self):
        self.assertLess(hooks.PRUNE_BUDGET, hooks.HOOKS["prune"].alarm)


if __name__ == "__main__":
    unittest.main()
