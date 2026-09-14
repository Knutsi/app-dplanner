"""The *Implementation notes* tab: one project's log under its own caption.

The page is the caption — what the log holds, behind its info glyph — then the view
(``view.py``) taking the rest: its strip, the list and the editor. The activity speaks for
its project through the entity edge ``EntityActivity`` publishes and nothing more: a note is
not a selection.
"""

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QWidget

from dplanner.domain.model import Project
from dplanner.framework.activity import EntityActivity
from dplanner.framework.context import Uri, activity_uri
from dplanner.framework.widgets import captioned
from dplanner.modules.notes.view import NotesView
from dplanner.theme.tokens import PANEL_MARGIN, SECTION_GAP

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.notes.module import NotesDeps

NOTES_KIND = "notes"
NOTES_CAPTION = "Implementation notes"
NOTES_HINT = "What was decided, handed over, changed and deferred along the way."


class NotesActivity(EntityActivity):
    """One project's implementation notes, as a tab."""

    def __init__(self, deps: "NotesDeps", project_id: str) -> None:
        super().__init__(deps.context, "project", project_id)
        self.project_id = project_id
        self._library = deps.library

        self.page = QWidget()
        layout = QVBoxLayout(self.page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)
        self.caption = captioned(NOTES_CAPTION, self.page, hint=NOTES_HINT)
        layout.addWidget(self.caption)
        self.view = NotesView(
            deps.library,
            deps.undo,
            deps.step_key,
            project_id,
            deps.debounce,
            self.page,
            dictation=deps.dictation,
        )
        layout.addWidget(self.view, 1)

    def show_note(self, note_id: str) -> bool:
        """Open the tab on one note — a jump from a test that says it came from it."""
        return self.view.show_note(note_id)

    @property
    def uri(self) -> Uri:
        return activity_uri(NOTES_KIND, self.project_id)

    @property
    def title(self) -> str:
        return f"{self._project().title or 'Untitled project'} — {NOTES_CAPTION}"

    @property
    def widget(self) -> QWidget:
        return self.page

    def close(self) -> None:
        self.view.dispose()

    def _project(self) -> Project:
        return self._library.project(self.project_id)
