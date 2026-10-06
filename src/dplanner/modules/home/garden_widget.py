"""Painting the garden: the plan in bloom, drawn soft and moved smoothly.

``garden.py`` decides what *is* — which seeds are ready, where each agent is, how far a
flower has opened. This decides how it *looks*, and owns what is only for the eye: the
glitter an agent sprinkles, the pollen a garden at rest lets go, the petals that fall when
the season turns. It ticks on a :class:`~dplanner.framework.motion.clock.FrameClock` that
runs only while the garden is on screen.

**Built to be cheap at sixty frames a second.** The sky, the hills and the soil do not move,
so they are drawn once per size and theme into a cached picture. Every blade of grass is one
outline in one path, filled once a layer; particles are batched by the motion library; a glow
is a radial gradient, never a blur. What moves is a few paths a frame.

**Colours are the plan's own**: the stems are finished work's green, the flowers a feature's
teal, an agent's blue, a review's amber, a milestone's violet, the agent's light is its blue
— constants that read on every theme (DESIGN.md's exception #2) — and the soil and the hills
are the palette's own ink at a whisper, so the garden sits on any theme.
"""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import QWidget

from dplanner.framework.motion.clock import FrameClock
from dplanner.framework.motion.curves import (
    breeze,
    cubic,
    in_out_sine,
    out_back,
    out_cubic,
    span,
)
from dplanner.framework.motion.draw import glow, paint_particles, petal, star, tapered
from dplanner.framework.motion.particles import Particle, Particles
from dplanner.modules.home.garden import GROUND_Y, Agent, Garden, Plant
from dplanner.theme.icons import paint_glyph
from dplanner.theme.tones import (
    BADGE_BORDER,
    CHIP_ATTENTION_BORDER,
    CHIP_INFO_BORDER,
    FEATURE_BORDER,
    GOOD_BORDER,
)

GARDEN_H = 196

# Particle tones, beyond the flowers' own (FLOWER_TONE + a flower's colour).
GLITTER, POLLEN, SPROUT, FLOWER_TONE = 0, 1, 2, 3
# A season's flowers, dealt round the seeds; the milestone is always the violet.
FLOWERS = (FEATURE_BORDER, CHIP_INFO_BORDER, CHIP_ATTENTION_BORDER, BADGE_BORDER)
MILESTONE = len(FLOWERS) - 1
AGENT_LIGHT = CHIP_INFO_BORDER

PETAL_R = 14.0  # A flower's radius, and the milestone's.
MILESTONE_R = 19.0
AGENT_GLYPH = 26.0  # The sparkles glyph's box around a flying agent.
SLOW_S = 0.05  # How often the grass and the stars are redrawn: twenty times a second.
# Seasons a garden plays before it rests, still, in full bloom — a page left open is not
# a reason to spend a core — and how long into that rest it waits for the sparkle to settle.
AWAKE_SEASONS = 2
SETTLE_S = 2.5
ROOT_S = 1.6  # How long a bloom's roots take to reach halfway to its neighbours.


def rgba(colour: QColor, alpha: int) -> QColor:
    shade = QColor(colour)
    shade.setAlpha(max(0, min(255, alpha)))
    return shade


def lighter(colour: QColor, amount: float, alpha: int = 255) -> QColor:
    """``colour`` mixed towards white by ``amount`` — a petal's heart, a leaf's light side."""
    return QColor(
        round(colour.red() + (255 - colour.red()) * amount),
        round(colour.green() + (255 - colour.green()) * amount),
        round(colour.blue() + (255 - colour.blue()) * amount),
        alpha,
    )


def darker(colour: QColor, amount: float, alpha: int = 255) -> QColor:
    return QColor(
        round(colour.red() * (1 - amount)),
        round(colour.green() * (1 - amount)),
        round(colour.blue() * (1 - amount)),
        alpha,
    )


@dataclass(frozen=True)
class Ring:
    """One ring of a flower's petals: their directions (from straight up), their length and
    width as fractions of the flower's radius, how their colour runs from heart to edge, and
    when they open — each petal ``stagger`` after the last, the whole ring ``later``."""

    angles: tuple[float, ...]
    length: float = 1.0
    width: float = 0.7
    heart: float = 0.35
    edge: float = 0.05
    stagger: float = 0.035
    later: float = 0.0
    drop: float = 0.0  # How far below the tip the ring hangs, for a cup.


