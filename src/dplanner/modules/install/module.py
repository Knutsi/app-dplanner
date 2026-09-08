"""Getting DPlanner onto this machine, from the window.

Three things have to be in place for DPlanner to be usable — the agent skill an agent
reads, the ``dplanner`` command on PATH, and a launcher in the applications menu — and each
has a CLI verb (``skill install``, the ``uv tool install`` the skill names, ``desktop
install``). What the window adds is discoverability: somebody who has never run the CLI
finds them under Tools, sees what will be written and where before anything is, and can
take each back out. Every dialog here writes exactly what its verb writes — the same
functions, never a second implementation.

The skill's files are rendered from the command registry, and that render costs a good
part of a second, so it happens **once per window, off the GUI thread**, and both readers
— the dialog and the notice source that says the installed copy is out of date — read the
cache. The dialog renders inline only when asked for before the worker has answered.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QWidget

from dplanner.cli.skill import target_dir
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.modules.install.command_dialog import CommandInstallDialog
from dplanner.modules.install.notices import SkillNoticeSource
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


class _SkillRender(QObject):
    """The render on a worker, its answer back on the GUI thread — the runner has no
    result seam, so the owner's own queued Qt signal carries it."""

    done = QtSignal(object)  # dict[str, str]


class InstallModule:
    id = MODULE_ID

    def __init__(self, deps: InstallDeps) -> None:
        self._deps = deps
        self._files: dict[str, str] | None = None
        self._render = _SkillRender(deps.parent)
        self._render.done.connect(self._rendered)
        self._runner = TaskRunner(deps.tasks, parent=self._render)
        self._source = SkillNoticeSource(lambda: self._files, self._render_async)

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

    def notice_source(self) -> SkillNoticeSource:
        """Whether the installed skill is this build's — for the notices inbox."""
        return self._source

    def skill_files(self) -> dict[str, str]:
        """The rendered files, from the cache or rendered now."""
        if self._files is None:
            self._files = self._deps.skill_files()
        return self._files

    def _render_async(self) -> None:
        if self._files is not None or self._runner.is_busy():
            return
        render, done = self._deps.skill_files, self._render.done

        def body() -> None:  # Worker thread: the registry is static, nothing else is read.
            done.emit(render())

        self._runner.run("Rendering the agent skill", body, key="install.skill")

    def _rendered(self, files: object) -> None:
        if isinstance(files, dict) and self._files is None:
            self._files = files
        self._source.changed.emit()

    def _run(self, _context: Context) -> None:
        dialog = AgentSkillDialog(self.skill_files(), target_dir(user=True), self._deps.parent)
        dialog.exec()
        # Install or Remove may have run: the inbox's notice is stale until it asks again.
        self._source.changed.emit()

    def _run_install_cli(self, _context: Context) -> None:
        CommandInstallDialog(self._deps.tasks, self._deps.parent).exec()
