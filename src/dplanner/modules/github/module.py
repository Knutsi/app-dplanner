"""The GitHub aspect, in the running application: the GitHub tab, the PR refresher, and
*Open Pull Request* — a step's PR on the web, from any surface a step is picked on."""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, Step, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.step_selection import focused_step
from dplanner.framework.tasks import TaskService
from dplanner.framework.undo import UndoService
from dplanner.modules.github.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    enabled,
    pr_label,
    pr_url,
    read,
    write_state,
)
from dplanner.modules.github.gh import parse_repo
from dplanner.modules.github.refresh import PrRefresher
from dplanner.modules.github.section import GithubSection, open_url
from dplanner.theme.icons import branch_icon, pull_request_icon

OPEN_PR = "Open Pull Re&quest"


@dataclass(frozen=True)
class GithubDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    tasks: TaskService
    actions: ActionRegistry
    parent: QWidget  # The window: owns the PR refresher.
    # step id -> the repository URL that step's refs belong to: the project's code
    # repository (`RepositoryFacts.code_remote`), arriving through the composition root.
    repository_for: Callable[[StepId], str]
    # A step waiting on its merge is done once its PR reads merged: the status aspect's
    # writer, applied off the undo stack, handed over by the root — this module never
    # learns what a status is. True when it wrote.
    finish_merged: Callable[[StepId], bool] = field(default=lambda _step_id: False)


class GithubModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: GithubDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=70,  # After Milestone (50) and Handoff (60).
                factory=lambda: GithubSection(
                    deps.library, deps.undo, deps.repository_for, deps.tasks, deps.finish_merged
                ),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and enabled(deps.library.step(step_id))
                ),
            )
        )
        deps.actions.register(
            aspect_toggle(
                id="github.toggle",
                label=SPEC.label,
                order=100,
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=enabled,
                fresh=lambda _step, _project: write_state(True),
                icon=branch_icon,
                tip="Track this step's branch and pull request; fill them in on the tab",
            )
        )
        # Beside Show Agent Terminal: where a step's work went is what follows a run, and a
        # table's row menu and a card both render this band.
        deps.actions.register(
            ActionSpec(
                id="github.open_pr",
                label=OPEN_PR,
                menu="Step",
                group="agent",
                order=38,
                tip="The step's pull request, on GitHub",
                icon=pull_request_icon,
                state=self._can_open_pr,
                run=self._open_pr,
            )
        )
        PrRefresher(
            deps.library,
            deps.tasks,
            deps.repository_for,
            parent=deps.parent,
            finish_merged=deps.finish_merged,
        ).start()
        # Nothing is raised at launch. A machine without gh still records typed refs, and the
        # tab says so where it bites; *this machine* is the Setup Checklist's subject, which
        # is where `checks.py` puts both gh rows. DESIGN.md's *A machine without gh*.

    def _pr_address(self, step: Step) -> tuple[str, str]:
        """Where the step's PR is on the web, or why it cannot be said. The repository is
        asked only when the refs carry a number and no address of their own."""
        refs = read(step)
        if refs is None or not refs.has_pr():
            return "", "no pull request recorded"
        if refs.pr_url:
            return refs.pr_url, ""
        address = pr_url(refs, parse_repo(self._deps.repository_for(step.id)))
        if not address:
            return "", f"no GitHub repository to find {pr_label(refs)} in"
        return address, ""

    def _can_open_pr(self, context: Context) -> ActionState:
        step = focused_step(context, self._deps.library)
        if step is None:
            return DISABLED
        _address, refusal = self._pr_address(step)
        if refusal:
            return ActionState(enabled=False, label=f"{OPEN_PR.replace('&', '')} — {refusal}")
        return ActionState(label=OPEN_PR)

    def _open_pr(self, context: Context) -> None:
        step = focused_step(context, self._deps.library)
        address = self._pr_address(step)[0] if step is not None else ""
        if address:
            open_url(address)
