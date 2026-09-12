"""The Milestone tab: one label, committed as one undoable command."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from dplanner.domain.model import Library, Step
from dplanner.framework.module_data_section import FIELD_GAP, PANEL_MARGIN, ModuleDataSection
from dplanner.framework.undo import UndoService
from dplanner.modules.step_milestone.aspect import MODULE_ID, read, write

# The swatch beside the label: a dot the size of a line of text, so the row reads as one.
SWATCH = 14
DOT = 10


class Swatch(QWidget):
    """The milestone's own shade, read-only — where the colour is *changed* is the Time
    tab, which is also where the sequence it means is visible."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(SWATCH, SWATCH)
        self._color = ""

    def show_color(self, color: str, tip: str) -> None:
        self._color = color
        self.setToolTip(tip)
        self.setVisible(bool(color))
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        if not self._color:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._color))
        inset = (SWATCH - DOT) / 2
        painter.drawEllipse(QRectF(inset, inset, DOT, DOT))
        painter.end()


class MilestoneSection(ModuleDataSection):
    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        shade: Callable[[str], tuple[str, str]] = lambda _step_id: ("", ""),
    ) -> None:
        super().__init__(library, undo, module_id=MODULE_ID, undo_label="Set Milestone")
        self._shade = shade

        self.label = QLineEdit(self)
        self.label.setPlaceholderText("MVP, v1.0, v2…")
        self.label.editingFinished.connect(self.commit)
        self.swatch = Swatch(self)

        note = QLabel(
            "Marks this step as a milestone point. When it lands is the schedule's answer;"
            " clearing the label makes it an ordinary step again.",
            self,
        )
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FIELD_GAP)
        named = QHBoxLayout()
        layout.addLayout(named)  # Joined before it is filled: never a loose QLayoutItem.
        named.setSpacing(FIELD_GAP)
        named.addWidget(self.label, 1)
        named.addWidget(self.swatch)
        layout.addWidget(note)
        layout.addStretch(1)

    def load_step(self, step: Step | None) -> None:
        self.label.setText(read(step) if step is not None else "")
        self.swatch.show_color(*(self._shade(step.id) if step is not None else ("", "")))

    def entry(self, step: Step) -> dict[str, Any]:
        return write(self.label.text())
