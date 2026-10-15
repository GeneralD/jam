"""Tests for the session registry: one small JSON file per session."""

import errno
import fcntl
import json
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
from jam.errors import InvalidRequest, RegistryError
from jam.registry import MAX_BYTES, Record, Registry, decoded, encoded, expired, spawned_marked

KEY = "aaaa1111"
CHILD = """
import sys
sys.path.insert(0, sys.argv[1])
from jam.registry import Registry
registry = Registry(sys.argv[2], lock_timeout=5)
for _ in range(20):
    registry.update("aaaa1111", lambda raw: {**raw, "n": raw.get("n", 0) + 1})
"""


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = self.root / "data"
        self.registry = Registry(self.data)

    @property
    def sessions_dir(self):
        return self.data / "sessions-v1"

    def path_of(self, key=KEY):
        return self.sessions_dir / f"{key}.json"

    def plant(self, key, data):
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.path_of(key).write_bytes(data)

    def tree(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))


class PureFunctionsTest(unittest.TestCase):
    def test_spawned_marked_adds_the_flag_and_keeps_everything_else(self):
        self.assertEqual(spawned_marked({"cwd": "/x"}), {"cwd": "/x", "spawned": True})

    def test_encoded_is_stable_ascii_with_one_trailing_newline(self):
        # Escaping keeps the file pure ASCII, so any text a note holds can be written.
        self.assertEqual(encoded({"b": 1, "a": "é\ud800"}), b'{"a":"\\u00e9\\ud800","b":1}\n')

    def test_decoded_returns_none_for_anything_that_is_not_an_object(self):
        for data in (b"{", b"[]", b"3", b"\xff\xfe", b"", b"[" * 60000):
            with self.subTest(data=data[:10]):
                self.assertIsNone(decoded(data))
        self.assertEqual(decoded(b'{"a": 1}'), {"a": 1})

    def test_expired_is_strictly_greater_than_and_ignores_future_mtimes(self):
        self.assertFalse(expired(100, 200, 100))
        self.assertTrue(expired(100, 201, 100))
        self.assertFalse(expired(300, 200, 100))

    def test_record_reads_spawned_only_when_it_is_exactly_true(self):
        self.assertTrue(Record.from_json({"spawned": True}).spawned)
        for value in ("yes", 1, None, [True]):
            with self.subTest(value=value):
                self.assertFalse(Record.from_json({"spawned": value}).spawned)
        self.assertFalse(Record.from_json({}).spawned)


class ConstructionTest(RegistryTestCase):
    def test_relative_or_malformed_data_dirs_are_rejected(self):
        for bad in ("", ".", "rel/dir", Path(""), None, 5):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(InvalidRequest):
                    Registry(bad)

    def test_a_bad_lock_timeout_is_rejected(self):
        for bad in (-1, "1", None):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(InvalidRequest):
                    Registry(self.data, lock_timeout=bad)

    def test_construction_and_reads_create_nothing(self):
        registry = Registry(self.data)
        self.assertIsNone(registry.record(KEY))
        self.assertEqual(registry.prune(), 0)
        self.assertEqual(self.tree(), [])


class KeyValidationTest(RegistryTestCase):
    def test_invalid_keys_are_rejected_before_any_path_is_built(self):
        bad = ["", "../x", "a/b", "-x", ".hidden", "x" * 65, "a\x00b", None, 5, True]
        for key in bad:
            with self.subTest(key=repr(key)):
                with self.assertRaises(InvalidRequest):
                    self.registry.update(key, spawned_marked)
                with self.assertRaises(InvalidRequest):
                    self.registry.remove(key)
                self.assertIsNone(self.registry.record(key))
        self.assertEqual(self.tree(), [])


