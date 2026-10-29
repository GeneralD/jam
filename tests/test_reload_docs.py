"""Checks that the documents say what `/reload-plugins` did and did not give a running session (#24), within the one observation behind it, and that the sentences they replaced are gone.

Same style as test_live_checks_docs.py: flattened text, one section at a time, and
both the new wording and the removed wording pinned. The wording is scoped to what
was seen (one background session, Claude Code 2.1.309, 2026-10-28), so the hedges
are pinned too, and the unchecked points are listed where the claim is.
"""

from __future__ import annotations

import re
import unittest

from test_spawn_docs import DECISIONS, README, flat, section

README_MARKER = "Nothing else is set up by hand: no PATH change and no settings edit (D5)."
FACT_MARKER = "**`/reload-plugins` in a running session (observed once on 2.1.309, 2026-10-28).**"
# A tripwire for the commonest widening words only; it cannot see a sentence that widens without them.
OVERREACH = re.compile(r"\b(always|never|every|all|any|whenever)\b", re.IGNORECASE)


def fact():
    """The platform-facts bullet that carries the evidence, up to the next bullet."""
    return flat(section(DECISIONS, "Plugin platform facts")).split(FACT_MARKER)[1].split(" - **")[0]


class ReadmeInstallTest(unittest.TestCase):
    def test_the_install_section_says_what_a_reload_gave_one_running_session(self):
        paragraph = flat(section(README, "Install")).split(README_MARKER)[1]
        for phrase in (
            "In one background session on Claude Code 2.1.309 (2026-10-28) that was already running when jam was installed at user scope, `/reload-plugins` reported four more hooks and one more plugin MCP server, and the `jam` tools became available, but no notice arrived and the plugin's data directory stayed empty.",
            "That fits `adopt`, the step that records the start directory, not having run; `prune`, the startup sweep, would leave nothing in an empty directory, so it is inferred not to have run either.",
            "What that session gets at a later restart, resume, clear or compact was not observed.",
            "For comparison, a print-mode `claude -p --resume <id>` of a session that had been created with jam disabled ran the SessionStart hooks with `source: resume`, notice included.",
            "The tool descriptions carry the instructions, and the notice is what gives the model the exact command line of the CLI, with the data directory flag, which matters only when the MCP server is not available.",
            'That is one observation: other Claude Code versions, a foreground session and the Devin CLI were not checked, and the points still open are under "Plugin platform facts" in [docs/decisions.md](docs/decisions.md).',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, paragraph)

    def test_the_paragraph_stays_inside_the_one_observation(self):
        paragraph = flat(section(README, "Install")).split(README_MARKER)[1]
        self.assertNotRegex(paragraph, OVERREACH)
        for removed in (
            "falls back to the project directory when no start record exists",
            "next start, resume, clear or compact",
            "Until that session is resumed or started again",
            "so `adopt` and `prune` had not run either",
            "reported the plugin's hooks and MCP server as loaded",
            "the only place that gives the command line",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, paragraph)

    def test_the_install_commands_and_the_promise_stay_where_they_were(self):
        install = flat(section(README, "Install"))
        self.assertLess(install.index("/plugin install jam@jam"), install.index("devin plugins install GeneralD/jam"))
        self.assertLess(install.index("devin plugins install GeneralD/jam"), install.index(README_MARKER))
        self.assertLess(install.index(README_MARKER), install.index("In one background session on Claude Code 2.1.309"))


