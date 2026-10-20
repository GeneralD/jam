"""Tests for the file checks: the bounded read of a small regular file, and whether a directory is a real one."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
