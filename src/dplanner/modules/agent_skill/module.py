"""One action: show the agent skill and let the user install, update or remove it.

The skill is generated from the CLI registry, so this module writes exactly what
``dplanner skill install`` writes — the same functions, not a second implementation. What
the window adds is discoverability: somebody who has never run the CLI still finds out that
their agent can drive DPlanner, sees what the skill says and where it goes before anything
is written, and can take it back out again.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.cli.skill import target_dir
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.tasks import TaskService
from dplanner.modules.agent_skill.cli_install import CliInstallDialog
from dplanner.modules.agent_skill.dialog import AgentSkillDialog

MODULE_ID = "agent_skill"


@dataclass(frozen=True)
class AgentSkillDeps:
    actions: ActionRegistry
    tasks: TaskService
    parent: QWidget
    # The files to write, from the same generator the CLI uses. A callable rather than the
    # content, because the composition root builds it from the registry and this module has
    # no business knowing what a registry is.
    skill_files: Callable[[], dict[str, str]]


class AgentSkillModule:
    id = MODULE_ID

    def __init__(self, deps: AgentSkillDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        self._deps.actions.register(
            ActionSpec(
                id="agent_skill.manage",
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
                id="agent_skill.install_cli",
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
        CliInstallDialog(self._deps.tasks, self._deps.parent).exec()
