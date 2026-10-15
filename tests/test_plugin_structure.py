"""Structural checks for the plugin manifests and hook wiring.

Stdlib only. Run from anywhere: python3 -m unittest discover -s tests
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
MCP_JSON = ROOT / ".mcp.json"

PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"
# A token that starts with "/", "~", a home variable, a drive letter, or a UNC
# prefix is an absolute or home-relative path. Tokens begin at the start of the
# text, after whitespace, a quote, "=", or "(". "/dev/null" is allowed.
ABSOLUTE_PATH = re.compile(
    r"(?:^|[\s\"'=(])(?:/(?!dev/null\b)|~|\$HOME|\$\{HOME\}|[A-Za-z]:[\\/]|\\\\)"
)


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


def script_problem(rel, root=ROOT):
    """Return what is wrong with a plugin-relative script path, or None."""
    if ".." in Path(rel).parts:
        return f"{rel}: contains a '..' segment"
    resolved = (root / rel).resolve()
    if not resolved.is_relative_to(root.resolve()):
        return f"{rel}: resolves outside the plugin"
    if not resolved.is_file():
        return f"{rel}: is not a file in the plugin"
    return None


class CommandCheckTest(unittest.TestCase):
    """The checks themselves must catch bad input, or an empty hooks.json
    would let them pass without proving anything."""

    def test_accepts_plugin_root_relative_command(self):
        self.assertEqual(command_problems("${CLAUDE_PLUGIN_ROOT}/hooks/x.sh"), [])

    def test_flags_missing_plugin_root_variable(self):
        self.assertTrue(command_problems("hooks/x.sh"))

    def test_flags_home_directory_path(self):
        self.assertTrue(command_problems("${CLAUDE_PLUGIN_ROOT}/x.sh /Users/someone/y"))

    def test_flags_absolute_paths_under_any_prefix(self):
        for tail in ("/workspace/repo", "~/repo", "$HOME/repo", "${HOME}/repo", "C:\\repo", "\\\\host\\share", "--dir=/srv/x", '"/mnt/x"'):
            with self.subTest(tail=tail):
                self.assertTrue(command_problems("${CLAUDE_PLUGIN_ROOT}/x.sh " + tail))

    def test_allows_dev_null_and_url_and_plugin_root_arguments(self):
        for tail in ("2>/dev/null", "--url=https://example.com/x", '"${CLAUDE_PLUGIN_ROOT}/data"'):
            with self.subTest(tail=tail):
                self.assertEqual(command_problems("${CLAUDE_PLUGIN_ROOT}/x.sh " + tail), [])

    def test_extracts_referenced_scripts(self):
        command = 'python3 "${CLAUDE_PLUGIN_ROOT}/bin/jam" --flag'
        self.assertEqual(list(referenced_scripts(command)), ["bin/jam"])

    def test_script_check_accepts_a_real_file(self):
        self.assertIsNone(script_problem("tests/test_plugin_structure.py"))

    def test_script_check_rejects_missing_directory_and_dotdot(self):
        for rel in ("hooks/nope.sh", "hooks", "../outside", "hooks/../../outside"):
            with self.subTest(rel=rel):
                self.assertIsNotNone(script_problem(rel))

    def test_script_check_rejects_a_symlink_that_leaves_the_plugin(self):
        with tempfile.TemporaryDirectory() as outer, tempfile.TemporaryDirectory() as inner:
            (Path(outer) / "real.sh").write_text("#!/bin/sh\n")
            (Path(inner) / "link.sh").symlink_to(Path(outer) / "real.sh")
            self.assertIn("outside", script_problem("link.sh", root=Path(inner)))

    def test_walks_nested_hook_structure(self):
        doc = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "c"}]}]}}
        self.assertEqual(list(hook_commands(doc)), ["c"])


class ManifestTest(unittest.TestCase):
    def test_plugin_manifest_names_the_plugin(self):
        self.assertEqual(load_json(PLUGIN_JSON)["name"], "jam")

    def test_marketplace_name_and_plugin_source_match_the_install_contract(self):
        # Users install with jam@jam, and the plugin lives at the repo root.
        marketplace = load_json(MARKETPLACE_JSON)
        self.assertEqual(marketplace["name"], "jam")
        self.assertIn("name", marketplace["owner"])
        entries = {entry["name"]: entry for entry in marketplace["plugins"]}
        self.assertEqual(entries[load_json(PLUGIN_JSON)["name"]]["source"], "./")

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
        problems = [
            problem
            for command in hook_commands(load_json(HOOKS_JSON))
            for rel in referenced_scripts(command)
            if (problem := script_problem(rel))
        ]
        self.assertEqual(problems, [])


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
