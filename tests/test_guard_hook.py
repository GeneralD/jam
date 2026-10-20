"""Tests for the guard handler: how a PreToolUse call is read, where the session started, and which repositories count.

Real temporary repositories, hand-built; git is replaced (see guardcase.py). The
state files, the throttle and the failure modes are in test_guard_state.py.
"""

from __future__ import annotations

import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from guardcase import CONFIG_VAR, CONTENT, HOME_VAR, MISSING, PROJECT_VAR, GuardCase
from test_operations import SESSION_ID, lazy

hooks = lazy("jam.harness.claude_hooks")


def call(tool, tool_input, **fields):
    return {"tool_name": tool, "tool_input": tool_input, "cwd": "/work/app", **fields}


class EditTargetTest(unittest.TestCase):
    """The reading of a tool call, alone: where the path sits, and what is made of a relative one."""

    def test_each_editing_tool_names_its_file_in_the_documented_field(self):
        self.assertEqual(hooks.edit_target(call("Write", {"file_path": "/work/x"})), "/work/x")
        self.assertEqual(hooks.edit_target(call("Edit", {"file_path": "/work/x"})), "/work/x")
        self.assertEqual(hooks.edit_target(call("MultiEdit", {"file_path": "/work/x"})), "/work/x")
        self.assertEqual(hooks.edit_target(call("NotebookEdit", {"notebook_path": "/work/n", "file_path": "/work/x"})), "/work/n")
        self.assertEqual(hooks.edit_target(call("NotebookEdit", {"file_path": "/work/x"})), "/work/x")
        self.assertIsNone(hooks.edit_target(call("Write", {"notebook_path": "/work/n"})))

    def test_a_relative_path_is_joined_to_the_working_directory_only_when_that_is_absolute(self):
        self.assertEqual(hooks.edit_target(call("Write", {"file_path": "src/a.ts"})), "/work/app/src/a.ts")
        for cwd in (None, "", "relative", "./x", 5, ["/work"], "/work\0"):
            with self.subTest(cwd=repr(cwd)):
                self.assertIsNone(hooks.edit_target(call("Write", {"file_path": "src/a.ts"}, cwd=cwd)))

    def test_what_is_not_a_usable_path_is_none(self):
        for value in (None, "", 5, ["/work/x"], {"a": 1}, "/work/x\0", "x\0"):
            with self.subTest(value=repr(value)):
                self.assertIsNone(hooks.edit_target(call("Write", {"file_path": value})))

    def test_what_is_not_an_editing_tool_call_is_none(self):
        for payload in ({}, call("Bash", {"file_path": "/work/x"}), call("write", {"file_path": "/work/x"}), call("Write", None), call("Write", [], cwd=None), {"tool_input": {"file_path": "/work/x"}}):
            with self.subTest(payload=payload):
                self.assertIsNone(hooks.edit_target(payload))


class TargetTest(GuardCase):
    def test_a_write_to_another_repository_is_denied(self):
        self.assertDenied(self.guarded(), self.other)

    def test_an_edit_is_read_through_file_path_as_a_write_is(self):
        self.assertDenied(self.guarded({"file_path": self.target, "old_string": "a", "new_string": "b"}, tool="Edit"), self.other)

    def test_a_multi_edit_is_read_through_file_path_and_one_without_it_allows(self):
        # Nothing here depends on the platform firing for MultiEdit: this is only how a payload of that name is read.
        self.assertDenied(self.guarded({"file_path": self.target, "edits": []}, tool="MultiEdit", session_id=self.fresh()), self.other)
        self.assertSilent(self.guarded({"edits": [{"old_string": "a", "new_string": "b"}]}, tool="MultiEdit", session_id=self.fresh()))

    def test_a_notebook_edit_is_read_through_notebook_path_and_then_file_path(self):
        self.assertDenied(self.guarded({"notebook_path": self.target, "new_source": "x = 1"}, tool="NotebookEdit", session_id=self.fresh()), self.other)
        self.assertDenied(self.guarded({"file_path": self.target, "new_source": "x = 1"}, tool="NotebookEdit", session_id=self.fresh()), self.other)

    def test_for_a_notebook_edit_the_notebook_path_wins_over_the_file_path(self):
        inside = str(self.app / "nb.ipynb")
        self.assertSilent(self.guarded({"notebook_path": inside, "file_path": self.target}, tool="NotebookEdit"))
        self.assertDenied(self.guarded({"notebook_path": self.target, "file_path": inside}, tool="NotebookEdit"), self.other)

    def test_a_tool_that_does_not_edit_a_file_is_ignored_whatever_it_carries(self):
        for tool in ("Bash", "Read", "Glob", "write", "", None, 5, ["Write"], {"a": 1}):
            with self.subTest(tool=tool):
                self.assertSilent(self.guarded({"file_path": self.target, "command": "touch x"}, tool=tool))

    def test_a_tool_input_that_is_not_an_object_or_is_missing_allows(self):
        for tool_input in (None, "x", [], [self.target], 5, True, MISSING):
            with self.subTest(tool_input=repr(tool_input)):
                self.assertSilent(self.guarded(tool_input))

    def test_a_path_that_is_missing_empty_not_a_string_or_holding_nul_allows(self):
        for value in (None, "", 5, ["x"], {"a": 1}, self.target + "\0", "\0"):
            with self.subTest(value=repr(value)):
                self.assertSilent(self.guarded({"file_path": value}))
        self.assertSilent(self.guarded({"content": CONTENT}))

    def test_a_relative_path_is_joined_to_an_absolute_working_directory(self):
        self.assertDenied(self.guarded({"file_path": "src/index.ts"}, cwd=str(self.other), session_id=self.fresh()), self.other)
        self.assertDenied(self.guarded({"file_path": "../other/src/index.ts"}, cwd=str(self.app), session_id=self.fresh()), self.other)

    def test_a_relative_path_without_a_usable_working_directory_allows(self):
        for cwd in (None, "", "relative/dir", 5, ["x"], str(self.other) + "\0"):
            with self.subTest(cwd=repr(cwd)):
                self.assertSilent(self.guarded({"file_path": "src/index.ts"}, cwd=cwd))

    def test_a_missing_working_directory_is_no_problem_for_an_absolute_path(self):
        self.assertDenied(self.guarded(cwd=None), self.other)

    def test_a_subagent_is_guarded_like_any_other_session(self):
        # D14-4: nothing reads agent_id, so there is no clause to remove.
        self.assertDenied(self.guarded(agent_id="agent-1", agent_type="Explore"), self.other)

    def test_a_link_inside_the_start_repository_does_not_hide_the_repository_it_leads_to(self):
        (self.app / "shortcut").symlink_to(self.other)
        self.assertDenied(self.write_to(self.app / "shortcut" / "src" / "index.ts"), self.other)

    def test_a_target_that_does_not_exist_and_whose_directories_do_not_exist_either_is_still_placed(self):
        self.assertDenied(self.write_to(self.other / "a" / "b" / "c" / "new.txt"), self.other)


