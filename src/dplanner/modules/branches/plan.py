"""What a branch stretch means for the steps it holds: which branches a run works between,
whether a merge accepted a step, how a new stretch's two ends are born, and the strip and
lane its work wears on a card and an arrow.

Headless: Run Agent's briefing, the GitHub refresh and the CLI's verbs all ask here, the
window and ``dplanner`` alike, so a stretch decides the same thing whichever surface asks.
"""

from collections.abc import Callable, Iterable

from dplanner.domain.branches import Reading, Stretch
from dplanner.domain.model import Edge, Library, Project, Step
from dplanner.modules.github.aspect import read as github_read
from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
from dplanner.modules.step_description.aspect import write_state as description_state
from dplanner.planning.agent import MODULE_ID as AGENT_ID
from dplanner.planning.agent import code_location, code_row, repository_key
from dplanner.planning.agent import enabled as agent_enabled
from dplanner.planning.agent import write_state as agent_state
from dplanner.planning.branches import (
    CUT_ID,
    DEFAULT_START,
    LAND_ID,
    BranchPlan,
    branch_of,
    reading,
    write_cut,
    write_land,
)
from dplanner.planning.estimate import MODULE_ID as ESTIMATION_ID
from dplanner.planning.estimate import write as estimate_write
from dplanner.planning.status import is_done
from dplanner.theme.palettes import lane


def branch_reading(project: Project) -> Reading:
    """The project's branch stretches, read afresh — the CLI's; the window reads the
    branches module's cached one."""
    return reading(project, is_done)


def branch_plan(
    library: Library,
    step: Step,
    base: str,
    read: Callable[[Project], Reading] | None = None,
) -> BranchPlan:
    """Which branches a run of ``step`` works between, from the stretches that hold it.

    A step on a branch starts its own from that branch and opens its PR against it; a
    landing works on the branch itself and opens its PR against the branch its stretch was
    cut from; anything else starts from ``base`` — the mainline its code location names, ""
    for the remote's default — and opens against the same. The first run in a stretch may
    cut its branch on the remote: while nothing on it has recorded a branch or a PR, a
    missing branch is one nobody made yet, and after that it is one somebody deleted.
    """
    project = library.project_of(step.id)
    found = (read or branch_reading)(project)
    if found.overlaps(step.id):
        named = " and ".join(stretch.branch for stretch in found.holding(step.id))
        return BranchPlan(refusal=f"it is on {named}, and neither is inside the other")
    landing = found.of_land(step.id)
    stretch = landing or found.innermost(step.id, open_only=True)
    if stretch is None:
        return BranchPlan(start=f"origin/{base}" if base else "", pr_base=base)
    if refusal := _elsewhere(project, step, stretch):
        return BranchPlan(refusal=refusal)
    return BranchPlan(
        work_branch=stretch.branch if landing is not None else "",
        start=f"origin/{stretch.branch}",
        cuts=_cuts(found, stretch, base),
        pr_base=found.base_of(step.id, base) if landing is not None else stretch.branch,
    )


def _cuts(found: Reading, stretch: Stretch, base: str) -> tuple[tuple[str, str], ...]:
    """The branches a run on ``stretch`` may cut on the remote, outside-in, each with where
    it starts: every open stretch around it that is still fresh, then its own — a branch
    off a branch nobody cut yet starts from nothing, so the outer one is cut first."""
    around = [held for held in found.holding(stretch.cut.id) if not held.landed]
    chain = [*sorted(around, key=lambda held: len(found.holding(held.cut.id))), stretch]
    return tuple(
        (
            held.branch,
            f"origin/{start}" if (start := found.base_of(held.cut.id, base)) else DEFAULT_START,
        )
        for held in chain
        if _fresh(held)
    )


def _fresh(stretch: Stretch) -> bool:
    """Whether nothing on an open stretch has recorded a branch or a PR: a missing branch is
    then one nobody made yet, and after that it is one somebody deleted."""
    return not stretch.landed and not any(
        github_read(member) is not None for member in (*stretch.members, stretch.land)
    )


def _elsewhere(project: Project, step: Step, stretch: Stretch) -> str:
    """Why an agent step on a stretch may not run there, "" when it may: it works in another
    repository than the branch — a branch lives in one, its landing's — so its run would
    find no such branch, or cut a second one of the name in the wrong place."""
    if step.id == stretch.land.id or not agent_enabled(step):
        return ""
    if repository_key(project.locations, step) == stretch_repository(project, stretch):
        return ""
    works = code_location(project.locations, step)
    lands = code_location(project.locations, stretch.land)
    assert works is not None and lands is not None  # Two keys differ, so both rows exist.
    return (
        f"it works in {works.repository_label}, but {stretch.branch} lands in"
        f" {lands.repository_label} — `dplanner agent workplace` puts it, or the landing,"
        " where the other is"
    )


def stretch_repository(project: Project, stretch: Stretch) -> str:
    """The repository a stretch's branch lives in, as :func:`repository_key` compares them:
    its landing's — the agent step that merges the branch back works where the branch is."""
    return repository_key(project.locations, stretch.land)


