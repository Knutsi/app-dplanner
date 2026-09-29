"""Putting steps on a branch, and taking a branch off them — each one rewire, one undo step.

**Put on a Branch** brackets the picked steps: a cut born in front of them and a landing
behind. Outside links move to the ends — what any picked step waited on from outside, the
cut waits on, and what waited on any picked step from outside waits on the landing — so the
pick becomes one way in and one way out, which is what a branch is to git. Every picked
step nothing else picked precedes waits on the cut, and the landing waits on every picked
step nothing else picked follows, so none of them is left off the branch or unlanded.

**Remove Branch** is the opposite, and it is never partial: the cut and the landing are
removed and the links close over the gap they leave, so every step on the branch is back
where it was — not only the ones picked. That is why the window asks first.
"""

from collections.abc import Callable, Iterable, Sequence

from dplanner.domain.branches import Reading, Stretch
from dplanner.domain.commands import (
    AddNodeCommand,
    Command,
    CompositeCommand,
    EdgeList,
    edge_list,
    remove_steps_command,
    rewire_command,
)
from dplanner.domain.model import Edge, Library, Project, Step, StepId
from dplanner.domain.ordering import dependents_index, left_between

PUT_LABEL = "Put on a Branch"
REMOVE_LABEL = "Remove Branch"


def put_refusal(
    library: Library,
    step_ids: Sequence[StepId],
    reading: Callable[[Project], Reading],
    stacked_apart: Callable[[Project, set[StepId]], str],
) -> str:
    """Why the picked steps cannot be put on a branch, "" when they can: they are one
    project's, nothing left out comes between two of them, the pick holds or avoids every
    stretch already there rather than crossing one, and it splits no stack."""
    if not step_ids:
        return "pick the steps to put on a branch"
    projects = {library.project_of(step_id).id for step_id in step_ids}
    if len(projects) > 1:
        return "pick steps of one project"
    project = library.project_of(step_ids[0])
    chosen = set(step_ids)
    between = left_between(project, chosen)
    if between is not None:
        return f"{between.title!r} comes between them — pick it too, or leave a step out"
    for stretch in reading(project).stretches:
        whole = {step.id for step in stretch.members} | {stretch.cut.id, stretch.land.id}
        inside = chosen <= {step.id for step in stretch.members}
        if not inside and not whole <= chosen and chosen & whole:
            return (
                f"the pick crosses {stretch.branch} — pick all of it with its cut and"
                " landing, or only steps on it"
            )
    return stacked_apart(project, chosen)


def put_command(
    library: Library,
    step_ids: Sequence[StepId],
    cut: Step,
    land: Step,
    *,
    carrying: Sequence[Command] = (),
    label: str = PUT_LABEL,
) -> CompositeCommand:
    """Bracket the picked steps between ``cut`` and ``land``, both born here with whatever
    they carry; ``carrying`` rides with the births (their seats). A caller asks
    :func:`put_refusal` first."""
    project = library.project_of(step_ids[0])
    chosen = set(step_ids)
    known = {step.id for step in project.steps}
    lists: dict[EdgeList, list[StepId]] = {}
    inputs: list[StepId] = []
    for step in project.steps:
        if step.id not in chosen:
            continue
        held = edge_list(lists, library, step.id, "requires")
        inputs += [source for source in held if source in known and source not in chosen]
        # A ghost an outside edit left is carried where it is, never moved or judged.
        kept = [source for source in held if source in chosen or source not in known]
        held[:] = kept if any(source in chosen for source in kept) else [*kept, cut.id]
    lists[(cut.id, "requires")] = list(dict.fromkeys(inputs))
    for step in project.steps:
        held = step.edges.get("requires", [])
        if step.id in chosen or not any(source in chosen for source in held):
            continue
        waiting = edge_list(lists, library, step.id, "requires")
        waiting[:] = list(dict.fromkeys(land.id if s in chosen else s for s in waiting))
    index = dependents_index(project)
    lists[(land.id, "requires")] = [
        step.id
        for step in project.steps
        if step.id in chosen and not any(d.id in chosen for d in index.get(step.id, []))
    ]
    births: list[Command] = [AddNodeCommand(project.id, cut), AddNodeCommand(project.id, land)]
    return rewire_command(library, lists, label, [*births, *carrying])


def stretch_picked(reading: Reading, step_ids: Iterable[StepId]) -> tuple[Stretch | None, str]:
    """The one stretch a pick is about — the one a picked cut or landing brackets, else the
    innermost one a picked step is on — and why there is none."""
    found: list[Stretch] = []
    for step_id in step_ids:
        stretch = reading.of_cut(step_id) or reading.of_land(step_id) or reading.innermost(step_id)
        if stretch is not None and stretch not in found:
            found.append(stretch)
    if not found:
        return None, "no picked step is on a branch"
    if len(found) > 1:
        return None, "the picked steps are on different branches — pick one of them"
    return found[0], ""


def remove_command(library: Library, stretch: Stretch) -> CompositeCommand:
    """Remove the stretch's cut and landing, closing the links over them: what waited on
    the cut waits on what the cut waited on, and what waited on the landing on what the
    landing waited on."""
    ends = {stretch.cut.id, stretch.land.id}
    bridges: list[Edge] = []
    for end in (stretch.cut, stretch.land):
        sources = [source.id for source in library.requires(end.id) if source.id not in ends]
        for waiter in library.dependents(end.id):
            if waiter.id not in ends:
                bridges += [(waiter.id, "requires", source) for source in sources]
    ends_in_order = [stretch.cut.id, stretch.land.id]
    command = remove_steps_command(library, ends_in_order, REMOVE_LABEL, bridges=bridges)
    command.label = REMOVE_LABEL
    return command
