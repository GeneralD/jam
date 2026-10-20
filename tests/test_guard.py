"""Tests for the guard's decision: which edits are denied, and the order in which the steps are tried.

The decision runs over an injected `Effects` record, so every test here uses
fakes that log each call. The real effects (files, claims, git) have their own
tests, and the adapter that feeds the decision has its own too.

The baseline edit passes every step, so it is denied. Each allow test changes
exactly one thing about it, which is how a test shows that its step, and no
other, is what lets the edit through.
"""

from __future__ import annotations

import hashlib
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy

guard = lazy("jam.guard")
repos = lazy("jam.repos")

SID = "aaaa1111-0000-4000-8000-000000000001"
OTHER_SID = "bbbb2222-0000-4000-8000-000000000002"
HOUR = 490000
APP, OTHER, THIRD = "/work/app", "/work/other", "/work/third"
NESTED = "/work/app/vendor/sub"
CONFIG = "/opt/cfg"
TARGET = "/work/other/src/index.ts"
# The repositories of the fake file system: root -> identity. The sibling with a shared name prefix is what a bare `startswith` would confuse.
ROOTS = {
    APP: "/work/app/.git",
    "/work/app2": "/work/app2/.git",
    OTHER: "/work/other/.git",
    THIRD: "/work/third/.git",
    "/work/wt": "/work/app/.git",  # a linked worktree of the first: another root, the same identity
    NESTED: "/work/app/.git/modules/sub",  # a submodule: below the first, with a git directory of its own
    "/opt/cfg2": "/opt/cfg2/.git",
}


def key_of(identity):
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


KEY = key_of(ROOTS[OTHER])


def repo_in(path):
    """The fake repository holding `path`: the one with the longest root that contains it, else None."""
    roots = [root for root in ROOTS if path == root or path.startswith(root + "/")]
    if not roots:
        return None
    root = max(roots, key=len)
    return repos.Repo(root, ROOTS[root])


def named(answer):
    """The fake's reply: a function is called with the arguments, anything else is returned as it is."""
    return answer if callable(answer) else lambda *args: answer


BASELINE = {
    "worker_marked": False,
    "start_recorded": None,
    "resolved": lambda path: path if isinstance(path, str) else None,
    "repo_of": repo_in,
    "pair_claimed": False,
    "hour": HOUR,
    "throttled": False,
    "ignored": False,
    "claim_pair": True,
    "claim_slot": True,
}
# What a denied edit calls, in order: the whole cheap-to-expensive sequence.
EVERYTHING = [
    ("worker_marked", SID),
    ("resolved", TARGET),
    ("resolved", APP),
    ("resolved", CONFIG),
    ("repo_of", APP),
    ("repo_of", TARGET),
    ("pair_claimed", SID, KEY),
    ("hour",),
    ("throttled", HOUR),
    ("ignored", TARGET),
    ("claim_pair", SID, KEY),
    ("claim_slot", HOUR),
]


class Fakes:
    """Effects that log every call as a tuple and answer from `BASELINE`, with some answers replaced."""

    def __init__(self, **answers):
        self.calls = []
        unknown = set(answers) - set(BASELINE)
        if unknown:
            raise AssertionError(f"not an effect: {sorted(unknown)}")
        self.answers = {**BASELINE, **answers}

    def effects(self):
        return guard.Effects(**{name: self._logged(name) for name in BASELINE})

    def _logged(self, name):
        reply = named(self.answers[name])

        def effect(*args):
            self.calls.append((name, *args))
            return reply(*args)

        return effect


def edit(**fields):
    return guard.Edit(**{"session_id": SID, "target": TARGET, "project_dir": APP, "config_dir": CONFIG, **fields})


def decided(edit_=None, **answers):
    fakes = Fakes(**answers)
    return guard.decide(edit() if edit_ is None else edit_, fakes.effects()), fakes.calls


