"""The *Implementation notes* tab: one project's log under its own caption.

The page is the caption and its line, then the view (``view.py``) taking the rest — the
shape every project tab has. The activity speaks for its project through the entity edge
``EntityActivity`` publishes and nothing more: a note is not a selection.
"""

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from dplanner.domain.model import Project
from dplanner.framework.activity import EntityActivity
from dplanner.framework.context import Uri, activity_uri
from dplanner.framework.module_data_section import PANEL_MARGIN
from dplanner.modules.notes.view import NotesView

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.notes.module import NotesDeps

NOTES_KIND = "notes"
NOTES_CAPTION = "Implementation notes"
NOTES_SUBTITLE = "What was decided, handed over, changed and deferred along the way."
CAPTION_GAP = 6
BLOCK_GAP = 12


class NotesActivity(EntityActivity):
    """One project's implementation notes, as a tab."""

    def __init__(self, deps: "NotesDeps", project_id: str) -> None:
        super().__init__(deps.context, "project", project_id)
        self.project_id = project_id
        self._library = deps.library

        self.page = QWidget()
        layout = QVBoxLayout(self.page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)
        self.caption = QLabel(NOTES_CAPTION, self.page)
        self.caption.setObjectName("InspectorCaption")
        layout.addWidget(self.caption)
        self.subtitle = QLabel(NOTES_SUBTITLE, self.page)
        self.subtitle.setObjectName("InspectorNote")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)
        layout.addSpacing(BLOCK_GAP)
        self.view = NotesView(
            deps.library, deps.undo, deps.step_key, project_id, deps.debounce, self.page
        )
        layout.addWidget(self.view, 1)

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
