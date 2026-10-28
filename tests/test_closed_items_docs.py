"""Checks that the documents record the four checks of 2026-10-28 that closed the open verification items: the notice in an interactive session, the PATH inside a worker, a foreground session's listing and wake, and a resume that keeps the id; and the `/clear` point of D12 that the same runs settled.

Same style as test_verification_docs.py: flattened text, one section at a time,
and both the new wording and the removed wording pinned. Every claim is scoped
to what the runs showed, so the scope words are pinned with it.
"""

from __future__ import annotations

import re
import unittest

from test_spawn_docs import DECISIONS, README, ROOT, flat, section
from test_verification_docs import platform_fact

MODES_FACT = '"Cross-session messages and permission modes" under "Plugin platform facts"'


class PinnedTest(unittest.TestCase):
    def assertHolds(self, text, present, absent=()):
        for phrase in present:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        for phrase in absent:
            with self.subTest(removed=phrase):
                self.assertNotIn(phrase, text)


class ForegroundSessionTest(PinnedTest):
    def test_the_messages_fact_records_the_foreground_session_that_woke(self):
        fact = platform_fact("Cross-session messages and permission modes (observed on 2.1.309, 2026-10-24 and 2026-10-28).**")
        self.assertHolds(
            fact,
            (
                "In the first check (2026-10-24), a background session in `auto` exchanged messages in both directions with `--bg` workers",
                "A foreground session was tried once, on 2026-10-28: an idle interactive session in `auto`, started in a tmux session of its own and also connected through Remote Control, was sent a message by name from a `--bg` worker started without a permission-mode flag (a worker started that way ran in `auto` on 2026-10-24; its mode and the `from-mode` of the delivered message were not recorded in this run).",
                "`SendMessage` reported success, with the message in the session's inbox and not yet read, and the foreground session then woke on its own, read it and replied. No message was held.",
                "It was one run in a tmux pane; a plain terminal and a zellij pane were not tried, nor was a foreground session in another mode, and what makes a session hold a message is not known.",
            ),
            (
                "A foreground session was not tried, and what makes",
                "In this check, a background session",
                "(workers started that way ran in `auto`)",
                "A foreground session in another mode was not tried, and what makes",
            ),
        )

    def test_d2_points_at_that_fact_instead_of_calling_the_wake_unverified(self):
        d2 = flat(section(DECISIONS, "D2."))
        self.assertHolds(
            d2,
            (
                f"A foreground terminal session was tried later, and a worker's message woke it (it ran in a tmux pane; see {MODES_FACT}); a plain terminal and a zellij pane were not tried.",
                "The owner had decided that whether one can be woken does not matter",
            ),
            ("Not verified: a foreground terminal session", "The owner decided that this does not matter"),
        )

    def test_the_agents_listing_fact_records_the_row_of_a_foreground_session(self):
        fact = platform_fact("Background session commands (observed on 2.1.300 and 2.1.309).**")
        self.assertHolds(
            fact,
            (
                "The rows of `claude agents --json` for background sessions have `id`, `sessionId`, `name`, `cwd`, `kind`, `startedAt`, `state`,",
                "The help text says the plain listing also includes interactive sessions, and it did on 2.1.309 (2026-10-28): a foreground session is a row with `kind: interactive` and `pid`, `cwd`, `startedAt`, `sessionId`, `name` and `status`, but no `id` and no `state`.",
                "A row once came back without `id`; it may have been such a row, but the cause was not established. The adapter skips a row without a usable id, so `list` and `stop` do not reach a foreground session, and the native `ListAgents` shows it by name.",
                "The `state` seen right after a stop was `stopped` in two runs and `done` in a third; on 2.1.309 (2026-10-28) it was `done` for two sessions that had finished a turn and `stopped` for two copies that never started one. It is treated as a pass-through string.",
            ),
            (
                "but only background ones have been seen",
                "Once, a row came back without `id`;",
                "most likely such a row",
                "`claude agents --json` rows have `id`",
                "`stopped` in two runs and `done` in a third, so it is treated as a pass-through string",
            ),
        )

    def test_d4_and_the_readme_say_a_foreground_row_has_no_id_and_is_not_managed(self):
        d4 = flat(section(DECISIONS, "D4."))
        self.assertHolds(
            d4,
            (
                "(visible in `claude agents` with an `id`)",
                f"A foreground session shows up there as a row without an `id`, which jam skips; in the one check made, a worker's message woke one all the same (see {MODES_FACT}).",
            ),
            ("(visible in `claude agents`)", "wakes it all the same"),
        )
        self.assertHolds(
            flat(README),
            ("so they show up in `claude agents` with an `id`. A foreground session shows up there without one, so jam does not list or stop it, although a worker's message woke one in the one check made (D2).",),
            ("so they show up in `claude agents`. It does not",),
        )

    def test_d11_sweeps_by_age_because_a_foreground_row_has_no_id(self):
        d11 = flat(section(DECISIONS, "D11."))
        self.assertHolds(
            d11,
            ('By file age only (30 days), not against the harness listing: the foreground session tried appeared in `claude agents` only as a row without an `id` (see "Background session commands" under "Plugin platform facts"), yet `adopt` wrote a start record for it (D14; the record stayed after the session exited, and no worker mark was made because no ticket was waiting), and a listing-based sweep could delete the files of live sessions it cannot match.',),
            (
                "whether foreground sessions appear in `claude agents` is unverified",
                "the notes of live sessions it cannot match",
                "a foreground session appears in `claude agents` only as a row without an `id`",
                "yet `adopt` writes a start record for it",
            ),
        )

    def test_d13_records_the_interactive_session_with_the_instruction_the_model_had(self):
        d13 = flat(section(DECISIONS, "D13."))
        self.assertHolds(
            d13,
            (
                "- **Partly verified.** No session was started to test this change itself.",
                "A later print-mode session (`claude -p --plugin-dir .`, 2026-10-21) ran the notice at `startup` and returned its `additionalContext`.",
                "An interactive session (`claude --plugin-dir .` in a trusted directory, not `--bg`, in a private tmux server with the `CLAUDE_*` variables of the parent session unset; 2026-10-28, Claude Code 2.1.309) ran all three SessionStart hooks once each at `startup`, the prune among them, each finishing with status 0, and the notice arrived as a `hook_success` attachment carrying its `additionalContext`.",
                "The debug log, started with `--debug-file` with a second logging plugin loaded, reported 211, 212 and 213 ms for the three jam hooks; the other hooks, a tiny shell script among them, reported 210 to 221 ms, so about 0.21 seconds is an upper bound shared by hooks that start together, not a measure of any one of them.",
                "The model (Sonnet 5.5 at `xhigh` effort, in `auto` mode) was told to rely only on the notice (no MCP tool, no filesystem search) and to run `whoami` from the shell, and its first tool call was `whoami` through Bash in the form the notice gives.",
                "So the run shows that the model copied the form the notice gives, not that the notice made it choose the command.",
                "`id` was null, as D12 says it is in a foreground session: `CLAUDE_JOB_DIR` was unset there, as in a terminal outside any background session.",
                "The model's own explanation of the null was wrong (it said the session was not started by `spawn`), and the notice does not explain a null `id`; the `whoami` tool description does.",
                "It was one run, so it does not show that a model left to choose would use the notice unprompted.",
            ),
            (
                "about 0.21 seconds for each of the three jam hooks",
                "which ran in parallel",
                "(the run had no `CLAUDE_JOB_DIR`)",
                "It was one run (one model, in `auto` mode)",
                "in a tmux session of its own; 2026-10-28, Claude Code 2.1.309) ran all three",
                "- **Verified later.** No session was started",
                "The hooks' timings in a real session are not measured",
                "first and only tool call",
                "with no MCP tool and no search for the CLI",
                "Still open, and listed under",
                "the one owner check",
            ),
        )

    def test_the_readme_status_says_a_model_told_to_rely_on_the_notice_ran_its_command(self):
        status = flat(section(README, "Status"))
        self.assertHolds(
            status,
            ("On 2026-10-28 an interactive `claude --plugin-dir .` session, started in a trusted directory and not as a background session (`--bg`), ran the three hooks, and a model told to rely on the notice alone, and asked to run `whoami`, ran it in the form the notice gives (D13).",),
            ("acted on the notice", "The one check left to the owner", "rely on the notice alone ran the command it gives"),
        )


