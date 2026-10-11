"""``dplanner github …`` — record the branch and PR a step's work lands in.

Recording (``set``, ``clear``) is plain strings and always works. The verbs that talk to
GitHub — ``refresh``, ``prs``, ``branches`` — need the ``gh`` CLI and a GitHub repository
URL, and refuse with one line when either is missing. ``show`` prints a step's refs as
recorded and, with ``gh``, where they stand now: the PR's state and title, and whether
the branch is still on the remote — the GitHub tab's standing line, for the terminal.

Which repository a step belongs to is **the code repository its project records** — the
one fact a plan stores about the code it plans — and, for a project that records none
(the older shape, a plan kept beside its code), its own directory's ``origin`` remote.

A verb that learns a PR is merged — ``refresh``, ``show`` — finishes a step waiting on
that merge, through the status writer the composition root hands ``commands()``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import replace
from functools import partial

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Project, Step
from dplanner.domain.repositories import repository_facts
from dplanner.domain.shelf import turn_off
from dplanner.modules.github.aspect import (
    MODULE_ID,
    PR_CLOSED,
    PR_MERGED,
    PR_OPEN,
    GithubRefs,
    branch_url,
    pr_label,
    pr_url,
    read,
    refreshed,
    write,
)
from dplanner.modules.github.gh import (
    GhError,
    PrInfo,
    default_branch,
    gh_refusal,
    list_branches,
    list_prs,
    merge_pr,
    parse_repo,
    pr_number_from,
    view_pr,
    which_gh,
)
from dplanner.planning.status import Status, Unknown, stored

FinishMerged = Callable[[CliContext, Step], bool]


def commands(*, finish_merged: FinishMerged) -> list[CliCommand]:
    """``finish_merged`` sets a step waiting on its merge done and answers whether it did —
    the status verb's writer, handed over by the composition root."""

    def run_show(context: CliContext, args: Namespace) -> int:
        return _show(context, args, finish_merged)

    def run_refresh(context: CliContext, args: Namespace) -> int:
        return _refresh(context, args, finish_merged)

    return [
        CliCommand(
            path=("github", "set"),
            summary="Record the branch and/or PR a step's work lands in.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner github set 'Read the spec' --branch feat/login",
                "dplanner github set 'Read the spec' --pr 12",
            ),
        ),
        CliCommand(
            path=("github", "clear"),
            summary="Remove a step's branch and/or PR ref; both at once turns the aspect off.",
            configure=_configure_clear,
            run=_clear,
            examples=("dplanner github clear 'Read the spec' --pr",),
        ),
        CliCommand(
            path=("github", "show"),
            summary="A step's branch and PR as recorded and, with gh, where they stand now: "
            "the PR's state and whether the branch is still on the remote.",
            configure=step_arg,
            run=run_show,
            examples=("dplanner github show S7",),
        ),
        CliCommand(
            path=("github", "refresh"),
            summary="Update the stored state of open PRs from GitHub (needs gh); a step ready "
            "to merge whose PR merged is done.",
            configure=_configure_refresh,
            run=run_refresh,
            examples=("dplanner github refresh",),
        ),
        CliCommand(
            path=("github", "prs"),
            summary="List the repository's pull requests (needs gh; first 100).",
            configure=_configure_prs,
            run=_prs,
            examples=("dplanner github prs --all",),
        ),
        CliCommand(
            path=("github", "branches"),
            summary="List the repository's branches (needs gh).",
            configure=_configure_branches,
            run=_branches,
            examples=("dplanner github branches",),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--branch", default="", help="the branch the work lives on")
    parser.add_argument("--pr", default="", help="PR number (12, #12) or its URL")


def _configure_clear(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--branch", action="store_true", help="clear only the branch")
    parser.add_argument("--pr", action="store_true", help="clear only the PR")


def _configure_refresh(parser: ArgumentParser) -> None:
    parser.add_argument("step", nargs="?", help="one step; omit for every step in the library")


def _configure_prs(parser: ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="include merged and closed PRs")


def _configure_branches(parser: ArgumentParser) -> None:
    return None


def _set(context: CliContext, args: Namespace) -> int:
    if not args.branch and not args.pr:
        raise CliError("nothing to set — pass --branch and/or --pr")
    step = find_step(context.library, args.step, context.current)
    current = read(step) or GithubRefs()

    refs = replace(current, branch=args.branch or current.branch)
    if args.pr:
        number = pr_number_from(args.pr)
        if number is None:
            raise CliError(f"{args.pr!r} names no PR — pass a number, #number, or its URL")
        refs = GithubRefs(
            branch=refs.branch,
            pr_number=number,
            pr_url=args.pr if "/pull/" in args.pr else "",
        )
        # Best effort; recording never fails on gh.
        info = _fetch_pr(_step_repo(context, step), number)
        if info is not None:
            refs = refreshed(refs, info)

    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(refs)))
    context.report(
        {"step": step.id} | write(refs),
        f"{step.title}: " + ", ".join(filter(None, [refs.branch, _pr_phrase(refs)])),
    )
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    current = read(step)
    if current is None:
        # Already clear is success — state-clearing verbs must survive batches.
        context.report({"step": step.id}, f"{step.title}: no GitHub refs")
        return 0
    both = args.branch == args.pr  # Neither flag or both: turn the aspect off, kept.
    if both:
        context.apply(turn_off(step.id, MODULE_ID, label="Remove GitHub"))
        context.report({"step": step.id}, f"{step.title}: GitHub refs cleared")
        return 0
    refs = _cleared_half(current, branch=args.branch)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(refs)))
    context.report({"step": step.id} | write(refs), f"{step.title}: GitHub refs cleared")
    return 0


