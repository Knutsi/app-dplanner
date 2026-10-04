"""The review aspect: a step whose agent reviews the step it waits on.

A review step is an agent step that ``requires`` the step it reviews — its **subject**, read
off the graph and never stored, so relinking a review re-aims it. What the entry holds is
how the review is run: which agent does it, the lenses it looks through and how many
rounds it may take before a person decides. Every key is optional and absence encodes the
default — ``{"on": true}`` is a review by the default profile, through architecture and
security, in three rounds at most — so a later change of default reaches every review that
never chose otherwise.

The conversation itself is the second aspect in this package (``rounds.py``), kept on the
step that asks. ``ARCHITECTURE.md``'s *A review is a conversation kept on the step that
asks* has the reasoning.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Library, Step

MODULE_ID = "step_review"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

ON_KEY: Final = "on"
AGENT_KEY: Final = "agent"
LENSES_KEY: Final = "lenses"
MAX_ROUNDS_KEY: Final = "max_rounds"


@dataclass(frozen=True)
class Lens:
    """A way of looking at a change: its id as stored, its name on the tab, and what the
    reviewing agent is asked through it."""

    id: str
    label: str
    asks: str


# The lenses a review is offered as checkboxes. A lens this build does not name is a skill of
# the person's own, passed on to the agent as written.
LENSES: Final = (
    Lens(
        "architecture",
        "Architecture",
        "Does the change fit the codebase it lands in — dependencies pointing the way the"
        " layers do, a general path generalised rather than a parallel one added beside it,"
        " names that say what each thing is, and nothing left behind (a near-duplicate, a"
        " dead branch, a stale comment) for the next change to trip on?",
    ),
    Lens(
        "security",
        "Security",
        "Could anything the change reads be turned against it — input reaching a shell"
        " string, a query or a path unescaped, a secret logged or committed, a permission or"
        " an exposed surface widened, a check a caller can skip?",
    ),
)
DEFAULT_LENSES: Final = ("architecture", "security")
DEFAULT_MAX_ROUNDS: Final = 3
# "" is the default launch profile — whatever *Run Agent* itself runs on this machine.
DEFAULT_AGENT: Final = ""


def no_review(kind: str) -> str:
    """Why a step nobody works — ``kind`` is what it is called, "a wait" — is no review."""
    return f"{kind} reviews nothing: it holds, and no agent works it"


# Why a link into a review auto-progresses whatever its flag says, as the Edge menu greys it.
TAKES_FROM_REVIEW: Final = "is a review: it takes its subject from review on"
# Why a review's run gets no worktree whatever its agent aspect says: it reads the subject's.
NO_WORKTREE_FOR_A_REVIEW: Final = "a review reads the work it reviews and commits none of its own"


@dataclass(frozen=True)
class ReviewSettings:
    """How a review is run. ``agent`` is a harness id, or "" for the default profile."""

    agent: str = DEFAULT_AGENT
    lenses: tuple[str, ...] = DEFAULT_LENSES
    max_rounds: int = DEFAULT_MAX_ROUNDS


def is_review(step: Step) -> bool:
    return (step.module_data.get(MODULE_ID) or {}).get(ON_KEY) is True


def settings(step: Step) -> ReviewSettings:
    """The step's settings — the defaults for any key it does not say, and for a step that
    is no review at all, whose conversation (a collector's) keeps the same cap."""
    entry = step.module_data.get(MODULE_ID) or {}
    agent = entry.get(AGENT_KEY)
    lenses = entry.get(LENSES_KEY)
    rounds = entry.get(MAX_ROUNDS_KEY)
    return ReviewSettings(
        agent=agent if isinstance(agent, str) else DEFAULT_AGENT,
        lenses=(
            tuple(dict.fromkeys(lens for lens in lenses if isinstance(lens, str) and lens))
            if isinstance(lenses, list)
            else DEFAULT_LENSES
        ),
        max_rounds=(
            rounds
            if isinstance(rounds, int) and not isinstance(rounds, bool) and rounds >= 1
            else DEFAULT_MAX_ROUNDS
        ),
    )


def write(chosen: ReviewSettings) -> dict[str, Any]:
    """The entry to store: the marker, and only what differs from the defaults."""
    entry: dict[str, Any] = {ON_KEY: True}
    if chosen.agent != DEFAULT_AGENT:
        entry[AGENT_KEY] = chosen.agent
    if chosen.lenses != DEFAULT_LENSES:
        entry[LENSES_KEY] = list(chosen.lenses)
    if chosen.max_rounds != DEFAULT_MAX_ROUNDS:
        entry[MAX_ROUNDS_KEY] = chosen.max_rounds
    return stamped(entry, DATA_FORMAT.version)


def reviews(waiter: Step, source: Step) -> bool:
    """Whether the link from ``source`` into ``waiter`` is a review's: every link into a
    review auto-progresses, because reviewing work under review is the review's job."""
    return is_review(waiter) and source.id in waiter.edges.get("requires", ())


def subjects(library: Library, review: Step) -> list[Step]:
    """What a review reviews: the steps it requires. One, when the plan is well made —
    lint's ``review.subject`` names a review with none or several."""
    return library.requires(review.id)


def lens(lens_id: str) -> Lens | None:
    """The lens this build names ``lens_id``, or None for a skill of the person's own."""
    return next((known for known in LENSES if known.id == lens_id), None)


def lens_words(lenses: Sequence[str]) -> str:
    """``architecture, security`` — or ``no lenses`` when none is chosen."""
    return ", ".join(lenses) or "no lenses"


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when the step is no review."""
    if not is_review(step):
        return ""
    chosen = settings(step)
    return f"review, {chosen.max_rounds} round{'' if chosen.max_rounds == 1 else 's'} at most"


SPEC = AspectSpec(
    id=MODULE_ID,
    label="Review",
    summary="Makes a step an automatic review of the step it waits on: which agent reviews,"
    " through which lenses, and how many rounds it may take before a person decides.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
