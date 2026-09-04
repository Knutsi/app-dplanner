"""The progression board: a header that says how far, columns that say what moves.

Pure rendering — the domain's :class:`~dplanner.domain.progression.Progression` arrives
computed and the board redraws wholesale, so nothing here can disagree with the model.
Callbacks carry every gesture out: selecting, opening details, the context menu and the Run
Agent button all belong to the activity, which is what keeps this file free of commands
and of other modules' names.

The segment tints are low-alpha constant ``QColor``s — DESIGN.md's deliberate exception
for semantic status colours, the same stance as the sync view's diff highlighter. The
track and every text colour come from the live palette at paint time, so the board owes
no ``PaletteChange`` hook: nothing stores a colour.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import StepId
from dplanner.domain.progression import Progression

CARD_PADDING = 12
LANE_PADDING = 12
COLUMN_GAP = 12
ROW_GAP = 8
BAR_HEIGHT = 10
PERCENT_POINT_SIZE = 26

# Three lanes at a comfortable card width, plus the gaps. Past this the board stops
# stretching and sits centred — a lane wider than its cards' text says nothing more.
BOARD_MAX_WIDTH = 1180

# Beyond this many ready cards the rest fold into "+N more" — a recommendation is a
# short list, and the CLI is the reader that wants everything.
MAX_READY = 8

# Semantic status tints, constant across themes (DESIGN.md deliberate exception #2).
# The alpha is higher than the sync view's region tints because a 10 px bar has no area
# to accumulate colour in the way a highlighted line does.
DONE_TINT = QColor(46, 160, 67, 200)
RUNNING_TINT = QColor(121, 162, 227, 200)
ATTENTION_TINT = QColor(248, 81, 73, 200)
READY_TINT = QColor(210, 153, 34, 200)
TRACK_ALPHA = 60


@dataclass(frozen=True)
class RunControl:
    """The Run Agent button as the activity resolved it: whether, why not, and how."""

    enabled: bool
    reason: str  # The action's current label — a disabled one carries the reason.
    run: Callable[[], None]


class SegmentedBar(QWidget):
    """Done, running, attention and ready as proportional segments on a waiting track."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._counts: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0)

    def set_counts(self, done: int, running: int, attention: int, ready: int, waiting: int) -> None:
        self._counts = (done, running, attention, ready, waiting)
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        total = sum(self._counts)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), BAR_HEIGHT / 2, BAR_HEIGHT / 2)
        painter.setClipPath(clip)

        track = self.palette().color(QPalette.ColorRole.Text)
        track.setAlpha(TRACK_ALPHA)
        painter.fillRect(self.rect(), track)
        if not total:
            return

        done, running, attention, ready, _waiting = self._counts
        x = 0.0
        width = float(self.rect().width())
        for count, tint in (
            (done, DONE_TINT),
            (running, RUNNING_TINT),
            (attention, ATTENTION_TINT),
            (ready, READY_TINT),
        ):
            if not count:
                continue
            span = width * count / total
            painter.fillRect(QRectF(x, 0.0, span, float(BAR_HEIGHT)), tint)
            x += span


