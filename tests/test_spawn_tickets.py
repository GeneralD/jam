"""Tests for the spawn ticket as the service writes it: before the harness runs, withdrawn when the harness raises, and never a reason to stop a spawn.

The harness is a fake that can look at the ticket directory from inside its spawn.
The ticket writer is the real one unless a test needs it to fail or to record.
"""

from __future__ import annotations

import os
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from jam.errors import HarnessError, RegistryError
from jam.registry import Registry
from jam.service import Jam
from test_operations import lazy
from test_service import SPAWNED, FakeHarness, ServiceTestCase, StubRegistry

operations = lazy("jam.operations")
tickets = lazy("jam.tickets")

PROMPT = "do it"


class FailingWriter:
    """A ticket writer whose issue always raises `error`; withdrawals are recorded."""

    def __init__(self, error):
        self.error = error
        self.withdrawn = []

    def issue(self, directory):
        raise self.error

    def withdraw(self, ticket):
        self.withdrawn.append(ticket)


class BrokenWithdrawal:
    """A ticket writer that issues a ticket and fails to withdraw it."""

    def issue(self, directory):
        return "/data/pending-v1/ticket"

    def withdraw(self, ticket):
        raise OSError(5, "Input/output error")


class RaisingWithdrawal:
    """A ticket writer that issues a ticket and fails to withdraw it with an error that is not an OSError."""

    def issue(self, directory):
        return "/data/pending-v1/ticket"

    def withdraw(self, ticket):
        raise RuntimeError("withdrawal failed")


class TicketOnSpawnTest(ServiceTestCase):
    def jam(self, harness, registry=None):
        return Jam(harness, Registry(self.data) if registry is None else registry, tickets.Tickets(str(self.data)))

    def test_the_ticket_exists_while_the_harness_runs_and_stays_after_a_successful_spawn(self):
        seen = []
        harness = FakeHarness(on_spawn=lambda: seen.append(sorted(os.listdir(self.data / "pending-v1"))))
        result = self.jam(harness).spawn("/work/x", PROMPT)
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(seen[0]), 1)
        self.assertEqual(sorted(os.listdir(self.data / "pending-v1")), seen[0])
        self.assertIsNone(result.problem)

    def test_the_ticket_is_named_for_the_directory_the_session_starts_in(self):
        app = self.root / "app"
        app.mkdir()
        self.jam(FakeHarness()).spawn(str(app), PROMPT)
        (name,) = os.listdir(self.data / "pending-v1")
        self.assertEqual(name.split(".")[0], tickets.dir_key(app))

    def test_a_raising_harness_withdraws_the_ticket_and_the_same_exception_propagates(self):
        error = HarnessError("boom")
        with self.assertRaises(HarnessError) as caught:
            self.jam(FakeHarness(spawn_error=error)).spawn("/work/x", PROMPT)
        self.assertIs(caught.exception, error)
        self.assertEqual(os.listdir(self.data / "pending-v1"), [])

    def test_an_interrupt_withdraws_the_ticket_and_still_propagates(self):
        with self.assertRaises(KeyboardInterrupt):
            self.jam(FakeHarness(spawn_error=KeyboardInterrupt())).spawn("/work/x", PROMPT)
        self.assertEqual(os.listdir(self.data / "pending-v1"), [])

    def test_a_failure_to_withdraw_is_swallowed_and_the_harness_error_is_the_one_raised(self):
        error = HarnessError("boom")
        with self.assertRaises(HarnessError) as caught:
            Jam(FakeHarness(spawn_error=error), StubRegistry(), BrokenWithdrawal()).spawn("/work/x", PROMPT)
        self.assertIs(caught.exception, error)

    def test_a_withdrawal_failing_with_a_non_os_error_is_swallowed_too(self):
        error = HarnessError("boom")
        with self.assertRaises(HarnessError) as caught:
            Jam(FakeHarness(spawn_error=error), StubRegistry(), RaisingWithdrawal()).spawn("/work/x", PROMPT)
        self.assertIs(caught.exception, error)

    def test_no_data_directory_writes_nothing_and_the_problem_is_the_registry_text_alone(self):
        registry = StubRegistry(update_error=RegistryError("no data directory: pass --data-dir before the command"))
        result = Jam(FakeHarness(), registry, tickets.Tickets(None)).spawn("/work/x", PROMPT)
        self.assertEqual(result.problem, "could not record cccc3333: no data directory: pass --data-dir before the command")
        self.assertEqual(result.spawned, SPAWNED)
        self.assertFalse(self.data.exists())

    def test_a_relative_data_directory_is_no_ticket_either(self):
        self.assertIsNone(Jam(FakeHarness(), StubRegistry(), tickets.Tickets("relative")).spawn("/work/x", PROMPT).problem)

    def test_two_argument_callers_still_spawn_and_write_no_ticket(self):
        result = Jam(FakeHarness(), StubRegistry()).spawn("/work/x", PROMPT)
        self.assertIsNone(result.problem)
        self.assertFalse(self.data.exists())


