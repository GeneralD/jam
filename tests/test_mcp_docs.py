"""Checks that the documents say where the MCP server is declared, and why it is not `.mcp.json`."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
DECISIONS = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")


def flat(text):
    return " ".join(text.split())


def section(text, title):
    """The body of the `## <title>` section that starts with `title`."""
    (body,) = [part for part in re.split(r"^## ", text, flags=re.MULTILINE) if part.startswith(title)]
    return body


class WhereTheServerIsDeclaredTest(unittest.TestCase):
    def test_the_readme_names_the_manifest_and_not_a_root_mcp_json(self):
        readme = flat(README)
        self.assertIn("The MCP server is declared inline in `.claude-plugin/plugin.json`", readme)
        self.assertNotIn("declared in `.mcp.json`", readme)
        self.assertNotIn("MCP server (.mcp.json)", readme)

    def test_the_platform_facts_say_why_a_root_mcp_json_is_avoided(self):
        facts = flat(DECISIONS)
        self.assertIn("or inline in `plugin.json` under `mcpServers`", facts)
        self.assertIn("is also read as the project-scoped MCP configuration of any session started in a clone", facts)
        self.assertIn("`${CLAUDE_PLUGIN_ROOT}` is not set there", facts)
        # Only a session that starts the server fails; an interactive one first asks for approval.
        self.assertNotIn("every such session listed `jam` as failed to connect", facts)
        self.assertIn("an interactive session that has not approved it shows it as pending approval", facts)

    def test_the_platform_facts_say_the_documentation_shows_both_shapes_of_a_mcp_json(self):
        facts = flat(DECISIONS)
        self.assertNotIn("the documentation shows only the wrapped shape", facts)
        self.assertIn("the documentation shows both the wrapped shape and one without the wrapper", facts)

    def test_d12_no_longer_names_a_root_mcp_json(self):
        self.assertNotIn(".mcp.json", section(DECISIONS, "D12."))


class WhatALiveSessionShowedTest(unittest.TestCase):
    """A print-mode session with `--plugin-dir .` answered two open items on 2026-10-21; the documents must not still ask them."""

    def test_d12_records_the_server_connecting_and_list_answering_in_a_real_session(self):
        d12 = flat(section(DECISIONS, "D12."))
        self.assertIn("listed the server `plugin:jam:jam` as connected with the four tools", d12)
        self.assertIn("a call to `list` returned the live sessions", d12)
        self.assertNotIn("the four tools appearing in a real `claude --plugin-dir` load", d12)

    def test_the_open_items_no_longer_ask_whether_the_tools_appear(self):
        self.assertNotIn("Do the four `mcp__plugin_jam_jam__*` tools appear", flat(section(DECISIONS, "Open verification items")))

    def test_the_readme_status_says_what_a_live_session_has_shown(self):
        status = flat(section(README, "Status"))
        self.assertNotIn("has not yet been run end to end in a live session", status)
        self.assertIn("A print-mode session with `claude -p --plugin-dir .` connected the MCP server", status)


if __name__ == "__main__":
    unittest.main()
