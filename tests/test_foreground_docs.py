"""Checks that the documents and the skill say how a foreground session is listed since #47 (2026-11-09).

The decision record, the README and the platform fact are pinned in
test_closed_items_docs.py, where the sentences they replace were pinned; this
file pins the skill's sentence and that the `list` and `whoami` descriptions
match the documents. Same style: flattened text, phrases pinned with their scope words.
"""

from __future__ import annotations

import unittest

from test_closed_items_docs import PinnedTest
from test_operations import operations
from test_spawn_docs import ROOT, flat

SKILL = flat((ROOT / "skills" / "delegate" / "SKILL.md").read_text(encoding="utf-8"))


class ForegroundRowDocsTest(PinnedTest):
    def test_the_skill_tells_a_session_what_a_null_id_row_is_and_who_ends_it(self):
        self.assertHolds(
            SKILL,
            ("A row with `id` null is one of the owner's foreground sessions: message it by `name` like any peer; the owner ends it.",),
        )

    def test_the_list_description_agrees_with_the_documents(self):
        description = operations.lookup("list").description
        self.assertIn(
            "A foreground session (one at the owner's keyboard) is a row with `id` null and `state` null: message it by `name` if you need to, but no `id` means `stop` and `close` cannot take it, and that is not an error.",
            description,
        )

    def test_the_whoami_description_names_the_foreground_case_after_the_no_match_case(self):
        description = operations.lookup("whoami").description
        no_match = description.index("if no row matches, your short id is unknown, so do not guess it")
        foreground = description.index("A matching row whose `id` is null means this is a foreground session, which has no short id.")
        self.assertLess(no_match, foreground)


if __name__ == "__main__":
    unittest.main()
