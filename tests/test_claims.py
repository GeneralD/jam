"""Tests for the guard's state files: create-once deny claims, the hour slots, and the readers of the marks other code writes.

Real temp directories throughout. The writers of the start record and the worker
mark are tested in test_start_marks.py, so these tests plant those files by hand.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy

claims = lazy("jam.claims")

SID = "aaaa1111-0000-4000-8000-000000000001"
OTHER_SID = "bbbb2222-0000-4000-8000-000000000002"
REPO = "0123456789abcdef"
OTHER_REPO = "fedcba9876543210"
HOUR = 490000
SRC = str(Path(support.__file__).resolve().parent.parent / "src")
RACER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from jam.claims import Claims
while time.time() < float(sys.argv[3]):
    pass
print(int(Claims(sys.argv[2]).claim_pair(sys.argv[4], sys.argv[5])))
"""
BAD_IDS = ["", "../x", "a/b", "-x", ".hidden", "x" * 65, "a\x00b", None, 5, True, ["a"]]
BAD_KEYS = ["", "abc", "0123456789abcde", "0123456789abcdef0", "0123456789ABCDEF", "0123456789abcdeg", "../../etc/pass", None, 5]


class ClaimsTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"
        self.claims = claims.Claims(str(self.data))

    @property
    def state(self):
        return self.data / "guard-v1"

    def plant(self, name, data=b""):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / name).write_bytes(data)

    def tree(self):
        return sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))


class PairClaimTest(ClaimsTestCase):
    def test_the_first_claim_of_a_session_and_repository_wins_and_the_second_does_not(self):
        self.assertIs(self.claims.claim_pair(SID, REPO), True)
        self.assertIs(self.claims.claim_pair(SID, REPO), False)
        self.assertEqual(self.tree(), ["data", "data/guard-v1", f"data/guard-v1/denied.{SID}.{REPO}"])

    def test_another_repository_and_another_session_each_get_their_own_claim(self):
        self.assertIs(self.claims.claim_pair(SID, REPO), True)
        self.assertIs(self.claims.claim_pair(SID, OTHER_REPO), True)
        self.assertIs(self.claims.claim_pair(OTHER_SID, REPO), True)

    def test_a_fresh_instance_over_the_same_directory_still_sees_the_claim_as_after_a_resume(self):
        self.claims.claim_pair(SID, REPO)
        self.assertIs(claims.Claims(str(self.data)).claim_pair(SID, REPO), False)

    def test_pair_claimed_reports_a_claim_without_making_one(self):
        self.assertIs(self.claims.pair_claimed(SID, REPO), False)
        self.assertEqual(self.tree(), [])
        self.claims.claim_pair(SID, REPO)
        self.assertIs(self.claims.pair_claimed(SID, REPO), True)
        self.assertIs(self.claims.pair_claimed(SID, OTHER_REPO), False)
        self.assertIs(self.claims.pair_claimed(OTHER_SID, REPO), False)

    def test_a_session_id_with_dots_is_a_session_id_like_any_other(self):
        self.assertIs(self.claims.claim_pair("a.b.c", REPO), True)
        self.assertIs(self.claims.claim_pair("a.b", REPO), True)
        self.assertIs(self.claims.pair_claimed("a.b.c", REPO), True)

    def test_an_invalid_session_id_or_key_is_refused_before_any_file_name_is_built(self):
        with mock.patch("jam.claims.os.open", side_effect=AssertionError("a file was opened")), mock.patch("jam.claims.os.makedirs", side_effect=AssertionError("a directory was made")):
            for sid in BAD_IDS:
                with self.subTest(sid=repr(sid)):
                    self.assertIs(self.claims.claim_pair(sid, REPO), False)
                    self.assertIs(self.claims.pair_claimed(sid, REPO), False)
            for key in BAD_KEYS:
                with self.subTest(key=repr(key)):
                    self.assertIs(self.claims.claim_pair(SID, key), False)
                    self.assertIs(self.claims.pair_claimed(SID, key), False)
        self.assertEqual(self.tree(), [])

    def test_a_claim_is_never_created_through_a_link_that_was_planted_under_its_name(self):
        outside = self.root / "outside"
        self.state.mkdir(parents=True)
        (self.state / f"denied.{SID}.{REPO}").symlink_to(outside)
        self.assertIs(self.claims.claim_pair(SID, REPO), False)
        self.assertFalse(outside.exists())


