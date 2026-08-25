"""Theme invariants.

A stylesheet is not type-checked and a colour is not tested by looking at it, so these
assert the properties that actually break: an unsubstituted token silently discards the
rule around it, and a palette that only fills the Active colour group makes a dark theme
turn light the moment the window loses focus.
"""

import pytest

from dplanner.theme import load_stylesheet
from dplanner.theme.palette import build_palette
from dplanner.theme.themes import DEFAULT, THEMES


def relative_lightness(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


@pytest.mark.parametrize("theme", THEMES.values(), ids=list(THEMES))
def test_every_theme_substitutes_fully(theme):
    """A leftover $TOKEN makes Qt discard the rule around it — silently."""
    assert "$" not in load_stylesheet(theme)


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


def test_the_palette_covers_the_inactive_group(app):
    """Qt's Fusion style paints an unfocused window from the Inactive group. Filling only
    Active is why dark themes appear to "go light" the moment focus moves."""
    from PySide6.QtGui import QPalette

    palette = build_palette(DEFAULT)
    active = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
    inactive = palette.color(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Window)
    assert active == inactive


def test_the_default_theme_is_registered():
    assert DEFAULT.name in THEMES
