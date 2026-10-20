"""Structural checks for the plugin manifests and hook wiring.

Stdlib only. Run from anywhere: python3 -m unittest discover -s tests
"""

import ast
import json
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
MCP_JSON = ROOT / ".mcp.json"
SRC = ROOT / "src" / "jam"
LAUNCHER = ROOT / "scripts" / "jam"
MAX_LINES = 400

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
        command = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jam" --flag'
        self.assertEqual(list(referenced_scripts(command)), ["scripts/jam"])

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


class McpConfigTest(unittest.TestCase):
    """.mcp.json is read unconditionally: a missing file must fail, not skip."""

    def server(self):
        servers = load_json(MCP_JSON)["mcpServers"]
        self.assertEqual(list(servers), ["jam"])
        return servers["jam"]

    def test_it_declares_exactly_the_python_launcher_through_the_plugin_root(self):
        server = self.server()
        self.assertEqual(server["command"], "python3")
        self.assertEqual(server["args"], ["-I", "${CLAUDE_PLUGIN_ROOT}/scripts/jam", "mcp"])
        self.assertNotIn("env", server)
        self.assertNotIn("cwd", server)

    def test_the_joined_command_passes_the_same_checks_as_a_hook_command(self):
        server = self.server()
        joined = " ".join([server["command"], *server["args"]])
        self.assertEqual(command_problems(joined), [])
        scripts = list(referenced_scripts(joined))
        self.assertEqual(scripts, ["scripts/jam"])
        self.assertEqual([script_problem(rel) for rel in scripts], [None])

    def test_the_manifest_declares_no_servers_of_its_own(self):
        self.assertNotIn("mcpServers", load_json(PLUGIN_JSON))


class LauncherFileTest(unittest.TestCase):
    def test_it_has_a_python3_shebang(self):
        first_line = LAUNCHER.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(first_line.startswith("#!"), first_line)
        self.assertIn("python3", first_line)

    @unittest.skipUnless(os.name == "posix", "executable bits are a POSIX notion")
    def test_it_carries_the_executable_bit(self):
        self.assertTrue(LAUNCHER.stat().st_mode & stat.S_IXUSR)

    def test_it_lives_in_scripts_not_in_a_bin_directory_that_would_join_the_path(self):
        self.assertFalse((ROOT / "bin").exists())