class PathInsideAWorkerTest(PinnedTest):
    def test_d12_records_that_claude_was_on_the_path_of_a_server_inside_a_worker_in_that_run(self):
        d12 = flat(section(DECISIONS, "D12."))
        self.assertHolds(
            d12,
            (
                "On 2026-10-28 (Claude Code 2.1.309) the server inside a `--bg` worker also answered `list`, which starts `claude` by its bare name, so in that run `claude` was on the PATH of an MCP server in a worker, on that machine.",
                "A worker's environment comes from the supervisor, not from the spawning shell, and how the supervisor was started was not recorded, so a machine whose supervisor starts with a narrower PATH may still fail.",
                "A failure reads \"cannot run 'claude': executable not found\"; add a binary override only if it happens.",
            ),
            ('Still open (also listed under "Open verification items"): `claude` being on the PATH', "so `claude` is on the PATH of an MCP server in a worker, on that machine."),
        )


class ResumeTest(PinnedTest):
    def test_the_resume_fact_records_the_pauses_tried_the_flag_tried_and_what_the_hook_saw(self):
        fact = platform_fact("Resuming a background session (observed on 2.1.300 and 2.1.309).**")
        self.assertHolds(
            fact,
            (
                "On 2.1.300, `claude --bg --resume <id>` with `--plugin-dir`, `--model`, `--permission-mode`, `--disallowedTools` and a prompt added, run right after `claude stop <id>` had printed `stopped <id>` and with no listing read in between, printed `note: session <id> is already running in the background, so this started a copy as <new id>`.",
                "The copy's session start reported `source: fork` with a new session id, and had the same `cwd`, `CLAUDE_PROJECT_DIR` and `CLAUDE_CONFIG_DIR` as the original. The form without those flags was not tried on 2.1.300.",
                "On 2.1.309 (2026-10-28), a resume with no other flag, run within about 3 seconds of a stop, started a copy with the same note, twice, once after a plain listing had been read in between.",
                "Neither copy ran a turn or left a transcript; the session-start log showed nothing for the first copy and was not read for the second, so their `source` was not seen.",
                "After a pause of 20 seconds or more (about 20, 20, 44 and 65 seconds were tried), the same command with no other flag woke the same session: the note said it was woken with its saved options (`--plugin-dir`, `-n` and `--model`), the id was kept, and the session start reported `source: resume`, although the woken session ran no turn and was listed as idle.",
                "No resume with no other flag was tried between 3 and 20 seconds after a stop.",
                "With `--plugin-dir` and a prompt added, the only flag variant tried on 2.1.309, run about 8 seconds after a stop, the note said that the background session keeps its own saved options, so the flags passed started a copy under a new id, and the copy reported `source: fork`; the note named the flags, not the timing, and no other flag was tried.",
                "The SessionStart hook of a resumed session saw the `cwd`, `CLAUDE_PROJECT_DIR` and `CLAUDE_CONFIG_DIR` of the session's start, not the caller's, in two runs: in one the caller ran from a subdirectory; in the other it set `CLAUDE_CONFIG_DIR` with a trailing slash (the same directory, spelled another way) and another `CLAUDE_PROJECT_DIR` together. Neither variable was changed alone, and a different configuration directory was not tried.",
            ),
            (
                "in separate runs",
                "none between 3 and 20",
                "neither copy had started a turn, so no session start",
                "the only variant tried, the note",
                "On 2.1.300, `claude --bg --resume <id>`, run right after",
                "it was started from the same directory, so this does not tell whether they are inherited",
                "A resume that keeps the id has not been seen for a background session.",
                "after a pause of about 15 to 20 seconds",
                "With any other flag",
                "among them), the id was kept",
            ),
        )

    def test_d14_says_what_a_resume_that_keeps_the_id_showed_and_what_it_did_not(self):
        d14 = flat(section(DECISIONS, "D14."))
        self.assertHolds(
            d14,
            (
                'One point stays open: the skip of `resume` and `fork` itself, which only unit tests cover; real sessions have reported the sources `resume`, `fork` and `clear` (see "Resuming a background session" and "Session variables" under "Plugin platform facts").',
                'On a resume that keeps the id, the SessionStart hook saw `CLAUDE_PROJECT_DIR` and `CLAUDE_CONFIG_DIR` with the values of the session\'s start even when the caller\'s working directory, project directory or spelling of the configuration directory differed (see "Resuming a background session"), so the guard is expected to keep the start repository and configuration directory there; no guarded edit was made in a resumed session.',
                "So registration did not wait for that point,",
                'while `/clear` and a fork get a new id and so start without one. On 2.1.309 a `claude --bg --resume` with no other flag, run 20 seconds or more after a stop, kept the id; one with `--plugin-dir` and a prompt added (the only flag variant tried), and one run within about 3 seconds of a stop, started a copy with a new id. jam\'s marks were not part of those runs (see "Resuming a background session" under "Plugin platform facts").',
                "The one resume tried then, `claude --bg --resume` from the same directory with `--plugin-dir`, `--model`, `--permission-mode`, `--disallowedTools` and a prompt added, started a copy with a new id, which had the same values;",
                'a resume that keeps the id was seen later, and its SessionStart hook saw the values of the session\'s start (see "Resuming a background session" under "Plugin platform facts").',
            ),
            (
                "a `claude --bg --resume` with no other flag kept the id, and one with a flag, or run right after a stop,",
                "The one resume tried then, `claude --bg --resume` from the same directory, started a copy",
                "Two points stay open",
                "If `CLAUDE_PROJECT_DIR` or `CLAUDE_CONFIG_DIR` differs on a resume that keeps the id",
                "did not wait for either",
                "whatever the caller's were",
                "so the guard does not take another start repository",
                "the one `claude --bg --resume` tried started a copy with a new id",
                "a resume that keeps the id was not seen",
            ),
        )

    def test_the_hook_source_comment_names_what_the_runs_of_2026_10_28_reported(self):
        source = (ROOT / "src" / "jam" / "harness" / "claude_hooks.py").read_text(encoding="utf-8")
        comment = flat(re.sub(r"^#\s?", "", source, flags=re.MULTILINE))
        self.assertIn("A resume with no other flag, made 20 seconds or more after a stop, kept the id and reported `resume`, and `/clear` reported `clear` (2026-10-28, D14); an unknown source takes one.", comment)
        self.assertNotIn("A resume with no other flag kept the id", comment)


