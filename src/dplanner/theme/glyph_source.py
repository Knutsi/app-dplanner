"""The vendored glyphs as text: where they are, and what one says, with no graphics stack.

``theme/icons.py`` paints a glyph through Qt's SVG renderer; the report draws the same one
into a page for people with no DPlanner, from the CLI, which may load no Qt at all. Both
read the file here, so the glyph a card wears on the canvas and on the page is one file
read one way. The CLI itself may not import ``theme/`` (``tests/test_architecture.py``), so
a module's Qt-free ``report.py`` reads the drawing here and hands it over as data.
"""

import re
from functools import lru_cache
from importlib.resources import files

GLYPH_DIR = files("dplanner.theme").joinpath("glyphs")

# Everything between the root's opening tag and its close: Tabler's files are one ``<svg>``
# of stroked shapes, after a comment that carries its tags.
_DRAWING = re.compile(r"<svg\b[^>]*>(.*)</svg>", re.DOTALL)


@lru_cache(maxsize=128)
def glyph_source(name: str) -> str:
    """One vendored glyph's SVG, as Tabler published it."""
    return GLYPH_DIR.joinpath(f"{name}.svg").read_text(encoding="utf-8")


@lru_cache(maxsize=128)
def glyph_markup(name: str) -> str:
    """The shapes inside the glyph's root — its drawing, without the ``<svg>`` around it.

    The root is where Tabler says how to draw them: a 24-unit view box, stroked in
    ``currentColor`` two units wide with round caps and joins, unfilled. A drawing that
    places a glyph says the same on a group of its own, in a colour it names — an SVG
    renderer that knows no ``currentColor`` (Qt's, which prints the report) never meets it.
    """
    found = _DRAWING.search(glyph_source(name))
    if found is None:
        return ""
    return " ".join(line.strip() for line in found.group(1).splitlines() if line.strip())
