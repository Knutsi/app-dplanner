"""Turning what a person typed into the node they meant.

An agent has ids; a person has words. Accepting both costs one function and removes the step
where somebody has to look an id up before they can do anything — which, over a
conversation's worth of small commands, is most of the friction.

This lives in ``cli/`` rather than in the projects module because every noun's verbs need
it. A step aspect resolving a step through the projects package would be one module reaching
into another, and ``tests/test_architecture.py`` says so.
"""

from dplanner.cli.command import CliError
from dplanner.domain.model import Product, Project, Step


def find_project(product: Product, needle: str) -> Project:
    """A project by id, folder name, or a unique part of its title."""
    return _find(product.projects, needle, "project")


def find_step(product: Product, needle: str) -> Step:
    """A step by id, folder name, or a unique part of its title, anywhere in the product."""
    steps = [step for project in product.projects for step in project.steps]
    return _find(steps, needle, "step")


def _find[NodeT: (Project, Step)](candidates: list[NodeT], needle: str, kind: str) -> NodeT:
    """Exact identity first, then a unique partial title.

    An ambiguous name is refused rather than resolved to the first match: silently acting on
    one of two things a person might have meant is the failure they cannot see.
    """
    exact = [node for node in candidates if needle in (node.id, node.folder_name)]
    if exact:
        return exact[0]
    lowered = needle.lower()
    partial = [node for node in candidates if lowered in node.title.lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise CliError(f"no {kind} matching {needle!r}")
    # The ids are the point of this message: it has to say what to type next, not just
    # that the guess failed.
    names = ", ".join(sorted(f"{node.title} ({node.id[:8]})" for node in partial))
    raise CliError(f"{needle!r} matches several {kind}s — use an id: {names}")
