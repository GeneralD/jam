"""Checks that the documents say the skill ships, how to install the plugin, and what the skill relies on.

Same style as test_spawn_docs.py: flattened text, one section at a time, and
both the new wording and the removed wording pinned.
"""

from __future__ import annotations

import unittest

from test_spawn_docs import DECISIONS, README, flat, section


class ReadmeTest(unittest.TestCase):
    def test_the_status_says_the_skill_ships(self):
        status = flat(section(README, "Status"))
        self.assertIn("The `delegate` skill (`/jam:delegate`) teaches the model when to delegate, how to brief a worker", status)
        self.assertNotIn("The skill does not exist yet", status)
        self.assertNotIn("is planned, not shipped", status)

    def test_the_reason_to_delegate_does_not_claim_an_outside_edit_misses_every_convention(self):
        why = flat(section(README, "Why delegate instead of editing directly"))
        self.assertIn("an edit made from another repository follows that session's setup, which may not include them", why)
        self.assertNotIn("never sees them", why)

    def test_the_install_section_gives_the_one_step_line_and_the_older_two_step_form(self):
        install = flat(section(README, "Install"))
        for phrase in ("2.1.275 or later", "/plugin install jam --marketplace GeneralD/jam", "/plugin marketplace add GeneralD/jam", "/plugin install jam@jam"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, install)

    def test_the_install_section_comes_after_the_requirements(self):
        self.assertLess(README.index("\n## Requirements\n"), README.index("\n## Install\n"))
        self.assertLess(README.index("\n## Install\n"), README.index("\n## Status\n"))


class DecisionsTest(unittest.TestCase):
    def test_d4_says_how_the_skill_addresses_a_session(self):
        d4 = flat(section(DECISIONS, "D4."))
        self.assertIn(
            "the skill (D15) teaches the AI to use the native `SendMessage`, addressing a session by the name `ListAgents` prints",
            d4,
        )
        self.assertNotIn("with the ids jam reports", d4)

    def test_d12_no_longer_defers_the_skill(self):
        d12 = flat(section(DECISIONS, "D12."))
        self.assertNotIn("The skill, self-stop refusal", d12)
        self.assertIn("and the skill is D15", d12)

    def test_d15_records_the_skill_what_it_relies_on_and_the_owner_question(self):
        d15 = flat(section(DECISIONS, "D15."))
        for phrase in (
            "`skills/delegate/SKILL.md` (`/jam:delegate`)",
            "the bounds that D14 leaves to the skill",
            "the first line of `ListAgents` names the calling session as others address it",
            "These come from the tool descriptions of Claude Code 2.1.300 and from one listing seen on 2026-10-22, not from a documentation page",
            "D15-1",
            "listed the skill as `jam:delegate` among its skills and slash commands",
            "It repeats a rule of the tool descriptions only where its guidance builds on it",
            "a change to one of those descriptions may call for the same change here",
            "so the skill spawns and waits only from the main conversation",
            "Answered on 2026-10-23: D15-1",
            "D15-2, yes: the deny reason now says to call `spawn` from the main conversation",
            "the description under 400 characters",
            "the body under 100 lines",
            "A call with `notify_when_idle: true` and an empty `message` was refused as an invalid parameter on 2.1.309 (2026-10-28)",
            "while the same call with a one-line message subscribed, so the skill asks for one line and says that the session receives it",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, d15)
        for phrase in (
            "It does not repeat the tool descriptions",
            "what the tool descriptions and the notice leave out",
            "It repeats only the rules of the tool descriptions",
            "names `spawn` without saying where to call it",
            "only the skill carries the rule",
            "the body under 200 lines",
        ):
            with self.subTest(removed=phrase):
                self.assertNotIn(phrase, d15)

    def test_d14_points_the_bounds_it_leaves_open_to_d15(self):
        self.assertIn("those belong to the skill (D15) and to `SendMessage`", flat(section(DECISIONS, "D14.")))

    def test_d14_records_the_sentence_that_d15_2_added_to_the_deny_reason(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("and the sentence that says to call `spawn` from the main conversation is the one D15-2 added", d14)
        self.assertIn("the rest of the reason was unchanged until D15-2 added one sentence on 2026-10-23", d14)
        self.assertNotIn("the rest of the reason is unchanged", d14)

    def test_d14_4_says_where_a_denied_subagent_goes_next(self):
        self.assertIn("what a denied subagent does next is in D15", flat(section(DECISIONS, "D14.")))

    def test_the_why_of_d6_does_not_claim_an_outside_edit_misses_every_convention(self):
        d6 = flat(section(DECISIONS, "D6."))
        self.assertIn("An edit made from outside follows the setup of the session that makes it, which may not include them.", d6)
        self.assertNotIn("never sees them", d6)

    def test_the_platform_facts_record_how_a_plugin_skill_loads(self):
        facts = flat(section(DECISIONS, "Plugin platform facts"))
        for phrase in (
            "**Skills.** A plugin skill lives at `skills/<name>/SKILL.md` and loads as `/<plugin>:<name>`, "
            "where `<name>` is the frontmatter `name` when it sets one and the directory name otherwise.",
            "The skill listing always holds every skill's name",
            "capped together at 1,536 characters by default (`skillListingMaxDescChars` changes the cap)",
            "the skills invoked least lose theirs first",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, facts)
        self.assertNotIn("truncated together at 1,536 characters", facts)


if __name__ == "__main__":
    unittest.main()
