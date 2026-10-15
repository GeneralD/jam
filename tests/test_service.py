"""Tests for the service that composes a harness with the registry."""

import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts src/ on sys.path)
from jam.errors import HarnessError, InvalidRequest, RegistryError, UnparseableOutput, WorkspaceNotTrusted
from jam.harness.claude import ClaudeHarness
from jam.registry import Record, Registry, spawned_marked
from jam.service import Jam, Listed, Listing, SpawnResult, failure_reason, joined
from jam.session import Session, Spawned

from test_claude_harness import LIVE, FakeRunner, agents

SPAWNED = Spawned(id="cccc3333", name="worker-c")


def session(session_id, **fields):
    return Session(id=session_id, session_id=session_id + "-full", name="n", cwd="/work/x", kind="background", state="done", **fields)


class FakeHarness:
    def __init__(self, sessions=(), spawn_error=None, list_error=None, on_spawn=None):
        self.sessions = list(sessions)
        self.spawn_error, self.list_error, self.on_spawn = spawn_error, list_error, on_spawn
        self.spawn_calls, self.list_calls, self.stop_calls = [], [], []

    def spawn(self, cwd, prompt, name=None, permission_mode=None):
        self.spawn_calls.append((cwd, prompt, name, permission_mode))
        if self.on_spawn:
            self.on_spawn()
        if self.spawn_error:
            raise self.spawn_error
        return SPAWNED

    def list(self, include_exited=False, cwd=None):
        self.list_calls.append((include_exited, cwd))
        if self.list_error:
            raise self.list_error
        return list(self.sessions)

    def stop(self, session_id):
        self.stop_calls.append(session_id)
        return session(session_id)


class StubRegistry:
    """Counts calls and optionally raises, standing in for Registry."""

    def __init__(self, update_error=None, record_error=None):
        self.update_error, self.record_error = update_error, record_error
        self.updates, self.records, self.removes = [], [], []

    def update(self, key, change):
        self.updates.append(key)
        if self.update_error:
            raise self.update_error

    def record(self, key):
        self.records.append(key)
        if self.record_error:
            raise self.record_error
        return None

    def remove(self, key):
        self.removes.append(key)


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"


