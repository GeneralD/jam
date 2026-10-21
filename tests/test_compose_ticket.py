"""Tests for the spawn ticket that the composed runtime writes: the wiring of `compose.build_runtime`, which no service test reaches."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts src/ on sys.path)

from test_claude_harness import SPAWN_STDOUT, FakeRunner, ok
from test_operations import lazy

compose = lazy("jam.compose")
tickets = lazy("jam.tickets")

DATA_VAR = "CLAUDE_PLUGIN_DATA"


class ComposedTicketTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"
        self.work = self.root / "work"
        self.work.mkdir()

    def test_a_composed_spawn_writes_one_ticket_for_its_directory_in_the_data_directory(self):
        jam = compose.build_runtime(str(self.data), {}, runner=FakeRunner(ok(SPAWN_STDOUT))).jam()
        result = jam.spawn(self.work, "do it")
        self.assertEqual((result.spawned.id, result.problem), ("cccc3333", None))
        (name,) = os.listdir(self.data / "pending-v1")
        self.assertTrue(tickets.is_ticket_name(name))
        self.assertEqual(name.split(".")[0], tickets.dir_key(self.work))

    def test_the_environment_variable_names_the_ticket_directory_too(self):
        jam = compose.build_runtime(None, {DATA_VAR: str(self.data)}, runner=FakeRunner(ok(SPAWN_STDOUT))).jam()
        self.assertIsNone(jam.spawn(self.work, "do it").problem)
        self.assertEqual(len(os.listdir(self.data / "pending-v1")), 1)

    def test_without_a_data_directory_the_composed_spawn_writes_nothing(self):
        jam = compose.build_runtime(None, {}, runner=FakeRunner(ok(SPAWN_STDOUT))).jam()
        self.assertIn("--data-dir", jam.spawn(self.work, "do it").problem)
        self.assertFalse(self.data.exists())


if __name__ == "__main__":
    unittest.main()