class BaselineTest(unittest.TestCase):
    def test_the_baseline_edit_is_denied_naming_the_root_of_the_other_repository(self):
        denial, _ = decided()
        self.assertEqual(denial, guard.Denial(OTHER))

    def test_every_step_runs_once_in_the_order_cheapest_first(self):
        _, calls = decided()
        self.assertEqual(calls, EVERYTHING)

    def test_the_pair_key_is_sixteen_hex_digits_of_the_hash_of_the_identity_and_not_of_the_root(self):
        _, calls = decided(repo_of=lambda path: repos.Repo("/work/root-a", "/shared/.git") if path == TARGET else repo_in(path))
        self.assertEqual(calls[6], ("pair_claimed", SID, key_of("/shared/.git")))

    def test_the_hour_is_read_once_and_both_slot_steps_use_it(self):
        _, calls = decided()
        self.assertEqual([call for call in calls if call[0] == "hour"], [("hour",)])
        self.assertEqual({call[1] for call in calls if call[0] in ("throttled", "claim_slot")}, {HOUR})


class EarlyStepsTest(unittest.TestCase):
    def test_step_2_a_session_id_that_is_not_an_id_ends_it_before_any_effect(self):
        for bad in ("", "../x", "a/b", "-x", ".hidden", "x" * 65, "a\x00b", None, 5, True, ["a"]):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(decided(edit(session_id=bad)), (None, []))

    def test_step_3_the_worker_mark_allows_before_any_path_work(self):
        # D14-1: the whole-session exemption is this one clause.
        self.assertEqual(decided(worker_marked=True), (None, EVERYTHING[:1]))

    def test_step_3_a_repo_lookup_that_would_raise_is_never_reached_for_a_marked_session(self):
        def boom(path):
            raise AssertionError("repo_of was called")

        self.assertEqual(decided(worker_marked=True, repo_of=boom, resolved=boom, ignored=boom), (None, EVERYTHING[:1]))

    def test_step_4_a_target_that_cannot_be_resolved_allows(self):
        self.assertEqual(decided(resolved=lambda path: None), (None, EVERYTHING[:2]))

    def test_step_4_a_target_that_is_not_a_string_is_handed_to_the_lookup_as_it_is_and_allows(self):
        self.assertEqual(decided(edit(target=None)), (None, [("worker_marked", SID), ("resolved", None)]))


class StartDirectoryTest(unittest.TestCase):
    def test_step_5_without_the_variable_and_without_a_record_there_is_no_start_and_it_allows(self):
        denial, calls = decided(edit(project_dir=None))
        self.assertEqual((denial, calls), (None, EVERYTHING[:2] + [("start_recorded", SID)]))

    def test_step_5_the_record_stands_in_when_the_variable_is_absent_and_is_resolved_like_the_variable(self):
        denial, calls = decided(edit(project_dir=None), start_recorded="/work/app")
        self.assertEqual(denial, guard.Denial(OTHER))
        self.assertEqual(calls[:4], EVERYTHING[:2] + [("start_recorded", SID), ("resolved", APP)])

    def test_step_5_the_variable_beats_the_record_and_the_record_is_not_even_read(self):
        denial, calls = decided(start_recorded=OTHER)
        self.assertEqual(denial, guard.Denial(OTHER))
        self.assertNotIn("start_recorded", [call[0] for call in calls])

    def test_step_5_an_empty_variable_counts_as_absent(self):
        self.assertEqual(decided(edit(project_dir=""), start_recorded=APP)[0], guard.Denial(OTHER))

    def test_step_5_a_start_that_cannot_be_resolved_allows(self):
        denial, calls = decided(resolved=lambda path: None if path == APP else path)
        self.assertEqual((denial, calls), (None, EVERYTHING[:3]))


class ExclusionTest(unittest.TestCase):
    """Step 6 excludes the configuration directory and nothing else: the start directory is not an exclusion (D14-6)."""

    def test_step_6_edits_under_the_config_directory_allow_before_any_repository_is_looked_up(self):
        # D14-3: the config-directory exclusion is this one clause.
        denial, calls = decided(edit(target="/opt/cfg/memory/notes.md"))
        self.assertEqual((denial, calls), (None, [("worker_marked", SID), ("resolved", "/opt/cfg/memory/notes.md"), ("resolved", APP), ("resolved", CONFIG)]))

    def test_step_6_a_sibling_of_the_config_directory_is_not_inside_it(self):
        self.assertEqual(decided(edit(target="/opt/cfg2/x"))[0], guard.Denial("/opt/cfg2"))

    def test_step_6_without_a_config_directory_the_exclusion_is_off_and_nothing_extra_is_resolved(self):
        denial, calls = decided(edit(config_dir=None))
        self.assertEqual(denial, guard.Denial(OTHER))
        self.assertEqual([call for call in calls if call[0] == "resolved"], [("resolved", TARGET), ("resolved", APP)])

    def test_step_6_a_config_directory_that_cannot_be_resolved_excludes_nothing(self):
        self.assertEqual(decided(resolved=lambda path: None if path == CONFIG else path)[0], guard.Denial(OTHER))


