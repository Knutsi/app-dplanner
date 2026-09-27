"""Home's page: the getting-started guide, centred, over a garden that says what DPlanner does.

The Home tab's widget. It follows what it shows for as long as it lives and lets go when Qt
destroys it, which is when the tab host drops a closed tab's page.

**The guide's buttons are the verbs themselves.** Each is restated from its ``ActionSpec`` on
every context change and runs through the registry, as a menu entry does — so a verb that
needs a project greys in its own words until one is picked in the index.

**The garden is the one ornament in the application that moves** (DESIGN.md's *Focus and
motion*): a cloud wearing the robot glyph rains on a row of seedlings, and what it rains on
blooms. It is painted from ``garden.py``'s state, ticks only while it is on screen, and goes
when the person closes it — Settings ▸ Home brings it back.
"""

import math
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QShowEvent,
)
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.action_registry import ActionState
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import SCOPE_ACTIVITY, ContextNode, activity_uri
from dplanner.framework.row_well import RowWell, WellRow
from dplanner.framework.toolbar import action_words
from dplanner.framework.widgets import EDITOR_MEASURE, GlyphButton, caption, centered_column
from dplanner.modules.home.garden import PLACES, REACH, Garden
from dplanner.modules.home.guide import GUIDE, GuideStep
from dplanner.modules.home.settings_page import garden_wanted, want_garden
from dplanner.theme.icons import close_icon, paint_glyph
from dplanner.theme.tokens import CAPTION_GAP, PANEL_MARGIN, SECONDARY_ALPHA
from dplanner.theme.tones import (
    BADGE_BORDER,
    CHIP_ATTENTION_BORDER,
    CHIP_INFO_BORDER,
    FEATURE_BORDER,
    GOOD_BORDER,
    at_alpha,
)

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.home.module import HomeDeps

HOME_KIND = "home"
GUIDE_CAPTION = "Getting started"
HIDE_GARDEN = "Hide the garden — Settings ▸ Home brings it back"

# The garden's metrics, in pixels. A strip rather than a scene: it sits under the guide and
# never competes with it for height.
GARDEN_H = 128
GROUND = 18  # From the bottom edge to the soil line.
STEM_MAX = 60
CLOUD_W, CLOUD_H = 88, 38
CLOUD_TOP = 8
ROBOT = 18  # The glyph's square, inside the cloud.
DROPS = 7
FALL_S = 0.9  # How long a drop takes from the cloud to the soil.
TICK_MS = 33  # About thirty frames a second: smooth, and nothing to a machine.
# The flowers wear the plan's own tones — a milestone's violet, a feature's teal, a
# review's amber, an agent's blue — and the rain is the agent's blue. Constants that read on
# every theme (DESIGN.md's exception #2), never a theme's opaque colour.
BLOOMS = (BADGE_BORDER, FEATURE_BORDER, CHIP_ATTENTION_BORDER, CHIP_INFO_BORDER)
RAIN = at_alpha(CHIP_INFO_BORDER, 170)


class GuideRow(WellRow):
    """One step of the guide: its title, its words under it, and its verb at the right."""

    def __init__(self, step: GuideStep, page: "HomePage") -> None:
        super().__init__(step.title)
        self.set_note(step.words)
        self.button = self.add_button("", lambda: page.run(step))


