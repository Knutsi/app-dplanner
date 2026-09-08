"""The "Agent" settings page: which agent Run Agent starts, which terminal it opens in,
and what a launch records on the step.

**Sane defaults, options laid out.** Both choices are a dropdown of known rows over an
editable field: the agent is one of the known CLIs — Claude Code, Codex, OpenCode — and
the terminal is one of the known terminals for this platform, each marked when it is not
installed. Picking a row pre-fills the field, so nobody has to research an invocation to
use the feature; the free-text field exists for the person who already knows exactly what
they want. The defaults work untouched: Claude Code, in plan mode, in the platform's own
default terminal.

The third choice is *On launch*: a launch claims the step is in progress, unless the
person says otherwise. On by default for the reason the marks are — a preference that has
to be found before it can help is one that helps nobody — and a switch rather than a rule
because a plan whose statuses somebody else keeps by hand should not have the window
writing into it.

Per user, per machine — a colleague's terminal is not the workspace's business, which is
why this is a GLOBAL-scope section and never a file in the plan. Whether a step's agent
gets a fresh worktree is *not* here: that is a fact about the step, kept on its agent
aspect and switched on the Agent tab.
"""

import sys

from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID
from dplanner.modules.step_agent_instruction.launcher import (
    DEFAULT_AGENT_COMMAND,
    PRESETS,
    TerminalPreset,
    current_command,
    is_installed,
    terminals_for,
)

AGENT_COMMAND_KEY = "agent_command"
LAUNCH_COMMAND_KEY = "launch_command"
START_IN_PROGRESS_KEY = "start_in_progress"

CUSTOM_LABEL = "Custom"
AUTOMATIC_LABEL = "Automatic"


def agent_command() -> str:
    """The stored command, read through the presets: a text an earlier version shipped
    for a preset is that preset, so the dropdown shows it and the wrapper runs its
    current command."""
    return current_command(str(get_global(MODULE_ID, AGENT_COMMAND_KEY, DEFAULT_AGENT_COMMAND)))


def launch_command() -> str:
    """The terminal template; "" means Automatic — the first installed preset."""
    return str(get_global(MODULE_ID, LAUNCH_COMMAND_KEY, ""))


def start_in_progress() -> bool:
    """On unless the user turned it off: a launch is the moment the work starts, and a
    step somebody is working on that still reads *pending* is the plan telling a lie
    nobody asked it to tell. Switching it off is the deliberate act."""
    return bool(get_global(MODULE_ID, START_IN_PROGRESS_KEY, True))


def terminal_label(preset: TerminalPreset, installed: bool) -> str:
    return preset.label if installed else f"{preset.label} — not found"


def _note(text: str, parent: QWidget) -> QLabel:
    note = QLabel(text, parent)
    note.setObjectName("InspectorNote")
    note.setWordWrap(True)
    return note


def _preset_field(
    combo: QComboBox, edit: QLineEdit, key: str, rows: list[tuple[str, str]], blank_label: str
) -> None:
    """Wire one dropdown-over-field pair: rows of (label, command), then a blank row.

    The dropdown reflects the field — a preset when the text matches one, the blank row
    (Custom, or Automatic when empty means "let the platform choose") otherwise — and
    picking a preset fills the field and commits. The same mechanics serve the agent and
    the terminal, which is why they are one function.
    """
    for label, command in rows:
        combo.addItem(label, command)
    combo.addItem(blank_label, "")

    def show_current() -> None:
        index = combo.findData(edit.text().strip())
        combo.blockSignals(True)
        combo.setCurrentIndex(index if index != -1 else combo.count() - 1)
        combo.blockSignals(False)

    def commit() -> None:
        set_global(MODULE_ID, key, edit.text().strip())
        show_current()

    def pick(index: int) -> None:
        command = combo.itemData(index)
        if command:  # The blank row pre-fills nothing; whatever is typed stays.
            edit.setText(command)
            commit()

    show_current()
    combo.activated.connect(pick)
    edit.editingFinished.connect(commit)


def build_page(parent: QWidget | None, platform: str = sys.platform) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("AgentSettingsPage")

    agent_combo = QComboBox(page)
    agent_combo.setObjectName("AgentPresetCombo")
    command_edit = QLineEdit(page)
    command_edit.setObjectName("AgentCommandEdit")
    command_edit.setText(agent_command())
    command_edit.setPlaceholderText(DEFAULT_AGENT_COMMAND)
    _preset_field(
        agent_combo,
        command_edit,
        AGENT_COMMAND_KEY,
        [(preset.label, preset.command) for preset in PRESETS],
        CUSTOM_LABEL,
    )

    terminal_combo = QComboBox(page)
    terminal_combo.setObjectName("AgentTerminalCombo")
    terminal_edit = QLineEdit(page)
    terminal_edit.setObjectName("AgentLaunchCommandEdit")
    terminal_edit.setText(launch_command())
    terminal_edit.setPlaceholderText("ghostty -e {script}")
    _preset_field(
        terminal_combo,
        terminal_edit,
        LAUNCH_COMMAND_KEY,
        [
            (terminal_label(preset, is_installed(preset)), preset.command)
            for preset in terminals_for(platform)
        ],
        AUTOMATIC_LABEL,
    )

    started_box = QCheckBox("Mark the step in progress when a run starts", page)
    started_box.setObjectName("AgentStartInProgressBox")
    started_box.setChecked(start_in_progress())
    started_box.toggled.connect(lambda on: set_global(MODULE_ID, START_IN_PROGRESS_KEY, bool(on)))

    layout = QVBoxLayout(page)
    layout.addWidget(QLabel("Agent", page))
    layout.addWidget(agent_combo)
    layout.addWidget(QLabel("Command", page))
    layout.addWidget(command_edit)
    layout.addWidget(
        _note(
            "What the terminal runs. {prompt} is the opening line — one sentence pointing"
            " the agent at the briefing file, never the briefing itself (appended when"
            " omitted); {session} is the run's session id, for an agent that can resume"
            " one; {run_dir} is the directory holding the briefing and its staged files,"
            " for an agent that must be allowed to read there. Picking an agent above"
            " fills this in.",
            page,
        )
    )
    layout.addWidget(QLabel("Terminal", page))
    layout.addWidget(terminal_combo)
    layout.addWidget(terminal_edit)
    layout.addWidget(
        _note(
            "How the terminal opens on the run script. Automatic takes the first installed"
            " terminal above, always a new window — tmux only when nothing else is"
            " installed; picking one fills in its command, which can be edited."
            " Placeholders: {script}, {workdir}, {title}.",
            page,
        )
    )
    layout.addWidget(QLabel("On launch", page))
    layout.addWidget(started_box)
    layout.addWidget(
        _note(
            "Run Agent sets the step's status to in progress as the terminal opens, so"
            " the board shows the work has started without waiting for the agent to say"
            " so. It is not undone when the agent stops: finishing is the agent's own"
            " claim, or yours from Step ▸ Status.",
            page,
        )
    )
    layout.addStretch(1)
    return page