class TicketFailureTest(ServiceTestCase):
    def test_a_ticket_that_cannot_be_written_still_spawns_and_the_problem_is_path_free(self):
        harness = FakeHarness()
        writer = FailingWriter(RegistryError(tickets.NOT_WRITTEN))
        result = Jam(harness, Registry(self.data), writer).spawn("/work/x", PROMPT)
        self.assertEqual(len(harness.spawn_calls), 1)
        self.assertEqual(result.spawned, SPAWNED)
        self.assertEqual(result.problem, f"could not mark cccc3333 as started by jam: {tickets.NOT_WRITTEN}")

    def test_a_ticket_directory_that_is_a_link_gives_the_same_path_free_problem_and_writes_nothing(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.data.mkdir()
        (self.data / "pending-v1").symlink_to(outside)
        result = Jam(FakeHarness(), StubRegistry(), tickets.Tickets(str(self.data))).spawn("/work/x", PROMPT)
        self.assertEqual(result.problem, f"could not mark cccc3333 as started by jam: {tickets.NOT_WRITTEN}")
        self.assertEqual(os.listdir(outside), [])

    def test_an_unexpected_ticket_error_is_reported_by_its_type_name_only(self):
        result = Jam(FakeHarness(), StubRegistry(), FailingWriter(RuntimeError("/private/path"))).spawn("/work/x", PROMPT)
        self.assertEqual(result.problem, "could not mark cccc3333 as started by jam: RuntimeError")
        self.assertNotIn("/private/path", result.problem)

    def test_both_failures_are_joined_with_a_semicolon_and_the_ticket_comes_first(self):
        registry = StubRegistry(update_error=RegistryError("session registry is busy"))
        writer = FailingWriter(RegistryError(tickets.NOT_WRITTEN))
        result = Jam(FakeHarness(), registry, writer).spawn("/work/x", PROMPT)
        self.assertEqual(
            result.problem,
            f"could not mark cccc3333 as started by jam: {tickets.NOT_WRITTEN}; could not record cccc3333: session registry is busy",
        )

    def test_a_ticket_that_was_never_written_is_not_withdrawn(self):
        writer = FailingWriter(RegistryError("x"))
        with self.assertRaises(HarnessError):
            Jam(FakeHarness(spawn_error=HarnessError("boom")), StubRegistry(), writer).spawn("/work/x", PROMPT)
        self.assertEqual(writer.withdrawn, [])


class ToolDescriptionTest(unittest.TestCase):
    def test_the_spawn_description_calls_a_failed_ticket_jams_own_bookkeeping_not_a_note(self):
        description = operations.lookup("spawn").description
        self.assertIn("only jam's own bookkeeping failed", description)
        self.assertNotIn("only jam's own note failed", description)


if __name__ == "__main__":
    unittest.main()