class ReadingTest(RegistryTestCase):
    def test_absent_and_unusable_content_reads_as_no_record_and_heals_on_update(self):
        cases = [b"{", b"[]", b"\xff\xfe", b"", b"[" * 60000, b'{"a":"' + b"x" * MAX_BYTES + b'"}']
        for data in cases:
            with self.subTest(data=data[:12], size=len(data)):
                self.plant(KEY, data)
                self.plant("bbbb2222", b'{"spawned":true}')
                self.assertIsNone(self.registry.record(KEY))
                self.assertTrue(self.registry.record("bbbb2222").spawned)
                seen = []
                self.registry.update(KEY, lambda raw: seen.append(dict(raw)) or {**raw, "ok": 1})
                self.assertEqual(seen, [{}])
                self.assertEqual(json.loads(self.path_of().read_text()), {"ok": 1})

    def test_wrongly_typed_fields_are_ignored(self):
        for body, expected in ((b'{"spawned":"yes"}', False), (b'{"spawned":1}', False), (b'{"spawned":true}', True)):
            with self.subTest(body=body):
                self.plant(KEY, body)
                self.assertEqual(self.registry.record(KEY), Record(spawned=expected))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores file modes")
    def test_an_unreadable_record_is_an_error_not_an_absence(self):
        self.plant(KEY, b'{"spawned":true}')
        os.chmod(self.path_of(), 0)
        self.addCleanup(os.chmod, self.path_of(), 0o600)
        with self.assertRaises(RegistryError):
            self.registry.record(KEY)
        with self.assertRaises(RegistryError):
            self.registry.update(KEY, spawned_marked)
        os.chmod(self.path_of(), 0o600)
        self.assertEqual(self.path_of().read_bytes(), b'{"spawned":true}')


class WritingTest(RegistryTestCase):
    def test_update_keeps_unknown_keys(self):
        self.plant(KEY, b'{"spawned":true,"cwd":"/x","future":[1]}')
        self.registry.update(KEY, lambda raw: {**raw, "extra": 1})
        self.assertEqual(
            json.loads(self.path_of().read_text()),
            {"spawned": True, "cwd": "/x", "future": [1], "extra": 1},
        )

    def test_two_writers_adding_different_keys_merge_in_either_order(self):
        add_cwd = lambda raw: {**raw, "cwd": "/x"}  # noqa: E731
        self.registry.update("aaaa1111", spawned_marked)
        self.registry.update("aaaa1111", add_cwd)
        self.registry.update("bbbb2222", add_cwd)
        self.registry.update("bbbb2222", spawned_marked)
        self.assertEqual(self.path_of("aaaa1111").read_bytes(), self.path_of("bbbb2222").read_bytes())

    def test_modes_are_private_even_under_umask_zero(self):
        previous = os.umask(0)
        try:
            self.registry.update(KEY, spawned_marked)
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(self.sessions_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.path_of().stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.data / "sessions-v1.lock").stat().st_mode), 0o600)

    def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp_file(self):
        self.registry.update(KEY, spawned_marked)
        before = self.path_of().read_bytes()
        with mock.patch("jam.registry.os.replace", side_effect=OSError(errno.ENOSPC, "No space left on device", "/secret/x")):
            with self.assertRaises(RegistryError) as caught:
                self.registry.update(KEY, lambda raw: {**raw, "n": 1})
        self.assertNotIn("/secret/x", str(caught.exception))
        self.assertEqual(self.path_of().read_bytes(), before)
        self.assertEqual([p.name for p in self.sessions_dir.iterdir()], [f"{KEY}.json"])

    def test_a_failing_change_writes_nothing_and_releases_the_lock(self):
        with self.assertRaises(ValueError):
            self.registry.update(KEY, lambda raw: (_ for _ in ()).throw(ValueError("boom")))
        self.assertFalse(self.path_of().exists())
        self.registry.update(KEY, spawned_marked)
        self.assertTrue(self.registry.record(KEY).spawned)

    def test_an_unserializable_change_leaves_no_temp_file(self):
        self.registry.update(KEY, spawned_marked)
        with self.assertRaises(TypeError):
            self.registry.update(KEY, lambda raw: {"bad": object()})
        self.assertEqual([p.name for p in self.sessions_dir.iterdir()], [f"{KEY}.json"])

    def test_a_deleted_data_dir_is_recreated_by_the_next_update(self):
        self.registry.update(KEY, spawned_marked)
        shutil.rmtree(self.data)
        self.assertIsNone(self.registry.record(KEY))
        self.assertFalse(self.data.exists())
        self.registry.update(KEY, spawned_marked)
        self.assertTrue(self.registry.record(KEY).spawned)

    def test_error_messages_carry_no_paths(self):
        blocker = self.root / "blocker"
        blocker.write_text("not a directory")
        with self.assertRaises(RegistryError) as caught:
            Registry(blocker).update(KEY, spawned_marked)
        self.assertNotIn(str(blocker), str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)


