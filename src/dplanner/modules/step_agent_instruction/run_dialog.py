"""The fallback when no terminal could be opened: the prompt itself, ready to carry.

Not an error page — the prompt is the library, and the terminal was only ever one way to
deliver it. Copy it, or point an agent at the file; ``dplanner agent prompt`` prints the
same thing.
"""

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DIALOG_MARGIN = 16


class PromptFallbackDialog(QDialog):
    """Also the Preview Prompt dialog: same prompt, a different note over it."""

    def __init__(
        self,
        prompt_text: str,
        prompt_path: str,
        parent: QWidget | None,
        note_text: str = "",
        title: str = "Run Agent",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)

        note = QLabel(
            note_text
            or "No terminal could be opened, so here is the prompt itself. It is also saved"
            f" at {prompt_path} — and `dplanner agent prompt` prints the same thing.",
            self,
        )
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)

        self.prompt = QPlainTextEdit(self)
        self.prompt.setObjectName("AgentPromptView")
        self.prompt.setPlainText(prompt_text)
        self.prompt.setReadOnly(True)

        copy_button = QPushButton("Copy Prompt", self)
        copy_button.clicked.connect(self._copy)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        layout.addWidget(note)
        layout.addWidget(self.prompt, 1)
        layout.addWidget(buttons)
        self.resize(560, 480)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.prompt.toPlainText())
