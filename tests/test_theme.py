"""Theme invariants.

A stylesheet is not type-checked and a colour is not tested by looking at it, so these
assert the properties that actually break: an unsubstituted token silently discards the
rule around it, and a palette that only fills the Active colour group makes a dark theme
turn light the moment the window loses focus.
"""

import re
from importlib.resources import files
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu, QSplitter, QStyle, QToolButton, QWidget

import dplanner
from dplanner.theme import load_stylesheet, tokens
from dplanner.theme.icons import ICON_SIZE, plus_icon
from dplanner.theme.palette import build_palette
from dplanner.theme.providers import BUILTIN, OMARCHY_THEMES
from dplanner.theme.style import build_style
from dplanner.theme.themes import DARK, DEFAULT, LIGHT

# Every theme the built-in provider offers: the house themes and the generated Omarchy ones.
THEMES = {theme.name: theme for theme in BUILTIN.themes()}
TOKYO_NIGHT = next(theme for theme in OMARCHY_THEMES if theme.name == "tokyo-night")


def relative_lightness(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


@pytest.mark.parametrize("theme", THEMES.values(), ids=list(THEMES))
def test_every_theme_substitutes_fully(theme):
    """A leftover $TOKEN makes Qt discard the rule around it — silently."""
    assert "$" not in load_stylesheet(theme)


# An object name the stylesheet styles that no ``setObjectName("…")`` literal sets: name → why
# (a name composed at runtime, say). Empty on purpose; an entry here needs its reason.
NAMED_DYNAMICALLY: dict[str, str] = {}


def test_every_name_the_stylesheet_styles_is_set_by_some_widget():
    """A rule for a surface that no longer exists is not dead weight but a lie: the next
    reader copies its look, sets the name, and gets a rule written for another widget.
    Forty per cent of this file once described the application the template came from."""
    raw = files("dplanner.theme").joinpath("theme.qss").read_text(encoding="utf-8")
    assert "Writer" not in raw
    rules = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    names = set(re.findall(r"#([A-Z][A-Za-z0-9_]*)", rules))  # A capital: never a hex colour.
    package = Path(dplanner.__file__).parent
    source = "".join(p.read_text(encoding="utf-8") for p in package.rglob("*.py"))
    unset = sorted(n for n in names if f'"{n}"' not in source and n not in NAMED_DYNAMICALLY)
    assert unset == []


@pytest.mark.parametrize("theme", THEMES.values(), ids=list(THEMES))
def test_theme_polarity_is_consistent(theme):
    background = relative_lightness(theme.bg_base)
    assert (background < 128) == theme.is_dark


@pytest.mark.parametrize("theme", THEMES.values(), ids=list(THEMES))
def test_body_text_clears_a_contrast_floor(theme):
    """Reading psychology, not taste: prose needs a generous luminance gap."""
    gap = abs(relative_lightness(theme.text_primary) - relative_lightness(theme.bg_base))
    assert gap >= 100, f"{theme.name}: body text sits {gap:.0f} from its background"


@pytest.mark.parametrize("theme", THEMES.values(), ids=list(THEMES))
def test_secondary_text_stays_readable(theme):
    gap = abs(relative_lightness(theme.text_secondary) - relative_lightness(theme.bg_base))
    assert gap >= 40, f"{theme.name}: secondary text sits {gap:.0f} from its background"


@pytest.mark.parametrize("theme", THEMES.values(), ids=list(THEMES))
def test_selected_text_stays_readable(theme):
    """A generated theme's selection pair is Omarchy's own, never hand-tuned here."""
    gap = abs(relative_lightness(theme.selection_fg) - relative_lightness(theme.selection_bg))
    assert gap >= 60, f"{theme.name}: selected text sits {gap:.0f} from its wash"


def test_the_palette_covers_the_inactive_group(app):
    """Qt's Fusion style paints an unfocused window from the Inactive group. Filling only
    Active is why dark themes appear to "go light" the moment focus moves."""
    from PySide6.QtGui import QPalette

    palette = build_palette(DEFAULT)
    active = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
    inactive = palette.color(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Window)
    assert active == inactive


def test_the_default_theme_is_built_in():
    assert DEFAULT in BUILTIN.themes()


def test_the_tab_close_glyph_is_painted_per_theme(app):
    """The cross on a tab is the one mark in the window a palette cannot reach.

    ``PE_IndicatorTabClose`` asks the style for a standard icon and draws whatever it gets,
    so Qt's bundled red ✕ read as an error badge on every theme until the proxy style
    answered with a painted glyph — and the style is rebuilt per theme because it caches
    the answer.
    """
    close = QStyle.StandardPixmap.SP_TabCloseButton
    dark = build_style(DARK).standardIcon(close)
    light = build_style(LIGHT).standardIcon(close)

    assert not dark.isNull()
    assert dark.pixmap(16, 16).toImage() != light.pixmap(16, 16).toImage()


@pytest.mark.parametrize("theme", (DARK, TOKYO_NIGHT), ids=("dark", "tokyo-night"))
@pytest.mark.parametrize(
    "orientation",
    [Qt.Orientation.Horizontal, Qt.Orientation.Vertical],
    ids=["horizontal", "vertical"],
)
def test_a_splitter_seam_is_exactly_one_hairline(app, orientation, theme):
    """Both orientations of a handle draw one line, whatever it takes to get there.

    Asserted by rendering rather than by reading the rule, because Qt paints the two
    differently: a horizontal handle honours the box model and a vertical one fills its whole
    rect with the background and puts its borders outside it. The rule that centres a line in
    the first renders a seven-pixel slab in the second, and nothing in the stylesheet says so.
    Rendered for a generated theme too: its hairline is a derived colour, not a tuned one.
    """
    splitter = QSplitter(orientation)
    for _ in range(2):
        page = QWidget()
        page.setMinimumSize(40, 40)
        splitter.addWidget(page)
    splitter.setStyleSheet(load_stylesheet(theme))
    splitter.resize(120, 120)
    splitter.show()
    app.processEvents()

    image = splitter.grab().toImage()
    across = (
        [image.pixel(60, y) for y in range(40, 80)]
        if orientation is Qt.Orientation.Vertical
        else [image.pixel(x, 60) for x in range(40, 80)]
    )
    border = QColor(theme.border).rgb()
    assert sum(pixel == border for pixel in across) == 1


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
def test_a_buttons_dropdown_arrow_is_a_target_of_its_own(app, theme):
    """A button whose arrow drops a family down is two targets, and both have to be aimable.

    Rendered rather than read, for the reason the splitter seam is: a styled subcontrol sits
    outside Qt's size hint, so a ``::menu-button`` width without the matching padding paints
    the arrow over the last letter — which looks exactly like a rule that did not apply.
    """
    button = QToolButton()
    button.setObjectName("ToolbarButton")
    button.setText("Divide")
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setMenu(QMenu(button))
    button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    button.setProperty("hasMenu", True)
    button.setStyleSheet(load_stylesheet(theme))
    button.resize(button.sizeHint())
    button.show()
    app.processEvents()

    arrow = button.style().subControlRect(
        QStyle.ComplexControl.CC_ToolButton,
        _tool_option(button),
        QStyle.SubControl.SC_ToolButtonMenu,
        button,
    )
    assert arrow.width() >= tokens.ARROW_W

    # And the words stop before it: the last column of the text half is background.
    image = button.grab().toImage()
    ground = QColor(theme.bg_overlay).rgb()
    column = [image.pixel(arrow.left() - 2, y) for y in range(4, button.height() - 4)]
    assert all(pixel == ground for pixel in column)


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
@pytest.mark.parametrize("name", ("TemplateButton", "LayoutButton"))
def test_a_faces_indicator_stands_clear_of_its_border(app, theme, name):
    """A face's arrow is right-aligned in the padding box, which puts it flush against the
    border unless something holds it off.

    It did, and the arrow's ink reached to within a pixel of the button's own edge — which
    reads as a clipped control, and on a fractionally scaled display that pixel is the one
    that goes. Rendered rather than read, because a subcontrol offset is exactly the kind
    of rule that silently does not apply. The ground is read from the render rather than
    from the theme: an application-wide stylesheet is already on this widget.
    """
    button = QToolButton()
    button.setObjectName(name)
    button.setText("Template")
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setMenu(QMenu(button))
    button.setStyleSheet(load_stylesheet(theme))
    button.resize(button.sizeHint())
    button.show()
    app.processEvents()

    image = button.grab().toImage()
    # The middle band only: a rounded corner leaves whatever is behind the widget in the
    # pixels outside its own arc, which is neither ground nor ink.
    middle = range(button.height() // 2 - 4, button.height() // 2 + 4)
    band = [image.pixel(x, y) for x in range(button.width()) for y in middle]
    ground = max(set(band), key=band.count)  # What the button is mostly made of.

    # The inset the rule reserves is the button's own ground all the way to its border,
    # which is the outermost two columns (a hairline and what antialiasing spills).
    for x in range(button.width() - tokens.INDICATOR_INSET, button.width() - 2):
        column = [image.pixel(x, y) for y in middle]
        assert all(pixel == ground for pixel in column), f"ink at x={x} of {button.width()}"


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
@pytest.mark.parametrize(
    ("marker", "popup", "room"),
    (
        ("hasMenu", QToolButton.ToolButtonPopupMode.MenuButtonPopup, tokens.ARROW_ROOM),
        ("face", QToolButton.ToolButtonPopupMode.InstantPopup, tokens.INDICATOR_ROOM),
    ),
    ids=("arrow", "menu face"),
)
def test_a_dense_strips_arrow_keeps_its_room(app, theme, marker, popup, room):
    """A dense strip narrows every button's sides — and must not narrow the arrow's room.

    ``#ControlBar[dense="true"] #ToolbarButton`` is two names and an attribute, so its
    padding shorthand outranks the two rules that ask for the arrow's width. It did, and
    Qt painted a 20 px subcontrol straight over a 16 px glyph: a clipped icon and nothing
    else to show for it, because a styled subcontrol widens no button by itself.
    """
    strip = QWidget()
    strip.setObjectName("ControlBar")
    strip.setProperty("dense", True)
    plain, dropping = (_glyph_button(strip) for _ in range(2))
    dropping.setMenu(QMenu(dropping))
    dropping.setPopupMode(popup)
    dropping.setProperty(marker, True)
    strip.setStyleSheet(load_stylesheet(theme))
    strip.show()
    app.processEvents()

    # The room replaces the dense side padding rather than adding to it, and what is left
    # is what the arrow is drawn in.
    gained = dropping.sizeHint().width() - plain.sizeHint().width()
    assert gained >= room - tokens.DENSE_GAP


@pytest.mark.parametrize("ratio", (1.0, 2.0, 3.0), ids=("1x", "2x", "3x"))
def test_a_glyph_is_the_same_picture_at_every_device_pixel_ratio(app, monkeypatch, ratio):
    """A glyph is painted at the screen's resolution, in glyph units either way.

    The pixmap grows with the ratio and carries it; the painter is *not* scaled, because a
    paint device that declares a ratio already maps logical coordinates. Scaling it as well
    applies the ratio twice and the glyph lands in the top-left quarter of its own icon —
    which is what shipped, and which the offscreen platform cannot show, because there the
    ratio is always 1. Hence a forced ratio here.
    """
    from dplanner.theme import icons

    monkeypatch.setattr(icons, "_ratio", lambda: ratio)
    pixmap = icons.plus_icon("#ffffff").pixmap(QSize(ICON_SIZE, ICON_SIZE), ratio)
    image = pixmap.toImage()
    assert image.width() == round(ICON_SIZE * ratio)  # Painted at the screen's resolution…

    lit = [
        x
        for x in range(image.width())
        if any(image.pixelColor(x, y).alpha() > 0 for y in range(image.height()))
    ]
    # …and the plus still spans the glyph's own 16 units, whatever the ratio.
    assert min(lit) / ratio < ICON_SIZE / 4
    assert max(lit) / ratio > 3 * ICON_SIZE / 4


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
@pytest.mark.parametrize("drops_a_menu", (False, True), ids=("plain", "with an arrow"))
@pytest.mark.parametrize("checked", (False, True), ids=("off", "on"))
def test_a_toolbar_button_is_bordered_on_all_four_sides(app, theme, drops_a_menu, checked):
    """Rendered, not read — because what broke this was a rule that names no border at all.

    A ``#ToolbarButton:checked::menu-button`` rule, in *any* form, made Qt drop the
    **button's own left border** — on every toolbar button in the application, checked or
    not, menu or no menu. Nothing in the rule says "left border of the widget", and nothing
    short of looking at the pixels could have caught it.
    """
    strip = QWidget()
    strip.setObjectName("ControlBar")
    strip.setProperty("dense", True)
    button = _glyph_button(strip)
    button.setCheckable(True)
    button.setChecked(checked)
    if drops_a_menu:
        button.setMenu(QMenu(button))
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setProperty("hasMenu", True)
    button.setFixedHeight(tokens.CONTROL_HEIGHT)
    button.resize(button.sizeHint())
    strip.resize(button.size())
    strip.setStyleSheet(load_stylesheet(theme))
    strip.show()
    app.processEvents()

    image = button.grab().toImage()
    middle_x, middle_y = button.width() // 2, button.height() // 2
    edges = {
        "left": (0, middle_y),
        "right": (button.width() - 1, middle_y),
        "top": (middle_x, 0),
        "bottom": (middle_x, button.height() - 1),
    }
    drawn = {side: QColor(image.pixel(x, y)).name() for side, (x, y) in edges.items()}
    # One colour on all four, whatever it is: a checked button's border is the accent it is
    # filled with, and an unchecked one's is the hairline. A side that differs from the
    # other three is a side that is not drawn.
    assert len(set(drawn.values())) == 1, drawn


def _glyph_button(parent):
    button = QToolButton(parent)
    button.setObjectName("ToolbarButton")
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    button.setIcon(plus_icon("#ffffff"))
    return button


def _tool_option(button):
    from PySide6.QtWidgets import QStyleOptionToolButton

    option = QStyleOptionToolButton()
    button.initStyleOption(option)
    return option


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
def test_a_combo_box_on_a_strip_wears_the_quiet_bordered_look(themed, theme):
    """Beside the strip's buttons a Fusion combo box read as another product's; rendered,
    its ground inside the border is the overlay the buttons wear."""
    from PySide6.QtWidgets import QComboBox

    from dplanner.framework.toolbar import Toolbar
    from dplanner.theme import apply_theme

    apply_theme(themed, theme)
    bar = Toolbar()
    combo = QComboBox(bar)
    combo.addItems(["All steps", "Milestones"])
    bar.add_widget(combo)
    bar.resize(bar.sizeHint())
    bar.show()
    themed.processEvents()
    try:
        image = combo.grab().toImage()
        assert image.pixelColor(4, combo.height() // 2) == QColor(theme.bg_overlay)
    finally:
        bar.deleteLater()
