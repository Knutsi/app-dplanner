"""What a step *is*: the one ranking of its kinds, and the key and the word it gives.

Each kind is a fact its own aspect answers (:mod:`.milestone`, :mod:`.feature`, …); this is
the order in which they are asked. The coarser claim wins — a milestone that is also a
feature is a milestone — so a step has at most one kind, and its key's letter and its kind
word are read from the same row.

**Only the key and the word follow this ranking.** Who works a step (its primary glyph),
the medallions (several marks at once) and the body tone (done outranks any kind) are
separate policies in the composition root that *read* these facts, and where a scope's walk
stops is :func:`scope_kinds`, below — written out rather than ranked; folding them into one
list was the review's error, corrected in §12 of the structural review.
"""

from collections.abc import Callable
from enum import Enum
from typing import Final

from dplanner.domain.model import Library, Project, Step
from dplanner.planning.agent import enabled as is_agent
from dplanner.planning.branches import A_CUT, is_cut
from dplanner.planning.check import read as is_check
from dplanner.planning.feature import is_feature
from dplanner.planning.milestone import is_milestone
from dplanner.planning.scope import ScopeKind, gatherers
from dplanner.planning.start import read as is_start
from dplanner.planning.wait import is_wait


class Kind(Enum):
    """A step's kind; ``.value`` is the word a report and ``--json`` print."""

    MILESTONE = "milestone"
    FEATURE = "feature"
    CHECK = "check"
    WAIT = "wait"
    CUT = "cut"
    AGENT = "agent"


# Coarsest first. The letter is what the key prints; an agent step and a step of no kind
# share ``S``.
RANKING: Final[tuple[tuple[Kind, str, Callable[[Step], bool]], ...]] = (
    (Kind.MILESTONE, "M", is_milestone),
    (Kind.FEATURE, "F", is_feature),
    (Kind.CHECK, "C", is_check),
    (Kind.WAIT, "W", is_wait),
    (Kind.CUT, "B", is_cut),
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


def counts_as_work(step: Step) -> bool:
    """Whether a step is work: a wait and a branch cut are not — no worker takes them and no
    count holds them."""
    return not works_nobody(step)


def scope_kinds() -> tuple[ScopeKind, ...]:
    """The collectors this build knows, and where each one's cone stops.

    Read most specific first: a step marked as both a milestone and a feature is a milestone,
    because that is the coarser claim and the one a person is looking for.

    The stopping rules are the whole design. A **check** stands for everything behind it
    having been verified, so it stops at nothing. A **milestone** collects what is new since
    the previous milestone, so it stops at milestones. A **feature** collects its own work up
    to the previous feature — and at a milestone too, since a milestone is a boundary anything
    below it also respects.

    The two that *own* work — a milestone and a feature — also stop at the plan's **start**:
    every parallel branch traces back to the origin, so without that every feature fanning
    out of it would gather it, and lint would call the recommended shape ambiguous. A check
    owns nothing and still stands for everything, the start included.

    A milestone and a check are then *read* as lists of features; a feature is the finest
    grain and is read flat. That is a different question from where the walk stops, and
    saying both here is what keeps a surface from having to guess either.

    Written literally rather than derived from a rank, because three lines a reader can
    check by eye beat an ordering abstraction over exactly three things.
    """
    return (
        ScopeKind(
            "step_milestone",
            "Milestone",
            is_milestone,
            lambda step: is_milestone(step) or is_start(step),
            gathers="feature",
        ),
        ScopeKind(
            "feature",
            "Feature",
            is_feature,
            lambda step: is_feature(step) or is_milestone(step) or is_start(step),
        ),
        ScopeKind("step_check", "Check", is_check, lambda _step: False, gathers="feature"),
    )


def flows_into(library: Library, project: Project, step_id: str) -> list[Step]:
    """The features that gather a step, in project order — what a work step's briefing
    and its passages reach the spec through. The wired feature kind's own walk, so it holds
    exactly what `scope show` says a feature holds, and the plan's start flows into none."""
    feature = next(kind for kind in scope_kinds() if kind.id == "feature")
    owners = gatherers(
        library, project, carried_by=feature.carried_by, stops_at=feature.stops_at
    ).get(step_id, ())
    return [owned for owner in owners if (owned := project.step(owner)) is not None]
