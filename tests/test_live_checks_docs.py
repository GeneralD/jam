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


class ResumeAndSummaryTest(unittest.TestCase):
    def test_the_docs_tie_keeping_the_mark_to_a_resume_that_keeps_the_id(self):
        decisions = flat(DECISIONS)
        self.assertIn("so a resume that keeps the id keeps it, while `/clear` and a fork get a new id", decisions)
        self.assertIn("a resumed one can return with the same id", decisions)
        for removed in ("so a resume keeps it,", "The session id keeps the mark across a resume", "a resumed one returns with the same id"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, decisions)

    def test_d6_names_the_fresh_start_and_the_ticket_module_leaves_the_skip_to_the_adapter(self):
        d6 = flat(section(DECISIONS, "D6."))
        self.assertIn("the first fresh start in that directory (D13) takes the ticket as the mark", d6)
        self.assertNotIn("the first session start in that directory takes the ticket", d6)
        module = flat((ROOT / "src" / "jam" / "tickets.py").read_text(encoding="utf-8"))
        self.assertIn("which starts continue or copy a session already started and so take no ticket", module)
        self.assertNotIn("continue a session already marked", module)


class LiveChecksTest(unittest.TestCase):
    def test_d14_records_the_checks_as_verified_with_the_date_and_the_version(self):
        d14 = flat(section(DECISIONS, "D14."))
        verified = d14.split("**Verified in real sessions (2026-10-21, Claude Code 2.1.300).**")[1].split("- **Rejected.**")[0]
        for phrase in (
            "PreToolUse fires inside a `--bg` worker",
            "`CLAUDE_PROJECT_DIR` is the spawn directory",
            "both stay the same after `EnterWorktree`",
            "a resume that keeps the id was not seen",
            "A JSON denial holds under `bypassPermissions`",
            "a Haiku worker whose prompt asked it to decide what to do after a refusal re-issued the denied edit",
            "Whether other models and prompts do the same is not known",
            "`PreToolUse:Write hook error: <reason>`",
            "reported `source: startup`",
            "`guard-v1/worker.<id>` existed afterwards with the ticket gone",
            "The probe ran `claude --bg` itself instead of going through `spawn`",
            "the skip of `resume` and `fork`, added to the `RESUMED` tuple of `src/jam/harness/claude_hooks.py` after the probe, is covered by unit tests only",
            "In both runs that were denied, the original session and the copy its resume started,",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, verified)
        self.assertNotIn("**Unverified, and to be checked", d14)
        self.assertNotIn("Still to be observed on a real `--bg`", d14)
        self.assertNotIn("after `EnterWorktree` and after a resume", d14)
        self.assertNotIn("The model re-issues a denied edit", d14)

    def test_d14_status_and_the_shape_of_the_work_say_registration_waited_only_for_d14_8(self):
        d14 = section(DECISIONS, "D14.")
        status = flat(d14.split("\n- **Event and entry.**")[0])
        shape = flat(d14.split("Shape of the work:")[1])
        self.assertIn("the live checks it waited for ran on 2026-10-21", status)
        self.assertIn("Two points stay open: the skip of `resume` and `fork`, which only unit tests cover, and a resume that keeps the session id", status)
        self.assertIn("If `CLAUDE_PROJECT_DIR` or `CLAUDE_CONFIG_DIR` differs on a resume that keeps the id", status)
        self.assertIn("So registration did not wait for either", status)
        self.assertNotIn("So registration does not wait for either", status)
        self.assertNotIn("Registering it waits only for the owner's approval", status)
        self.assertIn("and the live checks above ran, leaving open two points whose cost is bounded (see the status above), so the change that registered the hook waited only for D14-8", shape)
        for removed in ('waits only for the live checks under "Unverified"', "is expected to carry its mark", "the live checks it waited for passed", "One point stays open"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, status)
        self.assertNotIn("Until a live worker has shown its mark", shape)

    def test_d13_records_the_first_session_start_as_observed(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("Observed later (2026-10-21, Claude Code 2.1.300, see D14)", d13)
        self.assertIn("the one run with a ticket measured 0.9 seconds", d13)
        self.assertNotIn("are unobserved, so no live worker has shown its mark yet", d13)
        self.assertNotIn("no run has measured it", d13)
        self.assertIn("- **Partly verified.** No session was started to test this change itself.", section(DECISIONS, "D13."))
        self.assertIn("which only unit tests cover", d13)
        self.assertNotIn("the timings are still open (also listed", d13)

    def test_the_readme_status_says_the_checks_ran_and_what_registration_waited_for(self):
        status = flat(section(README, "Status"))
        self.assertIn("the live checks it waited for ran in real background sessions on 2026-10-21", status)
        self.assertIn("it was registered once the owner approved the text the model reads (D14-8)", status)
        self.assertNotIn("registering it waits only for live checks in real sessions", status)
        self.assertNotIn("among them whether a real background worker takes its mark", status)


class PlatformFactsTest(unittest.TestCase):
    def test_the_platform_facts_record_what_the_live_checks_found(self):
        facts = flat(section(DECISIONS, "Plugin platform facts"))
        for phrase in (
            "**The background isolation guard (observed once on 2.1.300, 2026-10-21).**",
            "that order is inferred, not observed",
            "This background session hasn't isolated its changes yet.",
            '`"worktree": {"bgIsolation": "none"}`',
            "which jam's guard counts as the start repository",
            "`claude rm` refused to remove the session",
            "**Resuming a background session (observed on 2.1.300).**",
            "so this started a copy as <new id>",
            "reported `source: fork` with a new session id",
            "`<config>/plugins/data/jam-probe-inline`, where `<config>` is the configuration directory",
            "so `<name>-inline` is expected for any name",
            "Once, a row came back without `id`",
            "In the one case tried (2026-10-21), a git repository created inside a trusted project was refused",
            "whether trust is inherited at all is still unverified",
            "run right after `claude stop <id>` had printed `stopped <id>`",
            "it was started from the same directory, so this does not tell whether they are inherited",
            "as the way to turn it off; that setting was not tried",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, facts)
        for removed in ("whose state was `stopped`", "`.claude/settings.json` turns it off", "so whatever is inherited does not reach a nested repository", "kept the `cwd`"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, facts)

    def test_the_open_items_drop_the_d14_points_and_keep_a_resume_that_keeps_its_id(self):
        items = flat(section(DECISIONS, "Open verification items"))
        self.assertNotIn("The unverified points of D14", items)
        self.assertNotIn("the worker's first session start and the mark it leaves", items)
        self.assertIn("A resume of a background session that keeps its id", items)
        self.assertIn("Do `CLAUDE_PROJECT_DIR` and `CLAUDE_CONFIG_DIR` keep their values there?", items)


if __name__ == "__main__":
    unittest.main()
