"""Which steps' work goes onto a feature branch, and which branch that is — derived from the
links, never stored.

A **stretch** is bracketed by two steps: a **cut**, which names the branch and says where it
starts, and a **landing**, which merges it back as a pull request of its own. The landing
names its cut, and the pairing counts only while the cut is upstream of it — the
auto-progress rule, a stored id read through the graph — because a pairing worked out from
the links alone re-paired two stretches side by side whenever one link moved.

**What is on the branch is everything after the cut, until the landing.** A member is a step
downstream of the cut that is neither the landing nor after it. Read forwards, a step that
builds on work on the branch is on the branch by construction — nothing can leak onto main
unlanded — and one that never reaches the landing is named (:func:`unlanded`) rather than
quietly put back on main. Read the other way — everything the landing waits on — main work
the landing needs would have been swept onto the branch.

**A stretch inside another is a branch off a branch.** One stretch holds another when the
other's cut and landing are both its members; a step's branch is the one of the innermost
*open* stretch holding it, so a cut inside a stretch cuts from that stretch's branch and its
landing opens its pull request into it. Two stretches holding one step with neither inside
the other is an overlap, and nothing may run there until it is resolved.

**Handed functions, never a schema** — the rule ``scope.py`` lives by. Nothing here knows
where a branch name is stored; the composition root writes the readers.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import dependents_index, downstream, upstream


@dataclass(frozen=True)
class Stretch:
    """One branch: its cut and landing, the steps on it in project order, and whether it has
    landed — after which its members' work is on the branch it was cut from."""

    cut: Step
    land: Step
    branch: str
    members: tuple[Step, ...]
    landed: bool

    def holds(self, step_id: StepId) -> bool:
        return any(member.id == step_id for member in self.members)

    def inside(self, other: "Stretch") -> bool:
        """Whether this stretch is a branch off ``other``'s."""
        return other.holds(self.cut.id) and other.holds(self.land.id)


@dataclass(frozen=True)
class Reading:
    """A project's stretches, and the cuts and landings that pair with nothing."""

    stretches: tuple[Stretch, ...]
    stray_cuts: tuple[Step, ...]
    stray_lands: tuple[Step, ...]

    def holding(self, step_id: StepId) -> tuple[Stretch, ...]:
        return tuple(stretch for stretch in self.stretches if stretch.holds(step_id))

    def innermost(self, step_id: StepId, *, open_only: bool = False) -> Stretch | None:
        """The stretch that holds ``step_id`` inside every other holding it, or None when
        none holds it — or when two hold it and neither is inside the other (an overlap)."""
        holders = [s for s in self.holding(step_id) if not (open_only and s.landed)]
        for candidate in holders:
            if all(other is candidate or candidate.inside(other) for other in holders):
                return candidate
        return None

    def overlaps(self, step_id: StepId) -> bool:
        holders = self.holding(step_id)
        return len(holders) > 1 and self.innermost(step_id) is None

    def of_cut(self, step_id: StepId) -> Stretch | None:
        return next((s for s in self.stretches if s.cut.id == step_id), None)

    def of_land(self, step_id: StepId) -> Stretch | None:
        return next((s for s in self.stretches if s.land.id == step_id), None)

    def base_of(self, step_id: StepId, mainline: str) -> str:
        """The branch ``step_id``'s work lands on: the innermost open stretch holding it,
        else the mainline. A landing's pull request, and a cut's start, open against this."""
        stretch = self.innermost(step_id, open_only=True)
        return stretch.branch if stretch is not None else mainline


def read(
    project: Project,
    *,
    branch_of: Callable[[Step], str],
    cut_of: Callable[[Step], StepId | None],
    is_done: Callable[[Step], bool],
) -> Reading:
    """The project's stretches. ``branch_of`` is the branch a cut names ("" for a step that
    is no cut), ``cut_of`` the cut a landing names (None for a step that is no landing),
    ``is_done`` whether a landing has landed.

    A landing pairs with the cut it names while that cut is a cut and upstream of it; a cut
    two landings name pairs with the first in project order, and the other is a stray.
    """
    index = dependents_index(project)
    cuts = {step.id: step for step in project.steps if branch_of(step)}
    found: list[Stretch] = []
    stray_lands: list[Step] = []
    closed: set[StepId] = set()
    for land in project.steps:
        cut_id = cut_of(land)
        if cut_id is None:
            continue
        cut = cuts.get(cut_id)
        after = downstream(project, cut_id, index) if cut is not None else []
        if cut is None or cut_id in closed or all(step.id != land.id for step in after):
            stray_lands.append(land)
            continue
        closed.add(cut_id)
        beyond = {step.id for step in downstream(project, land.id, index)} | {land.id}
        found.append(
            Stretch(
                cut=cut,
                land=land,
                branch=branch_of(cut),
                members=tuple(step for step in after if step.id not in beyond),
                landed=is_done(land),
            )
        )
    stray_cuts = tuple(cut for cut_id, cut in cuts.items() if cut_id not in closed)
    return Reading(tuple(found), stray_cuts, tuple(stray_lands))


def late_entries(library: Library, project: Project, stretch: Stretch) -> list[tuple[Step, Step]]:
    """``(member, source)`` for every link into the middle of ``stretch`` from work that is
    neither on it nor behind its cut — main work the branch was cut before, which a member's
    worktree will not have."""
    before = {step.id for step in upstream(library, project, stretch.cut.id)}
    allowed = before | {step.id for step in stretch.members} | {stretch.cut.id}
    return [
        (member, source)
        for member in stretch.members
        for source in library.requires(member.id)
        if source.id not in allowed
    ]


def unlanded(library: Library, project: Project, stretch: Stretch) -> list[Step]:
    """The members of ``stretch`` with no path to its landing: work on the branch that the
    landing will not wait for, and so may land after it — or never."""
    landed_through = {step.id for step in upstream(library, project, stretch.land.id)}
    return [member for member in stretch.members if member.id not in landed_through]
