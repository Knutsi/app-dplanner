"""``dplanner product …`` — read and write the product's identity.

Qt-free by rule: this file sits beside ``module.py`` but must be importable without a
graphics stack, and ``tests/test_architecture.py`` fails the build if it is not.
"""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import VALUE_FIELDS

FIELDS = VALUE_FIELDS["product"]


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("product", "show"),
            summary="What this product is, and where its code lives.",
            run=_show,
            examples=("dplanner product show", "dplanner product show --json"),
        ),
        CliCommand(
            path=("product", "set"),
            summary="Change the product's name, repository URL or checkout path.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner product set --name 'Widget'",
                "dplanner product set --repository https://github.com/owner/widget",
            ),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    parser.add_argument("--name", help="what people call this product")
    parser.add_argument("--repository", help="the URL of the repository being planned")
    parser.add_argument("--checkout", help="where this machine has that repository cloned")


def _show(context: CliContext, _args: Namespace) -> int:
    product = context.product
    data = {
        "id": product.id,
        "name": product.name,
        "repository": product.repository,
        "checkout": product.checkout,
        "projects": len(product.projects),
        "steps": sum(len(project.steps) for project in product.projects),
    }
    lines = [
        f"{product.name or '(unnamed)'}",
        f"  repository  {product.repository or '—'}",
        f"  checkout    {product.checkout or '—'}",
        f"  projects    {data['projects']} ({data['steps']} steps)",
    ]
    context.report(data, "\n".join(lines))
    return 0


def _set(context: CliContext, args: Namespace) -> int:
    product = context.product
    wanted = {field: getattr(args, field) for field in FIELDS if getattr(args, field) is not None}
    if not wanted:
        raise CliError(f"nothing to set — pass one of {', '.join('--' + f for f in FIELDS)}")
    for field, value in wanted.items():
        context.apply(SetFieldCommand(product.id, field, value))
    context.report(
        {field: getattr(product, field) for field in FIELDS},
        "\n".join(f"{field}: {getattr(product, field)}" for field in sorted(wanted)),
    )
    return 0
