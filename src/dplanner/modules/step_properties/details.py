"""The Details tab: the first thing a step shows, composed from blocks other modules own.

The same contract as the tabs, one host down: a module that wants its editor on the first
tab rather than behind one of its own registers an
:class:`~dplanner.framework.inspector.InspectorSection` into the ``step_details`` registry,
and this composite stacks the blocks — a caption from the section's ``label``, then the
extension's widget, ``stretch`` deciding who gets the leftover height. This module never
learns what a description or an estimate is, exactly as the panel never learns what a tab
holds.

Blocks honour ``shown_for`` the way tabs do: re-asked on every target change and on model
changes to the shown target, hiding caption and widget together — a block with nothing to
say vanishes rather than sitting empty. Every extension is still shown every target,
visible or not, so a block that reappears is already current.
"""

from collections.abc import Sequence

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, TextEdit
from dplanner.framework.inspector import InspectorExtension, InspectorSection
from dplanner.framework.widgets import caption
from dplanner.theme.icons import ICON_SIZE, info_icon
from dplanner.theme.tokens import CAPTION_GAP, PANEL_MARGIN, SECONDARY_ALPHA, SECTION_GAP


class _Block(QWidget):
    """One section's caption and widget, hidden and shown as a unit."""

    def __init__(self, section: InspectorSection, extension: InspectorExtension) -> None:
        super().__init__()
        self.section = section
        self.extension = extension
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(CAPTION_GAP)
        header.addWidget(caption(section.label, self))
        self.hint: QLabel | None = None
        if section.hint:
            # DESIGN.md's *Words* rule: a standing convention goes behind a glyph, never
            # on a line of its own under the field.
            self.hint = QLabel(self)
            self.hint.setFixedSize(ICON_SIZE, ICON_SIZE)
            self.hint.setToolTip(section.hint)
            self._paint_hint()
            header.addWidget(self.hint)
        header.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(CAPTION_GAP)
        layout.addLayout(header)
        layout.addWidget(extension.widget, stretch=1)
        if section.stretch == 0:
            # What makes ``InspectorSection.stretch`` authoritative. A QWidgetItem reports
            # itself expanding when the widget's *own* layout does and its policy carries
            # GrowFlag — and the line above makes every block's layout expanding, whatever
            # its section declared. So with the one stretch block hidden, qGeomCalc found no
            # stretch to honour, fell through to "spread among the expansive", and grew all
            # three survivors to a third of the tab each (328 px for a 42 px name field,
            # whose caption and editor sank to the bottom with it). Maximum is ShrinkFlag
            # only: no GrowFlag, no promotion, and the declared stretch decides again.
            # Maximum rather than Fixed so a panel shorter than its blocks still compresses.
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def _paint_hint(self) -> None:
        if self.hint is None:
            return
        ink = QColor(self.palette().text().color())
        ink.setAlpha(SECONDARY_ALPHA)
        self.hint.setPixmap(info_icon(ink).pixmap(ICON_SIZE, ICON_SIZE))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        # A colour copied out of the palette goes stale: the glyph carries the ink it was
        # painted in, and nothing else reaches into a block to repaint it.
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_hint()
        super().changeEvent(event)


class DetailsSection(QWidget):
    """The blocks the ``step_details`` registry collected, stacked in (order, id) order."""

    def __init__(self, library: Library, sections: Sequence[InspectorSection]) -> None:
        super().__init__()
        self._product = library
        self._target_id: str | None = None
        self._blocks = [_Block(section, section.factory()) for section in sections]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)
        for block in self._blocks:
            layout.addWidget(block, stretch=block.section.stretch)
        # Somewhere for the leftover height to go when the block that wanted it is turned
        # off, so the rest stay their own size at the top. Factor **zero** on purpose: at 1
        # it would split the leftover with the description block and halve the prose editor
        # whenever that block *is* shown. Without it the blocks scatter instead, Qt handing
        # each an equal share of the surplus. ``addStretch`` rather than a hand-built
        # QSpacerItem, which is the one wrapper shape ``gc_policy``'s finalizer cannot see.
        layout.addStretch(0)

        # A block follows its aspect the way a tab does: toggles arrive as module data,
        # and some aspects are also implied by prose, so both writes re-ask shown_for.
        self._unsubscribes = [
            library.module_data_changed.connect(self._on_module_data),
            library.text_edited.connect(self._on_text),
        ]

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._target_id = target_id
        for block in self._blocks:
            block.extension.show_target(target_id)
        self._refresh_blocks()

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []
        for block in self._blocks:
            block.extension.dispose()
        self._blocks = []

    def block(self, section_id: str) -> InspectorExtension:
        """A block's extension by its section id — how tests reach an editor."""
        for block in self._blocks:
            if block.section.id == section_id:
                return block.extension
        raise KeyError(section_id)

    # -- internals -----------------------------------------------------------------------------

    def _on_module_data(self, node_id: NodeId, _module_id: str, _origin: object) -> None:
        if node_id == self._target_id:
            self._refresh_blocks()

    def _on_text(self, edit: TextEdit, _origin: object) -> None:
        if edit.node_id == self._target_id:
            self._refresh_blocks()

    def _refresh_blocks(self) -> None:
        for block in self._blocks:
            shown = block.section.shown_for is None or block.section.shown_for(self._target_id)
            block.setVisible(shown)
