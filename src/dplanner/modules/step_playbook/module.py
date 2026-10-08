"""The playbook aspect, in the running application: a Details block, a project tab, and
*Step ▸ Run Playbook* and *Stop Playbook*.

A step's block picks its playbook and the overrides a choice of its own may carry; the
project's tab, under *Project ▸ Settings…*, picks what a step that never chose runs.

**Run Playbook is Run Agent's equivalent for a pass**: a child menu of every preset beside
Run Agent's, the step's own playbook first and marked with where it was chosen. Each entry is
greyed with its own reason — Run Agent's questions of the step, a role no launch profile
runs, an agent not usable here (``Availability.why_not``, the status checks' reading, never
probed on the GUI thread). Starting one is the launch module's, handed in by the root
(:class:`PlaybookLauncher`): a pass starts only as ``dplanner agent run --playbook``. It is
one step at a time — a selection is what *Autonomous work* runs — and a *Remote ▸* entry is
for when workers exist.

**Stop Playbook stops the step's pass whatever it is doing**, after a confirmation naming what
runs, by running ``dplanner playbook stop`` — the launch module runs it, as it runs Run
Playbook's verb. It is greyed with the reason when nothing of a pass is left to stop.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QMenu, QWidget

from dplanner.domain.model import Library, Step
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
    DataMenuSpec,
)
from dplanner.framework.context import Context, ContextService
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.step_selection import chosen_steps
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.step_playbook.aspect import DATA_FORMAT, MODULE_ID, SPEC, read, resolve
from dplanner.modules.step_playbook.engine import stoppable
from dplanner.modules.step_playbook.passes import agents_of, pinned
from dplanner.modules.step_playbook.presets import PRESETS, Playbook
from dplanner.modules.step_playbook.project_section import ProjectPlaybookSection
from dplanner.modules.step_playbook.section import PlaybookSection
from dplanner.planning.kinds import works_nobody
from dplanner.theme.icons import playbook_icon

RUN_MENU_ID = f"{MODULE_ID}.run_with"
RUN_MENU_TITLE = "Run Playbook"
ONE_AT_A_TIME = "one step at a time — Autonomous work runs a selection"
STOP_TITLE = "Stop Playbook"
# Where the step's playbook was chosen, as its entry in the child menu says.
SOURCE_WORDS = {"step": "this step's", "project": "project default", "landing": "landing default"}


class PlaybookLauncher(Protocol):
    """What Run Playbook needs of the launch: the agent launch module, handed in by the root."""

    def playbook_refusal(self, step: Step) -> str:
        """Why no pass can start on ``step`` here, "" when one can."""
        ...

    def runnable(self) -> tuple[str, ...]:
        """The harnesses some launch profile runs headless."""
        ...

    def implementer(self) -> str:
        """The harness a pass's work stages run."""
        ...

    def start_playbook(self, step: Step, playbook_id: str) -> None:
        """Start a pass, saying how it went."""
        ...

    def stop_playbook(self, step: Step) -> None:
        """Stop the step's pass, saying how it went."""
        ...


class AgentReadings(Protocol):
    """Whether each agent CLI is usable here — the status checks' shared reading."""

    def why_not(self, harness_ids: Iterable[str]) -> str:
        """Why these cannot all run here, "" when they can. Never probes."""
        ...

    def stale(self) -> bool: ...

    def refresh_stale(self) -> None:
        """Probe what is missing or old: a task's body."""
        ...


@dataclass(frozen=True)
class StepPlaybookDeps:
    library: Library
    undo: UndoService[Library]
    details: InspectorSectionRegistry
    project_settings: InspectorSectionRegistry
    harness_ids: tuple[str, ...]  # What a reviewer override may name.
    actions: ActionRegistry
    context: ContextService
    launcher: PlaybookLauncher
    readings: AgentReadings
    parent: QWidget
    # Where the readings are refreshed, off the GUI thread; None refreshes them inline.
    tasks: TaskService | None = None
    # Where a project's runs and questions are: what Stop Playbook reads; None reads nothing.
    project_dir: Callable[[str], Path] | None = None


class StepPlaybookModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepPlaybookDeps) -> None:
        self._deps = deps
        self._reading: TaskRunner | None = None

    def register(self) -> None:
        deps = self._deps
        deps.details.register(
            InspectorSection(
                id=f"{MODULE_ID}.details",
                label=SPEC.label,
                order=18,  # After the size and schedule (10 to 15), before the description (20).
                hint="What runs this step when a playbook is started on it: stages that plan, "
                "execute and judge the work. Default is what the project chose for steps like "
                "this one.",
                factory=lambda: PlaybookSection(deps.library, deps.undo, deps.harness_ids),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and not works_nobody(deps.library.step(step_id))
                ),
            )
        )
        deps.project_settings.register(
            InspectorSection(
                id=f"{MODULE_ID}.project",
                label="Playbooks",
                order=25,
                hint="What a step that never chose a playbook runs, and what a landing runs.",
                factory=lambda: ProjectPlaybookSection(deps.library, deps.undo),
                icon=playbook_icon,
            )
        )
        # The verb the palette runs — the step's own playbook. Its seat is the child menu
        # below, beside Run Agent's, which lists every preset with the step's own first.
        deps.actions.register(
            ActionSpec(
                id="playbook.run",
                label="Run &Playbook",
                menu="Step",
                group="agent",
                submenu=RUN_MENU_TITLE,
                order=15,
                in_menus=False,
                tip="Start the step's playbook: stages that plan, execute and judge the work,"
                " headless",
                icon=playbook_icon,
                state=self._can_run_own,
                run=self._run_own,
            )
        )
        deps.actions.register_data_menu(
            DataMenuSpec(
                id=RUN_MENU_ID,
                menu="Step",
                group="agent",
                title=RUN_MENU_TITLE,
                order=15,  # After Run Agent (10), before Preview Agent Prompt (20).
                fill=self._fill,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="playbook.stop",
                label="Stop Playboo&k",
                menu="Step",
                group="agent",
                order=16,  # Right after Run Playbook's child menu.
                tip="Stop the step's playbook pass, whatever it is doing; nothing of it starts"
                " again by itself",
                state=self._can_stop,
                run=self._stop,
            )
        )
        # Whether each agent is usable is read, never probed, when a menu asks; the probes
        # run on a task whenever the reading has gone stale and the person moves on.
        deps.context.changed.connect(lambda _context: self._refresh())
        self._refresh()

    # -- Run Playbook --------------------------------------------------------------------------

    def _step(self, context: Context) -> Step | str | None:
        """The one step Run Playbook acts on, why not when several are chosen, or None."""
        library = self._deps.library
        chosen = chosen_steps(context, library)
        if len(chosen) > 1:
            return ONE_AT_A_TIME
        return library.step(chosen[0]) if chosen else None

    def _own(self, step: Step) -> tuple[Playbook | None, str]:
        """The step's own playbook, and the words for where it was chosen."""
        resolved = resolve(step, self._deps.library.project_of(step.id))
        return resolved.playbook, SOURCE_WORDS.get(resolved.source, "")

    def _refusal(self, step: Step, playbook: Playbook) -> str:
        """Why a pass of ``playbook`` cannot start on ``step`` here, "" when it can."""
        launcher = self._deps.launcher
        if why := launcher.playbook_refusal(step):
            return why
        try:
            settings = pinned(playbook, read(step), launcher.implementer(), launcher.runnable())
        except ValueError as error:
            return str(error)
        return self._deps.readings.why_not(agents_of(playbook, settings))

    def _can_run_own(self, context: Context) -> ActionState:
        step = self._step(context)
        if step is None:
            return DISABLED
        if isinstance(step, str):
            return ActionState(enabled=False, label=f"{RUN_MENU_TITLE} — {step}")
        playbook, _source = self._own(step)
        if playbook is None:
            return ActionState(
                enabled=False,
                label=f"{RUN_MENU_TITLE} — the step has no playbook; pick one from Step ▸"
                f" {RUN_MENU_TITLE}",
            )
        if why := self._refusal(step, playbook):
            return ActionState(enabled=False, label=f"{RUN_MENU_TITLE} — {why}")
        return ENABLED

    def _run_own(self, context: Context) -> None:
        step = self._step(context)
        if isinstance(step, Step) and (playbook := self._own(step)[0]) is not None:
            self._deps.launcher.start_playbook(step, playbook.id)

    # -- Stop Playbook -------------------------------------------------------------------------

    def _running(self, step: Step) -> str:
        """What stopping the step's pass would end, in words, or "" — read from its records."""
        deps = self._deps
        if deps.project_dir is None:
            return ""
        try:
            project_dir = deps.project_dir(deps.library.project_of(step.id).id)
        except KeyError:  # A project the store does not hold has no records here.
            return ""
        return stoppable(project_dir, step)

    def _can_stop(self, context: Context) -> ActionState:
        step = self._step(context)
        if step is None:
            return DISABLED
        if isinstance(step, str):
            return ActionState(enabled=False, label=f"{STOP_TITLE} — {step}")
        if not self._running(step):
            return ActionState(
                enabled=False, label=f"{STOP_TITLE} — no playbook pass runs or waits on it"
            )
        return ENABLED

    def _stop(self, context: Context) -> None:
        deps = self._deps
        step = self._step(context)
        if not isinstance(step, Step) or not (running := self._running(step)):
            return
        question = (
            f"Stop the playbook on “{step.title}”? {running[0].upper()}{running[1:]}. Nothing"
            " of the pass will start again by itself; a step in progress goes back to pending,"
            " and its worktree and branch are kept."
        )
        if confirm(deps.parent, STOP_TITLE, question, verb="Stop"):
            deps.launcher.stop_playbook(step)

    def _fill(self, menu: QMenu) -> None:
        """Every preset over the chosen step, its own first and marked, each greyed with its
        own reason — one agent may be signed out where another is not. Rebuilt every time
        the menu opens."""
        deps = self._deps
        self._refresh()
        step = self._step(deps.context.current())
        if not isinstance(step, Step):
            entry = menu.addAction(step.capitalize() if step else "No step is chosen")
            entry.setEnabled(False)
            return
        own, source = self._own(step)
        listed = [own] if own is not None else []
        listed += [playbook for playbook in PRESETS if playbook != own]
        for playbook in listed:
            name = f"{playbook.name} ({source})" if playbook == own else playbook.name
            why = self._refusal(step, playbook)
            entry = menu.addAction(f"{name} — {why}" if why else name)
            entry.setToolTip(playbook.summary)
            entry.setEnabled(not why)
            entry.triggered.connect(
                lambda _checked=False, s=step, p=playbook: deps.launcher.start_playbook(s, p.id)
            )

    def _refresh(self) -> None:
        """Probe the agents whose reading is missing or old, on a task — one at a time."""
        deps = self._deps
        if not deps.readings.stale():
            return
        if deps.tasks is None:
            deps.readings.refresh_stale()
            return
        runner = self._reading = self._reading or TaskRunner(deps.tasks, deps.parent)
        if not runner.is_busy():
            runner.run("Checking the agent CLIs", deps.readings.refresh_stale, key="agents.check")
