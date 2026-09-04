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
from dplanner.modules.project_editor.positions import NODE_H
from dplanner.modules.project_editor.sorts import V_GAP, layered_flow


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


def below(x: float, y: float) -> tuple[float, float]:
    """One row down from a point: where a second node dropped at the same spot goes.

    The automatic layout's own row pitch, so steps stacked by pressing New twice line up
    with steps the layout would have arranged — and two of them never land on one another.
    """
    return (x, y + NODE_H + V_GAP)
