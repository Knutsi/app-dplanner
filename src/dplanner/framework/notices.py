"""A standing fact about the whole window, said over its content.

The status bar carries what a gesture *came to*; a dialog's status slot carries where the
work in that dialog stands. Neither can carry a fact that is true for as long as it is
true and that the person must not miss — *an agent is editing this plan right now*, *these
entries changed here and outside*. Those want the top of the content, which is the one
place a person cannot be looking away from while they work.

So: one bar above the tab area, a row per standing notice, keyed by whoever owns it. A
row is DESIGN.md's *Signalling* vocabulary and nothing new — a :class:`StatusLine` in one
of the four tones, the same turning arc a working button turns when the notice is about
something running, one quiet verb at the right, and the 4 px accent bar underneath when
the notice carries a count somebody declared. The bar is gone while nothing stands, so an
ordinary window has no chrome it did not ask for.

**A notice is data, and showing the same notice twice is nothing.** The owner recomputes
its notice whenever it likes — a poll, a settle — and hands it over; a row that would not
change is left alone, so a two-second poll costs no repaint and nothing under the pointer
moves. That is what makes it safe to drive from a timer.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.signalling import Spinner, StatusLine, Tone
from dplanner.theme.icons import ICON_SIZE
from dplanner.theme.tokens import CONTROL_GAP, FIELD_GAP, PANEL_MARGIN

BAR_STEPS = 1000  # A fraction is drawn on a fixed range; the bar shows no text either way.


@dataclass(frozen=True)
class Notice:
    """One standing fact: whose it is, what it says, and the one thing to do about it.

    ``busy`` leads the words with the turning arc — the application's one motion for
    *something is running here*. ``fraction`` draws the 4 px bar when it is 0..1; below
    zero there is no bar, which is the honest picture for work with no declared count.
    ``action`` is the words on a quiet verb at the right end, ``tip`` what it explains on
    hover, and ``act`` what it runs.
    """

    id: str
    words: str
    tone: Tone = "info"
    busy: bool = False
    fraction: float = -1.0
    action: str = ""
    tip: str = ""
    act: Callable[[], None] | None = field(default=None, compare=False)


class _NoticeRow(QWidget):
    """One notice, drawn: the arc, the words, the verb, and the bar under all three."""

    def __init__(self, notice: Notice, parent: QWidget) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(FIELD_GAP // 2)
        # The child layout joins its parent before anything goes in it: a parentless layout
        # filled first leaves QLayoutItem wrappers alive on the Python side (CLAUDE.md).
        line = QHBoxLayout()
        column.addLayout(line)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(CONTROL_GAP)

        # A bare label is all the arc needs to stand on its own — DESIGN.md's *Signalling*.
        self._arc = QLabel(self)
        self._arc.setFixedSize(ICON_SIZE, ICON_SIZE)
        self._spinner = Spinner(self).attach(self._arc)
        self._words = StatusLine(self)
        self._words.setWordWrap(True)
        self._button = QToolButton(self)
        self._button.setObjectName("ToolbarButton")
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        line.addWidget(self._arc)
        line.addWidget(self._words, 1)
        line.addWidget(self._button)

        self._bar = QProgressBar(self)
        self._bar.setRange(0, BAR_STEPS)
        self._bar.setTextVisible(False)
        column.addWidget(self._bar)

        self._notice = replace(notice, id="")  # Never equal to the first show: forces a draw.
        self._act: Callable[[], None] | None = None
        self._button.clicked.connect(self._run)
        self.show_notice(notice)

    def show_notice(self, notice: Notice) -> None:
        if notice == self._notice:
            self._act = notice.act  # The words are the same; the closure may be newer.
            return
        self._notice, self._act = notice, notice.act
        self._words.say(notice.words, notice.tone)
        self._button.setText(notice.action)
        self._button.setToolTip(notice.tip)
        self._button.setVisible(bool(notice.action))
        self._arc.setVisible(notice.busy)
        self._spin(notice.busy)
        showing = 0.0 <= notice.fraction <= 1.0
        self._bar.setVisible(showing)
        if showing:
            self._bar.setValue(round(notice.fraction * BAR_STEPS))

    def notice(self) -> Notice:
        return self._notice

    def dispose(self) -> None:
        self._spin(False)

    def _spin(self, on: bool) -> None:
        self._spinner.start() if on else self._spinner.stop()

    def _run(self) -> None:
        if self._act is not None:
            self._act()


class NoticeBar(QWidget):
    """Every standing notice, stacked over the window's content. Gone while there are none.

    ``show_notice`` adds or updates a row by its ``id``; ``clear_notice`` takes one away.
    Rows keep the order they first appeared in, so a notice that comes and goes does not
    shuffle the ones beside it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NoticeBar")
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(PANEL_MARGIN, FIELD_GAP, PANEL_MARGIN, FIELD_GAP)
        self._column.setSpacing(FIELD_GAP)
        # Our own list of what is in the layout: a layout is never read back (CLAUDE.md's
        # *A QLayoutItem wrapper is a double delete waiting for a gc pass*).
        self._rows: dict[str, _NoticeRow] = {}
        self.hide()

    def show_notice(self, notice: Notice) -> None:
        row = self._rows.get(notice.id)
        if row is None:
            row = _NoticeRow(notice, self)
            self._rows[notice.id] = row
            self._column.addWidget(row)
        else:
            row.show_notice(notice)
        self.setVisible(True)

    def clear_notice(self, notice_id: str) -> None:
        row = self._rows.pop(notice_id, None)
        if row is None:
            return
        row.dispose()
        self._column.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self.setVisible(bool(self._rows))

    def notices(self) -> list[Notice]:
        """What stands, in the order it is drawn — what a test reads instead of pixels."""
        return [row.notice() for row in self._rows.values()]
