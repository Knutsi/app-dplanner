"""Theme-invariant design tokens, and the token → stylesheet mapping.

Theme-dependent colours live on :class:`dplanner.theme.themes.Theme`; what remains here is
constant across every theme: metrics.

Qt stylesheets have no variable mechanism, so :func:`as_qss_mapping` feeds both these
constants and the active theme's fields into ``theme.qss`` as ``$TOKEN`` placeholders;
:mod:`dplanner.theme.palette` consumes the same theme for the ``QPalette``. One source for
both consumers is what keeps palette and stylesheet from drifting into mismatched greys.
"""

from dataclasses import fields
from typing import Final

from dplanner.theme.themes import Theme

# Metrics.
RADIUS_SM: Final = 5
RADIUS_MD: Final = 8

# Spacing, on DESIGN.md's 4-point scale. One declaration each: a dialog and a panel that
# disagree about a margin are two surfaces that read as two products.
DIALOG_MARGIN: Final = 20  # A dialog's outer margin: dialogs breathe more than panels.
SECTION_GAP: Final = 12  # Between sections; between blocks; between cards; body to footer.
FIELD_GAP: Final = 8  # Fields within a section; footer buttons.
CONTROL_GAP: Final = 12  # Between the controls on a strip: a packed row of verbs reads as one.
CONTROL_HEIGHT: Final = 32  # Every control on a strip: a glyph button, a worded one, a combo.
CAPTION_GAP: Final = 6  # A caption to its field, a note to its field.
PANEL_MARGIN: Final = 16  # Side panels and tab pages.
# A rich row (a list of two-line items, a two-line table cell): DESIGN.md's list-row rule.
ROW_PADDING_V: Final = 10
ROW_PADDING_H: Final = 12
ROW_LINE_GAP: Final = 4
# A plain table cell, and the header section over it.
CELL_PADDING_V: Final = 6
CELL_PADDING_H: Final = 8
# ~63 %: DESIGN.md's opacity-derived secondary text, for a painter that has only the palette.
SECONDARY_ALPHA: Final = 160
# The slice of the screen a framed or editor-sized dialog claims. A float is Python-only:
# ``as_qss_mapping`` takes ints and strings, and a stylesheet has no use for a ratio.
SCREEN_SHARE: Final = 0.8
# The arrow half of a button that drops a child menu down. Qt's own metric is about ten
# pixels — a sliver too thin to aim at, and one that reads as a fault beside the button it
# is attached to. Wide enough to be a target, narrow enough that the words still lead.
ARROW_W: Final = 20
# The room a worded button leaves for it: the arrow's width and DESIGN.md's 4 px beside it.
# A styled subcontrol is outside Qt's size hint, so the text runs under the arrow without it.
ARROW_ROOM: Final = ARROW_W + 4


def mix(first: str, second: str, share: float) -> str:
    """``first`` blended ``share`` of the way towards ``second``, both ``#rrggbb``."""
    a = [int(first.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(second.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(
        f"{round(x * (1 - share) + y * share):02x}" for x, y in zip(a, b, strict=True)
    )


def as_qss_mapping(theme: Theme) -> dict[str, str]:
    """Every invariant token plus the theme's colours, for ``string.Template``.

    Collected by introspection rather than a hand-maintained dict, so adding a module
    constant above or a field to :class:`Theme` makes it available to the stylesheet with
    no second edit. A few tokens are derived from the theme rather than stored on it —
    a hairline at half strength — so a theme provider never has to know they exist.
    """
    mapping = {
        name: str(value)
        for name, value in globals().items()
        if name.isupper() and isinstance(value, str | int)
    }
    for field in fields(theme):
        value = getattr(theme, field.name)
        if field.name != "name" and isinstance(value, str):
            mapping[field.name.upper()] = value
    # A divider between controls, faded halfway into the ground: a rule that parts without
    # drawing attention, where $BORDER is a hairline meant to be seen.
    mapping["BORDER_FAINT"] = mix(theme.border, theme.bg_base, 0.5)
    # The accent washed over the overlay ground: a control that is *on* (a filter) without
    # being filled, so its words keep their ink.
    mapping["ACCENT_WASH"] = mix(theme.bg_overlay, theme.accent, 0.22)
    return mapping
