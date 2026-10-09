"""The agent-run aspect, in the running application: the shells this window launched.

The aspect on the step is written by Run Agent (through the composition root's
``track`` callback) and by the CLI from inside the agent's shell; the canvas reads it
through the composition root's accent translation. What this module adds is the other
half of a launch — **the shell is a peer this window keeps an eye on**:

- A two-second timer, running for the window's life, reads each live run's exit file and
  pid (``runs.settle``). When the shell has ended, the step's state is cleared the way the
  launch was stamped — directly, off the undo stack, with the launch origin — and the
  status bar says how it ended. That write is skipped while the workspace has changed
  underneath: the library watcher adopts the change into the live model first — or, when
  the store cannot reconcile it, falls back to a rebuild whose new module re-adopts its
  runs from the per-user store — and the next tick checks again on a plan this window has
  seen, so the exit is never written over an agent's own last ``dplanner`` call.
- **What a run consumed is never this module's to catch.** The launch writes the run's
  record into the project's ledger and the end marks it (``agent_usage``'s ``aspect.py``);
  the tokens are read back into it by a harvest that anybody may run at any time — the
  wrapper script when the agent exits, and ``agent_usage``'s sweep, which ``deps.ended``
  sets going when this module sees a shell end. A window that was closed, a terminal
  killed on the agent, a ``/tmp`` a reboot emptied: the next sweep reads the same records.
- A status-bar button ("Agent on “X”", "2 agents running") opens the Agents browser —
  View ▸ Agents… does the same — where every run this machine launched is a row with its
  state or outcome, *Show Terminal*, *Reveal* and a dismiss — and, once it has ended, the
  command that picks the agent up again where it stopped, as the wrapper recorded it. **It
  lists the live runs newest first and keeps the ended ones off screen** until *Show ended*
  asks for them, under the live ones, which is also what *Clear ended* waits for; the
  footer counts both either way, so nothing hidden goes unsaid.
- Tools ▸ Agent List is the quick switch: a data child menu listing the live runs, each
  entry raising its terminal. Availability is per run (``terminal.focus_reason`` — a tmux
  pane is reachable on a desktop whose bare windows are not), and a run that cannot be
  switched to is greyed with the reason, in the list, the browser and the Step verb alike.
- **Headless runs are listed beside the shells** (``headless.py``): every project's ledger and
  questions read again whenever their fingerprints move, on the same two-second tick, which
  runs while the window does. Each row's *Follow* and *Open Session* open the default profile's
  terminal on ``dplanner agent follow`` / ``agent open-session`` (``deps.open_terminal``), so the
  window and a person's own terminal run the one verb; *Open Session* on a run that is not over
  asks first, since it takes the run from its playbook. Both are Step-menu verbs too, over
  the step's latest headless run.
- Three Step-menu verbs: *Show Agent Terminal* (the focus provider in ``terminal.py``, greyed
  with the reason when the desktop cannot), *Retry Now* — the step's headless run, parked on
  a usage limit or a block, resumed at once (``dplanner agent retry``'s twin, through the
  Deps) — and *Clear Agent Run*, the window's twin of ``dplanner agent-state clear`` — an edit
  of the user's, so it goes through the undo stack.

Runs live in the user's store (``user_config``), never the plan: a temp directory and a
pid are facts about this machine.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMenu, QWidget

from dplanner.domain import ledger, questions
from dplanner.domain.agents import AgentHarness, harness_by_id
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, StepId, now_stamp
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
from dplanner.framework.widgets import StatusBarButton, confirm
from dplanner.framework.window import StatusHost
from dplanner.framework.window_watch import WatchableRepository
from dplanner.modules.agent_supervisor.follow import follow_argv
from dplanner.modules.agent_supervisor.takeover import elsewhere, open_session_argv
from dplanner.modules.agent_usage.aspect import end, launch_record, words
from dplanner.modules.step_agent_run import headless, terminal
from dplanner.modules.step_agent_run.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    read,
    record_exit,
    record_launch,
)
from dplanner.modules.step_agent_run.browser_dialog import (
    AgentBrowserDialog,
    button_text,
    stage_label,
)
from dplanner.modules.step_agent_run.headless import HeadlessRun, ProjectRuns
from dplanner.modules.step_agent_run.runs import (
    AgentRun,
    describe,
    new_run,
    read_shell,
    settle,
)

POLL_MS = 2000
RUNS_KEY = "runs"
# When *Clear ended* last took the ended headless runs off the list: their records are the
# plan's, so clearing them is a per-user stamp, never a deletion.
CLEARED_KEY = "headless_cleared"
OPEN_SESSION = "Open Session"


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
    # Told once runs have ended: a slot is free, even when the agent had already cleared
    # its state and the plan did not change — what the window's launcher waits on.
    ended: Callable[[], None] = lambda: None
    # Where a step's project keeps its ledger, None for a step or project this store does
    # not hold — where a run's record is written at launch and marked at its end.
    project_dir: Callable[[StepId], Path | None] = lambda _step: None
    # Retry now on the step's parked headless run: why it does not apply ("" when it does),
    # and doing it, as a person — what became of it, or ValueError saying why not.
    retry_refusal: Callable[[StepId], str] = lambda _step: "no headless runs here"
    retry_now: Callable[[StepId], str] = lambda _step: ""
    # Every project's ledger directory: where the headless runs listed beside the shells are.
    project_dirs: Callable[[], list[Path]] = lambda: []
    # The card's playbook phrase for the step's pass ("Review 1/2"), "" for none: what a
    # headless row of the pass's latest run leads with, so the browser and the card agree.
    pass_phrase: Callable[[StepId], str] = lambda _step: ""
    # Open a terminal in a directory on a command (title, project id): why none opened, or "".
    open_terminal: Callable[[Path, str, Sequence[str], str], str] = (
        lambda _directory, _title, _command, _project: "no terminal here"
    )
    # The library the window has open, which a terminal's `dplanner` verb acts on.
    library_path: Path | None = None


class StepAgentRunModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepAgentRunDeps) -> None:
        self._deps = deps
        self._runs: list[AgentRun] = []
        self._timer: QTimer | None = None
        self._button: StatusBarButton | None = None
        self._browser: AgentBrowserDialog | None = None
        self._seen: dict[Path, tuple[object, ...]] = {}
        self._projects: dict[Path, ProjectRuns] = {}
        self._headless: list[HeadlessRun] = []

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
            relist=self.refresh,  # Show ended changes what is listed, not what is known.
            follow=self._follow,
            open_session=self._open_session,
            reveal_step=deps.reveal,
        )
        self._timer = QTimer(self._button)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.check)
        deps.library.module_data_changed.connect(lambda *_a: self.refresh())

        deps.actions.register(
            ActionSpec(
                id="agent.show_terminal",
                label="Show Agent Ter&minal",
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
                id="agent.follow",
                label="&Follow Agent Run",
                menu="Step",
                group="agent",
                order=31,
                tip="Watch the step's headless run in a terminal as it streams — read-only",
                state=lambda context: self._can_headless(context, "Follow Agent Run", follow=True),
                run=lambda context: self._on_latest(context, self._follow),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="agent.open_session",
                label="Open A&gent Session",
                menu="Step",
                group="agent",
                order=32,
                tip="Take the step's headless run's session into a terminal of your own",
                state=lambda context: self._can_headless(context, "Open Agent Session"),
                run=lambda context: self._on_latest(context, self._open_session),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="agent.retry_now",
                label="Retr&y Now",
                menu="Step",
                group="agent",
                order=35,
                tip="Resume the step's headless run now, without waiting for its usage limit"
                " to reset",
                state=self._can_retry,
                run=self._retry,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="agent.clear_run",
                label="Cle&ar Agent Run",
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

    def live(self, step_id: StepId | None = None) -> int:
        """How many runs this window launched are still going — on ``step_id``, or at all."""
        return sum(run.live and step_id in (None, run.step_id) for run in self._runs)

    def track(
        self,
        step_id: StepId,
        shell_file: str,
        exit_file: str,
        harness: str = "",
        session: str = "",
        prompt_chars: int = 0,
        plans_first: bool = False,
        run: str = "",
        workdir: Path | None = None,
    ) -> None:
        """A shell was just spawned on the step: stamp it, write its record into the
        ledger unless the launch already did (Run Agent writes it before the spawn),
        remember it, start watching."""
        deps = self._deps
        record_launch(deps.library, step_id, plans_first)
        project_dir = deps.project_dir(step_id)
        if (
            run
            and workdir is not None
            and project_dir is not None
            and ledger.find(project_dir, run) is None
        ):
            ledger.write(
                project_dir,
                launch_record(
                    run=run,
                    project=deps.library.project_of(step_id).id,
                    step=step_id,
                    harness=harness,
                    directory=workdir,
                    session=session,
                    prompt_chars=prompt_chars,
                ),
            )
        self._runs.append(
            new_run(step_id, shell_file, exit_file, harness, session, prompt_chars, run)
        )
        self._store()
        self.refresh()

    def check(self) -> None:
        """One tick: settle every live run whose shell has ended, and say so.

        The store is asked whether the plan changed underneath only once a run *has*
        ended: that answer is a walk over every plan file, on the GUI thread, and asking
        it every two seconds for its own sake stalled a large library's window for as
        long as the walk took (300 to 500 ms) the whole time an agent ran. Settling a run
        is a handful of stats, so the tick costs nothing until there is an exit to write.
        """
        deps = self._deps
        self._read_headless()
        ended = [
            (index, settled)
            for index, run in enumerate(self._runs)
            if (settled := settle(run)) is not run
        ]
        if not ended:
            self.refresh()
            return
        if deps.repo.changed_underneath():
            return  # The watcher takes the change first; the next tick checks again.
        for index, settled in ended:
            self._runs[index] = settled
            record_exit(deps.library, settled.step_id)
            project_dir = deps.project_dir(settled.step_id)
            if settled.run and project_dir is not None:
                end(project_dir, settled.run, settled.code, settled.ended)
            deps.status.show_status(
                f"Agent on “{self._title_of(settled.step_id)}” {describe(settled, '')}", 6000
            )
        self._store()
        self.refresh()
        deps.ended()  # A slot is free, and what the ended runs consumed is due a read.

    def _forget(self, run: AgentRun) -> None:
        self._runs = [other for other in self._runs if other.key != run.key]
        self._store()
        self.refresh()

    def _clear_ended(self) -> None:
        self._runs = [run for run in self._runs if run.live]
        set_global(MODULE_ID, CLEARED_KEY, now_stamp())
        self._store()
        self._read_headless()
        self.refresh()

    def _store(self) -> None:
        set_global(MODULE_ID, RUNS_KEY, [run.to_json() for run in self._runs])

    def refresh(self) -> None:
        """Say the runs again — the button, and the browser when it is open, which shows
        what each consumed once a harvest has read it. The tick runs while the window does:
        a headless run is started by other processes, and nothing else would notice it."""
        if self._button is None or self._browser is None or self._timer is None:
            return
        self._button.show_text(button_text(self._runs, self._title_of, self._headless))
        if self._browser.isVisible():
            self._refresh_browser()
        if not self._timer.isActive():
            self._timer.start()

    def _refresh_browser(self) -> None:
        assert self._browser is not None
        self._browser.refresh(
            self._runs,
            self._focus_reason,
            self._resume_of,
            self._usage_of,
            headless=self._headless,
            phrase_of=lambda run: self._deps.pass_phrase(run.step),
            harness_label=self._harness_label,
        )

    def _read_headless(self) -> None:
        """Re-read each project whose ledger or questions moved, and list the headless runs
        again — every tick, since how long ago a run last spoke changes while nothing moves."""
        for directory in self._deps.project_dirs():
            stamp = (ledger.fingerprint(directory), questions.fingerprint(directory))
            if stamp != self._seen.get(directory):
                self._seen[directory] = stamp
                self._projects[directory] = headless.read(directory)
        cleared = str(get_global(MODULE_ID, CLEARED_KEY, ""))
        self._headless = headless.listed(
            list(self._projects.values()), self._deps.harnesses, datetime.now(UTC), cleared=cleared
        )

    def _open_browser(self) -> None:
        assert self._browser is not None
        self._read_headless()
        self._browser.show()  # Non-modal: the agents keep working underneath.
        self.refresh()  # The button too: what was just read may be news to it.
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
        session = run.session or self._found_session(run)
        if harness is None or not harness.resume or not session:
            return ""
        command = harness.resume.replace("{session}", session)
        directory = shell.get("dir", "")
        return f'cd "{directory}" && {command}' if directory else command

    def _record_of(self, run: AgentRun) -> ledger.LedgerRecord | None:
        project_dir = self._deps.project_dir(run.step_id)
        if not run.run or project_dir is None:
            return None
        return ledger.find(project_dir, run.run)

    def _found_session(self, run: AgentRun) -> str:
        """The session a harvest found for a CLI that mints its own ids, or ""."""
        record = self._record_of(run)
        return record.session if record is not None else ""

    def _usage_of(self, run: AgentRun) -> str:
        """What the run consumed, as its ledger record says, or "" before it was read."""
        record = self._record_of(run)
        return words(record.tokens) if record is not None and record.agents else ""

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
        followed = [run for run in self._headless if run.live]
        if not live and not followed:
            nothing = menu.addAction("No agents running from this window")
            nothing.setEnabled(False)
        for run in live:
            reason = self._focus_reason(run)
            name = f"Agent on “{self._title_of(run.step_id)}”"
            entry = menu.addAction(f"{name} — {reason}" if reason else name)
            entry.setEnabled(not reason)
            entry.triggered.connect(lambda _checked=False, r=run: self._show_terminal(r))
        for each in followed:
            name = f"Follow “{self._title_of(each.step)}”"
            entry = menu.addAction(
                f"{name} — {each.follow_refusal}" if each.follow_refusal else name
            )
            entry.setEnabled(not each.follow_refusal)
            entry.triggered.connect(lambda _checked=False, r=each: self._follow(r))
        menu.addSeparator()
        append_action(menu, self._deps.actions, self._deps.context, "agent_run.show_agents")

    def _can_clear(self, context: Context) -> ActionState:
        step_id = self._focused(context)
        if step_id is None:
            return DISABLED
        if not read(self._deps.library.step(step_id)):
            return ActionState(enabled=False, label="Clear Agent Run — no agent run on this step")
        return ENABLED

    def _can_retry(self, context: Context) -> ActionState:
        step_id = self._focused(context)
        if step_id is None:
            return DISABLED
        refused = self._deps.retry_refusal(step_id)
        return ActionState(enabled=False, label=f"Retry Now — {refused}") if refused else ENABLED

    def _retry(self, context: Context) -> None:
        step_id = self._focused(context)
        if step_id is None:
            return
        try:
            said = self._deps.retry_now(step_id)
        except (LookupError, ValueError) as error:
            said = f"Could not retry the run — {error}"
        self._deps.status.show_status(said, 6000)

    def _clear(self, context: Context) -> None:
        step_id = self._focused(context)
        if step_id is None:
            return
        self._deps.undo.push(SetModuleDataCommand(step_id, MODULE_ID, {}, label="Clear Agent Run"))

    # -- headless runs ---------------------------------------------------------------------------

    def _follow(self, run: HeadlessRun) -> None:
        try:
            said = self.follow_run(run.project_dir, run.run)
        except (LookupError, ValueError) as refused:
            said = f"Cannot follow the run — {refused}"
        self._deps.status.show_status(said, 6000)

    def follow_run(self, project_dir: Path, run: str) -> str:
        """Open a terminal following the run — ``dplanner agent follow``, read-only — and say
        so; ``ValueError`` or ``LookupError`` says why not. What the browser's row, the Step
        menu and the Control Centre's question card all do."""
        record = ledger.find(project_dir, run)
        if record is None:
            raise LookupError(f"run {run} is no longer in the ledger")
        if refused := elsewhere(record):
            raise ValueError(refused)
        argv = follow_argv(self._deps.library_path, project_dir, run)
        title = self._title_of(record.step)
        if reason := self._open_on(
            project_dir, record.step, record.directory, f"Follow {title}", argv
        ):
            raise ValueError(f"no terminal opened — {reason}")
        return f"Following the run on “{title}” in a terminal"

    def _open_session(self, run: HeadlessRun) -> None:
        """Open a terminal taking the run's session: ``dplanner agent open-session``, which
        fences a run that is not over as taken over — asked first, since the run is then no
        longer its playbook's — and releases its step from the squad holding it."""
        deps = self._deps
        if run.open_refusal:
            deps.status.show_status(f"Cannot open the session — {run.open_refusal}", 6000)
            return
        title = self._title_of(run.step)
        if run.live and not confirm(
            deps.parent, OPEN_SESSION, _taking(title, run), verb=OPEN_SESSION
        ):
            return
        argv = open_session_argv(deps.library_path, run.project_dir, run.run)
        if reason := self._open_on(
            run.project_dir, run.step, run.directory, f"Session {title}", argv
        ):
            deps.status.show_status(f"No terminal opened — {reason}", 8000)

    def _open_on(
        self, project_dir: Path, step_id: str, worked_in: str, title: str, argv: Sequence[str]
    ) -> str:
        """Open a terminal on ``argv`` where the run worked — its project's directory when that
        is gone — and answer why none opened, or ""."""
        deps = self._deps
        directory = Path(worked_in) if worked_in and Path(worked_in).is_dir() else project_dir
        project = deps.library.project_of(step_id).id if deps.library.has(step_id) else ""
        return deps.open_terminal(directory, title, argv, project)

    def _latest(self, step_id: StepId) -> HeadlessRun | None:
        """The step's latest headless run, from its project's records as last read."""
        directory = self._deps.project_dir(step_id)
        if directory is None:
            return None
        project = self._projects.get(directory) or headless.read(directory)
        return headless.latest_on(project, step_id, self._deps.harnesses)

    def _can_headless(self, context: Context, verb: str, *, follow: bool = False) -> ActionState:
        step_id = self._focused(context)
        if step_id is None:
            return DISABLED
        run = self._latest(step_id)
        if run is None:
            return ActionState(enabled=False, label=f"{verb} — no headless run on this step")
        refused = run.follow_refusal if follow else run.open_refusal
        return ActionState(enabled=False, label=f"{verb} — {refused}") if refused else ENABLED

    def _on_latest(self, context: Context, act: Callable[[HeadlessRun], None]) -> None:
        step_id = self._focused(context)
        run = self._latest(step_id) if step_id is not None else None
        if run is not None:
            act(run)

    def _harness_label(self, harness_id: str) -> str:
        harness = harness_by_id(self._deps.harnesses, harness_id)
        return harness.label if harness is not None else harness_id

    def _focused(self, context: Context) -> StepId | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return step_id


def _taking(title: str, run: HeadlessRun) -> str:
    """What *Open Session* on a run that is not over does, asked before it does it."""
    stage = stage_label(run.stage) or "headless"
    return (
        f"The {stage.lower()} run on “{title}” is the playbook's until you take it. Opening its"
        " session fences the run as taken over by you, so nothing resumes it by itself again,"
        " and releases the step from the squad holding it. The step is yours from here."
    )
