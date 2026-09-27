"""The shapes and light that moving things are drawn with — soft, and cheap to redraw.

Everything here is drawn fresh each frame, so it is built to cost little: a glow is one
radial gradient, never a blur; a stroke that tapers is one filled polygon; a whole particle
system is one path per tone, filled once. Colours come in from the caller — a tone constant
or a palette ink — so nothing here knows a theme.
"""

import math
from collections.abc import Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QRadialGradient

from dplanner.framework.motion.curves import Point
from dplanner.framework.motion.particles import Particle

FADE_STEPS = 5  # The alphas a fading particle passes through.


def glow(painter: QPainter, centre: QPointF, radius: float, colour: QColor) -> None:
    """A soft light: ``colour`` at the centre fading to nothing at ``radius``."""
    if radius <= 0 or colour.alpha() == 0:
        return
    gradient = QRadialGradient(centre, radius)
    gradient.setColorAt(0.0, colour)
    middle = QColor(colour)
    middle.setAlphaF(colour.alphaF() * 0.35)
    gradient.setColorAt(0.45, middle)
    gradient.setColorAt(1.0, QColor(colour.red(), colour.green(), colour.blue(), 0))
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawEllipse(centre, radius, radius)
    painter.restore()


def star(centre: QPointF, radius: float, angle: float = 0.0, pinch: float = 0.18) -> QPainterPath:
    """A four-pointed sparkle, its sides curved in — the agent glyph's own star, filled.

    ``pinch`` is how far the waist comes in, as a fraction of the radius.
    """
    path = QPainterPath()
    points = []
    for index in range(4):
        theta = angle + index * math.pi / 2
        points.append(
            QPointF(centre.x() + math.cos(theta) * radius, centre.y() + math.sin(theta) * radius)
        )
    path.moveTo(points[0])
    for index in range(4):
        tip = points[(index + 1) % 4]
        waist = angle + (index + 0.5) * math.pi / 2
        control = QPointF(
            centre.x() + math.cos(waist) * radius * pinch,
            centre.y() + math.sin(waist) * radius * pinch,
        )
        path.quadTo(control, tip)
    path.closeSubpath()
    return path


def petal(base: QPointF, length: float, width: float, angle: float) -> QPainterPath:
    """A teardrop from ``base`` outwards along ``angle``: rounded at the tip, narrow at the
    root, so five of them round a centre read as a flower and one falling reads as a petal."""
    ux, uy = math.cos(angle), math.sin(angle)
    nx, ny = -uy, ux
    tip = QPointF(base.x() + ux * length, base.y() + uy * length)
    shoulder = 0.62 * length

    def at(along: float, across: float) -> QPointF:
        return QPointF(base.x() + ux * along + nx * across, base.y() + uy * along + ny * across)

    path = QPainterPath(base)
    path.cubicTo(at(shoulder * 0.35, width * 0.55), at(shoulder, width * 0.62), tip)
    path.cubicTo(at(shoulder, -width * 0.62), at(shoulder * 0.35, -width * 0.55), base)
    path.closeSubpath()
    return path


def tapered(points: Sequence[Point], base_width: float, tip_width: float) -> QPainterPath:
    """A stroke along ``points`` that narrows from ``base_width`` to ``tip_width`` — a stem,
    a blade of grass — as one filled outline rather than many pen widths."""
    if len(points) < 2:
        return QPainterPath()
    left: list[QPointF] = []
    right: list[QPointF] = []
    last = len(points) - 1
    for index, (x, y) in enumerate(points):
        ahead = points[min(index + 1, last)]
        behind = points[max(index - 1, 0)]
        dx, dy = ahead[0] - behind[0], ahead[1] - behind[1]
        norm = math.hypot(dx, dy) or 1.0
        half = (base_width + (tip_width - base_width) * index / last) / 2
        nx, ny = -dy / norm * half, dx / norm * half
        left.append(QPointF(x + nx, y + ny))
        right.append(QPointF(x - nx, y - ny))
    path = QPainterPath(left[0])
    for point in left[1:]:
        path.lineTo(point)
    for point in reversed(right):
        path.lineTo(point)
    path.closeSubpath()
    return path


def paint_particles(
    painter: QPainter,
    particles: Sequence[Particle],
    tones: Mapping[int, QColor],
) -> None:
    """Draw a particle system: one path per tone, shape and step of fade, each filled once
    — five steps of alpha are smooth to the eye and keep the fills few. A twinkling
    particle's size breathes with its phase. No glow behind each one: a gradient per
    particle is what a frame cannot afford, and a bright core over a dark ground glows
    enough."""
    groups: dict[tuple[int, str, int], QPainterPath] = {}
    for item in particles:
        fade = item.fade
        if fade <= 0.01:
            continue
        size = item.size * (0.75 + 0.25 * math.sin(item.twinkle + item.age * 9.0))
        centre = QPointF(item.x, item.y)
        level = min(FADE_STEPS - 1, int(fade * FADE_STEPS))
        path = groups.get((item.tone, item.shape, level))
        if path is None:
            # Winding, so two sparks that overlap add up rather than cut a hole in each other.
            path = groups[(item.tone, item.shape, level)] = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
        if item.shape == "spark":
            path.addPath(star(centre, size * (0.6 + 0.4 * fade), item.angle))
        elif item.shape == "petal":
            path.addPath(petal(centre, size * 2.2, size * 1.3, item.angle))
        else:
            path.addEllipse(centre, size * fade, size * fade)
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for (tone, _shape, level), path in groups.items():
        colour = QColor(tones[tone])
        colour.setAlphaF(colour.alphaF() * (level + 1) / FADE_STEPS)
        painter.setBrush(colour)
        painter.drawPath(path)
    painter.restore()


def rect_around(centre: QPointF, size: float) -> QRectF:
    return QRectF(centre.x() - size / 2, centre.y() - size / 2, size, size)
