"""The notes module in the running application: the *Implementation notes* tab.

One tab per project — the log as rows beside the picked note's editor (``view.py``) —
opened from the row this module puts under each project in the index's Docs folder
(``index_row``, handed to the docs module by the composition root; neither imports the
other). No menu verb of its own: far more often the log is written by an agent through
``dplanner note add``, and what a step's briefing carries of it is the Agent tab's
Inherited pane, rendered by the same blocks the composition root hands the briefing. The
Qt-free halves never load this file.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.domain.model import Library, NodeId, Step
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.context import ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.project_list_segment import ChildRow
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.modules.notes.activity import NOTES_CAPTION, NOTES_KIND, NotesActivity
from dplanner.modules.notes.log import MODULE_ID
from dplanner.modules.notes.migrate import DATA_FORMAT
from dplanner.theme.icons import edit_icon


@dataclass(frozen=True)
class NotesDeps:
    library: Library
    undo: UndoService[Library]
    debounce: DebounceService
    context: ContextService
    tabs: TabHost
    # A step's key, the way every row prints one; the rule is the composition root's.
    step_key: Callable[[Step], str]


class NotesModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: NotesDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.tabs.register_factory(NOTES_KIND, self._activity)
        follow_entity_tabs(
            deps.tabs,
            NotesActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(NOTES_KIND, project_id, preview=preview)

    def index_row(self) -> ChildRow:
        """The row under each project in the Docs folder that opens this tab."""
        return ChildRow(
            NOTES_CAPTION,
            edit_icon,
            lambda project_id, preview: self.open(project_id, preview=preview),
        )

    def _activity(self, target: str | None) -> NotesActivity:
        assert target is not None
        return NotesActivity(self._deps, target)
