"""Structural checks for the plugin manifests and hook wiring.

Stdlib only. Run from anywhere: python3 -m unittest discover -s tests
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
MCP_JSON = ROOT / ".mcp.json"

PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"
# Absolute paths, home-relative paths, and the usual home directory prefixes.
ABSOLUTE_PATH = re.compile(r"(^|[\s\"'=])(/Users/|/home/|~/|/(?:usr|opt|etc|var|tmp)/)")


def load_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def hook_commands(hooks_doc):
    """Yield every hook command string in a hooks.json document."""
    for groups in hooks_doc["hooks"].values():
        for group in groups:
            for hook in group.get("hooks", []):
                if "command" in hook:
                    yield hook["command"]


def command_problems(command):
    """Return what is wrong with one hook command, as a list of messages."""
    problems = []
    if PLUGIN_ROOT_VAR not in command:
        problems.append(f"does not use {PLUGIN_ROOT_VAR}: {command}")
    if ABSOLUTE_PATH.search(command):
        problems.append(f"contains an absolute or home path: {command}")
    return problems


def referenced_scripts(command):
    """Yield the repo-relative paths a command takes from the plugin root."""
    for match in re.finditer(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s\"']+)", command):
        yield match.group(1)


class CommandCheckTest(unittest.TestCase):
    """The checks themselves must catch bad input, or an empty hooks.json
    would let them pass without proving anything."""

    def test_accepts_plugin_root_relative_command(self):
        self.assertEqual(command_problems("${CLAUDE_PLUGIN_ROOT}/hooks/x.sh"), [])

    def test_flags_missing_plugin_root_variable(self):
        self.assertTrue(command_problems("hooks/x.sh"))

    def test_flags_home_directory_path(self):
        self.assertTrue(command_problems("${CLAUDE_PLUGIN_ROOT}/x.sh /Users/someone/y"))

    def test_extracts_referenced_scripts(self):
        command = 'python3 "${CLAUDE_PLUGIN_ROOT}/bin/jam" --flag'
        self.assertEqual(list(referenced_scripts(command)), ["bin/jam"])

    def test_walks_nested_hook_structure(self):
        doc = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "c"}]}]}}
        self.assertEqual(list(hook_commands(doc)), ["c"])


class ManifestTest(unittest.TestCase):
    def test_plugin_manifest_names_the_plugin(self):
        self.assertEqual(load_json(PLUGIN_JSON)["name"], "jam")

    def test_marketplace_lists_this_plugin(self):
        marketplace = load_json(MARKETPLACE_JSON)
        self.assertTrue(marketplace["name"])
        self.assertIn("name", marketplace["owner"])
        names = [entry["name"] for entry in marketplace["plugins"]]
        self.assertIn(load_json(PLUGIN_JSON)["name"], names)

    def test_plugin_and_marketplace_entry_agree(self):
        plugin = load_json(PLUGIN_JSON)
        entry = next(e for e in load_json(MARKETPLACE_JSON)["plugins"] if e["name"] == plugin["name"])
        if "version" in plugin and "version" in entry:
            self.assertEqual(plugin["version"], entry["version"])

    def test_mcp_servers_are_declared_in_one_place_only(self):
        if MCP_JSON.exists():
            self.assertNotIn("mcpServers", load_json(PLUGIN_JSON))


class HooksTest(unittest.TestCase):
    def test_hooks_file_has_top_level_hooks_key(self):
        self.assertIsInstance(load_json(HOOKS_JSON).get("hooks"), dict)

    def test_every_command_uses_plugin_root_and_no_absolute_path(self):
        problems = [p for c in hook_commands(load_json(HOOKS_JSON)) for p in command_problems(c)]
        self.assertEqual(problems, [])

    def test_every_referenced_script_exists(self):
        missing = [
            rel
            for command in hook_commands(load_json(HOOKS_JSON))
            for rel in referenced_scripts(command)
            if not (ROOT / rel).exists()
        ]
        self.assertEqual(missing, [])


class HygieneTest(unittest.TestCase):
    def test_no_absolute_or_home_paths_in_manifests(self):
        candidates = [PLUGIN_JSON, MARKETPLACE_JSON, HOOKS_JSON, MCP_JSON]
        offenders = [
            str(path.relative_to(ROOT))
            for path in candidates
            if path.exists() and ABSOLUTE_PATH.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
