"""Checks that the documents record the live checks of 2026-10-21 and the source rule they led to, and that the sentences they replaced are gone.

Same style as test_spawn_docs.py: flattened text, one section at a time, and
both the new wording and the removed wording pinned.
"""

from __future__ import annotations

import unittest

from test_spawn_docs import DECISIONS, README, ROOT, flat, section

HOOKS = (ROOT / "src" / "jam" / "harness" / "claude_hooks.py").read_text(encoding="utf-8")


class SourceRuleTest(unittest.TestCase):
    def test_d13_adopt_takes_the_ticket_only_at_a_fresh_start(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("At a fresh start (any source other than `resume`, `clear`, `compact` and `fork`, so an unknown one counts) it also takes the freshest spawn ticket", d13)
        self.assertNotIn("For a source other than `clear` or `compact`", d13)

    def test_d14_loop_protection_names_the_four_sources_that_skip_the_ticket(self):
        d14 = flat(section(DECISIONS, "D14."))
        for phrase in (
            "Only a fresh start takes the ticket: `resume`, `clear`, `compact` and `fork` skip it (D13), and an unknown source takes it",
            "A live `--bg` worker's first start reported `startup`, so the skip costs a worker nothing",
            "`/clear` and a fork get a new id and so start without one",
            "(a fresh start in that directory within 300 seconds of the spawn)",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, d14)
        for removed in (
            "Only `clear` and `compact` skip the ticket",
            "A resume takes it like a startup does",
            "first start source is unobserved",
            "other than `clear` and `compact`",
            "any value other than `clear` or `compact` claims the mark",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, d14)

    def test_the_hook_module_docstring_names_the_four_sources(self):
        text = flat(HOOKS)
        self.assertIn("(`resume`, `clear`, `compact` or `fork`)", text)
        self.assertNotIn("(`clear` or `compact`)", text)


class LiveChecksTest(unittest.TestCase):
    def test_d14_records_the_checks_as_verified_with_the_date_and_the_version(self):
        d14 = flat(section(DECISIONS, "D14."))
        verified = d14.split("**Verified in real sessions (2026-10-21, Claude Code 2.1.300).**")[1].split("- **Rejected.**")[0]
        for phrase in (
            "PreToolUse fires inside a `--bg` worker",
            "`CLAUDE_PROJECT_DIR` is the spawn directory",
            "after `EnterWorktree` and after a resume",
            "A JSON denial holds under `bypassPermissions`",
            "The model re-issues a denied edit",
            "`PreToolUse:Write hook error: <reason>`",
            "reported `source: startup`",
            "`guard-v1/worker.<id>` existed afterwards with the ticket gone",
            "The probe ran `claude --bg` itself instead of going through `spawn`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, verified)
        self.assertNotIn("**Unverified, and to be checked", d14)
        self.assertNotIn("Still to be observed on a real `--bg`", d14)

    def test_d14_status_and_the_shape_of_the_work_say_registration_waits_only_for_d14_8(self):
        d14 = section(DECISIONS, "D14.")
        status = flat(d14.split("\n- **Event and entry.**")[0])
        shape = flat(d14.split("Shape of the work:")[1])
        self.assertIn("the live checks it waited for passed on 2026-10-21", status)
        self.assertIn("Registering it waits only for the owner's approval of the text the model reads (D14-8)", status)
        self.assertIn("and the live checks above passed, so the change that registers the hook waits only for D14-8", shape)
        for removed in ('waits only for the live checks under "Unverified"', "is expected to carry its mark"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, status)
        self.assertNotIn("Until a live worker has shown its mark", shape)

    def test_d13_records_the_first_session_start_as_observed(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("Observed later (2026-10-21, Claude Code 2.1.300, see D14)", d13)
        self.assertIn("the one run with a ticket measured 0.9 seconds", d13)
        self.assertNotIn("are unobserved, so no live worker has shown its mark yet", d13)
        self.assertNotIn("no run has measured it", d13)

    def test_the_readme_status_says_the_checks_passed_and_what_registration_waits_for(self):
        status = flat(section(README, "Status"))
        self.assertIn("the live checks it waited for passed in real background sessions on 2026-10-21", status)
        self.assertIn("registering it waits only for approval of the text the model reads (D14-8)", status)
        self.assertNotIn("registering it waits only for live checks in real sessions", status)
        self.assertNotIn("among them whether a real background worker takes its mark", status)


class PlatformFactsTest(unittest.TestCase):
    def test_the_platform_facts_record_what_the_live_checks_found(self):
        facts = flat(section(DECISIONS, "Plugin platform facts"))
        for phrase in (
            "**The background isolation guard (observed on 2.1.300, 2026-10-21).**",
            "This background session hasn't isolated its changes yet.",
            '`"worktree": {"bgIsolation": "none"}`',
            "which jam's guard counts as the start repository",
            "`claude rm` refuses to remove the session",
            "**Resuming a background session (observed on 2.1.300).**",
            "so this started a copy as <new id>",
            "reported `source: fork` with a new session id",
            "`<config>/plugins/data/<name>-inline`, where `<config>` is the configuration directory",
            "Once, a row came back without `id`",
            "A git repository created inside a trusted project was refused",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, facts)

    def test_the_open_items_drop_the_d14_points_and_keep_a_resume_that_keeps_its_id(self):
        items = flat(section(DECISIONS, "Open verification items"))
        self.assertNotIn("The unverified points of D14", items)
        self.assertNotIn("the worker's first session start and the mark it leaves", items)
        self.assertIn("A resume of a background session that keeps its id", items)


if __name__ == "__main__":
    unittest.main()
