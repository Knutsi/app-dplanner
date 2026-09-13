"""The agent-run aspect, in the running application: the shells this window launched.

The aspect on the step is written by Run Agent (through the composition root's
``track`` callback) and by the CLI from inside the agent's shell; the canvas reads it
through the composition root's accent translation. What this module adds is the other
half of a launch — **the shell is a peer this window keeps an eye on**:

- A two-second timer, running only while a run is live, reads each run's exit file and
  pid (``runs.settle``). When the shell has ended, the step's state is cleared the way the
  launch was stamped — directly, off the undo stack, with the launch origin — and the
  status bar says how it ended. **The same tick reads what the run consumed**: the
  harness that ran it is asked for its own record of the session (``deps.report``, the
  composition root's reading of ``agent_harnesses()``), and the tokens land on the step's
  ``agent_usage`` aspect (``usage.py``) the same way — a row per run, off the undo stack.
  A harness that mints its own session id is found by directory and start time, which is
  also what makes such a run resumable afterwards. Both writes are skipped while the
  workspace has changed underneath: the library watcher adopts the change into the live
  model first — or, when the store cannot reconcile it, falls back to a rebuild whose new
  module re-adopts its runs from the per-user store — and the next tick checks again on a plan this
  window has seen, so the exit is never written over an agent's own last ``dplanner``
  call.
- A status-bar button ("Agent on “X”", "2 agents running") opens the Agents browser —
  View ▸ Agents… does the same — where every run this machine launched is a row with its
  state or outcome, *Show Terminal*, *Reveal* and a dismiss — and, once it has ended, the
  command that picks the agent up again where it stopped, as the wrapper recorded it.
- Tools ▸ Agent List is the quick switch: a data child menu listing the live runs, each
  entry raising its terminal. Availability is per run (``terminal.focus_reason`` — a tmux
  pane is reachable on a desktop whose bare windows are not), and a run that cannot be
  switched to is greyed with the reason, in the list, the browser and the Step verb alike.
- Two Step-menu verbs: *Show Agent Terminal* (the focus provider in ``terminal.py``, greyed
  with the reason when the desktop cannot) and *Clear Agent Run*, the window's twin of
  ``dplanner agent-state clear`` — an edit of the user's, so it goes through the undo stack.

Runs live in the user's store (``user_config``), never the plan: a temp directory and a
pid are facts about this machine.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMenu, QWidget

from dplanner.domain.agents import AgentHarness, Usage, harness_by_id
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, StepId
from dplanner.framework.action_menu import append_action
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
    DataMenuSpec,
)
from dplanner.framework.context import Context, ContextService
from dplanner.framework.undo import UndoService
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import StatusBarButton
from dplanner.framework.window import StatusHost
from dplanner.framework.window_watch import WatchableRepository
from dplanner.modules.step_agent_run import terminal
from dplanner.modules.step_agent_run.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    read,
    record_exit,
    record_launch,
)
from dplanner.modules.step_agent_run.runs import (
    AgentRun,
    describe,
    new_run,
    read_shell,
    run_facts,
    settle,
)
from dplanner.modules.step_agent_run.usage import record, row_for, rows, words
from dplanner.modules.step_agent_run.view import AgentBrowserDialog, button_text

POLL_MS = 2000
RUNS_KEY = "runs"


@dataclass(frozen=True)
class StepAgentRunDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    context: ContextService
    status: StatusHost
    parent: QWidget
    # Whether the plan changed underneath: an exit is never written over another writer.
    repo: WatchableRepository
    # Selects a step in its project — the ``steps.reveal`` verb, run against the row's step.
    reveal: Callable[[StepId], None]
    # Every agent CLI this build knows: which one a run recorded is looked up here for
    # its ``report`` (the session and the tokens) and its ``resume`` template.
    harnesses: tuple[AgentHarness, ...] = ()


class StepAgentRunModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepAgentRunDeps) -> None:
        self._deps = deps
        self._runs: list[AgentRun] = []
        self._timer: QTimer | None = None
        self._button: StatusBarButton | None = None
        self._browser: AgentBrowserDialog | None = None

    def register(self) -> None:
        deps = self._deps
        self._runs = [
            run
            for run in map(AgentRun.from_json, get_global(MODULE_ID, RUNS_KEY, []))
            if run is not None
        ]
        self._button = StatusBarButton("Launched agents — click to open")
        self._button.clicked.connect(lambda: self._open_browser())
        deps.status.add_status_widget(self._button)
        self._browser = AgentBrowserDialog(
            deps.parent,
            title_of=self._title_of,
            state_of=lambda step_id: (
                read(deps.library.step(step_id)) if deps.library.has(step_id) else ""
            ),
            show_terminal=self._show_terminal,
            reveal=lambda run: deps.reveal(run.step_id),
            forget=self._forget,
            clear_ended=self._clear_ended,
        )
        self._timer = QTimer(self._button)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.check)
        deps.library.module_data_changed.connect(lambda *_a: self._refresh())

        deps.actions.register(
            ActionSpec(
                id="agent.show_terminal",
                label="Show Agent &Terminal",
                menu="Step",
                group="agent",
                order=30,
                tip="Bring the terminal the agent runs in to the front",
                state=self._can_show_terminal,
                run=lambda context: self._show_terminal_for(context),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="agent.clear_run",
                label="Clear Agent &Run",
                menu="Step",
                group="agent",
                order=40,
                tip="The run is over: take the agent chip off this step",
                state=self._can_clear,
                run=self._clear,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="agent_run.show_agents",
                label="A&gents…",
                menu="View",
                group="panels",
                order=45,
                tip="Show the agents launched from this window and how they ended",
                run=lambda _context: self._open_browser(),
            )
        )
        deps.actions.register_data_menu(
            DataMenuSpec(
                id="agent_run.list",
                menu="Tools",
                group="runs",
                title="Agent List",
                order=10,
                fill=self._fill_agent_list,
            )
        )
        self.check()

    # -- tracking ----------------------------------------------------------------------------

    def runs(self) -> list[AgentRun]:
        return list(self._runs)

    def track(
        self,
        step_id: StepId,
        shell_file: str,
        exit_file: str,
        harness: str = "",
        session: str = "",
        prompt_chars: int = 0,
    ) -> None:
        """A shell was just spawned on the step: stamp it, remember it, start watching."""
        record_launch(self._deps.library, step_id)
        self._runs.append(new_run(step_id, shell_file, exit_file, harness, session, prompt_chars))
        self._store()
        self._refresh()

    def check(self) -> None:
        """One tick: settle every live run whose shell has ended, and say so.

        The store is asked whether the plan changed underneath only once a run *has*
        ended: that answer is a walk over every plan file, on the GUI thread, and asking
        it every two seconds for its own sake stalled a large library's window for as
        long as the walk took (300 to 500 ms) the whole time an agent ran. Settling a run
        is a handful of stats, so the tick costs nothing until there is an exit to write.
        """
        deps = self._deps
        ended = [
            (index, settled)
            for index, run in enumerate(self._runs)
            if (settled := settle(run)) is not run
        ]
        if not ended:
            self._refresh()
            return
        if deps.repo.changed_underneath():
            return  # The watcher takes the change first; the next tick checks again.
        for index, settled in ended:
            settled, usage_words = self._read_back(settled)
            self._runs[index] = settled
            record_exit(deps.library, settled.step_id)
            deps.status.show_status(
                f"Agent on “{self._title_of(settled.step_id)}” {describe(settled, '')}"
                + usage_words,
                6000,
            )
        self._store()
        self._refresh()

    def _read_back(self, run: AgentRun) -> tuple[AgentRun, str]:
        """The harness's own record of the ended run: the session it was, kept on the
        run, and the tokens it consumed, recorded on the step. The words for the status
        line come back beside the run; "" when there was nothing to read."""
        harness = harness_by_id(self._deps.harnesses, run.harness)
        if harness is None or harness.report is None:
            return run, ""
        report = harness.report(run_facts(run))
        if report is None:
            return run, ""
        if report.session and not run.session:
            run = replace(run, session=report.session)
        if report.usage is None:
            return run, ""
        record(
            self._deps.library,
            run.step_id,
            row_for(run.harness, run.session, report.usage, prompt_chars=run.prompt_chars),
        )
        return run, f" — {words(report.usage)}"

    def _forget(self, run: AgentRun) -> None:
        self._runs = [other for other in self._runs if other.key != run.key]
        self._store()
        self._refresh()

    def _clear_ended(self) -> None:
        self._runs = [run for run in self._runs if run.live]
        self._store()
        self._refresh()

    def _store(self) -> None:
        set_global(MODULE_ID, RUNS_KEY, [run.to_json() for run in self._runs])

    def _refresh(self) -> None:
        if self._button is None or self._browser is None or self._timer is None:
            return
        self._button.show_text(button_text(self._runs, self._title_of))
        if self._browser.isVisible():
            self._browser.refresh(self._runs, self._focus_reason, self._resume_of, self._usage_of)
        live = any(run.live for run in self._runs)
        if live and not self._timer.isActive():
            self._timer.start()
        elif not live:
            self._timer.stop()

    def _open_browser(self) -> None:
        assert self._browser is not None
        self._browser.refresh(self._runs, self._focus_reason, self._resume_of, self._usage_of)
        self._browser.show()  # Non-modal: the agents keep working underneath.
        self._browser.raise_()

    def _title_of(self, step_id: StepId) -> str:
        library = self._deps.library
        if library.has(step_id):
            return library.step(step_id).title or "Untitled step"
        return "a deleted step"

    def _live_run(self, step_id: StepId) -> AgentRun | None:
        return next((run for run in self._runs if run.live and run.step_id == step_id), None)

    def _focus_reason(self, run: AgentRun) -> str:
        """Why this run's terminal cannot be raised, or "" — per run, not per desktop."""
        return terminal.focus_reason(read_shell(run))

    def _resume_of(self, run: AgentRun) -> str:
        """The command that picks an ended run up where it stopped: as the wrapper
        recorded it, else composed from the session the harness found afterwards;
        "" for a live run or an agent that cannot resume."""
        if run.live:
            return ""
        shell = read_shell(run)
        if shell.get("resume"):
            return shell["resume"]
        harness = harness_by_id(self._deps.harnesses, run.harness)
        if harness is None or not harness.resume or not run.session:
            return ""
        command = harness.resume.replace("{session}", run.session)
        directory = shell.get("dir", "")
        return f'cd "{directory}" && {command}' if directory else command

    def _usage_of(self, run: AgentRun) -> str:
        """What the run consumed, as its step's row records it, or ""."""
        library = self._deps.library
        if not library.has(run.step_id):
            return ""
        step = library.step(run.step_id)
        for row in rows(step):
            if run.session and row.get("session") == run.session:
                return words(Usage(int(row["input"]), int(row["output"])))
        return ""

    # -- the verbs -----------------------------------------------------------------------------

    def _can_show_terminal(self, context: Context) -> ActionState:
        step_id = self._focused(context)
        if step_id is None:
            return DISABLED
        run = self._live_run(step_id)
        if run is None:
            return ActionState(
                enabled=False,
                label="Show Agent Terminal — no agent shell launched from here is running",
            )
        reason = self._focus_reason(run)
        if reason:
            return ActionState(enabled=False, label=f"Show Agent Terminal — {reason}")
        return ENABLED

    def _show_terminal_for(self, context: Context) -> None:
        step_id = self._focused(context)
        run = self._live_run(step_id) if step_id is not None else None
        if run is not None:
            self._show_terminal(run)

    def _show_terminal(self, run: AgentRun) -> None:
        reason = terminal.focus(read_shell(run))
        if reason:
            self._deps.status.show_status(f"Could not show the agent's terminal — {reason}", 6000)

    def _fill_agent_list(self, menu: QMenu) -> None:
        """Tools ▸ Agent List: every live run as an entry that raises its terminal.

        The rows are data on the layout button's pattern — built fresh each time the menu
        opens — and the browser entry at the bottom renders through the registry. A run
        that cannot be switched to is greyed with its reason, per run: a tmux pane is
        reachable on a desktop whose bare windows are not.
        """
        live = [run for run in self._runs if run.live]
        if not live:
            nothing = menu.addAction("No agents running from this window")
            nothing.setEnabled(False)
        for run in live:
            reason = self._focus_reason(run)
            name = f"Agent on “{self._title_of(run.step_id)}”"
            entry = menu.addAction(f"{name} — {reason}" if reason else name)
            entry.setEnabled(not reason)
            entry.triggered.connect(lambda _checked=False, r=run: self._show_terminal(r))
        menu.addSeparator()
        append_action(menu, self._deps.actions, self._deps.context, "agent_run.show_agents")

    def _can_clear(self, context: Context) -> ActionState:
        step_id = self._focused(context)
        if step_id is None:
            return DISABLED
        if not read(self._deps.library.step(step_id)):
            return ActionState(enabled=False, label="Clear Agent Run — no agent run on this step")
        return ENABLED

    def _clear(self, context: Context) -> None:
        step_id = self._focused(context)
        if step_id is None:
            return
        self._deps.undo.push(SetModuleDataCommand(step_id, MODULE_ID, {}, label="Clear Agent Run"))

    def _focused(self, context: Context) -> StepId | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return step_id
