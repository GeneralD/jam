"""Checks that the documents say what the spawn tickets, the start record, the worker mark and the `adopt` hook really do, and that the sentences they replaced are gone.

Same style as test_mcp_docs.py and test_guard_docs.py: flattened text, one
section at a time, and both the new wording and the removed wording pinned.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def section(text, title):
    """The body of the `## <title>` section that starts with `title`."""
    (body,) = [part for part in re.split(r"^## ", text, flags=re.MULTILINE) if part.startswith(title)]
    return body


def flat(text):
    return " ".join(text.split())


class ReadmeTest(unittest.TestCase):
    def test_the_design_names_three_session_start_hooks_and_a_fourth_handler_that_is_not_registered(self):
        design = flat(section(README, "What it does") + section(README, "Design"))
        self.assertIn("Three SessionStart hooks run through the same launcher", design)
        self.assertIn("one records where the session started and, at a fresh start, when `spawn` left a ticket for that directory in the last 300 seconds, turns the ticket into the session's worker mark (D14)", design)
        self.assertNotIn("one marks the sessions jam starts", design)
        self.assertIn("A fourth handler, the delegation guard, is implemented and tested but not registered", design)
        self.assertNotIn("Two SessionStart hooks", design)
        self.assertNotIn("A third hook, the delegation guard", design)

    def test_the_status_counts_three_hooks_and_drops_the_wait_for_the_mark(self):
        status = flat(section(README, "Status"))
        self.assertIn("plus three SessionStart hooks", status)
        self.assertIn("`hooks/hooks.json` declares only the three SessionStart hooks, so no session is affected", status)
        self.assertIn("the step that records the start directory and, at a fresh start, turns a spawn ticket from the last 300 seconds into a worker mark", status)
        for removed in ("plus two SessionStart hooks", "declares only the two SessionStart hooks", "for the change that marks the sessions jam starts", "the step that marks the sessions jam starts"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, status)


class DecisionsTest(unittest.TestCase):
    def test_d13_ships_three_hooks_and_adopt_has_the_failure_contract_of_a_session_start_hook(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("Three hooks ship, all on SessionStart", d13)
        self.assertIn("**`adopt`**", d13)
        self.assertIn("prints nothing and always exits 0", d13)
        self.assertIn("bounded work: one create, one capped listing, at most 8 moves", d13)
        self.assertIn("a lost mark costs at most one extra deny per repository once the guard is registered", d13)
        self.assertNotIn("Two hooks ship", d13)

    def test_d13_keeps_the_guard_handler_out_of_the_registered_hooks_and_counts_it_as_the_fourth(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("A fourth handler, `guard` (PreToolUse)", d13)
        self.assertNotIn("A third handler", d13)

    def test_d13_timeouts_and_alarms_name_adopt(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("5 seconds for `notice` and `adopt`, and 3 for `prune`", d13)
        self.assertIn("an alarm (3 seconds for `notice` and `adopt`, 2 for `prune`)", d13)

    def test_d13_says_only_adopt_reads_source_and_the_sweep_cost_counts_the_tickets(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("only `adopt` reads `source`", d13)
        self.assertNotIn("no handler branches on `source`", d13)
        self.assertIn("plus the sweep of the guard's state and of the spawn tickets", d13)
        self.assertNotIn("plus the sweep of the guard's state (D14): a second scan", d13)

    def test_d13_prune_sweeps_the_ticket_directory_and_the_marks_as_well_as_the_guard_state(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("sweeps the guard's state directory `guard-v1` (D14) and the spawn ticket directory `pending-v1` (D14)", d13)
        self.assertIn("start records and worker marks", d13)

    def test_d14_status_no_longer_waits_for_the_marks(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertNotIn("waits for both the live checks", d14)
        self.assertNotIn("until that change exists", d14)

    def test_d14_state_table_names_adopt_as_the_writer_of_the_start_record_and_the_mark(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("| `start.<id>` | the session's start directory and a line feed | `adopt`, once | step 5, as the fallback |", d14)
        self.assertIn("| `worker.<id>` | empty | `adopt`, by moving a spawn ticket | step 3 |", d14)

    def test_d14_describes_the_ticket_directory_and_its_names(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("`pending-v1/<dir16>.<nonce16>`", d14)
        self.assertIn("empty, written by `spawn` before the harness runs", d14)

    def test_d14_no_longer_says_the_core_ships_only_the_readers(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertNotIn("The core ships only the readers", d14)
        self.assertIn("`prune` also removes", d14)

    def test_d14_owner_questions_9_and_10_record_the_answered_check_and_the_marks_in_place(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("The `--session-id` check was answered on 2026-10-21", d14)
        self.assertIn("The writers of the spawn tickets and the `worker.<id>` marks are in place (D13, `adopt`)", d14)
        self.assertNotIn("waits for both the checks above and the change that writes the spawn tickets", d14)

    def test_d14_core_and_adapter_names_the_ticket_module_as_core(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("the spawn tickets (`jam.tickets`)", d14)

    def test_d13_puts_the_cap_and_the_deadline_on_the_two_guard_sweeps_and_says_the_note_sweep_has_neither(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("Only the two guard sweeps, of the guard's state and of the spawn tickets, have a cap on the entries they look at", d13)
        self.assertIn("The note sweep of the registry (D11) has neither", d13)
        self.assertIn("only the alarm bounds it", d13)
        self.assertNotIn("Each sweep has a cap on the entries it looks at", d13)
        self.assertNotIn("so the cost stays bounded", d13)

    def test_d13_adopt_and_its_unverified_part_state_the_300_second_window(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("A ticket counts only when it was written at most 300 seconds before the start", d13)
        self.assertIn("a ticket dated in the future counts as fresh", d13)
        self.assertIn("a worker whose first session start comes later gets no mark", d13)
        self.assertIn("The delay between the spawn and that first session start must also stay within 300 seconds", d13)

    def test_d14_status_says_a_worker_carried_its_mark_within_the_window(self):
        status = flat(section(DECISIONS, "D14.").split("\n- **Event and entry.**")[0])
        self.assertIn("a worker started after a spawn ticket carried its mark from its first session start", status)
        self.assertIn("which came well within the 300 seconds of D13", status)
        self.assertNotIn("so a worker jam starts carries its mark", status)

    def test_d14_loop_protection_says_when_the_mark_stops_exempting_and_who_takes_a_ticket(self):
        d14 = flat(section(DECISIONS, "D14."))
        for phrase in (
            "is not denied while the mark exists",
            "The mark is a bare file created by moving a ticket",
            "at the first fresh start in that directory (D13) within 300 seconds",
            "it records that the session took the ticket, not that jam started it",
            "a resume that keeps the id keeps the mark",
            "The mark stays until the sweep removes it, 30 days after the spawn",
            "A session that takes a ticket it did not spawn",
            "is not denied in any repository while its mark exists",
            "it misses one nudge per repository it edits in",
            "A worker gets at most one extra denial per repository when another session took its ticket",
            "when its first session start comes more than 300 seconds after the spawn",
            "a recognised worker is not denied while its mark exists",
            "The mark is a flag that records the ticket was taken, fixed at creation.",
            "a session that took a spawn ticket written by `spawn` is not denied",
            "The exemption lasts while the mark exists; the 30-day sweep ends it",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, d14)
        for removed in (
            "a stolen ticket costs one",
            "costs one missed nudge",
            "Every wrong assumption is benign",
            "a session started through `spawn` is never denied",
            "A session with a `worker.<id>` mark is never denied",
            "a recognised worker is never denied",
            "So the worker a jam starts carries its mark",
            "a provenance flag",
            "at the first session start in that directory within 300 seconds",
            "the worker's first SessionStart turns it into a mark",
            "in their own directories",
            "however the directory is named",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, d14)

    def test_d14_state_paragraph_names_the_directories_and_the_thirty_day_age_of_the_mark(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("removes start records and worker marks from `guard-v1` and spawn tickets from `pending-v1`, each file older than 30 days", d14)
        self.assertIn("A worker mark's age is its file time, which the move keeps from the spawn ticket", d14)
        self.assertIn("so a spawn and the worker's start agree on it when both spell the directory the same way after realpath", d14)
        self.assertIn("on a case-insensitive file system another spelling costs a lost mark", d14)

    def test_d6_says_the_mark_exempts_only_while_it_exists(self):
        d6 = flat(section(DECISIONS, "D6."))
        self.assertIn("a marked session is not denied while its mark exists (30 days from the spawn, see D14)", d6)
        self.assertNotIn("a marked session is never denied", d6)
        self.assertNotIn("the worker's first SessionStart turns it into a mark", d6)

    def test_the_platform_facts_record_the_session_id_under_bg_as_verified_with_its_sample_marked(self):
        facts = flat(section(DECISIONS, "Plugin platform facts"))
        self.assertIn("**`--session-id` under `--bg` (verified by experiment, 2026-10-21, Claude Code 2.1.300).**", facts)
        self.assertIn("warning: --bg manages the session id; ignoring --session-id", facts)
        self.assertIn("one observation and is not relied on", facts)
        self.assertNotIn("The id is the first 8 characters of `sessionId`.", facts)

    def test_the_open_verification_items_no_longer_ask_about_the_session_id(self):
        items = flat(section(DECISIONS, "Open verification items"))
        self.assertNotIn("Does `claude --bg --session-id <uuid>` keep the id it is given", items)
        self.assertNotIn("It needs a real spawn in a trusted directory to find out.", items)


if __name__ == "__main__":
    unittest.main()
