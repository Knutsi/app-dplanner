"""The window's half of *an agent is at work on this plan*.

An agent working a plan through the CLI is a second writer, and the window has always
taken its changes in silently — which is right until the developer is editing the same
step, and then a question nobody wanted appears in the middle of their sentence. The fix
is to make the other writer **visible**: the agent says what it is doing
(``dplanner agent-work …``, ``domain/at_work.py``) and this module puts it over the
window's content for as long as it holds.

Three things it does, and no more:

- **Polls the board** every :data:`POLL_MS` and stands **one notice for every claim**: an
  amber band across the window with the turning arc, one agent's own words when there is
  one and a count of them when there are several (*3 agents are at work on DPlanner
  changes 2 · S4, F7, S23*), and everything they counted filling that band with the
  percentage beside the verb. One band however many agents: four stacked bands were four
  things to read past, and a person needs to know *that* agents are writing before *which*.
  A click on the band opens :class:`~dplanner.modules.agent_at_work.at_work_dialog.AtWorkDialog`,
  where each agent is said in full. A claim that has lapsed is simply not there —
  ``domain/at_work.py`` has why.
- **Offers the ways out a person needs**: *Clear* on the band drops every claim it stands
  for, and the dialog clears one at a time. Not a plan edit and not undoable — it is this
  machine's bookkeeping, like dismissing a launched run.
- **Answers "is an agent at work on this project?"** for whoever must know. The library
  watcher is the one asker: while an agent is at work it leaves its conflict question in
  the notice bar instead of raising a modal over somebody who is already being asked to
  keep their hands still.

It writes nothing. The claim belongs to the agent, and the only window-side write is a
person clearing one — which is why there is no *Start* verb here and never should be.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from dplanner.domain.at_work import (
    AtWork,
    AtWorkBoard,
    claim_words,
    claims_words,
    combined_fraction,
)
from dplanner.domain.model import Library, ProjectId, Step, StepId
from dplanner.framework.notices import Notice
from dplanner.framework.window import NoticeHost
from dplanner.modules.agent_at_work.at_work_dialog import AtWorkDialog

MODULE_ID = "agent_at_work"
NOTICE_ID = MODULE_ID  # One notice, whoever is at work.

# The workspace watcher's cadence, and for the same reason: an agent's change arrives
# through that poll, so the banner and the change it explains land in the same breath.
POLL_MS = 2000

CLEAR = "Clear"
CLEAR_TIP = (
    "Drop every claim — an agent still working makes a new one the next time it says what"
    " it is doing"
)
OPEN_TIP = "Show every agent at work"
ELSEWHERE = "A project this window does not have"


@dataclass(frozen=True)
class AgentAtWorkDeps:
    board: AtWorkBoard
    notices: NoticeHost
    library: Library  # Names the project and the step a claim is on.
    parent: QWidget  # Owns the timer and the dialog: a discarded build stops polling.
    # Selects a step in its project — ``steps.reveal``, run against the row's step.
    reveal: Callable[[StepId], None]
    # The step's key as every surface prints it — the root's one rule, handed down.
    key_of: Callable[[Step], str] | None = None


class AgentAtWorkModule:
    id = MODULE_ID

    def __init__(self, deps: AgentAtWorkDeps) -> None:
        self._deps = deps
        self._showing = False
        self._dialog: AtWorkDialog | None = None  # Built the first time the band is clicked.
        self._timer = QTimer(deps.parent)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.refresh)

    def register(self) -> None:
        self._timer.start()
        self.refresh()

    # -- what the window shows -------------------------------------------------------------

    def refresh(self) -> None:
        """Read the board and say what stands. Cheap by construction: a notice equal to the
        one already on screen redraws nothing, so an idle poll costs a directory listing."""
        claims = self._deps.board.claims()
        if claims:
            self._deps.notices.show_notice(self._notice(claims))
        elif self._showing:
            self._deps.notices.clear_notice(NOTICE_ID)
        self._showing = bool(claims)
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.refresh([(claim, self._row_title(claim, claims)) for claim in claims])

    def at_work_words(self, project_id: ProjectId) -> str:
        """What to tell somebody who is about to interrupt work on this project — "" when
        no agent is at work on it. The library watcher's one question."""
        claims = self._deps.board.claims(project_id)
        return "; ".join(claim_words(claim, step=self._step_key(claim)) for claim in claims)

    def dialog(self) -> AtWorkDialog | None:
        """The dialog, once the band has been clicked — what a test reads."""
        return self._dialog

    # -- the pieces ------------------------------------------------------------------------

    def _notice(self, claims: list[AtWork]) -> Notice:
        return Notice(
            id=NOTICE_ID,
            words=claims_words(claims, self._project_title, self._step_key),
            # Warn rather than busy because the band is not about *our* work running — it
            # is asking the developer to keep their hands off a plan somebody else is
            # writing, which is a caution, and amber is what this application says that in.
            # The arc beside the words is what says *running*.
            tone="warn",
            busy=True,
            fraction=combined_fraction(claims),
            action=CLEAR,
            tip=CLEAR_TIP,
            act=lambda: self._clear_all(claims),
            open=self._open_dialog,
            open_tip=OPEN_TIP,
        )

    def _open_dialog(self) -> None:
        """Non-modal, like the Agents browser: the agents keep working underneath, and the
        poll keeps the rows current while it is open."""
        if self._dialog is None:
            self._dialog = AtWorkDialog(
                self._deps.parent,
                reveal=lambda claim: self._deps.reveal(claim.step),
                clear=self._clear,
                clear_all=lambda: self._clear_all(self._deps.board.claims()),
            )
        self._dialog.show()
        self.refresh()
        self._dialog.raise_()

    def _clear(self, claim: AtWork) -> None:
        self._deps.board.end(claim.project, claim.step)
        self.refresh()

    def _clear_all(self, claims: list[AtWork]) -> None:
        for claim in claims:
            self._deps.board.end(claim.project, claim.step)
        self.refresh()

    def _row_title(self, claim: AtWork, claims: list[AtWork]) -> str:
        """What a row is about: the step by key and title, or the project for a claim on the
        plan as a whole — and the project ahead of the step when the rows span several."""
        project = self._project_title(claim) or ELSEWHERE
        if not claim.step:
            return project
        step = self._step_title(claim)
        if len({other.project for other in claims}) > 1:
            return f"{project} · {step}"
        return step

    def _project_title(self, claim: AtWork) -> str:
        """As the library knows it — "" for a project this window does not have, which is
        every claim made against another library on the same machine."""
        library = self._deps.library
        if not library.has(claim.project):
            return ""
        return str(getattr(library.node(claim.project), "title", ""))

    def _step_key(self, claim: AtWork) -> str:
        key_of = self._deps.key_of
        if not claim.step or key_of is None:
            return ""
        try:
            return key_of(self._deps.library.step(claim.step))
        except KeyError:
            return ""  # A step this library does not have, or one since deleted.

    def _step_title(self, claim: AtWork) -> str:
        """The step's key and title, as a row names it — "A step …" when it is not here."""
        try:
            title = self._deps.library.step(claim.step).title
        except KeyError:
            return "A step this window does not have"
        return f"{self._step_key(claim)} {title}".strip()
