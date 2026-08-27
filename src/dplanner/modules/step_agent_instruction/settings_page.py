"""The "Agent" settings page: which agent Run Agent starts, and how the terminal opens.

**Sane defaults, options laid out.** The agent is a dropdown of the known CLIs — Claude
Code, Codex, OpenCode — and picking one pre-fills an editable command, so nobody has to
research an invocation to use the feature; the free-text field exists for the person who
already knows exactly what they want. The defaults work untouched: Claude Code, in plan
mode, in a fresh worktree.

Per user, per machine — a colleague's terminal is not the workspace's business, which is
why this is a GLOBAL-scope section and never a file in the plan.
"""

from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID
from dplanner.modules.step_agent_instruction.launcher import DEFAULT_AGENT_COMMAND, PRESETS

AGENT_COMMAND_KEY = "agent_command"
WORKTREE_KEY = "worktree"
LAUNCH_COMMAND_KEY = "launch_command"

CUSTOM_LABEL = "Custom"


def agent_command() -> str:
    return str(get_global(MODULE_ID, AGENT_COMMAND_KEY, DEFAULT_AGENT_COMMAND))


def use_worktree() -> bool:
    return bool(get_global(MODULE_ID, WORKTREE_KEY, True))


def launch_command() -> str:
    return str(get_global(MODULE_ID, LAUNCH_COMMAND_KEY, ""))


def _note(text: str, parent: QWidget) -> QLabel:
    note = QLabel(text, parent)
    note.setObjectName("InspectorNote")
    note.setWordWrap(True)
    return note


def build_page(parent: QWidget | None) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("AgentSettingsPage")

    agent_combo = QComboBox(page)
    agent_combo.setObjectName("AgentPresetCombo")
    for preset in PRESETS:
        agent_combo.addItem(preset.label, preset.command)
    agent_combo.addItem(CUSTOM_LABEL, "")

    command_edit = QLineEdit(page)
    command_edit.setObjectName("AgentCommandEdit")
    command_edit.setText(agent_command())
    command_edit.setPlaceholderText(DEFAULT_AGENT_COMMAND)

    def show_current() -> None:
        """The dropdown reflects the command: a preset when it matches one, else Custom."""
        index = agent_combo.findData(command_edit.text().strip())
        agent_combo.blockSignals(True)
        agent_combo.setCurrentIndex(index if index != -1 else agent_combo.count() - 1)
        agent_combo.blockSignals(False)

    def pick_preset(index: int) -> None:
        command = agent_combo.itemData(index)
        if command:  # Custom pre-fills nothing; whatever is typed stays.
            command_edit.setText(command)
            commit_command()

    def commit_command() -> None:
        set_global(MODULE_ID, AGENT_COMMAND_KEY, command_edit.text().strip())
        show_current()

    show_current()
    agent_combo.activated.connect(pick_preset)
    command_edit.editingFinished.connect(commit_command)

    worktree_box = QCheckBox("Start in a fresh git worktree", page)
    worktree_box.setObjectName("AgentWorktreeBox")
    worktree_box.setChecked(use_worktree())
    worktree_box.toggled.connect(lambda on: set_global(MODULE_ID, WORKTREE_KEY, bool(on)))

    terminal_edit = QLineEdit(page)
    terminal_edit.setObjectName("AgentLaunchCommandEdit")
    terminal_edit.setText(launch_command())
    terminal_edit.setPlaceholderText("ghostty -e {script}")
    terminal_edit.editingFinished.connect(
        lambda: set_global(MODULE_ID, LAUNCH_COMMAND_KEY, terminal_edit.text().strip())
    )

    layout = QVBoxLayout(page)
    layout.addWidget(QLabel("Agent", page))
    layout.addWidget(agent_combo)
    layout.addWidget(QLabel("Command", page))
    layout.addWidget(command_edit)
    layout.addWidget(
        _note(
            "What the terminal runs, seeded with the step's briefing — {prompt} is where"
            " it goes (appended when omitted). Picking an agent above fills this in.",
            page,
        )
    )
    layout.addWidget(worktree_box)
    layout.addWidget(
        _note(
            "When the checkout is a git repository, the agent works in"
            " .dplanner/worktrees/<step> on an agent/<step> branch — created on the first"
            " run, reused on the next — so parallel agents never share a checkout.",
            page,
        )
    )
    layout.addWidget(QLabel("Terminal", page))
    layout.addWidget(terminal_edit)
    layout.addWidget(
        _note(
            "How the terminal itself opens. Placeholders: {script}, {prompt_file},"
            " {workdir}. Empty uses this platform's default terminal (tmux when inside"
            " one).",
            page,
        )
    )
    layout.addStretch(1)
    return page
