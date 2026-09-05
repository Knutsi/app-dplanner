"""Files the application ships: its icon, at the sizes a desktop asks for.

The icon is rendered by ``scripts/render_icon.py`` and committed, because the two readers
cannot share a renderer: the window sets it through Qt, and ``dplanner desktop install``
writes it into a launcher from a process that must never load Qt. One list of sizes and
one path rule here, so neither reader can name a file the other does not ship.
"""

from importlib.resources import files
from pathlib import Path

ICON_SIZES = (16, 32, 48, 64, 128, 256, 512)


def icon_path(size: int) -> Path:
    """The PNG at ``size`` pixels square — one of :data:`ICON_SIZES`."""
    return Path(str(files("dplanner.assets").joinpath("icons", f"dplanner-{size}.png")))
