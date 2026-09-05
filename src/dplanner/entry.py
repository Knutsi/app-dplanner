"""The one ``dplanner`` command: the CLI, or ``dplanner window``.

``dplanner window`` opens the application. Every other command line is the CLI: ``dplanner
project list`` runs a verb, a word the CLI does not know is refused with exit 2, and a bare
``dplanner`` prints the help. One binary rather than two because the whole point of the CLI
is that an agent can use it, and "which executable" is a paragraph of instructions that a
single name makes unnecessary.

The window is a word, and not the default, because an agent's reflex on an unfamiliar tool
is to run it bare — and a window that opens on the developer's desktop and blocks the
agent's shell is the wrong answer to that question. A word no task contains is a fence that
holds for every agent, where a terminal test or an environment variable holds for some.
``ARCHITECTURE.md``'s *The window is a word* has the reasoning.

The dispatch happens **before** anything Qt is imported, so the CLI path never pays for a
toolkit it does not use — and works on a machine that has none. Qt's own ``-style`` and
``-platform`` follow the word, because the first word is the decision.
"""

import sys

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import WINDOW_WORD, run
from dplanner.core.telemetry import Telemetry, install, journal_path
from dplanner.modules import default_cli_commands, default_module_formats

# Options that take a value, so the value is not mistaken for a command word. Both surfaces
# understand --library; the CLI also scopes verbs with --project. Skipping the value is
# what lets ``dplanner --library ~/plans.json window`` open a window on that library.
VALUE_OPTIONS = ("--library", "--project")


def _word_indices(argv: list[str]) -> list[int]:
    """Where the positional words sit in ``argv``, with option values skipped."""
    indices: list[int] = []
    skip = False
    for index, argument in enumerate(argv):
        if skip:
            skip = False
        elif argument in VALUE_OPTIONS:
            skip = True
        elif not argument.startswith("-"):
            indices.append(index)
    return indices


def command_words(argv: list[str]) -> list[str]:
    """The positional words, with option values skipped.

    Skipping them is the whole job: ``dplanner --library ~/plans.json project list`` has
    three non-flag tokens and only the last two are the command. Reading the path as the
    first word is how this quietly opened a window instead of listing anything.
    """
    return [argv[index] for index in _word_indices(argv)]


def opens_a_window(argv: list[str]) -> bool:
    """Whether these arguments ask for a window: the first command word is the window word.

    Everything else — nothing, a verb, a typo, a Qt flag on its own — is the CLI, which
    says what it did not understand.
    """
    words = command_words(argv)
    return bool(words) and words[0] == WINDOW_WORD


def window_arguments(argv: list[str]) -> list[str]:
    """``argv`` — one that ``opens_a_window`` — without the word, so Qt never sees it.

    By index, not by value: in ``--library window window`` the first ``window`` is a path.
    """
    first = _word_indices(argv)[0]
    return argv[:first] + argv[first + 1 :]


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    window = opens_a_window(arguments)
    # The journal is the process's, so it is installed here — before either surface —
    # and both write to the same file: a CLI run's row lands beside the window's.
    install(Telemetry(journal_path(), surface="window" if window else "cli"))
    if window:
        from dplanner.app import main as gui_main

        return gui_main([sys.argv[0], *window_arguments(arguments)])

    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    return run(registry, default_module_formats(), arguments)
