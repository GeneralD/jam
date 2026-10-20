"""Tests for the age sweep: remove old regular files whose names a predicate accepts, within an entry cap and a deadline."""

from __future__ import annotations

import contextlib
import errno
import itertools
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy

sweep = lazy("jam.sweep")

DAY = 24 * 3600.0
NOW = 2_000_000_000.0
FOREVER = float("inf")


def accept_old_style(name):
    return name.startswith("old-")


def ticking(step=1.0):
    """A clock that reads 0, step, 2*step, ... one reading per call."""
    counter = itertools.count()
    return lambda: next(counter) * step


class SweepTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)

    def file(self, name, age_days, data=b"x"):
        path = self.root / name
        path.write_bytes(data)
        moment = NOW - age_days * DAY
        os.utime(path, (moment, moment))
        return path

    def swept(self, **options):
        arguments = {"accept": accept_old_style, "max_age": 30 * DAY, "now": NOW, "limit": 1000, "deadline": FOREVER}
        return sweep.swept(str(self.root), **{**arguments, **options})

    def names(self):
        return sorted(path.name for path in self.root.iterdir())


class SelectionTest(SweepTestCase):
    def test_only_accepted_names_older_than_the_limit_go_and_the_count_is_returned(self):
        self.file("old-stale", 31)
        self.file("old-fresh", 29)
        self.file("other-stale", 90)
        self.assertEqual(self.swept(), 1)
        self.assertEqual(self.names(), ["old-fresh", "other-stale"])

    def test_the_age_limit_is_strictly_greater_than_and_a_future_time_never_expires(self):
        self.file("old-exactly", 30)
        self.file("old-future", -5)
        self.assertEqual(self.swept(), 0)
        self.assertEqual(self.names(), ["old-exactly", "old-future"])

    def test_the_clock_is_the_one_given(self):
        self.file("old-a", 10)
        self.assertEqual(self.swept(now=NOW + 15 * DAY, max_age=30 * DAY), 0)
        self.assertEqual(self.swept(now=NOW + 21 * DAY, max_age=30 * DAY), 1)

    def test_the_predicate_sees_the_bare_name_and_not_a_path(self):
        self.file("old-a", 90)
        seen = []
        self.swept(accept=lambda name: seen.append(name) or True)
        self.assertEqual(seen, ["old-a"])

    def test_symbolic_links_and_directories_are_left_alone_even_when_old_and_accepted(self):
        target = self.file("kept-target", 90)
        link = self.root / "old-link"
        link.symlink_to(target)
        directory = self.root / "old-dir"
        directory.mkdir()
        os.utime(directory, (NOW - 90 * DAY, NOW - 90 * DAY))
        os.utime(link, (NOW - 90 * DAY, NOW - 90 * DAY), follow_symlinks=False)
        self.assertEqual(self.swept(), 0)
        self.assertEqual(self.names(), ["kept-target", "old-dir", "old-link"])
        self.assertTrue(target.exists())

    def test_a_dangling_link_is_left_alone_too(self):
        (self.root / "old-dangling").symlink_to(self.root / "nowhere")
        self.assertEqual(self.swept(), 0)
        self.assertEqual(self.names(), ["old-dangling"])

    def test_a_pipe_is_left_alone(self):
        os.mkfifo(self.root / "old-pipe")
        os.utime(self.root / "old-pipe", (NOW - 90 * DAY, NOW - 90 * DAY))
        self.assertEqual(self.swept(), 0)

    def test_a_missing_directory_is_nothing_to_sweep_and_creates_nothing(self):
        self.assertEqual(sweep.swept(str(self.root / "absent"), accept_old_style, 30 * DAY, NOW, 10, FOREVER), 0)
        self.assertEqual(self.names(), [])

    def test_a_path_that_is_a_file_is_nothing_to_sweep(self):
        path = self.file("old-file", 90)
        self.assertEqual(sweep.swept(str(path), accept_old_style, 30 * DAY, NOW, 10, FOREVER), 0)
        self.assertTrue(path.exists())


