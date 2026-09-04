"""The one ``dplanner`` command: a window, or a verb.

``dplanner`` with no words opens the application. ``dplanner project list`` runs the CLI.
One binary rather than two because the whole point of the CLI is that an agent can use it,
and "which executable" is a paragraph of instructions that a single name makes unnecessary.

The dispatch happens **before** anything Qt is imported, so the CLI path never pays for a
toolkit it does not use — and works on a machine that has none.
"""

import sys

from dplanner.core.telemetry import Telemetry, install, journal_path
from dplanner.modules import default_cli_commands, default_module_formats

# Options that take a value, so the value is not mistaken for a command word. Both entry
# points understand --library; the CLI also scopes verbs with --project; everything else
# Qt is given is a flag.
VALUE_OPTIONS = ("--library", "--project")


def cli_nouns() -> set[str]:
    return {command.path[0] for command in default_cli_commands()}


def command_words(argv: list[str]) -> list[str]:
    """The positional words, with option values skipped.

    Skipping them is the whole job: ``dplanner --library ~/plans.json project list`` has
    three non-flag tokens and only the last two are the command. Reading the path as the
    first word is how this quietly opened a window instead of listing anything.
    """
    words: list[str] = []
    skip = False
    for argument in argv:
        if skip:
            skip = False
        elif argument in VALUE_OPTIONS:
            skip = True
        elif not argument.startswith("-"):
            words.append(argument)
    return words


def looks_like_a_verb(argv: list[str]) -> bool:
    """Whether these arguments are a CLI invocation rather than a request for a window.

    A registered noun, or a bare request for help. Everything else — no arguments, just a
    library, Qt's own ``-style``/``-platform`` — is the application.
    """
    words = command_words(argv)
    if words:
        return words[0] in cli_nouns()
    return bool(argv) and argv[0] in ("-h", "--help", "--version")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    verb = looks_like_a_verb(arguments)
    # The journal is the process's, so it is installed here — before either surface —
    # and both write to the same file: a CLI run's row lands beside the window's.
    install(Telemetry(journal_path(), surface="cli" if verb else "window"))
    if verb:
        from dplanner.cli.command import CliRegistry
        from dplanner.cli.main import run

        registry = CliRegistry()
        registry.register_all(default_cli_commands())
        return run(registry, default_module_formats(), arguments)

    from dplanner.app import main as gui_main

    return gui_main([sys.argv[0], *arguments])