def jam_imports(source, package):
    """Every dotted name under jam that a module imports, with relative imports resolved."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            parts = package.split(".")[: len(package.split(".")) - max(node.level - 1, 0)] if node.level else []
            base = ".".join([*parts, *([node.module] if node.module else [])])
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return {name for name in found if name == "jam" or name.startswith("jam.")}


def string_constants(source):
    return [node.value for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


class JamImportsCheckTest(unittest.TestCase):
    """The import and literal scanners must see what they are meant to catch."""

    def test_relative_and_absolute_forms_resolve_to_dotted_names(self):
        self.assertIn("jam.service", jam_imports("from .service import Jam", "jam"))
        self.assertIn("jam.registry", jam_imports("from . import registry", "jam"))
        self.assertIn("jam.harness.claude", jam_imports("import jam.harness.claude", "jam"))
        self.assertIn("jam.harness", jam_imports("from jam.harness import claude", "jam"))
        self.assertIn("jam.errors", jam_imports("from ..errors import HarnessError", "jam.harness"))
        self.assertEqual(jam_imports("import json\nfrom pathlib import Path", "jam"), set())

    def test_string_constants_include_docstrings(self):
        self.assertIn("CLAUDE_X", string_constants('"""CLAUDE_X"""\nvalue = "other"'))


class ModuleBoundaryTest(unittest.TestCase):
    FORBIDDEN = ("jam.service", "jam.registry", "jam.harness")

    def test_the_entry_points_reach_the_core_only_through_operations_and_compose(self):
        for name in ("mcp.py", "cli.py"):
            with self.subTest(module=name):
                imports = jam_imports((SRC / name).read_text(encoding="utf-8"), "jam")
                banned = sorted(i for i in imports if any(i == f or i.startswith(f + ".") for f in self.FORBIDDEN))
                self.assertEqual(banned, [])

    def test_the_cli_reaches_the_composition_root(self):
        imports = jam_imports((SRC / "cli.py").read_text(encoding="utf-8"), "jam")
        self.assertTrue({"jam.compose", "jam.operations"} <= imports, imports)

    def test_only_the_composition_root_names_the_claude_harness_outside_its_package(self):
        users = {path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py") if "ClaudeHarness" in path.read_text(encoding="utf-8")}
        self.assertEqual({user for user in users if not user.startswith("harness/")}, {"compose.py"})

    def test_environment_variable_names_live_in_the_harness_package_only(self):
        for path in sorted(SRC.rglob("*.py")):
            if path.relative_to(SRC).parts[0] == "harness":
                continue
            with self.subTest(module=path.relative_to(SRC).as_posix()):
                self.assertEqual([text for text in string_constants(path.read_text(encoding="utf-8")) if "CLAUDE_" in text], [])
        env_module = (SRC / "harness" / "claude_env.py").read_text(encoding="utf-8")
        for name in ("CLAUDE_PLUGIN_DATA", "CLAUDE_CODE_SESSION_ID", "CLAUDE_JOB_DIR"):
            self.assertIn(name, string_constants(env_module))


BUILTIN_TYPES = {"str", "int", "float", "bool", "bytes", "list", "dict", "set", "tuple", "object"}
NEWER_TYPING = {
    "TypeAlias", "ParamSpec", "Concatenate", "TypeGuard", "Self", "Never", "LiteralString", "TypeVarTuple",
    "Unpack", "Required", "NotRequired", "override", "assert_never", "assert_type", "reveal_type", "dataclass_transform",
}


def annotation_node_ids(tree):
    annotations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
            annotations.extend(arg.annotation for arg in every if arg is not None and arg.annotation is not None)
            if getattr(node, "returns", None) is not None:
                annotations.append(node.returns)
    return {id(inner) for annotation in annotations for inner in ast.walk(annotation)}


def looks_like_a_type(node):
    if isinstance(node, ast.Subscript):
        node = node.value
    return (isinstance(node, ast.Constant) and node.value is None) or (isinstance(node, ast.Name) and node.id in BUILTIN_TYPES)


def newer_python_uses(source):
    """Runtime uses of Python 3.10+ features that `from __future__ import annotations` does not cover."""
    tree = ast.parse(source, feature_version=(3, 9))
    skipped = annotation_node_ids(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr) and id(node) not in skipped:
            if looks_like_a_type(node.left) or looks_like_a_type(node.right):
                found.append(f"line {node.lineno}: runtime X | Y")
        elif isinstance(node, ast.ImportFrom) and node.module in ("typing", "typing_extensions"):
            found.extend(f"line {node.lineno}: typing.{a.name}" for a in node.names if a.name in NEWER_TYPING)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            keywords = {keyword.arg for keyword in node.keywords}
            if (name == "dataclass" and keywords & {"slots", "kw_only"}) or (name == "zip" and "strict" in keywords):
                found.append(f"line {node.lineno}: {name}({', '.join(sorted(k for k in keywords if k))})")
    return found


def starts_with_future_annotations(source):
    body = ast.parse(source).body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    first = body[0] if body else None
    return first is None or (isinstance(first, ast.ImportFrom) and first.module == "__future__" and [a.name for a in first.names] == ["annotations"])


class HygieneCheckTest(unittest.TestCase):
    def test_the_python_39_scanner_flags_what_it_claims_to(self):
        self.assertEqual(newer_python_uses("value = int | None"), ["line 1: runtime X | Y"])
        self.assertEqual(newer_python_uses("ok = isinstance(x, str | bytes)"), ["line 1: runtime X | Y"])
        self.assertEqual(newer_python_uses("from typing import TypeAlias"), ["line 1: typing.TypeAlias"])
        self.assertEqual(len(newer_python_uses("@dataclass(slots=True)\nclass A: ...")), 1)
        self.assertEqual(len(newer_python_uses("list(zip(a, b, strict=True))")), 1)
        with self.assertRaises(SyntaxError):
            newer_python_uses("match x:\n    case 1:\n        pass\n")

    def test_the_python_39_scanner_leaves_annotations_and_plain_flags_alone(self):
        clean = "def f(a: int | None) -> str | None:\n    b: list[int] | None = None\n    return None\nmask = 1 | 2\n"
        self.assertEqual(newer_python_uses(clean), [])

    def test_the_future_import_check_can_fail(self):
        self.assertTrue(starts_with_future_annotations('"""Doc."""\n\nfrom __future__ import annotations\n\nimport os\n'))
        self.assertTrue(starts_with_future_annotations('"""Only a docstring."""\n'))
        self.assertFalse(starts_with_future_annotations('"""Doc."""\n\nimport os\n'))
        self.assertFalse(starts_with_future_annotations("import os\nfrom __future__ import annotations\n"))


class Python39HygieneTest(unittest.TestCase):
    """The system python3 of macOS is 3.9, and so are the lines these tests hold."""

    def modules(self):
        self.assertTrue(LAUNCHER.is_file(), "scripts/jam is the launcher")
        return [*sorted(SRC.rglob("*.py")), LAUNCHER]

    def test_every_module_and_the_launcher_parses_as_python_39_without_newer_features(self):
        for path in self.modules():
            with self.subTest(module=path.relative_to(ROOT).as_posix()):
                self.assertEqual(newer_python_uses(path.read_text(encoding="utf-8")), [])

    def test_every_module_starts_with_the_future_annotations_import(self):
        for path in self.modules():
            with self.subTest(module=path.relative_to(ROOT).as_posix()):
                self.assertTrue(starts_with_future_annotations(path.read_text(encoding="utf-8")))

    def test_every_module_stays_within_the_line_budget(self):
        for path in self.modules():
            with self.subTest(module=path.relative_to(ROOT).as_posix()):
                self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), MAX_LINES)


if __name__ == "__main__":
    unittest.main()
