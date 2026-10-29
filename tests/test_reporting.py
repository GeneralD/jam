"""Tests for the pure renderers and the failure-to-message mapping shared by both transports."""

from __future__ import annotations

import json
import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from jam.errors import HarnessError, InvalidRequest, RegistryError, UnparseableOutput, WorkspaceNotTrusted
from jam.registry import Record
from jam.service import Listed, Listing, SpawnResult
from jam.session import Spawned

from test_operations import HINT, SESSION_ID, identity, lazy
from test_service import session

reporting = lazy("jam.reporting")

LIMIT = 2000


class Operation(str):
    """The operation as failure_text may receive it: its name, which is also its `.name`."""

    @property
    def name(self):
        return str(self)


def failure(operation, error):
    return reporting.failure_text(Operation(operation), error)


def has_control_characters(text):
    return any(ord(char) < 32 or 0x7F <= ord(char) <= 0x9F for char in text)


class RenderedTest(unittest.TestCase):
    def test_a_spawn_result_is_one_json_object_in_a_fixed_key_order(self):
        text = reporting.rendered(SpawnResult(Spawned("cccc3333", "worker-c"), None))
        self.assertEqual(text, json.dumps({"id": "cccc3333", "name": "worker-c", "problem": None}, ensure_ascii=False))
        self.assertEqual(list(json.loads(text)), ["id", "name", "problem"])

    def test_a_spawn_result_keeps_its_problem_and_a_missing_name(self):
        text = reporting.rendered(SpawnResult(Spawned("cccc3333", None), "could not record cccc3333: busy"))
        self.assertEqual(json.loads(text), {"id": "cccc3333", "name": None, "problem": "could not record cccc3333: busy"})

    def test_characters_are_not_escaped_and_the_text_stays_on_one_line(self):
        text = reporting.rendered(SpawnResult(Spawned("cccc3333", "ワーカー\nline two"), None))
        self.assertIn("ワーカー", text)
        self.assertNotIn("\n", text)
        self.assertEqual(json.loads(text)["name"], "ワーカー\nline two")

    def test_a_listing_renders_every_row_with_spawned_true_false_or_null(self):
        busy = session("aaaa1111", status="busy", pid=4242, started_at=1700000000000)
        listing = Listing((Listed(busy, None), Listed(session("bbbb2222"), Record(spawned=True)), Listed(session("cccc3333"), Record(spawned=False))), None)
        found = json.loads(reporting.rendered(listing))
        self.assertEqual(list(found), ["sessions", "problem"])
        self.assertIsNone(found["problem"])
        self.assertEqual([row["spawned"] for row in found["sessions"]], [None, True, False])
        self.assertEqual(list(found["sessions"][0]), ["id", "session_id", "name", "cwd", "kind", "state", "status", "spawned"])
        self.assertEqual([row["status"] for row in found["sessions"]], ["busy", None, None])

    def test_a_listing_carries_its_problem_and_may_be_empty(self):
        found = json.loads(reporting.rendered(Listing((), "cannot read the session registry")))
        self.assertEqual(found, {"sessions": [], "problem": "cannot read the session registry"})

    def test_an_identity_renders_both_ids_or_null(self):
        self.assertEqual(json.loads(reporting.rendered(identity())), {"session_id": SESSION_ID, "id": "aaaa1111"})
        self.assertEqual(list(json.loads(reporting.rendered(identity()))), ["session_id", "id"])
        self.assertIsNone(json.loads(reporting.rendered(identity(short=None)))["id"])


