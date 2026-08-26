"""Small shared widget helpers.

Nothing here is a framework concept — these are the three or four things every second
feature would otherwise reimplement slightly differently: a confirmation whose default is
"no", a centred column at a readable measure, and Ctrl+wheel zoom. Add to it sparingly;
a helper that only one feature uses belongs in that feature.
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QHBoxLayout,
    QMessageBox,
    QWidget,
)


def confirm(parent: QWidget | None, title: str, question: str) -> bool:
    """A Yes/No prompt for an action that throws work away; No is the default so Enter
    never discards anything."""
    buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    answer = QMessageBox.question(parent, title, question, buttons, QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def centered_column(content: QWidget, max_width: int) -> QWidget:
    """Wrap ``content`` so it sits centred at a readable measure.

    Stretch-column-stretch rather than an alignment flag: an aligned widget is given only
    its size hint, which would collapse an editor; this way the column takes all space up
    to its maximum width and the stretches absorb the rest, so the measure stays
    comfortable in a wide window and degrades gracefully in a narrow one.
    """
    content.setMaximumWidth(max_width)
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch(1)
    layout.addWidget(content, stretch=100)
    layout.addStretch(1)
    return wrapper


class _CtrlWheelFilter(QObject):
    def __init__(self, viewport: QWidget, on_steps: Callable[[int], None]) -> None:
        super().__init__(viewport)
        self._on_steps = on_steps

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if (
            isinstance(event, QWheelEvent)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            delta = event.angleDelta().y()
            if delta:
                self._on_steps(1 if delta > 0 else -1)
            return True  # Consumed — also suppresses the editor's built-in zoom.
        return super().eventFilter(obj, event)


def install_ctrl_wheel_zoom(editor: QAbstractScrollArea, on_steps: Callable[[int], None]) -> None:
    """Route Ctrl+wheel on ``editor`` to ``on_steps(±1)``.

    Wheel events land on the viewport of a scroll area, so the filter lives there; it is
    parented to the viewport and needs no further bookkeeping.
    """
    viewport = editor.viewport()
    viewport.installEventFilter(_CtrlWheelFilter(viewport, on_steps))
