"""What a branch stretch means for the steps it holds: which branches a run works between,
whether a merge accepted a step, and how a new stretch's two ends are born.

Headless: Run Agent's briefing, the GitHub refresh and the CLI's verbs all ask here, the
window and ``dplanner`` alike, so a stretch decides the same thing whichever surface asks.
"""

from collections.abc import Callable

from dplanner.domain.branches import Reading
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
from dplanner.modules.estimation.aspect import write as estimate_write
from dplanner.modules.github.aspect import read as github_read
from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
from dplanner.modules.step_description.aspect import write_state as description_state
from dplanner.planning.agent import MODULE_ID as AGENT_ID
from dplanner.planning.agent import write_state as agent_state
from dplanner.planning.branches import (
    CUT_ID,
    DEFAULT_START,
    LAND_ID,
    BranchPlan,
    reading,
    write_cut,
    write_land,
)
from dplanner.planning.status import Status, stored


def is_done(step: Step) -> bool:
    """Whether a step's own status says done — for a landing, that its branch landed."""
    return stored(step) is Status.DONE


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
    found = (read or branch_reading)(library.project_of(step.id))
    if found.overlaps(step.id):
        named = " and ".join(stretch.branch for stretch in found.holding(step.id))
        return BranchPlan(refusal=f"it is on {named}, and neither is inside the other")
    landing = found.of_land(step.id)
    stretch = landing or found.innermost(step.id, open_only=True)
    if stretch is None:
        return BranchPlan(start=f"origin/{base}" if base else "", pr_base=base)
    cut_from = found.base_of(stretch.cut.id, base)
    fresh = not stretch.landed and not any(
        _recorded_work(member) for member in (*stretch.members, stretch.land)
    )
    return BranchPlan(
        work_branch=stretch.branch if landing is not None else "",
        start=f"origin/{stretch.branch}",
        create=stretch.branch if fresh else "",
        create_from=(f"origin/{cut_from}" if cut_from else DEFAULT_START) if fresh else "",
        pr_base=found.base_of(step.id, base) if landing is not None else stretch.branch,
    )


def _recorded_work(step: Step) -> bool:
    """Whether a step has recorded a branch or a PR — that its work was carried out."""
    return github_read(step) is not None


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
    return stretch is not None and stretch.branch == refs.pr_base


def branch_births(project: Project, branch: str) -> tuple[Step, Step]:
    """The two ends of a new stretch, dressed as the templates dress them: the cut named for
    its branch with no estimate and no description, since nobody works it; the landing an
    agent step of a quarter day, briefed by the stretch it closes rather than by a
    description of its own."""
    cut = Step(title=branch)
    cut.module_data[CUT_ID] = write_cut(branch)
    cut.module_data[ESTIMATION_ID] = estimate_write(None, on=False)
    cut.module_data[DESCRIPTION_ID] = description_state(False)
    land = Step(title=f"Land {branch}")
    land.module_data[LAND_ID] = write_land(cut.id)
    land.module_data[AGENT_ID] = agent_state(True)
    land.module_data[ESTIMATION_ID] = estimate_write(0.25)
    land.module_data[DESCRIPTION_ID] = description_state(False)
    return cut, land
