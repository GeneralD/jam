"""Tests for the session registry when a link stands where its notes directory should be.

`sessions-v1` is the level the plugin creates. A link there would carry a write,
a removal or the age sweep to wherever it points, so none of them goes through
one: each raises the usual path-free `RegistryError`. A directory that is merely
absent is still "no note" and "nothing to prune". The data directory above it
belongs to the platform, may be reached through a link, and is not checked.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import support  # noqa: F401  (puts src/ on sys.path)
from jam.errors import RegistryError
from jam.registry import Record, Registry, spawned_marked

KEY = "aaaa1111"
NOTE = b'{"spawned":true}\n'
LONG_AGO = time.time() - 40 * 86400


class LinkTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"
        self.data.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()

    def stale_note(self, directory, key=KEY):
        path = directory / f"{key}.json"
        path.write_bytes(NOTE)
        os.utime(path, (LONG_AGO, LONG_AGO))
        return path

    def refused(self, call, action):
        """The message of the RegistryError `call` raises: path-free, and saying only that the place is not a directory."""
        with self.assertRaises(RegistryError) as caught:
            call()
        message = str(caught.exception)
        self.assertEqual(message, f"cannot {action} the session registry: not a directory")
        self.assertNotIn(self.root.name, message)
        return message


class LinkedNotesDirectoryTest(LinkTestCase):
    def setUp(self):
        super().setUp()
        (self.data / "sessions-v1").symlink_to(self.outside)
        self.registry = Registry(self.data)

    def test_update_writes_nothing_through_the_link_and_leaves_no_lock_behind(self):
        self.refused(lambda: self.registry.update(KEY, spawned_marked), "write")
        self.assertEqual(os.listdir(self.outside), [])
        self.assertEqual(os.listdir(self.data), ["sessions-v1"])

    def test_prune_scans_and_removes_nothing_through_the_link(self):
        note = self.stale_note(self.outside)
        self.refused(self.registry.prune, "scan")
        self.assertTrue(note.exists())

    def test_record_reads_nothing_through_the_link(self):
        self.stale_note(self.outside)
        self.refused(lambda: self.registry.record(KEY), "read")

    def test_remove_unlinks_nothing_through_the_link(self):
        note = self.stale_note(self.outside)
        self.refused(lambda: self.registry.remove(KEY), "remove from")
        self.assertTrue(note.exists())

    def test_a_key_that_is_not_an_id_is_still_none_for_record_whatever_stands_in_the_way(self):
        self.assertIsNone(self.registry.record("../x"))

    def test_the_same_note_in_a_real_directory_is_read_and_pruned(self):
        control = Registry(self.root / "control")
        real = self.root / "control" / "sessions-v1"
        real.mkdir(parents=True)
        note = self.stale_note(real)
        self.assertEqual(control.record(KEY), Record(spawned=True))
        self.assertEqual(control.prune(), 1)
        self.assertFalse(note.exists())

    def test_a_link_to_nothing_is_refused_like_any_link(self):
        link = self.data / "sessions-v1"
        link.unlink()
        link.symlink_to(self.root / "nowhere")
        self.refused(self.registry.prune, "scan")
        self.refused(lambda: self.registry.record(KEY), "read")
        with self.assertRaises(RegistryError):
            self.registry.update(KEY, spawned_marked)
        self.assertFalse((self.root / "nowhere").exists())


class AbsentNotesDirectoryTest(LinkTestCase):
    def test_a_directory_that_is_not_there_yet_is_no_note_nothing_to_prune_and_nothing_to_remove(self):
        registry = Registry(self.data)
        self.assertIsNone(registry.record(KEY))
        self.assertEqual(registry.prune(), 0)
        registry.remove(KEY)
        self.assertEqual(os.listdir(self.data), [])


class LinkedDataDirectoryTest(LinkTestCase):
    """The negative control: the platform's own directory may be a link, and the notes below it are still jam's."""

    def test_notes_are_written_read_and_pruned_below_a_data_directory_that_is_a_link(self):
        alias = self.root / "alias"
        alias.symlink_to(self.data)
        registry = Registry(alias)
        registry.update(KEY, spawned_marked)
        self.assertTrue((self.data / "sessions-v1" / f"{KEY}.json").is_file())
        self.assertEqual(registry.record(KEY), Record(spawned=True))
        os.utime(self.data / "sessions-v1" / f"{KEY}.json", (LONG_AGO, LONG_AGO))
        self.assertEqual(registry.prune(), 1)


if __name__ == "__main__":
    unittest.main()