class UnusableDirectoryTest(ClaimsTestCase):
    def test_no_data_directory_at_all_means_no_claim_and_no_file(self):
        before = self.tree()
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        for data in (None, "", "relative/dir", ".", 5, b"/abs", ["/abs"], "/abs\x00dir"):
            with self.subTest(data=repr(data)):
                unusable = claims.Claims(data)
                self.assertIs(unusable.claim_pair(SID, REPO), False)
                self.assertIs(unusable.pair_claimed(SID, REPO), False)
                self.assertIs(unusable.claim_slot(HOUR), False)
                self.assertIs(unusable.throttled(HOUR), False)
                self.assertIs(unusable.worker_marked(SID), False)
                self.assertIsNone(unusable.start_recorded(SID))
        self.assertEqual(self.tree(), before)

    def test_a_data_directory_that_is_a_regular_file_means_no_claim(self):
        self.data.write_text("not a directory", encoding="utf-8")
        self.assertIs(self.claims.claim_pair(SID, REPO), False)
        self.assertIs(self.claims.claim_slot(HOUR), False)
        self.assertEqual(self.data.read_text(encoding="utf-8"), "not a directory")

    def test_a_state_directory_that_is_a_regular_file_means_no_claim(self):
        self.data.mkdir()
        (self.data / "guard-v1").write_text("not a directory", encoding="utf-8")
        self.assertIs(self.claims.claim_pair(SID, REPO), False)
        self.assertIs(self.claims.claim_slot(HOUR), False)

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "a permission bit does not stop root")
    def test_a_state_directory_that_cannot_be_written_means_no_claim_and_leaves_it_alone(self):
        self.state.mkdir(parents=True)
        self.state.chmod(0o500)
        self.addCleanup(self.state.chmod, 0o700)
        self.assertIs(self.claims.claim_pair(SID, REPO), False)
        self.assertIs(self.claims.claim_slot(HOUR), False)
        self.assertEqual(list(self.state.iterdir()), [])

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "a permission bit does not stop root")
    def test_a_data_directory_that_cannot_be_entered_means_no_claim_and_no_read(self):
        self.state.mkdir(parents=True)
        self.plant(f"worker.{SID}")
        self.data.chmod(0)
        self.addCleanup(self.data.chmod, 0o700)
        self.assertIs(self.claims.claim_pair(SID, REPO), False)
        self.assertIs(self.claims.pair_claimed(SID, REPO), False)
        self.assertIs(self.claims.worker_marked(SID), False)
        self.assertIsNone(self.claims.start_recorded(SID))

    def test_a_directory_that_does_not_exist_yet_is_created_private_whatever_the_umask(self):
        for umask in (0o000, 0o077):
            with self.subTest(umask=oct(umask)):
                shutil.rmtree(self.data, ignore_errors=True)
                previous = os.umask(umask)
                try:
                    self.assertIs(claims.Claims(str(self.data)).claim_pair(SID, REPO), True)
                    self.assertIs(claims.Claims(str(self.data)).claim_slot(HOUR), True)
                finally:
                    os.umask(previous)
                self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
                for path in self.state.iterdir():
                    with self.subTest(file=path.name.split(".")[0]):
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_construction_and_every_read_create_nothing(self):
        reader = claims.Claims(str(self.data))
        reader.pair_claimed(SID, REPO)
        reader.throttled(HOUR)
        reader.worker_marked(SID)
        reader.start_recorded(SID)
        self.assertEqual(self.tree(), [])


