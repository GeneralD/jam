"""Structure checks for the hook wiring: what hooks/hooks.json declares, and which module may import which.

These sit beside test_plugin_structure.py, whose helpers they reuse, because that
file is at its line budget. The checks there (placeholder, no absolute path,
script exists) apply to the hooks declared here as well.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy
from test_plugin_structure import HOOKS_JSON, SRC, command_problems, jam_imports, load_json, referenced_scripts, script_problem

# The two directories the tree is read from: SRC is src/jam (the package), and its parent is what goes on sys.path.
PACKAGE_PARENT = SRC.parent

hooks = lazy("jam.harness.claude_hooks")

LAUNCH = 'python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/jam" hook '
HARNESS_PACKAGE = "jam.harness"
SESSION_START = "SessionStart"
# Every event, matcher, command, timeout and async setting the plugin declares. A new entry is a deliberate edit here.
DECLARED = {
    (SESSION_START, None, LAUNCH + "notice", 5, None),
    (SESSION_START, "startup", LAUNCH + "prune", 3, None),
}
# The guard handler exists but hooks/hooks.json does not declare it, so no session is affected. These two constants are the entry the
# registering change will add (the `|| exit 0` keeps a missing script, which exits 2 and would block every edit, from blocking one).
PRE_TOOL_USE = "PreToolUse"
GUARD_COMMAND = LAUNCH + "guard || exit 0"
GUARD_TIMEOUT = 5
UNREGISTERED = {"guard"}


def entries(document):
    """(event, matcher, command, timeout, async) of every hook in a hooks.json document."""
    return {
        (event, group.get("matcher"), hook.get("command"), hook.get("timeout"), hook.get("async"))
        for event, groups in document["hooks"].items()
        for group in groups
        for hook in group.get("hooks", [])
    }


def every_hook(document):
    return [hook for groups in document["hooks"].values() for group in groups for hook in group.get("hooks", [])]


class DeclaredHooksTest(unittest.TestCase):
    def setUp(self):
        self.document = load_json(HOOKS_JSON)

    def test_the_declared_hooks_are_exactly_the_session_start_pair(self):
        self.assertEqual(entries(self.document), DECLARED)

    def test_the_file_is_not_vacuously_empty(self):
        self.assertGreaterEqual(len(every_hook(self.document)), 1)

    def test_session_start_is_the_only_event_and_no_session_end_hook_exists(self):
        # D13: SessionEnd has a 1.5 s budget shared by all its hooks that a plugin cannot raise, so registering nothing is the decision.
        self.assertEqual(set(self.document["hooks"]), {SESSION_START})

    def test_the_notice_has_no_matcher_so_it_fires_again_on_resume_clear_compact_and_fork(self):
        (notice_group,) = [group for group in self.document["hooks"][SESSION_START] if "notice" in group["hooks"][0]["command"]]
        self.assertNotIn("matcher", notice_group)

    def test_no_hook_is_asynchronous_and_none_has_an_on_failure_setting(self):
        for hook in every_hook(self.document):
            with self.subTest(command=hook["command"]):
                self.assertNotIn("async", hook)
                self.assertNotIn("asyncRewake", hook)
                self.assertNotIn("onFailure", hook)
        for group in self.document["hooks"][SESSION_START]:
            self.assertNotIn("onFailure", group)

    def test_every_hook_is_a_command_with_an_explicit_timeout_of_at_most_ten_seconds(self):
        for hook in every_hook(self.document):
            with self.subTest(command=hook["command"]):
                self.assertEqual(hook["type"], "command")
                self.assertIsInstance(hook["timeout"], int)  # the platform default for a command hook is 600 seconds
                self.assertTrue(0 < hook["timeout"] <= 10)

    def test_every_command_runs_a_named_hook_through_the_isolated_launcher(self):
        for hook in every_hook(self.document):
            with self.subTest(command=hook["command"]):
                self.assertTrue(hook["command"].startswith(LAUNCH), hook["command"])
                self.assertIn(hook["command"][len(LAUNCH):], hooks.HOOKS)

    def test_each_in_process_alarm_goes_off_before_the_platform_timeout_of_the_same_hook(self):
        for hook in every_hook(self.document):
            name = hook["command"][len(LAUNCH):]
            with self.subTest(hook=name):
                self.assertLess(hooks.HOOKS[name].alarm, hook["timeout"])

    def test_every_table_entry_but_the_unregistered_ones_is_wired_and_every_wired_hook_is_in_the_table(self):
        wired = {hook["command"][len(LAUNCH):] for hook in every_hook(self.document)}
        self.assertEqual(wired, set(hooks.HOOKS) - UNREGISTERED)

    def test_the_guard_is_in_the_table_and_nowhere_in_hooks_json(self):
        self.assertEqual(UNREGISTERED & set(hooks.HOOKS), UNREGISTERED)
        self.assertNotIn(PRE_TOOL_USE, self.document["hooks"])
        for hook in every_hook(self.document):
            with self.subTest(command=hook["command"]):
                self.assertNotIn("guard", hook["command"])
        self.assertNotIn("guard", HOOKS_JSON.read_text(encoding="utf-8").lower())


class GuardEntryTest(unittest.TestCase):
    """The entry the registering change will add is pinned here already, so that the handler is built for it."""

    def test_the_command_is_the_launcher_with_the_guard_name_and_the_exit_zero_wrapper(self):
        self.assertTrue(GUARD_COMMAND.startswith(LAUNCH), GUARD_COMMAND)
        self.assertEqual(GUARD_COMMAND[len(LAUNCH):], "guard || exit 0")

    def test_it_passes_the_same_structure_checks_as_the_declared_commands(self):
        self.assertEqual(command_problems(GUARD_COMMAND), [])
        self.assertEqual(list(referenced_scripts(GUARD_COMMAND)), ["scripts/jam"])
        self.assertIsNone(script_problem("scripts/jam"))

    def test_the_guard_alarm_goes_off_before_the_timeout_of_that_entry(self):
        name = GUARD_COMMAND[len(LAUNCH):].split(" ")[0]
        self.assertIn(name, hooks.HOOKS)
        self.assertLess(hooks.HOOKS[name].alarm, GUARD_TIMEOUT)

    def test_the_timeout_is_explicit_and_at_most_ten_seconds_like_every_other_hook(self):
        self.assertTrue(0 < GUARD_TIMEOUT <= 10)


def imports_of(name):
    return jam_imports((SRC / name).read_text(encoding="utf-8"), HARNESS_PACKAGE)


class BoundaryTest(unittest.TestCase):
    """The notice names Claude Code, so it lives in the harness package; the core never reaches into it."""

    def test_the_notice_module_imports_nothing_of_jam_but_the_session_id_check(self):
        self.assertLessEqual(imports_of("harness/notice.py"), {"jam.session", "jam.session.is_id"})

    def test_the_hook_modules_do_not_import_the_entry_points_the_composition_root_or_the_service(self):
        banned = ("jam.cli", "jam.compose", "jam.mcp", "jam.operations", "jam.service")
        for name in ("harness/claude_hooks.py", "harness/hook_io.py"):
            with self.subTest(module=name):
                found = sorted(i for i in imports_of(name) if any(i == b or i.startswith(b + ".") for b in banned))
                self.assertEqual(found, [])

    def test_the_registry_is_imported_inside_the_prune_handler_and_not_at_module_level(self):
        tree = ast.parse((SRC / "harness" / "claude_hooks.py").read_text(encoding="utf-8"))
        top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = {name for node in top_level for name in jam_imports(ast.unparse(node), HARNESS_PACKAGE)}
        self.assertFalse({n for n in names if n == "jam.registry" or n.startswith("jam.registry.")}, names)

    def test_the_guard_path_modules_are_imported_inside_the_handlers_and_not_at_module_level(self):
        tree = ast.parse((SRC / "harness" / "claude_hooks.py").read_text(encoding="utf-8"))
        top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = {name for node in top_level for name in jam_imports(ast.unparse(node), HARNESS_PACKAGE)}
        for module in ("jam.guard", "jam.claims", "jam.repos", "jam.files", "jam.sweep"):
            with self.subTest(module=module):
                self.assertFalse({n for n in names if n == module or n.startswith(module + ".")}, names)

    def test_only_the_composition_root_outside_the_harness_package_imports_the_harness(self):
        users = {
            path.relative_to(SRC).as_posix()
            for path in SRC.rglob("*.py")
            if path.relative_to(SRC).parts[0] != "harness"
            and any(i == HARNESS_PACKAGE or i.startswith(HARNESS_PACKAGE + ".") for i in jam_imports(path.read_text(encoding="utf-8"), "jam"))
        }
        self.assertEqual(users, {"compose.py"})


# The harness-neutral modules the foreign-repository guard stands on, and the jam modules each may import (a `from .x import y` also lists `jam.x.y`).
CORE_IMPORTS = {
    "files.py": set(),
    "repos.py": {"jam.files", "jam.files.read_small"},
    "claims.py": {"jam.files", "jam.files.read_small", "jam.files.real_directory", "jam.session", "jam.session.ID_PATTERN", "jam.session.is_id"},
    "sweep.py": {"jam.files", "jam.files.real_directory", "jam.registry", "jam.registry.expired"},
    "guard.py": {"jam.repos", "jam.repos.Repo", "jam.session", "jam.session.is_id"},
}
# Modules a core module may only import inside the function that needs them: they cost start-up time on the hot path.
LAZY_ONLY = ("subprocess", "hashlib", "tempfile", "argparse", "jam.registry")
CLAUDE_WORDS = ("claude", "pretooluse", "sessionstart", "notebookedit", "multiedit", "mcp__")
# Tool names that are also ordinary English, so they are matched as capitalised whole words. `Edit` is left out: it is the guard's own noun.
CLAUDE_TOOLS = ("Write", "Bash", "Glob", "Grep", "WebFetch", "WebSearch", "TodoWrite", "SendMessage")


def top_level_modules(name):
    """Every module a file imports outside any function: standard ones as written, jam ones with relative imports resolved."""
    found = set()
    for node in ast.parse((SRC / name).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.update(jam_imports(ast.unparse(node), "jam") if node.level else {node.module})
    return found


def imports_of_core(name):
    return jam_imports((SRC / name).read_text(encoding="utf-8"), "jam")


class GuardCoreBoundaryTest(unittest.TestCase):
    """The guard's storage and repository primitives are core: stdlib only, no harness, no Claude Code names."""

    def test_each_core_module_imports_only_the_jam_modules_listed_for_it(self):
        for name, allowed in CORE_IMPORTS.items():
            with self.subTest(module=name):
                self.assertLessEqual(imports_of_core(name), allowed)

    def test_no_core_module_imports_the_harness_the_entry_points_or_the_composition_root(self):
        banned = (HARNESS_PACKAGE, "jam.cli", "jam.compose", "jam.mcp", "jam.operations", "jam.service")
        for name in CORE_IMPORTS:
            with self.subTest(module=name):
                self.assertEqual(sorted(i for i in imports_of_core(name) if any(i == b or i.startswith(b + ".") for b in banned)), [])

    def test_no_core_module_names_claude_code_its_events_or_its_tools_not_even_in_a_comment(self):
        for name in CORE_IMPORTS:
            text = (SRC / name).read_text(encoding="utf-8").lower()
            for word in CLAUDE_WORDS:
                with self.subTest(module=name, word=word):
                    self.assertNotIn(word, text)

    def test_no_core_module_names_a_claude_code_tool_as_a_capitalised_word(self):
        for name in CORE_IMPORTS:
            text = (SRC / name).read_text(encoding="utf-8")
            for tool in CLAUDE_TOOLS:
                with self.subTest(module=name, tool=tool):
                    self.assertIsNone(re.search(rf"\b{tool}\b", text))

    def test_the_heavy_modules_are_imported_only_inside_the_functions_that_need_them(self):
        for name in CORE_IMPORTS:
            banned = set(LAZY_ONLY) - ({"jam.registry"} if name == "sweep.py" else set())  # the sweep belongs to the prune hook, which loads the registry anyway
            with self.subTest(module=name):
                self.assertEqual(top_level_modules(name) & banned, set())

    def test_importing_the_hot_path_modules_loads_none_of_the_heavy_ones(self):
        heavy = ("argparse", "subprocess", "tempfile", "hashlib", "jam.registry", "jam.sweep", "jam.cli", "jam.compose", "jam.mcp", "jam.operations", "jam.service", HARNESS_PACKAGE)
        code = "import sys\nsys.path.insert(0, sys.argv[1])\nimport jam.files, jam.repos, jam.claims, jam.guard\nprint(' '.join(n for n in sys.argv[2:] if n in sys.modules))\n"
        proc = subprocess.run([sys.executable, "-I", "-c", code, str(PACKAGE_PARENT), *heavy], capture_output=True, text=True, timeout=60)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertEqual(proc.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
