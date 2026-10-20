"""Tests for the bounded read of a small regular file."""

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


if __name__ == "__main__":
    unittest.main()
