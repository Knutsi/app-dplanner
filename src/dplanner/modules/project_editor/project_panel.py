"""The project's own form: what the right side shows when no step is selected.

**Why this is a panel and not an aspect section.** An
:class:`~dplanner.framework.inspector.InspectorExtension`'s whole contract is
``show_target(step_id | None)`` — one target vocabulary — so making the project form a peer of
Estimate and Ticket would force every aspect editor to answer "what if this is a project?" and
hide itself, which is precisely the conditional the section registry exists to delete. As a
panel it is a peer of the *step panel* instead: two surfaces in one area, each deciding from
the context whether it has anything to show, and neither aware of the other's contents.

**The cards are the modules'.** Below its own form the panel renders every
:class:`InspectorSection` registered into ``services.detail_cards`` as a
:class:`~dplanner.framework.cards.ToolCard` — the same contract the step panel's tabs use,
with a card stack as the host instead of a tab bar. This module never learns what a card
holds; a module with something to say about a *project* registers there and appears here.
"""

from collections.abc import Sequence

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import NodeId, Product
from dplanner.framework.cards import CardStack, ToolCard
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorExtension, InspectorSection
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.theme.themes import Theme

# DESIGN.md's side-panel spacing; the caption is the panel frame's header, not ours.
PANEL_MARGIN = 16
CAPTION_GAP = 6


class ProjectPanel(QWidget):
    """The current project's name and summary, plus a card per module with more to say."""

    def __init__(
        self,
        product: Product,
        undo: UndoService[Product],
        cards: Sequence[InspectorSection] = (),
        theme: ThemeService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self._product = product
        self._undo = undo
        self._project_id: NodeId | None = None

        self.title_edit = QLineEdit(self)
        self.title_edit.setPlaceholderText("What this project is called")
        self.title_edit.editingFinished.connect(lambda: self._commit("title"))

        self.summary_edit = QLineEdit(self)
        self.summary_edit.setPlaceholderText("What it delivers, in one line")
        self.summary_edit.editingFinished.connect(lambda: self._commit("summary"))

        fields = QFormLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(8)
        fields.addRow("Name", self.title_edit)
        fields.addRow("Summary", self.summary_edit)

        hint = QLabel("Double-click the canvas to add a step.", self)
        hint.setObjectName("InspectorNote")
        hint.setWordWrap(True)

        # The form keeps the panel's own margins; the card stack carries the same 16 px
        # inside itself, so the cards line up with the fields above them.
        form_box = QWidget(self)
        form_column = QVBoxLayout(form_box)
        form_column.setContentsMargins(PANEL_MARGIN, 0, PANEL_MARGIN, 0)
        form_column.setSpacing(CAPTION_GAP)
        form_column.addLayout(fields)
        form_column.addWidget(hint)

        # One extension per registered section, built once for this panel — the step
        # panel's lifecycle, with cards for tabs.
        self._sections = list(cards)
        self._extensions: list[InspectorExtension] = [
            section.factory() for section in self._sections
        ]
        self._stack = CardStack(self)
        self._cards: list[ToolCard] = []
        for section, extension in zip(self._sections, self._extensions, strict=True):
            card = ToolCard(section.label, extension.widget)
            self._cards.append(card)
            self._stack.add_card(card)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(form_box)
        layout.addWidget(self._stack, stretch=1)

        def paint_glyphs(current: Theme) -> None:
            for section, card in zip(self._sections, self._cards, strict=True):
                if section.icon is not None:
                    card.set_glyph(section.icon(current.text_secondary))

        self._unsubscribes = [product.field_changed.connect(self._on_field)]
        if theme is not None:
            self._unsubscribes.append(theme.changed.connect(paint_glyphs))
            paint_glyphs(theme.current)

    # -- what the context says ---------------------------------------------------------------

    def show_context(self, context: Context) -> bool:
        """The project, unless there is one step to edit — then the step panel has the area."""
        if context.selected_entity("step") is not None:
            self._set_project(None)
            return False
        # focus_entity falls back from the selection to the activity's own entity, so this is
        # the same answer for the graph tab, the order table and anything opened later.
        project_id = context.focus_entity("project")
        if project_id is None or not self._product.has(project_id):
            self._set_project(None)
            return False
        self._set_project(project_id)
        self._refresh()
        return True

    def _set_project(self, project_id: NodeId | None) -> None:
        # Unchanged target, unchanged cards — the same guard the step panel has. The dock
        # calls show_context on every context change, and a model edit can republish the
        # context mid-typing; re-targeting then would rebuild each card's binding and throw
        # the user's cursor to the start of the text.
        if project_id == self._project_id:
            return
        self._project_id = project_id
        for extension in self._extensions:
            extension.show_target(project_id)

    def current_project_id(self) -> NodeId | None:
        return self._project_id

    def dispose(self) -> None:
        for extension in self._extensions:
            extension.dispose()
        self._extensions = []
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- internals -----------------------------------------------------------------------------

    def _refresh(self) -> None:
        project = self._product.project(self._project_id) if self._project_id else None
        if project is None:
            return
        for edit, value in ((self.title_edit, project.title), (self.summary_edit, project.summary)):
            if not edit.hasFocus():
                edit.setText(value)

    def _commit(self, field_name: str) -> None:
        # editingFinished also fires during teardown, when the project may already be gone.
        if self._project_id is None or not self._product.has(self._project_id):
            return
        edit = self.title_edit if field_name == "title" else self.summary_edit
        value = edit.text().strip()
        if value != getattr(self._product.project(self._project_id), field_name):
            self._undo.push(SetFieldCommand(self._project_id, field_name, value, view_origin=self))

    def _on_field(self, node_id: NodeId, _field_name: str, origin: object) -> None:
        # Not a plain `origin is self`: an undo performed while a field has focus still has to
        # reach it, and _refresh only writes to fields that are not being typed in.
        if node_id == self._project_id and origin is not self:
            self._refresh()
