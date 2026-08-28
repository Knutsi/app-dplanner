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


def as_qss_mapping(theme: Theme) -> dict[str, str]:
    """Every invariant token plus the theme's colours, for ``string.Template``.

    Collected by introspection rather than a hand-maintained dict, so adding a module
    constant above or a field to :class:`Theme` makes it available to the stylesheet with
    no second edit.
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
    return mapping
