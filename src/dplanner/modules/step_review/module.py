"""The review aspect, in the running application: the Review toggle and the Review tab.

The conversation is not driven from here. Reviewer and reviewed step talk through
``dplanner review …`` (``cli.py``), and the tab shows what they said as the ledger changes;
a window has no verb that posts a finding, because only an agent writes one.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from dplanner.domain.agents import AgentHarness
from dplanner.domain.model import Library, Step
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.step_review.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    NO_REVIEW_ON_A_WAIT,
    SPEC,
    ReviewSettings,
    is_review,
    write,
)
from dplanner.modules.step_review.rounds import DATA_FORMAT as ROUNDS_FORMAT
from dplanner.modules.step_review.rounds import MODULE_ID as ROUNDS_ID
from dplanner.modules.step_review.section import ReviewSection
from dplanner.theme.icons import review_icon


@dataclass(frozen=True)
class StepReviewDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    sections: InspectorSectionRegistry
    is_wait: Callable[[Step], bool]
    key_of: Callable[[Step], str]
    # The agent CLIs this build can launch, and the name of this machine's default launch
    # profile — the choices the Agent field lays out, the default first.
    harnesses: Sequence[AgentHarness]
    default_profile: Callable[[], str]


class StepReviewModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepReviewDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=42,  # Right after Agent (40): a review is an agent step first.
                factory=lambda: ReviewSection(
                    deps.library,
                    deps.undo,
                    key_of=deps.key_of,
                    harnesses=deps.harnesses,
                    default_profile=deps.default_profile,
                ),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and is_review(deps.library.step(step_id))
                ),
            )
        )
        deps.actions.register(
            aspect_toggle(
                id="review.toggle",
                label=SPEC.label,
                order=35,  # A kind, after Agent (30): what the agent does.
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=is_review,
                fresh=lambda _step, _project: write(ReviewSettings()),
                icon=review_icon,
                tip="Make this step an automatic review of the step it waits on",
                refusal=lambda step: NO_REVIEW_ON_A_WAIT if deps.is_wait(step) else "",
            )
        )


class ReviewRoundsModule:
    """Declares the conversation's format only; the ``review`` verbs write it."""

    id = ROUNDS_ID
    data_format = ROUNDS_FORMAT

    def register(self) -> None:
        return None
