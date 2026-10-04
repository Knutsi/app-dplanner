"""The two aspects that bracket a branch stretch: the cut, and the landing.

A **cut** is a step that names a feature branch — ``{"branch": "feature/stacks"}`` — and is
where it starts: the steps after it work on that branch, and their pull requests merge into
it. It is no work: nobody works it, it has no status of its own, and it reads done once what
it waits on is done, as a wait does with nothing to hold. A **landing** is an agent step
that names its cut — ``{"cut": "<id>"}`` — and merges the branch back as a pull request of
its own. The pairing is stored, and it counts only while the cut is upstream of the landing:
``domain/branches.py`` reads it through the graph, and what is on the branch is derived
there from the links, never listed here.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.core.storage.sparse import valid_ref
from dplanner.domain import branches
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Project, Step, StepId

CUT_ID = "branch_cut"
LAND_ID = "branch_land"
CUT_FORMAT = ModuleDataFormat(CUT_ID)
LAND_FORMAT = ModuleDataFormat(LAND_ID)
BRANCH_KEY = "branch"
CUT_KEY = "cut"

# What a cut is called wherever a refusal names the kind of step nobody works.
A_CUT = "a branch cut"


def branch_of(step: Step) -> str:
    """The branch a cut names, "" for a step that is no cut."""
    named = (step.module_data.get(CUT_ID) or {}).get(BRANCH_KEY)
    return named if isinstance(named, str) else ""


def is_cut(step: Step) -> bool:
    return bool(branch_of(step))


def write_cut(branch: str) -> dict[str, Any]:
    """The cut's entry — ``{}`` for none, which removes the file."""
    return stamped({BRANCH_KEY: branch}, CUT_FORMAT.version) if branch else {}


def cut_of(step: Step) -> StepId | None:
    """The cut a landing names, whether or not it is still upstream of it; None for a step
    that is no landing."""
    named = (step.module_data.get(LAND_ID) or {}).get(CUT_KEY)
    return named if isinstance(named, str) and named else None


def is_land(step: Step) -> bool:
    return cut_of(step) is not None


def write_land(cut: StepId | None) -> dict[str, Any]:
    """The landing's entry — ``{}`` for none, which removes the file."""
    return stamped({CUT_KEY: cut}, LAND_FORMAT.version) if cut else {}


def name_problem(branch: str, taken: Sequence[str] = ()) -> str | None:
    """Why ``branch`` cannot name a stretch, None when it can: a name git accepts and a
    script can carry, and not a branch another open stretch already names."""
    if not branch:
        return "name the branch"
    if not valid_ref(branch):
        return f"{branch!r} is not a branch name git accepts"
    if branch in taken:
        return f"another branch in this project is already called {branch}"
    return None


# A run's own branch is `agent/<run name>`; a landing's is the feature branch it lands.
BRANCH_PREFIX = "agent/"


def branch_name(name: str) -> str:
    return f"{BRANCH_PREFIX}{name}"


@dataclass(frozen=True)
class BranchPlan:
    """Which git branches a run of a step works between — decided by the plan, carried out
    by the wrapper script and told to the agent, so the two cannot disagree.

    ``work_branch`` is the branch its worktree is on, "" for the step's own
    ``agent/<run name>``; a landing names the feature branch it lands. ``start`` is where a
    new branch starts — ``origin/<branch>`` — and "" is the remote's default branch, looked
    up by the script. ``create`` is the branch this run may create on the remote from
    ``create_from`` when it is not there yet: the first run in a stretch cuts it, and no
    later one ever cuts it again. ``pr_base`` is the branch the step's PR opens against, ""
    for the repository's default. ``refusal`` is why no agent may run on the step now, ""
    when one may. Every field names a branch the plan wrote, so each is checked with
    :func:`dplanner.core.storage.sparse.valid_ref` before it reaches a script.
    """

    work_branch: str = ""
    start: str = ""
    create: str = ""
    create_from: str = ""
    pr_base: str = ""
    refusal: str = ""

    def branch_for(self, run: str) -> str:
        """The branch a worktree named ``run`` is on."""
        return self.work_branch or branch_name(run)


# A run nothing narrows: its own branch, started from the remote's default, its PR opened
# against the same — and every run that has no worktree, which reads none of it.
DEFAULT_BRANCHES = BranchPlan()
# The remote's default branch, as a start a plan can name when its mainline names none.
DEFAULT_START = "origin/HEAD"


def reading(project: Project, is_done: Callable[[Step], bool]) -> branches.Reading:
    """The project's stretches, read through this module's two aspects."""
    return branches.read(project, branch_of=branch_of, cut_of=cut_of, is_done=is_done)


def remap_for_paste(
    _project: Project, steps: Sequence[Step], remapped: Mapping[StepId, StepId]
) -> None:
    """A copied landing lands the copy of its cut — the paste policy. A landing copied
    without its cut names nothing, and its entry goes."""
    for step in steps:
        cut = cut_of(step)
        if cut is None:
            continue
        entry = write_land(remapped.get(cut))
        if entry:
            step.module_data[LAND_ID] = entry
        else:
            step.module_data.pop(LAND_ID, None)


def cut_summary(step: Step) -> str:
    branch = branch_of(step)
    return f"cuts {branch}" if branch else ""


def land_summary(step: Step) -> str:
    return "lands a branch" if is_land(step) else ""


CUT_SPEC = AspectSpec(
    id=CUT_ID,
    label="Branch cut",
    summary="Where a feature branch starts: the steps after it work on the branch it names,"
    " and their PRs merge into it; no work, no worker.",
    data_format=CUT_FORMAT,
    phrase=cut_summary,
)

LAND_SPEC = AspectSpec(
    id=LAND_ID,
    label="Landing",
    summary="An agent step that merges the branch a cut started back as a PR of its own —"
    " the review after it is the branch's review.",
    data_format=LAND_FORMAT,
    phrase=land_summary,
)
