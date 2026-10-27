"""Checks that the documents record the checks of 2026-10-24: permission modes and messages, stop then remove, the clean install, and the acceptance run.

Same style as test_spawn_docs.py: flattened text, one section at a time, and
both the new wording and the removed wording pinned.
"""

from __future__ import annotations

import unittest

from test_spawn_docs import DECISIONS, README, flat, section

MODES_FACT = '"Cross-session messages and permission modes" under "Plugin platform facts"'


def platform_fact(title):
    """The flattened bullet of "Plugin platform facts" whose bold title starts with `title`."""
    facts = section(DECISIONS, "Plugin platform facts")
    (bullet,) = [flat(part) for part in facts.split("\n- **") if flat(part).startswith(title)]
    return bullet


class PermissionModeTest(unittest.TestCase):
    def test_the_platform_facts_record_that_no_mode_held_a_message(self):
        fact = platform_fact("Cross-session messages and permission modes (observed on 2.1.309, 2026-10-24).**")
        for phrase in (
            "The `SendMessage` tool description says that a session running in a different permission mode holds cross-session messages for its user's approval and may let them expire, and that a `[Cross-session delivery notice]` tells the sender when a session on the same machine holds or refuses one.",
            "a background session in `auto` exchanged messages in both directions with `--bg` workers started in `auto`, `manual`, `acceptEdits`, `plan`, `dontAsk` and `bypassPermissions`",
            "The worker started by jam's `spawn`, which passes no mode, ran in `auto`, the `permissions.defaultMode` of that configuration",
            "The worker started with `manual` ran in what its transcript records as `default`.",
            "No message was held and no `[Cross-session delivery notice]` arrived.",
            'Delivered messages carried `from-mode="prompting"` for five of those modes and `from-mode="bypass"` for `bypassPermissions`',
            "so the harness sorts modes into at least two classes, and a message across them was not held either.",
            "A foreground session was not tried, and what makes a session hold a message is not known.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, fact)

    def test_d2_quotes_the_rule_as_the_tool_description_states_it_and_points_at_the_observation(self):
        d2 = flat(section(DECISIONS, "D2."))
        self.assertIn(f"The `SendMessage` description says that a session in a different permission mode holds a message for its user's approval; between background sessions this was not seen for any mode tried (see {MODES_FACT}).", d2)
        self.assertNotIn("Peers hold a message for approval when their permission modes differ.", d2)
        self.assertNotIn("this was not seen for any mode (see", d2)

    def test_d12_says_a_worker_starts_in_the_default_mode_and_nothing_calls_for_choosing_one(self):
        d12 = flat(section(DECISIONS, "D12."))
        self.assertIn("A mode chosen by the model would bypass the per-tool first-use approval of D8.", d12)
        self.assertIn(f"Without one, a worker starts in the owner's `permissions.defaultMode`, and messages between background sessions flowed both ways for every mode tried (see {MODES_FACT}), so nothing calls for choosing one.", d12)
        self.assertIn("If it is ever exposed, use an owner-visible allowlist that never accepts a bypass-class mode.", d12)
        self.assertNotIn("which mode a worker should get is still an open item", d12)


class StopThenRemoveTest(unittest.TestCase):
    def test_the_platform_facts_record_the_one_leftover_and_the_runs_since(self):
        fact = platform_fact("Stop, then remove (last checked on 2.1.309, 2026-10-24).**")
        for phrase in (
            "Once, `claude stop` followed by `claude rm` printed success while the session stayed in `claude agents` as idle, and a second stop and rm removed it.",
            "It did not recur in five later runs, nor on 2026-10-24, when seven workers were each stopped and removed in one round and a re-list matched the listing taken before they started.",
            "The adapter does not retry: `remove` checks the full listing and reports a session that is still there.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, fact)


class InstallAndAcceptanceTest(unittest.TestCase):
    def test_the_install_fact_records_the_run_against_an_empty_configuration_directory(self):
        fact = platform_fact("Install from the public repository (verified by experiment).**")
        for phrase in (
            "On 2026-10-24 (Claude Code 2.1.309), the add and install commands were run against an empty configuration directory (`CLAUDE_CONFIG_DIR`) and were the whole setup",
            "a print-mode session there ran jam's three SessionStart hooks with exit 0, received the notice, and listed `plugin:jam:jam` as connected with its four tools",
            "The model call then failed because that directory had no login, which is Claude Code's own setup, not jam's.",
            "A recursive comparison with `main` (outside `.git`, `.claude` and `__pycache__`) found only the harness's `.in_use` marker added.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, fact)

    def test_the_acceptance_check_records_each_criterion_and_the_whoami_finding(self):
        check = flat(section(DECISIONS, "Acceptance check (2026-10-24, Claude Code 2.1.309)"))
        for phrase in (
            "The three acceptance criteria of the design issue were checked once, end to end, from a background session in `auto` mode.",
            '- **Installing is the only setup.** See "Install from the public repository" under "Plugin platform facts": the marketplace add and install, run against an empty configuration directory,',
            "were enough for the three SessionStart hooks and the MCP connection, and only the model call needed a login",
            "- **Spawn, prompt, result.** A print-mode session that loaded the installed copy with `--plugin-dir` called `spawn` once through the MCP server, with a prompt that asked the worker to compute a product and send it to the background session by name.",
            "The worker did, and the background session that ran the check received the result as a cross-session message.",
            "Through jam's CLI the background session also spawned a worker itself",
            "a follow-up message reached that worker and was answered",
            "- **The guard denies once per session and repository.** In a print-mode session started in one git repository with the same copy loaded,",
            "the first `Write` to a second git repository outside the configuration directory was denied with the one-time notice, and the same `Write`, re-issued, created the file",
            "- **Found.** In that print-mode session, `whoami` returned its own `session_id` with the short id of the background session whose shell had started it, because the session inherited `CLAUDE_JOB_DIR` (#20). Fixed afterwards: `whoami` reports a null `id` in that case (D12).",
            "Every worker was then stopped and removed, and a re-list matched the listing from before.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, check)

    def test_the_readme_status_points_at_the_acceptance_check(self):
        status = flat(section(README, "Status"))
        self.assertIn('On 2026-10-24 the acceptance criteria were checked end to end on Claude Code 2.1.309 (see "Acceptance check" in `docs/decisions.md`).', status)


class SessionVariablesTest(unittest.TestCase):
    def test_d12_and_the_session_variables_fact_name_the_inherited_job_directory(self):
        d12 = flat(section(DECISIONS, "D12."))
        for phrase in (
            "`id` is the last path component of `CLAUDE_JOB_DIR` when that passes the id check and the session id starts with it, else null.",
            'The short id is never cut from the first 8 characters of the session id: that relation was observed (see "`--session-id` under `--bg`") but is not documented, so it only confirms a name the job directory supplies.',
            "A foreground session started from the shell of a background session inherits that session's `CLAUDE_JOB_DIR`, and the check keeps it from reporting the other session's short id as its own (#20).",
            'The check has a cost. `/clear` gives a background session a new session id (see "Session variables"), and its job directory is expected to keep the old name, so from then on the command run through Bash reports `id` as null where it used to report the right one.',
            "Whether the `list` row's `sessionId` follows `/clear` is unverified, so the fallback below may find no row; the `whoami` description then tells the model that its short id is unknown.",
            "A wrong id is worse than none: the `stop` description relies on it to keep a session from stopping itself, and a peer would use it as an address.",
            "If a later version drops the relation, `id` is null everywhere, and the caller falls back to `list` as below.",
            "so after `/clear`, or `--continue` and `--resume` without an explicit id, the MCP answer may be stale, while the `session_id` from the command run through Bash is always current.",
            "Because `CLAUDE_JOB_DIR` is documented only for background sessions and their shell commands, `id` is null in a foreground session (the check above covers one that inherited a job directory) and not guaranteed over MCP; the caller then matches `session_id` in `list`.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, d12)
        for removed in ("when that passes the id check, else null", "unless that session was started from the shell of a background session and inherited its job directory", '(see "Background session commands") but is not documented', "while the command run through Bash is always current"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, d12)
        fact = platform_fact("Session variables (documented).**")
        self.assertIn("so it is absent in a foreground session unless that session was started from the shell of a background session, which exports it to everything it starts (#20), and not guaranteed to an MCP server", fact)


class OpenItemsTest(unittest.TestCase):
    def test_the_open_items_drop_the_two_answered_questions_and_narrow_the_notice_item(self):
        items = flat(section(DECISIONS, "Open verification items"))
        self.assertIn("with the plugin installed into an empty configuration directory, a later one ran all three SessionStart hooks, the prune among them, once each with exit 0", items)
        self.assertIn('(see "Install from the public repository" under "Plugin platform facts"). An interactive session and the model acting on the notice are still unchecked.', items)
        for removed in (
            "Which permission mode should `spawn` give a worker",
            "once printed success while the session stayed in `claude agents` as idle",
            "an interactive session, the model acting on the notice, and the prune are still unchecked",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, items)


if __name__ == "__main__":
    unittest.main()