class RepositoryTest(unittest.TestCase):
    def test_step_7_a_session_that_started_outside_any_repository_is_never_denied(self):
        # D14-5: silence for a non-git start is this one clause.
        denial, calls = decided(repo_of=lambda path: None if path == APP else repo_in(path))
        self.assertEqual((denial, calls), (None, EVERYTHING[:5]))

    def test_step_7_a_target_outside_any_repository_allows(self):
        self.assertEqual(decided(repo_of=lambda path: repo_in(APP) if path == APP else None), (None, EVERYTHING[:6]))

    def test_step_7_the_same_repository_allows_and_so_does_a_linked_worktree_that_shares_its_identity(self):
        self.assertEqual(decided(edit(target="/work/app2/f.txt"), repo_of=lambda path: repo_in(APP))[0], None)
        denial, calls = decided(edit(target="/work/wt/f.txt"))
        self.assertEqual((denial, calls[-1]), (None, ("repo_of", "/work/wt/f.txt")))

    def test_step_7_repositories_with_different_identities_are_foreign_even_when_one_lies_inside_the_other(self):
        # D14-6: a repository nested below the start directory is its own repository because identity decides, wherever the session started.
        for start in (APP, "/work/app/pkg", "/work/app/vendor"):
            with self.subTest(start=start):
                denial, _ = decided(edit(target=NESTED + "/f.txt", project_dir=start))
                self.assertEqual(denial, guard.Denial(NESTED))

    def test_step_7_the_start_directory_is_no_exclusion_so_an_edit_below_it_is_decided_by_its_repository_alone(self):
        # The reads are the price of step 7; nothing beyond them runs for an edit in the start directory's own repository.
        self.assertEqual(decided(edit(project_dir=OTHER)), (None, EVERYTHING[:2] + [("resolved", OTHER), ("resolved", CONFIG), ("repo_of", OTHER), ("repo_of", TARGET)]))

    def test_step_7_an_edit_of_the_start_directory_itself_is_in_its_repository_and_allows(self):
        calls = [("worker_marked", SID), ("resolved", OTHER), ("resolved", OTHER), ("resolved", CONFIG), ("repo_of", OTHER), ("repo_of", OTHER)]
        self.assertEqual(decided(edit(target=OTHER, project_dir=OTHER)), (None, calls))

    def test_step_7_a_sibling_whose_name_starts_with_the_start_directory_is_another_repository(self):
        denial, _ = decided(edit(target="/work/app2/f.txt"))
        self.assertEqual(denial, guard.Denial("/work/app2"))

    def test_step_7_a_start_directory_that_is_the_file_system_root_is_no_repository_and_allows(self):
        denial, calls = decided(edit(project_dir="/"))
        self.assertEqual((denial, calls[-1]), (None, ("repo_of", "/")))

    def test_step_7_roots_are_never_compared(self):
        same_identity_other_root = lambda path: repos.Repo("/elsewhere", "/work/app/.git") if path == TARGET else repo_in(path)
        self.assertEqual(decided(repo_of=same_identity_other_root)[0], None)


