"""Tests for the two guard records that the session start writes: the start record and the worker mark, and the name test that sweeps them.

The readers are covered in test_claims.py. Real temporary directories throughout;
the length of a path that the platform would refuse is supplied by patching
`os.path.realpath`, which is the one call the writer makes on it.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

from test_claims import BAD_IDS
from test_operations import lazy

claims = lazy("jam.claims")

SID = "aaaa1111-0000-4000-8000-000000000001"
OTHER_SID = "bbbb2222-0000-4000-8000-000000000002"
MAX_RECORD = 4096  # the start record in all, its line feed included


class FullDisk:
    """A file handle whose every write fails with a full disk, as `os.fdopen` would return it; it closes the real descriptor."""

    def __init__(self, handle):
        self._handle = handle

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._handle.close()
        return False

    def fileno(self):
        return self._handle.fileno()

    def write(self, data):
        raise OSError(28, "no space left")


class StartCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"
        self.state = self.data / "guard-v1"
        self.app = self.root / "app"
        self.app.mkdir()
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)

    def book(self):
        return claims.Claims(str(self.data))

    def tree(self):
        return sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))


class RecordStartTest(StartCase):
    def test_the_record_is_the_real_path_and_a_line_feed_in_a_private_file_in_a_private_directory(self):
        self.assertTrue(self.book().record_start(SID, str(self.app)))
        path = self.state / f"start.{SID}"
        self.assertEqual(path.read_bytes(), os.fsencode(os.path.realpath(self.app)) + b"\n")
        self.assertEqual(stat.S_IMODE(os.lstat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(self.state).st_mode), 0o700)

    def test_the_record_reads_back_as_the_directory_it_was_given_through_a_symlink(self):
        link = self.root / "link"
        link.symlink_to(self.app)
        self.assertTrue(self.book().record_start(SID, str(link)))
        self.assertEqual(self.book().start_recorded(SID), os.path.realpath(self.app))

    def test_an_existing_record_is_kept_as_it_is(self):
        other = self.root / "other"
        other.mkdir()
        self.assertTrue(self.book().record_start(SID, str(self.app)))
        self.assertFalse(self.book().record_start(SID, str(other)))
        self.assertEqual(self.book().start_recorded(SID), os.path.realpath(self.app))

    def test_a_failed_write_leaves_no_record_so_the_next_start_writes_it(self):
        real_fdopen = os.fdopen
        with mock.patch("os.fdopen", side_effect=lambda fd, mode: FullDisk(real_fdopen(fd, mode))):
            self.assertFalse(self.book().record_start(SID, str(self.app)))
        self.assertIsNone(self.book().start_recorded(SID))
        self.assertTrue(self.book().record_start(SID, str(self.app)))
        self.assertEqual(self.book().start_recorded(SID), os.path.realpath(self.app))

    def test_the_limit_is_4096_bytes_in_all_with_the_line_feed_counted(self):
        fits = "/" + "a" * (MAX_RECORD - 2)
        with mock.patch("os.path.realpath", return_value=fits):
            self.assertTrue(self.book().record_start(SID, "/x"))
        self.assertEqual(len((self.state / f"start.{SID}").read_bytes()), MAX_RECORD)
        self.assertEqual(self.book().start_recorded(SID), fits)

    def test_one_byte_over_the_limit_writes_nothing_and_creates_nothing(self):
        too_long = "/" + "a" * (MAX_RECORD - 1)
        with mock.patch("os.path.realpath", return_value=too_long):
            self.assertFalse(self.book().record_start(OTHER_SID, "/x"))
        self.assertFalse(self.state.exists())

    def test_a_directory_that_is_not_an_absolute_path_or_holds_a_nul_writes_nothing(self):
        for bad in ("relative/app", "", "/a\0b", None, 5, b"/bytes"):
            with self.subTest(bad=repr(bad)):
                self.assertFalse(self.book().record_start(SID, bad))
        self.assertFalse(self.state.exists())

    def test_an_invalid_session_id_writes_nothing(self):
        for sid in BAD_IDS:
            with self.subTest(sid=repr(sid)):
                self.assertFalse(self.book().record_start(sid, str(self.app)))
        self.assertFalse(self.state.exists())

    def test_a_state_directory_that_is_a_link_is_never_written_through(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.data.mkdir()
        self.state.symlink_to(outside)
        self.assertFalse(self.book().record_start(SID, str(self.app)))
        self.assertEqual(os.listdir(outside), [])


class MarkWorkerTest(StartCase):
    def ticket(self, name="ticket"):
        pending = self.data / "pending-v1"
        pending.mkdir(parents=True, exist_ok=True)
        path = pending / name
        path.write_bytes(b"")
        return path

    def test_a_ticket_is_moved_to_the_worker_mark_and_the_ticket_is_gone(self):
        source = self.ticket()
        self.assertIs(self.book().mark_worker(SID, str(source)), True)
        mark = self.state / f"worker.{SID}"
        self.assertEqual((stat.S_ISREG(os.lstat(mark).st_mode), mark.read_bytes()), (True, b""))
        self.assertFalse(source.exists())
        self.assertIs(self.book().worker_marked(SID), True)

    def test_a_ticket_that_is_gone_answers_false_and_makes_no_mark(self):
        self.assertIs(self.book().mark_worker(SID, str(self.data / "pending-v1" / "gone")), False)
        self.assertIs(self.book().worker_marked(SID), False)

    def test_any_other_failure_answers_none(self):
        source = self.ticket()
        with mock.patch("os.link", side_effect=PermissionError(13, "denied")):
            self.assertIsNone(self.book().mark_worker(SID, str(source)))
        self.assertTrue(source.exists())

    def test_the_mark_keeps_the_file_time_of_the_ticket(self):
        source = self.ticket()
        os.utime(source, (1_000_000.0, 1_000_000.0))
        self.assertIs(self.book().mark_worker(SID, str(source)), True)
        self.assertEqual(os.lstat(self.state / f"worker.{SID}").st_mtime, 1_000_000.0)

    def test_a_mark_that_is_there_already_is_kept_and_the_second_ticket_stays(self):
        first, second = self.ticket("first"), self.ticket("second")
        self.assertIs(self.book().mark_worker(SID, str(first)), True)
        mark = self.state / f"worker.{SID}"
        kept = os.lstat(mark).st_ino
        self.assertIsNone(self.book().mark_worker(SID, str(second)))
        self.assertEqual(os.lstat(mark).st_ino, kept)
        self.assertTrue(second.exists())

    def test_a_session_that_linked_a_ticket_another_removed_first_takes_its_link_back(self):
        source = self.ticket()
        real_link = os.link

        def raced(src, dst, **kwargs):
            real_link(src, dst, **kwargs)
            os.unlink(src)  # another session linked the same ticket and removed it first

        with mock.patch("os.link", side_effect=raced):
            self.assertIs(self.book().mark_worker(SID, str(source)), False)
        self.assertFalse((self.state / f"worker.{SID}").exists())

    def test_a_ticket_that_cannot_be_removed_takes_the_link_back_and_stays(self):
        source = self.ticket()
        real_unlink = os.unlink

        def refused(path, *args, **kwargs):
            if os.fspath(path) == str(source):
                raise PermissionError(13, "denied")
            return real_unlink(path, *args, **kwargs)

        with mock.patch("os.unlink", side_effect=refused):
            self.assertIsNone(self.book().mark_worker(SID, str(source)))
        self.assertFalse((self.state / f"worker.{SID}").exists())
        self.assertTrue(source.exists())

    def test_only_a_regular_file_under_the_mark_name_is_a_mark(self):
        self.state.mkdir(parents=True)
        target = self.root / "target"
        target.write_bytes(b"")
        planted = {
            "a directory": lambda path: path.mkdir(),
            "a link to a file": lambda path: path.symlink_to(target),
            "a fifo": lambda path: os.mkfifo(path),
        }
        for number, (kind, plant) in enumerate(planted.items()):
            with self.subTest(kind=kind):
                sid = f"cccc3333-0000-4000-8000-00000000000{number}"
                plant(self.state / f"worker.{sid}")
                self.assertIs(self.book().worker_marked(sid), False)

    def test_an_invalid_session_id_or_source_answers_none(self):
        source = str(self.ticket())
        for sid in BAD_IDS:
            with self.subTest(sid=repr(sid)):
                self.assertIsNone(self.book().mark_worker(sid, source))
        for bad in (None, 5, "/a\0b"):
            with self.subTest(source=repr(bad)):
                self.assertIsNone(self.book().mark_worker(SID, bad))

    def test_the_mark_is_never_made_through_a_link_in_place_of_the_state_directory(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.data.mkdir()
        self.state.symlink_to(outside)
        source = self.ticket()
        self.assertIsNone(self.book().mark_worker(SID, str(source)))
        self.assertEqual(os.listdir(outside), [])
        self.assertTrue(source.exists())


class StateNameTest(unittest.TestCase):
    def test_the_start_record_and_the_worker_mark_are_state_names_for_any_valid_id(self):
        for name in (f"start.{OTHER_SID}", f"worker.{OTHER_SID}", "start.a.b", "worker.a-b_c.d"):
            with self.subTest(name=name):
                self.assertTrue(claims.is_state_name(name))

    def test_the_start_record_and_the_worker_mark_need_a_valid_id_after_their_prefix(self):
        for name in ("start.", "worker.", "start..x", "worker.-x", "start.a/b", "worker.x" * 12, "start.x\n", "worker", "start"):
            with self.subTest(name=name):
                self.assertFalse(claims.is_state_name(name))

    def test_the_older_kinds_keep_their_names(self):
        self.assertTrue(claims.is_state_name("denied.aaaa1111.0123456789abcdef"))
        self.assertTrue(claims.is_state_name("slot.490000.19"))
        self.assertFalse(claims.is_state_name(None))


if __name__ == "__main__":
    unittest.main()
