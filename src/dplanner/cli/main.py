"""The argparse tree, built from the registry.

Two levels, always: ``dplanner <noun> <verb>``. The parsers are built from whatever was
registered, so adding a verb to a module adds it to ``--help`` and to the generated skill
without editing anything here.

**Help output is a pure function of the registry** — ``_Formatter`` has the why.
"""

import sys
from argparse import (
    SUPPRESS,
    ArgumentParser,
    HelpFormatter,
    Namespace,
    RawDescriptionHelpFormatter,
)
from collections.abc import Sequence
from typing import TextIO

from dplanner.cli.command import CliCommand, CliContext, CliError, CliRegistry
from dplanner.cli.discovery import find_current_project, find_library, open_library
from dplanner.domain.library_file import LIBRARY_ENV
from dplanner.core.module_data import ModuleDataFormat
from dplanner.identity import APP_NAME, APP_VERSION

PROG = "dplanner"
HELP_WIDTH = 88


class _Formatter(RawDescriptionHelpFormatter):
    """Argument help wrapped to a fixed width; examples left exactly as written.

    Fixed rather than the terminal's width because ``skill.py`` renders these same parsers
    into files that go into version control — a help text that reflowed with the window
    would produce a diff every time somebody regenerated it somewhere else.
    """

    def __init__(self, prog: str) -> None:
        super().__init__(prog, width=HELP_WIDTH)


def _formatter(prog: str) -> HelpFormatter:
    return _Formatter(prog)


def _add_common(parser: ArgumentParser, *, suppress: bool = False) -> None:
    """``--library``, ``--project`` and ``--json``, on the top level and on every verb.

    Argparse wants global options before the subcommand, which is not how anybody types —
    ``dplanner step show x --json`` is the natural order and is what an agent will write. So
    the options exist in both places, and the verb-level copies default to SUPPRESS so that
    omitting them leaves whatever the top level parsed.

    ``--project`` scopes a verb to one project when the working directory does not; its
    dest is ``project_scope`` because several verbs already take a positional ``project``.
    """
    default = SUPPRESS if suppress else None
    parser.add_argument(
        "--library",
        metavar="PATH",
        default=default,
        help=f"the project library to act on (default: the user's, or ${LIBRARY_ENV})",
    )
    parser.add_argument(
        "--project",
        metavar="NAME",
        dest="project_scope",
        default=default,
        help="the project to act in (default: resolved from the working directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=SUPPRESS if suppress else False,
        help="machine-readable output",
    )


def build_tree(registry: CliRegistry) -> tuple[ArgumentParser, dict[str, ArgumentParser]]:
    """The parser tree, and every verb's parser by command id.

    The map is handed back rather than dug out of argparse's internals afterwards, because
    ``skill.py`` renders those same parsers into a file: one tree, built once, is what keeps
    the reference and ``--help`` from ever disagreeing.
    """
    verb_parsers: dict[str, ArgumentParser] = {}
    parser = ArgumentParser(
        prog=PROG,
        description=f"{APP_NAME}: plan your projects as graphs of connected steps.",
        formatter_class=_formatter,
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {APP_VERSION}")
    _add_common(parser)
    nouns = parser.add_subparsers(dest="noun", required=True, metavar="<noun>")
    for noun, commands in registry.groups().items():
        noun_parser = nouns.add_parser(noun, help=_noun_help(commands), formatter_class=_formatter)
        verbs = noun_parser.add_subparsers(dest="verb", required=True, metavar="<verb>")
        for command in commands:
            verb_parser = verbs.add_parser(
                command.path[1],
                help=command.summary,
                description=command.summary,
                epilog=_examples(command),
                formatter_class=_formatter,
            )
            command.configure(verb_parser)
            _add_common(verb_parser, suppress=True)
            verb_parser.set_defaults(_command=command)
            verb_parsers[command.id] = verb_parser
    return parser, verb_parsers


def _noun_help(commands: Sequence[CliCommand]) -> str:
    return ", ".join(command.path[1] for command in commands)


def _examples(command: CliCommand) -> str:
    if not command.examples:
        return ""
    return "examples:\n" + "\n".join(f"  {line}" for line in command.examples)


def run(
    registry: CliRegistry,
    formats: Sequence[ModuleDataFormat],
    argv: Sequence[str],
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Parse, open the library if the verb needs one, and run it."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    args: Namespace = build_tree(registry)[0].parse_args(list(argv))
    command: CliCommand = args._command
    try:
        if not command.needs_library:
            return command.run(CliContext(out=out, as_json=args.as_json), args)
        path = find_library(args.library)
        with open_library(path, formats, out, as_json=args.as_json) as context:
            context.current = find_current_project(
                context.library, context.store, args.project_scope
            )
            return command.run(context, args)
    except CliError as error:
        print(f"{PROG}: {error}", file=err)
        return 1