class FailureMappingTest(unittest.TestCase):
    def test_each_class_maps_to_its_message(self):
        cases = [
            (InvalidRequest("bad arguments"), ["bad arguments"]),
            (WorkspaceNotTrusted("/work/x"), [str(WorkspaceNotTrusted("/work/x")), "nothing was started", "do not retry"]),
            (UnparseableOutput("no id", "raw output"), ["no id", "raw output", HINT]),
            (HarnessError("boom"), ["boom"]),
            (RegistryError("session registry is busy"), ["session registry is busy"]),
            (RuntimeError("/private/path"), ["internal error: RuntimeError"]),
        ]
        for error, fragments in cases:
            with self.subTest(error=type(error).__name__):
                text = failure("spawn", error)
                for fragment in fragments:
                    self.assertIn(fragment, text)

    def test_invalid_request_is_not_reported_as_a_generic_harness_failure(self):
        self.assertEqual(failure("spawn", InvalidRequest("bad arguments")), "bad arguments")
        self.assertIn(HINT, failure("spawn", HarnessError("bad arguments")))

    def test_an_untrusted_workspace_says_nothing_started(self):
        text = failure("spawn", WorkspaceNotTrusted("/work/x"))
        self.assertNotIn(HINT, text)
        self.assertIn("/work/x", text)

    def test_unparseable_output_carries_its_raw_text_clipped_to_200_characters(self):
        text = failure("spawn", UnparseableOutput("no id", "R" * 500))
        self.assertIn("R" * 200, text)
        self.assertNotIn("R" * 201, text)
        self.assertEqual(text.count(HINT), 1)

    def test_an_internal_error_names_only_the_type(self):
        self.assertEqual(failure("list", RuntimeError("/private/path/secret")), "internal error: RuntimeError")
        self.assertEqual(failure("whoami", KeyError("/private/path/secret")), "internal error: KeyError")
        text = failure("spawn", RuntimeError("/private/path/secret"))
        self.assertNotIn("/private", text)
        self.assertIn("internal error: RuntimeError", text)
        self.assertIn(HINT, text)

    def test_the_run_list_hint_is_for_spawn_failures_other_than_the_pre_start_ones(self):
        for error in (HarnessError("'claude' timed out after 60s"), UnparseableOutput("no id", "raw"), RuntimeError("x")):
            with self.subTest(error=type(error).__name__):
                self.assertIn(HINT, failure("spawn", error))
        for error in (InvalidRequest("bad"), WorkspaceNotTrusted("/work/x")):
            with self.subTest(error=type(error).__name__):
                self.assertNotIn(HINT, failure("spawn", error))

    def test_the_hint_never_appears_for_list_stop_close_or_whoami(self):
        for operation in ("list", "stop", "close", "whoami"):
            for error in (HarnessError("boom"), RegistryError("busy"), RuntimeError("x"), InvalidRequest("bad")):
                with self.subTest(operation=operation, error=type(error).__name__):
                    self.assertNotIn(HINT, failure(operation, error))
        self.assertEqual(failure("list", HarnessError("boom")), "boom")


class SanitisingTest(unittest.TestCase):
    MESSY = "first line\n\x1b[31mred\x1b[0m\r\n\tsecond\x07 line\x00 third\x9b end"

    def errors(self):
        return [
            InvalidRequest(self.MESSY),
            WorkspaceNotTrusted(self.MESSY),
            UnparseableOutput(self.MESSY, self.MESSY * 5),
            HarnessError(self.MESSY),
            RegistryError(self.MESSY),
            RuntimeError(self.MESSY),
        ]

    def test_every_branch_comes_out_as_one_clean_line(self):
        for operation in ("spawn", "list"):
            for error in self.errors():
                with self.subTest(operation=operation, error=type(error).__name__):
                    text = failure(operation, error)
                    self.assertFalse(has_control_characters(text), repr(text))
                    self.assertNotIn("[31m", text)
                    self.assertNotIn("  ", text)
                    self.assertLessEqual(len(text), LIMIT)

    def test_whitespace_runs_collapse_and_ansi_escapes_vanish(self):
        self.assertEqual(failure("list", HarnessError("a\n\n  b\t\x1b[1mc\x1b[0m\r\nd")), "a b c d")
        self.assertEqual(failure("list", HarnessError("失敗 しました")), "失敗 しました")

    def test_a_long_message_is_capped_with_an_ellipsis(self):
        text = failure("list", HarnessError("x" * 5000))
        self.assertLessEqual(len(text), LIMIT)
        self.assertTrue(text.startswith("x" * 100))
        self.assertTrue(text.endswith("..."))

    def test_the_nothing_started_note_survives_a_huge_path(self):
        for error in (WorkspaceNotTrusted("/x" * 3000), WorkspaceNotTrusted("x" * 1900)):
            with self.subTest(length=len(str(error))):
                text = failure("spawn", error)
                self.assertLessEqual(len(text), LIMIT)
                self.assertIn("nothing was started", text)
                self.assertIn("do not retry", text)
                self.assertNotIn(HINT, text)

    def test_the_hint_survives_a_huge_message(self):
        for error in (HarnessError("x" * 5000), UnparseableOutput("no id", "y" * 5000), RuntimeError("z" * 5000)):
            with self.subTest(error=type(error).__name__):
                text = failure("spawn", error)
                self.assertLessEqual(len(text), LIMIT)
                self.assertIn(HINT, text)


if __name__ == "__main__":
    unittest.main()
