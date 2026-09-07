"""Turning what a person typed into the node they meant.

An agent has ids; a person has words. Accepting both costs one function and removes the step
where somebody has to look an id up before they can do anything — which, over a
conversation's worth of small commands, is most of the friction.

This lives in ``cli/`` rather than in the projects module because every noun's verbs need
it. A step aspect resolving a step through the projects package would be one module reaching
into another, and ``tests/test_architecture.py`` says so.

The *declaration* half lives here for the same reason: :func:`step_arg` / :func:`project_arg`
are the positional argument every step and project verb takes, so the help text — which
reaches the generated skill verbatim — has exactly one source, and a verb cannot promise a
lookup this module does not perform.
"""

import re
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import TYPE_CHECKING

from dplanner.cli.command import CliError
from dplanner.domain.model import Library, Project, Step

if TYPE_CHECKING:
    from dplanner.cli.command import CliContext


# A step's key as a person types it: the number with or without its letter — `S7`, `s7`,
# `7`. The letter is presentation over the stored number (a feature's `F7` is the same
# step as its earlier `S7`), so only the number decides.
_KEY = re.compile(r"^[A-Za-z]?(\d+)$")


def step_arg(parser: ArgumentParser) -> None:
    """The positional a step verb takes, resolved by :func:`find_step`."""
    parser.add_argument("step", help="step key (S7), id, folder name, or part of its title")


def project_arg(parser: ArgumentParser) -> None:
    """The positional a project verb takes, resolved by :func:`find_project`."""
    parser.add_argument("project", help="project id, folder name, or part of its title")


def body_from(file_arg: str) -> str:
    """A text body from a file, or stdin when the argument is ``-``."""
    if file_arg == "-":
        return sys.stdin.read()
    path = Path(file_arg)
    if not path.is_file():
        raise CliError(f"no such file: {file_arg}")
    return path.read_text()


def find_project(library: Library, needle: str) -> Project:
    """A project by id, folder name, or a unique part of its title."""
    return _find(library.projects, needle, "project")


def find_step(library: Library, needle: str, within: Project | None = None) -> Step:
    """A step by key, id, folder name, or a unique part of its title.

    ``within`` is the current project, when the invocation has one: a needle that matches
    there is resolved there, so "the step called review" means *this* project's — and only
    a needle the current project cannot answer at all falls back to the whole library.
    """
    if within is not None and _matches_something(list(within.steps), needle):
        return _find(list(within.steps), needle, "step")
    steps = [step for project in library.projects for step in project.steps]
    return _find(steps, needle, "step")


def _matches_something(candidates: list[Step], needle: str) -> bool:
    lowered = needle.lower()
    number = _key_number(needle)
    return any(
        needle in (node.id, node.folder_name)
        or (number is not None and node.number == number)
        or (needle and node.id.startswith(needle))
        or lowered in node.title.lower()
        for node in candidates
    )


def _key_number(needle: str) -> int | None:
    match = _KEY.match(needle.strip())
    return int(match.group(1)) if match else None


def _find[NodeT: (Project, Step)](candidates: list[NodeT], needle: str, kind: str) -> NodeT:
    """Exact identity first — an id, a folder name, or a step's key — then a unique id
    prefix, then a unique partial title.

    The key is numbered per project, so a bare number is unambiguous inside one and may
    match a step in each of several; several is refused with the keys and titles, exactly
    as a title shared across projects is. The prefix pass is what makes the 8-character
    ids the CLI *prints* the ids it also *accepts* — a message that says "use an id" must
    take the id it showed. It applies to ids only: folder names stay exact, because a
    folder-name prefix is indistinguishable from the start of a title and the title pass
    already covers that intent.

    An ambiguous name is refused rather than resolved to the first match: silently acting on
    one of two things a person might have meant is the failure they cannot see.
    """
    exact = [node for node in candidates if needle in (node.id, node.folder_name)]
    if exact:
        return exact[0]
    number = _key_number(needle)
    keyed = [node for node in candidates if isinstance(node, Step) and node.number == number]
    if len(keyed) == 1:
        return keyed[0]
    if keyed:
        names = ", ".join(sorted(f"{node.title} ({node.id[:8]})" for node in keyed))
        raise CliError(f"{needle!r} is a step in several projects — use an id: {names}")
    prefixed = [node for node in candidates if needle and node.id.startswith(needle)]
    if len(prefixed) == 1:
        return prefixed[0]
    if prefixed:
        names = ", ".join(sorted(f"{node.title} ({node.id[:8]})" for node in prefixed))
        raise CliError(f"{needle!r} is the start of several {kind} ids — type more of it: {names}")
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


# -- resolvers a verb hands the topology gate: "which project does this reshape?" ------------


def project_of(context: "CliContext", args: Namespace) -> Project:
    """The project a project verb names — ``args.project`` through :func:`find_project`."""
    return find_project(context.library, args.project)


def project_of_step(context: "CliContext", args: Namespace) -> Project:
    """The project a step verb's step belongs to, resolved the way the verb itself does."""
    return context.library.project_of(find_step(context.library, args.step, context.current).id)


def project_of_steps(context: "CliContext", args: Namespace) -> Project:
    """The same, for a verb whose steps are a list — the first one names the project.

    A verb reshaping several steps at once reshapes one graph: the model refuses a link
    across projects, so the rest can only be in the same one.
    """
    return context.library.project_of(find_step(context.library, args.steps[0], context.current).id)
