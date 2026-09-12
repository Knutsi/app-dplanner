"""The one ``dplanner`` command: the CLI, or ``dplanner window``.

``dplanner window`` opens the application (``dpw`` is the same with the word typed for you).
Every other command line is the CLI: ``dplanner
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

**And never from inside an agent's shell.** A window started from a shell an agent CLI
runs is that agent's background process: it ends when the agent's turn does, and every
agent launched from it inherits the shell's session markers and becomes a *child* session
of the first — no transcript of its own, ended with its parent. One such window took four
agents down with it. So ``dplanner window`` refuses when the environment says an agent's
shell is around it, and says why; the launcher scrubs the same markers for a window that
got them some other way. ``ARCHITECTURE.md``'s *The window is a word* has the reasoning.
"""

import os
import sys
from collections.abc import Mapping

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import WINDOW_WORD, run
from dplanner.core.telemetry import Telemetry, install, journal_path
from dplanner.modules import agent_harnesses, default_cli_commands, default_module_formats

# Options that take a value, so the value is not mistaken for a command word. Both surfaces
# understand --library; the CLI also scopes verbs with --project. Skipping the value is
# what lets ``dplanner --library ~/plans.json window`` open a window on that library.
VALUE_OPTIONS = ("--library", "--project")


def agent_shell_markers() -> tuple[str, ...]:
    """What an agent CLI sets in every shell it runs: each harness's first marker — the
    one that names the CLI itself rather than a session detail. Not a dispatch rule —
    the word decides what runs — but a guard on who owns the window, and a missed agent
    here costs a guard, not a wrong dispatch."""
    return tuple(h.shell_markers[0] for h in agent_harnesses() if h.shell_markers)


REFUSAL = (
    "dplanner window: not from inside an agent's shell ({marker} is set).\n"
    "A window opened here is the agent's background process: it ends when the agent's"
    " turn does,\nand every agent launched from it goes with it. Open DPlanner from your"
    " own terminal."
)


def agent_shell_marker(env: Mapping[str, str] = os.environ) -> str:
    """The marker set in this environment, or "" when no agent's shell is around us."""
    return next((name for name in agent_shell_markers() if env.get(name)), "")


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
    marker = agent_shell_marker() if window else ""
    if marker:
        print(REFUSAL.format(marker=marker), file=sys.stderr)
        return 2
    # The journal is the process's, so it is installed here — before either surface —
    # and both write to the same file: a CLI run's row lands beside the window's.
    install(Telemetry(journal_path(), surface="window" if window else "cli"))
    if window:
        from dplanner.app import main as gui_main

        return gui_main([sys.argv[0], *window_arguments(arguments)])

    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    return run(registry, default_module_formats(), arguments)


def window_main(argv: list[str] | None = None) -> int:
    """``dpw``: the window, with the word typed for you.

    The same door — the same refusal inside an agent's shell — with the word prepended.
    It is a ``gui-scripts`` entry in ``pyproject.toml``, so on Windows it is an executable
    with no console window behind it, which is what a desktop launcher should open.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    return main([WINDOW_WORD, *arguments])
