"""Getting DPlanner onto this machine, from the window.

Three things have to be in place for DPlanner to be usable — the agent skill an agent
reads, the ``dplanner`` command on PATH, and a launcher in the applications menu — and each
has a CLI verb (``skill install``, the ``uv tool install`` the skill names, ``desktop
install``). What the window adds is discoverability: somebody who has never run the CLI
finds them under Tools, sees what will be written and where before anything is, and can
take each back out. Every dialog here writes exactly what its verb writes — the same
functions, never a second implementation.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.cli.skill import target_dir
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.tasks import TaskService
from dplanner.modules.install.command_dialog import CommandInstallDialog
from dplanner.modules.install.skill_dialog import AgentSkillDialog

MODULE_ID = "install"


@dataclass(frozen=True)
class InstallDeps:
    actions: ActionRegistry
    tasks: TaskService
    parent: QWidget
    # The files to write, from the same generator the CLI uses. A callable rather than the
    # content, because the composition root builds it from the registry and this module has
    # no business knowing what a registry is.
    skill_files: Callable[[], dict[str, str]]


class InstallModule:
    id = MODULE_ID

    def __init__(self, deps: InstallDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        self._deps.actions.register(
            ActionSpec(
                id="install.skill",
                label="&Agent Skill…",
                menu="Tools",
                group="agent",
                order=10,
                tip="Preview, install or remove the skill that lets a coding agent drive DPlanner",
                run=self._run,
            )
        )
        self._deps.actions.register(
            ActionSpec(
                id="install.command",
                label="Install &dplanner Command…",
                menu="Tools",
                group="agent",
                order=20,
                tip="Put the dplanner command on PATH, so agents and terminals can run it",
                run=self._run_install_cli,
            )
        )

    def _run(self, _context: Context) -> None:
        dialog = AgentSkillDialog(
            self._deps.skill_files(), target_dir(user=True), self._deps.parent
        )
        dialog.exec()

    def _run_install_cli(self, _context: Context) -> None:
        CommandInstallDialog(self._deps.tasks, self._deps.parent).exec()
