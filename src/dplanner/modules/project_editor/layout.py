"""Where a step's node goes when nobody has placed it.

Plain functions over the model, with no Qt anywhere, so the interesting part — does the graph
read left to right in dependency order — is testable without a widget in sight. Writer's
corkboard splits its move rules out for the same reason.

**Nothing here is ever written to disk.** A computed position is recomputed every time the
project opens; only a step somebody actually dragged earns a stored one. Persisting the
automatic layout would mean that merely opening a tab dirtied the workspace, autosave would
flush it 1.5 seconds later, and every step an agent created through the CLI would grow a
position file the next time a window happened to open.
"""

from dplanner.domain.model import Product, Project, StepId

# Roughly a node and a half apart, so an edge is visible between two columns.
COLUMN_SPACING = 260.0
ROW_SPACING = 110.0
ORIGIN_X = 40.0
ORIGIN_Y = 40.0


def depths(product: Product, project: Project) -> dict[StepId, int]:
    """How many ``requires`` edges deep each step is — the length of its longest chain.

    Cycles cannot occur: the model refuses to create one, so the walk always terminates.
    An edge pointing at a step outside this project cannot occur either, for the same reason.
    """
    known: dict[StepId, int] = {}

    def depth_of(step_id: StepId, seen: frozenset[StepId]) -> int:
        if step_id in known:
            return known[step_id]
        if step_id in seen:  # Defensive: a hand-edited file could still contain one.
            return 0
        waiting = product.step(step_id).edges.get("requires", [])
        resolved = [t for t in waiting if project.step(t) is not None]
        found = 0 if not resolved else 1 + max(depth_of(t, seen | {step_id}) for t in resolved)
        known[step_id] = found
        return found

    for step in project.steps:
        depth_of(step.id, frozenset())
    return known


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
