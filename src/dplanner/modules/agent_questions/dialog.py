"""The full text a question card abbreviates — a plan to approve, a permission's denials —
read-only, Close alone."""

from PySide6.QtWidgets import QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.markdown_view import MarkdownView


class QuestionBodyDialog(DialogFrame):
    def __init__(self, title: str, body: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent, size=(720, 640))
        self.view = MarkdownView(self.body)
        self.view.show_markdown(body)
        self.body_layout.addWidget(self.view, 1)
        self.add_dismiss("Close")
