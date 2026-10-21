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

    def test_d14_states_the_unverified_points(self):
        d14 = flat(section(DECISIONS, "D14."))
        for phrase in ("inside a `--bg` worker", "after a resume", "`bypassPermissions`", "re-issues a denied edit"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, d14)

    def test_d14_status_and_the_shape_of_the_work_say_registration_waits_only_for_the_live_checks_now_that_the_marks_are_written(self):
        # The writers of the marks are in place (adopt and spawn), so the only thing left before registration is the live checks.
        d14 = section(DECISIONS, "D14.")
        places = {"status": flat(d14.split("\n- **Event and entry.**")[0]), "shape of the work": flat(d14.split("Shape of the work:")[1])}
        self.assertIn("Registering it waits only for the live checks", places["status"])
        self.assertIn("waits only for the live checks above", places["shape of the work"])
        for name, text in places.items():
            with self.subTest(place=name):
                self.assertNotIn("waits for both the", text)
                self.assertNotIn("until that change exists", text)

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

    def test_d14_says_the_start_directory_is_no_exclusion_and_a_nested_repository_is_foreign_wherever_the_session_started(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertNotIn("equal to or below the start directory", d14)
        self.assertIn("The start directory is not an exclusion", d14)
        self.assertIn("one nested below the start directory included (D14-6), is foreign", d14)
        self.assertIn("the `.git` walks of step 7 are paid by every edit that reaches it", d14)
        self.assertNotIn("so the costly ones happen only for an edit that would be denied.", d14)

    def test_d14_6_covers_every_repository_nested_below_the_start_directory_and_names_the_alternative_that_brings_the_shortcut_back(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("any repository nested below the start directory", d14)
        self.assertIn("would bring back a shortcut for the start directory", d14)

    def test_d14_says_the_targets_own_repository_decides_what_is_ignored_and_an_enclosing_one_does_not(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("git answers for the target's own repository, so an enclosing repository's ignore rules do not count", d14)
        self.assertIn("unless that repository's own ignore rules, or the user's global excludes, cover the path", d14)
        self.assertNotIn("started, unless git says the path is ignored.", d14)

    def test_d6_excludes_the_start_directorys_own_repository_and_not_the_start_directory(self):
        d6 = flat(section(DECISIONS, "D6."))
        self.assertIn("the start directory's own repository", d6)
        self.assertIn("a repository nested below the start directory is not, see D14-6", d6)
        self.assertNotIn("the start directory, non-git paths", d6)

    def test_d14_and_d11_say_a_link_in_place_of_the_state_directory_is_refused_and_the_gap_after_the_check_is_accepted(self):
        for title, directory in (("D14.", "`guard-v1`"), ("D11.", "`sessions-v1`")):
            text = flat(section(DECISIONS, title))
            with self.subTest(decision=title):
                self.assertIn(f"{directory} must be a real directory", text)
                self.assertEqual(text.count("time of check to time of use"), 1)
                self.assertIn("only the same user can plant a link in the user's own plugin data directory", text)
        self.assertIn("raise `RegistryError` rather than go through one", flat(section(DECISIONS, "D11.")))

    def test_the_source_comments_that_were_corrected_stay_corrected(self):
        sources = {
            "src/jam/harness/notice.py": (["the model itself named a prefix of"], []),
            "src/jam/harness/claude_hooks.py": (["before the platform's timeout in hooks/hooks.json"], ["which has no entry there yet"]),
            "src/jam/guard.py": (
                ["the target is not inside the start directory", "(reading `.git` entries, asking git, writing claims) are reached only by"],
                ["The exception is D14-2", "the target is not inside the configuration directory (D14-3)", "paid by every edit that gets that far"],
            ),
            "src/jam/claims.py": (["One lstat; written by other code."], ["is not a real directory"]),
        }
        for name, (gone, present) in sources.items():
            text = flat((ROOT / name).read_text(encoding="utf-8"))
            with self.subTest(source=name):
                self.assertTrue(all(phrase not in text for phrase in gone), gone)
                self.assertTrue(all(phrase in text for phrase in present), present)


class ReadmeTest(unittest.TestCase):
    def test_the_status_says_the_guard_core_exists_but_is_not_registered(self):
        status = flat(section(README, "Status"))
        self.assertIn("core of the delegation guard exists and is tested, but it is not registered", status)

    def test_the_status_says_registration_waits_only_for_live_checks_in_real_sessions(self):
        status = flat(section(README, "Status"))
        self.assertIn("registering it waits only for live checks in real sessions", status)
        self.assertNotIn("for the change that marks the sessions jam starts", status)

    def test_no_document_says_the_guard_does_not_exist(self):
        for name, text in (("README.md", README), ("docs/decisions.md", DECISIONS)):
            with self.subTest(document=name):
                self.assertNotRegex(flat(text).lower(), r"guard[^.]{0,80}do(es)? not exist")


if __name__ == "__main__":
    unittest.main()
