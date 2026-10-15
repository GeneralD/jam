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


if __name__ == "__main__":
    unittest.main()
