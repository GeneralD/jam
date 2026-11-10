"""Tests for the bounds of what `peek` returns."""

from __future__ import annotations

import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from jam import turn_bounds
from jam.session import Peeked, Session, Turn

ROW = Session(id="aaaa1111", session_id="aaaa1111-full", name="n", cwd="/w", kind="background", state="done")


def turn(prompt="p", reply="r", tools=()):
    return Turn("user", prompt, reply, tools, None)


class BoundedTest(unittest.TestCase):
    def test_short_turns_come_back_unchanged(self):
        turns = (turn("one", "two", ("Bash",)), Turn(None, None, "x", (), None))
        self.assertEqual(turn_bounds.bounded(turns), turns)

    def test_a_long_prompt_keeps_its_opening_and_a_long_reply_keeps_its_end(self):
        (found,) = turn_bounds.bounded((turn("a" * 5000 + "END", "START" + "b" * 9000),))
        self.assertEqual(len(found.prompt), turn_bounds.MAX_PROMPT_CHARS)
        self.assertTrue(found.prompt.startswith("aaa") and found.prompt.endswith("..."))
        self.assertEqual(len(found.reply), turn_bounds.MAX_REPLY_CHARS)
        self.assertTrue(found.reply.startswith("...") and found.reply.endswith("bbb"))
        self.assertNotIn("START", found.reply)

    def test_text_at_the_limit_is_not_cut(self):
        (found,) = turn_bounds.bounded((turn("a" * turn_bounds.MAX_PROMPT_CHARS, "b" * turn_bounds.MAX_REPLY_CHARS),))
        self.assertNotIn("...", found.prompt + found.reply)

    def test_tool_names_are_capped(self):
        (found,) = turn_bounds.bounded((turn(tools=tuple(f"tool{n}" for n in range(99))),))
        self.assertEqual(len(found.tools), turn_bounds.MAX_TOOL_NAMES)

    def test_the_oldest_turns_go_first_when_the_total_is_full(self):
        turns = tuple(turn(f"{n}" + "a" * 1990, "b" * 3999) for n in range(9))
        found = turn_bounds.bounded(turns)
        self.assertEqual([item.prompt[0] for item in found], ["6", "7", "8"])
        self.assertLessEqual(sum(len(item.prompt) + len(item.reply) for item in found), turn_bounds.MAX_TOTAL_CHARS)

    def test_the_total_counts_from_the_newest_turn(self):
        small_old = turn("A" + "a" * 99, "")
        newer = tuple(turn(f"{n}" + "a" * 1999, "b" * 4000) for n in "CDE")  # 6000 each, at the limits, so nothing is cut
        found = turn_bounds.bounded((small_old, turn("B" + "a" * 1999, "b" * 4000), *newer))
        self.assertEqual([item.prompt[0] for item in found], ["C", "D", "E"])

    def test_a_total_exactly_at_the_limit_is_kept_whole(self):
        turns = (turn("Y" * 2000, ""), *(turn("a" * 2000, "b" * 4000) for _ in range(3)))
        self.assertEqual(sum(len(item.prompt) + len(item.reply) for item in turns), turn_bounds.MAX_TOTAL_CHARS)
        self.assertEqual(len(turn_bounds.bounded(turns)), 4)

    def test_no_more_than_the_turn_cap_comes_back_whatever_a_harness_read(self):
        turns = tuple(turn(f"p{n}", "r") for n in range(turn_bounds.MAX_TURNS + 5))
        found = turn_bounds.bounded(turns)
        self.assertEqual([item.prompt for item in found], [f"p{n}" for n in range(5, turn_bounds.MAX_TURNS + 5)])

    def test_a_long_tool_name_and_a_long_time_are_cut(self):
        (found,) = turn_bounds.bounded((Turn("user", "p", "r", ("x" * 3000000,), "t" * 5000),))
        self.assertEqual(len(found.tools[0]), turn_bounds.MAX_TOOL_NAME_CHARS)
        self.assertTrue(found.tools[0].endswith("..."))
        self.assertEqual(len(found.at), turn_bounds.MAX_AT_CHARS)

    def test_tool_names_and_times_count_toward_the_total(self):
        names = tuple(f"{n:02d}" + "x" * (turn_bounds.MAX_TOOL_NAME_CHARS - 2) for n in range(turn_bounds.MAX_TOOL_NAMES))
        turns = tuple(Turn("user", "a" * 2000, "b" * 4000, names, None) for _ in range(3))  # 9840 each
        self.assertEqual(len(turn_bounds.bounded(turns)), 2)

    def test_no_turns_are_no_turns(self):
        self.assertEqual(turn_bounds.bounded(()), ())

    def test_bounded_peek_keeps_the_row_and_the_problem(self):
        peeked = Peeked(ROW, (turn("a" * 5000),), "note")
        found = turn_bounds.bounded_peek(peeked)
        self.assertEqual((found.session, found.problem), (ROW, "note"))
        self.assertEqual(len(found.turns[0].prompt), turn_bounds.MAX_PROMPT_CHARS)


if __name__ == "__main__":
    unittest.main()