class ClaimStepsTest(unittest.TestCase):
    def test_step_8_a_pair_that_was_claimed_allows_before_the_clock_or_git_is_touched(self):
        self.assertEqual(decided(pair_claimed=True), (None, EVERYTHING[:7]))

    def test_step_9_a_full_hour_allows_before_git_is_asked(self):
        # D14-2: the throttle is the two clauses of steps 9 and 12, over one constant in the claims.
        self.assertEqual(decided(throttled=True), (None, EVERYTHING[:9]))

    def test_step_10_a_path_git_ignores_allows_and_burns_no_claim(self):
        self.assertEqual(decided(ignored=True), (None, EVERYTHING[:10]))

    def test_step_10_a_path_git_cannot_judge_allows_and_burns_no_claim(self):
        self.assertEqual(decided(ignored=None), (None, EVERYTHING[:10]))

    def test_step_10_only_false_goes_on_so_odd_answers_do_not_deny(self):
        for answer in (0, "", [], 1, "no"):
            with self.subTest(answer=answer):
                self.assertIsNone(decided(ignored=answer)[0])

    def test_step_10_git_that_raises_ends_the_run_without_a_claim(self):
        def boom(path):
            raise RuntimeError("git went wrong")

        fakes = Fakes(ignored=boom)
        with self.assertRaises(RuntimeError):
            guard.decide(edit(), fakes.effects())
        self.assertEqual(fakes.calls, EVERYTHING[:10])

    def test_step_11_losing_the_pair_race_allows_without_taking_a_slot(self):
        self.assertEqual(decided(claim_pair=False), (None, EVERYTHING[:11]))

    def test_step_12_having_no_free_slot_allows_after_the_pair_was_taken(self):
        self.assertEqual(decided(claim_slot=False), (None, EVERYTHING))

    def test_step_13_the_denial_carries_the_working_tree_root_of_the_repository(self):
        denial, _ = decided(repo_of=lambda path: repos.Repo("/work/wt-of-other", ROOTS[OTHER]) if path == TARGET else repo_in(path))
        self.assertEqual(denial.root, "/work/wt-of-other")


class Memory:
    """In-memory claims with the semantics of the real ones: create-once pairs and twenty slots an hour."""

    def __init__(self, hour=HOUR):
        self.pairs, self.slots, self.now = set(), {}, hour

    def answers(self):
        return {
            "pair_claimed": lambda sid, key: (sid, key) in self.pairs,
            "claim_pair": self._claim_pair,
            "hour": lambda: self.now,
            "throttled": lambda hour: self.slots.get(hour, 0) >= 20,
            "claim_slot": self._claim_slot,
        }

    def _claim_pair(self, sid, key):
        taken = (sid, key) in self.pairs
        self.pairs.add((sid, key))
        return not taken

    def _claim_slot(self, hour):
        used = self.slots.get(hour, 0)
        self.slots[hour] = min(used + 1, 20)
        return used < 20

    def denied(self, target, sid=SID):
        return decided(edit(session_id=sid, target=target), **self.answers())[0] is not None


class SequenceTest(unittest.TestCase):
    def setUp(self):
        self.memory = Memory()

    def test_a_foreign_edit_is_denied_once_and_the_identical_reissue_passes(self):
        self.assertEqual([self.memory.denied(TARGET), self.memory.denied(TARGET)], [True, False])

    def test_another_file_of_the_same_repository_passes(self):
        self.assertTrue(self.memory.denied(TARGET))
        self.assertFalse(self.memory.denied("/work/other/docs/readme.md"))

    def test_a_repository_nested_below_the_start_directory_is_denied_once_and_the_start_repository_never(self):
        nested = f"{NESTED}/f.txt"
        self.assertEqual([self.memory.denied(nested), self.memory.denied(nested), self.memory.denied(f"{APP}/src/new.ts")], [True, False, False])

    def test_a_second_repository_is_denied_once_more(self):
        self.assertEqual([self.memory.denied(TARGET), self.memory.denied("/work/third/f.txt")], [True, True])

    def test_a_second_session_is_denied_once_for_the_same_repository(self):
        self.assertEqual([self.memory.denied(TARGET), self.memory.denied(TARGET, OTHER_SID), self.memory.denied(TARGET, OTHER_SID)], [True, True, False])

    def test_the_twenty_first_denial_of_an_hour_is_let_through_and_the_next_hour_starts_afresh(self):
        sessions = [f"s{number:03d}" for number in range(22)]
        self.assertEqual([self.memory.denied(TARGET, sid) for sid in sessions[:20]], [True] * 20)
        self.assertEqual([self.memory.denied(TARGET, sid) for sid in sessions[20:]], [False, False])
        self.memory.now += 1
        self.assertTrue(self.memory.denied(TARGET, "fresh"))

    def test_a_denial_that_lost_the_last_slot_to_a_race_has_still_taken_its_pair_so_it_cannot_speak_later(self):
        self.memory.slots[HOUR] = 20
        racing = {**self.memory.answers(), "throttled": False}  # the last slot went between the check of step 9 and the claim of step 12
        self.assertIsNone(decided(edit(), **racing)[0])
        self.memory.now += 1
        self.assertFalse(self.memory.denied(TARGET))


if __name__ == "__main__":
    unittest.main()
