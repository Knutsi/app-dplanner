"""Where a step's node goes when nobody has placed it.

Plain functions over the model, with no Qt anywhere, so the interesting part — does the graph
read left to right in dependency order — is testable without a widget in sight.

The arrangement itself is ``sorts.layered_flow``, the same algorithm the Sort menu offers —
one implementation, whether the layout is ambient or asked for. The difference is what
happens to the result: a sort *action* is a user gesture and persists through the undo
stack; the fallback here is recomputed every time the project opens.

**Nothing here is ever written to disk.** A computed position is recomputed every time the
project opens; only a step somebody actually dragged — or a sort somebody actually ran —
earns a stored one. Persisting the automatic layout would mean that merely opening a tab
dirtied the workspace, autosave would flush it 1.5 seconds later, and every step an agent
created through the CLI would grow a position file the next time a window happened to open.
"""

from dplanner.domain.model import Library, Project, StepId
from dplanner.modules.project_editor.positions import (
    GRID,
    NODE_H,
    NODE_W,
    node_size,
    snapped,
)
from dplanner.modules.project_editor.sorts import H_GAP, ORIGIN, V_GAP, V_PITCH, layered_flow

type Box = tuple[float, float, float, float]  # x, y, w, h — a card as it is drawn.
type Size = tuple[float, float]


def auto_positions(library: Library, project: Project) -> dict[StepId, tuple[float, float]]:
    """A position for every step, from the graph alone.

    A pure function of the graph, so it only moves a node when the graph itself changed.
    """
    return layered_flow(library, project)


def positions(library: Library, project: Project) -> dict[StepId, tuple[float, float]]:
    """Where every node goes: what was stored, falling back to the automatic layout.

    The layout is computed only when some step needs it. Every canvas sync asks this
    question, and a settled plan — every step dragged or sorted into place — used to pay a
    whole layered flow per keystroke for an answer it then discarded step by step.
    """
    from dplanner.modules.project_editor.positions import read_position

    stored = {step.id: read_position(step) for step in project.steps}
    if all(stored.values()):
        return {step_id: position for step_id, position in stored.items() if position is not None}
    automatic = auto_positions(library, project)
    return {step.id: stored[step.id] or automatic[step.id] for step in project.steps}


def below(x: float, y: float, height: float = NODE_H) -> tuple[float, float]:
    """One row down from a point: where a second node dropped at the same spot goes.

    The automatic layout's own row pitch, so steps stacked by pressing New twice line up
    with steps the layout would have arranged — and two of them never land on one another.
    ``height`` is the card already at the point, when it is taller than the default.
    """
    return (x, y + height + V_GAP)


def boxes(library: Library, project: Project) -> list[Box]:
    """Every card as the canvas would draw it now: where it sits, at its own footprint."""
    placed = positions(library, project)
    return [(*placed[step.id], *node_size(step)) for step in project.steps if step.id in placed]


def free_spot(
    library: Library, project: Project, size: Size = (NODE_W, NODE_H)
) -> tuple[float, float]:
    """A grid-snapped top-left no card overlaps: a fresh column, right of everything.

    Where a step born by a gesture with no point goes — the Specs tab's *New feature
    step…*, and whatever asks next. It walks *down* a row at a time from the top of the
    graph while anything is in the way, so a second one made straight after the first sits
    under it rather than on it, and the column it opens is a column nothing is in.

    A stored position, rather than letting the ambient layout answer, for the same reason
    a step placed by pointing earns one: the alternative is ``layered_flow`` computing a
    coordinate against an arrangement nobody chose, which lands on a hand-placed card.
    """
    drawn = boxes(library, project)
    if not drawn:
        return (snapped(ORIGIN, GRID), snapped(ORIGIN, GRID))
    x = snapped(max(left + width for left, _top, width, _height in drawn) + H_GAP, GRID)
    top = snapped(min(top for _left, top, _width, _height in drawn), GRID)
    width, height = size
    row = 0
    while any(_overlaps((x, top + row * V_PITCH, width, height), box) for box in drawn):
        row += 1
    return (x, top + row * V_PITCH)


def _overlaps(one: Box, other: Box) -> bool:
    ax, ay, aw, ah = one
    bx, by, bw, bh = other
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah
