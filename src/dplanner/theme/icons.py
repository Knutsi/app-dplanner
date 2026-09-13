"""The application's glyphs: Tabler's SVGs, inked and painted at the screen's resolution.

The set is **Tabler Icons** (MIT), vendored under ``glyphs/`` — only the fifty-odd this
application uses, by ``scripts/vendor_tabler_icons.py``, which also names what each one
*means* here. A glyph key is ours and outlives any icon set: swapping sets is changing that
script's right-hand column and running it again.

Qt's SVG renderer knows no ``currentColor``, so the ink is substituted into the source
before rendering — the same trick ``theme/__init__.py`` plays for the combo arrow — and the
colour's alpha becomes the painter's opacity, which is how a strip's glyphs come out in the
secondary tone.

Four glyphs are still painted by hand, because each is a picture of *state* rather than a
picture of a thing: the key badge (it draws text), the colour strip (a gradient), the
spinner (a frame per angle) and the filter funnel (two states in one width).
"""

from collections.abc import Callable
from functools import lru_cache
from importlib.resources import files

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer

from dplanner.theme.palettes import Palette

ICON_SIZE = 16
# A glyph nobody is pointing at is present without asking to be read.
IDLE_GLYPH_ALPHA = 110

GLYPH_DIR = files("dplanner.theme").joinpath("glyphs")
# Which Tabler release the vendored SVGs beside this file came from. Stated here rather
# than in the script that fetched them, because it is the *application* that has to say it:
# Help ▸ About names the set and the version it is used at, which is what an MIT notice and
# a bug report both want. `scripts/vendor_tabler_icons.py` reads it back.
TABLER_TAG = "v3.46.0"


def _ratio() -> float:
    """How many device pixels this screen gives a logical one.

    A glyph painted into a 16-pixel pixmap and shown at 16 logical points on a 2x display
    is upscaled by the compositor, and every stroke in it goes soft — which is most of what
    "the icons look a bit blurry" turns out to mean. Painting at the screen's ratio and
    stamping that ratio on the pixmap is all Qt needs to draw it crisply.
    """
    app = QGuiApplication.instance()
    return app.devicePixelRatio() if isinstance(app, QGuiApplication) else 1.0


def _canvas(width: int = ICON_SIZE, height: int = ICON_SIZE) -> tuple[QPixmap, QPainter]:
    """A transparent pixmap and a painter over it, in glyph units whatever the screen is.

    The pixmap is the screen's own resolution and carries the ratio; **the painter is not
    scaled**, because a paint device that declares a device pixel ratio already maps
    logical coordinates for you. Scaling it as well applies the ratio twice, and a 16-unit
    glyph lands in the top-left quarter of its own icon — which the offscreen platform,
    where the ratio is always 1, cannot show you.
    """
    ratio = _ratio()
    pixmap = QPixmap(QSize(round(width * ratio), round(height * ratio)))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def _pen(color: str | QColor, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


@lru_cache(maxsize=512)
def _inked(name: str, ink: str) -> bytes:
    """One vendored glyph with its ``currentColor`` replaced by ``ink``.

    Cached because the canvas asks for the same few glyphs in the same few colours on every
    repaint, and re-reading a file to do a string substitution is the sort of work a paint
    path should never repeat. The cache is keyed by colour, so a theme change simply asks
    for entries it has not got.
    """
    raw = GLYPH_DIR.joinpath(f"{name}.svg").read_text(encoding="utf-8")
    return raw.replace("currentColor", ink).encode("utf-8")


def paint_glyph(painter: QPainter, rect: QRectF, name: str, color: str | QColor) -> None:
    """One glyph into ``rect``, at whatever opacity ``color`` carries.

    The alpha is the painter's opacity rather than the ink's, because an SVG stroke colour
    has none — and a strip's glyphs are the text colour at ``SECONDARY_ALPHA``, so getting
    this wrong makes every toolbar read a shade too loud.
    """
    ink = QColor(color)
    painter.save()
    painter.setOpacity(painter.opacity() * ink.alphaF())
    QSvgRenderer(_inked(name, ink.name())).render(painter, rect)
    painter.restore()


def glyph_icon(name: str, color: str | QColor, *, size: int = ICON_SIZE) -> QIcon:
    """One glyph as an icon, at the screen's resolution."""
    pixmap, painter = _canvas(size, size)
    paint_glyph(painter, QRectF(0.0, 0.0, float(size), float(size)), name, color)
    painter.end()
    return QIcon(pixmap)


def blank_icon(_color: str | QColor) -> QIcon:
    """No glyph, but the slot: a verb whose spec carries no painter must not jump the row."""
    return QIcon()


def container_icon(color: str | QColor) -> QIcon:
    """A stack of folders: the index's Projects segment."""
    return glyph_icon("container", color)


def edit_icon(color: str | QColor) -> QIcon:
    """A pencil: rename, or edit in place."""
    return glyph_icon("edit", color)


def typewriter_icon(color: str | QColor) -> QIcon:
    """A page being written: what the agent is told about a project."""
    return glyph_icon("typewriter", color)


def coverage_icon(color: str | QColor) -> QIcon:
    """Dots joined by a line — a passage, a feature, what became of it."""
    return glyph_icon("coverage", color)


def read_icon(color: str | QColor) -> QIcon:
    """An open book: reading."""
    return glyph_icon("read", color)


def external_icon(color: str | QColor) -> QIcon:
    """An arrow leaving a box: open outside the application."""
    return glyph_icon("external", color)


def leaf_icon(color: str | QColor) -> QIcon:
    """A page: a thing with no children."""
    return glyph_icon("leaf", color)


def project_icon(color: str | QColor) -> QIcon:
    """A board: a project."""
    return glyph_icon("project", color)


def graph_icon(color: str | QColor) -> QIcon:
    """Joined nodes: a project's step graph."""
    return glyph_icon("graph", color)


def spec_icon(color: str | QColor) -> QIcon:
    """A page of lines: a specification."""
    return glyph_icon("spec", color)


def folder_icon(color: str | QColor) -> QIcon:
    """A folder: the workspace directory."""
    return glyph_icon("folder", color)


def branch_icon(color: str | QColor) -> QIcon:
    """A git branch."""
    return glyph_icon("branch", color)


def plus_icon(color: str | QColor) -> QIcon:
    """A plus: add a step, or an aspect."""
    return glyph_icon("plus", color)


def trash_icon(color: str | QColor) -> QIcon:
    """A waste basket: delete."""
    return glyph_icon("trash", color)


def unlink_icon(color: str | QColor) -> QIcon:
    """A broken chain: remove a link."""
    return glyph_icon("unlink", color)


def lasso_icon(color: str | QColor) -> QIcon:
    """A loop with its rope trailing: draw round the steps to pick."""
    return glyph_icon("lasso", color)


def isolate_icon(color: str | QColor) -> QIcon:
    """A chain crossed out: cut a selection loose from everything."""
    return glyph_icon("isolate", color)


def link_icon(color: str | QColor) -> QIcon:
    """A chain: the two steps are joined, or a markdown link joins text to an address."""
    return glyph_icon("link", color)


def connect_icon(color: str | QColor) -> QIcon:
    """A chain with a plus: the mode that draws one."""
    return glyph_icon("connect", color)


def redirect_to_icon(color: str | QColor) -> QIcon:
    """An arrow branching right: move the arrowheads."""
    return glyph_icon("redirect-to", color)


def redirect_from_icon(color: str | QColor) -> QIcon:
    """The mirror of it: move the tails."""
    return glyph_icon("redirect-from", color)


def divide_vertical_icon(color: str | QColor) -> QIcon:
    """An upright cut, with room made either side."""
    return glyph_icon("divide-vertical", color)


def divide_horizontal_icon(color: str | QColor) -> QIcon:
    """The same cut on its side."""
    return glyph_icon("divide-horizontal", color)


def sort_icon(color: str | QColor) -> QIcon:
    """A little tree: laying the graph out by what feeds what."""
    return glyph_icon("sort", color)


def region_icon(color: str | QColor) -> QIcon:
    """A titled area drawn behind the graph."""
    return glyph_icon("region", color)


def grid_icon(color: str | QColor) -> QIcon:
    """Ruled dots: what a drag, a resize and a placed card land on."""
    return glyph_icon("grid", color)


def undo_icon(color: str | QColor) -> QIcon:
    """An arrow curving back on itself."""
    return glyph_icon("undo", color)


def redo_icon(color: str | QColor) -> QIcon:
    """The same arrow the other way round."""
    return glyph_icon("redo", color)


def frame_icon(color: str | QColor) -> QIcon:
    """Four corners: fit the whole graph in the window."""
    return glyph_icon("frame", color)


def refresh_icon(color: str | QColor) -> QIcon:
    """A circular arrow: run it again, now."""
    return glyph_icon("refresh", color)


def find_icon(color: str | QColor) -> QIcon:
    """A magnifier: name a step, and land on it."""
    return glyph_icon("find", color)


def star_icon(color: str | QColor) -> QIcon:
    """A star: the default — what a plain Run Agent… runs."""
    return glyph_icon("star", color)


def options_icon(color: str | QColor) -> QIcon:
    """Sliders: how the graph is drawn, rather than what is drawn."""
    return glyph_icon("options", color)


def mark_starts_icon(color: str | QColor) -> QIcon:
    """A bar with the flow leaving it: a step nothing comes before."""
    return glyph_icon("mark-starts", color)


def mark_ends_icon(color: str | QColor) -> QIcon:
    """The flow arriving at a bar: a step nothing comes after."""
    return glyph_icon("mark-ends", color)


def mark_orphans_icon(color: str | QColor) -> QIcon:
    """A dotted ring: joined to nothing at all."""
    return glyph_icon("mark-orphans", color)


def gauge_icon(color: str | QColor) -> QIcon:
    """A dial: an estimate."""
    return glyph_icon("gauge", color)


def clock_icon(color: str | QColor) -> QIcon:
    """A clock: time."""
    return glyph_icon("clock", color)


def image_icon(color: str | QColor) -> QIcon:
    """A picture: an attached image."""
    return glyph_icon("image", color)


# -- the markdown toolbar ---------------------------------------------------------------
# What a mark does to the text it wraps. Four more of these — inline code, a link, a
# picture and a numbered list — are the painters above, because the glyph for "this is
# code" is the glyph for "the code repository" and a second copy of one SVG would be a
# second thing to keep in step.


def bold_icon(color: str | QColor) -> QIcon:
    """A weighted B: the selection in bold."""
    return glyph_icon("bold", color)


def italic_icon(color: str | QColor) -> QIcon:
    """A leaning I: the selection in italics."""
    return glyph_icon("italic", color)


def heading_icon(level: int) -> Callable[[str | QColor], QIcon]:
    """The painter for one heading level — H1, H2 or H3.

    A factory rather than three near-identical functions: the level is the only thing
    that differs, and the toolbar wants them as a sequence anyway.
    """

    def paint(color: str | QColor) -> QIcon:
        return glyph_icon(f"heading-{level}", color)

    return paint


def bullet_list_icon(color: str | QColor) -> QIcon:
    """Dots and lines: an unordered list."""
    return glyph_icon("bullet-list", color)


def quote_icon(color: str | QColor) -> QIcon:
    """A quotation mark: a block quote."""
    return glyph_icon("quote", color)


def table_icon(color: str | QColor) -> QIcon:
    """A grid: a markdown table."""
    return glyph_icon("table", color)


def list_icon(color: str | QColor) -> QIcon:
    """A numbered list: the order table, and the markdown toolbar's `1.` verb."""
    return glyph_icon("list", color)


def tag_icon(color: str | QColor) -> QIcon:
    """A label: a milestone the graph aims at."""
    return glyph_icon("tag", color)


def spark_icon(color: str | QColor) -> QIcon:
    """Sparkles: there is machine guidance here."""
    return glyph_icon("spark", color)


def beaker_icon(color: str | QColor) -> QIcon:
    """A flask: this step keeps tests."""
    return glyph_icon("beaker", color)


def shield_icon(color: str | QColor) -> QIcon:
    """A shield with a tick: a check stands for everything behind it."""
    return glyph_icon("shield", color)


def layers_icon(color: str | QColor) -> QIcon:
    """Stacked sheets: a feature collects the work behind it."""
    return glyph_icon("layers", color)


def problem_icon(color: str | QColor) -> QIcon:
    """A warning triangle: what is wrong with the plan."""
    return glyph_icon("problem", color)


def check_icon(color: str | QColor) -> QIcon:
    """A tick: record the picked tests as passing."""
    return glyph_icon("check", color)


def skip_icon(color: str | QColor) -> QIcon:
    """Skip forward: record them as skipped — looked at, not run."""
    return glyph_icon("skip", color)


def eraser_icon(color: str | QColor) -> QIcon:
    """An eraser: take a recorded result back."""
    return glyph_icon("eraser", color)


def play_icon(color: str | QColor) -> QIcon:
    """Play: open a test run over what is in scope."""
    return glyph_icon("play", color)


def stop_icon(color: str | QColor) -> QIcon:
    """Stop: close the open run."""
    return glyph_icon("stop", color)


def archive_icon(color: str | QColor) -> QIcon:
    """An archive box: the tests taken off the roster."""
    return glyph_icon("archive", color)


def eye_icon(color: str | QColor) -> QIcon:
    """An eye: light what wants a look."""
    return glyph_icon("eye", color)


def attach_icon(color: str | QColor) -> QIcon:
    """A paperclip: attach a file."""
    return glyph_icon("attach", color)


def clipboard_icon(color: str | QColor) -> QIcon:
    """A clipboard: copy a path."""
    return glyph_icon("clipboard", color)


def sweep_icon(color: str | QColor) -> QIcon:
    """A list struck through: clean up what nothing uses."""
    return glyph_icon("sweep", color)


def camera_icon(color: str | QColor) -> QIcon:
    """A camera: keep the plan as it stands, to compare against later."""
    return glyph_icon("camera", color)


def calendar_off_icon(color: str | QColor) -> QIcon:
    """A struck-out calendar: take a date of its own away."""
    return glyph_icon("calendar-off", color)


def palette_icon(color: str | QColor) -> QIcon:
    """A painter's palette: a milestone's colour."""
    return glyph_icon("palette", color)


def step_icon(color: str | QColor) -> QIcon:
    """A card: a plain step."""
    return glyph_icon("step", color)


def info_icon(color: str | QColor) -> QIcon:
    """An i in a circle: the sentence beside a caption."""
    return glyph_icon("info", color)


def ticket_icon(color: str | QColor) -> QIcon:
    """A ticket: the issue this step is filed under."""
    return glyph_icon("ticket", color)


def code_icon(color: str | QColor) -> QIcon:
    """Angle brackets: the code repository, and code in a markdown document."""
    return glyph_icon("code", color)


def pull_request_icon(color: str | QColor) -> QIcon:
    """A pull request."""
    return glyph_icon("pull-request", color)


def clone_icon(color: str | QColor) -> QIcon:
    """Two pages: a clone arriving."""
    return glyph_icon("clone", color)


def move_icon(color: str | QColor) -> QIcon:
    """A page leaving: a plan moving out."""
    return glyph_icon("move", color)


def close_icon(color: str | QColor) -> QIcon:
    """A cross: the close button on a tab, and a panel's way out.

    Two pixmaps rather than one because Qt asks for the ``Disabled`` variant whenever the
    button is neither hovered nor on the current tab, and the variant it generates for
    itself is greyscale — the one colour a theme cannot reach.
    """
    idle = QColor(color)
    idle.setAlpha(IDLE_GLYPH_ALPHA)
    icon = QIcon()
    icon.addPixmap(glyph_icon("close", color).pixmap(ICON_SIZE, ICON_SIZE), QIcon.Mode.Normal)
    icon.addPixmap(glyph_icon("close", idle).pixmap(ICON_SIZE, ICON_SIZE), QIcon.Mode.Disabled)
    return icon


# The medallion vocabulary the canvas paints, as row and menu icons: one glyph per kind name
# a step can wear ("tag" a milestone, "layers" a feature, "spark" an agent step, "beaker" one
# carrying tests, "shield" a check). It lives here, beside the glyphs, so a surface that shows
# what kind a step is looks it up rather than keeping its own table.
GLYPH_ICONS: dict[str, Callable[[str | QColor], QIcon]] = {
    "step": step_icon,
    "tag": tag_icon,
    "layers": layers_icon,
    "spark": spark_icon,
    "beaker": beaker_icon,
    "shield": shield_icon,
    "ticket": ticket_icon,
}


def glyph_painter(kind: str) -> Callable[[QColor], QIcon] | None:
    """The painter for one kind name, or None for a name this build has no glyph for."""
    return GLYPH_ICONS.get(kind)


# A step's key as a badge — the width a three-character key needs at a glyph's height.
KEY_BADGE_W = 28
KEY_BADGE_ALPHA = 44  # The tone washed under the letters; the border and the ink at full.
KEY_BADGE_POINTS = 7.5


def key_badge_icon(text: str, color: str | QColor) -> QIcon:
    """``F1``, ``M2`` as a rounded chip in a tone: a glyph that names the step.

    Where a row is a milestone the badge stands where the glyph would — the key is what a
    milestone is known by across the graph, and a tag glyph beside a key on the second
    line said the same thing twice.
    """
    pixmap, painter = _canvas(KEY_BADGE_W)
    tone = QColor(color)
    wash = QColor(tone)
    wash.setAlpha(KEY_BADGE_ALPHA)
    painter.setPen(_pen(tone, 1.0))
    painter.setBrush(wash)
    painter.drawRoundedRect(QRectF(0.5, 0.5, KEY_BADGE_W - 1.0, ICON_SIZE - 1.0), 4.0, 4.0)
    font = painter.font()
    font.setPointSizeF(KEY_BADGE_POINTS)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(tone)
    painter.drawText(QRectF(0.0, 0.0, KEY_BADGE_W, ICON_SIZE), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


# A colour map as a strip: wide enough to read the ramp, short enough to sit in a menu row.
PALETTE_STRIP = QSize(56, 12)
PALETTE_STRIP_RADIUS = 3


def palette_strip_icon(found: Palette, size: QSize = PALETTE_STRIP) -> QIcon:
    """A milestone colour map as a strip, dark to light — the map before it is dealt.

    The Time tab's picker and the command palette both show it, which is why it lives here
    rather than beside either of them: one painter, so the two surfaces cannot draw the same
    map differently. ``size`` is the caller's because the two want different shapes — a wide
    strip in a combo row, a square at :data:`ICON_SIZE` in a list of glyphs — and a wide
    pixmap scaled into a square slot renders as a sliver.
    """
    pixmap, painter = _canvas(size.width(), size.height())
    gradient = QLinearGradient(QPointF(0, 0), QPointF(size.width(), 0))
    last = len(found.stops) - 1
    for index, stop in enumerate(found.stops):
        gradient.setColorAt(index / last, QColor(stop))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(
        QRectF(0, 0, size.width(), size.height()),
        PALETTE_STRIP_RADIUS,
        PALETTE_STRIP_RADIUS,
    )
    painter.end()
    return QIcon(pixmap)


SPINNER_FRAMES = 12  # One turn: a frame every 30°, so the arc reads as turning, not jumping.


def spinner_frames(color: str | QColor, count: int = SPINNER_FRAMES) -> list[QIcon]:
    """A three-quarter arc at ``count`` rotations: the glyph of a button whose work is
    running. Painted once per ink and stepped by ``framework/signalling.py``'s Spinner."""
    frames = []
    for step in range(count):
        pixmap, painter = _canvas()
        painter.setPen(_pen(color, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        start = (90 - step * 360 // count) * 16
        painter.drawArc(QRectF(2.5, 2.5, 11.0, 11.0), start, -270 * 16)
        painter.end()
        frames.append(QIcon(pixmap))
    return frames


FILTER_ICON_W = 24  # A dot's slot at the left, then the funnel: one width, on or off.


def filter_icon(color: str | QColor, *, active: bool = False) -> QIcon:
    """A funnel with a slot for the indicator before it: outline while no filter is on,
    filled with a dot in the slot while one is — so the face never changes size."""
    pixmap, painter = _canvas(FILTER_ICON_W)
    left = FILTER_ICON_W - ICON_SIZE
    funnel = [
        QPointF(left + 2.5, 3.5),
        QPointF(left + 13.5, 3.5),
        QPointF(left + 9.5, 8.5),
        QPointF(left + 9.5, 13.0),
        QPointF(left + 6.5, 11.5),
        QPointF(left + 6.5, 8.5),
    ]
    painter.setPen(_pen(color, 1.5))
    painter.setBrush(QColor(color) if active else Qt.BrushStyle.NoBrush)
    painter.drawPolygon(funnel)
    if active:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(1.0, 5.5, 5.0, 5.0))
    painter.end()
    return QIcon(pixmap)
