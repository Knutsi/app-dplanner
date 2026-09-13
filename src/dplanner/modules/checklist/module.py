"""*Tools ▸ Setup Checklist…*, and the one greeting a new machine gets.

The rows are every module's; this module owns the surface, the two per-user facts and the
count the menu entry carries.

**What opens it at start.** Once on a machine DPlanner has never greeted — whatever the
state, because a setup surface that only appears when something is wrong is one nobody ever
sees working — and afterwards only while the person left *"open this at start"* ticked and
something *required* is missing. Nothing else raises it: DESIGN.md's principle 3 keeps a
background fact out of a modal, and every advisory row is said where it bites instead. It
replaced the missing-gh box, which DESIGN.md had already forbidden.

**Only the required checks are probed at start**, which is what ``required`` costs a
machine: ``which("git")`` and one ``git --version``, and the installer's reader, which runs
no subprocess at all. No network, no ``gh auth status``, no ``az`` on a launch.

**The count in the menu entry is read, never probed.** A state callback runs on every
context change and may not shell out, so it reads the last sweep this module kept and the
module calls ``context.refresh()`` when a new one lands — the theme-toggle pattern.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from dplanner.cli.checklist import MachineCheck, Reading
from dplanner.framework.action_registry import ActionRegistry, ActionSpec, ActionState
from dplanner.framework.context import Context, ContextService
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.checklist.dialog import ChecklistDialog, Preferences

MODULE_ID = "checklist"
GREETED_KEY = "greeted"
AT_START_KEY = "show_when_missing"
MUTED_KEY = "muted"
LABEL = "&Setup Checklist"
START_TASK_KEY = "checklist.start"

# One greeting per process, however many workspaces get opened — a workspace switch re-runs
# every module's register(), and the notice this replaced learned that the hard way.
_greeted_this_process = False


def greeted() -> bool:
    return bool(get_global(MODULE_ID, GREETED_KEY, False))


def set_greeted() -> None:
    set_global(MODULE_ID, GREETED_KEY, True)


def at_start() -> bool:
    """On unless the person turned it off: a machine missing something required should keep
    saying so, and the one who has decided to live with it says so once."""
    return bool(get_global(MODULE_ID, AT_START_KEY, True))


def set_at_start(on: bool) -> None:
    set_global(MODULE_ID, AT_START_KEY, bool(on))


def muted() -> frozenset[str]:
    """The checks the person has asked not to be warned about, by id.

    Muting changes what nags and never what is true: the row still shows and still says
    what it found, and ``dplanner checklist show`` — the machine's truth, which an agent
    gates on — never reads this at all.
    """
    stored = get_global(MODULE_ID, MUTED_KEY, [])
    return frozenset(str(one) for one in stored) if isinstance(stored, list) else frozenset()


def set_muted(check_id: str, on: bool) -> None:
    kept = set(muted())
    kept.add(check_id) if on else kept.discard(check_id)
    set_global(MODULE_ID, MUTED_KEY, sorted(kept))


@dataclass(frozen=True)
class ChecklistDeps:
    actions: ActionRegistry
    context: ContextService
    tasks: TaskService
    parent: QWidget
    # Every module's rows, assembled by the composition root — the same tuple the
    # ``checklist show`` verb reads.
    checks: Callable[[], Sequence[MachineCheck]]


class ChecklistModule:
    id = MODULE_ID

    def __init__(self, deps: ChecklistDeps) -> None:
        self._deps = deps
        self._checks: tuple[MachineCheck, ...] = ()
        self._readings: dict[str, Reading] = {}
        self._runner: TaskRunner | None = None

    def register(self) -> None:
        self._checks = tuple(self._deps.checks())
        self._deps.actions.register(
            ActionSpec(
                id="checklist.show",
                label=f"{LABEL}…",
                menu="Tools",
                group="install",
                order=20,
                tip="What this machine has of what DPlanner needs, and how to get the rest",
                run=self._run,
                state=self._state,
            )
        )
        # Deferred past the window's show, like the notice it replaced: the window is the
        # context object, so a build closed before the turn comes raises nothing over a
        # deleted window.
        window = self._deps.parent
        QTimer.singleShot(0, window, self._at_start)

    # -- the menu entry ----------------------------------------------------------------

    def _state(self, _context: Context) -> ActionState:
        """The label carries how many required rows are unhappy — the menu bar paints no
        glyph, so a count in the words is the only mark it can wear there."""
        missing = self.missing()
        return ActionState(label=f"{LABEL} ({missing})…" if missing else f"{LABEL}…")

    def missing(self) -> int:
        """Required rows the last sweep found wanting, minus the ones the person asked not
        to be warned about. Read; nothing is probed here."""
        silent = muted()
        return sum(
            1
            for check in self._checks
            if check.required
            and check.id not in silent
            and check.id in self._readings
            and not self._readings[check.id].ok
        )

    # -- opening ------------------------------------------------------------------------

    def _run(self, _context: Context) -> None:
        self._open(greeting=False)

    def _open(self, *, greeting: bool) -> ChecklistDialog:
        set_greeted()
        dialog = ChecklistDialog(
            self._checks,
            self._deps.tasks,
            self._remedy,
            self._deps.parent,
            prefs=Preferences(
                at_start=at_start(),
                muted=muted(),
                on_at_start=set_at_start,
                on_mute=set_muted,
            ),
            greeting=greeting,
        )
        # A bound method, never a lambda closing over the dialog: the connection lives on
        # the dialog, and a lambda holding it back would be a cycle for no reason.
        dialog.settled.connect(self._took)
        dialog.open()  # Never exec(): a nested modal loop at startup deadlocks a test run.
        return dialog

    def _remedy(self, action_id: str) -> None:
        self._deps.actions.run(action_id, self._deps.context.current())

    # -- the start-up sweep -------------------------------------------------------------

    def _at_start(self) -> None:
        """Probe the required rows off the GUI thread, then decide whether to say anything."""
        global _greeted_this_process
        if _greeted_this_process:
            return
        _greeted_this_process = True
        if not greeted():
            self._open(greeting=True)  # A machine we have never met, whatever it has.
            return
        if not at_start():
            return
        # A muted check is not probed at all: the only thing a start-up sweep decides is
        # whether to say something, and this one has been told not to.
        silent = muted()
        required = [check for check in self._checks if check.required and check.id not in silent]
        if not required:
            return
        self._runner = TaskRunner(self._deps.tasks, parent=self._deps.parent)
        self._runner.failed.connect(lambda _error: None)  # A failed probe says nothing here.
        answers: dict[str, Reading] = {}

        def body() -> None:
            for check in required:
                answers[check.id] = check.probe()

        def done(busy: bool) -> None:
            if busy:
                return
            self._took(answers)
            if any(not reading.ok for reading in answers.values()):
                self._open(greeting=False)

        self._runner.busy_changed.connect(done)
        self._runner.run("Checking this machine", body, key=START_TASK_KEY)

    def _took(self, readings: dict[str, Reading]) -> None:
        """Keep what a sweep found, and let the menu entry's count follow it."""
        self._readings.update(readings)
        self._deps.context.refresh()
