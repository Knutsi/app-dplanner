"""A standing fact about the whole window, said over its content.

The status bar carries what a gesture *came to*; a dialog's status slot carries where the
work in that dialog stands. Neither can carry a fact that is true for as long as it is
true and that the person must not miss — *an agent is editing this plan right now*, *these
entries changed here and outside*. Those want the top of the content, which is the one
place a person cannot be looking away from while they work.

So: one bar above the tab area, a row per standing notice, keyed by whoever owns it. A
row is DESIGN.md's *Signalling* vocabulary and nothing new — a :class:`StatusLine` in one
of the tones, the same turning arc a working button turns when the notice is about
something running, one quiet verb at the right — **and the row is a band in its tone**.
The bar is gone while nothing stands, so an ordinary window has no chrome it did not ask
for.

**The band is the tone, and the band is the meter.** A notice is not a line in a footer
somebody chose to look at: it is the one thing on screen a person must not read past, so
it wears its tone as a wash across the whole row rather than in a dot beside the words —
amber while another writer is at work, red while something is owed. A declared count fills
that band from the left and says how far in words at the right, next to the verb, which is
what a 4 px strip could not do: a strip at nought per cent is a hairline nobody reads as a
meter, where an amber band that says *0%* is plainly something that fills. Plain
information has no tone and so no band, which is what a claim that has gone quiet
becomes — it stops shouting without leaving the screen.

**A notice is data, and showing the same notice twice is nothing.** The owner recomputes
its notice whenever it likes — a poll, a settle — and hands it over; a row that would not
change is left alone, so a two-second poll costs no repaint and nothing under the pointer
moves. That is what makes it safe to drive from a timer.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.signalling import Spinner, StatusLine, Tone, tone_colour
from dplanner.theme.icons import ICON_SIZE
from dplanner.theme.tokens import (
    CONTROL_GAP,
    FIELD_GAP,
    PANEL_MARGIN,
    RADIUS_SM,
    ROW_PADDING_H,
    ROW_PADDING_V,
)
from dplanner.theme.tones import at_alpha

# The band, and the part of it a declared count has filled: the tone's own shade at two
# weights (DESIGN.md's exception #2 — a semantic tint is a low-alpha constant, so it reads
# on every theme). Low enough that secondary words keep their contrast over either, and far
# enough apart that the boundary between them is the meter without a second colour.
BAND_ALPHA = 38
FILLED_ALPHA = 92


@dataclass(frozen=True)
class Notice:
    """One standing fact: whose it is, what it says, and the one thing to do about it.

    ``tone`` is the band the row is washed in — ``warn`` while somebody else is at work,
    ``error`` while something is owed, and plain ``info`` for a fact that has stopped
    needing the eye. ``busy`` leads the words with the turning arc — the application's one
    motion for *something is running here*. ``fraction`` fills the band from the left and
    puts the percentage beside the verb when it is 0..1; below zero the band is plain,
    which is the honest picture for work with no declared count. ``action`` is the words on
    a quiet verb at the right end, ``tip`` what it explains on hover, and ``act`` what it
    runs.
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
    """One notice, drawn: a band in its tone carrying the arc, the words, how far it has
    come, and the verb."""

    def __init__(self, notice: Notice, parent: QWidget) -> None:
        super().__init__(parent)
        line = QHBoxLayout(self)
        line.setContentsMargins(ROW_PADDING_H, ROW_PADDING_V, ROW_PADDING_H, ROW_PADDING_V)
        line.setSpacing(CONTROL_GAP)

        # A bare label is all the arc needs to stand on its own — DESIGN.md's *Signalling*.
        self._arc = QLabel(self)
        self._arc.setFixedSize(ICON_SIZE, ICON_SIZE)
        self._spinner = Spinner(self).attach(self._arc)
        self._words = StatusLine(self)
        self._words.setWordWrap(True)
        # How far, in words, where the eye already goes for the verb. Its room is the widest
        # reading it can ever hold, so the verb beside it does not step sideways as the
        # count climbs past nine and past ninety-nine.
        self._percent = QLabel(self)
        self._percent.setObjectName("NoticePercent")
        self._percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._percent.setMinimumWidth(self._percent.fontMetrics().horizontalAdvance("100%"))
        self._button = QToolButton(self)
        self._button.setObjectName("ToolbarButton")
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        line.addWidget(self._arc)
        line.addWidget(self._words, 1)
        line.addWidget(self._percent)
        line.addWidget(self._button)

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
        counted = self._counted()
        self._percent.setText(f"{round(notice.fraction * 100)}%" if counted else "")
        self._percent.setVisible(counted)
        self.update()  # The band is painted from the notice, so a new notice is a new band.

    def notice(self) -> Notice:
        return self._notice

    def dispose(self) -> None:
        self._spin(False)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        """The band, and the part of it that is done. Plain information paints nothing and
        keeps the bar's own ground: a fact nobody must act on earns no colour."""
        shade = tone_colour(self._notice.tone)
        if shade is None:
            return
        band = QRectF(self.rect())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(at_alpha(shade, BAND_ALPHA))
        painter.drawRoundedRect(band, RADIUS_SM, RADIUS_SM)
        if self._counted():
            # The same rounded band, clipped to what is done: the fill keeps the band's
            # left corners and ends on a straight edge, which is where the meter reads.
            painter.setClipRect(
                QRectF(band.left(), band.top(), band.width() * self._notice.fraction, band.height())
            )
            painter.setBrush(at_alpha(shade, FILLED_ALPHA))
            painter.drawRoundedRect(band, RADIUS_SM, RADIUS_SM)
        painter.end()

    def _counted(self) -> bool:
        """Whether the owner declared how far along this is."""
        return 0.0 <= self._notice.fraction <= 1.0

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
        # *Qt objects* rules; the `suite-crash` skill has the crash).
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
