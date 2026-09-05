"""Render the application icon at every size the desktop asks for.

    QT_QPA_PLATFORM=offscreen uv run python scripts/render_icon.py

The mark is what DPlanner is: a graph of steps. Two plain steps on the left feed a
milestone on the right, on a dark rounded tile that reads on a light or a dark desktop.
The colours are the theme's — the milestone's violet is ``BADGE_TINT``'s hue at full ink —
and the geometry is in units of the size, so every rendering is the same picture.

The output goes to ``src/dplanner/assets/icons/`` and is committed: the CLI writes a
launcher's icon from a process that never loads Qt, so it reads the files this script
made rather than drawing. Re-run it after changing the mark, and commit the result.
"""

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

from dplanner.assets import ICON_SIZES, icon_path

TILE_TOP = QColor("#2F3F68")
TILE_BOTTOM = QColor("#1A2440")
EDGE = QColor(196, 206, 232, 220)
STEP = QColor("#ECEFF8")
MILESTONE = QColor(150, 130, 220)  # theme/tones.py's badge hue, at full ink.


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    tile = QPainterPath()
    radius = s * 0.22
    tile.addRoundedRect(QRectF(0, 0, s, s), radius, radius)
    gradient = QLinearGradient(0, 0, 0, s)
    gradient.setColorAt(0.0, TILE_TOP)
    gradient.setColorAt(1.0, TILE_BOTTOM)
    painter.fillPath(tile, gradient)

    upper, lower, milestone = (
        QPointF(0.31 * s, 0.32 * s),
        QPointF(0.31 * s, 0.68 * s),
        QPointF(0.71 * s, 0.50 * s),
    )
    pen = QPen(EDGE)
    pen.setWidthF(max(1.0, s * 0.062))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(upper, milestone)
    painter.drawLine(lower, milestone)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(STEP)
    step_radius = s * 0.115
    painter.drawEllipse(upper, step_radius, step_radius)
    painter.drawEllipse(lower, step_radius, step_radius)
    painter.setBrush(MILESTONE)
    milestone_radius = s * 0.145
    painter.drawEllipse(milestone, milestone_radius, milestone_radius)
    painter.end()
    return image


def main() -> int:
    QApplication.instance() or QApplication(sys.argv)
    target_dir = Path(icon_path(ICON_SIZES[0])).parent
    target_dir.mkdir(parents=True, exist_ok=True)
    for size in ICON_SIZES:
        path = icon_path(size)
        if not render(size).save(str(path), "PNG"):
            print(f"could not write {path}", file=sys.stderr)
            return 1
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
