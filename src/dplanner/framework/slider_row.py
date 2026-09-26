"""A slider over a run of steps, with a step either way — History's days, a replay's frames.

A bare ``QSlider`` is hard to land on one step of many with the mouse, and its arrow keys
only work once it has the focus. :class:`SliderRow` puts a glyph button either side that
steps once and greys at its end, and says every move — dragged, stepped or keyed — through
one signal, as it happens, so a view can follow the slider rather than wait for it to be let
go.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QSlider, QWidget

from dplanner.framework.widgets import GlyphButton
from dplanner.theme.icons import chevron_left_icon, chevron_right_icon
from dplanner.theme.tokens import CAPTION_GAP


class SliderRow(QWidget):
    """``count`` steps, ``0`` to ``count - 1``; :attr:`moved` says each one reached."""

    moved = Signal(int)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        earlier: str = "A step back",
        later: str = "A step on",
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(CAPTION_GAP)
        self.earlier = GlyphButton("", chevron_left_icon, self, tip=earlier)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setPageStep(1)
        self.later = GlyphButton("", chevron_right_icon, self, tip=later)
        row.addWidget(self.earlier)
        row.addWidget(self.slider, 1)
        row.addWidget(self.later)
        self.earlier.clicked.connect(lambda: self.set_value(self.value() - 1, say=True))
        self.later.clicked.connect(lambda: self.set_value(self.value() + 1, say=True))
        self.slider.valueChanged.connect(self._on_value)
        self._quiet = False
        self.set_count(1)

    def value(self) -> int:
        return self.slider.value()

    def set_count(self, count: int) -> None:
        """How many steps the row runs over; the value is kept where it still falls."""
        self._quiet = True
        self.slider.setRange(0, max(0, count - 1))
        self._quiet = False
        self._sync()

    def set_value(self, value: int, *, say: bool = False) -> None:
        """Move to ``value`` — silently, as a host placing it, unless ``say``."""
        self._quiet = not say
        self.slider.setValue(max(self.slider.minimum(), min(value, self.slider.maximum())))
        self._quiet = False
        self._sync()

    def _on_value(self, value: int) -> None:
        self._sync()
        if not self._quiet:
            self.moved.emit(value)

    def _sync(self) -> None:
        self.earlier.setEnabled(self.value() > self.slider.minimum())
        self.later.setEnabled(self.value() < self.slider.maximum())
