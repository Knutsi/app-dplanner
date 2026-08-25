"""One action: put the agent skill where a coding agent will find it.

The skill is generated from the CLI registry, so this module writes exactly what
``dplanner skill install`` writes — the same function, not a second implementation. What the
window adds is discoverability: somebody who has never run the CLI still finds out that
their agent can drive DPlanner, and the label says whether the copy they have is current.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QWidget

from dplanner.cli.skill import install, status, target_dir
from dplanner.framework.action_registry import ActionRegistry, ActionSpec, ActionState
from dplanner.framework.context import Context
from dplanner.framework.window import StatusHost

MODULE_ID = "agent_skill"

LABELS = {
    "missing": "&Install Agent Skill…",
    "stale": "&Update Agent Skill…",
    "installed": "Agent Skill Is &Current",
}


@dataclass(frozen=True)
class AgentSkillDeps:
    actions: ActionRegistry
    status: StatusHost
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
                id="agent_skill.install",
                label=LABELS["missing"],
                menu="Tools",
                group="agent",
                order=10,
                tip="Write the skill that lets a coding agent drive DPlanner",
                state=self._state,
                run=self._run,
            )
        )

    def _directory(self) -> Path:
        return target_dir(user=True)

    def _state(self, _context: Context) -> ActionState:
        """The label says what pressing it would do — installed, or out of date.

        Reading the state here rather than caching it means the menu is right even when the
        user installed the skill from a terminal a moment ago.
        """
        return ActionState(label=LABELS[status(self._deps.skill_files(), self._directory())])

    def _run(self, _context: Context) -> None:
        written = install(self._deps.skill_files(), self._directory())
        self._deps.status.show_status(f"Agent skill written to {written[0].parent}", 6000)