class BoundTest(SweepTestCase):
    def test_the_entry_cap_limits_how_many_entries_are_looked_at(self):
        for number in range(10):
            self.file(f"old-{number}", 90)
        self.assertEqual(self.swept(limit=4), 4)
        self.assertEqual(len(self.names()), 6)
        self.assertEqual(self.swept(limit=0), 0)

    def test_a_cap_that_covers_the_directory_removes_everything_stale(self):
        for number in range(10):
            self.file(f"old-{number}", 90)
        self.assertEqual(self.swept(limit=10), 10)
        self.assertEqual(self.names(), [])

    def test_the_deadline_stops_the_sweep_between_two_entries(self):
        for number in range(8):
            self.file(f"old-{number}", 90)
        # The clock reads 0, 1, 2, ... once per entry; the sweep stops at the first reading that reaches the deadline.
        self.assertEqual(self.swept(deadline=3.0, clock=ticking()), 3)
        self.assertEqual(len(self.names()), 5)

    def test_a_deadline_that_has_passed_removes_nothing(self):
        self.file("old-a", 90)
        self.assertEqual(self.swept(deadline=0.0, clock=lambda: 5.0), 0)
        self.assertEqual(self.names(), ["old-a"])

    def test_by_default_the_deadline_is_judged_on_the_monotonic_clock(self):
        self.file("old-a", 90)
        self.assertEqual(self.swept(deadline=time.monotonic() - 1.0), 0)
        self.assertEqual(self.swept(deadline=time.monotonic() + 60.0), 1)


class FailureTest(SweepTestCase):
    def test_an_entry_that_vanishes_after_the_scan_is_skipped_and_the_sweep_goes_on(self):
        self.file("old-a", 90)
        self.file("old-b", 90)
        real_unlink = os.unlink
        vanished = []

        def unlink(path, *args, **kwargs):
            if not vanished:
                vanished.append(path)
                real_unlink(path)  # someone else got there first
            return real_unlink(path, *args, **kwargs)

        with mock.patch("jam.sweep.os.unlink", unlink):
            self.assertEqual(self.swept(), 1)
        self.assertEqual(self.names(), [])

    def test_an_entry_that_vanishes_before_it_is_examined_is_skipped_and_the_sweep_goes_on(self):
        class Vanished:
            name, path = "old-gone", "/opt/jam/old-gone"

            def stat(self, follow_symlinks=True):
                raise FileNotFoundError(errno.ENOENT, "No such file or directory", self.path)

        self.file("old-a", 90)
        real_scandir = os.scandir

        def scandir(path):
            with real_scandir(path) as scan:
                return contextlib.nullcontext([Vanished(), *scan])

        with mock.patch("jam.sweep.os.scandir", scandir):
            self.assertEqual(self.swept(), 1)
        self.assertEqual(self.names(), [])

    def test_any_other_error_stops_the_sweep_quietly_and_reports_what_was_done(self):
        for number in range(3):
            self.file(f"old-{number}", 90)
        denied = PermissionError(errno.EACCES, "Permission denied")
        with mock.patch("jam.sweep.os.unlink", side_effect=denied) as unlink:
            self.assertEqual(self.swept(), 0)
        self.assertEqual(unlink.call_count, 1)
        self.assertEqual(len(self.names()), 3)

    def test_an_error_while_reading_an_entry_stops_the_sweep_quietly_and_does_not_just_skip_that_entry(self):
        class Unstatable:
            name, path = "old-a", "/opt/jam/old-a"

            def stat(self, follow_symlinks=True):
                raise PermissionError(errno.EACCES, "Permission denied", self.path)

        stale = self.file("old-b", 90)  # listed after the entry that cannot be read, and expired
        real_scandir = os.scandir

        def scandir(path):
            with real_scandir(path) as scan:
                return contextlib.nullcontext([Unstatable(), *scan])

        with mock.patch("jam.sweep.os.scandir", scandir):
            self.assertEqual(self.swept(), 0)
        self.assertTrue(stale.exists())

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "a permission bit does not stop root")
    def test_a_directory_that_cannot_be_listed_is_nothing_to_sweep(self):
        self.file("old-a", 90)
        self.root.chmod(0)
        self.addCleanup(self.root.chmod, 0o700)
        self.assertEqual(self.swept(), 0)

    def test_the_scan_is_closed_even_when_the_cap_cuts_it_short(self):
        for number in range(5):
            self.file(f"old-{number}", 90)
        closed = []
        real_scandir = os.scandir

        class Recorded:
            def __init__(self, scan):
                self.scan = scan

            def __enter__(self):
                return self.scan.__enter__()

            def __exit__(self, *error):
                closed.append(True)
                return self.scan.__exit__(*error)

        with mock.patch("jam.sweep.os.scandir", lambda path: Recorded(real_scandir(path))):
            self.swept(limit=2)
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
