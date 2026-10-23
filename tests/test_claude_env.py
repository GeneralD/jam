"""Tests for the one module that knows the Claude Code environment variable names."""

from __future__ import annotations

import dataclasses
import unittest
from collections.abc import Mapping

import support  # noqa: F401  (puts src/ on sys.path)
from jam.errors import HarnessError

from test_operations import SESSION_ID, lazy

claude_env = lazy("jam.harness.claude_env")
session_module = lazy("jam.session")

# The variable names are spelled out here on purpose: the tests must not depend
# on what the module calls its constants.
SESSION_VAR, JOB_VAR, DATA_VAR = "CLAUDE_CODE_SESSION_ID", "CLAUDE_JOB_DIR", "CLAUDE_PLUGIN_DATA"
TOKEN_VAR, TOKEN = "CLAUDE_CODE_SESSION_ACCESS_TOKEN", "planted-token-value"
PROJECT_VAR, CONFIG_VAR, HOME_VAR = "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR", "HOME"
# Values the directory resolvers must refuse: empty, relative, a control character, the wrong type.
UNUSABLE = ("", "relative/dir", ".", "~/dir", "/a\x00b", None, 5, b"/abs", ["/abs"])


class RecordingEnv(Mapping):
    """A read-only environment that records every key read and refuses to be enumerated."""

    def __init__(self, values):
        self._values = dict(values)
        self.reads = []

    def __getitem__(self, key):
        self.reads.append(key)
        return self._values[key]

    def __iter__(self):
        raise AssertionError("the environment must not be enumerated")

    def __len__(self):
        return len(self._values)


class DataDirTest(unittest.TestCase):
    def test_the_flag_beats_the_environment(self):
        self.assertEqual(claude_env.data_dir("/from/flag", {DATA_VAR: "/from/env"}), "/from/flag")

    def test_the_environment_is_used_without_a_flag(self):
        self.assertEqual(claude_env.data_dir(None, {DATA_VAR: "/from/env"}), "/from/env")

    def test_an_empty_flag_counts_as_absent(self):
        self.assertEqual(claude_env.data_dir("", {DATA_VAR: "/from/env"}), "/from/env")

    def test_neither_gives_none(self):
        for flag, env in ((None, {}), ("", {}), (None, {DATA_VAR: ""})):
            with self.subTest(flag=flag, env=env):
                self.assertIsNone(claude_env.data_dir(flag, env))

    def test_only_the_data_variable_is_read(self):
        env = RecordingEnv({DATA_VAR: "/from/env", TOKEN_VAR: TOKEN, SESSION_VAR: SESSION_ID})
        claude_env.data_dir(None, env)
        self.assertEqual(set(env.reads), {DATA_VAR})


class ProjectDirTest(unittest.TestCase):
    def test_an_absolute_value_is_the_project_directory(self):
        self.assertEqual(claude_env.project_dir({PROJECT_VAR: "/work/app"}), "/work/app")

    def test_anything_that_is_not_an_absolute_string_is_none(self):
        for value in UNUSABLE:
            with self.subTest(value=repr(value)):
                self.assertIsNone(claude_env.project_dir({PROJECT_VAR: value}))
        self.assertIsNone(claude_env.project_dir({}))

    def test_only_the_project_variable_is_read(self):
        env = RecordingEnv({PROJECT_VAR: "/work/app", DATA_VAR: "/var/jam", TOKEN_VAR: TOKEN})
        claude_env.project_dir(env)
        self.assertEqual(set(env.reads), {PROJECT_VAR})


class ConfigDirTest(unittest.TestCase):
    def test_an_absolute_variable_is_the_config_directory_and_beats_home(self):
        self.assertEqual(claude_env.config_dir({CONFIG_VAR: "/opt/cfg", HOME_VAR: "/opt/home"}), "/opt/cfg")

    def test_without_a_usable_variable_it_is_dot_claude_below_home(self):
        for value in (*UNUSABLE, "relative/cfg"):
            with self.subTest(value=repr(value)):
                self.assertEqual(claude_env.config_dir({CONFIG_VAR: value, HOME_VAR: "/opt/home"}), "/opt/home/.claude")
        self.assertEqual(claude_env.config_dir({HOME_VAR: "/opt/home/"}), "/opt/home/.claude")

    def test_with_neither_a_usable_variable_nor_a_usable_home_it_is_none(self):
        for home in UNUSABLE:
            with self.subTest(home=repr(home)):
                self.assertIsNone(claude_env.config_dir({HOME_VAR: home}))
        self.assertIsNone(claude_env.config_dir({}))

    def test_only_the_config_variable_and_home_are_read_and_home_only_as_the_fallback(self):
        env = RecordingEnv({CONFIG_VAR: "/opt/cfg", HOME_VAR: "/opt/home", TOKEN_VAR: TOKEN})
        claude_env.config_dir(env)
        self.assertEqual(env.reads, [CONFIG_VAR])
        fallback = RecordingEnv({HOME_VAR: "/opt/home", TOKEN_VAR: TOKEN})
        claude_env.config_dir(fallback)
        self.assertEqual(set(fallback.reads), {CONFIG_VAR, HOME_VAR})


