"""The "Agent" settings page: which agent Run Agent starts, which terminal it opens in,
and how many it may start at once.

**Sane defaults, options laid out.** Both choices are a dropdown of known rows over an
editable field: the agent is one of the known CLIs — Claude Code, Codex, OpenCode — and
the terminal is one of the known terminals for this platform, each marked when it is not
installed. Picking a row pre-fills the field, so nobody has to research an invocation to
use the feature; the free-text field exists for the person who already knows exactly what
they want. The defaults work untouched: Claude Code, in plan mode, in the platform's own
default terminal.

**How many at once is here too**, because it is a fact about this desk rather than about
the plan: how many terminals, worktrees and live sessions one machine can carry is the
person's to say, and Run Agent over a multi-selection refuses past it. Four is the default
— enough for the gesture the limit exists for, few enough that a stray lasso cannot fill
the screen.

Per user, per machine — a colleague's terminal is not the workspace's business, which is
why this is a GLOBAL-scope section and never a file in the plan. Whether a step's agent
gets a fresh worktree is *not* here: that is a fact about the step, kept on its agent
aspect and switched on the Agent tab.
"""

import sys

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

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
MAX_AGENTS_KEY = "max_agents"

CUSTOM_LABEL = "Custom"
AUTOMATIC_LABEL = "Automatic"

DEFAULT_MAX_AGENTS = 4
# The ceiling the field offers. Not a judgement about hardware — a spin box needs a range,
# and a number typed past this one is far likelier a slip than an intention.
MAX_AGENTS_CEILING = 20


def agent_command() -> str:
    """The stored command, read through the presets: a text an earlier version shipped
    for a preset is that preset, so the dropdown shows it and the wrapper runs its
    current command."""
    return current_command(str(get_global(MODULE_ID, AGENT_COMMAND_KEY, DEFAULT_AGENT_COMMAND)))


def max_agents() -> int:
    """How many agents one Run Agent may launch. Anything unreadable or out of the field's
    range reads as the default: a stored preference is not worth refusing the verb over."""
    try:
        stored = int(get_global(MODULE_ID, MAX_AGENTS_KEY, DEFAULT_MAX_AGENTS))
    except (TypeError, ValueError):
        return DEFAULT_MAX_AGENTS
    return min(max(stored, 1), MAX_AGENTS_CEILING)


def launch_command() -> str:
    """The terminal template; "" means Automatic — the first installed preset."""
    return str(get_global(MODULE_ID, LAUNCH_COMMAND_KEY, ""))


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

    limit = QSpinBox(page)
    limit.setObjectName("AgentMaxAgentsSpin")
    limit.setRange(1, MAX_AGENTS_CEILING)
    limit.setValue(max_agents())
    # Arrow steps commit as they land; typing commits on Enter or focus-out, so a
    # half-typed "1" on the way to "12" never becomes the limit for an instant.
    limit.setKeyboardTracking(False)
    limit.valueChanged.connect(lambda value: set_global(MODULE_ID, MAX_AGENTS_KEY, value))

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
    layout.addWidget(QLabel("Agents at once", page))
    limit_row = QHBoxLayout()
    layout.addLayout(limit_row)  # Parented before it is filled — see CLAUDE.md's layout rule.
    limit_row.addWidget(limit)
    limit_row.addStretch(1)
    layout.addWidget(
        _note(
            "How many agents Run Agent may launch from one selection. Each is a terminal,"
            " a worktree and a session of its own; select more than this and the verb says"
            " so instead of filling the desk.",
            page,
        )
    )
    layout.addStretch(1)
    return page
