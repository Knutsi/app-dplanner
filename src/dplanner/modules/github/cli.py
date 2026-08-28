"""``dplanner github …`` — record the branch and PR a step's work lands in.

Recording (``set``, ``clear``) is plain strings and always works. The verbs that talk to
GitHub — ``refresh``, ``prs``, ``branches`` — need the ``gh`` CLI and a GitHub repository
URL, and refuse with one line when either is missing.

``commands()`` takes the repository resolution as a typed parameter, supplied by the
composition root — the CLI-side twin of a module ``Deps`` callback: which repository a
step belongs to is the ``project_repo`` module's rule, and a ``cli.py`` never imports
another module, so the answer arrives as an argument.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import replace
from functools import partial

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Product, Project, Step
from dplanner.modules.github.aspect import (
    MODULE_ID,
    GithubRefs,
    pr_label,
    read,
    refreshed,
    write,
)
from dplanner.modules.github.gh import (
    GhError,
    PrInfo,
    gh_refusal,
    list_branches,
    list_prs,
    parse_repo,
    pr_number_from,
    view_pr,
    which_gh,
)

# (product, project) -> the repository URL that project's work belongs to. Required:
# project_repo's resolution is the only authority on it, and the composition root supplies
# it — a default here would be a second copy of that rule.
RepositoryFor = Callable[[Product, Project], str]


def commands(*, repository_for: RepositoryFor) -> list[CliCommand]:
    return [
        CliCommand(
            path=("github", "set"),
            summary="Record the branch and/or PR a step's work lands in.",
            configure=_configure_set,
            run=lambda context, args: _set(context, args, repository_for),
            examples=(
                "dplanner github set 'Read the spec' --branch feat/login",
                "dplanner github set 'Read the spec' --pr 12",
            ),
        ),
        CliCommand(
            path=("github", "clear"),
            summary="Remove a step's branch and/or PR ref.",
            configure=_configure_clear,
            run=_clear,
            examples=("dplanner github clear 'Read the spec' --pr",),
        ),
        CliCommand(
            path=("github", "refresh"),
            summary="Update the stored state of open PRs from GitHub (needs gh).",
            configure=_configure_refresh,
            run=lambda context, args: _refresh(context, args, repository_for),
            examples=("dplanner github refresh",),
        ),
        CliCommand(
            path=("github", "prs"),
            summary="List the repository's pull requests (needs gh; first 100).",
            configure=_configure_prs,
            run=lambda context, args: _prs(context, args, repository_for),
            examples=("dplanner github prs --all",),
        ),
        CliCommand(
            path=("github", "branches"),
            summary="List the repository's branches (needs gh).",
            configure=_configure_branches,
            run=lambda context, args: _branches(context, args, repository_for),
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
    parser.add_argument("step", nargs="?", help="one step; omit for every step in the product")


def _configure_prs(parser: ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="include merged and closed PRs")
    _project_option(parser)


def _configure_branches(parser: ArgumentParser) -> None:
    _project_option(parser)


def _project_option(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--project", default="", help="use this project's repository instead of the product's"
    )


def _set(context: CliContext, args: Namespace, repository_for: RepositoryFor) -> int:
    if not args.branch and not args.pr:
        raise CliError("nothing to set — pass --branch and/or --pr")
    step = find_step(context.product, args.step)
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
        info = _fetch_pr(_step_repo(context, step, repository_for), number)
        if info is not None:
            refs = refreshed(refs, info)

    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(refs)))
    context.report(
        {"step": step.id} | write(refs),
        f"{step.title}: " + ", ".join(filter(None, [refs.branch, _pr_phrase(refs)])),
    )
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    current = read(step)
    if current is None:
        raise CliError(f"{step.title!r} has no GitHub refs")
    both = args.branch == args.pr  # Neither flag or both: clear everything.
    refs = GithubRefs() if both else _cleared_half(current, branch=args.branch)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(refs)))
    context.report({"step": step.id} | write(refs), f"{step.title}: GitHub refs cleared")
    return 0


def _refresh(context: CliContext, args: Namespace, repository_for: RepositoryFor) -> int:
    _need_gh()
    steps = [find_step(context.product, args.step)] if args.step else _all_steps(context)
    checked = updated = 0
    for step in steps:
        refs = read(step)
        if refs is None or refs.pr_number is None or refs.pr_state in ("merged", "closed"):
            continue
        repo = _step_repo(context, step, repository_for)
        if repo is None:
            if args.step:  # Asked about one step, so its missing repo is an answer.
                raise CliError(_NO_REPOSITORY)
            continue
        checked += 1
        info = _gh(partial(view_pr, repo, refs.pr_number))
        if info is None:
            continue
        fresh = refreshed(refs, info)
        if fresh != refs:
            context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(fresh)))
            updated += 1
    context.report(
        {"checked": checked, "updated": updated}, f"{checked} PR(s) checked, {updated} updated"
    )
    return 0


def _prs(context: CliContext, args: Namespace, repository_for: RepositoryFor) -> int:
    repo = _scope_repo(context, args, repository_for)
    prs = _gh(lambda: list_prs(repo))
    if not args.all:
        prs = [pr for pr in prs if pr.state == "open"]
    rows = [
        {"number": pr.number, "state": pr.state, "title": pr.title, "branch": pr.head_ref}
        for pr in prs
    ]
    text = "\n".join(f"#{pr.number}  {pr.state:<7} {pr.title}  ({pr.head_ref})" for pr in prs)
    context.report({"prs": rows}, text or "no pull requests")
    return 0


def _branches(context: CliContext, args: Namespace, repository_for: RepositoryFor) -> int:
    repo = _scope_repo(context, args, repository_for)
    branches = _gh(lambda: list_branches(repo))
    context.report({"branches": branches}, "\n".join(branches) or "no branches")
    return 0


def _gh[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except GhError as error:
        raise CliError(str(error)) from error


_NO_REPOSITORY = (
    "no GitHub repository to ask — set one with "
    "`dplanner product set --repository https://github.com/owner/repo` "
    "or `dplanner repo set <project> --repository …`"
)


def _need_gh() -> None:
    refusal = gh_refusal()
    if refusal is not None:
        raise CliError(refusal)


def _step_repo(context: CliContext, step: Step, repository_for: RepositoryFor) -> str | None:
    """The ``owner/repo`` a step's refs belong to: its project's repository over the
    product's — ``project_repo``'s rule, arriving through ``repository_for``."""
    project = context.product.project_of(step.id)
    return parse_repo(repository_for(context.product, project))


def _scope_repo(context: CliContext, args: Namespace, repository_for: RepositoryFor) -> str:
    """The repo a list verb asks: ``--project``'s over the product's, gh checked first."""
    _need_gh()
    if args.project:
        project = find_project(context.product, args.project)
        repo = parse_repo(repository_for(context.product, project))
    else:
        repo = parse_repo(context.product.repository)
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
    return [step for project in context.product.projects for step in project.steps]


def _cleared_half(current: GithubRefs, *, branch: bool) -> GithubRefs:
    return replace(current, branch="") if branch else GithubRefs(branch=current.branch)


def _pr_phrase(refs: GithubRefs) -> str:
    if not refs.has_pr():
        return ""
    name = pr_label(refs)
    return f"{name} ({refs.pr_state})" if refs.pr_state else name
