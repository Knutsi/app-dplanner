"""``dplanner cut …``, ``dplanner land …`` and ``dplanner branch …`` — a stretch of the plan
on a feature branch of its own, from the terminal.

``cut set``/``clear`` and ``land set``/``clear`` mark the two ends one at a time, as the
Type toggles do; ``branch put`` brackets picked steps in one go, as *Put on a Branch* does;
``branch remove`` takes the whole bracket away again; ``branch show`` says what is on each
branch. The two verbs that relink read the topology first.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import find_project, find_step, project_of_step, project_of_steps, step_arg
from dplanner.domain.branches import Reading, Stretch, late_entries, unlanded
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import upstream
from dplanner.domain.shelf import turn_off
from dplanner.domain.store import FilesFor
from dplanner.modules.branches.edits import put_command, put_refusal, remove_command, stretch_picked
from dplanner.modules.branches.plan import branch_births, branch_reading
from dplanner.planning.branches import (
    CUT_ID,
    LAND_ID,
    branch_of,
    is_cut,
    is_land,
    name_problem,
    write_cut,
    write_land,
)
from dplanner.planning.status import is_done


def commands(
    *,
    stacked_apart: Callable[[Project, set[StepId]], str],
    key_of: Callable[[Step], str],
) -> list[CliCommand]:
    def run_put(context: CliContext, args: Namespace) -> int:
        return _put(context, args, branch_reading, stacked_apart, key_of)

    def run_remove(context: CliContext, args: Namespace) -> int:
        return _remove(context, args, branch_reading, key_of)

    def run_show(context: CliContext, args: Namespace) -> int:
        return _show(context, args, branch_reading, key_of)

    def run_land(context: CliContext, args: Namespace) -> int:
        return _land_set(context, args, branch_reading, key_of)

    return [
        CliCommand(
            path=("cut", "set"),
            summary="Make a step the cut a feature branch starts from: the steps after it"
            " work on that branch.",
            configure=_configure_cut,
            run=_cut_set,
            examples=("dplanner cut set B22 --branch feature/stacks",),
        ),
        CliCommand(
            path=("cut", "clear"),
            summary="A step is no longer a branch cut; the name is kept on the shelf.",
            configure=step_arg,
            run=_cut_clear,
            examples=("dplanner cut clear B22",),
        ),
        CliCommand(
            path=("land", "set"),
            summary="Make an agent step the landing that merges a cut's branch back as a PR.",
            configure=_configure_land,
            run=run_land,
            examples=("dplanner land set S27", "dplanner land set S27 --cut B22"),
        ),
        CliCommand(
            path=("land", "clear"),
            summary="A step no longer lands a branch.",
            configure=step_arg,
            run=_land_clear,
            examples=("dplanner land clear S27",),
        ),
        CliCommand(
            path=("branch", "put"),
            summary="Put steps on a feature branch: a cut is born before them and a landing"
            " after, and the links from outside move onto the two.",
            configure=_configure_put,
            run=run_put,
            examples=("dplanner branch put S16 S17 S18 F19 --branch feature/stacks",),
            edits_graph=project_of_steps,
        ),
        CliCommand(
            path=("branch", "remove"),
            summary="Take a branch off every step on it: its cut and landing go, and the"
            " links close over them.",
            configure=step_arg,
            run=run_remove,
            examples=("dplanner branch remove S17", "dplanner branch remove B22"),
            edits_graph=project_of_step,
        ),
        CliCommand(
            path=("branch", "show"),
            summary="Each feature branch in a project: its cut, its landing, the steps on it"
            " and whether it has landed.",
            configure=_configure_show,
            run=run_show,
            examples=("dplanner branch show", "dplanner branch show 'Changes 2'"),
        ),
    ]


def _configure_cut(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--branch", required=True, help="the feature branch, e.g. feature/stacks")


def _configure_land(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument(
        "--cut", help="the cut whose branch this lands; the one cut upstream when omitted"
    )


def _configure_put(parser: ArgumentParser) -> None:
    parser.add_argument("steps", nargs="+", help="the steps to put on the branch")
    parser.add_argument("--branch", required=True, help="the feature branch, e.g. feature/stacks")


def _configure_show(parser: ArgumentParser) -> None:
    parser.add_argument("project", nargs="?", help="the project; the current one when omitted")


def _cut_set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if problem := name_problem(args.branch):
        raise CliError(problem)
    context.apply(SetModuleDataCommand(step.id, CUT_ID, write_cut(args.branch)))
    context.report({"step": step.id, "branch": args.branch}, f"{step.title}: cuts {args.branch}")
    return 0


def _cut_clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if not is_cut(step):
        context.report({"step": step.id}, f"{step.title}: not a branch cut")
        return 0
    context.apply(turn_off(step.id, CUT_ID, label="Remove Branch Cut"))
    context.report({"step": step.id}, f"{step.title}: no longer a branch cut")
    return 0


def _land_set(
    context: CliContext,
    args: Namespace,
    read: Callable[[Project], Reading],
    key_of: Callable[[Step], str],
) -> int:
    library = context.library
    step = find_step(library, args.step, context.current)
    project = library.project_of(step.id)
    if args.cut is not None:
        cut = find_step(library, args.cut, context.current)
        if not is_cut(cut):
            raise CliError(f"{cut.title!r} is no branch cut — `dplanner cut set` it first")
    else:
        cut = _open_cut_upstream(library, project, step, read(project), key_of)
    context.apply(SetModuleDataCommand(step.id, LAND_ID, write_land(cut.id)))
    context.report(
        {"step": step.id, "cut": cut.id, "branch": branch_of(cut)},
        f"{step.title}: lands {branch_of(cut)}",
    )
    return 0


def _open_cut_upstream(
    library: Library, project: Project, step: Step, found: Reading, key_of: Callable[[Step], str]
) -> Step:
    """The one cut upstream of ``step`` that no landing closes yet, or a refusal naming the
    choices."""
    open_cuts = {cut.id for cut in found.stray_cuts}
    candidates = [s for s in upstream(library, project, step.id) if s.id in open_cuts]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise CliError(f"no open branch cut is upstream of {step.title!r} — name one with --cut")
    named = ", ".join(key_of(cut) or cut.title for cut in candidates)
    raise CliError(f"several cuts are upstream of {step.title!r} ({named}) — name one with --cut")


def _land_clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if not is_land(step):
        context.report({"step": step.id}, f"{step.title}: lands no branch")
        return 0
    context.apply(turn_off(step.id, LAND_ID, label="Remove Landing"))
    context.report({"step": step.id}, f"{step.title}: lands no branch now")
    return 0


def _put(
    context: CliContext,
    args: Namespace,
    read: Callable[[Project], Reading],
    stacked_apart: Callable[[Project, set[StepId]], str],
    key_of: Callable[[Step], str],
) -> int:
    library = context.library
    steps = [find_step(library, needle, context.current) for needle in args.steps]
    ids = list(dict.fromkeys(step.id for step in steps))
    if refusal := put_refusal(library, ids, read, stacked_apart):
        raise CliError(refusal)
    project = library.project_of(ids[0])
    taken = [s.branch for s in read(project).stretches if not s.landed]
    if problem := name_problem(args.branch, taken):
        raise CliError(problem)
    cut, land = branch_births(project, args.branch)
    context.apply(put_command(library, ids, cut, land))
    context.report(
        {"branch": args.branch, "cut": cut.id, "land": land.id, "steps": ids},
        f"{key_of(cut)} cuts {args.branch} before {len(ids)} step"
        f"{'' if len(ids) == 1 else 's'}; {key_of(land)} lands it",
    )
    return 0


def _remove(
    context: CliContext,
    args: Namespace,
    read: Callable[[Project], Reading],
    key_of: Callable[[Step], str],
) -> int:
    library = context.library
    step = find_step(library, args.step, context.current)
    stretch, why = stretch_picked(read(library.project_of(step.id)), [step.id])
    if stretch is None:
        raise CliError(f"{step.title!r}: {why}")
    count = len(stretch.members)
    context.apply(remove_command(library, stretch))
    context.report(
        {"branch": stretch.branch, "cut": stretch.cut.id, "land": stretch.land.id},
        f"{stretch.branch} is gone: {key_of(stretch.cut)} and {key_of(stretch.land)} removed,"
        f" {count} step{'' if count == 1 else 's'} back where they were",
    )
    return 0


def _show(
    context: CliContext,
    args: Namespace,
    read: Callable[[Project], Reading],
    key_of: Callable[[Step], str],
) -> int:
    project = find_project(context.library, args.project) if args.project else context.project
    found = read(project)
    rows = [_stretch_row(stretch, found, key_of) for stretch in found.stretches]
    lines = [line for _data, line in rows]
    lines += [
        f"{key_of(cut)} cuts {branch_of(cut)} — no landing closes it" for cut in found.stray_cuts
    ]
    context.report(
        {"project": project.id, "branches": [data for data, _line in rows]},
        "\n".join(lines) or "no branches",
    )
    return 0


def _stretch_row(
    stretch: Stretch, found: Reading, key_of: Callable[[Step], str]
) -> tuple[dict[str, object], str]:
    base = found.base_of(stretch.cut.id, "")
    members = " ".join(key_of(step) or step.title for step in stretch.members)
    state = "landed" if stretch.landed else "open"
    data: dict[str, object] = {
        "branch": stretch.branch,
        "cut": stretch.cut.id,
        "land": stretch.land.id,
        "from": base,
        "steps": [step.id for step in stretch.members],
        "landed": stretch.landed,
    }
    line = (
        f"{stretch.branch} ({state}, from {base or 'the default branch'}):"
        f" {key_of(stretch.cut)} → {members or 'nothing'} → {key_of(stretch.land)}"
    )
    return data, line


# -- lint ---------------------------------------------------------------------------------------


def lint_checks(
    *,
    is_agent: Callable[[Step], bool],
    is_milestone: Callable[[Step], bool],
    pr_base_of: Callable[[Step], str],
) -> list[LintCheck]:
    def finding(check: str, step: Step, message: str) -> LintFinding:
        return LintFinding(check=check, subject_id=step.id, subject=step.title, message=message)

    def pairs(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """A cut no landing closes, a landing that closes no cut, and a landing nobody can
        run — the three ways a bracket is half-made."""
        found = branch_reading(project)
        out = [
            finding(
                "branch.unpaired",
                cut,
                f"cuts {branch_of(cut)}, but no landing closes it — nothing merges it back;"
                f" `dplanner land set <step> --cut '{cut.title}'`, or `dplanner cut clear"
                f" '{cut.title}'`",
            )
            for cut in found.stray_cuts
        ]
        out += [
            finding(
                "branch.unpaired",
                land,
                "lands a branch, but its cut is gone or no longer upstream of it —"
                f" `dplanner land set '{land.title}' --cut <cut>`, or `dplanner land clear"
                f" '{land.title}'`",
            )
            for land in found.stray_lands
        ]
        out += [
            finding(
                "branch.land-agent",
                stretch.land,
                f"lands {stretch.branch}, but is no agent step — nobody is briefed to merge it;"
                f" `dplanner agent on '{stretch.land.title}'`",
            )
            for stretch in found.stretches
            if not is_agent(stretch.land)
        ]
        return out

    def names(_library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """A branch name git refuses, or one two open stretches share."""
        found = branch_reading(project)
        out = []
        cuts = [s.cut for s in found.stretches if not s.landed] + list(found.stray_cuts)
        for cut in cuts:
            others = [branch_of(other) for other in cuts if other is not cut]
            if problem := name_problem(branch_of(cut), others):
                out.append(
                    finding(
                        "branch.name",
                        cut,
                        f"{problem} — `dplanner cut set '{cut.title}' --branch <name>`",
                    )
                )
        return out

    def shapes(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """The links that break one way in, one way out, and a stretch two others cross."""
        found = branch_reading(project)
        out = []
        for stretch in found.stretches:
            for member, source in late_entries(library, project, stretch):
                out.append(
                    finding(
                        "branch.late-entry",
                        member,
                        f"is on {stretch.branch} but waits on {source.title!r}, which is not —"
                        " the branch was cut before that work, so this step's worktree will"
                        f" not have it; `dplanner step link '{stretch.cut.title}'"
                        f" '{source.title}'` to cut after it",
                    )
                )
            for member in unlanded(library, project, stretch):
                out.append(
                    finding(
                        "branch.unlanded",
                        member,
                        f"is on {stretch.branch}, but {stretch.land.title!r} does not wait for"
                        " it — its work may never land; link it into the landing, or take it"
                        " off the branch",
                    )
                )
            for member in stretch.members:
                if is_milestone(member):
                    out.append(
                        finding(
                            "branch.crosses-milestone",
                            member,
                            f"is a milestone on {stretch.branch} — a release whose work is not"
                            " on main yet; land the branch before it",
                        )
                    )
        for step in project.steps:
            if found.overlaps(step.id):
                named = " and ".join(s.branch for s in found.holding(step.id))
                out.append(
                    finding(
                        "branch.overlap",
                        step,
                        f"is on {named}, and neither is inside the other — it cannot tell which"
                        " branch its work goes on; `dplanner branch remove` one of them",
                    )
                )
        return out

    def merges(_library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """A pull request aimed at the wrong branch, and a branch landed before its work."""
        found = branch_reading(project)
        out = []
        for stretch in found.stretches:
            open_members = [m for m in stretch.members if not is_done(m)]
            if stretch.landed and open_members:
                out.append(
                    finding(
                        "branch.landed-open",
                        stretch.land,
                        f"landed {stretch.branch} while {open_members[0].title!r} is not done —"
                        " its work, merged later, goes nowhere",
                    )
                )
            if stretch.landed:
                continue
            for member in stretch.members:
                base, expected = pr_base_of(member), found.base_of(member.id, "")
                if base and expected and base != expected and not is_done(member):
                    out.append(
                        finding(
                            "branch.pr-base",
                            member,
                            f"is on {expected}, but its PR merges into {base} —"
                            f" `gh pr edit <number> --base {expected}`",
                        )
                    )
        return out

    return [pairs, names, shapes, merges]