class IdentityTypeTest(unittest.TestCase):
    def test_identity_is_a_frozen_pair_of_session_id_and_short_id(self):
        identity = session_module.Identity(SESSION_ID, "aaaa1111")
        self.assertEqual([field.name for field in dataclasses.fields(identity)], ["session_id", "id"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.id = "other"


class IdentityTest(unittest.TestCase):
    def test_the_session_id_and_the_job_directory_name_give_the_identity(self):
        env = {SESSION_VAR: SESSION_ID, JOB_VAR: "/jobs/aaaa1111"}
        self.assertEqual(claude_env.identity(env), session_module.Identity(SESSION_ID, "aaaa1111"))

    def test_a_job_directory_the_session_id_does_not_start_with_gives_no_short_id(self):
        # A session started from the shell of a background session inherits that session's job directory (#20).
        for job_dir in ("/jobs/bbbb2222", "/jobs/AAAA1111", "/jobs/aaaa1112", "/jobs/0000-4000"):
            with self.subTest(job_dir=job_dir):
                self.assertIsNone(claude_env.identity({SESSION_VAR: SESSION_ID, JOB_VAR: job_dir}).id)

    def test_there_is_no_short_id_without_a_job_directory(self):
        self.assertEqual(claude_env.identity({SESSION_VAR: SESSION_ID}), session_module.Identity(SESSION_ID, None))

    def test_trailing_slashes_on_the_job_directory_are_tolerated(self):
        # The name is the last path component, not whatever follows the last slash.
        for job_dir in ("/jobs/aaaa1111/", "/jobs/aaaa1111//"):
            with self.subTest(job_dir=job_dir):
                self.assertEqual(claude_env.identity({SESSION_VAR: SESSION_ID, JOB_VAR: job_dir}).id, "aaaa1111")

    def test_the_short_id_is_never_the_front_of_the_session_id(self):
        for extra in ({}, {JOB_VAR: "/jobs/.hidden"}):
            with self.subTest(extra=extra):
                found = claude_env.identity({SESSION_VAR: SESSION_ID, **extra})
                self.assertIsNone(found.id)
                self.assertNotEqual(found.id, SESSION_ID[:8])

    def test_a_job_directory_name_that_is_not_an_id_gives_no_short_id(self):
        for job_dir in ("/jobs/.hidden", "/jobs/-flag", "/jobs/has space", "/jobs/" + "a" * 65, "/", ""):
            with self.subTest(job_dir=job_dir):
                self.assertIsNone(claude_env.identity({SESSION_VAR: SESSION_ID, JOB_VAR: job_dir}).id)

    def test_a_missing_or_malformed_session_id_names_the_variable_and_hides_the_value(self):
        marker = "MARKER-xyz"
        for env in ({}, {SESSION_VAR: ""}, {SESSION_VAR: "has space " + marker}, {SESSION_VAR: "../" + marker}, {SESSION_VAR: marker + "x" * 200}):
            with self.subTest(env=env):
                with self.assertRaises(HarnessError) as caught:
                    claude_env.identity(env)
                self.assertIn(SESSION_VAR, str(caught.exception))
                self.assertNotIn(marker, str(caught.exception))

    def test_no_other_session_variable_is_ever_read_or_shown(self):
        env = RecordingEnv({SESSION_VAR: SESSION_ID, JOB_VAR: "/jobs/aaaa1111", TOKEN_VAR: TOKEN})
        found = claude_env.identity(env)
        self.assertTrue(set(env.reads) <= {SESSION_VAR, JOB_VAR}, env.reads)
        self.assertNotIn(TOKEN, repr(found))
        broken = RecordingEnv({TOKEN_VAR: TOKEN})
        with self.assertRaises(HarnessError) as caught:
            claude_env.identity(broken)
        self.assertTrue(set(broken.reads) <= {SESSION_VAR, JOB_VAR}, broken.reads)
        self.assertNotIn(TOKEN, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