class PlatformFactTest(unittest.TestCase):
    def test_the_bullet_records_what_was_observed_with_its_date_and_version(self):
        bullet = fact()
        for phrase in (
            "jam was installed at user scope with `/plugin install` while a background session was already running, and `/reload-plugins` was run in that session.",
            "The reload reported one more plugin, four more hooks and one more plugin MCP server, and the jam tools became available there.",
            "No SessionStart notice arrived in that session, and the plugin's data directory stayed empty afterwards.",
            "For comparison, a print-mode `claude -p --resume <id>` of a session that had been created with jam disabled loaded the plugin, connected the MCP server and ran the SessionStart hooks with `source: resume`, notice included.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bullet)

    def test_the_bullet_separates_what_was_observed_from_what_was_inferred(self):
        bullet = fact()
        for phrase in (
            "Two things were observed: no notice, and an empty data directory.",
            "`adopt` writes the start record into that directory (D14), so the empty directory fits `adopt` not having run.",
            "`prune` would leave nothing in an empty directory, so that it did not run is inferred from the missing notice and the missing record.",
            "So in that session the reload reported the hooks and made the MCP tools available, and the SessionStart hooks appear not to have run, although a session start runs them (D13).",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bullet)

    def test_the_bullet_names_the_cost_without_claiming_the_guard_ran(self):
        bullet = fact()
        for phrase in (
            "the tool descriptions carry the instructions for using the tools",
            "no worker mark is involved (a mark is taken at a fresh start, D13)",
            "the guard reads `CLAUDE_PROJECT_DIR` first and the start record only when that is not absolute, so a missing record matters only then, and the guard then allows (D14, step 5), and whether the guard ran in the reloaded session was not checked",
            "the notice is what gives the model the exact command line of the CLI, with the data directory flag, which matters only when the MCP server is not available",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bullet)
        self.assertNotIn("falls back to the project directory", flat(DECISIONS))
        self.assertNotIn("falls back to the project directory", flat(README))
        self.assertNotIn("the only place that gives the command line", bullet)

    def test_the_bullet_lists_what_was_not_checked_and_keeps_the_server_instructions_open(self):
        bullet = fact()
        for phrase in (
            "Not checked: other Claude Code versions; a foreground session;",
            "the hooks of a second running session, which was seen to start a jam MCP server after its own reload;",
            "whether a `clear` or a `compact` in a reloaded session runs the hooks;",
            "the Devin CLI;",
            "and whether a reload re-injects the MCP server `instructions`, which D12 defers and which would reach a reloaded session if it did (#24).",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bullet)

    def test_the_bullet_stays_inside_the_one_observation(self):
        self.assertNotRegex(fact(), OVERREACH)

    def test_the_guard_still_reads_the_project_directory_before_the_record(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertIn("(5) The start directory is `CLAUDE_PROJECT_DIR` when it is absolute, else the record `start.<id>`, else allow;", d14)


class StatementsOfWhatASessionGetsTest(unittest.TestCase):
    def test_d5_says_a_reload_gave_no_notice_in_the_one_session_checked(self):
        d5 = flat(section(DECISIONS, "D5."))
        self.assertIn("The AI is told the CLI's absolute path by a SessionStart hook (`additionalContext`, D13), so no PATH change is needed.", d5)
        self.assertIn(
            'In the one session checked, `/reload-plugins` did not bring the notice to a session that was already running when the plugin was installed (see "Plugin platform facts").',
            d5,
        )
        self.assertNotIn("and has the tool descriptions until its next start", d5)

    def test_d12_keeps_the_server_instructions_deferred_and_names_the_open_question(self):
        d12 = flat(section(DECISIONS, "D12."))
        self.assertIn("the MCP extras (server instructions, pagination, structured output, cancellation).", d12)
        self.assertIn(
            "Server instructions are the extra that could reach a session that only reloaded the plugin, if Claude Code injects them at reload; that was not checked (#24).",
            d12,
        )

    def test_d13_records_the_missing_notice_and_record_after_a_reload_without_claiming_a_skip(self):
        d13 = flat(section(DECISIONS, "D13."))
        bullet = d13.split("**No notice and no start record after a reload (observed once, #24).**")[1].split(" - **")[0]
        for phrase in (
            "On 2.1.309 (2026-10-28), `/reload-plugins` in one running background session reported four more hooks, and no notice arrived and no start record was written there, which fits the notice and `adopt` not having run;",
            "that `prune` did not run is inferred, since it leaves nothing in an empty directory.",
            "What a `clear` or a `compact` does in a reloaded session was not tried.",
            'See "`/reload-plugins` in a running session" under "Plugin platform facts".',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bullet)
        self.assertNotRegex(bullet, OVERREACH)
        self.assertNotIn("**A reload does not run them", d13)
        self.assertNotIn("**A reload did not run the SessionStart hooks", d13)
        self.assertNotIn("without running the three SessionStart hooks", d13)
        self.assertIn("**`notice`** has no matcher, so it fires again on resume, clear, compact and fork", d13)

    def test_d15_no_longer_says_the_notice_reaches_a_session_at_every_start_without_the_exception(self):
        d15 = flat(section(DECISIONS, "D15."))
        self.assertIn(
            'the notice is injected at every session start and after every compaction (though not by `/reload-plugins` in the one session checked; see "Plugin platform facts"), while a skill body loads only when it is used.',
            d15,
        )
        self.assertNotIn("after every compaction, while a skill body loads only when it is used.", d15)

    def test_the_open_items_keep_the_resume_point_and_add_the_reload_points(self):
        # The whole sentence is pinned in test_closed_items_docs.py; this keeps the join between the two points.
        items = flat(section(DECISIONS, "Open verification items"))
        self.assertIn('("Resuming a background session" under "Plugin platform facts"), and what `/reload-plugins` gives a running session', items)
        self.assertNotIn(", and a resume under a different configuration directory", items)


class PublicRepositoryTest(unittest.TestCase):
    """Only two fragments are checked; names of people or organisations cannot be listed in a public test."""

    def test_the_documents_name_no_home_directory(self):
        for name, text in (("README.md", README), ("docs/decisions.md", DECISIONS)):
            for fragment in ("/Users/", "/home/"):
                with self.subTest(document=name, fragment=fragment):
                    self.assertNotIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
