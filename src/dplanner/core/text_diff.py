"""Plain text diffing: the shared primitive pipeline steps use to turn "text in, text
out" into positioned hunks a review UI can show and apply/undo individually."""

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class Hunk:
    pos: int
    removed: str
    added: str


def diff_hunks(before: str, after: str) -> list[Hunk]:
    """Every non-equal opcode between ``before`` and ``after``, in ``before``'s
    coordinates — applying them back-to-front (highest ``pos`` first) never invalidates
    an earlier hunk's position."""
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    return [
        Hunk(pos=i1, removed=before[i1:i2], added=after[j1:j2])
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]
