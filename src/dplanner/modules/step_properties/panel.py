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

from collections.abc import Callable, Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QStackedLayout,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import Library, NodeId, StepId, TextEdit
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorExtension, InspectorSection
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.theme.icons import ICON_SIZE, plus_icon
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
        on_add_aspect: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._product = library
        self._undo = undo
        self._step_id: StepId | None = None
        self._sections = list(sections)

        self.title_edit = QLineEdit(self)
        self.title_edit.setObjectName("InspectorTitle")
        self.title_edit.setPlaceholderText("What this step is")
        self.title_edit.editingFinished.connect(self._commit_title)

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

        # Right of the last tab, so "there could be more here" reads as part of the bar.
        # A bare QTabBar has no corner widget, so the row is the panel's own.
        self.add_aspect = QToolButton(self)
        self.add_aspect.setObjectName("ToolbarButton")
        self.add_aspect.setToolTip("Add or remove aspects")
        self.add_aspect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_aspect.setAutoRaise(True)
        self.add_aspect.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        # Painted from the palette now and re-painted from the theme below, so a host that
        # passes no ThemeService still gets a glyph rather than an empty square.
        self.add_aspect.setIcon(plus_icon(self.palette().text().color()))
        self.add_aspect.setVisible(False)  # Nothing to add until a step is shown.
        if on_add_aspect is not None:
            self.add_aspect.clicked.connect(on_add_aspect)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(CAPTION_GAP)
        tab_row.addWidget(self.tab_bar)
        tab_row.addStretch(1)
        tab_row.addWidget(self.add_aspect, 0, Qt.AlignmentFlag.AlignVCenter)

        self._pages = QStackedLayout()
        for section, extension in zip(sections, self._extensions, strict=True):
            self.tab_bar.addTab(section.label)
            self._pages.addWidget(extension.widget)
        self.tab_bar.currentChanged.connect(self._pages.setCurrentIndex)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, 0, PANEL_MARGIN, 0)
        layout.setSpacing(CAPTION_GAP)
        layout.addWidget(self.title_edit)
        layout.addSpacing(BLOCK_GAP)
        layout.addLayout(tab_row)
        layout.addLayout(self._pages, stretch=1)

        def paint_tab_icons(current: Theme) -> None:
            for index, section in enumerate(sections):
                if section.icon is not None:
                    self.tab_bar.setTabIcon(index, section.icon(current.text_secondary))
            # A colour copied out of the palette goes stale; the glyph is repainted with
            # the tabs it sits beside.
            self.add_aspect.setIcon(plus_icon(current.text_secondary))

        self._unsubscribes = [
            library.field_changed.connect(self._on_field),
            library.structure_changed.connect(self._on_structure),
            # A tab follows its aspect: toggles arrive as module data, and the agent
            # aspect is also implied by its prose, so both writes re-ask shown_for.
            library.module_data_changed.connect(self._on_module_data),
            library.text_edited.connect(self._on_text),
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
            self.add_aspect.setVisible(False)
            self._show_in_extensions(None)
            return
        self.add_aspect.setVisible(True)
        if step_id == self._step_id:
            return
        self._step_id = step_id
        self.title_edit.setText(self._product.step(step_id).title)
        self._refresh_tab_visibility()
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

    def _on_module_data(self, node_id: NodeId, _module_id: str, _origin: object) -> None:
        if node_id == self._step_id:
            self._refresh_tab_visibility()

    def _on_text(self, edit: TextEdit, _origin: object) -> None:
        if edit.node_id == self._step_id:
            self._refresh_tab_visibility()

    def _refresh_tab_visibility(self) -> None:
        """Show each tab only where its section has something to say about this step.

        ``setTabVisible`` keeps indices stable, so the 1:1 tab-to-page mapping survives;
        when the current tab goes off screen the first visible one takes over rather than
        leaving the bar pointing at nothing.
        """
        if self._step_id is None:
            return
        for index, section in enumerate(self._sections):
            shown = section.shown_for is None or section.shown_for(self._step_id)
            self.tab_bar.setTabVisible(index, shown)
        if not self.tab_bar.isTabVisible(self.tab_bar.currentIndex()):
            for index in range(self.tab_bar.count()):
                if self.tab_bar.isTabVisible(index):
                    self.tab_bar.setCurrentIndex(index)
                    break

    def _on_structure(self, _parent_id: NodeId, _origin: object = None) -> None:
        if self._step_id is None:
            return
        if not self._product.has(self._step_id):
            # The shown step was removed. This also nulls _step_id, so re-showing the same
            # id later is not swallowed by the unchanged-id early return.
            self.show_step(None)
