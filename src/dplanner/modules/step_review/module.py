"""The review aspect, in the running application: the Review toggle, the Review tab and
the verb that reads a conversation.

The conversation is not driven from here. Reviewer and reviewed step talk through
``dplanner review …`` (``cli.py``), and the tab and *Review Conversation…* show what they
said as the ledger changes; a window has no verb that posts a finding, because only an
agent writes one.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.agents import AgentHarness
from dplanner.domain.model import Library, Step
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.step_selection import focused_step
from dplanner.framework.undo import UndoService
from dplanner.modules.step_review.aspect import DATA_FORMAT as ROUNDS_FORMAT
from dplanner.modules.step_review.aspect import MODULE_ID as ROUNDS_ID
from dplanner.modules.step_review.aspect import rounds
from dplanner.modules.step_review.conversation import open_conversation
from dplanner.modules.step_review.section import ReviewSection
from dplanner.planning.review import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    ReviewSettings,
    is_review,
    no_review,
    write,
)
from dplanner.theme.icons import review_icon

CONVERSATION = "Re&view Conversation…"


@dataclass(frozen=True)
class StepReviewDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    sections: InspectorSectionRegistry
    works_nobody: Callable[[Step], str]
    key_of: Callable[[Step], str]
    # The agent CLIs this build can launch, and the name of this machine's default launch
    # profile — the choices the Agent field lays out, the default first.
    harnesses: Sequence[AgentHarness]
    default_profile: Callable[[], str]
    parent: QWidget  # What the conversation dialog opens over.


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
                refusal=lambda step: no_review(kind) if (kind := deps.works_nobody(step)) else "",
            )
        )
        deps.actions.register(
            ActionSpec(
                id="review.conversation",
                label=CONVERSATION,
                menu="Step",
                group="agent",
                order=25,  # After Preview Agent Prompt: what the agents were told, then said.
                tip="Read what a review and the step it reviews said to each other",
                state=self._conversation_state,
                run=self._show_conversation,
            )
        )

    def _conversation_state(self, context: Context) -> ActionState:
        """Open on any step that has asked a round: a review, or a collector that sent work
        back upstream — the ledger is the same on both."""
        step = focused_step(context, self._deps.library)
        if step is None:
            return DISABLED
        if rounds(step):
            return ENABLED
        reason = "no rounds yet" if is_review(step) else "not a review"
        return ActionState(enabled=False, label=f"Review Conversation — {reason}")

    def _show_conversation(self, context: Context) -> None:
        deps = self._deps
        step = focused_step(context, deps.library)
        if step is not None:
            open_conversation(deps.library, step.id, deps.key_of, deps.parent)


class ReviewRoundsModule:
    """Declares the conversation's format only; the ``review`` verbs write it."""

    id = ROUNDS_ID
    data_format = ROUNDS_FORMAT

    def register(self) -> None:
        return None