class ProgressHeader(QWidget):
    """The big number, the bar under it, and the counts that explain the bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ROW_GAP)

        top = QHBoxLayout()
        top.setSpacing(ROW_GAP)
        self.percent = QLabel("0%", self)
        font = QFont(self.percent.font())
        font.setPointSize(PERCENT_POINT_SIZE)
        font.setBold(True)
        self.percent.setFont(font)
        top.addWidget(self.percent, 0, Qt.AlignmentFlag.AlignBaseline)
        self.summary = QLabel("", self)
        self.summary.setObjectName("InspectorNote")
        top.addWidget(self.summary, 0, Qt.AlignmentFlag.AlignBaseline)
        top.addStretch(1)
        layout.addLayout(top)

        self.bar = SegmentedBar(self)
        layout.addWidget(self.bar)

        self.counts = QLabel("", self)
        self.counts.setObjectName("InspectorNote")
        self.counts.setWordWrap(True)
        layout.addWidget(self.counts)

    def show_progress(self, progress: Progression, weighted: tuple[float, float] | None) -> None:
        self.percent.setText(f"{progress.percent:.0f}%")
        self.summary.setText(
            f"{len(progress.done)} of {progress.total} steps done"
            if progress.total
            else "No steps yet."
        )
        self.bar.set_counts(
            len(progress.done),
            len(progress.running),
            len(progress.attention),
            len(progress.ready),
            len(progress.upcoming) + len(progress.waiting),
        )
        parts = [
            phrase
            for count, phrase in (
                (len(progress.done), f"{len(progress.done)} done"),
                (len(progress.running), f"{len(progress.running)} running"),
                (
                    len(progress.attention),
                    f"{len(progress.attention)} needs attention"
                    if len(progress.attention) == 1
                    else f"{len(progress.attention)} need attention",
                ),
                (len(progress.ready), f"{len(progress.ready)} ready"),
                (
                    len(progress.upcoming) + len(progress.waiting),
                    f"{len(progress.upcoming) + len(progress.waiting)} waiting",
                ),
            )
            if count
        ]
        lines = [" · ".join(parts)] if parts else []
        if weighted is not None:
            finished, total = weighted
            lines.append(f"{finished:g} of {total:g} estimated days done")
        self.counts.setText("\n".join(lines))
        self.counts.setVisible(bool(lines))


class StepCard(QFrame):
    """One step on the board: the what on line one, the why on line two.

    Wears the ``#ToolCard`` well so the board's rows and the panel's cards read alike —
    the box is the stylesheet's, and no colour is stored here.
    """

    def __init__(
        self,
        step_id: StepId,
        title: str,
        detail: str,
        *,
        dimmed: bool = False,
        select: Callable[[StepId], None],
        details: Callable[[StepId], None],
        menu: Callable[[StepId, QPoint], None],
        run: RunControl | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ToolCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.step_id = step_id
        self._select = select
        self._details = details
        self._menu = menu

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(4)

        self.title = QLabel(title, self)
        self.title.setWordWrap(True)
        if dimmed:  # An upcoming step is present without asking to be read.
            self.title.setObjectName("InspectorNote")
        layout.addWidget(self.title)

        self.detail = QLabel(detail, self)
        self.detail.setObjectName("InspectorNote")
        self.detail.setWordWrap(True)
        self.detail.setVisible(bool(detail))
        layout.addWidget(self.detail)

        self.run_button: QPushButton | None = None
        if run is not None:
            self.run_button = QPushButton("Run Agent", self)
            self.run_button.setEnabled(run.enabled)
            # The gate's own words: a disabled button teaches its precondition.
            self.run_button.setToolTip(run.reason)
            self.run_button.clicked.connect(run.run)
            holder = QHBoxLayout()
            holder.addWidget(self.run_button)
            holder.addStretch(1)
            layout.addLayout(holder)

    def select(self) -> None:
        """Make this card's step the selection — the click's meaning, callable by name."""
        self._select(self.step_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._select(self.step_id)
        elif event.button() == Qt.MouseButton.RightButton:
            self._select(self.step_id)
            self._menu(self.step_id, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._details(self.step_id)
        super().mouseDoubleClickEvent(event)


class StatusColumn(QFrame):
    """One vertical list: a caption, its cards, and words when there are none.

    A lane, not a bare stack: the ``#ProgressionLane`` rule paints it ``$BG_ELEVATED``,
    which is what gives the list a shape on a tab page — and puts the ``#ToolCard`` rows
    inside on the elevated ground that well was designed for (DESIGN.md §Cards).
    """

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProgressionLane")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(LANE_PADDING, LANE_PADDING, LANE_PADDING, LANE_PADDING)
        layout.setSpacing(ROW_GAP)

        self.caption = QLabel(caption, self)
        self.caption.setObjectName("InspectorCaption")
        layout.addWidget(self.caption)

        scroll = QScrollArea(self)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        content = QWidget()
        self._rows = QVBoxLayout(content)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(ROW_GAP)
        self._rows.addStretch(1)
        self._held: list[QWidget] = []  # What add() laid out, top to bottom.
        scroll.setWidget(content)
        # The page paints the background; the viewport's default Base fill would hide it.
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        layout.addWidget(scroll, 1)

    def clear(self) -> None:
        for widget in self._held:
            self._rows.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self._held.clear()

    def add(self, widget: QWidget) -> None:
        self._rows.insertWidget(self._rows.count() - 1, widget)  # Before the trailing stretch.
        self._held.append(widget)

    def say(self, words: str) -> None:
        """The empty state: a section empty for now says so rather than vanishing."""
        note = QLabel(words, self)
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)
        self.add(note)

    def cards(self) -> list[StepCard]:
        # The list, never the layout: a QLayoutItem wrapper ``itemAt()`` hands out is a
        # double delete waiting for a gc pass (CLAUDE.md's crash notes).
        return [widget for widget in self._held if isinstance(widget, StepCard)]

    def titles(self) -> list[str]:
        return [card.title.text() for card in self.cards()]


class ProgressionBoard(QWidget):
    """The whole surface: header over three columns, rebuilt wholesale on every change."""

    def __init__(
        self,
        *,
        select: Callable[[StepId], None],
        details: Callable[[StepId], None],
        menu: Callable[[StepId, QPoint], None],
        run_control: Callable[[StepId], RunControl | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._select = select
        self._details = details
        self._menu = menu
        self._run_control = run_control

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(COLUMN_GAP)

        self.header = ProgressHeader(self)
        layout.addWidget(self.header)

        columns = QHBoxLayout()
        columns.setSpacing(COLUMN_GAP)
        self.running = StatusColumn("Running", self)
        self.ready = StatusColumn("Ready", self)
        self.upcoming = StatusColumn("Up next", self)
        for column in (self.running, self.ready, self.upcoming):
            columns.addWidget(column, 1)
        layout.addLayout(columns, 1)

    def show_progress(self, progress: Progression, weighted: tuple[float, float] | None) -> None:
        self.header.show_progress(progress, weighted)

        def card(
            step_id: StepId,
            title: str,
            detail: str,
            *,
            dimmed: bool = False,
            with_run: bool = False,
        ) -> StepCard:
            return StepCard(
                step_id,
                title or "Untitled step",
                detail,
                dimmed=dimmed,
                select=self._select,
                details=self._details,
                menu=self._menu,
                run=self._run_control(step_id) if with_run else None,
            )

        self.running.clear()
        for step in progress.attention:
            self.running.add(card(step.id, step.title, "⚠ Blocked — needs attention"))
        for step in progress.running:
            self.running.add(card(step.id, step.title, "In progress"))
        if not progress.attention and not progress.running:
            self.running.say("Nothing running.")

        self.ready.clear()
        for launchable in progress.ready[:MAX_READY]:
            detail = f"Unblocks {launchable.unlocks}" if launchable.unlocks else ""
            self.ready.add(card(launchable.step.id, launchable.step.title, detail, with_run=True))
        if len(progress.ready) > MAX_READY:
            self.ready.say(f"+{len(progress.ready) - MAX_READY} more")
        if not progress.ready:
            if not progress.total:
                self.ready.say("No steps yet.")
            elif progress.percent == 100.0:
                self.ready.say("All done.")
            else:
                self.ready.say("Nothing to start — everything is running, blocked, or waiting.")

        self.upcoming.clear()
        for coming in progress.upcoming:
            names = ", ".join(step.title or "Untitled step" for step in coming.after)
            detail = f"After {names}" if names else ""
            self.upcoming.add(card(coming.step.id, coming.step.title, detail, dimmed=True))
        if not progress.upcoming:
            self.upcoming.say("Nothing queued.")
