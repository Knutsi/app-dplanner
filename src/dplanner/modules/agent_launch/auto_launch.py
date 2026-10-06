"""The window launches what the plan made due — on its own, once, within the agent cap.

What is due, and the claim that says it was launched, are headless (``due.py``): the
composition root hands them over as :class:`Due` records read with the runs this window is
watching, and this module only reacts. Only a window can launch, because the profiles, the
terminals and the cap are this desk's settings; the terminal says what became due.

**Level-triggered, never edge-triggered.** :class:`AutoLauncher` does not listen for "A3
moved to review" — the window may have been closed when it happened, or adopt three such
changes in one tick. It re-derives what is due from the plan after every change of any
origin, when a run ends, when the day turns and once at start, and launches what it finds.
A step is launched once because its claim is written the moment its shell opens: the run
stamp and in progress for what auto-progress made due, the round's stamp for a turn — so the
very next pass, another window or the terminal reads it as no longer due.

**A launch is an external effect, so its intent is written first** (``intents.py``): before
the shell is spawned, beside the lock, and forgotten only once its step reads no longer due
in a plan that is on disk. An intent a pass finds left over is a launch a crash interrupted,
reconciled before anything else is launched: a shell that started is claimed, one that never
did is refused for a person — neither is launched again. The refused intent stays, so a
window built later refuses it too (its shell may only be slow to start), until somebody
edits that step: that is the person answering, and the intent goes with the refusal.

**It never writes over a plan it has not seen.** While the plan changed underneath and is
not taken in yet the pass stands down, and the library watcher's ``settled`` hook, not only
a model signal, wakes it again. Each step is re-read from the live model just before its
shell opens, and past *Max agents* live runs the rest wait for a run to end.

**One window per library on this machine launches** — the holder of a :class:`LaunchLock`
under the config directory, taken while *Agent profiles ▸ When a step becomes due* is on.
The lock belongs to the session rather than the window, because a reload builds the new
window before it discards the old one, and the new one must not find itself locked out.

``docs/architecture/agents.md``'s *Auto-progress is launched by the window* has the reasoning,
including what two machines can still race on.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QLockFile

from dplanner.domain.model import Step, StepId
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.framework.debounce import Debounced
from dplanner.framework.notices import Notice
from dplanner.framework.user_config import library_scope
from dplanner.modules.agent_launch.due import Due, claim
from dplanner.modules.agent_launch.intents import LaunchIntent, LaunchIntents
from dplanner.modules.agent_launch.settings_page import auto_launch, max_agents
from dplanner.modules.step_agent_run.aspect import asks_person
from dplanner.modules.step_agent_run.aspect import read as run_state
from dplanner.planning.kinds import key_of

if TYPE_CHECKING:
    from dplanner.modules.agent_launch.module import AgentLaunchDeps

NOTICE_ID = "agent.auto_launch"
ANOTHER_WINDOW = "another DPlanner window on this library launches them"
INTERRUPTED = "a launch on it was interrupted before its shell started — Run Agent starts it"


class LaunchLock:
    """Whether this window launches for its library: a ``QLockFile`` under the config
    directory, held from the first pass the switch is on until it goes off.

    Stale only when the process holding it is gone (``setStaleLockTime(0)``: Qt then asks
    whether the pid, its program and the boot are still the ones that wrote it), so a
    window that crashed never locks the next one out and one that is merely quiet keeps
    its hold however long nothing is due.

    ``intents`` are written beside it, and only by its holder.
    """

    def __init__(self, path: Path, intents: LaunchIntents) -> None:
        self._path = path
        self.intents = intents
        self._file: QLockFile | None = None

    def take(self) -> str:
        """Hold it: "" when this window launches, else why not."""
        if self._file is not None:
            return ""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return f"cannot write the launch lock in {self._path.parent} — {error.strerror}"
        lock = QLockFile(str(self._path))
        lock.setStaleLockTime(0)
        if lock.tryLock(0):
            self._file = lock
            return ""
        if lock.error() == QLockFile.LockError.LockFailedError:
            return ANOTHER_WINDOW
        return f"cannot write the launch lock in {self._path.parent}"

    def release(self) -> None:
        if self._file is not None:
            self._file.unlock()
            self._file = None


class LaunchLocks:
    """This machine's launch locks, one per library — built once per session, so the window
    a reload builds is handed the very lock the old one held."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._each: dict[Path, LaunchLock] = {}

    def for_library(self, library_path: Path) -> LaunchLock:
        key = Path(library_path).expanduser().resolve()
        if key not in self._each:
            scope = library_scope(key)
            self._each[key] = LaunchLock(
                self._directory / f"{scope}.lock", LaunchIntents(self._directory / scope)
            )
        return self._each[key]


