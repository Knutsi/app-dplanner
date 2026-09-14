"""The window's half of *an agent is at work on this plan*.

An agent working a plan through the CLI is a second writer, and the window has always
taken its changes in silently — which is right until the developer is editing the same
step, and then a question nobody wanted appears in the middle of their sentence. The fix
is to make the other writer **visible**: the agent says what it is doing
(``dplanner agent-work …``, ``domain/at_work.py``) and this module puts it over the
window's content for as long as it holds.

Three things it does, and no more:

- **Polls the board** every :data:`POLL_MS` and shows one standing notice per claim: the
  turning arc while the agent reads as at work, the words the agent wrote, its own count
  when it offered one, and when it was last heard from. A claim that has gone quiet keeps
  its row and changes its words — *was at work … last heard 22 minutes ago* — because a
  banner that vanished would be a guess about a process we cannot see.
- **Offers the one way out a person needs**: *Clear* drops a claim an agent left behind.
  Not a plan edit and not undoable — it is this machine's bookkeeping, like dismissing a
  launched run.
- **Answers "is an agent at work on this project?"** for whoever must know. The library
  watcher is the one asker: while an agent is at work it leaves its conflict question in
  the status bar instead of raising a modal over somebody who is already being asked to
  keep their hands still.

It writes nothing. The claim belongs to the agent, and the only window-side write is a
person clearing one — which is why there is no *Start* verb here and never should be.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from dplanner.domain.at_work import AtWork, AtWorkBoard, claim_words, fraction, is_fresh
from dplanner.domain.model import Library, ProjectId, Step
from dplanner.framework.notices import Notice
from dplanner.framework.window import NoticeHost

MODULE_ID = "agent_at_work"

# The workspace watcher's cadence, and for the same reason: an agent's change arrives
# through that poll, so the banner and the change it explains land in the same breath.
POLL_MS = 2000

CLEAR = "Clear"
CLEAR_TIP = (
    "Drop this claim — an agent still working makes a new one the next time it says"
    " what it is doing"
)


@dataclass(frozen=True)
class AgentAtWorkDeps:
    board: AtWorkBoard
    notices: NoticeHost
    library: Library  # Names the project and the step a claim is on.
    parent: QWidget  # Owns the timer: a discarded build stops polling.
    # The step's key as every surface prints it — the root's one rule, handed down.
    key_of: Callable[[Step], str] | None = None


class AgentAtWorkModule:
    id = MODULE_ID

    def __init__(self, deps: AgentAtWorkDeps) -> None:
        self._deps = deps
        self._showing: dict[str, AtWork] = {}
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
        claims = {self._notice_id(claim): claim for claim in self._deps.board.claims()}
        for gone in set(self._showing) - set(claims):
            self._deps.notices.clear_notice(gone)
        for notice_id, claim in claims.items():
            self._deps.notices.show_notice(self._notice(notice_id, claim))
        self._showing = claims

    def at_work_words(self, project_id: ProjectId) -> str:
        """What to tell somebody who is about to interrupt work on this project — "" when
        no agent reads as at work on it. The library watcher's one question."""
        claims = self._deps.board.at_work(project_id)
        if not claims:
            return ""
        return "; ".join(claim_words(claim, step=self._step_key(claim)) for claim in claims)

    # -- the pieces ------------------------------------------------------------------------

    def _notice(self, notice_id: str, claim: AtWork) -> Notice:
        fresh = is_fresh(claim)
        return Notice(
            id=notice_id,
            words=claim_words(claim, self._project_title(claim), self._step_key(claim)),
            # Busy while the agent is at work, plain information once it has gone quiet:
            # the tone is the reading, and the reading is the last sign of life.
            tone="busy" if fresh else "info",
            busy=fresh,
            fraction=fraction(claim),
            action=CLEAR,
            tip=CLEAR_TIP,
            act=lambda: self._clear(claim),
        )

    def _clear(self, claim: AtWork) -> None:
        self._deps.board.end(claim.project, claim.step)
        self.refresh()

    def _notice_id(self, claim: AtWork) -> str:
        return f"{MODULE_ID}:{claim.project}:{claim.step}"

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