def _show(context: CliContext, args: Namespace, finish_merged: FinishMerged) -> int:
    step = find_step(context.library, args.step, context.current)
    refs = read(step)
    if refs is None:
        context.report({"step": step.id}, f"{step.title}: no GitHub refs")
        return 0
    repo = _step_repo(context, step)
    data: dict[str, object] = {"step": step.id} | write(refs)
    data["pr_link"] = pr_url(refs, repo)
    data["branch_link"] = branch_url(refs, repo)
    lines = [f"{step.title}: " + ", ".join(filter(None, [refs.branch, _pr_phrase(refs)]))]
    checked = repo is not None and which_gh() is not None
    data["checked"] = checked
    if checked:
        assert repo is not None
        if refs.pr_number is not None:
            info = _fetch_pr(repo, refs.pr_number)
            if info is not None:
                fresh = refreshed(refs, info)
                if fresh != refs:
                    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(fresh)))
                    refs = fresh
                data["pr_state"] = info.state
                data["pr_title"] = info.title
                lines.append(
                    f"{pr_label(refs)} is {info.state}" + (f" · {info.title}" if info.title else "")
                )
        if refs.branch:
            try:
                on_remote = refs.branch in list_branches(repo)
            except GhError:
                on_remote = None
            data["branch_on_remote"] = on_remote
            if on_remote is not None:
                lines.append(
                    f"{refs.branch} is on the remote"
                    if on_remote
                    else f"{refs.branch} is not on the remote — deleted after the merge?"
                )
    else:
        data["branch_on_remote"] = None
        lines.append("(stored state only — gh or a GitHub remote is missing)")
    data["finished"] = refs.pr_state == PR_MERGED and finish_merged(context, step)
    if data["finished"]:
        lines.append(f"{step.title} was waiting on this merge: it is done")
    for link in (data["pr_link"], data["branch_link"]):
        if link:
            lines.append(str(link))
    context.report(data, "\n".join(lines))
    return 0


def _refresh(context: CliContext, args: Namespace, finish_merged: FinishMerged) -> int:
    _need_gh()
    steps = (
        [find_step(context.library, args.step, context.current)]
        if args.step
        else _all_steps(context)
    )
    checked = updated = finished = 0
    for step in steps:
        refs = read(step)
        if refs is not None and refs.pr_state == PR_MERGED:
            # Terminal, so never fetched again — but a step can reach ready-to-merge after
            # its PR did, and it is finished here.
            finished += finish_merged(context, step)
            continue
        if refs is None or refs.pr_number is None or refs.pr_state == PR_CLOSED:
            continue
        repo = _step_repo(context, step)
        if repo is None:
            if args.step:  # Asked about one step, so its missing repo is an answer.
                raise CliError(_NO_REPOSITORY)
            continue
        checked += 1
        info = _gh(partial(view_pr, repo, refs.pr_number))
        if info is None:
            continue
        fresh = _recorded(context, step, refs, info)
        updated += fresh != refs
        if fresh.pr_state == PR_MERGED:
            finished += finish_merged(context, context.library.step(step.id))
    context.report(
        {"checked": checked, "updated": updated, "finished": finished},
        f"{checked} PR(s) checked, {updated} updated"
        + (f", {finished} step(s) merged and done" if finished else ""),
    )
    return 0


