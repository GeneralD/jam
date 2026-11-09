"""Tests for the harness-neutral session helpers."""

import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from jam import session
from jam.session import Session, Spawned, is_id


class IsIdTest(unittest.TestCase):
    def test_accepts_ids_names_use_as_file_names_and_argv_entries(self):
        for value in ("aaaa1111", "a.b_c-d", "A", "x" * 64):
            with self.subTest(value=value):
                self.assertTrue(is_id(value))

    def test_rejects_anything_that_could_escape_a_path_or_read_as_a_flag(self):
        bad = ["", "../x", "a/b", "-x", ".hidden", "x" * 65, "a\x00b", "a\n", "a b", None, 5, True, b"abc"]
        for value in bad:
            with self.subTest(value=value):
                self.assertFalse(is_id(value))


class SpawnedMovedTest(unittest.TestCase):
    def test_spawned_lives_in_the_core_and_the_adapter_reuses_it(self):
        from jam.harness import claude

        self.assertIs(claude.Spawned, session.Spawned)
        self.assertEqual(Spawned(id="aaaa1111", name=None), Spawned("aaaa1111", None))

    def test_session_still_builds_from_a_row(self):
        self.assertEqual(Session.from_agent({"id": "aaaa1111"}).id, "aaaa1111")


class ForegroundRowTest(unittest.TestCase):
    """A foreground session is a row without `id` and `state` (#47): listed read-only, as reported."""

    def test_a_row_without_an_id_but_with_a_session_id_is_a_session_with_null_id_and_state(self):
        from test_claude_harness import INTERACTIVE

        found = Session.from_agent(INTERACTIVE)
        self.assertEqual((found.id, found.state), (None, None))
        self.assertEqual((found.session_id, found.name, found.kind, found.status), (INTERACTIVE["sessionId"], "owner-terminal", "interactive", "idle"))
        self.assertEqual((found.pid, found.started_at), (5151, 1700000002000))

    def test_an_empty_or_non_string_id_counts_as_none(self):
        for bad_id in ("", 7, None, True):
            with self.subTest(id=repr(bad_id)):
                self.assertIsNone(Session.from_agent({"id": bad_id, "sessionId": "ffff0000-0000-4000-8000-00000000000f"}).id)

    def test_a_row_with_neither_id_nor_session_id_names_no_session(self):
        for row in ({}, {"no": "id"}, {"id": "", "sessionId": ""}, {"id": 7, "sessionId": 8}, {"sessionId": None, "name": "x"}):
            with self.subTest(row=row):
                self.assertIsNone(Session.from_agent(row))

    def test_a_background_row_keeps_its_state_and_a_non_string_state_is_none(self):
        self.assertEqual(Session.from_agent({"id": "aaaa1111", "state": "working"}).state, "working")
        self.assertIsNone(Session.from_agent({"id": "aaaa1111", "state": 3}).state)


if __name__ == "__main__":
    unittest.main()
