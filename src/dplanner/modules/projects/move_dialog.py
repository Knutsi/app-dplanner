"""Move Plan: where the plan should live from now on.

A plan repository from the picker — one the library uses, another folder, a clone, or a
new one, local or to be published — and a folder name inside it. The dialog only answers;
the module runs ``domain/relocate.move_project`` and reloads, because a move rewrites the
working tree (ARCHITECTURE.md's *Storage operations that rewrite the working tree are
synchronous*), and every view that cached a directory is rebuilt rather than patched.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.relocate import target_in
from dplanner.domain.repositories import RepositoryFacts
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.projects.project_dialog import glyph_label
from dplanner.modules.projects.repo_picker import PlanTarget, RepoPicker
from dplanner.modules.projects.repos import RepositoryServices, shown_path
from dplanner.theme.icons import ICON_SIZE, folder_icon


class MovePlanDialog(QDialog):
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
        super().__init__(parent)
        self.setObjectName("MovePlanDialog")
        self.setWindowTitle("Move Plan")
        self.setMinimumWidth(560)

        caption = QLabel("Where should the plan live?", self)
        caption.setObjectName("InspectorCaption")
        self.picker = RepoPicker(services, tasks, allow_new=True, theme=theme, parent=self)
        self.picker.setObjectName("MovePlanPicker")
        self.picker.changed.connect(self._revalidate)

        self.folder_glyph = glyph_label(self)
        self.folder_glyph.setPixmap(
            folder_icon(theme.current.text_secondary).pixmap(ICON_SIZE, ICON_SIZE)
        )
        self.folder_edit = QLineEdit(folder_name, self)
        self.folder_edit.setObjectName("MoveFolderEdit")
        self.folder_edit.setPlaceholderText("folder name inside the repository")
        self.folder_edit.textChanged.connect(lambda _text: self._revalidate())
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_row.addWidget(self.folder_glyph)
        folder_row.addWidget(self.folder_edit, 1)
        self.target_label = QLabel(self)
        self.target_label.setObjectName("MoveTargetPath")
        self.target_label.setWordWrap(True)

        self.summary = QLabel(self)
        self.summary.setObjectName("MovePlanSummary")
        self.summary.setWordWrap(True)
        origin = facts.plan_label or "its current folder"
        self.summary.setText(
            f"“{title}” leaves {origin} — one commit there records the move, one in the new"
            " repository adds it — and the library follows. Finish running agents first."
        )

        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        self.move_button = QPushButton("Move Plan", self)
        self.move_button.setObjectName("PrimaryButton")
        self.move_button.setDefault(True)
        self.move_button.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(self.move_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(caption)
        layout.addWidget(self.picker)
        layout.addLayout(folder_row)
        layout.addWidget(self.target_label)
        layout.addWidget(self.summary)
        layout.addLayout(footer)
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
        target = self.target()
        if target is None:
            self.target_label.setText("")
            self.move_button.setEnabled(False)
            return
        exists = target.exists()
        self.target_label.setText(shown_path(target) + (" — already exists" if exists else ""))
        self.move_button.setEnabled(not exists)

    def accept(self) -> None:
        self.picker.remember()
        super().accept()
