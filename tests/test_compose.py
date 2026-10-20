"""Tests for the composition root that builds a Runtime from the environment."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts src/ on sys.path)
from jam.errors import InvalidRequest, RegistryError
from jam.registry import Record, Registry, spawned_marked

from test_claude_harness import LIVE, SPAWN_STDOUT, STOPPED, FakeRunner, agents, ok
from test_operations import lazy

compose = lazy("jam.compose")

ROOT = Path(__file__).resolve().parent.parent
DATA_VAR = "CLAUDE_PLUGIN_DATA"


class ComposeTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"
        self.work = self.root / "work"
        self.work.mkdir()


class DataDirectoryTest(ComposeTestCase):
    def test_a_spawn_records_the_note_and_creates_the_directory_on_that_first_update(self):
        runner = FakeRunner(ok(SPAWN_STDOUT))
        jam = compose.build_runtime(str(self.data), {}, runner=runner).jam()
        self.assertFalse(self.data.exists())
        result = jam.spawn(self.work, "do it", name="worker-c")
        self.assertEqual((result.spawned.id, result.problem), ("cccc3333", None))
        self.assertEqual(Registry(self.data).record("cccc3333"), Record(spawned=True))

    def test_the_environment_variable_is_used_without_a_flag(self):
        jam = compose.build_runtime(None, {DATA_VAR: str(self.data)}, runner=FakeRunner(ok(SPAWN_STDOUT))).jam()
        self.assertIsNone(jam.spawn(self.work, "do it").problem)
        self.assertEqual(Registry(self.data).record("cccc3333"), Record(spawned=True))

    def test_the_flag_beats_the_environment_variable(self):
        other = self.root / "other"
        jam = compose.build_runtime(str(self.data), {DATA_VAR: str(other)}, runner=FakeRunner(ok(SPAWN_STDOUT))).jam()
        jam.spawn(self.work, "do it")
        self.assertEqual(Registry(self.data).record("cccc3333"), Record(spawned=True))
        self.assertFalse(other.exists())

    def test_listing_reads_the_notes_in_the_chosen_directory(self):
        Registry(self.data).update("bbbb2222", spawned_marked)
        jam = compose.build_runtime(str(self.data), {}, runner=FakeRunner(agents(LIVE, STOPPED))).jam()
        self.assertEqual([row.record for row in jam.list().sessions], [None, Record(spawned=True)])


class UnusableDataDirectoryTest(ComposeTestCase):
    CASES = [
        ("none", None, {}, "--data-dir"),
        ("empty flag", "", {}, "--data-dir"),
        ("empty variable", None, {DATA_VAR: ""}, "--data-dir"),
        ("relative flag", "relative/data", {}, "absolute"),
        ("relative variable", None, {DATA_VAR: "relative/data"}, "absolute"),
    ]

    def test_spawn_still_returns_its_id_with_a_path_free_problem(self):
        for label, flag, env, fragment in self.CASES:
            with self.subTest(case=label):
                jam = compose.build_runtime(flag, env, runner=FakeRunner(ok(SPAWN_STDOUT))).jam()
                result = jam.spawn(self.work, "do it")
                self.assertEqual(result.spawned.id, "cccc3333")
                self.assertIn("cccc3333", result.problem)
                self.assertIn(fragment, result.problem)
                self.assertNotIn("relative/data", result.problem)

    def test_list_still_returns_the_harness_rows_with_a_problem(self):
        for label, flag, env, fragment in self.CASES:
            with self.subTest(case=label):
                jam = compose.build_runtime(flag, env, runner=FakeRunner(agents(LIVE, STOPPED))).jam()
                listing = jam.list()
                self.assertEqual([row.session.id for row in listing.sessions], ["aaaa1111", "bbbb2222"])
                self.assertEqual([row.record for row in listing.sessions], [None, None])
                self.assertIn(fragment, listing.problem)

    def test_the_unavailable_registry_raises_registry_error_with_its_reason(self):
        registry = compose.UnavailableRegistry("no data directory here")
        for call in (lambda: registry.record("aaaa1111"), lambda: registry.update("aaaa1111", spawned_marked)):
            with self.assertRaises(RegistryError) as caught:
                call()
            self.assertNotIsInstance(caught.exception, InvalidRequest)
            self.assertEqual(str(caught.exception), "no data directory here")


class NothingCreatedTest(ComposeTestCase):
    def test_building_and_constructing_do_no_io(self):
        runner = FakeRunner()
        runtime = compose.build_runtime(str(self.data), {}, runner=runner)
        runtime.jam()
        runtime.jam()
        self.assertEqual(runner.calls, [])
        self.assertFalse(self.data.exists())

    def test_listing_never_creates_the_directory(self):
        compose.build_runtime(str(self.data), {}, runner=FakeRunner(agents(LIVE))).jam().list()
        self.assertFalse(self.data.exists())


class PluginVersionTest(ComposeTestCase):
    def plugin_json(self, content):
        folder = self.root / "plugin" / ".claude-plugin"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plugin.json").write_text(content, encoding="utf-8")
        return self.root / "plugin"

    def test_it_equals_the_version_in_the_manifest(self):
        expected = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertEqual(compose.plugin_version(ROOT), expected)
        self.assertEqual(compose.plugin_version(self.plugin_json('{"version": "1.2.3"}')), "1.2.3")

    def test_anything_unusable_reads_as_unknown(self):
        cases = {
            "invalid json": "{not json",
            "empty": "",
            "not an object": '["1.2.3"]',
            "no version": "{}",
            "number": '{"version": 5}',
            "null": '{"version": null}',
            "oversized": '{"version": "1.2.3", "pad": "' + "x" * (2 * 1024 * 1024) + '"}',
        }
        for label, content in cases.items():
            with self.subTest(case=label):
                self.assertEqual(compose.plugin_version(self.plugin_json(content)), "unknown")

    def test_a_missing_file_and_an_unreadable_one_read_as_unknown(self):
        self.assertEqual(compose.plugin_version(self.root / "nowhere"), "unknown")
        unreadable = self.root / "dir" / ".claude-plugin" / "plugin.json"
        unreadable.mkdir(parents=True)
        self.assertEqual(compose.plugin_version(self.root / "dir"), "unknown")


if __name__ == "__main__":
    unittest.main()
