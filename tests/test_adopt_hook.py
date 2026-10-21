"""Tests for the `adopt` handler: the start record, and the worker mark taken from a spawn ticket.

Everything runs in process through the hook's `main`, with the streams, the
environment and the alarm injected (see `run` in test_claude_hooks), so no test
starts a session or arms a real alarm. The data directory is a temp directory.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

from test_claude_hooks import BAD_STDIN, DATA_VAR, payload, run
from test_operations import SESSION_ID, lazy

tickets = lazy("jam.tickets")
claims = lazy("jam.claims")

OTHER_SID = "bbbb2222-0000-4000-8000-000000000002"
MINUTE = 60.0


class AdoptCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"
        self.app = self.root / "app"
        self.app.mkdir()
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)

    @property
    def state(self):
        return self.data / "guard-v1"

    @property
    def pending(self):
        return self.data / "pending-v1"

    def adopt(self, sid=SESSION_ID, cwd=None, source="startup", env=None):
        """Run the hook as the platform would, with `cwd` (the app by default) and the data directory in the environment."""
        cwd = str(self.app) if cwd is None else cwd
        environment = {DATA_VAR: str(self.data)} if env is None else env
        return run("adopt", stdin=payload(session_id=sid, cwd=cwd, source=source), env=environment)

    def ticket(self, age=1.0, cwd=None, name=None):
        """A ticket for `cwd` (the app by default) that is `age` seconds old, written as spawn writes it."""
        path = tickets.Tickets(str(self.data)).issue(self.app if cwd is None else cwd)
        if name is not None:
            renamed = self.pending / name
            os.rename(path, renamed)
            path = str(renamed)
        when = time.time() - age
        os.utime(path, (when, when))
        return Path(path)

    def tree(self):
        return sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")) if self.root.exists() else []

    def mark(self, sid=SESSION_ID):
        return self.state / f"worker.{sid}"


class StartRecordTest(AdoptCase):
    def test_the_start_record_is_written_once_and_keeps_its_first_content(self):
        other = self.root / "other"
        other.mkdir()
        self.adopt(cwd=str(self.app))
        self.adopt(cwd=str(other), source="resume")
        self.assertEqual((self.state / f"start.{SESSION_ID}").read_bytes(), os.fsencode(os.path.realpath(self.app)) + b"\n")

    def test_a_clear_or_a_compact_writes_the_start_record_too_when_it_is_missing(self):
        for source in ("clear", "compact"):
            with self.subTest(source=source):
                sid = f"cccc3333-{source}"
                self.adopt(sid=sid, source=source)
                self.assertEqual(self.book_start(sid), os.path.realpath(self.app))

    def book_start(self, sid):
        return claims.Claims(str(self.data)).start_recorded(sid)

    def test_a_cwd_too_long_for_the_record_writes_nothing_at_all(self):
        self.adopt(cwd="/" + "a" * 5000)
        self.assertFalse((self.state / f"start.{SESSION_ID}").exists())
        self.assertEqual(self.tree(), ["app"])

    def test_an_invalid_session_id_a_relative_or_missing_cwd_or_no_data_directory_does_nothing(self):
        cases = (
            dict(sid="../escape"),
            dict(sid=None),
            dict(cwd="relative/app"),
            dict(cwd="/a\0b"),
            dict(env={}),
            dict(env={DATA_VAR: "relative/data"}),
        )
        for case in cases:
            with self.subTest(case=repr(case)):
                result = self.adopt(**case)
                self.assertEqual((result.code, result.out, result.err), (0, "", ""))
                self.assertFalse(self.data.exists())

    def test_a_missing_cwd_field_does_nothing(self):
        result = run("adopt", stdin=b'{"session_id": "%s", "source": "startup"}' % SESSION_ID.encode("ascii"), env={DATA_VAR: str(self.data)})
        self.assertEqual((result.code, result.out, result.err), (0, "", ""))
        self.assertFalse(self.data.exists())


class WorkerMarkTest(AdoptCase):
    def test_a_fresh_ticket_of_the_directory_becomes_the_worker_mark_and_leaves_the_directory(self):
        ticket = self.ticket(age=2 * MINUTE)
        self.adopt()
        mark = self.mark()
        info = os.lstat(mark)
        self.assertEqual((stat.S_ISREG(info.st_mode), stat.S_IMODE(info.st_mode), info.st_size), (True, 0o600, 0))
        self.assertFalse(ticket.exists())

    def test_the_hook_prints_nothing_exits_zero_and_arms_its_own_alarm_of_three_seconds(self):
        self.ticket()
        result = self.adopt()
        self.assertEqual((result.code, result.out, result.err, result.alarms), (0, "", "", [3, 0]))

    def test_the_freshest_ticket_is_the_one_claimed(self):
        old = self.ticket(age=4 * MINUTE, name=f"{tickets.dir_key(self.app)}.{1:016x}")
        fresh = self.ticket(age=MINUTE, name=f"{tickets.dir_key(self.app)}.{2:016x}")
        self.adopt()
        self.assertFalse(fresh.exists())
        self.assertTrue(old.exists())

    def test_a_ticket_older_than_five_minutes_is_left_alone(self):
        stale = self.ticket(age=6 * MINUTE)
        self.adopt()
        self.assertFalse(self.mark().exists())
        self.assertTrue(stale.exists())

    def test_a_ticket_of_another_directory_is_left_alone(self):
        other = self.root / "other"
        other.mkdir()
        foreign = self.ticket(cwd=other)
        self.adopt()
        self.assertFalse(self.mark().exists())
        self.assertTrue(foreign.exists())

    def test_an_existing_mark_claims_no_ticket(self):
        self.state.mkdir(parents=True)
        (self.state / f"worker.{SESSION_ID}").write_bytes(b"")
        ticket = self.ticket()
        self.adopt()
        self.assertTrue(ticket.exists())

    def test_clear_and_compact_claim_no_ticket_but_write_the_start_record(self):
        for source in ("clear", "compact"):
            with self.subTest(source=source):
                ticket = self.ticket()
                self.adopt(source=source)
                self.assertFalse(self.mark().exists())
                self.assertTrue(ticket.exists())
                ticket.unlink()

    def test_any_other_source_claims_the_ticket(self):
        for source in ("startup", "resume", "fork", "something new", None):
            with self.subTest(source=source):
                ticket = self.ticket()
                self.adopt(source=source)
                self.assertTrue(self.mark().exists())
                self.mark().unlink()
                self.assertFalse(ticket.exists())

    def test_a_ticket_that_vanishes_before_the_rename_gives_way_to_the_next_one(self):
        first = self.ticket(age=1.0, name=f"{tickets.dir_key(self.app)}.{1:016x}")
        second = self.ticket(age=9.0, name=f"{tickets.dir_key(self.app)}.{2:016x}")
        real_rename = os.rename
        sources = []

        def racing(source, target):
            sources.append(source)
            if len(sources) == 1:
                os.unlink(source)
            return real_rename(source, target)

        with mock.patch("os.rename", side_effect=racing):
            self.adopt()
        self.assertEqual(sources, [str(first), str(second)])
        self.assertTrue(self.mark().exists())

    def test_at_most_eight_renames_are_attempted(self):
        made = [self.ticket(age=1.0 + number, name=f"{tickets.dir_key(self.app)}.{number:016x}") for number in range(10)]
        sources = []

        def gone(source, target):
            sources.append(source)
            raise FileNotFoundError(2, "gone")

        with mock.patch("os.rename", side_effect=gone):
            result = self.adopt()
        self.assertEqual(sources, [str(path) for path in made[:8]])
        self.assertEqual((result.code, result.err), (0, ""))

    def test_a_symlinked_working_directory_names_the_same_tickets_as_the_spawn(self):
        link = self.root / "link"
        link.symlink_to(self.app)
        self.ticket(cwd=link)
        self.adopt(cwd=str(self.app))
        self.assertTrue(self.mark().exists())

    def test_the_mark_of_a_session_is_its_own_and_another_session_is_unaffected(self):
        self.ticket()
        self.adopt(sid=OTHER_SID)
        self.assertTrue((self.state / f"worker.{OTHER_SID}").exists())
        self.assertFalse(self.mark().exists())


class FailOpenAdoptTest(AdoptCase):
    def test_every_unusable_payload_prints_nothing_and_exits_zero(self):
        self.ticket()
        for name, stdin in BAD_STDIN.items():
            with self.subTest(stdin=name):
                result = run("adopt", stdin=stdin, env={DATA_VAR: str(self.data)})
                self.assertEqual((result.code, result.out, result.err), (0, "", ""))

    def test_a_failure_in_the_start_record_still_lets_the_mark_be_taken(self):
        self.ticket()
        with mock.patch("jam.claims.Claims.record_start", side_effect=RuntimeError("bug")):
            result = self.adopt()
        self.assertEqual((result.code, result.out, result.err), (0, "", "RuntimeError\n"))
        self.assertTrue(self.mark().exists())

    def test_a_failure_in_the_mark_is_reported_by_type_and_the_start_record_is_still_written(self):
        with mock.patch("jam.tickets.claim_mark", side_effect=RuntimeError("/private/path")):
            result = self.adopt()
        self.assertEqual((result.code, result.out, result.err), (0, "", "RuntimeError\n"))
        self.assertTrue((self.state / f"start.{SESSION_ID}").exists())


if __name__ == "__main__":
    unittest.main()
