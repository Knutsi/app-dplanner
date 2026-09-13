"""The two dialogs a launch can raise: the prompt itself when no terminal could be
opened, and the graph's question before a shell opens on a step whose prerequisites are
not done.

The fallback is not an error page — the prompt is the library, and the terminal was only
ever one way to deliver it. Copy it, or point an agent at the file; ``dplanner agent
prompt`` prints the same thing. The question is DESIGN.md's first flow: the count in the
window title, the step and what it waits on in the body, *Run Anyway* the primary.
"""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.widgets import caption, make_text_well, note, space_lines

DIALOG_SIZE = (560, 480)


class PromptFallbackDialog(DialogFrame):
    """Also the Preview Prompt dialog: same prompt, a different note over it."""

    def __init__(
        self,
        prompt_text: str,
        prompt_path: str,
        parent: QWidget | None,
        note_text: str = "",
        title: str = "Run Agent",
    ) -> None:
        super().__init__(title, parent, size=DIALOG_SIZE)
        body, layout = self.body, self.body_layout
        layout.addWidget(
            note(
                note_text
                or "No terminal could be opened, so here is the prompt itself. It is also saved"
                f" at {prompt_path} — and `dplanner agent prompt` prints the same thing.",
                body,
            )
        )
        self.prompt = QPlainTextEdit(body)
        self.prompt.setReadOnly(True)
        self.prompt.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # Close is the first stop.
        make_text_well(self.prompt)
        self.prompt.setPlainText(prompt_text)
        space_lines(self.prompt)
        layout.addWidget(self.prompt, 1)
        self.copy_button = self.add_button("Copy Prompt", self._copy)
        self.add_dismiss("Close")

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.prompt.toPlainText())
        self.status.say("Prompt copied", "ok")


class RunAnywayDialog(DialogFrame):
    """The graph's question before a launch: which chosen steps wait on work not done,
    what that work is, and *Run Anyway* — the accent, because it discards nothing and is
    the flow's next step; Cancel is Escape's.

    ``count`` is the launches the gesture would make — every chosen step, not only the
    ones that wait — so *Run 3 Agents* says what Run Anyway does. ``groups`` is one
    ``(heading, lines)`` per waiting step; a single waiting step has no heading, the
    lead already names it.
    """

    def __init__(
        self,
        count: int,
        lead: str,
        groups: Sequence[tuple[str, Sequence[str]]],
        closing: str,
        parent: QWidget | None,
    ) -> None:
        super().__init__("Run Agent" if count == 1 else f"Run {count} Agents", parent)
        body, layout = self.body, self.body_layout
        self._groups = [(heading, list(lines)) for heading, lines in groups]
        self.lead = QLabel(lead, body)
        self.lead.setObjectName("DialogQuestion")
        self.lead.setWordWrap(True)
        layout.addWidget(self.lead)
        for heading, lines in self._groups:
            if heading:
                layout.addWidget(caption(heading, body))
            listed = note("\n".join(lines), body)
            listed.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(listed)
        self.closing = QLabel(closing, body)
        self.closing.setObjectName("DialogQuestion")
        self.closing.setWordWrap(True)
        layout.addWidget(self.closing)
        layout.addStretch(0)
        self.add_dismiss()
        self.set_primary("Run Anyway", self.accept)

    def words(self) -> str:
        """Everything under the lead as one text: each group under its heading, then the
        closing line — what a test reads, and what the box this replaced said."""
        blocks = [
            (f"{heading}:\n" if heading else "") + "\n".join(lines)
            for heading, lines in self._groups
        ]
        return "\n\n".join([*blocks, self.closing.text()])