def landing_workplace(project: Project, steps: Iterable[Step]) -> str:
    """The workplace a landing over ``steps`` takes: the code row their agent steps work in,
    "" for the primary or for a pick with none. :func:`edits.put_refusal` has seen to it that
    they work in one repository."""
    primary = code_row(project.locations, "")
    row = next(
        (code_location(project.locations, step) for step in steps if agent_enabled(step)), None
    )
    return row.id if row is not None and row != primary else ""


def taken_names(found: Reading, project: Project, workplace: str) -> list[str]:
    """The names a new stretch whose landing works in ``workplace`` may not take: every open
    stretch's in the same repository — a branch lives in one repository, so two may share a
    name across two — and every stray cut's, whose repository no landing says yet."""
    row = code_row(project.locations, workplace)
    repository = row.canonical if row is not None else ""
    return [
        stretch.branch
        for stretch in found.stretches
        if not stretch.landed and stretch_repository(project, stretch) == repository
    ] + [branch_of(cut) for cut in found.stray_cuts]


def merged_into_its_branch(
    library: Library,
    step: Step,
    read: Callable[[Project], Reading] | None = None,
) -> bool:
    """Whether a step's PR merged into the branch of an open stretch holding it — the merge
    that accepts it, the branch's own review coming when the branch lands."""
    refs = github_read(step)
    if refs is None or not refs.pr_base:
        return False
    project = library.project_of(step.id)
    stretch = (read or branch_reading)(project).innermost(step.id, open_only=True)
    return (
        stretch is not None
        and stretch.branch == refs.pr_base
        # The same name may be a branch of another repository: that merge accepts nothing.
        and repository_key(project.locations, step) == stretch_repository(project, stretch)
    )


def branch_births(project: Project, branch: str, workplace: str = "") -> tuple[Step, Step]:
    """The two ends of a new stretch, dressed as the templates dress them: the cut named for
    its branch with no estimate and no description, since nobody works it; the landing an
    agent step of a quarter day, briefed by the stretch it closes rather than by a
    description of its own, working in ``workplace`` — the repository the branch lives in."""
    cut = Step(title=branch)
    cut.module_data[CUT_ID] = write_cut(branch)
    cut.module_data[ESTIMATION_ID] = estimate_write(None, on=False)
    cut.module_data[DESCRIPTION_ID] = description_state(False)
    land = Step(title=f"Land {branch}")
    land.module_data[LAND_ID] = write_land(cut.id)
    land.module_data[AGENT_ID] = agent_state(True, workplace=workplace)
    land.module_data[ESTIMATION_ID] = estimate_write(0.25)
    land.module_data[DESCRIPTION_ID] = description_state(False)
    return cut, land


def branches_in(project: Project) -> dict[str, str]:
    """The feature branch each step's work is on, for the steps a stretch not yet landed
    holds — and each landing, whose work is on the branch it brings back."""
    found = branch_reading(project)
    on: dict[str, str] = {}
    for step in project.steps:
        stretch = found.of_land(step.id) or found.innermost(step.id, open_only=True)
        if stretch is not None and not stretch.landed:
            on[step.id] = stretch.branch
    return on


def strips(found: Reading) -> dict[str, tuple[str, str]]:
    """What each card on a branch wears under its body: the branch's name, and its lane
    colour while the branch is open — "" once it has landed, when the strip goes quiet and
    keeps the name. Every step on a stretch and its landing wear one; a step on a branch off
    a branch wears the inner one's."""
    colors = _lane_colors(found)
    worn: dict[str, tuple[str, str]] = {}
    for stretch in sorted(found.stretches, key=lambda stretch: -len(stretch.members)):
        tone = "" if stretch.landed else colors[stretch.cut.id]
        for step in (*stretch.members, stretch.land):
            worn[step.id] = (stretch.branch, tone)
    return worn


def _lane_colors(found: Reading) -> dict[str, str]:
    """Each stretch's lane colour by its cut's id, dealt in the order the cuts were made, so
    a branch keeps its colour while others come and go after it."""
    cuts = sorted((stretch.cut for stretch in found.stretches), key=lambda cut: cut.number)
    return {cut.id: lane(index) for index, cut in enumerate(cuts)}


def lanes(library: Library, found: Reading) -> dict[Edge, str]:
    """The arrows of work on a branch not yet landed, each with its branch's lane colour:
    from the cut or a step on it, into a step on it or its landing. An arrow on a branch
    off a branch wears the inner one's."""
    colors = _lane_colors(found)
    drawn: dict[Edge, str] = {}
    widest_first = sorted(found.stretches, key=lambda stretch: -len(stretch.members))
    for stretch in widest_first:
        if stretch.landed:
            continue
        on = {member.id for member in stretch.members}
        for waiter in (*stretch.members, stretch.land):
            for source in library.requires(waiter.id):
                if source.id in on or source.id == stretch.cut.id:
                    drawn[(waiter.id, "requires", source.id)] = colors[stretch.cut.id]
    return drawn