class SpawnTest(ServiceTestCase):
    def test_spawn_records_spawned_and_passes_arguments_through(self):
        harness, registry = FakeHarness(), Registry(self.data)
        result = Jam(harness, registry).spawn("/work/x", "do it", name="worker-c", permission_mode="default")
        self.assertEqual(result, SpawnResult(SPAWNED, None))
        self.assertEqual(harness.spawn_calls, [("/work/x", "do it", "worker-c", "default")])
        self.assertEqual(registry.record("cccc3333"), Record(spawned=True))

    def test_the_id_survives_a_registry_error(self):
        harness, registry = FakeHarness(), StubRegistry(update_error=RegistryError("session registry is busy"))
        result = Jam(harness, registry).spawn("/work/x", "do it")
        self.assertEqual(result.spawned.id, "cccc3333")
        self.assertIn("cccc3333", result.problem)
        self.assertIn("busy", result.problem)
        self.assertEqual(len(harness.spawn_calls), 1)

    def test_the_id_survives_a_bug_without_leaking_its_message(self):
        registry = StubRegistry(update_error=RuntimeError("/private/path"))
        result = Jam(FakeHarness(), registry).spawn("/work/x", "do it")
        self.assertEqual(result.spawned.id, "cccc3333")
        self.assertIn("RuntimeError", result.problem)
        self.assertNotIn("/private/path", result.problem)

    def test_keyboard_interrupt_is_not_swallowed(self):
        registry = StubRegistry(update_error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            Jam(FakeHarness(), registry).spawn("/work/x", "do it")

    def test_a_failed_spawn_propagates_and_leaves_the_registry_untouched(self):
        errors = [
            WorkspaceNotTrusted("/work/x"),
            UnparseableOutput("no id", "raw output"),
            HarnessError("boom"),
            InvalidRequest("bad"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                stub = StubRegistry()
                with self.assertRaises(type(error)) as caught:
                    Jam(FakeHarness(spawn_error=error), stub).spawn("/work/x", "do it")
                if isinstance(error, UnparseableOutput):
                    self.assertEqual(caught.exception.raw, "raw output")
                self.assertEqual(stub.updates, [])
                self.assertFalse(self.data.exists())

    def test_the_registry_is_usable_while_the_harness_spawns(self):
        outcome = []

        def other_writer():
            Registry(self.data, lock_timeout=0.1).update("zzzz9999", spawned_marked)
            outcome.append("ok")

        Jam(FakeHarness(on_spawn=other_writer), Registry(self.data)).spawn("/work/x", "do it")
        self.assertEqual(outcome, ["ok"])


class ListTest(ServiceTestCase):
    def test_list_joins_registry_notes_onto_harness_rows_in_harness_order(self):
        registry = Registry(self.data)
        registry.update("bbbb2222", spawned_marked)
        registry.update("orphan99", spawned_marked)
        harness = FakeHarness([session("aaaa1111"), session("bbbb2222")])
        listing = Jam(harness, registry).list(include_exited=True, cwd="/work/x")
        self.assertEqual([row.session.id for row in listing.sessions], ["aaaa1111", "bbbb2222"])
        self.assertEqual([row.record for row in listing.sessions], [None, Record(spawned=True)])
        self.assertIsNone(listing.problem)
        self.assertEqual(harness.list_calls, [(True, "/work/x")])

    def test_list_degrades_visibly_when_the_registry_fails(self):
        stub = StubRegistry(record_error=RegistryError("cannot read the session registry: Input/output error"))
        listing = Jam(FakeHarness([session("aaaa1111")]), stub).list()
        self.assertEqual([row.record for row in listing.sessions], [None])
        self.assertIn("cannot read", listing.problem)

    def test_list_lets_a_registry_bug_through_instead_of_degrading_on_it(self):
        # Only RegistryError is an expected, message-safe failure; anything else is a bug to surface.
        stub = StubRegistry(record_error=RuntimeError("/private/path"))
        with self.assertRaises(RuntimeError):
            Jam(FakeHarness([session("aaaa1111")]), stub).list()

    def test_list_survives_an_odd_harness_id(self):
        listing = Jam(FakeHarness([session("../x")]), Registry(self.data)).list()
        self.assertEqual(listing.sessions[0].record, None)
        self.assertIsNone(listing.problem)

    def test_a_harness_failure_propagates_and_the_registry_is_not_consulted(self):
        stub = StubRegistry()
        with self.assertRaises(HarnessError):
            Jam(FakeHarness(list_error=HarnessError("down")), stub).list()
        self.assertEqual(stub.records, [])

    def test_joined_is_a_pure_left_join(self):
        rows = [session("aaaa1111"), session("bbbb2222")]
        self.assertEqual(
            joined(rows, {"bbbb2222": Record(spawned=True), "orphan99": Record(spawned=True)}),
            (Listed(rows[0], None), Listed(rows[1], Record(spawned=True))),
        )

    def test_spawn_then_list_with_a_real_registry(self):
        registry = Registry(self.data)
        harness = FakeHarness([session("cccc3333")])
        jam = Jam(harness, registry)
        jam.spawn("/work/x", "do it")
        (row,) = jam.list().sessions
        self.assertTrue(row.record.spawned)

    def test_list_works_with_the_real_claude_harness(self):
        harness = ClaudeHarness(claude_bin="claude", runner=FakeRunner(agents(LIVE)))
        listing = Jam(harness, Registry(self.data)).list()
        self.assertEqual([row.session.id for row in listing.sessions], ["aaaa1111"])
        self.assertIsInstance(listing, Listing)


class StopTest(ServiceTestCase):
    def test_stop_delegates_and_never_touches_the_registry(self):
        harness, stub = FakeHarness(), StubRegistry()
        stopped = Jam(harness, stub).stop("aaaa1111")
        self.assertEqual(stopped.id, "aaaa1111")
        self.assertEqual(harness.stop_calls, ["aaaa1111"])
        self.assertEqual((stub.updates, stub.records, stub.removes), ([], [], []))


class FailureReasonTest(unittest.TestCase):
    def test_only_registry_errors_may_carry_their_message(self):
        self.assertEqual(failure_reason(RegistryError("busy")), "busy")
        self.assertEqual(failure_reason(RuntimeError("/private/path")), "RuntimeError")


class NothingCreatedTest(ServiceTestCase):
    def test_listing_never_creates_the_data_dir(self):
        Jam(FakeHarness([session("aaaa1111")]), Registry(self.data)).list()
        self.assertFalse(self.data.exists())


if __name__ == "__main__":
    unittest.main()
