"""Where a step's node goes when nobody has placed it.

Plain functions over the model, with no Qt anywhere, so the interesting part — does the graph
read left to right in dependency order — is testable without a widget in sight. Writer's
corkboard splits its move rules out for the same reason.

The dependency walk itself lives in ``domain/ordering.py``: a column here is a wave there, and
one implementation serves the canvas, the order view and the CLI.

**Nothing here is ever written to disk.** A computed position is recomputed every time the
project opens; only a step somebody actually dragged earns a stored one. Persisting the
automatic layout would mean that merely opening a tab dirtied the workspace, autosave would
flush it 1.5 seconds later, and every step an agent created through the CLI would grow a
position file the next time a window happened to open.
"""

from dplanner.domain.model import Product, Project, StepId
from dplanner.domain.ordering import depths

# Roughly a node and a half apart, so an edge is visible between two columns.
COLUMN_SPACING = 260.0
ROW_SPACING = 110.0
ORIGIN_X = 40.0
ORIGIN_Y = 40.0


def auto_positions(product: Product, project: Project) -> dict[StepId, tuple[float, float]]:
    """A position for every step: a column per dependency depth, in the project's own order.

    A pure function of the graph, so it only moves a node when the graph itself changed.
    """
    by_depth = depths(product, project)
    rows: dict[int, int] = {}
    placed: dict[StepId, tuple[float, float]] = {}
    for step in project.steps:
        column = by_depth.get(step.id, 0)
        row = rows.get(column, 0)
        rows[column] = row + 1
        placed[step.id] = (
            ORIGIN_X + column * COLUMN_SPACING,
            ORIGIN_Y + row * ROW_SPACING,
        )
    return placed


def positions(product: Product, project: Project) -> dict[StepId, tuple[float, float]]:
    """Where every node goes: what was stored, falling back to the automatic layout."""
    from dplanner.modules.project_editor.positions import read_position

    automatic = auto_positions(product, project)
    return {step.id: (read_position(step) or automatic[step.id]) for step in project.steps}