class ClearTest(PinnedTest):
    def test_the_session_variables_fact_records_what_clear_did_in_a_background_session(self):
        fact = platform_fact("Session variables (documented; observed on 2.1.309).**")
        self.assertHolds(
            fact,
            (
                "Observed in a background session on 2.1.309 (2026-10-28): after `/clear`, `CLAUDE_CODE_SESSION_ID` in Bash held a new id and the job directory kept its name, so `jam whoami` through Bash reported the new `session_id` with a null `id`; the session start reported `source: clear` with the new id,",
                "and the session's row in `claude agents --json` kept its `id` and held the new `sessionId` in the first listing read after it, about 4 seconds later (one session, attached in a terminal).",
            ),
            ("by the next listing, a few seconds later",),
        )

    def test_d12_says_the_fallback_finds_the_row_and_a_foreground_session_has_none(self):
        d12 = flat(section(DECISIONS, "D12."))
        self.assertHolds(
            d12,
            (
                'The check has a cost. `/clear` gives a background session a new session id and its job directory keeps the old name (see "Session variables"), so from then on the command run through Bash reports `id` as null where it used to report the right one.',
                'In the one check made (a background session attached in a terminal), the `list` row kept its `id` and held the new `sessionId` in the first listing read, about 4 seconds after the `/clear` was sent (see "Session variables"), so the fallback below found the row; the id an MCP server sees after `/clear` was not checked. Where no row matches, the `whoami` description tells the model that its short id is unknown.',
                "The foreground session tried (2026-10-28) had no row there: `claude agents` listed it without an `id`, which `list` skips, so for it the match finds nothing; it has no short id, and `whoami` leaves `id` null.",
            ),
            (
                "is expected to keep the old name",
                "is unverified, so the fallback below may find no row",
                "its short id stays unknown. Reading",
                'The `list` row keeps its `id` and takes the new `sessionId`',
                "A foreground session has no row there",
            ),
        )


