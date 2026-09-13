"""Move Plan: where the plan should live from now on.

A plan repository from the picker — one the library uses, another folder, a clone, or a
new one, local or to be published — and a folder name inside it. The dialog only answers;
the module runs ``domain/relocate.move_project`` and reloads, because a move rewrites the
working tree (ARCHITECTURE.md's *Storage operations that rewrite the working tree are
synchronous*), and every view that cached a directory is rebuilt rather than patched.
"""

from pathlib import Path

from PySide6.QtWidgets import QLineEdit, QWidget

from dplanner.domain.relocate import target_in
from dplanner.domain.repositories import RepositoryFacts
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.widgets import block, caption, note
from dplanner.modules.projects.repo_picker import PlanTarget, RepoPicker
from dplanner.modules.projects.repos import RepositoryServices, shown_path

MIN_WIDTH = 560  # The path the plan moves to is shown in full, and a path wants the room.


class MovePlanDialog(DialogFrame):
    """A fit dialog: the plan repository and the folder inside it as two captioned blocks,
    the path they make as the line under the folder, and *Move Plan* refused in words
    until both are answered."""

    def __init__(
        self,
        *,
        title: str,
        folder_name: str,
        facts: RepositoryFacts,
        services: RepositoryServices,
        tasks: TaskService,
        theme: ThemeService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Move Plan", parent)
        self.setMinimumWidth(MIN_WIDTH)
        body, layout = self.body, self.body_layout

        self.picker = RepoPicker(services, tasks, allow_new=True, theme=theme, parent=body)
        self.picker.setObjectName("MovePlanPicker")
        self.picker.changed.connect(self._revalidate)
        block(layout, caption("Plan repository", body), self.picker)

        self.folder_edit = QLineEdit(folder_name, body)
        self.folder_edit.setObjectName("MoveFolderEdit")
        self.folder_edit.setPlaceholderText("folder name inside the repository")
        self.folder_edit.textChanged.connect(lambda _text: self._revalidate())
        self.target_label = note("", body)
        block(layout, caption("Folder", body), self.folder_edit, self.target_label)

        origin = facts.plan_label or "its current folder"
        self.summary = note(
            f"“{title}” leaves {origin} — one commit there records the move, one in the new"
            " repository adds it — and the library follows. Finish running agents first.",
            body,
        )
        layout.addWidget(self.summary)

        self.add_dismiss()
        self.move_button = self.set_primary("Move Plan", self.accept)
        self._revalidate()

    def plan_target(self) -> PlanTarget | None:
        return self.picker.current()

    def target(self) -> Path | None:
        """The directory the plan moves to; None until both the repository and a folder
        name are chosen."""
        chosen = self.picker.current()
        name = self.folder_edit.text().strip()
        if chosen is None or not name:
            return None
        return target_in(chosen.root, name)

    def _revalidate(self) -> None:
        """The primary is refused with its reason until the move is fully named."""
        if self.picker.current() is None:
            self.target_label.setText("")
            self.refuse("Pick a plan repository")
            return
        if not self.folder_edit.text().strip():
            self.target_label.setText("")
            self.refuse("Name the folder inside it")
            return
        target = self.target()
        assert target is not None
        self.target_label.setText(shown_path(target))
        self.refuse("That folder already exists" if target.exists() else None)

    def accept(self) -> None:
        self.picker.remember()
        super().accept()
