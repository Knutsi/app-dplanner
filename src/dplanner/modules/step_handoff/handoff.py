"""Who inherits what: the handoff derivation.

**Inherited material is computed, never stored** — the same rule the topological order
follows, and for the same reason: ``dplanner step link`` changes the graph with no window
running to notice, and a stored inheritance would be wrong the moment it did. One function
answers for the inspector, the CLI and the assembled agent prompt, so the three can never
disagree.

The file area is handed in as a function rather than a store, the way
:mod:`dplanner.domain.schedule` is handed ``days_for`` — whoever calls decides where files
live, and this module works headless with no store at all.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.domain.assets import assets
from dplanner.domain.model import Product, Step, StepId
from dplanner.domain.ordering import placed
from dplanner.domain.store import ModuleFileArea
from dplanner.modules.step_handoff.aspect import MODULE_ID, read_note, read_scope

# The seam: (step id, module id) -> that module's file area. ``ProductStore.files`` is one.
FilesFor = Callable[[StepId, str], ModuleFileArea]


@dataclass(frozen=True)
class Handoff:
    step_id: StepId
    title: str
    note: str
    scope: str
    assets: tuple[str, ...]  # Workspace-relative paths, ready to print for an agent.


def own(product: Product, step: Step, files: FilesFor) -> Handoff | None:
    """What this step hands forward, or None when it hands forward nothing."""
    note = read_note(step)
    paths = asset_paths(files, step.id)
    if not note and not paths:
        return None
    return Handoff(
        step_id=step.id,
        title=step.title or "Untitled step",
        note=note,
        scope=read_scope(step),
        assets=paths,
    )


def inherited(product: Product, step: Step, files: FilesFor) -> list[Handoff]:
    """Everything this step's worker should know, in the order the work was done.

    The handoffs of every transitive ``requires`` ancestor, plus every project-scoped
    handoff from the rest of the project — walked once over the topological order, so the
    result is deterministic and an ancestor is never listed twice.
    """
    project = product.project_of(step.id)
    ancestors = _ancestors(product, step)
    found = []
    for place in placed(product, project):
        other = place.step
        if other.id == step.id:
            continue
        if other.id not in ancestors and read_scope(other) != "project":
            continue
        handoff = own(product, other, files)
        if handoff is not None:
            found.append(handoff)
    return found


def inherited_text(handoffs: list[Handoff]) -> str:
    """The inherited context as text — what the CLI prints and the inspector shows.

    One renderer, so the terminal and the window cannot describe the same inheritance two
    ways.
    """
    if not handoffs:
        return "Nothing handed forward yet."
    blocks = []
    for handoff in handoffs:
        lines = [f"From {handoff.title}:"]
        if handoff.note:
            lines.extend(f"  {line}" for line in handoff.note.splitlines())
        lines.extend(f"  {path}" for path in handoff.assets)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _ancestors(product: Product, step: Step) -> set[StepId]:
    seen: set[StepId] = set()
    queue = [step.id]
    while queue:
        for required in product.requires(queue.pop()):
            if required.id not in seen:
                seen.add(required.id)
                queue.append(required.id)
    return seen


def asset_paths(files: FilesFor, step_id: StepId) -> tuple[str, ...]:
    """The step's handoff files as workspace-relative paths.

    A node the store has never flushed has no directory yet, and the store says so with a
    ``KeyError`` — a step created this run simply has no files to list.
    """
    try:
        area = files(step_id, MODULE_ID)
    except KeyError:
        return ()
    return tuple(f"{area.directory}/{name}" for name in assets(area))