class LockingTest(RegistryTestCase):
    def test_processes_do_not_lose_updates(self):
        src = str(Path(support.__file__).resolve().parent.parent / "src")
        children = [subprocess.Popen([sys.executable, "-I", "-c", CHILD, src, str(self.data)]) for _ in range(6)]
        self.assertEqual([child.wait(timeout=60) for child in children], [0] * 6)
        self.assertEqual(json.loads(self.path_of().read_text())["n"], 120)

    def test_threads_do_not_lose_updates(self):
        failures = []

        def work():
            registry = Registry(self.data, lock_timeout=5)
            try:
                for _ in range(25):
                    registry.update(KEY, lambda raw: {**raw, "n": raw.get("n", 0) + 1})
            except Exception as exc:  # noqa: BLE001  (collected, then asserted)
                failures.append(exc)

        threads = [threading.Thread(target=work) for _ in range(8)]
        [t.start() for t in threads]
        [t.join(timeout=60) for t in threads]
        self.assertEqual(failures, [])
        self.assertEqual(json.loads(self.path_of().read_text())["n"], 200)

    def test_lock_timeout_is_bounded_and_reads_stay_free(self):
        self.registry.update(KEY, spawned_marked)
        holder = os.open(self.data / "sessions-v1.lock", os.O_RDWR)
        fcntl.flock(holder, fcntl.LOCK_EX)
        try:
            started = time.monotonic()
            with self.assertRaises(RegistryError) as caught:
                Registry(self.data, lock_timeout=0.2).update("bbbb2222", spawned_marked)
            self.assertLess(time.monotonic() - started, 2)
            self.assertIn("busy", str(caught.exception))
            self.assertFalse(self.path_of("bbbb2222").exists())
            self.assertTrue(self.registry.record(KEY).spawned)
            self.registry.remove(KEY)
        finally:
            os.close(holder)
        Registry(self.data, lock_timeout=0.2).update("bbbb2222", spawned_marked)
        self.assertTrue(self.path_of("bbbb2222").exists())


class RemoveAndPruneTest(RegistryTestCase):
    def age(self, path, days):
        stamp = time.time() - days * 86400
        os.utime(path, (stamp, stamp))

    def test_remove_ignores_a_missing_record(self):
        self.registry.remove(KEY)
        self.registry.update(KEY, spawned_marked)
        self.registry.remove(KEY)
        self.assertFalse(self.path_of().exists())

    def test_prune_removes_only_stale_files(self):
        self.registry.update("aaaa1111", spawned_marked)
        self.registry.update("bbbb2222", spawned_marked)
        self.registry.update("cccc3333", spawned_marked)
        orphan = self.sessions_dir / ".x.abc.tmp"
        orphan.write_text("partial")
        unrelated = self.sessions_dir / "notes.txt"
        unrelated.write_text("keep")
        self.age(self.path_of("aaaa1111"), 31)
        self.age(orphan, 31)
        self.age(unrelated, 31)
        self.age(self.path_of("cccc3333"), -5)
        self.assertEqual(self.registry.prune(), 2)
        self.assertFalse(self.path_of("aaaa1111").exists())
        self.assertFalse(orphan.exists())
        self.assertTrue(self.path_of("bbbb2222").exists())
        self.assertTrue(self.path_of("cccc3333").exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue((self.data / "sessions-v1.lock").exists())

    def test_prune_honours_an_explicit_age_and_clock(self):
        self.registry.update(KEY, spawned_marked)
        self.assertEqual(self.registry.prune(max_age=10, now=time.time() + 5), 0)
        self.assertEqual(self.registry.prune(max_age=10, now=time.time() + 60), 1)


if __name__ == "__main__":
    unittest.main()
