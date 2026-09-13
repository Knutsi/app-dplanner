"""A well of widget rows, each with its own verbs: what the task and Agents browsers list.

DESIGN.md's *Lists of rich items*, for a roster whose rows cannot be painted: a row carries
buttons that act on it, a status line whose tone is the mood, a bar while its work has a
known end, and a line a person copies from. A ``Table`` cannot host that, and a roster that
ticks four times a second must not rebuild — a pressed Cancel and a half-selected command
would go with it — so :class:`RowWell` keeps one :class:`WellRow` per key, and
:meth:`RowWell.reconcile` builds only what is new and drops only what has gone.

The well is framed and scrolls; its rows are transparent and parted by a hairline, the last
by nothing, since the well's own border is already there. The parts are named (``#RowWell``,
``#WellRow``, ``#WellRowDismiss``) and the stylesheet styles them — never a dialog by name.
"""

from collections.abc import Callable, Hashable, Sequence
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.signalling import StatusLine
from dplanner.theme.tokens import FIELD_GAP, ROW_LINE_GAP, ROW_PADDING_H, ROW_PADDING_V


def _keep_room(button: QToolButton) -> None:
    """A row whose verb comes and goes must not move: the button's room stays when it hides."""
    policy = button.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    button.setSizePolicy(policy)


class WellRow(QWidget):
    """One row: the title with the row's verbs at its right, a status line under it, a bar
    under that while the work's end is known, and a note a person can select and copy."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WellRow")
        # A QWidget subclass paints no stylesheet border unless told to; the hairline
        # between rows is a QSS border-bottom.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(ROW_PADDING_H, ROW_PADDING_V, ROW_PADDING_H, ROW_PADDING_V)
        layout.setSpacing(ROW_LINE_GAP)
        self._title_line = QHBoxLayout()
        layout.addLayout(self._title_line)  # Before it is filled: a parentless layout leaks.
        self._title_line.setContentsMargins(0, 0, 0, 0)
        self._title_line.setSpacing(FIELD_GAP)
        self.title = QLabel(title, self)
        self.title.setWordWrap(True)
        self._title_line.addWidget(self.title, 1)

        self.status = StatusLine(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        # Determinate only: an unknown fraction is busy, and the status line says busy.
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.bar)
        self.note = QLabel(self)
        self.note.setObjectName("InspectorNote")
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)  # A command, pasted as it reads.
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.note.hide()
        layout.addWidget(self.note)

    def add_button(self, text: str, slot: Callable[[], object], *, tip: str = "") -> QToolButton:
        """One of the row's verbs, in the quiet bordered look at the right of its title.

        It never takes the keyboard — a monitor that opens on a row's Cancel is one Enter
        from cancelling — and it keeps its room while hidden. Add the dismissal last.
        """
        button = QToolButton(self)
        button.setObjectName("ToolbarButton")
        button.setText(text)
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _keep_room(button)
        button.clicked.connect(lambda _checked=False: slot())
        self._title_line.addWidget(button)
        return button

    def add_dismiss(self, slot: Callable[[], object], *, tip: str = "Dismiss") -> QToolButton:
        """The row's way off the list: a quiet cross at the far right of its title."""
        button = QToolButton(self)
        button.setObjectName("WellRowDismiss")
        button.setText("✕")
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _keep_room(button)
        button.clicked.connect(lambda _checked=False: slot())
        self._title_line.addWidget(button)
        return button

    def show_fraction(self, fraction: float | None) -> None:
        """The bar under the status line while the work's end is known, and no bar while it
        is not — never Qt's animated indeterminate bar, which promises a fraction nobody has."""
        if fraction is None:
            self.bar.hide()
            return
        self.bar.setValue(round(min(1.0, max(0.0, fraction)) * 100))
        self.bar.show()

    def set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))


class RowWell(QScrollArea):
    """A framed, scrolling well of :class:`WellRow`s, reconciled by key."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RowWell")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Nothing in the well takes the keyboard, so a dialog around it opens on its way out.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.host = QWidget()
        self._layout = QVBoxLayout(self.host)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)  # Rows carry their own padding and hairline.
        self._layout.addStretch(1)
        self.setWidget(self.host)
        # setWidget() switches the host's autofill on, which would paint an opaque slab over
        # the well's own ground.
        self.host.setAutoFillBackground(False)
        self._rows: dict[Hashable, WellRow] = {}
        self._order: list[Hashable] = []
        self._last: WellRow | None = None

    def reconcile[K: Hashable, R: WellRow](
        self,
        keys: Sequence[K],
        build: Callable[[K], R],
        update: Callable[[K, R], None],
    ) -> None:
        """Make the well list ``keys``, in order: build a row for a new key, drop the row of
        a key that has gone, keep every other row as it is, then ``update`` each one.

        A well holds one kind of row, the one ``build`` makes, which is what ``update`` is
        handed back."""
        wanted = set(keys)
        for key, row in list(self._rows.items()):
            if key not in wanted:
                self._layout.removeWidget(row)
                row.hide()  # Gone now, not at the next deferred-delete pass.
                row.deleteLater()
                del self._rows[key]
                if row is self._last:
                    self._last = None
        for key in keys:
            if key not in self._rows:
                self._rows[key] = build(key)
        order: list[Hashable] = list(keys)
        if order != self._order:
            for row in self._rows.values():
                self._layout.removeWidget(row)
            for position, key in enumerate(order):
                self._layout.insertWidget(position, self._rows[key])
            self._order = order
        for key in keys:
            update(key, cast(R, self._rows[key]))
        self._mark_last(self._rows[keys[-1]] if keys else None)

    def rows(self) -> list[WellRow]:
        """Top to bottom, as listed."""
        return [self._rows[key] for key in self._order]

    def row(self, key: Hashable) -> WellRow | None:
        return self._rows.get(key)

    def count(self) -> int:
        return len(self._rows)

    def _mark_last(self, last: WellRow | None) -> None:
        """The last row has no row under it to be parted from, and the well's border is
        already there. A dynamic property changed after polish needs a repolish to apply."""
        if last is self._last:
            return
        for row, is_last in ((self._last, False), (last, True)):
            if row is not None:
                row.setProperty("last", is_last)
                row.style().unpolish(row)
                row.style().polish(row)
        self._last = last