class SlotTest(ClaimsTestCase):
    def test_the_named_constant_is_twenty_slots_an_hour(self):
        self.assertEqual(claims.SLOTS_PER_HOUR, 20)

    def test_every_slot_of_an_hour_is_claimed_once_and_then_the_hour_is_full(self):
        results = [self.claims.claim_slot(HOUR) for _ in range(claims.SLOTS_PER_HOUR + 1)]
        self.assertEqual(results, [True] * claims.SLOTS_PER_HOUR + [False])
        names = sorted(path.name for path in self.state.iterdir())
        self.assertEqual(names, sorted(f"slot.{HOUR}.{n}" for n in range(claims.SLOTS_PER_HOUR)))

    def test_the_next_hour_starts_empty_and_the_full_one_stays_full(self):
        [self.claims.claim_slot(HOUR) for _ in range(claims.SLOTS_PER_HOUR)]
        self.assertIs(self.claims.claim_slot(HOUR + 1), True)
        self.assertIs(self.claims.claim_slot(HOUR), False)

    def test_throttled_turns_true_with_the_last_slot_and_not_before(self):
        self.assertIs(self.claims.throttled(HOUR), False)
        [self.claims.claim_slot(HOUR) for _ in range(claims.SLOTS_PER_HOUR - 1)]
        self.assertIs(self.claims.throttled(HOUR), False)
        self.claims.claim_slot(HOUR)
        self.assertIs(self.claims.throttled(HOUR), True)
        self.assertIs(self.claims.throttled(HOUR + 1), False)

    def test_the_last_slot_alone_reports_the_hour_as_throttled(self):
        self.plant(f"slot.{HOUR}.{claims.SLOTS_PER_HOUR - 1}")
        self.assertIs(self.claims.throttled(HOUR), True)

    def test_slots_are_shared_by_everyone_who_uses_the_directory(self):
        [claims.Claims(str(self.data)).claim_slot(HOUR) for _ in range(claims.SLOTS_PER_HOUR)]
        self.assertIs(self.claims.claim_slot(HOUR), False)

    def test_an_hour_that_is_not_a_non_negative_integer_claims_nothing(self):
        for hour in (-1, 1.5, "490000", None, True, float("nan")):
            with self.subTest(hour=repr(hour)):
                self.assertIs(self.claims.claim_slot(hour), False)
                self.assertIs(self.claims.throttled(hour), False)
        self.assertEqual(self.tree(), [])

    def test_a_failure_other_than_a_taken_slot_stops_the_search_at_once(self):
        self.claims.claim_slot(HOUR)
        with mock.patch("jam.claims.os.open", side_effect=OSError(28, "No space left on device")) as opened:
            self.assertIs(self.claims.claim_slot(HOUR), False)
        self.assertEqual(opened.call_count, 1)


class RaceTest(ClaimsTestCase):
    def race(self, work, count=16):
        gate, outcomes = threading.Barrier(count), []

        def runner():
            gate.wait(timeout=30)
            outcomes.append(work())

        threads = [threading.Thread(target=runner) for _ in range(count)]
        [thread.start() for thread in threads]
        [thread.join(timeout=60) for thread in threads]
        return outcomes

    def test_sixteen_threads_with_their_own_instances_produce_exactly_one_winner(self):
        outcomes = self.race(lambda: claims.Claims(str(self.data)).claim_pair(SID, REPO))
        self.assertEqual((len(outcomes), outcomes.count(True)), (16, 1))

    def test_sixteen_threads_sharing_one_instance_produce_exactly_one_winner(self):
        outcomes = self.race(lambda: self.claims.claim_pair(SID, REPO))
        self.assertEqual((len(outcomes), outcomes.count(True)), (16, 1))

    def test_thirty_threads_asking_for_a_slot_fill_the_hour_exactly(self):
        outcomes = self.race(lambda: self.claims.claim_slot(HOUR), count=30)
        self.assertEqual((len(outcomes), outcomes.count(True)), (30, claims.SLOTS_PER_HOUR))

    def test_four_processes_produce_exactly_one_winner(self):
        # Child interpreters, as the registry's lock test does: they need no importable test module, which the spawn start method would.
        start = time.time() + 2.0
        children = [
            subprocess.Popen([sys.executable, "-I", "-c", RACER, SRC, str(self.data), str(start), SID, REPO], stdout=subprocess.PIPE, text=True)
            for _ in range(4)
        ]
        results = [child.communicate(timeout=60)[0].strip() for child in children]
        self.assertEqual([child.returncode for child in children], [0] * 4)
        self.assertEqual(sorted(results), ["0", "0", "0", "1"])


