"""Getting DPlanner onto this machine, from the window.

Three things have to be in place for DPlanner to be usable — the ``dplanner`` command on
PATH, a launcher in the applications menu, and the agent skill an agent reads — and they are
one act, not three: a machine with the command and a skill from an older build is the
ordinary case, and two dialogs and four verbs were what made it invisible. What the window
adds is discoverability: somebody who has never run the CLI finds the state under Tools and
brings all three up to date with one button.

The work itself is ``cli/install.py``, which ``dplanner install all`` also runs — the same
functions, never a second implementation.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.tasks import TaskService
from dplanner.modules.install.dialog import InstallDialog

MODULE_ID = "install"


@dataclass(frozen=True)
class InstallDeps:
    actions: ActionRegistry
    tasks: TaskService
    parent: QWidget
    # The skill files to write, from the same generator the CLI uses. A callable rather than
    # the content, because the composition root builds it from the registry and this module
    # has no business knowing what a registry is.
    skill_files: Callable[[], dict[str, str]]


class InstallModule:
    id = MODULE_ID

    def __init__(self, deps: InstallDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        self._deps.actions.register(
            ActionSpec(
                id="install.dplanner",
                label="&Install DPlanner…",
                menu="Tools",
                group="install",
                order=10,
                tip=(
                    "Install or update the dplanner command, the desktop launcher "
                    "and the agent skill"
                ),
                run=self._run,
            )
        )

    def _run(self, _context: Context) -> None:
        InstallDialog(self._deps.tasks, self._deps.skill_files(), self._deps.parent).exec()