class StartDirectoryTest(GuardCase):
    def test_the_variable_beats_the_record_when_both_exist_and_differ(self):
        self.record_start(SESSION_ID, self.other)  # were it used, the edit would be in the start repository
        self.assertDenied(self.guarded(), self.other)

    def test_the_record_stands_in_when_the_variable_is_unset_empty_or_relative(self):
        for index, value in enumerate((None, "", "relative/dir")):
            session_id = f"session-{index}"  # a session is denied once per repository, so each case is a session of its own
            self.record_start(session_id, self.app)
            with self.subTest(value=value):
                self.assertDenied(self.guarded(env={PROJECT_VAR: value}, session_id=session_id), self.other)

    def test_without_a_variable_and_without_a_record_the_guard_stays_silent(self):
        self.assertSilent(self.guarded(env={PROJECT_VAR: None}))

    def test_a_record_without_its_line_feed_reads_as_absent(self):
        self.record_start(SESSION_ID, self.app, ending="")
        self.assertSilent(self.guarded(env={PROJECT_VAR: None}))

    def test_a_record_of_a_relative_path_reads_as_absent(self):
        self.record_start(SESSION_ID, "app")
        self.assertSilent(self.guarded(env={PROJECT_VAR: None}))

    def test_the_working_directory_of_the_call_is_never_taken_for_the_start_directory(self):
        self.assertDenied(self.guarded(cwd=str(self.other)), self.other)  # the shell moved into the other repository; the session did not
        self.assertSilent(self.guarded(env={PROJECT_VAR: None}, cwd=str(self.app)))  # and with no start known, a working directory is no help

    def test_a_start_reached_through_a_link_is_compared_by_its_real_path(self):
        (self.root / "applink").symlink_to(self.app)
        self.assertSilent(self.write_to(self.app / "notes.txt", env={PROJECT_VAR: str(self.root / "applink")}))

    def test_an_edit_in_the_start_directorys_own_repository_allows_without_asking_git(self):
        self.assertSilent(self.write_to(self.app / "src" / "new.ts"))
        self.assertSilent(self.write_to(self.app / "README.md"))
        self.ignored.assert_not_called()


