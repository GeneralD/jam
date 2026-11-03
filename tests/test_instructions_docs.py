"""Checks that the documents record the MCP server `instructions` (#31): what they are, where the text comes from, and what one check of `/reload-plugins` showed.

Same style as test_reload_docs.py: flattened text, one section at a time, the new
wording pinned, the hedges pinned, and the evidence scoped to the two sessions
it came from (Claude Code 2.1.309, 2026-11-03).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from test_spawn_docs import DECISIONS, README, ROOT, flat, section

CLAUDE_MD = (ROOT / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
FACT_MARKER = "**MCP server instructions (observed on 2.1.309, 2026-11-03).**"
# A tripwire for the commonest widening words only; it cannot see a sentence that widens without them.
OVERREACH = re.compile(r"\b(always|never|every|all|any|whenever)\b", re.IGNORECASE)


def fact():
    """The platform-facts bullet that carries the evidence, up to the next bullet."""
    return flat(section(DECISIONS, "Plugin platform facts")).split(FACT_MARKER)[1].split(" - **")[0]


class DecisionTest(unittest.TestCase):
    def test_d12_says_what_the_instructions_are_and_where_the_text_comes_from(self):
        d12 = flat(section(DECISIONS, "D12."))
        for phrase in (
            "- **Server instructions.** The `initialize` reply carries `instructions`: the session notice without the session id line, built by the hook's own function from the plugin root and the data directory the server resolved for itself (the flag, else the variable, like the commands), so the two texts cannot drift (added on 2026-11-03, #31).",
            "The session id is left out because the one the server holds can be stale after `/clear` (above).",
            'The text is computed when `initialize` is answered and reads no file, so the `server/discover` probe (see "Plugin platform facts") still costs nothing.',
            "in one foreground session on Claude Code 2.1.309 (2026-11-03) the text was in the model's context after `/reload-plugins` had loaded the plugin, and in a fresh session at a normal start, while the five tools were reachable through tool search only",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, d12)

    def test_d5_and_d13_point_at_the_same_text(self):
        self.assertIn("The MCP server's `instructions` repeat the notice without the session id line, and in one later check they arrived at a reload (D12, #31).", flat(section(DECISIONS, "D5.")))
        self.assertIn("The MCP server's `instructions` are the same text without the session id line, from the same function (D12, #31).", flat(section(DECISIONS, "D13.")))

    def test_the_project_rules_name_the_second_way_the_model_learns_the_command_line(self):
        self.assertIn("and from the MCP server's `instructions`, which repeat that notice without the session id.", flat(CLAUDE_MD))


class PlatformFactTest(unittest.TestCase):
    def test_the_bullet_records_the_setup_and_the_two_observations(self):
        bullet = fact()
        for phrase in (
            "loaded a throwaway copy of the plugin that carried only the MCP server, with the `instructions` of D12 and no hooks or skills, installed at `local` scope from a marketplace on a local path, under a plugin name with a hyphen in it.",
            "The copy was installed while the first session was already running.",
            "the model named four servers of the owner's own setup and no jam one.",
            "After `/reload-plugins`, whose report listed counts of plugins, skills, agents, hooks and MCP servers (read as totals here and as differences in the bullet above; the two readings were not reconciled), the same question got a fifth server, `plugin:<plugin>:jam`,",
            "the model quoted the first and the last of the text's seven lines and its command line verbatim, with the copy's launcher path and the copy's data directory, `<config>/plugins/data/<plugin>-<marketplace>`.",
            "It named the five tools as `mcp__plugin_<plugin>_jam__<verb>`, the hyphen of the plugin name kept",
            "and as reachable through tool search only.",
            "The second session, started after the install, had the same text and the same deferred tools at its start.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bullet)

    def test_the_bullet_says_why_the_evidence_is_the_server_text_and_not_the_notice(self):
        bullet = fact()
        self.assertIn("The installed `jam@jam` 0.1.0 plugin, whose server returns no `instructions`, was loaded in both sessions too, with its notice; the model listed no server for it,", bullet)
        self.assertIn("the quoted command line, which names the copy's launcher and not the installed one, is why the evidence is the server text and not the notice.", bullet)

    def test_the_bullet_lists_what_was_not_checked_and_uses_no_widening_word(self):
        bullet = fact()
        self.assertIn("Not checked: other versions, a background session, a plugin installed at user scope, the Devin CLI, and whether the text is read again when a running server is restarted.", bullet)
        self.assertNotRegex(bullet, OVERREACH)

    def test_the_open_items_name_what_the_check_left_open(self):
        items = flat(section(DECISIONS, "Open verification items"))
        self.assertIn('whether the SessionStart hooks run in a reloaded foreground session (the MCP server `instructions` did arrive in one; see "MCP server instructions" under "Plugin platform facts")', items)
        self.assertNotIn("whether a reload re-injects the MCP server `instructions`", items)


class ReadmeTest(unittest.TestCase):
    def test_the_install_section_says_the_server_carries_the_text_and_what_one_check_showed(self):
        install = flat(section(README, "Install"))
        self.assertIn(
            "The MCP server's `initialize` reply now carries that text too, without the session id line, as its `instructions` (#31): in one foreground session on 2.1.309 (2026-11-03) it was in the model's context after `/reload-plugins` had loaded the plugin, and in a fresh session at its start, while the tools were listed as reachable through tool search only.",
            install,
        )


class PublicRepositoryTest(unittest.TestCase):
    def test_the_documents_name_no_home_directory_and_no_probe_path(self):
        for name, text in (("README.md", README), ("docs/decisions.md", DECISIONS), (".claude/CLAUDE.md", CLAUDE_MD)):
            for fragment in ("/Users/", "/home/", "probe31", "jobs/"):
                with self.subTest(document=name, fragment=fragment):
                    self.assertNotIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
