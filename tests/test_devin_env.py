"""Tests for the one module that knows the Devin CLI environment variable names."""

from __future__ import annotations

import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from jam.errors import HarnessError

from test_operations import lazy

devin_env = lazy("jam.harness.devin_env")

# The variable names are spelled out here on purpose: the tests must not depend
# on what the module calls its constants.
AGENT_VAR, DATA_VAR, PROJECT_VAR = "AI_AGENT", "PLUGIN_DATA", "DEVIN_PROJECT_DIR"
HOME_VAR = "HOME"
# Values the directory resolvers must refuse: empty, relative, a control character, the wrong type.
UNUSABLE = ("", "relative/dir", ".", "~/dir", "/a\x00b", None, 5, b"/abs", ["/abs"])


class DetectTest(unittest.TestCase):
    def test_the_agent_variable_marks_a_devin_session(self):
        self.assertTrue(devin_env.detect({AGENT_VAR: "devin_3000-11-92_agent"}))

    def test_the_project_and_data_variables_mark_a_hook_process(self):
        for var in (PROJECT_VAR, DATA_VAR):
            with self.subTest(var=var):
                self.assertTrue(devin_env.detect({var: "/abs/dir"}))

    def test_other_agents_and_empty_environments_are_not_devin(self):
        for env in ({}, {AGENT_VAR: "codex"}, {AGENT_VAR: ""}):
            with self.subTest(env=env):
                self.assertFalse(devin_env.detect(env))


class DataDirTest(unittest.TestCase):
    def test_the_flag_beats_the_environment(self):
        self.assertEqual(devin_env.data_dir("/from/flag", {DATA_VAR: "/from/env"}), "/from/flag")

    def test_the_environment_is_used_without_a_flag(self):
        self.assertEqual(devin_env.data_dir(None, {DATA_VAR: "/from/env"}), "/from/env")

    def test_an_empty_flag_counts_as_absent(self):
        self.assertEqual(devin_env.data_dir("", {DATA_VAR: "/from/env"}), "/from/env")

    def test_neither_gives_none(self):
        for flag, env in ((None, {}), ("", {}), (None, {DATA_VAR: ""})):
            with self.subTest(flag=flag, env=env):
                self.assertIsNone(devin_env.data_dir(flag, env))


class ProjectDirTest(unittest.TestCase):
    def test_an_absolute_path_is_returned(self):
        self.assertEqual(devin_env.project_dir({PROJECT_VAR: "/work/repo"}), "/work/repo")

    def test_unusable_values_give_none(self):
        for value in UNUSABLE:
            with self.subTest(value=value):
                self.assertIsNone(devin_env.project_dir({PROJECT_VAR: value}))


class ConfigDirTest(unittest.TestCase):
    def test_the_devin_config_dir_lives_under_home(self):
        self.assertEqual(devin_env.config_dir({HOME_VAR: "/home/x"}), "/home/x/.devin")

    def test_no_home_gives_none(self):
        for value in UNUSABLE:
            with self.subTest(value=value):
                self.assertIsNone(devin_env.config_dir({HOME_VAR: value}))


class IdentityTest(unittest.TestCase):
    def test_devin_exports_no_session_id_so_whoami_refuses(self):
        with self.assertRaises(HarnessError):
            devin_env.identity({AGENT_VAR: "devin_1", PROJECT_VAR: "/work/repo"})


if __name__ == "__main__":
    unittest.main()
