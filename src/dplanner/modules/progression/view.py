"""The Ready-to-start board: a header that says how far, columns that say what moves.

Pure rendering — the domain's :class:`~dplanner.domain.progression.Progression` arrives
computed and the board redraws wholesale, so nothing here can disagree with the model.
Callbacks carry every gesture out: selecting, opening details, the context menu, ticking a
ready step and the *Run Agents* button all belong to the activity, which is what keeps
this file free of commands and of other modules' names.

**A ready step is ticked, and the lane runs the ticked ones.** Each ready card carries a
check box at its top left, and the Ready lane's caption row ends in one *Run N Agents*
button — a face that drops the Step menu's own Run Agent child down (the profiles, then
the way to Settings), so the board offers exactly what the menu does and never a copy.
The ticks survive a rebuild (the set is kept here by step id and pruned to what is still
ready) and are what the button counts.

The segment tints are low-alpha constant ``QColor``s — DESIGN.md's deliberate exception
for semantic status colours, the same stance as the sync view's diff highlighter. The
track and every text colour come from the live palette at paint time, so the board owes
no ``PaletteChange`` hook: nothing stores a colour.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import StepId
from dplanner.domain.progression import Progression
from dplanner.theme.icons import ICON_SIZE, KEY_BADGE_W
from dplanner.theme.tokens import (
    CAPTION_GAP,
    CONTROL_HEIGHT,
    FIELD_GAP,
    ROW_LINE_GAP,
    SECTION_GAP,
)

# The page metrics, from the one table (DESIGN.md's *Tokens*): a card's and a lane's
# padding are a section's gap, a row sits a field's gap from the next, and a badge stands a
# caption's gap from the title it leads.
CARD_PADDING = SECTION_GAP
BADGE_GAP = CAPTION_GAP
LANE_PADDING = SECTION_GAP
COLUMN_GAP = SECTION_GAP
ROW_GAP = FIELD_GAP
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
    """The Run Agents button as the activity resolved it over the ticked steps: its
    words, whether, why not, and the menu it drops down."""

    label: str  # "Run 2 Agents" — the count is the face.
    enabled: bool
    reason: str  # The tooltip: the gate's own reason when disabled, a hint otherwise.
    fill: Callable[[QMenu], None]  # The choices, read fresh every time the menu opens.


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
    """The big number and the bar under it.

    Two lines used to stand under the bar — the same counts in words, then the same
    progress again in estimated days. The bar *is* those counts, drawn to scale, and a
    board whose job is to say what to start next should not spend three sentences on how
    far along the project is. The terminal still prints both (``dplanner progression
    show``), where a line costs nothing and there is no bar to read.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ROW_GAP)

        top = QHBoxLayout()
        layout.addLayout(top)  # Joined before it is filled: no layout-item wrappers survive.
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

        self.bar = SegmentedBar(self)
        layout.addWidget(self.bar)

    def show_progress(self, progress: Progression) -> None:
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


