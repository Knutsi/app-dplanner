"""A save that could not be pushed because the remote changed the same lines.

The one storage failure with a remedy other than "try again": the commit is recorded here,
and somebody has to rebase it onto what arrived on origin before it can leave. A status line
cannot hold that, so whichever dialog meets it — the quit-time save's progress, or the
*Not Pushed* dialog Save and Update from Remote open — says it in the body, in the words
below, and offers to send an agent into that repository with any launch profile.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtWidgets import QMenu, QPushButton, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.widgets import note

# Every launch profile and why it cannot open a terminal here ("" when it can), the default
# first — the Problems panel's shape, so both list profiles the same way.
Profiles = Callable[[], Sequence[tuple[str, str]]]
# (repository root, branch, profile name) -> whether a terminal opened.
Reconcile = Callable[[Path, str, str], bool]


@dataclass(frozen=True)
class Divergence:
    """Which repository could not be pushed, and on which branch."""

    repo_root: Path
    branch: str


def explanation(divergence: Divergence) -> str:
    """The whole story, in the body: the error's own words would only repeat its first
    clause, so a dialog showing this leaves its status line empty."""
    branch = divergence.branch
    return (
        f"Your changes are committed in {divergence.repo_root}, but not pushed: "
        f"origin/{branch} has changes to the same lines, so the two cannot be combined "
        f"automatically. Nothing is lost. To finish, rebase {branch} onto origin/{branch}, "
        "settle the conflicts and push — in a terminal, or with an agent."
    )


def add_explanation(dialog: DialogFrame, divergence: Divergence, at: int = -1) -> None:
    label = note(explanation(divergence), dialog.body)
    dialog.body_layout.insertWidget(at, label)
    # Now, not on the next turn as a layout would: a dialog already on screen measures
    # what it holds right after this, and a hidden child is not counted.
    label.show()


def attach_reconcile_menu(
    button: QPushButton,
    divergence: Divergence,
    profiles: Profiles,
    reconcile: Reconcile,
    launched: Callable[[], object],
) -> None:
    """Make ``button`` drop one entry per launch profile, greyed with its own reason —
    rebuilt each time it opens, as the Problems panel's is. ``launched`` runs once a
    terminal has opened, so the dialog can step aside for the agent."""
    popup = QMenu(button)

    def run(name: str, _checked: bool = False) -> None:
        if reconcile(divergence.repo_root, divergence.branch, name):
            launched()

    def fill() -> None:
        popup.clear()
        for index, (name, refusal) in enumerate(profiles()):
            label = f"{name} (default)" if index == 0 else name
            entry = popup.addAction(f"{label} — {refusal}" if refusal else label)
            entry.setEnabled(not refusal)
            entry.triggered.connect(partial(run, name))

    popup.aboutToShow.connect(fill)
    button.setMenu(popup)


RECONCILE_LABEL = "Reconcile with Agent"


class NotPushedDialog(DialogFrame):
    """What Save and Update from Remote open when a repository diverged from its remote."""

    def __init__(
        self,
        divergence: Divergence,
        parent: QWidget | None = None,
        *,
        profiles: Profiles | None = None,
        reconcile: Reconcile | None = None,
    ) -> None:
        super().__init__("Not Pushed", parent)
        add_explanation(self, divergence)
        self.add_dismiss("Close")
        self.reconcile_button: QPushButton | None = None
        if profiles is not None and reconcile is not None:
            self.reconcile_button = self.set_primary(RECONCILE_LABEL, lambda: None)
            attach_reconcile_menu(
                self.reconcile_button, divergence, profiles, reconcile, self.accept
            )
