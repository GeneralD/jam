"""Checks that the documents describe the `peek` verb (#48) as it is, and that the sentences it replaced are gone.

Same style as test_close_docs.py: flattened text, one section at a time, and
both the new wording and the removed wording pinned.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from test_spawn_docs import DECISIONS, README, flat, section

ROOT = Path(__file__).resolve().parent.parent
SKILL = (ROOT / "skills" / "delegate" / "SKILL.md").read_text(encoding="utf-8")


class ReadmeTest(unittest.TestCase):
    def test_the_feature_list_says_what_peek_shows_and_what_it_keeps_back(self):
        self.assertIn(
            "**Peek** at a session's last turns without interrupting it: what it was asked, what it answered and which "
            "tools it used, never what those tools took or returned (D20).",
            flat(section(README, "What it does")),
        )

    def test_the_old_verb_lists_are_gone(self):
        for removed in ("verbs: spawn / list / stop / close / whoami", "`spawn`, `list`, `stop`, `close`, and `whoami`"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, flat(README))


class DecisionsTest(unittest.TestCase):
    def setUp(self):
        self.d20 = flat(section(DECISIONS, "D20. Peeking at a session's last turns"))

    def test_d20_records_the_decision_the_boundary_and_the_bounds(self):
        for phrase in (
            "Decided on 2026-11-09, from issue #48.",
            "`claude logs` prints what the session's terminal showed, not its turns",
            "the transcript is the one record of them, and nothing native reads it turn by turn",
            "jam only reads it, and only the part it needs",
            "What tools took and returned, and what the session thought, never leave the adapter",
            "A turn starts with a prompt the session was given",
            "at most 20 turns, 3 when the caller names no number",
            "A prompt is cut to its first 2000 characters and a reply to its last 4000, the cut marked with \"...\" within that length",
            "a turn keeps at most 30 tool names of at most 128 characters each",
            "A call returns at most 20000 characters in all, tool names and times included",
            "Every bound, the number of turns included, is applied in the core (`turn_bounds`)",
            "is written as an attachment of type `queued_command`, not as a prompt; it starts a turn too",
            "is known by its wrapper, \"Another Claude session sent\", and keeps that wrapper",
            "The last 16 MiB of the file are read",
            "found by its file name under `projects` of the configuration directory",
            "**Short id only.**",
            "The Devin adapter refuses `peek`",
            "A peer's turns are input to weigh, not orders (D10)",
            "`peek` is not the `result` verb D4 left out",
            "**Verified (2026-11-10, Claude Code 2.1.309).**",
            "**Not checked.**",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.d20)

    def test_d20_says_what_a_turns_time_is_and_how_a_harness_note_without_an_origin_is_known(self):
        for phrase in (
            "and the time of the latest message in it, a tool's result included.",
            "A record without an `origin` is the harness's own only when it opens with one of the tags the harness "
            "writes there (seen from 2.1.159 to 2.1.309) or with an interrupt marker; any other text is a prompt, even "
            "one that opens with a tag.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.d20)
        self.assertNotIn("the time of its last record", self.d20)

    def test_d4_and_d12_name_the_verb(self):
        text = flat(DECISIONS)
        for removed in (
            "the verbs `spawn`, `list`, `stop`, `close`, and `whoami`",
            "`spawn`, `list`, `stop`, `close`, and `whoami` are rows",
            "and `stop`, `close` and `whoami` never touch the registry",
            "`__list`, `__stop`, `__close`, and `__whoami`",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, text)


class DevinTest(unittest.TestCase):
    def test_every_place_that_describes_the_devin_harness_says_peek_is_refused(self):
        self.assertIn("`peek` refuses: `devin -r` resumes a session, so it is no read-only view (D20).", flat(README))
        self.assertIn("**peek** → refused before anything runs (D20)", flat(section(DECISIONS, "D16. The Devin CLI harness")))


class SkillTest(unittest.TestCase):
    def test_the_skill_names_the_tool_and_when_to_use_it(self):
        text = flat(SKILL)
        self.assertIn("(`mcp__plugin_jam_jam__spawn`, `__list`, `__peek`, `__stop`, `__close`, `__whoami`)", text)
        self.assertIn("`peek` shows where a session got to without interrupting it (not on Devin).", text)
        self.assertIn("Do not poll `list`, `ListAgents` or `peek`", text)


class ManifestTest(unittest.TestCase):
    def test_the_version_is_bumped_for_the_new_verb(self):
        self.assertEqual(json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"], "0.3.0")


if __name__ == "__main__":
    unittest.main()
