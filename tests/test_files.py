"""Tests for the file checks: the bounded read of a small regular file, and whether a directory is a real one."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy

files = lazy("jam.files")


class ReadSmallTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)

    def planted(self, data, name="f"):
        path = self.root / name
        path.write_bytes(data)
        return str(path)

    def test_a_file_up_to_the_limit_is_returned_whole(self):
        for data in (b"", b"x", b"x" * 16):
            with self.subTest(size=len(data)):
                self.assertEqual(files.read_small(self.planted(data), 16), data)

    def test_a_file_one_byte_over_the_limit_is_none_and_is_never_read_beyond_it(self):
        self.assertIsNone(files.read_small(self.planted(b"x" * 17), 16))
        self.assertIsNone(files.read_small(self.planted(b"x" * 100000), 16))

    def test_a_missing_file_and_an_unreadable_one_raise_instead_of_reading_as_none(self):
        with self.assertRaises(FileNotFoundError):
            files.read_small(str(self.root / "absent"), 16)
        with self.assertRaises(NotADirectoryError):
            files.read_small(self.planted(b"x") + "/below", 16)

    def test_a_symbolic_link_is_refused_and_not_followed(self):
        target = self.planted(b"x")
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            files.read_small(str(link), 16)

    def test_a_directory_is_none(self):
        self.assertIsNone(files.read_small(str(self.root), 16))

    def test_a_named_pipe_is_none_and_does_not_hold_the_reader(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        outcome = []
        reader = threading.Thread(target=lambda: outcome.append(files.read_small(str(fifo), 16)), daemon=True)  # a daemon, so a lost bound fails the test instead of hanging the suite
        reader.start()
        reader.join(timeout=5)
        self.assertFalse(reader.is_alive(), "read_small blocked on a pipe")
        self.assertEqual(outcome, [None])


class RealDirectoryTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_directory_is_real_and_a_path_object_will_do(self):
        (self.root / "dir").mkdir()
        self.assertIs(files.real_directory(str(self.root / "dir")), True)
        self.assertIs(files.real_directory(self.root / "dir"), True)

    def test_a_link_is_not_even_when_it_leads_to_a_directory(self):
        (self.root / "dir").mkdir()
        (self.root / "link").symlink_to(self.root / "dir")
        self.assertIs(files.real_directory(str(self.root / "link")), False)

    def test_a_link_in_an_ancestor_is_followed_because_only_the_last_level_is_in_question(self):
        (self.root / "dir" / "inner").mkdir(parents=True)
        (self.root / "alias").symlink_to(self.root / "dir")
        self.assertIs(files.real_directory(str(self.root / "alias" / "inner")), True)

    def test_what_is_not_a_directory_is_not_real_and_nothing_raises(self):
        (self.root / "file").write_bytes(b"x")
        (self.root / "dangling").symlink_to(self.root / "nowhere")
        os.mkfifo(self.root / "pipe")
        for path in (self.root / "file", self.root / "dangling", self.root / "pipe", self.root / "absent", self.root / "file" / "below"):
            with self.subTest(path=path.name):
                self.assertIs(files.real_directory(str(path)), False)

    def test_a_path_with_nul_is_not_a_directory_and_does_not_raise(self):
        self.assertIs(files.real_directory(str(self.root) + "\0"), False)


class EnsuredTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)

    def test_a_missing_directory_is_made_private_whatever_the_umask(self):
        target = self.root / "data" / "pending-v1"
        self.assertEqual(files.ensured(str(target)), str(target))
        self.assertEqual(stat.S_IMODE(os.lstat(target).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.lstat(target.parent).st_mode), 0o700)

    def test_a_missing_directory_is_made_private_under_every_umask(self):
        for umask in (0o000, 0o077, 0o177, 0o277, 0o377):
            with self.subTest(umask=oct(umask)):
                base = self.root / f"base-{umask:o}"
                os.umask(0)  # the ancestor is made under no umask, so that it is usable whatever the loop's previous umask was
                os.makedirs(base, mode=0o755)
                os.umask(umask)
                target = base / "data" / "pending-v1"
                self.assertEqual(files.ensured(str(target)), str(target))
                self.assertEqual(stat.S_IMODE(os.lstat(target).st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(os.lstat(target.parent).st_mode), 0o700)

    def test_an_existing_directory_is_returned_as_it_is(self):
        self.assertEqual(files.ensured(str(self.root)), str(self.root))

    def test_a_link_or_a_file_in_its_place_is_refused(self):
        real = self.root / "real"
        real.mkdir()
        (self.root / "link").symlink_to(real)
        (self.root / "file").write_text("x", encoding="utf-8")
        self.assertIsNone(files.ensured(str(self.root / "link")))
        self.assertIsNone(files.ensured(str(self.root / "file")))

    def test_a_directory_that_cannot_be_made_is_none_and_no_error(self):
        (self.root / "file").write_text("x", encoding="utf-8")
        self.assertIsNone(files.ensured(str(self.root / "file" / "below")))


class CreatedTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)

    def test_a_new_file_is_private_and_holds_the_data_and_nothing_is_written_over_it(self):
        path = str(self.root / "f")
        self.assertIs(files.created(path, b"abc\n"), True)
        self.assertEqual(stat.S_IMODE(os.lstat(path).st_mode), 0o600)
        self.assertIs(files.created(path, b"other"), False)
        self.assertEqual(Path(path).read_bytes(), b"abc\n")

    def test_an_empty_file_is_the_default(self):
        self.assertIs(files.created(str(self.root / "e")), True)
        self.assertEqual((self.root / "e").stat().st_size, 0)

    def test_a_file_that_cannot_be_made_is_none(self):
        self.assertIsNone(files.created(str(self.root / "missing" / "f")))

    def test_a_link_in_the_place_of_the_file_is_never_followed(self):
        target = self.root / "target"
        (self.root / "f").symlink_to(target)
        self.assertIs(files.created(str(self.root / "f")), False)
        self.assertFalse(target.exists())

    def test_a_new_file_is_private_under_every_umask(self):
        for umask in (0o000, 0o077, 0o177, 0o277, 0o377):
            with self.subTest(umask=oct(umask)):
                os.umask(umask)
                path = str(self.root / f"f{umask:o}")
                self.assertIs(files.created(path, b"x"), True)
                self.assertEqual(stat.S_IMODE(os.lstat(path).st_mode), 0o600)

    def test_a_failed_write_is_none_and_leaves_no_file_behind_so_the_next_attempt_starts_again(self):
        path = str(self.root / "f")
        real_fdopen = os.fdopen

        class FailingWrite:
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

        with mock.patch("os.fdopen", side_effect=lambda fd, mode: FailingWrite(real_fdopen(fd, mode))):
            self.assertIsNone(files.created(path, b"abc\n"))
        self.assertFalse(os.path.lexists(path))
        self.assertIs(files.created(path, b"abc\n"), True)
        self.assertEqual(Path(path).read_bytes(), b"abc\n")


class AbsolutePathTest(unittest.TestCase):
    def test_an_absolute_string_or_path_object_is_returned_as_a_string(self):
        self.assertEqual(files.absolute_path("/x/y"), "/x/y")
        self.assertEqual(files.absolute_path(Path("/x/y")), "/x/y")

    def test_anything_that_is_not_an_absolute_path_is_none(self):
        for value in (None, 1, b"/x", "x/y", "", "/x/\0y"):
            with self.subTest(value=repr(value)):
                self.assertIsNone(files.absolute_path(value))

    def test_a_lone_surrogate_has_no_file_name_form_but_an_escaped_byte_does(self):
        self.assertEqual(files.absolute_path("/x/\udc80"), "/x/\udc80")
        self.assertIsNone(files.absolute_path("/x/\ud800"))

    def test_a_name_below_an_absolute_directory_and_none_for_anything_else(self):
        self.assertEqual(files.subdirectory("/data", "guard-v1"), os.path.join("/data", "guard-v1"))
        for data in (None, "relative", "/x/\0y", "/x/\ud800"):
            with self.subTest(data=repr(data)):
                self.assertIsNone(files.subdirectory(data, "guard-v1"))


if __name__ == "__main__":
    unittest.main()
