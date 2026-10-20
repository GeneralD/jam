"""Structure checks for the hook wiring: what hooks/hooks.json declares, and which module may import which.

These sit beside test_plugin_structure.py, whose helpers they reuse, because that
file is at its line budget. The checks there (placeholder, no absolute path,
script exists) apply to the hooks declared here as well.
"""

from __future__ import annotations

import ast
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy
from test_plugin_structure import HOOKS_JSON, SRC, jam_imports, load_json

hooks = lazy("jam.harness.claude_hooks")

LAUNCH = 'python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/jam" hook '
HARNESS_PACKAGE = "jam.harness"
SESSION_START = "SessionStart"
# Every event, matcher, command, timeout and async setting the plugin declares. A new entry is a deliberate edit here.
DECLARED = {
    (SESSION_START, None, LAUNCH + "notice", 5, None),
    (SESSION_START, "startup", LAUNCH + "prune", 3, None),
}


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

    def test_every_table_entry_is_wired_and_every_wired_hook_is_in_the_table(self):
        wired = {hook["command"][len(LAUNCH):] for hook in every_hook(self.document)}
        self.assertEqual(wired, set(hooks.HOOKS))


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

    def test_only_the_composition_root_outside_the_harness_package_imports_the_harness(self):
        users = {
            path.relative_to(SRC).as_posix()
            for path in SRC.rglob("*.py")
            if path.relative_to(SRC).parts[0] != "harness"
            and any(i == HARNESS_PACKAGE or i.startswith(HARNESS_PACKAGE + ".") for i in jam_imports(path.read_text(encoding="utf-8"), "jam"))
        }
        self.assertEqual(users, {"compose.py"})


if __name__ == "__main__":
    unittest.main()
