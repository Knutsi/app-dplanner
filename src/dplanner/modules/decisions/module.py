"""The decisions module in the running application: the project panel's Decisions card.

No tab, no menu verb: a decision is read from the project panel and written from the
card's dialog — or, far more often, by an agent through ``dplanner decision add``. The
card registers into ``deps.cards`` like every project-level section; the Qt-free halves
(``log.py``, ``cli.py``) never load this file.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, Step
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.decisions.card import DecisionsCard
from dplanner.modules.decisions.log import DATA_FORMAT, MODULE_ID
from dplanner.theme.icons import edit_icon


@dataclass(frozen=True)
class DecisionsDeps:
    library: Library
    undo: UndoService[Library]
    # The project panel's card host — the same contract as a step tab, one level up.
    cards: InspectorSectionRegistry
    parent: QWidget  # The window: parents the editor dialog.
    # A step's key, the way every row prints one; the rule is the composition root's.
    step_key: Callable[[Step], str]


class DecisionsModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: DecisionsDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.cards.register(
            InspectorSection(
                id=f"{MODULE_ID}.card",
                label="Decisions",
                order=40,  # After the standing instruction (20) and the docs style.
                factory=lambda: DecisionsCard(deps.library, deps.undo, deps.step_key, deps.parent),
                icon=edit_icon,
            )
        )
