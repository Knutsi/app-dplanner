"""One step's detail panel: the aspect bar, and a tab per aspect editor other modules registered.

**This module never learns which aspects exist.** It is handed a list of
:class:`~dplanner.framework.inspector.InspectorSection` objects and turns each into a tab; an
aspect module never learns that a panel renders it. The composition root is the only place
that knows both, which is what lets the fifth aspect cost one registration and nothing else.
The bar across the top is the same seam one presenter along: it renders the Step ▸ Type
submenu on its right, and the templates it words on its left are named by the composition
root.

**Nor does it learn who is looking at a step.** It is driven by ``show_step`` and shows
exactly what it was opened about, which is what lets a table row open it for the row under
the cursor. The bar is handed a context naming *this panel's* step, for the same reason: the
panel shows a step nobody selected, and its toggles must act on what is on screen. It reads
no context of its own and follows no selection — the dialog (``dialog.py``) is its one host.

The name is not here: it is the first block of the Details tab, registered by this module
like any other block, so the control stack reads top-down from the one field every step has.
"""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QStackedLayout, QTabBar, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, StepId, TextEdit
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_bar import AspectBar, AspectTemplate
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.framework.inspector import (
    FocusableExtension,
    InspectorExtension,
    InspectorSection,
)
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.theme.themes import Theme
from dplanner.theme.tokens import CAPTION_GAP, PANEL_MARGIN, SECTION_GAP

# DESIGN.md's *Tokens*: side panels get 16 px outer margins, and more space between blocks
# than within one — 12 between, 6 from a caption to its field. The panel's own caption is
# its frame's header, so nothing here prints one; the bar is chrome and runs edge to edge
# above it all.


class StepPanel(QWidget):
    """THE step detail panel, hosted by the details dialog.

    Its own state is one step id; everything else belongs to a contributing module (the tabs).
    """

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        actions: ActionRegistry,
        sections: Sequence[InspectorSection] = (),
        templates: Sequence[AspectTemplate] = (),
        theme: ThemeService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._product = library
        self._undo = undo
        self._step_id: StepId | None = None
        self._sections = list(sections)

        self.bar = AspectBar(actions, self._own_context, templates, undo=undo, parent=self)

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

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(CAPTION_GAP)
        tab_row.addWidget(self.tab_bar)
        tab_row.addStretch(1)

        self._pages = QStackedLayout()
        for section, extension in zip(sections, self._extensions, strict=True):
            self.tab_bar.addTab(section.label)
            self._pages.addWidget(extension.widget)
        self.tab_bar.currentChanged.connect(self._pages.setCurrentIndex)

        column = QVBoxLayout()
        column.setContentsMargins(PANEL_MARGIN, SECTION_GAP, PANEL_MARGIN, 0)
        column.setSpacing(CAPTION_GAP)
        column.addLayout(tab_row)
        column.addLayout(self._pages, stretch=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.bar)
        layout.addLayout(column, stretch=1)

        def paint(current: Theme) -> None:
            for index, section in enumerate(sections):
                if section.icon is not None:
                    self.tab_bar.setTabIcon(index, section.icon(current.text_secondary))
            # The bar re-inks itself on PaletteChange, strip and face alike. Painting it
            # from here too would put the theme's grey beside the palette's in one row.

        self._unsubscribes = [
            library.structure_changed.connect(self._on_structure),
            # A tab follows its aspect: toggles arrive as module data, and the agent
            # aspect is also implied by its prose, so both writes re-ask shown_for — and
            # re-read the bar, since a toggle may have changed another toggle's state.
            library.module_data_changed.connect(self._on_module_data),
            library.text_edited.connect(self._on_text),
        ]
        if theme is not None:
            # A panel is shorter-lived than the theme service; detach in dispose().
            self._unsubscribes.append(theme.changed.connect(paint))
            paint(theme.current)

    # -- what it is showing ---------------------------------------------------------------

    def show_step(self, step_id: StepId | None) -> None:
        """Show one step, or nothing.

        The empty path runs *before* the unchanged-id early return: a step deleted under an
        open dialog has to get through every time, or it stays on screen as an editor over
        something that no longer exists.
        """
        if step_id is None or not self._product.has(step_id):
            self._step_id = None
            self.bar.refresh()
            self._show_in_extensions(None)
            return
        if step_id == self._step_id:
            return
        self._step_id = step_id
        self.bar.refresh()
        self._refresh_tab_visibility()
        self._show_in_extensions(step_id)

    def current_step_id(self) -> StepId | None:
        return self._step_id

    def focus(self, kind: str, entity_id: str) -> bool:
        """Bring the tab holding ``entity_id`` forward, with the thing itself shown —
        the first section that answers for the kind wins; none is False."""
        for index, extension in enumerate(self._extensions):
            if not self.tab_bar.isTabVisible(index):
                continue
            if isinstance(extension, FocusableExtension) and extension.focus_entity(
                kind, entity_id
            ):
                self.tab_bar.setCurrentIndex(index)
                return True
        return False

    def dispose(self) -> None:
        """Full detachment — a disposed panel must never hear another model signal."""
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        for extension in self._extensions:
            extension.dispose()
        self._extensions = []

    # -- internals -----------------------------------------------------------------------------

    def _own_context(self) -> Context:
        """The bar's context: this panel's step, whether or not anybody selected it."""
        if self._step_id is None:
            return Context({})
        node = ContextNode(selection_uri("step", self._step_id))
        return Context({SCOPE_SELECTION: (node,)})

    def _show_in_extensions(self, step_id: StepId | None) -> None:
        for extension in self._extensions:
            extension.show_target(step_id)

    def _on_module_data(self, node_id: NodeId, _module_id: str, _origin: object) -> None:
        if node_id == self._step_id:
            self._refresh_tab_visibility()
            self.bar.refresh()

    def _on_text(self, edit: TextEdit, _origin: object) -> None:
        if edit.node_id == self._step_id:
            self._refresh_tab_visibility()
            self.bar.refresh()

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
            # Only on a change: QTabBar.setTabVisible *clears* its layout-dirty flag when
            # the value is unchanged, so a blanket loop ends by forgetting the tab it just
            # showed and paints it with an empty rect. And it lays nothing out itself — the
            # layout happens in sizeHint() — so ask the parent layout to come and read it.
            if shown != self.tab_bar.isTabVisible(index):
                self.tab_bar.setTabVisible(index, shown)
        self.tab_bar.updateGeometry()
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
