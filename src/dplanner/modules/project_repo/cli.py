"""``dplanner repo …`` — which repository and checkout a project works against.

``show`` prints the stored values and the *effective* ones — the same ``checkout_for``
resolution Run Agent is wired through — marking whatever falls back to the product, so an
agent never has to re-derive the rule.
"""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.modules.project_repo.repo import (
    MODULE_ID,
    checkout_for,
    read_checkout,
    read_repository,
    repository_for,
    write_association,
)


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("repo", "set"),
            summary="Point a project at its own repository or checkout.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner repo set discovery --checkout ~/Code/widget",
                "dplanner repo set discovery --repository https://github.com/owner/widget",
            ),
        ),
        CliCommand(
            path=("repo", "show"),
            summary="A project's repository and checkout, effective values included.",
            configure=_one_project,
            run=_show,
            examples=("dplanner repo show discovery --json",),
        ),
        CliCommand(
            path=("repo", "clear"),
            summary="Back to the product's repository and checkout; leaves no file behind.",
            configure=_one_project,
            run=_clear,
            examples=("dplanner repo clear discovery",),
        ),
    ]


def _one_project(parser: ArgumentParser) -> None:
    parser.add_argument("project", help="project id, folder name, or part of its title")


def _configure_set(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("--repository", help="https://github.com/owner/repo")
    parser.add_argument("--checkout", help="where this machine has it cloned")


def _set(context: CliContext, args: Namespace) -> int:
    if args.repository is None and args.checkout is None:
        raise CliError("nothing to set — pass --repository or --checkout")
    project = find_project(context.product, args.project)
    # A flag not passed keeps its stored value; a flag passed empty clears that half.
    repository = read_repository(project) if args.repository is None else args.repository
    checkout = read_checkout(project) if args.checkout is None else args.checkout
    entry = write_association(repository, checkout)
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, entry))
    said = ", ".join(part for part in (repository.strip(), checkout.strip()) if part)
    said = said or "back to the product's"
    context.report({"project": project.id} | entry, f"{project.title}: {said}")
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    product = context.product
    own_repository = read_repository(project)
    own_checkout = read_checkout(project)
    effective_repository = repository_for(product, project)
    effective_checkout = checkout_for(product, project)
    data = {
        "project": project.id,
        "repository": own_repository,
        "checkout": own_checkout,
        "effective_repository": effective_repository,
        "effective_checkout": effective_checkout,
    }
    lines = [
        _line("repository", own_repository, effective_repository),
        _line("checkout", own_checkout, effective_checkout),
    ]
    context.report(data, "\n".join(lines))
    return 0


def _line(label: str, own: str, effective: str) -> str:
    if own:
        return f"{label:<11} {own}"
    if effective:
        return f"{label:<11} {effective} (from the product)"
    return f"{label:<11} —"


def _clear(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, {}))
    context.report({"project": project.id}, f"{project.title}: back to the product's")
    return 0
