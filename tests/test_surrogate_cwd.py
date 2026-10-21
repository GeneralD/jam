"""A session whose cwd holds an unpaired surrogate (a JSON "\\ud800" escape) has no file name form: nothing is written and nothing raises."""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy

claims = lazy("jam.claims")
tickets = lazy("jam.tickets")
claude_hooks = lazy("jam.harness.claude_hooks")

CWD = "/work/\ud800app"
SID = "aaaa1111-0000-4000-8000-000000000001"


class UnpairedSurrogateCwdTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = str(self.root / "data")

    def test_the_directory_key_is_none(self):
        self.assertIsNone(tickets.dir_key(CWD))

    def test_the_start_record_is_not_written_and_nothing_raises(self):
        self.assertFalse(claims.Claims(self.data).record_start(SID, CWD))
        self.assertFalse(os.path.exists(os.path.join(self.data, "guard-v1")))

    def test_a_ticket_path_with_a_lone_surrogate_is_not_marked(self):
        self.assertIsNone(claims.Claims(self.data).mark_worker(SID, "/x/\ud800"))
        self.assertFalse(os.path.exists(os.path.join(self.data, "guard-v1")))

    def test_the_adopt_hook_prints_nothing_writes_nothing_and_exits_zero(self):
        out, err = io.StringIO(), io.StringIO()
        payload = json.dumps({"session_id": SID, "cwd": CWD, "source": "startup"}).encode("ascii")
        code = claude_hooks.main(["adopt"], env={"CLAUDE_PLUGIN_DATA": self.data}, stdin=io.BytesIO(payload), stdout=out, stderr=err, arm=lambda seconds: None)
        self.assertEqual((code, out.getvalue(), err.getvalue()), (0, "", ""))
        self.assertFalse(os.path.exists(os.path.join(self.data, "guard-v1")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "pending-v1")))


if __name__ == "__main__":
    unittest.main()
