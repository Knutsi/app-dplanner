"""The "Agent" settings page: how Run Agent opens a terminal on this machine.

Per user, per machine — a colleague's terminal is not the workspace's business, which is
why this is a GLOBAL-scope section and never a file in the plan.
"""

from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID

LAUNCH_COMMAND_KEY = "launch_command"


def launch_command() -> str:
    return str(get_global(MODULE_ID, LAUNCH_COMMAND_KEY, ""))


def build_page(parent: QWidget | None) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("AgentSettingsPage")

    caption = QLabel("Run command", page)
    edit = QLineEdit(page)
    edit.setObjectName("AgentLaunchCommandEdit")
    edit.setText(launch_command())
    edit.setPlaceholderText("ghostty -e {script}")
    edit.editingFinished.connect(
        lambda: set_global(MODULE_ID, LAUNCH_COMMAND_KEY, edit.text().strip())
    )

    note = QLabel(
        "How Run Agent opens a terminal. Placeholders: {script} — a wrapper that starts the"
        " agent with the step's prompt; {prompt_file} — the assembled prompt as markdown;"
        " {workdir} — the product's checkout. Empty uses this platform's default terminal"
        " (tmux when inside one).",
        page,
    )
    note.setObjectName("InspectorNote")
    note.setWordWrap(True)

    layout = QVBoxLayout(page)
    layout.addWidget(caption)
    layout.addWidget(edit)
    layout.addWidget(note)
    layout.addStretch(1)
    return page