class StepCard(QFrame):
    """One step on the board: the what on line one, the why on line two.

    Wears the ``#ToolCard`` well so the board's rows and the panel's cards read alike —
    the box is the stylesheet's, and no colour is stored here.

    A milestone leads with its **key as a badge**, in its own shade of the project's colour
    map — the same mark its row wears in the order table and the same shade its card wears
    on the canvas (DESIGN.md's *Tables*). It is the one colour on the board that is not a
    status: a lane already says where the work stands, and this says what it is leading to.
    """

    def __init__(
        self,
        step_id: StepId,
        title: str,
        detail: str,
        *,
        badge: QIcon | None = None,
        dimmed: bool = False,
        select: Callable[[StepId], None],
        details: Callable[[StepId], None],
        menu: Callable[[StepId, QPoint], None],
        tick: Callable[[StepId, bool], None] | None = None,
        ticked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ToolCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.step_id = step_id
        self._select = select
        self._details = details
        self._menu = menu
        self._before_press = ticked  # What a double click puts the tick back to.

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(ROW_LINE_GAP)

        # The tick stands beside the card's words, and the words are one column: the title
        # over what it says about itself. A second line that began under the tick would be
        # indented from the name it belongs to, and the tick would float beside the pair
        # rather than beside line one.
        heading = QHBoxLayout()
        layout.addLayout(heading)  # Joined before it is filled, as every row here is.
        heading.setSpacing(BADGE_GAP)
        self.check_box: QCheckBox | None = None
        if tick is not None:
            self.check_box = QCheckBox(self)
            self.check_box.setObjectName("ProgressionTick")
            self.check_box.setToolTip("Include this step when running agents")
            self.check_box.setChecked(ticked)
            self.check_box.toggled.connect(lambda on: tick(step_id, on))
            heading.addWidget(self.check_box, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        heading.addLayout(column, 1)
        column.setSpacing(ROW_LINE_GAP)
        title_row = QHBoxLayout()
        column.addLayout(title_row)
        title_row.setSpacing(BADGE_GAP)
        if badge is not None:
            mark = QLabel(self)
            mark.setPixmap(badge.pixmap(QSize(KEY_BADGE_W, ICON_SIZE)))
            mark.setAlignment(Qt.AlignmentFlag.AlignTop)
            title_row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        self.title = QLabel(title, self)
        self.title.setWordWrap(True)
        if dimmed:  # An upcoming step is present without asking to be read.
            self.title.setObjectName("InspectorNote")
        title_row.addWidget(self.title, 1)

        self.detail = QLabel(detail, self)
        self.detail.setObjectName("InspectorNote")
        self.detail.setWordWrap(True)
        self.detail.setVisible(bool(detail))
        column.addWidget(self.detail)

        if self.check_box is not None:
            # A check box centres its indicator in its own height, so a box one line tall
            # puts the mark on the title's first line however many lines the title wraps to.
            self.check_box.setFixedHeight(QFontMetrics(self.title.font()).height())

    def select(self) -> None:
        """Make this card's step the selection — the click's meaning, callable by name."""
        self._select(self.step_id)

    def toggle(self) -> None:
        """Tick the card, or untick it. A click anywhere on a ready card does this: the box
        is a thirteen-pixel target and the card is the thing being chosen — and on this lane
        choosing a card *is* including it in the run. A card with no tick has nothing to do
        here (the lane is not a run) and only publishes its step."""
        if self.check_box is not None:
            self.check_box.setChecked(not self.check_box.isChecked())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._select(self.step_id)
            self._before_press = self.check_box is not None and self.check_box.isChecked()
            self.toggle()
        elif event.button() == Qt.MouseButton.RightButton:
            self._select(self.step_id)
            self._menu(self.step_id, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        """Open the card. The gesture means "show me", not "tick", so the tick goes back to
        what it was before the press that began it.

        It ends here rather than in ``super()``: Qt's own default for a double click is to
        call ``mousePressEvent`` again, which on this card would tick what was just unticked.
        """
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        if self.check_box is not None:
            self.check_box.setChecked(self._before_press)
        self._details(self.step_id)


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

        # The caption row is a control's height in every lane, so the three captions sit
        # level whether or not a lane ends its row in a button.
        self._caption_row = QHBoxLayout()
        layout.addLayout(self._caption_row)  # Joined before it is filled.
        self._caption_row.setSpacing(ROW_GAP)
        self.caption = QLabel(caption, self)
        self.caption.setObjectName("InspectorCaption")
        self.caption.setMinimumHeight(CONTROL_HEIGHT)
        self._caption_row.addWidget(self.caption, 1, Qt.AlignmentFlag.AlignVCenter)

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

    def add_tool(self, widget: QWidget) -> None:
        """A control at the caption row's right end, level with the caption."""
        self._caption_row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

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
        # double delete waiting for a gc pass (the `suite-crash` skill).
        return [widget for widget in self._held if isinstance(widget, StepCard)]

    def titles(self) -> list[str]:
        return [card.title.text() for card in self.cards()]


class ProgressionBoard(QWidget):
    """The whole surface: header over three columns, rebuilt wholesale on every change.

    ``run_control`` answers for a list of ticked step ids — None means a build without
    an agent, and then no card carries a tick and the Ready lane no button: the
    capability is absent, not greyed.
    """

    def __init__(
        self,
        *,
        select: Callable[[StepId], None],
        details: Callable[[StepId], None],
        menu: Callable[[StepId, QPoint], None],
        run_control: Callable[[list[StepId]], RunControl | None],
        milestone_badge: Callable[[StepId], QIcon | None] = lambda _step_id: None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._select = select
        self._details = details
        self._menu = menu
        self._run_control = run_control
        self._milestone_badge = milestone_badge
        self._ready_ids: list[StepId] = []  # The ready lane's cards, top to bottom.
        self._ticked: set[StepId] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(COLUMN_GAP)

        self.header = ProgressHeader(self)
        layout.addWidget(self.header)

        columns = QHBoxLayout()
        layout.addLayout(columns, 1)  # Joined before it is filled, as every row here is.
        columns.setSpacing(COLUMN_GAP)
        self.running = StatusColumn("Running", self)
        self.ready = StatusColumn("Ready", self)
        self.upcoming = StatusColumn("Up next", self)
        for column in (self.running, self.ready, self.upcoming):
            columns.addWidget(column, 1)

        # Run N Agents: a face that drops the Run Agent child menu down. A ToolbarButton
        # with the room the theme keeps for an arrow; InstantPopup, since the face names
        # a family and picking one member is the verb.
        self.run_button: QToolButton | None = None
        if run_control([]) is not None:
            self.run_button = QToolButton(self.ready)
            self.run_button.setObjectName("ToolbarButton")
            self.run_button.setProperty("hasMenu", True)
            self.run_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.run_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.run_button.setFixedHeight(CONTROL_HEIGHT)
            self.run_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            popup = QMenu(self.run_button)
            popup.aboutToShow.connect(lambda: self._fill_run_menu(popup))
            self.run_button.setMenu(popup)
            self.ready.add_tool(self.run_button)
            self._refresh_run()

    def ticked(self) -> list[StepId]:
        """The ticked ready steps, in the lane's order."""
        return [step_id for step_id in self._ready_ids if step_id in self._ticked]

    def run_menu(self) -> QMenu | None:
        """The Run Agents dropdown as it would open right now — a test's way in."""
        popup = self.run_button.menu() if self.run_button is not None else None
        if popup is not None:
            self._fill_run_menu(popup)
        return popup

    def _fill_run_menu(self, popup: QMenu) -> None:
        popup.clear()
        control = self._run_control(self.ticked())
        if control is not None:
            control.fill(popup)

    def _refresh_run(self) -> None:
        if self.run_button is None:
            return
        control = self._run_control(self.ticked())
        if control is None:
            return
        self.run_button.setText(control.label)
        self.run_button.setEnabled(control.enabled)
        self.run_button.setToolTip(control.reason)

    def _on_tick(self, step_id: StepId, on: bool) -> None:
        if on:
            self._ticked.add(step_id)
        else:
            self._ticked.discard(step_id)
        self._refresh_run()

    def show_progress(self, progress: Progression) -> None:
        self.header.show_progress(progress)
        self._ready_ids = [launchable.step.id for launchable in progress.ready[:MAX_READY]]
        self._ticked &= set(self._ready_ids)  # A step that left the lane leaves the run.

        def card(
            step_id: StepId,
            title: str,
            detail: str,
            *,
            dimmed: bool = False,
            with_tick: bool = False,
        ) -> StepCard:
            return StepCard(
                step_id,
                title or "Untitled step",
                detail,
                badge=self._milestone_badge(step_id),
                dimmed=dimmed,
                select=self._select,
                details=self._details,
                menu=self._menu,
                tick=self._on_tick if with_tick and self.run_button is not None else None,
                ticked=step_id in self._ticked,
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
            self.ready.add(card(launchable.step.id, launchable.step.title, detail, with_tick=True))
        if len(progress.ready) > MAX_READY:
            self.ready.say(f"+{len(progress.ready) - MAX_READY} more")
        if not progress.ready:
            if not progress.total:
                self.ready.say("No steps yet.")
            elif progress.percent == 100.0:
                self.ready.say("All done.")
            else:
                self.ready.say("Nothing to start — everything is running, blocked, or waiting.")

        self._refresh_run()

        self.upcoming.clear()
        for coming in progress.upcoming:
            names = ", ".join(step.title or "Untitled step" for step in coming.after)
            detail = f"After {names}" if names else ""
            self.upcoming.add(card(coming.step.id, coming.step.title, detail, dimmed=True))
        if not progress.upcoming:
            self.upcoming.say("Nothing queued.")