def accept_by_merge(
    context: CliContext,
    step: Step,
    *,
    base: str,
    head: str,
    finish_merged: FinishMerged,
) -> tuple[str, bool]:
    """A playbook's ``progress``: merge the step's PR into its feature branch, record it, and
    accept the step by the merge. ``("", False)`` when it was accepted; else why not, and
    whether that is because the work goes to the mainline — which a person merges — rather
    than something to put right.

    ``base`` and ``head`` are where the plan, as it stands now, says the PR goes and comes from
    — the step's feature branch, "" when its work goes to the mainline, and the step's own
    branch, "" when it has none. Everything that makes the merge right is checked **before**
    it, because a merge cannot be taken back: a feature branch that is not the repository's
    default, a PR from exactly ``head`` into exactly ``base``, and a step waiting on review or
    its merge."""
    if not base:
        return "the step's work goes to the mainline, which a person merges", True
    if (status := stored(step)) not in (Status.READY_FOR_REVIEW, Status.READY_TO_MERGE):
        said = status.word if isinstance(status, Unknown) else status.value
        return f"the step is {said}, not waiting on review or its merge", False
    refs = read(step)
    if refs is None or refs.pr_number is None:
        return "the step has no pull request recorded", False
    number = refs.pr_number
    repo = _step_repo(context, step)
    if repo is None:
        return _NO_REPOSITORY, False
    try:
        info = view_pr(repo, number)
        if info is None:
            return f"{repo} has no PR #{number}", False
        if info.state == PR_OPEN:
            if base == default_branch(repo):
                return f"{base} is {repo}'s default branch, which a person merges", True
            if info.base_ref != base or (head and info.head_ref != head):
                return (
                    f"PR #{number} goes from {info.head_ref} into {info.base_ref}; the plan"
                    f" expects {head or 'the step' + chr(39) + 's branch'} into {base}",
                    False,
                )
            merge_pr(repo, number)
            info = view_pr(repo, number) or info
    except GhError as error:
        return f"gh: {error}", False
    if _recorded(context, step, refs, info).pr_state != PR_MERGED:
        return f"PR #{number} is {info.state}, not merged", False
    if not finish_merged(context, context.library.step(step.id)):
        return f"PR #{number} merged into {info.base_ref}, but that did not accept the step", False
    return "", False


def _recorded(context: CliContext, step: Step, refs: GithubRefs, info: PrInfo) -> GithubRefs:
    """The step's refs as gh now reports its PR, written when they changed."""
    fresh = refreshed(refs, info)
    if fresh != refs:
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(fresh)))
    return fresh


def _prs(context: CliContext, args: Namespace) -> int:
    repo = _scope_repo(context)
    prs = _gh(lambda: list_prs(repo))
    if not args.all:
        prs = [pr for pr in prs if pr.state == PR_OPEN]
    rows = [
        {"number": pr.number, "state": pr.state, "title": pr.title, "branch": pr.head_ref}
        for pr in prs
    ]
    text = "\n".join(f"#{pr.number}  {pr.state:<7} {pr.title}  ({pr.head_ref})" for pr in prs)
    context.report({"prs": rows}, text or "no pull requests")
    return 0


def _branches(context: CliContext, _args: Namespace) -> int:
    repo = _scope_repo(context)
    branches = _gh(lambda: list_branches(repo))
    context.report({"branches": branches}, "\n".join(branches) or "no branches")
    return 0


def _gh[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except GhError as error:
        raise CliError(str(error)) from error


_NO_REPOSITORY = (
    "the project names no GitHub code repository — `dplanner location add <project> "
    "--role code --repository https://github.com/owner/repo`"
)


def _need_gh() -> None:
    refusal = gh_refusal()
    if refusal is not None:
        raise CliError(refusal)


def _repo_url(context: CliContext, project: Project) -> str:
    """The remote URL a project's work belongs to: the code repository it records, else —
    the older shape — its own directory's origin, from git; none while its code is not
    set. The same reading the GitHub tab's ``repository_for`` makes."""
    return repository_facts(project, context.store.project_dir(project.id), {}).code_remote


def _step_repo(context: CliContext, step: Step) -> str | None:
    """The ``owner/repo`` a step's refs belong to: its project directory's repository."""
    project = context.library.project_of(step.id)
    return parse_repo(_repo_url(context, project))


def _scope_repo(context: CliContext) -> str:
    """The repo a list verb asks: the current project's, gh checked first."""
    _need_gh()
    repo = parse_repo(_repo_url(context, context.project))
    if repo is None:
        raise CliError(_NO_REPOSITORY)
    return repo


def _fetch_pr(repo: str | None, number: int) -> PrInfo | None:
    if repo is None or which_gh() is None:
        return None
    try:
        return view_pr(repo, number)
    except GhError:
        return None


def _all_steps(context: CliContext) -> list[Step]:
    return [step for project in context.library.projects for step in project.steps]


def _cleared_half(current: GithubRefs, *, branch: bool) -> GithubRefs:
    return replace(current, branch="") if branch else GithubRefs(branch=current.branch)


def _pr_phrase(refs: GithubRefs) -> str:
    if not refs.has_pr():
        return ""
    name = pr_label(refs)
    return f"{name} ({refs.pr_state})" if refs.pr_state else name