class HomePage(QWidget):
    def __init__(
        self, deps: "HomeDeps", garden_changed: Signal[()], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._deps = deps
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QWidget(self)
        column = QVBoxLayout(body)
        column.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        column.setSpacing(CAPTION_GAP)
        column.addStretch(1)
        column.addWidget(caption(GUIDE_CAPTION, body))
        self.guide = RowWell(body)
        # As tall as its steps, so the guide sits centred rather than filling the page.
        self.guide.setSizeAdjustPolicy(RowWell.SizeAdjustPolicy.AdjustToContents)
        column.addWidget(self.guide)
        column.addStretch(1)
        layout.addWidget(centered_column(body, EDITOR_MEASURE), 1)

        self.garden = GardenView(self, hide=lambda: want_garden(False, garden_changed))
        layout.addWidget(self.garden)

        unsubscribe = [
            deps.context.changed.connect(lambda _context: self.restate()),
            garden_changed.connect(self._show_garden),
        ]
        self.destroyed.connect(lambda: [each() for each in unsubscribe])
        self.restate()
        self._show_garden()

    # -- the guide -----------------------------------------------------------------------------

    def restate(self) -> None:
        """Say what each verb says right now: its words, whether it runs, and why not. A
        verb this build does not have (hidden, not greyed) takes its step with it."""
        context = self._deps.context.current()
        states = {step: self._deps.actions.spec(step.action).state(context) for step in GUIDE}
        self.guide.reconcile(
            [step for step in GUIDE if states[step].visible],
            lambda step: GuideRow(step, self),
            lambda step, row: self._restate(step, row, states[step]),
        )

    def _restate(self, step: GuideStep, row: GuideRow, state: ActionState) -> None:
        words, tip = action_words(self._deps.actions.spec(step.action), state)
        row.button.setText(words)
        row.button.setToolTip(tip)
        row.button.setEnabled(state.enabled)

    def run(self, step: GuideStep) -> None:
        self._deps.actions.run(step.action, self._deps.context.current())

    def _show_garden(self) -> None:
        self.garden.setVisible(garden_wanted())


class GardenView(QWidget):
    """Paints a :class:`Garden` and moves it on while it is on screen.

    The clock runs only between a show and a hide, so a Home tab in the background costs
    nothing, and a test that never shows a window never starts it. A tick measures the time
    since the last one rather than trusting the interval, and a long gap — a stall, a
    closed laptop lid — is taken as one short step rather than a leap across a season.
    """

    def __init__(self, parent: QWidget | None = None, *, hide: Callable[[], None]) -> None:
        super().__init__(parent)
        self.setObjectName("Garden")
        self.setFixedHeight(GARDEN_H)
        self.state = Garden()
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

        corner = QHBoxLayout(self)
        corner.setContentsMargins(0, PANEL_MARGIN // 2, PANEL_MARGIN // 2, 0)
        corner.addStretch(1)
        self.close_button = GlyphButton("", close_icon, self, tip=HIDE_GARDEN)
        self.close_button.clicked.connect(lambda _checked=False: hide())
        corner.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)

    def running(self) -> bool:
        return self._timer.isActive()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        self._clock.start()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt override
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self.state.advance(min(self._clock.restart() / 1000.0, 0.1), self.reach())
        self.update()

    def reach(self) -> float:
        """The rain's half-width as a fraction of the garden's, as it is painted."""
        return max(REACH, CLOUD_W * 0.4 / max(1, self.width()))

    # -- painting ------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = self.palette().color(QPalette.ColorRole.Text)
        ground = self.height() - GROUND
        painter.setPen(QPen(at_alpha(ink, 40), 1))
        painter.drawLine(QPointF(0, ground + 0.5), QPointF(self.width(), ground + 0.5))
        for index, grown in enumerate(self.state.growth):
            self._flower(painter, index, grown, ground)
        self._cloud(painter, ink, ground)
        painter.end()

    def _flower(self, painter: QPainter, index: int, grown: float, ground: float) -> None:
        t = self.state.t
        base = QPointF(PLACES[index] * self.width(), ground)
        height = 4 + grown * STEM_MAX
        sway = math.sin(2 * math.pi * t / 5 + index * 1.3) * 3 * grown
        tip = QPointF(base.x() + sway, ground - height)
        stem = QPainterPath(base)
        stem.quadTo(QPointF(base.x(), ground - height * 0.6), tip)
        painter.setPen(QPen(GOOD_BORDER, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(stem)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(at_alpha(GOOD_BORDER, 120))
        # Leaves come with height: a pair at the middle once there is a middle to hold them.
        leaf = min(1.0, max(0.0, (grown - 0.2) / 0.3))
        if leaf > 0:
            middle = QPointF(base.x() + sway * 0.4, ground - height * 0.45)
            for side in (-1, 1):
                painter.save()
                painter.translate(middle)
                painter.rotate(side * 50)
                painter.drawEllipse(QRectF(-2.5 * leaf, -9 * leaf, 5 * leaf, 9 * leaf))
                painter.restore()
        # The bloom opens over the last third of the growth.
        bloom = min(1.0, max(0.0, (grown - 0.65) / 0.35))
        if bloom > 0:
            painter.setBrush(at_alpha(BLOOMS[index % len(BLOOMS)], 210))
            radius = 8 * bloom
            for petal in range(5):
                angle = 2 * math.pi * petal / 5 + t * 0.2
                centre = QPointF(
                    tip.x() + math.cos(angle) * radius * 0.8,
                    tip.y() + math.sin(angle) * radius * 0.8,
                )
                painter.drawEllipse(centre, radius * 0.6, radius * 0.6)
            painter.setBrush(at_alpha(CHIP_ATTENTION_BORDER, 230))
            painter.drawEllipse(tip, 2.5 * bloom, 2.5 * bloom)

    def _cloud(self, painter: QPainter, ink: QColor, ground: float) -> None:
        t = self.state.t
        centre_x = self.state.cloud_x() * self.width()
        top = CLOUD_TOP + 2 * math.sin(2 * math.pi * t / 6)
        left = centre_x - CLOUD_W / 2
        bottom = top + CLOUD_H
        # Rain first, so it falls from behind the cloud rather than across it.
        painter.setPen(QPen(RAIN, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for drop in range(DROPS):
            fall = (t / FALL_S + drop * 0.37) % 1.0
            x = left + CLOUD_W * (0.18 + 0.64 * drop / (DROPS - 1)) + 2 * math.sin(drop * 2.1)
            y = bottom - 4 + fall * (ground - bottom - 6)
            painter.setOpacity(1.0 - fall**3)
            painter.drawLine(QPointF(x, y), QPointF(x, y + 6))
        painter.setOpacity(1.0)
        puffs = QPainterPath()
        puffs.addRoundedRect(QRectF(left, top + CLOUD_H * 0.4, CLOUD_W, CLOUD_H * 0.6), 12, 12)
        puffs.addEllipse(QRectF(left + 10, top + 8, CLOUD_W * 0.42, CLOUD_H * 0.8))
        puffs.addEllipse(QRectF(left + CLOUD_W * 0.36, top, CLOUD_W * 0.48, CLOUD_H * 0.9))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(at_alpha(ink, 26))
        painter.drawPath(puffs.simplified())
        glyph = QRectF(centre_x - ROBOT / 2, top + (CLOUD_H - ROBOT) / 2 + 2, ROBOT, ROBOT)
        paint_glyph(painter, glyph, "robot", at_alpha(ink, SECONDARY_ALPHA))


class HomeActivity(ActivityBase):
    """The Home tab: the guide and the garden, kept open beside the others."""

    def __init__(self, deps: "HomeDeps", garden_changed: Signal[()]) -> None:
        self._context = deps.context
        self.uri = activity_uri(HOME_KIND)
        self.title = "Home"
        self.widget = HomePage(deps, garden_changed)

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))
