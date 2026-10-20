"""Tests for the guard's state when a link stands where its directory should be.

The state directory is the level the plugin creates, and the one place the guard
reads and writes. A link there would carry the claims, the marks and the sweep to
wherever it points, so none of them goes through one: every claim fails and every
reader answers "nothing", which the guard reads as "stay quiet". The data
directory above it belongs to the platform and may well be reached through a link
(a home directory behind an alias), so it is not held to the same rule.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy

claims = lazy("jam.claims")

SID = "aaaa1111-0000-4000-8000-000000000001"
REPO = "0123456789abcdef"
HOUR = 490000
START = "/work/app"


class LinkTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"
        self.data.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()

    def planted(self, directory):
        """Every file the readers know, in `directory`."""
        (directory / f"worker.{SID}").write_bytes(b"")
        (directory / f"start.{SID}").write_text(f"{START}\n", encoding="utf-8")
        (directory / f"denied.{SID}.{REPO}").write_bytes(b"")
        (directory / f"slot.{HOUR}.19").write_bytes(b"")

    def answers(self, book):
        return (book.worker_marked(SID), book.start_recorded(SID), book.pair_claimed(SID, REPO), book.throttled(HOUR))


class LinkedStateDirectoryTest(LinkTestCase):
    def setUp(self):
        super().setUp()
        self.state = self.data / "guard-v1"
        self.state.symlink_to(self.outside)
        self.book = claims.Claims(str(self.data))

    def test_no_claim_is_created_through_a_link_in_place_of_the_state_directory(self):
        self.assertIs(self.book.claim_pair(SID, REPO), False)
        self.assertIs(self.book.claim_slot(HOUR), False)
        self.assertEqual(os.listdir(self.outside), [])
        self.assertTrue(self.state.is_symlink())  # left as it was found

    def test_the_readers_answer_nothing_through_it_even_when_its_target_holds_the_files(self):
        self.planted(self.outside)
        self.assertEqual(self.answers(self.book), (False, None, False, False))

    def test_the_same_files_in_a_real_state_directory_are_seen(self):
        control = claims.Claims(str(self.root / "control"))
        (self.root / "control" / "guard-v1").mkdir(parents=True)
        self.planted(self.root / "control" / "guard-v1")
        self.assertEqual(self.answers(control), (True, START, True, True))

    def test_a_link_to_nothing_is_no_state_directory_either(self):
        self.state.unlink()
        self.state.symlink_to(self.root / "nowhere")
        self.assertIs(self.book.claim_pair(SID, REPO), False)
        self.assertIs(self.book.claim_slot(HOUR), False)
        self.assertFalse((self.root / "nowhere").exists())


class LinkedDataDirectoryTest(LinkTestCase):
    """The negative control: the platform's own directory may be a link, and the state below it is still the guard's."""

    def setUp(self):
        super().setUp()
        self.alias = self.root / "alias"
        self.alias.symlink_to(self.data)
        self.book = claims.Claims(str(self.alias))

    def test_claims_are_made_and_seen_below_a_data_directory_that_is_a_link(self):
        self.assertIs(self.book.claim_pair(SID, REPO), True)
        self.assertIs(self.book.claim_slot(HOUR), True)
        self.assertEqual(sorted(os.listdir(self.data / "guard-v1")), [f"denied.{SID}.{REPO}", f"slot.{HOUR}.0"])
        self.assertIs(self.book.pair_claimed(SID, REPO), True)

    def test_the_readers_see_the_marks_below_a_data_directory_that_is_a_link(self):
        (self.data / "guard-v1").mkdir()
        self.planted(self.data / "guard-v1")
        self.assertEqual(self.answers(self.book), (True, START, True, True))


if __name__ == "__main__":
    unittest.main()
