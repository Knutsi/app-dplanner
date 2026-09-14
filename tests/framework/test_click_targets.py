"""Ringing the part of a picture a test points at.

The painter is asserted on *pixels* rather than on calls: what it exists for is that a
reader can see where to act, and a mock painter would pass while drawing nothing. A ring
is inside the rectangle's edge, so the corner pixel changes and the middle of a large
target does not.
"""

from PySide6.QtGui import QColor, QImage

from dplanner.domain.assets import ClickTarget
from dplanner.framework.click_targets import TARGET_INK, marked, marked_bytes


def plain(width=200, height=200, colour="white"):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    return image


def png(image):
    from PySide6.QtCore import QBuffer

    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, format="PNG")
    return bytes(buffer.data().data())


def test_no_targets_hands_the_image_straight_back(app):
    image = plain()
    assert marked(image, []) is image


def test_a_target_is_rung_on_its_own_edge_and_leaves_the_rest_alone(app):
    rung = marked(plain(), [ClickTarget(50, 50, 60, 40)])
    assert QColor(rung.pixel(50, 50)) != QColor("white")  # The corner wears the ring.
    assert QColor(rung.pixel(5, 5)) == QColor("white")  # Well outside it, nothing moved.


def test_the_ring_is_the_constant_ink_whatever_the_theme(app):
    # DESIGN.md's deliberate exception: a screenshot carries its own colours and knows
    # nothing of the palette it is shown in, so this may not come from one.
    rung = marked(plain(), [ClickTarget(50, 50, 60, 40)])
    edge = [QColor(rung.pixel(x, 50)) for x in range(50, 110)]
    assert any(abs(one.red() - TARGET_INK.red()) < 40 for one in edge)


def test_the_original_image_is_never_painted_over(app):
    image = plain()
    marked(image, [ClickTarget(10, 10, 20, 20)])
    # The blob on disk is content-addressed and the same bytes for everybody; a marked
    # copy that overwrote it would make one attachment two files.
    assert QColor(image.pixel(10, 10)) == QColor("white")


def test_two_targets_are_numbered_and_one_is_not(app):
    first = ClickTarget(60, 60, 40, 40)
    one = marked(plain(), [first])
    two = marked(plain(), [first, ClickTarget(140, 140, 30, 30)])
    # The badge disc hangs off the rectangle's top-left corner, so (53, 53) is inside it
    # and clear of the ring itself. One target needs no number — nothing to tell it from.
    assert QColor(one.pixel(53, 53)) == QColor("white")
    assert QColor(two.pixel(53, 53)) != QColor("white")


def test_marked_bytes_re_encodes_as_png_and_says_so(app):
    data = png(plain(60, 60))
    carried, suffix = marked_bytes(data, [ClickTarget(10, 10, 20, 20)])
    assert suffix == ".png" and carried != data
    assert QColor(QImage.fromData(carried).pixel(10, 10)) != QColor("white")


def test_marked_bytes_leaves_untouched_what_it_cannot_ring(app):
    data = png(plain(60, 60))
    assert marked_bytes(data, []) == (data, "")
    # Not an image at all — a pack must carry it verbatim rather than drop it.
    assert marked_bytes(b"not a picture", [ClickTarget(1, 1, 2, 2)]) == (b"not a picture", "")
