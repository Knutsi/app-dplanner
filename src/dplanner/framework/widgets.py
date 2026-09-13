"""Small shared widget helpers.

Nothing here is a framework concept — these are the handful of things every second feature
would otherwise reimplement slightly differently: a confirmation whose default is "no", a
centred column at a readable measure, what an empty page says, the caption over a block
(with its help glyph) and the remark under it, and Ctrl+wheel zoom. Add to it sparingly;
a helper that only one feature uses belongs in that feature.
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPalette, QTextBlockFormat, QTextCursor, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.theme.cards import detail_font
from dplanner.theme.icons import ICON_SIZE, info_icon
from dplanner.theme.tokens import FIELD_GAP

# DESIGN.md's text-well metrics: the text never touches the frame.
DOCUMENT_MARGIN = 12
LINE_HEIGHT_PERCENT = 130


def make_text_well(pane: QPlainTextEdit) -> None:
    """DESIGN.md's text well: the document keeps 12 px from the frame on every side."""
    pane.document().setDocumentMargin(DOCUMENT_MARGIN)


def space_lines(pane: QPlainTextEdit) -> None:
    """~130 % line height for anything longer than a label — reapplied per setPlainText."""
    block = QTextBlockFormat()
    block.setLineHeight(
        LINE_HEIGHT_PERCENT, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
    )
    cursor = QTextCursor(pane.document())
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.mergeBlockFormat(block)


def confirm(parent: QWidget | None, title: str, question: str, *, verb: str = "Yes") -> bool:
    """A confirmation for an action that throws work away, on the dialog frame: the
    question in the body, the verb a quiet button (it discards, so no accent), and Cancel
    the default so Enter never discards anything.

    The question is the dialog's whole content, not a heading over it — the frame prints no
    title of its own, and the title names the window.
    """
    # The frame is built from this module's helpers, so it is imported here, not above.
    from dplanner.framework.dialog import DialogFrame

    dialog = DialogFrame(title, parent)
    asked = QLabel(question, dialog)
    asked.setObjectName("DialogQuestion")
    asked.setWordWrap(True)
    dialog.body_layout.addWidget(asked)
    dialog.body_layout.addStretch(0)
    dialog.add_button(verb, dialog.accept)
    dialog.add_dismiss()
    answer = dialog.exec() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    return answer


def caption(text: str, parent: QWidget | None = None) -> QLabel:
    """The one caption look (DESIGN.md's *Hierarchy*): bold, secondary, over its block."""
    label = QLabel(text, parent)
    label.setObjectName("InspectorCaption")
    return label


def note(text: str, parent: QWidget | None = None) -> QLabel:
    """A remark that changes with the data (DESIGN.md's *Words*): secondary, normal weight."""
    label = QLabel(text, parent)
    label.setObjectName("InspectorNote")
    label.setWordWrap(True)
    return label


def ink_of(widget: QWidget) -> QColor:
    """The ink a glyph beside ``widget``'s words is painted in.

    A colour taken out of the palette goes stale when the theme changes, so this is for
    something built fresh each time it is shown — a dialog, a menu, a popup — never for a
    long-lived widget, which re-reads on ``QEvent.PaletteChange`` instead.
    """
    return widget.palette().color(QPalette.ColorRole.Text)


class _HintGlyph(QLabel):
    """The info glyph beside a caption, re-inked when the theme changes.

    A pixmap ignores the stylesheet's ``color``, so the ink has to be painted in — and a
    colour painted into a long-lived widget goes stale on the next theme, which is the
    ``option.palette`` trap one layer up. It repaints itself on ``PaletteChange`` instead,
    the way ``Toolbar`` re-inks its verbs, so a caption on a tab page is as safe as one in
    a dialog built fresh each time it opens.
    """

    def __init__(self, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setToolTip(hint)
        self._reink()

    def _reink(self) -> None:
        self.setPixmap(info_icon(ink_of(self)).pixmap(ICON_SIZE, ICON_SIZE))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._reink()
        super().changeEvent(event)


def captioned(title: str, parent: QWidget, hint: str = "") -> QWidget:
    """A caption over a block, with a standing convention behind an info glyph.

    DESIGN.md's *Forms*: help is an ``info_icon()`` beside the caption with the sentence as
    its tooltip — never a line of prose under the field, which reads as an error.
    """
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(FIELD_GAP)
    layout.addWidget(caption(title, row))
    if hint:
        layout.addWidget(_HintGlyph(hint, row))
    layout.addStretch(1)
    return row


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


# DESIGN.md's *Empty states*: one short line at a readable measure, never a banner.
EMPTY_STATE_MEASURE = 360
EMPTY_STATE_GAP = 12  # Between the line and the button under it.


class EmptyState(QWidget):
    """What a page with nothing in it says: one short line, a size smaller and in the
    secondary ink, centred both ways in the space the content would have taken — and,
    when one verb puts something there, that verb as a plain button under the line.

    A tab cannot go off screen the way a panel does (DESIGN.md's *Panels*), so it says so
    in words — and a line left where the layout happened to put it reads as a stray
    footer. ``say`` shows the message and hides on "", and the content it ``stands_in_for``
    does the opposite: the caller gives both the same stretch, and the two trade places.
    """

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        action: tuple[str, Callable[[], object]] | None = None,  # A verb; its answer is not read.
        stands_in_for: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.stands_in_for = stands_in_for
        self.setObjectName("EmptyState")
        self.label = QLabel(text, self)
        self.label.setObjectName("EmptyStateText")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setFont(detail_font(self.label.font()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(EMPTY_STATE_GAP)
        layout.addStretch(1)
        layout.addWidget(centered_column(self.label, EMPTY_STATE_MEASURE))
        self.button: QPushButton | None = None
        if action is not None:
            label, run = action
            self.button = QPushButton(label, self)
            self.button.clicked.connect(run)
            layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        self._trade(bool(text))

    def say(self, text: str) -> None:
        self.label.setText(text)
        self._trade(bool(text))

    def _trade(self, shown: bool) -> None:
        self.setVisible(shown)
        if self.stands_in_for is not None:
            self.stands_in_for.setVisible(not shown)

    def text(self) -> str:
        return self.label.text()


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