class RepositoryTest(GuardCase):
    def test_a_start_in_a_subdirectory_of_the_same_repository_allows(self):
        (self.app / "pkg").mkdir()
        self.assertSilent(self.write_to(self.app / "docs" / "readme.md", env={PROJECT_VAR: str(self.app / "pkg")}))

    def test_a_start_in_a_linked_worktree_of_the_target_repository_allows_and_so_does_the_reverse(self):
        worktree = self.linked_worktree(self.other, "wt")
        self.assertSilent(self.guarded(env={PROJECT_VAR: str(worktree)}))
        self.assertSilent(self.write_to(worktree / "f.txt", env={PROJECT_VAR: str(self.other)}))

    def test_a_session_that_started_outside_any_repository_is_never_denied(self):
        # D14-5: silence for a non-git start is one clause of the decision.
        loose = self.root / "loose"
        loose.mkdir()
        self.assertSilent(self.guarded(env={PROJECT_VAR: str(loose)}))

    def test_a_target_outside_any_repository_allows(self):
        self.assertSilent(self.write_to(self.root / "loose" / "notes.txt"))

    def test_a_submodule_is_its_own_repository(self):
        # D14-6: identity is the git directory, and a submodule's has no commondir.
        top = self.plain("top")
        gitdir = top / ".git" / "modules" / "sub"
        gitdir.mkdir(parents=True)
        sub = top / "vendor" / "sub"
        sub.mkdir(parents=True)
        (sub / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        self.assertDenied(self.write_to(top / "README.md", env={PROJECT_VAR: str(sub)}), top)
        self.assertDenied(self.write_to(sub / "lib.c", env={PROJECT_VAR: str(top / "pkg")}), sub)

    def test_a_submodule_is_foreign_to_a_session_that_started_at_the_superproject_root_as_it_is_to_one_that_started_beside_it(self):
        # D14-6 does not depend on where in the superproject the session started.
        top = self.plain("top")
        gitdir = top / ".git" / "modules" / "sub"
        gitdir.mkdir(parents=True)
        sub = top / "vendor" / "sub"
        sub.mkdir(parents=True)
        (sub / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        self.assertDenied(self.write_to(sub / "lib.c", env={PROJECT_VAR: str(top)}, session_id=self.fresh()), sub)
        self.assertDenied(self.write_to(sub / "lib.c", env={PROJECT_VAR: str(top / "pkg")}, session_id=self.fresh()), sub)
        self.assertSilent(self.write_to(top / "README.md", env={PROJECT_VAR: str(top)}, session_id=self.fresh()))

    def test_a_nested_clone_below_the_start_directory_is_foreign_and_the_rest_of_the_start_repository_is_not(self):
        nested = self.app / "vendor" / "lib"
        (nested / ".git").mkdir(parents=True)
        (self.app / "pkg").mkdir()
        self.assertDenied(self.write_to(nested / "src" / "x.c", session_id=self.fresh()), nested)
        self.assertSilent(self.write_to(self.app / "vendor" / "notes.md", session_id=self.fresh()))
        self.assertSilent(self.write_to(self.app / "src" / "x.c", session_id=self.fresh()))
        self.assertDenied(self.write_to(nested / "src" / "x.c", env={PROJECT_VAR: str(self.app / "pkg")}, session_id=self.fresh()), nested)

    def test_a_nested_repository_that_git_ignores_stays_quiet_and_burns_no_claim(self):
        nested = self.app / "vendor" / "lib"
        (nested / ".git").mkdir(parents=True)
        self.ignored.return_value = True
        self.assertSilent(self.write_to(nested / "src" / "x.c"))
        self.assertEqual(self.claim_files(), [])

    def test_an_unreadable_or_damaged_repository_marker_allows(self):
        broken = self.pointer(b"not a pointer", name="broken")
        self.assertSilent(self.write_to(broken / "f.txt"))
        self.assertSilent(self.write_to(self.other / "f.txt", env={PROJECT_VAR: str(broken)}))

    def test_an_edit_in_the_same_repository_as_the_start_allows(self):
        self.assertSilent(self.write_to(self.app / "other-dir" / "f.txt", env={PROJECT_VAR: str(self.app)}))


class ConfigDirectoryTest(GuardCase):
    def test_edits_under_the_config_directory_allow_even_when_it_is_a_repository(self):
        # D14-3: the exclusion is one clause of the decision.
        config = self.plain("cfg")
        self.assertSilent(self.write_to(config / "memory" / "notes.md", env={CONFIG_VAR: str(config)}))

    def test_without_the_variable_the_directory_is_dot_claude_below_home(self):
        home = self.root / "home"
        config = home / ".claude"
        (config / ".git").mkdir(parents=True)
        self.assertSilent(self.write_to(config / "plans" / "plan.md", env={HOME_VAR: str(home)}))

    def test_a_relative_variable_falls_back_to_the_home_default(self):
        home = self.root / "home"
        (home / ".claude" / ".git").mkdir(parents=True)
        self.assertSilent(self.write_to(home / ".claude" / "x.md", env={CONFIG_VAR: "relative/cfg", HOME_VAR: str(home)}))

    def test_the_same_file_is_denied_when_the_config_directory_is_somewhere_else(self):
        config = self.plain("cfg")
        self.assertDenied(self.write_to(config / "memory" / "notes.md", env={CONFIG_VAR: str(self.root / "elsewhere")}), config)

    def test_a_sibling_of_the_config_directory_is_not_inside_it(self):
        config = self.plain("cfg")
        sibling = self.plain("cfg2")
        self.assertDenied(self.write_to(sibling / "x.md", env={CONFIG_VAR: str(config)}), sibling)

    def test_with_neither_variable_nothing_is_excluded(self):
        config = self.plain("cfg")
        self.assertDenied(self.write_to(config / "x.md", env={HOME_VAR: None, CONFIG_VAR: None}), config)


if __name__ == "__main__":
    unittest.main()
