"""The question cards: every open question in the library, as a card a person answers from
the window. It registers nothing — the Control Centre hosts the cards on top of its board,
handed :meth:`AgentQuestionsModule.create_cards` by the composition root.

What the card does is the headless half's: answering is ``inbox.answer`` with a person as
``by``, *Retry now* is ``inbox.retry_now``, both wired by the root as plain callbacks, so the
card and ``dplanner question answer`` cannot drift. ``docs/architecture/agents.md``'s *The
inbox is cards on top of the Control Centre* has the reasoning.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QWidget

from dplanner.domain.agents import AgentHarness
from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.framework.window import StatusHost
from dplanner.modules.agent_questions.panel import QuestionCards


@dataclass(frozen=True)
class AgentQuestionsDeps:
    library: Library
    status: StatusHost
    # Where a project keeps its questions: its directory, None for one the store lacks.
    project_dir: Callable[[NodeId], Path | None]
    # Record a person's answer (project dir, question id, words) and say what became of it;
    # raises ValueError or LookupError with the reason it was refused.
    answer: Callable[[Path, str, str], str]
    # Retry now on a parked run (project dir, run id): the same contract as ``answer``.
    retry_now: Callable[[Path, str], str]
    # Select the step in its project's graph.
    reveal: Callable[[StepId], None]
    # Who ran the question's run, named as the harness's dropdown names it.
    harnesses: tuple[AgentHarness, ...] = ()
    key_of: Callable[[Step], str] = lambda _step: ""


class AgentQuestionsModule:
    id = "agent_questions"  # Registers and stores nothing: no MODULE_ID to keep.

    def __init__(self, deps: AgentQuestionsDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        """Nothing anchored: the cards exist where a host puts them."""

    def create_cards(self, parent: QWidget | None = None) -> QuestionCards:
        return QuestionCards(self._deps, parent)
