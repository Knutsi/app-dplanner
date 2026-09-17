"""The project's home page: its name and summary, and a card per module with more to say.

**Why the form is not an aspect section.** An
:class:`~dplanner.framework.inspector.InspectorExtension`'s whole contract is
``show_target(step_id | None)`` — one target vocabulary — so making the project form a peer of
Estimate and Ticket would force every aspect editor to answer "what if this is a project?" and
hide itself — a second target vocabulary smuggled into every editor. (A section can hide per
*step*, via ``shown_for`` — that is one vocabulary answering "nothing to say here".)

**The cards are the modules'.** Below its own form the page renders every
:class:`InspectorSection` registered into ``services.project_cards`` as a
:class:`~dplanner.framework.cards.ToolCard` — the same contract the step panel's tabs use,
with a card stack as the host instead of a tab bar. This module never learns what a card
holds; a module with something to say about a *project* registers there and appears here.

**It is opened about one project, like the step editor's modal.** It reads no context: the
tab it is on names its project once (:meth:`DashboardPage.show_target`), so a model edit
that republishes the context mid-typing re-targets nothing and the cursor stays where it
was. When the form was a dock panel that guard had to be written; here it is the shape.
"""

from collections.abc import Sequence

from PySide6.QtWidgets import QFrame, QLineEdit, QVBoxLayout, QWidget

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import Library, NodeId
from dplanner.framework.cards import CardFlow, ToolCard
from dplanner.framework.inspector import InspectorExtension, InspectorSection
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import EDITOR_MEASURE, block, caption
from dplanner.theme.themes import Theme
from dplanner.theme.tokens import PANEL_MARGIN, SECTION_GAP


class DashboardPage(QWidget):
    """One project's name and summary, then a card per module with more to say."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        cards: Sequence[InspectorSection] = (),
        theme: ThemeService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._product = library
        self._undo = undo
        self._project_id: NodeId | None = None

        self.title_edit = QLineEdit(self)
        self.title_edit.setPlaceholderText("What this project is called")
        self.title_edit.editingFinished.connect(lambda: self._commit("title"))

        self.summary_edit = QLineEdit(self)
        self.summary_edit.setPlaceholderText("What it delivers, in one line (optional)")
        self.summary_edit.editingFinished.connect(lambda: self._commit("summary"))

        # One extension per registered section, built once for this page — the step
        # panel's lifecycle, with cards for tabs.
        self._sections = list(cards)
        self.extensions: list[InspectorExtension] = [
            section.factory() for section in self._sections
        ]
        self._flow = CardFlow(self)
        self.cards: list[ToolCard] = []
        for section, extension in zip(self._sections, self.extensions, strict=True):
            card = ToolCard(section.label, extension.widget)
            self.cards.append(card)
            # A section's stretch is who gets the leftover height, here as on the Details
            # tab: a prose editor grows into the page, a list of facts stays its size.
            self._flow.add_card(card, grows=section.stretch > 0)

        # The form's captions over its fields (DESIGN.md's *Forms*), held to a readable
        # measure; then the cards on a lane of their own — a bare card on a tab page's
        # ground is one faint border (DESIGN.md's *Cards*) — flowing into as many columns
        # as the page is wide, so a wide screen is used rather than a column down its middle.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)
        form = QWidget(self)
        form.setMaximumWidth(EDITOR_MEASURE)
        fields = QVBoxLayout(form)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(SECTION_GAP)
        block(fields, caption("Name", form), self.title_edit)
        block(fields, caption("Summary", form), self.summary_edit)
        layout.addWidget(form)
        lane = QFrame(self)
        lane.setObjectName("CardLane")
        lane.setFrameShape(QFrame.Shape.NoFrame)
        lane_column = QVBoxLayout(lane)
        lane_column.setContentsMargins(0, 0, 0, 0)
        lane_column.addWidget(self._flow)
        layout.addWidget(lane, 1)

        def paint_glyphs(current: Theme) -> None:
            for section, card in zip(self._sections, self.cards, strict=True):
                if section.icon is not None:
                    card.set_glyph(section.icon(current.text_secondary))

        self._unsubscribes = []
        if theme is not None:
            self._unsubscribes.append(theme.changed.connect(paint_glyphs))
            paint_glyphs(theme.current)

    def show_target(self, project_id: NodeId) -> None:
        """Point the page at its project — once, when the tab opens.

        The equality guard is the step panel's, kept so a second call is a no-op rather
        than a rebind that throws a typing cursor to the start of the text.
        """
        if project_id == self._project_id:
            return
        self._project_id = project_id
        for extension in self.extensions:
            extension.show_target(project_id)
        self.refresh()

    def refresh(self) -> None:
        """The fields from the model — what the tab calls when the project's fields change.
        The cards follow their own documents."""
        if self._project_id is None or not self._product.has(self._project_id):
            return
        project = self._product.project(self._project_id)
        # A field being typed in is left alone: what comes back after a commit is the value
        # just committed, and an undo made from elsewhere reaches every field not in use.
        for edit, value in ((self.title_edit, project.title), (self.summary_edit, project.summary)):
            if not edit.hasFocus():
                edit.setText(value)

    def dispose(self) -> None:
        for extension in self.extensions:
            extension.dispose()
        self.extensions = []
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    def _commit(self, field_name: str) -> None:
        # editingFinished also fires during teardown, when the project may already be gone.
        if self._project_id is None or not self._product.has(self._project_id):
            return
        edit = self.title_edit if field_name == "title" else self.summary_edit
        value = edit.text().strip()
        if value != getattr(self._product.project(self._project_id), field_name):
            self._undo.push(SetFieldCommand(self._project_id, field_name, value, view_origin=self))
