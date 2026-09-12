"""Add Detected Profiles…: the pairings this machine can run, ticked, then added.

A fit dialog on the frame (DESIGN.md's *Dialogs*): a note, then one checkable row per
pairing :func:`~dplanner.modules.step_agent_instruction.profiles.detect_pairings` found —
every agent CLI in every terminal of this platform, and Automatic. A row whose agent and
terminal are both on this machine and which the list does not already hold is ticked;
the rest are listed and say why they are not (*codex not found*, *already in the list*),
so the person sees what a missing tool would unlock rather than a shorter list. The
primary counts the ticks and is refused with its reason when there are none.

The dialog only reads and answers — ``chosen()`` is the ticked profiles — and the caller
writes them through ``add_profiles``, which is what lets the coming first-start checklist
host the same rows: the detection is the Qt-free half, this is one way of showing it.
"""

import os
import shutil
import sys
from collections.abc import Callable, Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

from dplanner.domain.agents import AgentHarness
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.widgets import note
from dplanner.modules.step_agent_instruction.profiles import Detected, Profile, detect_pairings

NOTHING_TICKED = "Tick at least one profile to add"


class DetectedProfilesDialog(DialogFrame):
    def __init__(
        self,
        harnesses: tuple[AgentHarness, ...],
        parent: QWidget | None = None,
        *,
        platform: str = sys.platform,
        which: Callable[[str], str | None] = shutil.which,
        env: Mapping[str, str] = os.environ,
        app_exists: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__("Add Detected Profiles", parent, size=(520, 480))
        self.setObjectName("DetectedProfilesDialog")
        self.detected = detect_pairings(harnesses, platform, which, env, app_exists)
        self.body_layout.addWidget(
            note(
                "Every agent CLI this build knows, in every terminal of this platform. "
                "A pairing is ticked when both are installed here and it is not in the "
                "list yet.",
                self.body,
            )
        )
        self.list = QListWidget(self.body)
        self.list.setObjectName("DetectedProfilesList")
        for row in self.detected:
            text = row.profile.name
            if row.remark:
                text = f"{text} — {row.remark}"
            item = QListWidgetItem(text, self.list)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if row.runnable and not row.present
                else Qt.CheckState.Unchecked
            )
            if row.present:  # Nothing to add: the row is a fact, not a choice.
                item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.body_layout.addWidget(self.list, 1)
        self.list.itemChanged.connect(lambda _item: self._revalidate())
        self.add_dismiss()
        self.primary_button = self.set_primary("Add Profiles", self.accept)
        self._revalidate()

    def rows(self) -> list[Detected]:
        return list(self.detected)

    def chosen(self) -> list[Profile]:
        """The ticked pairings, in the list's order."""
        return [
            row.profile
            for index, row in enumerate(self.detected)
            if (item := self.list.item(index)) is not None
            and item.checkState() == Qt.CheckState.Checked
        ]

    def _revalidate(self) -> None:
        count = len(self.chosen())
        self.primary_button.setText(f"Add {count} Profiles" if count != 1 else "Add Profile")
        self.refuse(None if count else NOTHING_TICKED)
