"""The Branch block on a cut's Details tab: the branch it starts, committed as one command."""

from typing import Any

from PySide6.QtWidgets import QLineEdit, QVBoxLayout

from dplanner.domain.model import Library, Step
from dplanner.framework.module_data_section import FIELD_GAP, ModuleDataSection
from dplanner.framework.signalling import StatusLine
from dplanner.framework.undo import UndoService
from dplanner.modules.branches.aspect import CUT_ID, branch_of, name_problem, write_cut


class CutSection(ModuleDataSection):
    """The branch name — refused, and said under the field, while git would refuse it."""

    def __init__(self, library: Library, undo: UndoService[Library]) -> None:
        super().__init__(library, undo, module_id=CUT_ID, undo_label="Set Branch")
        self.branch = QLineEdit(self)
        self.branch.setPlaceholderText("feature/…")
        self.problem = StatusLine(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self.branch)
        layout.addWidget(self.problem)
        self.branch.textChanged.connect(self._check)
        self.branch.editingFinished.connect(self._commit_valid)

    def load_step(self, step: Step | None) -> None:
        self.branch.setText(branch_of(step) if step is not None else "")

    def entry(self, step: Step) -> dict[str, Any]:
        return write_cut(self.branch.text().strip())

    def _check(self, text: str) -> None:
        self.problem.say(name_problem(text.strip()) or "", "error")

    def _commit_valid(self) -> None:
        if name_problem(self.branch.text().strip()) is None:
            self.commit()
