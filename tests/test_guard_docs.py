"""Checks that the documents say what the guard really is: proposed, not registered, and pointed to from the decision it refines."""

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


class DecisionsTest(unittest.TestCase):
    def test_d14_is_accepted_and_still_says_the_guard_is_not_registered(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("Status: **Accepted** on 2026-10-20", d14)
        self.assertNotIn("Proposed", d14)
        self.assertIn("**not registered**", d14)

    def test_d14_lists_every_owner_question_with_its_number(self):
        d14 = section(DECISIONS, "D14.")
        for number in range(1, 9):
            with self.subTest(question=number):
                self.assertIn(f"D14-{number}", d14)

    def test_d14_records_which_questions_the_owner_answered_and_which_hold_their_defaults(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("The owner accepted D14-1, D14-2 and D14-3 as proposed and authorised the live checks", d14)
        self.assertIn("hold their defaults until the owner revises them", d14)

    def test_d14_states_the_four_unverified_points(self):
        d14 = flat(section(DECISIONS, "D14."))
        for phrase in ("inside a `--bg` worker", "after a resume", "`bypassPermissions`", "re-issues a denied edit"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, d14)

    def test_d6_hands_loop_protection_to_d14_instead_of_calling_it_undecided(self):
        d6 = flat(section(DECISIONS, "D6."))
        self.assertIn("D14 (accepted on 2026-10-20) settles the mechanism", d6)
        self.assertNotIn("still to be designed", d6)
        self.assertNotIn("Prefer the marker in the prompt", d6)


class StatementsTest(unittest.TestCase):
    """Sentences that were once wrong about what the code does, kept from coming back."""

    def test_d13_says_the_launcher_enters_the_hook_adapter_directly(self):
        # D13 once said only the composition root imports the harness, while scripts/jam has entered claude_hooks since the hooks shipped.
        d13 = flat(section(DECISIONS, "D13."))
        self.assertIn("the launcher `scripts/jam` enters `jam.harness.claude_hooks` directly", d13)

    def test_d14_asks_no_approval_for_a_deviation_from_d13(self):
        d14 = flat(section(DECISIONS, "D14."))
        for phrase in ("recorded in D13", "D13's deviation", "contradicts it", "D13 does not record"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, d14)

    def test_d14_says_the_git_call_gets_only_the_absolute_path_entries(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("`PATH` reduced to its absolute entries", d14)
        self.assertIn("or the platform's default search path when none is left", d14)

    def test_d14_does_not_say_the_named_root_adds_no_foreign_text(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertNotIn("adds no foreign text", d14)
        self.assertIn("is a real path", d14)
        self.assertIn("the length bound and the character filter", d14)

    def test_d14_keeps_a_hook_timeout_out_of_the_cases_the_wrapper_turns_into_exit_zero(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertNotIn("the platform timeout, a missing", d14)
        self.assertIn("A hook timeout does not", d14)

    def test_d14_says_the_foreign_git_call_finds_git_only_through_absolute_path_entries(self):
        self.assertIn("only through the absolute entries of `PATH`", flat(section(DECISIONS, "D14.")))

    def test_d14_says_the_throttle_is_two_clauses_and_not_one(self):
        self.assertIn("D14-2 is the exception", flat(section(DECISIONS, "D14.")))

    def test_d13_counts_the_sweep_of_the_guards_state_in_the_cost_of_a_synchronous_prune(self):
        self.assertIn("plus the sweep of the guard's state", flat(section(DECISIONS, "D13.")))

    def test_the_source_comments_that_were_corrected_stay_corrected(self):
        sources = {
            "src/jam/harness/notice.py": ("the model itself named a prefix of", None),
            "src/jam/harness/claude_hooks.py": ("before the platform's timeout in hooks/hooks.json", "which has no entry there yet"),
            "src/jam/guard.py": (None, "The exception is D14-2"),
        }
        for name, (gone, present) in sources.items():
            text = flat((ROOT / name).read_text(encoding="utf-8"))
            with self.subTest(source=name):
                self.assertTrue(gone is None or gone not in text)
                self.assertTrue(present is None or present in text)


class ReadmeTest(unittest.TestCase):
    def test_the_status_says_the_guard_core_exists_but_is_not_registered(self):
        status = flat(section(README, "Status"))
        self.assertIn("core of the delegation guard exists and is tested, but it is not registered", status)

    def test_no_document_says_the_guard_does_not_exist(self):
        for name, text in (("README.md", README), ("docs/decisions.md", DECISIONS)):
            with self.subTest(document=name):
                self.assertNotRegex(flat(text).lower(), r"guard[^.]{0,80}do(es)? not exist")


if __name__ == "__main__":
    unittest.main()
