"""The notes module in the running application: the Docs tab's *Implementation notes*.

No tab, no menu verb, no panel of its own: the log is read and written in the Docs tab,
which hosts the view this module creates — a factory the composition root hands across,
the way the order view hosts the estimation module's start-date bar — or, far more often,
by an agent through ``dplanner note add``. What a step's briefing carries of the log is the
Agent tab's Inherited pane, rendered by the same blocks the composition root hands the
briefing. This module registers nothing; the Qt-free halves never load this file.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, NodeId, Step
from dplanner.framework.debounce import DebounceService
from dplanner.framework.undo import UndoService
from dplanner.modules.notes.log import MODULE_ID
from dplanner.modules.notes.migrate import DATA_FORMAT
from dplanner.modules.notes.view import NotesView


@dataclass(frozen=True)
class NotesDeps:
    library: Library
    undo: UndoService[Library]
    debounce: DebounceService
    # A step's key, the way every row prints one; the rule is the composition root's.
    step_key: Callable[[Step], str]


class NotesModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: NotesDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        """Nothing to install: the view is created for whichever surface hosts it."""

    def create_view(self, project_id: NodeId, parent: QWidget | None = None) -> NotesView:
        """One project's log as a list beside the picked note's editor."""
        deps = self._deps
        return NotesView(deps.library, deps.undo, deps.step_key, project_id, deps.debounce, parent)
