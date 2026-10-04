"""The dialog behind the banner: every agent at work, and what each is doing.

The banner stands for all of them in one row, so it can only count them; this is where each
is said in full. A ``DialogFrame`` over a ``RowWell`` — the Agents browser's shape, one row
kept per claim across every poll — because each row carries verbs of its own: *Reveal*
selects the step the agent is on, and the row's ✕ clears that one claim, which is the only
way to drop a dead agent's claim without clearing the live ones beside it.

A row is the step (or the project, for a claim on the plan as a whole), the agent's own
words with its count and when it was last heard on the status line, and a bar under that
while it declared a count. The line is busy in tone: an agent running is running, the same
mood a live row in the Agents browser wears. Pure widgets: the module feeds the claims and
their titles, and the callbacks.
"""

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from dplanner.domain.at_work import AtWork, fraction, heard_words, progress_words
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.row_well import RowWell, WellRow
from dplanner.framework.widgets import EmptyState

DIALOG_SIZE = (560, 400)  # The Agents browser's: the same kind of list, the same frame.
NO_AGENTS = "No agent is at work."
CLEAR_ONE_TIP = (
    "Clear this claim — an agent still working makes a new one the next time it says what"
    " it is doing"
)

ClaimKey = tuple[str, str]  # (project, step) — what makes two claims two.


def claim_key(claim: AtWork) -> ClaimKey:
    return (claim.project, claim.step)


def status_words(claim: AtWork) -> str:
    """What the agent wrote, how far it says it is, and when it was last heard from."""
    parts = (claim.doing, progress_words(claim), heard_words(claim))
    return " · ".join(part for part in parts if part)


class ClaimRow(WellRow):
    """One claim: what it is on, with its verbs; what the agent says; how far it has come."""

    def __init__(
        self,
        claim: AtWork,
        reveal: Callable[[AtWork], None],
        clear: Callable[[AtWork], None],
    ) -> None:
        super().__init__()
        self.claim = claim
        self.reveal_button = self.add_button(
            "Reveal", lambda: reveal(self.claim), tip="Select the step in its project"
        )
        self.add_dismiss(lambda: clear(self.claim), tip=CLEAR_ONE_TIP)

    def refresh(self, claim: AtWork, title: str) -> None:
        self.claim = claim
        self.title.setText(title)
        self.status.say(status_words(claim), "busy")
        counted = fraction(claim)
        self.show_fraction(counted if counted >= 0 else None)
        # A claim on the plan as a whole has no step to select; the verb's room stays.
        self.reveal_button.setVisible(bool(claim.step))


class AtWorkDialog(DialogFrame):
    """Every standing claim as a row kept by claim, in the order they began."""

    def __init__(
        self,
        parent: QWidget | None,
        reveal: Callable[[AtWork], None],
        clear: Callable[[AtWork], None],
        clear_all: Callable[[], None],
    ) -> None:
        super().__init__("Agents at Work", parent, size=DIALOG_SIZE)
        self.setObjectName("AtWorkDialog")
        self._reveal = reveal
        self._clear = clear
        self.well = RowWell(self.body)
        self.body_layout.addWidget(self.well, 1)
        self.empty = EmptyState(NO_AGENTS, self.body, stands_in_for=self.well)
        self.body_layout.addWidget(self.empty, 1)
        self.clear_button = self.add_button("Clear All", clear_all)
        self.close_button = self.add_dismiss("Close")

    def rows(self) -> list[ClaimRow]:
        """The listed claims' rows, top to bottom."""
        return [row for row in self.well.rows() if isinstance(row, ClaimRow)]

    def refresh(self, claims: list[tuple[AtWork, str]]) -> None:
        """``claims`` is every standing claim with the title its row wears."""
        by_key = {claim_key(claim): (claim, title) for claim, title in claims}

        def build(key: ClaimKey) -> ClaimRow:
            return ClaimRow(by_key[key][0], self._reveal, self._clear)

        def update(key: ClaimKey, row: ClaimRow) -> None:
            row.refresh(*by_key[key])

        self.well.reconcile(list(by_key), build, update)
        self.empty.say("" if by_key else NO_AGENTS)
        self.clear_button.setEnabled(bool(by_key))  # Disabled, never hidden: nobody is at work.