class ReaderTest(ClaimsTestCase):
    def test_the_worker_mark_is_read_by_name_and_only_by_the_session_it_belongs_to(self):
        self.assertIs(self.claims.worker_marked(SID), False)
        self.plant(f"worker.{SID}")
        self.assertIs(self.claims.worker_marked(SID), True)
        self.assertIs(self.claims.worker_marked(OTHER_SID), False)

    def test_the_worker_mark_needs_a_valid_session_id(self):
        self.plant("worker.")
        for sid in BAD_IDS:
            with self.subTest(sid=repr(sid)):
                self.assertIs(self.claims.worker_marked(sid), False)

    def test_the_start_record_is_the_path_it_holds_without_the_line_feed(self):
        self.plant(f"start.{SID}", b"/work/app\n")
        self.assertEqual(self.claims.start_recorded(SID), "/work/app")
        self.assertIsNone(self.claims.start_recorded(OTHER_SID))

    def test_a_start_record_that_is_not_complete_or_not_a_path_reads_as_absent(self):
        cases = {
            "no trailing line feed": b"/work/app",
            "empty": b"",
            "only a line feed": b"\n",
            "relative": b"work/app\n",
            "nul inside": b"/work\x00/app\n",
            "over the limit": b"/" + b"a" * 5000 + b"\n",
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                self.plant(f"start.{SID}", data)
                self.assertIsNone(self.claims.start_recorded(SID))

    def test_a_start_record_that_is_a_link_a_directory_or_a_pipe_reads_as_absent(self):
        self.state.mkdir(parents=True)
        real = self.root / "real"
        real.write_bytes(b"/work/app\n")
        (self.state / f"start.{SID}").symlink_to(real)
        self.assertIsNone(self.claims.start_recorded(SID))
        (self.state / f"start.{SID}").unlink()
        (self.state / f"start.{SID}").mkdir()
        self.assertIsNone(self.claims.start_recorded(SID))
        (self.state / f"start.{SID}").rmdir()
        os.mkfifo(self.state / f"start.{SID}")
        self.assertIsNone(self.claims.start_recorded(SID))

    def test_the_start_record_needs_a_valid_session_id(self):
        for sid in BAD_IDS:
            with self.subTest(sid=repr(sid)):
                self.assertIsNone(self.claims.start_recorded(sid))

    def test_a_start_path_may_hold_spaces_and_non_ascii_characters(self):
        self.plant(f"start.{SID}", "/work/my app/é\n".encode("utf-8"))
        self.assertEqual(self.claims.start_recorded(SID), "/work/my app/é")


class ClaimNameTest(unittest.TestCase):
    def test_deny_claims_and_hour_slots_are_state_names(self):
        for name in (f"denied.{SID}.{REPO}", "denied.a.b.c." + REPO, "denied.a." + REPO, "slot.490000.0", "slot.490000.19", "slot.0.7"):
            with self.subTest(name=name):
                self.assertTrue(claims.is_state_name(name))

    def test_the_fixed_width_suffix_is_anchored_so_dots_in_the_session_id_do_not_confuse_it(self):
        self.assertTrue(claims.is_state_name(f"denied.{'a.' * 20}b.{REPO}"))
        self.assertFalse(claims.is_state_name(f"denied.a.b.{REPO}0"))
        self.assertFalse(claims.is_state_name(f"denied.a.b.{REPO[:-1]}"))
        self.assertFalse(claims.is_state_name(f"denied.a.b.{REPO.upper()}"))
        self.assertFalse(claims.is_state_name(f"denied.{REPO}"))

    def test_anything_else_in_the_directory_is_not_a_state_name(self):
        for name in (
            "", "notes.txt", f"denied.{SID}", f"denied..{REPO}", f"denied.-x.{REPO}", f"denied.a/b.{REPO}", f"denied.{'x' * 65}.{REPO}",
            f"denied.{SID}.{REPO}\n", f"xdenied.{SID}.{REPO}", f"denied.{SID}.{REPO}.tmp",
            "slot.1", "slot.x.1", "slot.1.x", "slot.1.100", "slot..1", "slot.1.2\n", "slot.1.2.3", ".slot.1.2",
        ):
            with self.subTest(name=name):
                self.assertFalse(claims.is_state_name(name))


class StateDirTest(unittest.TestCase):
    def test_it_is_the_versioned_directory_below_an_absolute_data_directory(self):
        self.assertEqual(claims.state_dir("/opt/jam/data"), "/opt/jam/data/guard-v1")
        self.assertEqual(claims.STATE_DIR, "guard-v1")

    def test_what_is_not_an_absolute_path_without_nul_has_none(self):
        for bad in (None, "", "rel", ".", "/a\0b", 5, b"/abs"):
            with self.subTest(bad=repr(bad)):
                self.assertIsNone(claims.state_dir(bad))


if __name__ == "__main__":
    unittest.main()