def around(count: int, offset: float = 0.0) -> tuple[float, ...]:
    return tuple(offset + number * 2 * math.pi / count for number in range(count))


RINGS = {
    "round": (Ring(around(6)), Ring(around(6, math.pi / 6), 0.6, 0.72, 0.6, later=0.08)),
    "daisy": (Ring(around(11), 1.08, 0.3, 0.75, 0.0, stagger=0.02),),
    "tulip": (
        Ring((-0.42, 0.42), 1.3, 0.72, 0.3, 0.12, drop=0.25),
        Ring((0.0,), 1.35, 0.8, 0.45, 0.02, later=0.06, drop=0.25),
    ),
    "lotus": (
        Ring(around(8), 1.12, 0.6, 0.3, 0.08),
        Ring(around(8, math.pi / 8), 0.72, 0.62, 0.6, later=0.08),
    ),
}
# How wide a flower's heart is, as a fraction of its radius; a tulip shows none.
STYLE_DISC = {"round": 0.3, "daisy": 0.38, "tulip": 0.0, "lotus": 0.26}


@dataclass(frozen=True)
class Blade:
    x: float
    height: float
    lean: float
    front: bool


class GardenView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Garden")
        self.setFixedHeight(GARDEN_H)
        self.state = Garden()
        # Seeded: the same garden every run, which is what lets a render be compared.
        self._random = random.Random(7)
        self.sparks = Particles(capacity=360)  # Glitter and bursts: they fall to the soil.
        self.motes = Particles(capacity=120)  # Pollen: it rises.
        self.petals = Particles(capacity=120)  # A season's end: they drift away.
        self._owed: dict[str, float] = {}
        self._blades: list[Blade] = []
        self._stars: list[tuple[float, float, float, float]] = []
        self._backdrop: QPixmap | None = None
        self._slow: tuple[QPixmap, QPixmap] | None = None
        self._slow_t = 0.0
        self.clock = FrameClock(self)
        self.clock.ticked.connect(self.advance)
        self.clock.follow(self)
        self.asleep = False
        self._rests_left = AWAKE_SEASONS

    def running(self) -> bool:
        return self.clock.running()

    # -- time --------------------------------------------------------------------------------

    def advance(self, dt: float) -> None:
        """One frame: the garden moves on, what happened bursts, the particles drift."""
        garden = self.state
        for kind, index in garden.advance(dt):
            if kind == "bloom":
                self._burst_bloom(index)
            elif kind == "ready":
                self._burst_sprout(index)
            elif kind == "let go":
                self._let_petals_go()
            elif kind == "rest":
                self._rests_left -= 1
        for agent in garden.agents:
            if agent.state == "working":
                self._emit("glitter", agent, 46.0, dt, self._glitter)
            elif agent.state == "flying":
                self._emit("trail", agent, 30.0, dt, self._trail)
        if garden.season == "resting":
            self._emit("pollen", None, 9.0, dt, lambda _agent: self._pollen())
        ground = GROUND_Y * self.height()
        wind = breeze(garden.t, 0.0)
        self.sparks.step(dt, gravity=70.0, drag=0.9, floor=ground)
        self.motes.step(dt, gravity=-4.0, drag=0.3, wind=6.0 * wind)
        self.petals.step(dt, gravity=26.0, drag=0.9, wind=22.0 + 16.0 * wind)
        self.update()
        settled = garden.season == "resting" and garden.t - garden.since >= SETTLE_S
        if self._rests_left <= 0 and settled and not self.sparks:
            self.sleep()

    def sleep(self) -> None:
        """Stop, in full bloom: a still picture until somebody looks again."""
        self.asleep = True
        self.clock.stop()

    def wake(self) -> None:
        """One more season, from wherever it rests."""
        self.asleep = False
        self._rests_left = max(self._rests_left, 1)
        if self.isVisible():
            self.clock.start()

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 - Qt override
        if self.asleep:
            self.wake()
        super().enterEvent(event)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        # Shown again is looked at again; the clock itself starts on the show.
        self.asleep = False
        self._rests_left = max(self._rests_left, 1)
        super().showEvent(event)

    def _emit(
        self, key: str, agent: Agent | None, rate: float, dt: float, make: Callable[..., None]
    ) -> None:
        name = key if agent is None else f"{key}:{id(agent)}"
        owed = self._owed.get(name, 0.0) + rate * dt
        while owed >= 1.0:
            make(agent)
            owed -= 1.0
        self._owed[name] = owed

    def _at(self, x: float, y: float) -> QPointF:
        return QPointF(x * self.width(), y * self.height())

    # -- what happens ------------------------------------------------------------------------

    def _glitter(self, agent: Agent) -> None:
        rand = self._random
        point = self._at(agent.x, agent.y)
        self.sparks.emit(
            Particle(
                point.x() + rand.uniform(-11, 11),
                point.y() + rand.uniform(4, 12),
                vx=rand.uniform(-14, 14),
                vy=rand.uniform(22, 48),
                life=rand.uniform(0.9, 1.5),
                size=rand.uniform(1.4, 3.0),
                tone=GLITTER,
                shape="spark",
                angle=rand.uniform(0, math.pi),
                spin=rand.uniform(-3, 3),
                twinkle=rand.uniform(0, 6.3),
            )
        )

    def _trail(self, agent: Agent) -> None:
        rand = self._random
        point = self._at(agent.x, agent.y)
        self.sparks.emit(
            Particle(
                point.x() - agent.heading * rand.uniform(4, 10),
                point.y() + rand.uniform(-3, 5),
                vx=-agent.heading * rand.uniform(4, 18),
                vy=rand.uniform(-6, 10),
                life=rand.uniform(0.45, 0.8),
                size=rand.uniform(1.2, 2.4),
                tone=GLITTER,
                shape="spark",
                twinkle=rand.uniform(0, 6.3),
            )
        )

    def _burst_bloom(self, index: int) -> None:
        rand = self._random
        tip = self._tip(index, self.state.plants[index])
        tone = FLOWER_TONE + self._flower(index)
        count = 30 if self.state.plan[index].milestone else 20
        for burst in range(count):
            angle = rand.uniform(0, 2 * math.pi)
            speed = rand.uniform(26, 72)
            self.sparks.emit(
                Particle(
                    tip.x(),
                    tip.y(),
                    vx=math.cos(angle) * speed,
                    vy=math.sin(angle) * speed - 26,
                    life=rand.uniform(0.8, 1.5),
                    size=rand.uniform(1.6, 3.2),
                    tone=tone if burst % 3 else GLITTER,
                    shape="spark",
                    angle=rand.uniform(0, math.pi),
                    spin=rand.uniform(-4, 4),
                    twinkle=rand.uniform(0, 6.3),
                )
            )

    def _burst_sprout(self, index: int) -> None:
        rand = self._random
        base = self._at(self.state.plan[index].x, GROUND_Y)
        for _ in range(9):
            angle = rand.uniform(-math.pi * 0.9, -math.pi * 0.1)
            speed = rand.uniform(18, 40)
            self.sparks.emit(
                Particle(
                    base.x(),
                    base.y() - 4,
                    vx=math.cos(angle) * speed,
                    vy=math.sin(angle) * speed,
                    life=rand.uniform(0.5, 0.9),
                    size=rand.uniform(1.2, 2.2),
                    tone=SPROUT,
                    shape="spark",
                    twinkle=rand.uniform(0, 6.3),
                )
            )

    def _pollen(self) -> None:
        rand = self._random
        bloomed = [i for i, plant in enumerate(self.state.plants) if plant.stage == "bloomed"]
        if not bloomed:
            return
        tip = self._tip(rand.choice(bloomed), self.state.plants[bloomed[0]])
        self.motes.emit(
            Particle(
                tip.x() + rand.uniform(-6, 6),
                tip.y() + rand.uniform(-4, 4),
                vx=rand.uniform(-4, 8),
                vy=rand.uniform(-16, -6),
                life=rand.uniform(3.0, 5.0),
                size=rand.uniform(0.9, 1.7),
                tone=POLLEN,
                twinkle=rand.uniform(0, 6.3),
            )
        )

    def _let_petals_go(self) -> None:
        rand = self._random
        for index, plant in enumerate(self.state.plants):
            tip = self._tip(index, plant)
            seed = self.state.plan[index]
            for number in range(seed.petals):
                angle = -math.pi / 2 + number * 2 * math.pi / seed.petals
                self.petals.emit(
                    Particle(
                        tip.x() + math.cos(angle) * 5,
                        tip.y() + math.sin(angle) * 5,
                        vx=rand.uniform(4, 30),
                        vy=rand.uniform(-26, 2),
                        life=rand.uniform(2.6, 3.8),
                        size=rand.uniform(3.2, 4.4) * (1.3 if seed.milestone else 1.0),
                        tone=FLOWER_TONE + self._flower(index),
                        shape="petal",
                        angle=angle,
                        spin=rand.uniform(-2.2, 2.2),
                    )
                )

    # -- the look ----------------------------------------------------------------------------

    def _dark(self) -> bool:
        return self.palette().color(QPalette.ColorRole.Window).lightness() < 128

    def _ink(self) -> QColor:
        return self.palette().color(QPalette.ColorRole.Text)

    def _flower(self, index: int) -> int:
        """Which of FLOWERS a seed blooms in this season."""
        if self.state.plan[index].milestone:
            return MILESTONE
        return (index + self.state.round) % (len(FLOWERS) - 1)

    def _greens(self) -> tuple[QColor, QColor]:
        """A stem's base and its tip: finished work's green, deeper at the root."""
        if self._dark():
            return darker(GOOD_BORDER, 0.3, 235), lighter(GOOD_BORDER, 0.12, 235)
        return darker(GOOD_BORDER, 0.42, 235), darker(GOOD_BORDER, 0.18, 235)

    def _tones(self) -> dict[int, QColor]:
        dark = self._dark()
        tones = {
            GLITTER: QColor(225, 244, 255, 235) if dark else darker(AGENT_LIGHT, 0.25, 225),
            POLLEN: QColor(255, 236, 190, 200) if dark else darker(CHIP_ATTENTION_BORDER, 0.2, 200),
            SPROUT: lighter(GOOD_BORDER, 0.2, 230) if dark else darker(GOOD_BORDER, 0.25, 230),
        }
        for number, flower in enumerate(FLOWERS):
            tones[FLOWER_TONE + number] = rgba(flower, 235) if dark else darker(flower, 0.08, 235)
        return tones

    # -- painting ----------------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        self._backdrop = self._slow = None
        rand = random.Random(11)
        blades: list[Blade] = []
        for front, (low, high), (near, far) in ((False, (7, 17), (5, 9)), (True, (4, 10), (6, 11))):
            x = -4.0
            while x < self.width() + 4:
                blades.append(Blade(x, rand.uniform(low, high), rand.uniform(-0.3, 0.3), front))
                x += rand.uniform(near, far)
        self._blades = blades
        # A few stars over a night garden, placed once per size.
        self._stars = [
            (
                rand.uniform(0, self.width()),
                rand.uniform(4, GROUND_Y * self.height() * 0.62),
                rand.uniform(0.5, 1.2),
                rand.uniform(0, 6.3),
            )
            for _ in range(max(12, self.width() // 22))
        ]
        super().resizeEvent(event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._backdrop = self._slow = None  # The ink it was drawn in is another theme's.
        super().changeEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self._backdrop_pixmap())
        ground = GROUND_Y * self.height()
        tones = self._tones()
        behind, front = self._slow_layers(ground)
        painter.drawPixmap(0, 0, behind)
        self._pulses(painter, ground)
        for index, plant in enumerate(self.state.plants):
            self._plant(painter, index, plant, ground)
        painter.drawPixmap(0, 0, front)
        paint_particles(painter, self.petals.items, tones)
        paint_particles(painter, self.motes.items, tones)
        paint_particles(painter, self.sparks.items, tones)
        for agent in self.state.agents:
            self._agent(painter, agent)
        painter.end()

    def _slow_layers(self, ground: float) -> tuple[QPixmap, QPixmap]:
        """The grass, the stars and the roots, redrawn a few times a second rather than every
        frame: they move with a breeze that turns over in seconds or change only when a
        flower blooms, and at sixty frames a second they were over half of what one cost."""
        t = self.state.t
        if self._slow is None or abs(t - self._slow_t) >= SLOW_S:
            behind, front = self._layer(), self._layer()
            painter = QPainter(behind)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self._dark():
                self._sky(painter)
            self._roots(painter, ground)
            self._grass(painter, ground, front=False)
            painter.end()
            painter = QPainter(front)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._grass(painter, ground, front=True)
            painter.end()
            self._slow, self._slow_t = (behind, front), t
        return self._slow

    def _layer(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        return pixmap

    def _sky(self, painter: QPainter) -> None:
        """A night garden's stars, twinkling out of step, four strengths to one fill each."""
        t = self.state.t
        paths = [QPainterPath() for _ in range(4)]
        for x, y, size, phase in self._stars:
            level = min(3, int((0.5 + 0.5 * math.sin(t * 0.9 + phase)) * 4))
            paths[level].addEllipse(QPointF(x, y), size, size)
        ink = self._ink()
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for level, path in enumerate(paths):
            painter.setBrush(rgba(ink, 22 + 30 * level))
            painter.drawPath(path)
        painter.restore()

    def _backdrop_pixmap(self) -> QPixmap:
        """The sky, the hills and the soil: still, so drawn once per size and theme."""
        if self._backdrop is not None:
            return self._backdrop
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        ground = GROUND_Y * height
        ink, dark = self._ink(), self._dark()
        # A haze of the agent's light low over the land, fading to nothing above.
        haze = QLinearGradient(0, 0, 0, ground)
        haze.setColorAt(0.0, rgba(AGENT_LIGHT, 0))
        haze.setColorAt(1.0, rgba(AGENT_LIGHT, 20 if dark else 14))
        painter.fillRect(QRectF(0, 0, width, ground), haze)
        if not dark:
            # A daytime garden has a sun: warm, soft, well up to the left.
            glow(
                painter, QPointF(width * 0.1, -height * 0.25), 230, rgba(CHIP_ATTENTION_BORDER, 30)
            )
        # The sky melts into the page above it: no edge where the garden begins.
        melt = QLinearGradient(0, 0, 0, height * 0.4)
        melt.setColorAt(0.0, QColor(0, 0, 0, 0))
        melt.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.fillRect(QRectF(0, 0, width, height * 0.4), melt)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # Two ranges of hills, the far one fainter.
        for far, (rise, alpha) in enumerate(((0.3, 9), (0.18, 13))):
            hills = QPainterPath(QPointF(0, ground))
            steps = 48
            for step in range(steps + 1):
                x = width * step / steps
                y = ground - height * rise * (
                    0.55
                    + 0.25 * math.sin(x * 0.006 + far * 2.1)
                    + 0.2 * math.sin(x * 0.017 + far * 4.7)
                )
                hills.lineTo(x, y)
            hills.lineTo(width, ground)
            hills.closeSubpath()
            painter.fillPath(hills, rgba(ink, alpha if dark else alpha - 3))
        # The soil: a band that darkens away from the surface, and a lit edge.
        soil = QLinearGradient(0, ground, 0, height)
        soil.setColorAt(0.0, rgba(ink, 26 if dark else 18))
        soil.setColorAt(1.0, rgba(ink, 6 if dark else 4))
        painter.fillRect(QRectF(0, ground, width, height - ground), soil)
        painter.setPen(QPen(rgba(ink, 46 if dark else 38), 1.0))
        painter.drawLine(QPointF(0, ground + 0.5), QPointF(width, ground + 0.5))
        painter.end()
        self._backdrop = pixmap
        return pixmap

    def _root_curve(self, source: int, waiter: int, ground: float) -> tuple[QPointF, ...]:
        plan = self.state.plan
        a = self._at(plan[source].x, GROUND_Y)
        b = self._at(plan[waiter].x, GROUND_Y)
        depth = min(self.height() - ground - 6, 8 + 0.05 * abs(b.x() - a.x()))
        return (
            QPointF(a.x(), ground + 3),
            QPointF(a.x() + (b.x() - a.x()) * 0.2, ground + 3 + depth),
            QPointF(a.x() + (b.x() - a.x()) * 0.8, ground + 3 + depth),
            QPointF(b.x(), ground + 3),
        )

    def _roots(self, painter: QPainter, ground: float) -> None:
        """The plan's links, underground: a flower that has bloomed sends a root out along
        each of its links, reaching halfway and fading as it goes, so two bloomed neighbours
        meet in the soil between them and an unbloomed one is reached towards, not touched.
        They grow at the slow layers' pace, which a root's reach is slow enough for."""
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for source, waiter in self.state.edges():
            curve = self._root_curve(source, waiter, ground)
            for index, outward in ((source, True), (waiter, False)):
                plant = self.state.plants[index]
                if plant.stage != "bloomed" or plant.wilt >= 1.0:
                    continue
                reach = out_cubic(span(self.state.t, plant.since, ROOT_S)) * 0.5
                self._root(painter, curve, reach, outward, index, 1.0 - plant.wilt)
        painter.restore()

    def _root(
        self,
        painter: QPainter,
        curve: tuple[QPointF, ...],
        reach: float,
        outward: bool,
        seed: int,
        strength: float,
    ) -> None:
        """One root along ``curve`` from the end it grows from, ``reach`` of the way across:
        tapering, wandering a little, and fading to nothing where it stops."""
        if reach <= 0.01:
            return
        a, b, c, d = ((point.x(), point.y()) for point in curve)
        steps = 14
        points: list[tuple[float, float]] = []
        for step in range(steps + 1):
            along = reach * step / steps
            x, y = cubic(a, b, c, d, along if outward else 1.0 - along)
            wander = math.sin(along * 19.0 + seed * 1.7) * 2.2 * math.sin(math.pi * along * 2)
            points.append((x, y + wander))
        start, stop = QPointF(*points[0]), QPointF(*points[-1])
        fade = QLinearGradient(start, stop)
        fade.setColorAt(0.0, rgba(GOOD_BORDER, round(150 * strength)))
        fade.setColorAt(1.0, rgba(GOOD_BORDER, 0))
        painter.setBrush(fade)
        outline = tapered(points, 2.4, 0.3)
        # Two rootlets off the main root, forking down and on, once it has reached past them.
        for fork, length in ((0.3, 7.0), (0.6, 5.0)):
            if fork * 0.5 > reach:
                continue
            x, y = points[round(fork * 0.5 / reach * steps)]
            ahead = 1.0 if (curve[-1].x() > curve[0].x()) == outward else -1.0
            outline.addPath(
                tapered(
                    [
                        (x, y),
                        (x + ahead * length * 0.5, y + length * 0.6),
                        (x + ahead * length, y + length),
                    ],
                    1.2,
                    0.2,
                )
            )
        painter.drawPath(outline)

    def _pulses(self, painter: QPainter, ground: float) -> None:
        """A bloom's pulse, travelling down a root to what it unblocks."""
        dark = self._dark()
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for pulse in self.state.pulses:
            curve = self._root_curve(pulse.source, pulse.waiter, ground)
            p = in_out_sine(pulse.at(self.state.t))
            a, b, c, d = ((point.x(), point.y()) for point in curve)
            centre = QPointF(*cubic(a, b, c, d, p))
            glow(painter, centre, 12, rgba(GOOD_BORDER, 170 if dark else 120))
            painter.setBrush(lighter(GOOD_BORDER, 0.7, 240))
            painter.drawEllipse(centre, 2.2, 2.2)
        painter.restore()

    def _grass(self, painter: QPainter, ground: float, *, front: bool) -> None:
        """Every blade of a layer is two short lines, drawn in one call — the cheapest thing
        that still bends in the breeze."""
        t = self.state.t
        lines: list[QLineF] = []
        for blade in self._blades:
            if blade.front != front:
                continue
            bend = (breeze(t, blade.x) * 0.3 + blade.lean) * blade.height
            base = QPointF(blade.x, ground + (3 if front else 1))
            middle = QPointF(blade.x + bend * 0.3, base.y() - blade.height * 0.55)
            tip = QPointF(blade.x + bend, base.y() - blade.height)
            lines.append(QLineF(base, middle))
            lines.append(QLineF(middle, tip))
        base_green, tip_green = self._greens()
        pen = QPen(rgba(base_green, 150) if front else rgba(tip_green, 62), 1.6 if front else 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLines(lines)

    def _tip(self, index: int, plant: Plant) -> QPointF:
        """Where a plant's flower is, sway and all."""
        return self._stem(index, plant)[-1]

    def _stem(self, index: int, plant: Plant) -> list[QPointF]:
        seed = self.state.plan[index]
        t = self.state.t
        growth = 1.0 if plant.stage == "bloomed" else plant.growth
        shrink = 1.0 - out_cubic(plant.wilt)
        length = seed.height * self.height() * out_cubic(span(growth, 0.0, 0.6)) * shrink
        base = self._at(seed.x, GROUND_Y)
        lean = breeze(t, base.x()) * length * (0.1 if plant.stage == "bloomed" else 0.05)
        start = (base.x(), base.y())
        control_1 = (base.x(), base.y() - length * 0.4)
        control_2 = (base.x() + lean * 0.35, base.y() - length * 0.78)
        end = (base.x() + lean, base.y() - length)
        return [QPointF(*cubic(start, control_1, control_2, end, i / 11)) for i in range(12)]

    def _plant(self, painter: QPainter, index: int, plant: Plant, ground: float) -> None:
        seed = self.state.plan[index]
        t = self.state.t
        base = self._at(seed.x, GROUND_Y)
        ink, dark = self._ink(), self._dark()
        green_base, green_tip = self._greens()
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        if plant.stage == "seed":
            painter.setBrush(rgba(ink, 70 if dark else 60))
            painter.drawEllipse(QPointF(base.x(), ground + 1.5), 3.6, 2.4)
            painter.restore()
            return
        if plant.stage == "ready":
            # A sprout pops up and glints: this one is ready for an agent.
            pop = out_back(span(t, plant.since, 0.55), 2.2)
            breath = 0.5 + 0.5 * math.sin(t * 3.2 + index)
            strength = (40 + 40 * breath) * (1.0 if dark else 0.7)
            glow(
                painter, QPointF(base.x(), ground - 6), 16 * pop, rgba(GOOD_BORDER, round(strength))
            )
            sprout = [
                (base.x(), ground),
                (base.x() + 1.5 * pop, ground - 7 * pop),
                (base.x() + 0.5 * pop, ground - 11 * pop),
            ]
            shoot = tapered(sprout, 2.4, 1.2)
            top = QPointF(*sprout[-1])
            for side in (-1, 1):
                shoot.addPath(petal(top, 6 * pop, 3.4 * pop, -math.pi / 2 + side * 0.95))
            painter.setBrush(green_tip)
            painter.drawPath(shoot)
            painter.restore()
            return

        growth = 1.0 if plant.stage == "bloomed" else plant.growth
        shrink = 1.0 - out_cubic(plant.wilt)
        stem = self._stem(index, plant)
        tip = stem[-1]
        # The stem and its leaves are one green: one outline, one gradient, one fill.
        greenery = tapered([(p.x(), p.y()) for p in stem], 3.8, 1.5)
        greenery.setFillRule(Qt.FillRule.WindingFill)
        # Leaves unfurl one after the other as the stem rises past them.
        for at, side, delay in ((3, -1, 0.18), (5, 1, 0.3), (7, -1, 0.42)):
            if at == 7 and seed.height < 0.42:
                continue
            open_ = out_back(span(growth, delay, 0.34), 2.0) * shrink
            if open_ <= 0.02:
                continue
            sway = breeze(t, base.x() + at * 13) * 0.12
            angle = -math.pi / 2 + side * (1.02 + sway)
            greenery.addPath(petal(stem[at], 21 * open_, 9 * open_, angle))
        shade = QLinearGradient(base, tip)
        shade.setColorAt(0.0, green_base)
        shade.setColorAt(1.0, green_tip)
        painter.setBrush(shade)
        painter.drawPath(greenery)
        self._flower_head(painter, index, plant, tip, growth)
        painter.restore()

    def _flower_head(
        self, painter: QPainter, index: int, plant: Plant, tip: QPointF, growth: float
    ) -> None:
        """A flower opening at the stem's tip, petal after petal, in its style: a ring of
        round petals, a daisy's many narrow ones, a tulip's cup, the milestone's lotus."""
        seed = self.state.plan[index]
        t, dark = self.state.t, self._dark()
        colour = FLOWERS[self._flower(index)]
        radius = MILESTONE_R if seed.milestone else PETAL_R
        gone = min(1.0, plant.wilt * 5.0)  # The petals left as the season turned.
        if plant.stage == "bloomed" and gone < 1.0:
            burst = math.exp(-(t - plant.since) * 1.5)
            halo = (0.4 + 0.15 * math.sin(t * 1.6)) if seed.milestone else 0.14
            strength = (halo + 0.9 * burst) * (1.0 - gone)
            glow(
                painter,
                tip,
                radius * (2.3 + 1.2 * burst),
                rgba(colour, round((150 if dark else 90) * strength)),
            )
        bud = out_cubic(span(growth, 0.5, 0.18)) * (1.0 - gone)
        if bud > 0.01:
            painter.setBrush(darker(colour, 0.25, round(220 * bud)))
            painter.drawEllipse(tip, 3.8 * bud, 3.8 * bud)
        if gone >= 1.0:
            return
        tilt = breeze(t, tip.x()) * 0.15
        for ring in RINGS[seed.style]:
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for number, angle in enumerate(ring.angles):
                start = 0.6 + number * ring.stagger + ring.later
                open_ = out_back(span(growth, start, 0.3), 1.9) * (1.0 - gone)
                if open_ <= 0.02:
                    continue
                length = radius * ring.length * open_
                path.addPath(
                    petal(
                        QPointF(tip.x(), tip.y() + ring.drop * radius),
                        length,
                        length * ring.width,
                        -math.pi / 2 + tilt + angle,
                    )
                )
            if path.isEmpty():
                continue
            fill = QRadialGradient(tip, radius * ring.length)
            fill.setColorAt(0.0, lighter(colour, ring.heart, 245))
            fill.setColorAt(1.0, darker(colour, ring.edge, 240) if not dark else rgba(colour, 238))
            painter.setBrush(fill)
            painter.drawPath(path)
        disc = STYLE_DISC[seed.style]
        centre = out_back(span(growth, 0.72, 0.28), 2.4) * (1.0 - gone)
        if disc > 0 and centre > 0.02:
            heart = QRadialGradient(tip, radius * disc * centre)
            heart.setColorAt(0.0, lighter(CHIP_ATTENTION_BORDER, 0.55, 250))
            heart.setColorAt(1.0, darker(CHIP_ATTENTION_BORDER, 0.15, 250))
            painter.setBrush(heart)
            painter.drawEllipse(tip, radius * disc * centre, radius * disc * centre)

    def _agent(self, painter: QPainter, agent: Agent) -> None:
        """An agent: its sparkles glyph, lit from within, leaning into its flight."""
        t, dark = self.state.t, self._dark()
        centre = self._at(agent.x, agent.y)
        working = agent.state == "working"
        breath = 1.0 + (
            0.08 * math.sin(t * 6.0 + agent.phase)
            if working
            else 0.03 * math.sin(t * 2.0 + agent.phase)
        )
        painter.save()
        glow(painter, centre, 34 * breath, rgba(AGENT_LIGHT, 125 if dark else 80))
        glow(
            painter,
            centre,
            13 * breath,
            QColor(235, 248, 255, 170) if dark else rgba(AGENT_LIGHT, 90),
        )
        painter.translate(centre)
        if agent.state == "flying":
            painter.rotate(
                agent.heading * 12.0 * math.sin(math.pi * span(t, agent.since, agent.flight_s))
            )
        painter.scale(breath, breath)
        # The glyph's large star sits at (9, 12) of its 24-unit box, six units across: the
        # box is placed so that star is the agent's heart, and a filled star lights it.
        size = AGENT_GLYPH
        unit = size / 24.0
        core = QColor(240, 250, 255, 235) if dark else lighter(AGENT_LIGHT, 0.55, 240)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(core)
        painter.drawPath(star(QPointF(0, 0), 6.4 * unit, 0.0, 0.26))
        ink = QColor(250, 253, 255, 250) if dark else darker(AGENT_LIGHT, 0.45, 245)
        paint_glyph(painter, QRectF(-9 * unit, -12 * unit, size, size), "spark", ink)
        painter.restore()
