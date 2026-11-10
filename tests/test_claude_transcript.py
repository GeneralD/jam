"""Tests for reading a Claude Code transcript for `peek`. The records mirror the shapes observed on 2.1.309, with generic text."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts src/ on sys.path)
from jam.harness import claude_transcript
from jam.session import Session, Turn

SESSION_ID = "aaaa1111-0000-4000-8000-000000000001"
AT = "2026-11-09T10:00:00.000Z"
LATER = "2026-11-09T10:05:00.000Z"
CARRIED = "text-that-must-stay-behind"


def human(text, at=AT, **extra):
    return {"type": "user", "origin": {"kind": "human"}, "isSidechain": False, "message": {"role": "user", "content": text}, "timestamp": at, **extra}


def old_prompt(text, at=AT):
    """A prompt as Claude Code wrote it before `origin` existed (seen up to 2.1.277)."""
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": text}, "timestamp": at}


def peer(body, at=AT):
    return {
        "type": "user",
        "isMeta": True,
        "origin": {"kind": "peer", "body": body, "from": "/tmp/sock", "name": "worker-a"},
        "message": {"role": "user", "content": "Another Claude session sent this: " + CARRIED},
        "timestamp": at,
    }


def queued(prompt, kind="human", at=AT, **origin):
    """A message that reached a busy session: written as an attachment, not as a prompt (seen on 2.1.309)."""
    return {
        "type": "attachment",
        "isSidechain": False,
        "attachment": {"type": "queued_command", "commandMode": "prompt", "prompt": prompt, "origin": {"kind": kind, **origin}},
        "timestamp": at,
    }


def text(words):
    return {"type": "text", "text": words}


def tool(name):
    return {"type": "tool_use", "name": name, "id": "toolu_1", "input": {"command": CARRIED}}


def thinking():
    return {"type": "thinking", "thinking": CARRIED}


def assistant(*blocks, at=LATER, **extra):
    return {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": list(blocks)}, "timestamp": at, **extra}


def tool_result():
    return {"type": "user", "isSidechain": False, "toolUseResult": {"stdout": CARRIED}, "message": {"role": "user", "content": [{"type": "tool_result", "content": CARRIED}]}, "timestamp": AT}


def turns(*found):
    return claude_transcript.turns_of(found)


class TurnsTest(unittest.TestCase):
    def test_a_turn_is_the_prompt_the_replies_and_the_tool_names_in_first_use_order(self):
        found = turns(human("do it"), assistant(text("first"), tool("Bash")), tool_result(), assistant(tool("Edit"), tool("Bash")), assistant(text("done"), at="2026-11-09T10:09:00.000Z"))
        self.assertEqual(found, (Turn("user", "do it", "first\n\ndone", ("Bash", "Edit"), "2026-11-09T10:09:00.000Z"),))

    def test_what_tools_carried_and_what_the_session_thought_never_come_back(self):
        found = turns(human("do it"), assistant(thinking(), tool("Bash")), tool_result(), assistant(text("done")))
        self.assertNotIn(CARRIED, repr(found))

    def test_a_delivered_message_starts_a_turn_with_its_body_and_not_the_wrapper(self):
        (found,) = turns(peer("please report"))
        self.assertEqual((found.origin, found.prompt), ("peer", "please report"))
        self.assertNotIn(CARRIED, repr(found))

    def test_a_peer_record_without_a_usable_body_falls_back_to_nothing(self):
        record = peer("x")
        record["origin"]["body"] = 7
        self.assertEqual(turns(record), ())

    def test_records_that_nobody_said_start_no_turn(self):
        ignored = (
            tool_result(),
            human("a summary", isCompactSummary=True),
            human("a note", isMeta=True),
            human("from a subagent", isSidechain=True),
            {"type": "user", "origin": {"kind": "task-notification"}, "message": {"content": "<task-notification>x</task-notification>"}},
            *(old_prompt(f"  <{tag}>x</{tag}>") for tag in ("command-name", "command-message", "local-command-stdout", "bash-input", "bash-stdout", "bash-stderr")),
            old_prompt("   "),
            human([text("[Request interrupted by user]")], origin=None),
            old_prompt([text("[Request interrupted by user for tool use]")]),
            queued("<task-notification>x</task-notification>", kind="task-notification"),
            queued("<agent-message>x</agent-message>", kind="peer", body="[Subagent hand-back] done", handback=True),
            {**peer("x"), "origin": {"kind": "peer", "body": "[Subagent hand-back] done", "handback": True}},
            {**queued("from a subagent"), "isSidechain": True},
            {**queued("x"), "attachment": {"type": "queued_command", "commandMode": "bash", "prompt": "ls", "origin": {"kind": "human"}}},
            {"type": "attachment", "attachment": {"type": "edited_text_file", "filename": CARRIED}},
            {"type": "attachment", "attachment": "not an object"},
            {"type": "api-request-blob", "message": {"content": CARRIED}},
            {"type": "user"},
            {"type": "user", "message": "not an object"},
        )
        for record in ignored:
            with self.subTest(record=record):
                self.assertEqual(turns(record), ())

    def test_a_task_notification_leaves_the_reply_after_it_in_the_same_turn(self):
        notified = {"type": "user", "origin": {"kind": "task-notification"}, "message": {"content": "<task-notification>x</task-notification>"}}
        (found,) = turns(human("do it"), assistant(text("started")), notified, assistant(text("finished")))
        self.assertEqual(found.reply, "started\n\nfinished")

    def test_a_message_that_reached_a_busy_session_starts_a_turn_and_takes_the_replies_after_it(self):
        found = turns(
            human("do it"),
            assistant(text("working")),
            queued("<cross-session-message>" + CARRIED + "</cross-session-message>", kind="peer", body="stop after the tests"),
            assistant(text("stopping")),
            queued("also update the docs"),
            assistant(text("updating")),
        )
        self.assertEqual([(turn.origin, turn.prompt, turn.reply) for turn in found], [("user", "do it", "working"), ("peer", "stop after the tests", "stopping"), ("user", "also update the docs", "updating")])
        self.assertNotIn(CARRIED, repr(found))

    def test_a_queued_prompt_with_blocks_keeps_its_text_blocks(self):
        (found,) = turns(queued([text("see this"), {"type": "image", "source": CARRIED}]))
        self.assertEqual(found.prompt, "see this")

    def test_a_peer_message_without_origin_is_known_by_its_wrapper_and_keeps_it(self):
        wrapped = "Another Claude session sent a message:\n<teammate-message teammate_id=\"t\">report</teammate-message>"
        (found,) = turns(old_prompt(wrapped))
        self.assertEqual((found.origin, found.prompt), ("peer", wrapped))

    def test_a_prompt_from_a_version_without_origin_counts(self):
        (found,) = turns(old_prompt("do it"))
        self.assertEqual((found.origin, found.prompt), ("user", "do it"))

    def test_a_prompt_without_origin_that_opens_with_a_tag_of_its_own_counts(self):
        for prompt in ("<component>please update it</component>", "<command-names> are listed here", "<bash-input"):
            with self.subTest(prompt=prompt):
                (found,) = turns(old_prompt(prompt))
                self.assertEqual((found.origin, found.prompt), ("user", prompt))

    def test_a_typed_slash_command_is_a_turn_in_the_form_the_transcript_holds(self):
        (found,) = turns(human("<command-name>/go</command-name>"))
        self.assertEqual(found.prompt, "<command-name>/go</command-name>")

    def test_a_prompt_with_blocks_keeps_its_text_blocks_only(self):
        (found,) = turns(human([text("see this"), {"type": "image", "source": CARRIED}, text("and this")]))
        self.assertEqual(found.prompt, "see this\nand this")
        self.assertNotIn(CARRIED, repr(found))

    def test_replies_before_any_prompt_are_a_turn_whose_start_is_out_of_reach(self):
        found = turns(assistant(text("still going")), human("next"))
        self.assertEqual(found[0], Turn(None, None, "still going", (), LATER))
        self.assertEqual(found[1].prompt, "next")

    def test_a_reply_from_a_subagent_is_not_the_sessions_own(self):
        (found,) = turns(human("do it"), assistant(text(CARRIED), isSidechain=True))
        self.assertEqual(found.reply, "")

    def test_drifted_blocks_are_ignored(self):
        (found,) = turns(human("do it"), assistant("not a block", {"type": "text", "text": 5}, {"type": "tool_use", "name": 7}, text("kept")))
        self.assertEqual((found.reply, found.tools), ("kept", ()))

    def test_a_timestamp_that_is_not_text_is_none_and_keeps_the_last_good_one(self):
        (found,) = turns(human("do it", at=5), assistant(text("x"), at=AT), assistant(text("y"), at=None))
        self.assertEqual(found.at, AT)

    def test_the_time_is_that_of_the_latest_message_in_the_turn_a_tool_result_included(self):
        finished = "2026-11-09T10:30:00.000Z"
        notified = {"type": "user", "origin": {"kind": "task-notification"}, "message": {"content": "<task-notification>x</task-notification>"}, "timestamp": finished}
        for last in ({**tool_result(), "timestamp": finished}, notified, human("a note", at=finished, isMeta=True)):
            with self.subTest(last=last):
                found = turns(human("do it"), assistant(tool("Bash")), last, human("next", at="2026-11-09T11:00:00.000Z"))
                self.assertEqual(found[0].at, finished)

    def test_a_message_written_later_with_an_earlier_time_does_not_move_the_time_back(self):
        (found,) = turns(human("do it"), assistant(text("x"), at=LATER), {**tool_result(), "timestamp": AT}, assistant(text("y"), at=AT))
        self.assertEqual(found.at, LATER)

    def test_records_that_are_not_the_sessions_own_messages_leave_the_time_alone(self):
        later = "2026-11-09T11:00:00.000Z"
        others = (
            {"type": "pr-link", "timestamp": later},
            {"type": "system", "subtype": "away_summary", "timestamp": later},
            {**queued("x", kind="task-notification"), "timestamp": later},
            {**tool_result(), "isSidechain": True, "timestamp": later},
            {**assistant(text(CARRIED)), "isSidechain": True, "timestamp": later},
        )
        for other in others:
            with self.subTest(other=other):
                (found,) = turns(human("do it"), assistant(text("x")), other)
                self.assertEqual(found.at, LATER)

    def test_a_message_before_any_turn_starts_none(self):
        self.assertEqual(turns(tool_result(), human("a note", isMeta=True)), ())


class FileCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.config = self.root / "config"

    def written(self, *lines, project="-work-repo", session=SESSION_ID):
        path = self.config / "projects" / project / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\n".join(line if isinstance(line, bytes) else json.dumps(line, ensure_ascii=False).encode("utf-8") for line in lines) + b"\n")
        return path


class PathTest(FileCase):
    def test_the_file_is_found_in_whichever_project_directory_holds_it(self):
        path = self.written(human("x"), project="-somewhere-else")
        self.assertEqual(claude_transcript.path_of(str(self.config), SESSION_ID), path)

    def test_the_newest_file_wins_where_several_hold_the_session(self):
        # Neither the first nor the last directory in listing order holds the newest file.
        first, newest, last = (self.written(human(name), project=f"-{name}") for name in ("a", "m", "z"))
        for path, stamp in ((first, 2000), (newest, 3000), (last, 1000)):
            os.utime(path, (stamp, stamp))
        self.assertEqual(claude_transcript.path_of(str(self.config), SESSION_ID), newest)

    def test_nothing_is_found_for_a_missing_file_or_directory(self):
        self.assertIsNone(claude_transcript.path_of(str(self.config), SESSION_ID))
        self.written(human("x"), session="bbbb2222-0000-4000-8000-000000000002")
        self.assertIsNone(claude_transcript.path_of(str(self.config), SESSION_ID))


class TailTest(FileCase):
    def test_a_file_within_the_limit_is_read_whole(self):
        path = self.written(b"one", b"two")
        self.assertEqual(claude_transcript.tail(path, 1000), [b"one", b"two", b""])

    def test_a_line_cut_by_the_window_is_dropped(self):
        path = self.written(b"a" * 100, b"bb", b"cc")
        self.assertEqual(claude_transcript.tail(path, 10), [b"bb", b"cc", b""])

    def test_a_separator_character_inside_a_string_does_not_split_a_line(self):
        path = self.written(human("one two"))
        (found,) = claude_transcript.turns_of(claude_transcript.records(claude_transcript.tail(path, 1000)))
        self.assertEqual(found.prompt, "one two")


class RecordsTest(unittest.TestCase):
    def test_a_line_that_is_not_a_json_object_is_skipped(self):
        lines = [b"", b"not json", b"[1, 2]", b"5", b'{"type": "half', b"\xff\xfe", b'{"type": "user"}']
        self.assertEqual(claude_transcript.records(lines), [{"type": "user"}])

    def test_deep_nesting_is_skipped_rather_than_raised(self):
        self.assertEqual(claude_transcript.records([b"[" * 200000]), [])


class PeekedTest(FileCase):
    ROW = Session(id="aaaa1111", session_id=SESSION_ID, name="n", cwd="/work/repo", kind="background", state="working")

    def test_the_last_turns_come_back_oldest_first(self):
        self.written(human("one"), human("two"), human("three"))
        peeked = claude_transcript.peeked(self.ROW, str(self.config), 2)
        self.assertEqual([turn.prompt for turn in peeked.turns], ["two", "three"])
        self.assertEqual((peeked.session, peeked.problem), (self.ROW, None))

    def test_asking_for_more_than_there_are_returns_what_there_is(self):
        self.written(human("one"))
        self.assertEqual(len(claude_transcript.peeked(self.ROW, str(self.config), 20).turns), 1)

    def test_a_count_of_zero_returns_no_turn(self):
        self.written(human("one"))
        self.assertEqual(claude_transcript.peeked(self.ROW, str(self.config), 0).turns, ())

    def test_a_file_with_no_turn_yet_is_no_problem(self):
        self.written({"type": "mode", "mode": "auto"})
        peeked = claude_transcript.peeked(self.ROW, str(self.config), 3)
        self.assertEqual((peeked.turns, peeked.problem), ((), None))

    def test_a_missing_transcript_is_a_clean_answer_that_names_no_path(self):
        peeked = claude_transcript.peeked(self.ROW, str(self.config), 3)
        self.assertEqual((peeked.turns, peeked.problem), ((), claude_transcript.NO_TRANSCRIPT))
        self.assertNotIn(str(self.root), peeked.problem)

    def test_an_unknown_configuration_directory_is_the_same_clean_answer(self):
        self.assertEqual(claude_transcript.peeked(self.ROW, None, 3).problem, claude_transcript.NO_TRANSCRIPT)

    def test_a_row_without_a_usable_session_id_never_reaches_the_file_system(self):
        self.written(human("someone else's prompt"), project="-other", session="dddd4444-0000-4000-8000-000000000004")
        for bad in ("", "*", "../x", "a*b", "a/b", "*/*", "?" * 36):
            with self.subTest(bad=bad):
                row = Session(id="aaaa1111", session_id=bad, name="n", cwd="/w", kind="background", state="done")
                peeked = claude_transcript.peeked(row, str(self.config), 3)
                self.assertEqual((peeked.turns, peeked.problem), ((), claude_transcript.NO_TRANSCRIPT))

    def test_an_unreadable_file_is_a_clean_answer_that_names_no_path(self):
        path = self.written(human("x"))
        path.unlink()
        path.mkdir()  # opening a directory raises an OSError, on any user
        peeked = claude_transcript.peeked(self.ROW, str(self.config), 3)
        self.assertEqual((peeked.turns, peeked.problem), ((), claude_transcript.UNREADABLE))
        self.assertNotIn(str(self.root), peeked.problem)


if __name__ == "__main__":
    unittest.main()
