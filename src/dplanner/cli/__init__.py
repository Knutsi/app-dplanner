"""The command line: the same application, without a window.

DPlanner is meant to be driven by a coding agent as readily as by a person, so the CLI is
not a scripting afterthought — it is the second surface, and modules extend it the way they
extend the menu bar. A feature's ``cli.py`` sits beside its ``module.py``.

**This layer never imports Qt.** It sits between ``domain/`` and ``framework/``, and
``tests/test_architecture.py`` enforces that. The reason is practical: an agent refining a
project makes dozens of small calls, and loading a GUI toolkit for each one costs most of a
second — or fails outright in a container with no graphics libraries at all.

**A verb and a menu action share one command object.** Both build something from
``domain/commands.py``; the GUI pushes it onto the undo stack, the CLI applies it and lets
the store flush. That shared vocabulary is what keeps the two surfaces from drifting.
"""

from dplanner.cli.command import CliCommand, CliContext, CliError, CliRegistry

__all__ = ["CliCommand", "CliContext", "CliError", "CliRegistry"]