class AutoLauncher:
    """The settled pass that launches what is due. ``launch`` is the agent module's
    unattended launch: "" when a shell opened, else why not."""

    def __init__(self, deps: "AgentLaunchDeps", launch: Callable[[Due], str]) -> None:
        self._deps = deps
        self._launch = launch
        # Zero: once per event-loop turn — a burst adopted in one tick is one pass, and a pass
        # always runs after the adoption that woke it — and never held behind a modal, which
        # a dialog left open would otherwise make a launcher that never launches.
        self._settle = Debounced(self._pass, 0, parent=deps.parent, service=deps.debounce)
        self.settle: Callable[[], None] = self._settle.trigger
        # Why each step could not be launched, until that step changes or the switch or the
        # profiles do — a refusal repeated every settle would be a retry nobody asked for.
        self._refused: dict[StepId, str] = {}
        # What this window launched unattended, for the notice while its agent waits on a
        # person; forgotten once it does not.
        self._launched: set[StepId] = set()
        # What was last said about the due steps held back, so it is said once per change.
        self._held_back: tuple[StepId, ...] = ()
        self._busy = False
        self._again = False

    def start(self) -> None:
        """What is due is read off statuses, run stamps, flags, rounds and edges — module data,
        edges and structure, of any origin. A title or prose never makes a step due, so an
        edit of either only forgets that step's refusal: typing costs no pass."""
        library = self._deps.library
        library.structure_changed.connect(lambda node_id, _o: self._changed(node_id))
        library.edges_changed.connect(lambda step_id, _o: self._changed(step_id))
        library.module_data_changed.connect(lambda node_id, _m, _o: self._changed(node_id))
        library.field_changed.connect(lambda node_id, _f, _o: self._edited(node_id))
        library.text_edited.connect(lambda edit, _o: self._edited(edit.node_id))
        self._deps.clock.day_changed.connect(lambda _day: self.settle())
        self.settle()  # Once at start: what became due while no window was open.

    def reconsider(self) -> None:
        """The switch or the profiles changed: every refusal may be answered now."""
        self._refused.clear()
        self.settle()

    def holder_words(self) -> str:
        """Why this window does not launch although the switch is on, or "" — taking the
        lock if it is free, since the switch being on means this window should."""
        lock = self._deps.launch_lock
        if lock is None or not auto_launch():
            return ""
        return lock.take()

    # -- the pass ------------------------------------------------------------------------------

    def _changed(self, node_id: str) -> None:
        self._answered(node_id)
        self.settle()

    def _edited(self, node_id: str) -> None:
        """A step's words changed — a briefing written, say: a refusal may be answered."""
        if self._answered(node_id):
            self.settle()

    def _answered(self, step_id: str) -> bool:
        """Forget the refusal on ``step_id`` — and an interrupted launch's intent with it,
        since a person touching the step is the retry it waited for. True when there was one.

        A change made while a pass runs is the pass's own claim, never an answer: taken for
        one, a late shell's claim would drop its intent before the claim reached disk."""
        if self._busy:
            return False
        reason = self._refused.pop(step_id, None)
        if reason == INTERRUPTED and (lock := self._deps.launch_lock) is not None:
            for intent in lock.intents.pending():
                if intent.step == step_id:
                    lock.intents.drop(intent.run)
        return reason is not None

    def _pass(self) -> None:
        # The claims written below re-enter here inline when the debounce runs immediately
        # (the suite); the flag runs the pass once more rather than nesting it.
        if self._busy:
            self._again = True
            return
        self._busy = True
        try:
            self._again = True
            while self._again:
                self._again = False
                self._once()
        finally:
            self._busy = False

    def _once(self) -> None:
        deps = self._deps
        self._show_notice()
        lock = deps.launch_lock
        if lock is None or deps.repo is None:
            return  # A build with nowhere to hold a lock never launches.
        if not auto_launch():
            lock.release()
            self._refused.clear()
            self._held_back = ()
            return
        if lock.take():
            return
        if leftover := lock.intents.pending():
            if deps.repo.changed_underneath():
                return  # The watcher takes the change in first, and wakes this pass again.
            self._reconcile(lock.intents, leftover)
        candidates = [due for due in deps.due() if due.step_id not in self._refused]
        limit = max_agents()
        # The cap before the plan-file walk: while it holds, every burst would pay the walk.
        if candidates and deps.live_runs() >= limit:
            self._hold_back(candidates, f"wait for an agent slot — {limit} of {limit} running")
            return
        if candidates and deps.repo.changed_underneath():
            self._hold_back(candidates, "wait — the plan changed on disk and is not taken in yet")
            return
        self._held_back = ()
        launched: list[StepId] = []
        refused: list[StepId] = []
        for index, due in enumerate(candidates):
            if deps.live_runs() >= limit:
                self._hold_back(
                    candidates[index:], f"wait for an agent slot — {limit} of {limit} running"
                )
                break
            # Re-read from the live model just before the shell opens: the launch before
            # this one wrote its claim, and nothing may be launched on a stale answer.
            fresh = next((each for each in deps.due() if each.step_id == due.step_id), None)
            if fresh is None:
                continue
            reason = self._launch(fresh)
            if reason:
                self._refused[fresh.step_id] = reason
                refused.append(fresh.step_id)
            else:
                launched.append(fresh.step_id)
                self._launched.add(fresh.step_id)
        if launched and deps.flush():  # The claims on disk now, not after autosave's pause.
            self._forget_settled(lock.intents)
        self._say(launched, refused)
        self._show_notice()

    def _reconcile(self, intents: LaunchIntents, leftover: list[LaunchIntent]) -> None:
        """Settle launches a crash interrupted: claim a step whose shell started, refuse one
        whose shell never did — and launch neither again. Forgotten once the claims are on
        disk; until then the next pass reconciles them again, which finds them claimed. One
        refused stays recorded, and is refused again by every pass until a person answers it."""
        deps = self._deps
        due = {each.step_id: each for each in deps.due()}
        adopted: list[StepId] = []
        refused: list[StepId] = []
        for intent in leftover:
            found = due.get(intent.step)
            if found is None:
                continue  # Claimed before the crash, or no longer due.
            if intent.started:
                claim(deps.library, found, deps.clock.today())
                adopted.append(found.step_id)
                self._refused.pop(found.step_id, None)
            elif self._refused.get(found.step_id) != INTERRUPTED:
                self._refused[found.step_id] = INTERRUPTED
                refused.append(found.step_id)
        if deps.flush():
            self._forget_settled(intents)
        self._say([], refused)
        if adopted:
            deps.status.show_status(
                f"Claimed {self._keys(adopted)}: its agent started before the window closed", 8000
            )

    def _forget_settled(self, intents: LaunchIntents) -> None:
        """Forget each intent whose step no longer reads due — its claim is on disk, or it
        was settled otherwise. One still due is unresolved, and stays."""
        due = {each.step_id for each in self._deps.due()}
        for intent in intents.pending():
            if intent.step not in due:
                intents.drop(intent.run)

    def _hold_back(self, held: list[Due], why: str) -> None:
        ids = tuple(due.step_id for due in held)
        if ids == self._held_back:
            return
        self._held_back = ids
        named = _listed([self._named(step_id) for step_id in ids])
        verb = "is due and has to" if len(ids) == 1 else "are due and have to"
        self._deps.status.show_status(f"{named} {verb} {why}", 8000)

    def _say(self, launched: list[StepId], refused: list[StepId]) -> None:
        said = []
        if len(launched) == 1:
            said.append(f"Launched the agent on {self._named(launched[0])}, which was due")
        elif launched:
            said.append(f"Launched {len(launched)} agents on due steps: {self._keys(launched)}")
        for step_id in refused:
            said.append(
                f"Could not launch the agent on {self._named(step_id)} — {self._refused[step_id]}"
            )
        if said:
            self._deps.status.show_status(" · ".join(said), 8000)

    # -- the notice ----------------------------------------------------------------------------

    def _show_notice(self) -> None:
        """One notice while an agent this window launched unattended waits on a person — a
        plan to approve, a question to answer — since nobody clicked, and nobody may be
        looking at its terminal."""
        deps = self._deps
        library = deps.library
        self._launched = {
            step_id
            for step_id in self._launched
            if library.has(step_id) and asks_person(library.step(step_id))
        }
        waiting = [step.id for step in self._in_order(self._launched)]
        if deps.notices is None:
            return
        if not waiting:
            deps.notices.clear_notice(NOTICE_ID)
            return
        if len(waiting) == 1:
            step = library.step(waiting[0])
            asks = (
                "has a question for you in its terminal"
                if run_state(step) == "needs-input"
                else "started in plan mode and waits for you to approve its plan"
            )
            context = Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step.id)),)})
            notice = Notice(
                id=NOTICE_ID,
                words=f"The agent on {self._named(step.id)} {asks}",
                tone="warn",
                action="Show Terminal",
                tip="Bring its terminal to the front",
                act=lambda: deps.actions.run("agent.show_terminal", context),
            )
        else:
            notice = Notice(
                id=NOTICE_ID,
                words=f"{len(waiting)} agents launched here wait for you · {self._keys(waiting)}",
                tone="warn",
                action="Show Agents",
                tip="The agents this window launched, and a way to each terminal",
                act=lambda: deps.actions.run("agent_run.show_agents", deps.context.current()),
            )
        deps.notices.show_notice(notice)

    # -- words ---------------------------------------------------------------------------------

    def _in_order(self, step_ids: set[StepId]) -> list[Step]:
        library = self._deps.library
        return [
            step for project in library.projects for step in project.steps if step.id in step_ids
        ]

    def _named(self, step_id: StepId) -> str:
        library = self._deps.library
        if not library.has(step_id):
            return "a deleted step"
        step = library.step(step_id)
        return f"{key_of(step)} “{step.title or 'Untitled step'}”".strip()

    def _keys(self, step_ids: list[StepId]) -> str:
        library = self._deps.library
        return ", ".join(
            key_of(library.step(step_id)) or "?" for step_id in step_ids if library.has(step_id)
        )


def _listed(words: list[str]) -> str:
    if len(words) <= 2:
        return " and ".join(words)
    return f"{', '.join(words[:-1])} and {words[-1]}"
