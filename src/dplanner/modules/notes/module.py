"""The notes module in the running application: the project panel's Notes card.

No tab, no menu verb: a note is read from the project panel and written from the card's
dialog — or, far more often, by an agent through ``dplanner note add``. What a step's
briefing carries of the log is the Agent tab's Inherited pane, rendered by the same blocks
the composition root hands the briefing. The card registers into ``deps.cards`` like every
project-level section; the Qt-free halves never load this file.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, Step
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.notes.card import NotesCard
from dplanner.modules.notes.log import MODULE_ID
from dplanner.modules.notes.migrate import DATA_FORMAT
from dplanner.theme.icons import edit_icon


@dataclass(frozen=True)
class NotesDeps:
    library: Library
    undo: UndoService[Library]
    # The project panel's card host — the same contract as a step tab, one level up.
    cards: InspectorSectionRegistry
    parent: QWidget  # The window: parents the editor dialog.
    # A step's key, the way every row prints one; the rule is the composition root's.
    step_key: Callable[[Step], str]


class NotesModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: NotesDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.cards.register(
            InspectorSection(
                id=f"{MODULE_ID}.card",
                label="Notes",
                order=40,  # After the standing instruction (20) and the docs style.
                factory=lambda: NotesCard(deps.library, deps.undo, deps.step_key, deps.parent),
                icon=edit_icon,
            )
        )