class OpenItemsTest(PinnedTest):
    def test_the_section_says_the_four_items_are_closed_and_names_what_is_still_unverified(self):
        items = flat(section(DECISIONS, "Open verification items"))
        self.assertHolds(
            items,
            (
                'None from the list of 2026-10-24: its four items were checked on 2026-10-28 (Claude Code 2.1.309), and the results are in D2, D11, D12, D13, D14 and "Plugin platform facts". Points that are still unverified are named where they occur, among them the skip of `resume` and `fork` by `adopt` (D14), the notice being used by a model that is not told to rely on it (D13), a foreground session in a permission mode other than `auto`, in a plain terminal or in a zellij pane ("Cross-session messages and permission modes" under "Plugin platform facts"), and a resume under a different configuration directory ("Resuming a background session" under "Plugin platform facts").',
            ),
            (
                "Does a real session loaded with",
                "Is `claude` on the PATH of a jam MCP server",
                "Interactive (foreground) sessions: do they appear",
                "A resume of a background session that keeps its id",
                "Which permission mode should `spawn` give a worker",
                "once printed success while the session stayed in `claude agents` as idle",
                "are still unchecked",
            ),
        )

    def test_no_other_passage_sends_the_reader_to_an_item_that_is_gone(self):
        text = flat(DECISIONS)
        self.assertNotIn('see "Open verification items"', text)
        self.assertNotIn('under "Open verification items"', text)


if __name__ == "__main__":
    unittest.main()
