"""The playbook aspect, in the running application: a Details block, a project tab,
*Step ▸ Run Playbook*, and where each step's pass stands for the card's strip.

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

**Where a pass stands is polled** (:class:`PassStandings`). Its runs and questions are
written by other processes — a supervisor, an advance, an answer — and nothing watches their
directories, so every :data:`POLL_MS` it compares each project's ledger and questions
fingerprints, re-reads a project whose records moved (``engine.standings``, the reading
``playbook show`` makes) and re-reads everything once a minute for the clock alone: a hold's
reset passes, and a pass that ended stops being shown, with nothing written. When what it
holds for a project changes, :attr:`PassStandings.changed` names it and the canvas re-reads.
"""

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMenu, QWidget

from dplanner.core.signals import Signal
from dplanner.domain import ledger, questions
from dplanner.domain.model import Library, ProjectId, Step, StepId
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
from dplanner.modules.step_playbook.aspect import DATA_FORMAT, MODULE_ID, SPEC, read, resolve
from dplanner.modules.step_playbook.engine import standings
from dplanner.modules.step_playbook.passes import Standing, agents_of, describe, pinned
from dplanner.modules.step_playbook.presets import PRESETS, Playbook
from dplanner.modules.step_playbook.project_section import ProjectPlaybookSection
from dplanner.modules.step_playbook.section import PlaybookSection
from dplanner.planning.kinds import works_nobody
from dplanner.theme.icons import playbook_icon

RUN_MENU_ID = f"{MODULE_ID}.run_with"
RUN_MENU_TITLE = "Run Playbook"
ONE_AT_A_TIME = "one step at a time — Autonomous work runs a selection"
# Where the step's playbook was chosen, as its entry in the child menu says.
SOURCE_WORDS = {"step": "this step's", "project": "project default", "landing": "landing default"}
POLL_MS = 2000
# A hold's reset passes and an ended pass stops being shown with nothing written.
CLOCK_S = 60.0


class PassStandings:
    """Where each step's latest playbook pass stands, per project — what the card's playbook
    strip says. Built by the root ahead of the canvas that reads it; polling starts with the
    module's :meth:`StepPlaybookModule.register`, so a discarded build stops."""

    def __init__(
        self, library: Library, project_dir: Callable[[ProjectId], Path], parent: QWidget
    ) -> None:
        self._library = library
        self._project_dir = project_dir
        self._seen: dict[ProjectId, tuple[object, ...]] = {}
        self._held: dict[ProjectId, dict[StepId, Standing]] = {}
        self._read_at = 0.0
        self.changed: Signal[str] = Signal("step_playbook.standings_changed")
        self._timer = QTimer(parent)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.refresh)

    def start(self) -> None:
        self._timer.start()
        self.refresh()

    def card(self, project_id: ProjectId, step_id: StepId) -> tuple[str, str, str]:
        """What a card's playbook strip says — the phrase, its tone and the stages for its
        tooltip — or ("", "", "") for a step with no pass shown."""
        stands = self._held.get(project_id, {}).get(step_id)
        return ("", "", "") if stands is None else (stands.phrase, stands.tone, describe(stands))

    def refresh(self) -> None:
        """Re-read each project whose records moved — every project once a minute — and say
        which changed."""
        clock = time.monotonic() - self._read_at >= CLOCK_S
        if clock:
            self._read_at = time.monotonic()
        now = datetime.now(UTC)
        for project in self._library.projects:
            directory = self._project_dir(project.id)
            stamp = (ledger.fingerprint(directory), questions.fingerprint(directory))
            if stamp == self._seen.get(project.id) and not clock:
                continue
            self._seen[project.id] = stamp
            found = standings(directory, project.steps, now) if stamp[0] else {}
            if found != self._held.get(project.id, {}):
                self._held[project.id] = found
                self.changed.emit(project.id)


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
    standings: PassStandings  # Started here; read by the canvas through the root.
    # Where the readings are refreshed, off the GUI thread; None refreshes them inline.
    tasks: TaskService | None = None


class StepPlaybookModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepPlaybookDeps) -> None:
        self._deps = deps
        self._reading: TaskRunner | None = None

    def register(self) -> None:
        deps = self._deps
        deps.standings.start()
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
