"""What a step *is*: the one ranking of its kinds, and the key and the word it gives.

Each kind is a fact its own aspect answers (:mod:`.milestone`, :mod:`.feature`, …); this is
the order in which they are asked. The coarser claim wins — a milestone that is also a
feature is a milestone — so a step has at most one kind, and its key's letter and its kind
word are read from the same row.

**Only the key and the word follow this ranking.** Who works a step (its primary glyph),
the medallions (several marks at once), the body tone (done outranks any kind) and where a
scope's walk stops are separate policies in the composition root that *read* these facts;
folding them into one list was the review's error, corrected in §12 of the structural
review.
"""

from collections.abc import Callable
from enum import Enum
from typing import Final

from dplanner.domain.model import Step
from dplanner.planning.agent import enabled as is_agent
from dplanner.planning.branches import A_CUT, is_cut
from dplanner.planning.check import read as is_check
from dplanner.planning.feature import is_feature
from dplanner.planning.milestone import is_milestone
from dplanner.planning.review import is_review
from dplanner.planning.wait import is_wait


class Kind(Enum):
    """A step's kind; ``.value`` is the word a report and ``--json`` print."""

    MILESTONE = "milestone"
    FEATURE = "feature"
    CHECK = "check"
    WAIT = "wait"
    CUT = "cut"
    REVIEW = "review"
    AGENT = "agent"


# Coarsest first. The letter is what the key prints; an agent step and a step of no kind
# share ``S``.
RANKING: Final[tuple[tuple[Kind, str, Callable[[Step], bool]], ...]] = (
    (Kind.MILESTONE, "M", is_milestone),
    (Kind.FEATURE, "F", is_feature),
    (Kind.CHECK, "C", is_check),
    (Kind.WAIT, "W", is_wait),
    (Kind.CUT, "B", is_cut),
    (Kind.REVIEW, "R", is_review),
    (Kind.AGENT, "S", is_agent),
)
PLAIN_LETTER: Final = "S"


def kind_of(step: Step) -> Kind | None:
    """The step's kind, or None for a plain step."""
    return next((kind for kind, _letter, is_one in RANKING if is_one(step)), None)


def key_of(step: Step) -> str:
    """The step's readable key: its kind's letter and the number the project dealt — ``M3``,
    ``S12`` — or "" for a step not yet numbered.

    The letter is presentation over the stored number, which is why a step keeps its number
    when its kind changes and the letter follows. Read by every card's key block, every CLI
    row and lookup, the branch a run is named after, and the briefing.
    """
    if not step.number:
        return ""
    letter = next((letter for _kind, letter, is_one in RANKING if is_one(step)), PLAIN_LETTER)
    return f"{letter}{step.number}"


def kind_word(step: Step) -> str:
    """The step's kind as a word, "" for a plain step."""
    kind = kind_of(step)
    return kind.value if kind else ""


def works_nobody(step: Step) -> str:
    """What a step nobody works is called — "a wait", "a branch cut" — for the verbs that
    refuse it a status, an agent, a review or a test; "" for a step somebody works."""
    return "a wait" if is_wait(step) else A_CUT if is_cut(step) else ""
