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
from dplanner.modules.project_editor.sorts import layered_flow


def auto_positions(library: Library, project: Project) -> dict[StepId, tuple[float, float]]:
    """A position for every step, from the graph alone.

    A pure function of the graph, so it only moves a node when the graph itself changed.
    """
    return layered_flow(library, project)


def positions(library: Library, project: Project) -> dict[StepId, tuple[float, float]]:
    """Where every node goes: what was stored, falling back to the automatic layout."""
    from dplanner.modules.project_editor.positions import read_position

    automatic = auto_positions(library, project)
    return {step.id: (read_position(step) or automatic[step.id]) for step in project.steps}
