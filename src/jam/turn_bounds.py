"""What `peek` may return, whatever a harness read (D20). Pure and stdlib only."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from itertools import accumulate
from typing import Final

from .session import Peeked, Turn

DEFAULT_TURNS: Final = 3
MAX_TURNS: Final = 20
MAX_PROMPT_CHARS: Final = 2000  # what a turn was asked is in its opening
MAX_REPLY_CHARS: Final = 4000  # where a turn got to is in its end
MAX_TOOL_NAMES: Final = 30
MAX_TOOL_NAME_CHARS: Final = 128
MAX_AT_CHARS: Final = 64
MAX_TOTAL_CHARS: Final = 20000
CUT: Final = "..."


def head_kept(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - len(CUT)] + CUT


def tail_kept(text: str, limit: int) -> str:
    return text if len(text) <= limit else CUT + text[len(text) - limit + len(CUT) :]


def _bounded_turn(turn: Turn) -> Turn:
    return replace(
        turn,
        prompt=None if turn.prompt is None else head_kept(turn.prompt, MAX_PROMPT_CHARS),
        reply=tail_kept(turn.reply, MAX_REPLY_CHARS),
        tools=tuple(head_kept(name, MAX_TOOL_NAME_CHARS) for name in turn.tools[:MAX_TOOL_NAMES]),
        at=None if turn.at is None else head_kept(turn.at, MAX_AT_CHARS),
    )


def _size(turn: Turn) -> int:
    return len(turn.prompt or "") + len(turn.reply) + sum(map(len, turn.tools)) + len(turn.at or "")


def bounded(turns: Sequence[Turn]) -> tuple[Turn, ...]:
    """The newest `MAX_TURNS` of `turns` with long text cut, and without the oldest of them where the rest already fill the total."""
    cut = tuple(_bounded_turn(turn) for turn in turns[-MAX_TURNS:])
    kept = sum(1 for total in accumulate(_size(turn) for turn in reversed(cut)) if total <= MAX_TOTAL_CHARS)
    return cut[len(cut) - kept :]


def bounded_peek(peeked: Peeked) -> Peeked:
    return replace(peeked, turns=bounded(peeked.turns))
