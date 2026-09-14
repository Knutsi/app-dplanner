"""Drawing a picture's click targets onto it: one painter, every reader.

A test's screenshot may say *where* on itself the reader is meant to act — the fragment
on the link, parsed by ``domain/assets.py``. This is the one place that turns those
rectangles into ink, so the thumbnail in a gallery, the lightbox over it and the picture
in an exported pack cannot disagree about what a marked area looks like.

**The ring is drawn, never the picture changed.** :func:`marked` returns a copy: the blob
on disk is content-addressed and the same bytes for everybody, and a marked copy that
overwrote it would make the same attachment two files.

The colour is a **constant**, like a test result's (``DESIGN.md``'s deliberate exceptions):
a screenshot carries its own colours and knows nothing of the theme it is shown in, so a
ring in the palette's accent would vanish against the wrong screenshot on the wrong theme.
Amber on a dark hairline reads on both a light and a dark application, which is the whole
requirement.
"""

from collections.abc import Sequence

from PySide6.QtCore import QBuffer, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from dplanner.domain.assets import ClickTarget

# Constant across themes, and chosen against screenshots rather than against a palette.
TARGET_INK = QColor(255, 176, 0)
TARGET_SHADOW = QColor(0, 0, 0, 140)
TARGET_WASH = QColor(255, 176, 0, 38)

RING_W = 3  # At a thumbnail's scale a 1 px ring disappears; at full size 3 px is a ring.
SHADOW_W = RING_W + 2  # Drawn under the ring, so it reads on a pale screenshot too.
BADGE_D = 20  # The numeral's disc, when there is more than one target to tell apart.
BADGE_FONT = 11


def marked(image: QImage, targets: Sequence[ClickTarget]) -> QImage:
    """``image`` with a ring round each target — the image itself when there are none.

    The rectangles are in the picture's own pixels, so nothing here scales: a caller that
    wants a thumbnail marks first and scales after, which is also the only order that keeps
    a ring the same weight relative to what it rings.
    """
    if not targets or image.isNull():
        return image
    canvas = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rects = [QRect(t.x, t.y, t.width, t.height) for t in targets]
        for rect in rects:
            _ring(painter, rect)
        # Every ring first, then every badge: a ring drawn afterwards would cross the badge
        # of the target beside it, which is exactly where two adjacent targets need telling
        # apart. One target needs no number — there is nothing to tell it from.
        if len(rects) > 1:
            for number, rect in enumerate(rects, start=1):
                _badge(painter, rect, number)
    finally:
        # Explicitly, and before the QImage is handed back: a painter still active on an
        # image Python is about to drop is a crash waiting for the next collection.
        painter.end()
    return canvas


def marked_bytes(data: bytes, targets: Sequence[ClickTarget]) -> tuple[bytes, str]:
    """``data`` with its rings painted in, and the suffix the result now wears.

    For a copy that leaves the application — an exported pack — where the reader has no
    renderer that would draw the ring from the link. Untouched bytes and ``""`` when there
    is nothing to draw or the bytes are not an image, so a caller can always use the pair.

    **PNG whatever came in.** A ring drawn over a JPEG and saved as one loses a little of
    the screenshot each time, and a pack is somebody's evidence; that is also why the
    suffix comes back rather than being assumed by the caller.
    """
    if not targets:
        return data, ""
    image = QImage.fromData(data)
    if image.isNull():
        return data, ""
    # A bare QBuffer owns its bytes. ``QBuffer(QByteArray())`` hands it a Python temporary
    # that is freed on the next line, and the writes then land in freed memory — which is
    # a malloc abort rather than an exception, found by the test below.
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    # PySide's stub types ``format`` as bytes; the binding only accepts a str, and passing
    # what the stub asks for raises at runtime. The ignore is the stub's bug, not ours.
    if not marked(image, targets).save(buffer, format="PNG"):  # type: ignore[call-overload]
        return data, ""
    return bytes(buffer.data().data()), ".png"


def _ring(painter: QPainter, rect: QRect) -> None:
    painter.setBrush(TARGET_WASH)
    painter.setPen(QPen(TARGET_SHADOW, SHADOW_W))
    painter.drawRect(rect)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(TARGET_INK, RING_W))
    painter.drawRect(rect)


def _badge(painter: QPainter, rect: QRect, number: int) -> None:
    """The target's number on its top-left corner, so prose can say "click ②"."""
    disc = QRect(rect.left() - BADGE_D // 2, rect.top() - BADGE_D // 2, BADGE_D, BADGE_D)
    painter.setPen(QPen(TARGET_SHADOW, 1))
    painter.setBrush(TARGET_INK)
    painter.drawEllipse(disc)
    font = QFont(painter.font())
    font.setPixelSize(BADGE_FONT)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QPen(QColor(0, 0, 0)))
    painter.drawText(disc, Qt.AlignmentFlag.AlignCenter, str(number))
