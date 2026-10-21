"""Tests for the spawn tickets: the directory key, the names, the writer, the candidates a session start may claim, and the claim itself.

Real temporary directories and real files throughout. The age of a ticket is
passed in as `now`, so no test waits for a clock.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy

tickets = lazy("jam.tickets")
errors = lazy("jam.errors")

KEY = "0123456789abcdef"
OTHER_KEY = "fedcba9876543210"
SID = "aaaa1111-0000-4000-8000-000000000001"
NOW = 1_800_000_000.0
FRESH = 300.0  # the age a ticket may have and still be claimed


class TicketCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"
        self.pending = self.data / "pending-v1"
        self.cwd = self.root / "app"
        self.cwd.mkdir()
        self.key = tickets.dir_key(self.cwd)

    def plant(self, name, age=0.0, data=b""):
        self.pending.mkdir(parents=True, exist_ok=True)
        path = self.pending / name
        path.write_bytes(data)
        os.utime(path, (NOW - age, NOW - age))
        return path

    def names(self, paths):
        return [Path(path).name for path in paths]


class DirKeyTest(TicketCase):
    def test_the_path_through_a_symlinked_parent_and_its_resolved_form_name_the_same_directory(self):
        real = self.root / "real"
        (real / "app").mkdir(parents=True)
        (self.root / "link").symlink_to(real)
        keys = {tickets.dir_key(real / "app"), tickets.dir_key(self.root / "link" / "app"), tickets.dir_key(Path(self.root / "link" / "app").resolve())}
        self.assertEqual(len(keys), 1)

    def test_it_is_the_first_sixteen_hex_digits_of_the_sha256_of_the_real_path(self):
        expected = hashlib.sha256(os.fsencode(os.path.realpath(self.cwd))).hexdigest()[:16]
        self.assertEqual(self.key, expected)
        self.assertRegex(self.key, r"\A[0-9a-f]{16}\Z")

    def test_different_directories_have_different_keys(self):
        other = self.root / "other"
        other.mkdir()
        self.assertNotEqual(tickets.dir_key(self.cwd), tickets.dir_key(other))

    def test_what_is_not_a_usable_path_has_no_key(self):
        for bad in (None, 5, b"/bytes", "/a\0b", "/a/\ud800", ["/list"]):
            with self.subTest(bad=repr(bad)):
                self.assertIsNone(tickets.dir_key(bad))


class NameTest(unittest.TestCase):
    def test_a_ticket_name_is_sixteen_hex_digits_a_dot_and_sixteen_more(self):
        self.assertTrue(tickets.is_ticket_name(f"{KEY}.{OTHER_KEY}"))

    def test_anything_else_is_not_a_ticket_name_including_a_trailing_line_feed(self):
        for name in (
            f"{KEY}.{OTHER_KEY}\n", f"{KEY.upper()}.{OTHER_KEY}", f"{KEY}.", f"{KEY}.{OTHER_KEY[:-1]}", f"{KEY}.{OTHER_KEY}.tmp",
            f"{KEY}{OTHER_KEY}", f"{KEY}-{OTHER_KEY}", "", "x" * 33, f"{KEY}.{OTHER_KEY}0x", None, 5,
        ):
            with self.subTest(name=repr(name)):
                self.assertFalse(tickets.is_ticket_name(name))


class WriterTest(TicketCase):
    def setUp(self):
        super().setUp()
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)

    def test_the_ticket_is_an_empty_private_file_in_a_private_directory_whatever_the_umask(self):
        path = tickets.Tickets(str(self.data)).issue(self.cwd)
        self.assertEqual(os.path.dirname(path), str(self.pending))
        self.assertTrue(tickets.is_ticket_name(os.path.basename(path)))
        self.assertTrue(os.path.basename(path).startswith(self.key + "."))
        info = os.lstat(path)
        self.assertEqual((stat.S_ISREG(info.st_mode), stat.S_IMODE(info.st_mode), info.st_size), (True, 0o600, 0))
        self.assertEqual(stat.S_IMODE(os.lstat(self.pending).st_mode), 0o700)

    def test_the_ticket_directory_is_private_under_a_restrictive_umask(self):
        os.umask(0o277)
        path = tickets.Tickets(str(self.data)).issue(self.cwd)
        self.assertEqual(stat.S_IMODE(os.lstat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(self.pending).st_mode), 0o700)

    def test_each_ticket_has_its_own_nonce(self):
        writer = tickets.Tickets(str(self.data))
        self.assertNotEqual(writer.issue(self.cwd), writer.issue(self.cwd))

    def test_withdrawing_removes_the_ticket_and_withdrawing_it_again_is_no_problem(self):
        writer = tickets.Tickets(str(self.data))
        path = writer.issue(self.cwd)
        writer.withdraw(path)
        self.assertFalse(os.path.exists(path))
        writer.withdraw(path)

    def test_withdraw_raises_a_failure_other_than_a_missing_file(self):
        writer = tickets.Tickets(str(self.data))
        path = writer.issue(self.cwd)
        with mock.patch("os.unlink", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(PermissionError):
                writer.withdraw(path)

    def test_no_data_directory_or_a_relative_one_writes_nothing_and_raises_nothing(self):
        for data in (None, "", "relative/dir"):
            with self.subTest(data=repr(data)):
                self.assertIsNone(tickets.Tickets(data).issue(self.cwd))
        self.assertEqual(os.listdir(self.root), ["app"])

    def test_a_link_in_place_of_the_ticket_directory_writes_nothing_and_raises_only_a_path_free_error(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.data.mkdir()
        (self.data / "pending-v1").symlink_to(outside)
        with self.assertRaises(errors.RegistryError) as caught:
            tickets.Tickets(str(self.data)).issue(self.cwd)
        self.assertNotIn(str(self.root), str(caught.exception))
        self.assertEqual(os.listdir(outside), [])

    def test_a_directory_that_cannot_be_keyed_is_refused_with_the_same_error(self):
        with self.assertRaises(errors.RegistryError):
            tickets.Tickets(str(self.data)).issue(5)


class CandidateTest(TicketCase):
    def candidates(self, cwd=None, now=NOW):
        return tickets.candidates(str(self.data), self.cwd if cwd is None else cwd, now)

    def test_the_freshest_ticket_comes_first(self):
        for age in (10, 1, 100):
            self.plant(f"{self.key}.{age:016x}", age)
        self.assertEqual(self.names(self.candidates()), [f"{self.key}.{age:016x}" for age in (1, 10, 100)])

    def test_a_ticket_older_than_five_minutes_is_not_a_candidate_and_one_of_exactly_five_is(self):
        self.plant(f"{self.key}.{1:016x}", FRESH)
        self.plant(f"{self.key}.{2:016x}", FRESH + 1)
        self.assertEqual(self.names(self.candidates()), [f"{self.key}.{1:016x}"])

    def test_a_ticket_dated_in_the_future_counts_as_fresh(self):
        self.plant(f"{self.key}.{3:016x}", -3600.0)
        self.assertEqual(self.names(self.candidates()), [f"{self.key}.{3:016x}"])

    def test_tickets_of_other_directories_are_ignored(self):
        self.plant(f"{OTHER_KEY}.{4:016x}", 1)
        self.assertEqual(self.candidates(), [])

    def test_links_directories_and_malformed_names_are_ignored(self):
        real = self.plant(f"{self.key}.{5:016x}", 1)
        (self.pending / f"{self.key}.{6:016x}").symlink_to(real)
        (self.pending / f"{self.key}.{7:016x}").mkdir()
        os.utime(self.pending / f"{self.key}.{6:016x}", (NOW - 1, NOW - 1), follow_symlinks=False)
        os.utime(self.pending / f"{self.key}.{7:016x}", (NOW - 1, NOW - 1))
        self.plant(f"{self.key}.{8:016x}".upper(), 1)
        self.plant(f"{self.key}.{9:016x}.tmp", 1)
        self.plant(f"x{self.key}.{10:016x}", 1)
        self.assertEqual(self.names(self.candidates()), [f"{self.key}.{5:016x}"])

    def test_at_most_eight_candidates_come_back(self):
        for number in range(10):
            self.plant(f"{self.key}.{number:016x}", 1 + number)
        self.assertEqual(self.names(self.candidates()), [f"{self.key}.{number:016x}" for number in range(8)])

    def test_at_most_1024_entries_are_looked_at_whatever_their_names(self):
        for number in range(1100):
            self.plant(f"foreign-{number}", 1)
        counted = []
        real_scandir = os.scandir

        class Counting:
            def __init__(self, path):
                self.scan = real_scandir(path)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.scan.close()

            def __iter__(self):
                for entry in self.scan:
                    counted.append(entry.name)
                    yield entry

        with mock.patch("os.scandir", side_effect=Counting):
            self.assertEqual(self.candidates(), [])
        self.assertEqual(len(counted), 1024)

    def test_no_directory_no_key_or_no_data_directory_gives_no_candidates(self):
        self.plant(f"{self.key}.{11:016x}", 1)
        self.assertEqual(tickets.candidates(str(self.root / "absent"), self.cwd, NOW), [])
        self.assertEqual(tickets.candidates(None, self.cwd, NOW), [])
        self.assertEqual(tickets.candidates(str(self.data), 5, NOW), [])

    def test_a_pending_directory_that_is_a_link_is_not_listed_through(self):
        outside = self.root / "outside"
        outside.mkdir()
        ticket = outside / f"{self.key}.{12:016x}"
        ticket.write_bytes(b"")
        os.utime(ticket, (NOW - 1, NOW - 1))
        self.data.mkdir()
        (self.data / "pending-v1").symlink_to(outside)
        self.assertEqual(self.candidates(), [])
        self.assertFalse(tickets.claim_mark(str(self.data), SID, self.cwd, NOW))
        self.assertTrue(ticket.exists())


class ClaimTest(TicketCase):
    def claim(self, now=NOW):
        return tickets.claim_mark(str(self.data), SID, self.cwd, now)

    def test_the_freshest_ticket_becomes_the_worker_mark_and_leaves_the_directory(self):
        old = self.plant(f"{self.key}.{1:016x}", 60)
        fresh = self.plant(f"{self.key}.{2:016x}", 1)
        self.assertTrue(self.claim())
        mark = self.data / "guard-v1" / f"worker.{SID}"
        info = os.lstat(mark)
        self.assertEqual((stat.S_ISREG(info.st_mode), info.st_size), (True, 0))
        self.assertFalse(fresh.exists())
        self.assertTrue(old.exists())

    def test_an_existing_mark_claims_no_ticket(self):
        ticket = self.plant(f"{self.key}.{3:016x}", 1)
        (self.data / "guard-v1").mkdir(parents=True)
        (self.data / "guard-v1" / f"worker.{SID}").write_bytes(b"")
        self.assertFalse(self.claim())
        self.assertTrue(ticket.exists())

    def test_a_ticket_that_vanishes_before_the_move_gives_way_to_the_next_one(self):
        first = self.plant(f"{self.key}.{1:016x}", 1)
        second = self.plant(f"{self.key}.{2:016x}", 10)
        real_link = os.link
        sources = []

        def racing(source, target, **kwargs):
            sources.append(source)
            if len(sources) == 1:
                os.unlink(source)  # another session takes it between the listing and the move
            return real_link(source, target, **kwargs)

        with mock.patch("os.link", side_effect=racing):
            self.assertTrue(self.claim())
        self.assertEqual(sources, [str(first), str(second)])
        self.assertFalse(second.exists())
        self.assertTrue((self.data / "guard-v1" / f"worker.{SID}").is_file())

    def test_at_most_eight_moves_are_tried_when_each_ticket_is_gone(self):
        made = [self.plant(f"{self.key}.{number:016x}", 1 + number) for number in range(10)]
        sources = []

        def gone(source, target, **kwargs):
            sources.append(source)
            raise FileNotFoundError(2, "gone")

        with mock.patch("os.link", side_effect=gone):
            self.assertFalse(self.claim())
        self.assertEqual(sources, [str(path) for path in made[:8]])
        self.assertFalse((self.data / "guard-v1" / f"worker.{SID}").exists())

    def test_any_other_failure_ends_the_attempts_after_one_move(self):
        for number in range(3):
            self.plant(f"{self.key}.{number:016x}", 1 + number)
        with mock.patch("os.link", side_effect=PermissionError(13, "denied")) as link:
            self.assertFalse(self.claim())
        self.assertEqual(link.call_count, 1)

    def test_no_ticket_claims_nothing(self):
        self.assertFalse(self.claim())
        self.assertFalse((self.data / "guard-v1").exists())

    def test_an_invalid_session_id_lists_nothing_and_claims_nothing(self):
        ticket = self.plant(f"{self.key}.{5:016x}", 1)
        with mock.patch("os.scandir", wraps=os.scandir) as scan:
            self.assertFalse(tickets.claim_mark(str(self.data), "bad id/../x", self.cwd, NOW))
        scan.assert_not_called()
        self.assertTrue(ticket.exists())

    def test_the_mark_is_made_even_when_its_directory_does_not_exist_yet(self):
        self.plant(f"{self.key}.{4:016x}", 1)
        self.assertTrue(self.claim())
        self.assertEqual(stat.S_IMODE(os.lstat(self.data / "guard-v1").st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
