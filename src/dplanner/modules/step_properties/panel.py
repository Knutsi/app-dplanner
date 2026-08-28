"""One step's detail panel: its title, and a tab per aspect editor other modules registered.

**This module never learns which aspects exist.** It is handed a list of
:class:`~dplanner.framework.inspector.InspectorSection` objects and turns each into a tab; an
aspect module never learns that a panel renders it. The composition root is the only place
that knows both, which is what lets the fifth aspect cost one registration and nothing else.

**Nor does it learn who is looking at a step.** There is one panel in the window and it reads
the context: whichever pane the user is in publishes a step selection, and this shows it. A
canvas, a table and anything added later reach it the same way, and none of them is its host.

The title sits above the tab bar rather than inside a tab of its own: a step's name belongs
to the step, not to any aspect, and it should stay readable while you move between them.
"""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QStackedLayout,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import Library, NodeId, StepId
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorExtension, InspectorSection
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.theme.themes import Theme

# DESIGN.md: side panels get 16 px outer margins, and more space between blocks than within
# one — 12 between, 6 from a caption to its field. The panel's own caption is its frame's
# header, so nothing here prints one.
PANEL_MARGIN = 16
BLOCK_GAP = 12
CAPTION_GAP = 6


class StepPanel(QWidget):
    """THE step detail panel, anchored in one of the window's areas.

    Its own state is one step id; everything else belongs to a contributing module (the tabs).
    """

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        sections: Sequence[InspectorSection] = (),
        theme: ThemeService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._product = library
        self._undo = undo
        self._step_id: StepId | None = None

        self.title_edit = QLineEdit(self)
        self.title_edit.setObjectName("InspectorTitle")
        self.title_edit.setPlaceholderText("What this step is")
        self.title_edit.editingFinished.connect(self._commit_title)

        self.links = QLabel(self)
        self.links.setObjectName("InspectorNote")
        self.links.setWordWrap(True)

        # One extension per section, built once for this panel. The factory takes no
        # arguments: a contributing module closed over whatever it needs at registration.
        self._extensions: list[InspectorExtension] = [section.factory() for section in sections]

        self.tab_bar = QTabBar(self)
        self.tab_bar.setObjectName("InspectorTabs")
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDrawBase(False)
        # More tabs than the template ever contemplated for 360 px (one per aspect
        # editor), so the bar degrades rather than clipping.
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideRight)

        self._pages = QStackedLayout()
        for section, extension in zip(sections, self._extensions, strict=True):
            self.tab_bar.addTab(section.label)
            self._pages.addWidget(extension.widget)
        self.tab_bar.currentChanged.connect(self._pages.setCurrentIndex)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, 0, PANEL_MARGIN, 0)
        layout.setSpacing(CAPTION_GAP)
        layout.addWidget(self.title_edit)
        layout.addWidget(self.links)
        layout.addSpacing(BLOCK_GAP)
        layout.addWidget(self.tab_bar)
        layout.addLayout(self._pages, stretch=1)

        def paint_tab_icons(current: Theme) -> None:
            for index, section in enumerate(sections):
                if section.icon is not None:
                    self.tab_bar.setTabIcon(index, section.icon(current.text_secondary))

        self._unsubscribes = [
            library.field_changed.connect(self._on_field),
            library.edges_changed.connect(self._on_edges),
            library.structure_changed.connect(self._on_structure),
        ]
        if theme is not None:
            # A panel is shorter-lived than the theme service; detach in dispose().
            self._unsubscribes.append(theme.changed.connect(paint_tab_icons))
            paint_tab_icons(theme.current)

    # -- what the context says ---------------------------------------------------------------

    def show_context(self, context: Context) -> bool:
        """One selected step is something to edit; none or several is not.

        The panel says so by going off screen rather than by showing a placeholder — an area
        with nothing in it is a wider canvas, not a blank column.
        """
        self.show_step(context.selected_entity("step"))
        return self._step_id is not None

    def show_step(self, step_id: StepId | None) -> None:
        """Show one step, or nothing.

        The empty path runs *before* the unchanged-id early return: deselecting has to get
        through every time, or the last step stays on screen after the user clicks away.
        """
        if step_id is None or not self._product.has(step_id):
            self._step_id = None
            self._show_in_extensions(None)
            return
        if step_id == self._step_id:
            return
        self._step_id = step_id
        self.title_edit.setText(self._product.step(step_id).title)
        self._refresh_links()
        self._show_in_extensions(step_id)

    def current_step_id(self) -> StepId | None:
        return self._step_id

    def dispose(self) -> None:
        """Full detachment — a disposed panel must never hear another model signal."""
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        for extension in self._extensions:
            extension.dispose()
        self._extensions = []

    # -- internals -----------------------------------------------------------------------------

    def _show_in_extensions(self, step_id: StepId | None) -> None:
        for extension in self._extensions:
            extension.show_target(step_id)

    def _commit_title(self) -> None:
        # editingFinished also fires during teardown, when the step may already be gone.
        if self._step_id is None or not self._product.has(self._step_id):
            return
        value = self.title_edit.text().strip()
        if value != self._product.step(self._step_id).title:
            self._undo.push(SetFieldCommand(self._step_id, "title", value, view_origin=self))

    def _on_field(self, node_id: NodeId, field: str, origin: object) -> None:
        if node_id != self._step_id or field != "title":
            return
        # Not a plain `origin is self`: an undo performed while this field has focus still
        # has to reach it, and only a focused field is mid-edit.
        if not (origin is self and self.title_edit.hasFocus()):
            self.title_edit.setText(self._product.step(node_id).title)

    def _on_edges(self, step_id: StepId, _origin: object) -> None:
        if self._step_id is not None:
            self._refresh_links()

    def _on_structure(self, _parent_id: NodeId, _origin: object = None) -> None:
        if self._step_id is None:
            return
        if not self._product.has(self._step_id):
            # The shown step was removed. This also nulls _step_id, so re-showing the same
            # id later is not swallowed by the unchanged-id early return.
            self.show_step(None)
        else:
            self._refresh_links()

    def _refresh_links(self) -> None:
        if self._step_id is None:
            return
        waits = [step.title or "untitled" for step in self._product.requires(self._step_id)]
        blocks = [step.title or "untitled" for step in self._product.dependents(self._step_id)]
        lines = []
        if waits:
            lines.append("Waits on " + ", ".join(waits))
        if blocks:
            lines.append("Blocks " + ", ".join(blocks))
        self.links.setText(" · ".join(lines))
        self.links.setVisible(bool(lines))
