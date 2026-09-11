"""The "Agent" settings page: the launch profiles, and how many agents may start at once.

A **profile** (``profiles.py``) is one answer to Run Agent's two questions — which agent
CLI, and which terminal or multiplexer it opens in — under a name. The page is a list of
them beside an editor for the picked one; the first is the default *Run Agent…* runs, the
rest are the entries of *Step ▸ Run Agent With*, and *Make Default* moves one to the top.

**Sane defaults, options laid out.** Both of a profile's choices are a dropdown of known
rows over an editable field: the agent is one of the harnesses this build knows — Claude
Code, Codex, OpenCode — and the terminal is one of the known terminals and multiplexers
for this platform, each marked when it is not installed. Picking a row pre-fills the
field, so nobody has to research an invocation to use the feature; the free-text field
exists for the person who already knows exactly what they want. The defaults work
untouched: one profile, Claude Code in plan mode, in the platform's own default terminal.
A harness row also says what the CLI can do — *resumes*, *counts tokens* — words derived
from the harness record itself.

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
from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.agents import AgentHarness
from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID
from dplanner.modules.step_agent_instruction.launcher import (
    TerminalPreset,
    current_command,
    is_installed,
    terminals_for,
)
from dplanner.modules.step_agent_instruction.profiles import (
    Profile,
    default_profile,
    read_profiles,
    unique_name,
    update_profile,
    write_profiles,
)

MAX_AGENTS_KEY = "max_agents"

CUSTOM_LABEL = "Custom"
AUTOMATIC_LABEL = "Automatic"

DEFAULT_MAX_AGENTS = 4
# The ceiling the field offers. Not a judgement about hardware — a spin box needs a range,
# and a number typed past this one is far likelier a slip than an intention.
MAX_AGENTS_CEILING = 20


def agent_command(harnesses: tuple[AgentHarness, ...], profile: Profile | None = None) -> str:
    """The profile's agent command, read through the harnesses: a text an earlier version
    shipped for a harness is that harness, so the dropdown shows it and the wrapper runs
    its current command. The default profile's when none is given."""
    return current_command((profile or default_profile()).agent_command, harnesses)


def launch_command(profile: Profile | None = None) -> str:
    """The profile's terminal template; "" means Automatic — the first installed preset."""
    return (profile or default_profile()).launch_command


def max_agents() -> int:
    """How many agents one Run Agent may launch. Anything unreadable or out of the field's
    range reads as the default: a stored preference is not worth refusing the verb over."""
    try:
        stored = int(get_global(MODULE_ID, MAX_AGENTS_KEY, DEFAULT_MAX_AGENTS))
    except (TypeError, ValueError):
        return DEFAULT_MAX_AGENTS
    return min(max(stored, 1), MAX_AGENTS_CEILING)


def terminal_label(preset: TerminalPreset, installed: bool) -> str:
    label = f"{preset.label} — multiplexer" if preset.multiplexer else preset.label
    return label if installed else f"{label} — not found"


def harness_label(harness: AgentHarness) -> str:
    """The harness's name with what it can do — words derived from the record."""
    abilities = ", ".join(harness.capabilities())
    return f"{harness.label} — {abilities}" if abilities else harness.label


def _note(text: str, parent: QWidget) -> QLabel:
    note = QLabel(text, parent)
    note.setObjectName("InspectorNote")
    note.setWordWrap(True)
    return note


class PresetField:
    """One dropdown-over-field pair: rows of (label, command), then a blank row.

    The dropdown reflects the field — a preset when the text matches one, the blank row
    (Custom, or Automatic when empty means "let the platform choose") otherwise — and
    picking a preset fills the field and commits through ``on_commit``. The same
    mechanics serve the agent and the terminal, which is why they are one class.
    """

    def __init__(
        self,
        combo: QComboBox,
        edit: QLineEdit,
        rows: list[tuple[str, str]],
        blank_label: str,
        on_commit: Callable[[str], None],
        canonical: Callable[[str], str] = lambda text: text,
    ) -> None:
        self.combo, self.edit, self._on_commit, self._canonical = combo, edit, on_commit, canonical
        for label, command in rows:
            combo.addItem(label, command)
        combo.addItem(blank_label, "")
        combo.activated.connect(self._pick)
        edit.editingFinished.connect(self._commit)

    def show(self, text: str) -> None:
        """Reflect a stored text: the field, then the row it means."""
        self.edit.setText(text)
        self._show_current()

    def _show_current(self) -> None:
        index = self.combo.findData(self._canonical(self.edit.text().strip()))
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(index if index != -1 else self.combo.count() - 1)
        self.combo.blockSignals(False)

    def _commit(self) -> None:
        self._on_commit(self.edit.text().strip())
        self._show_current()

    def _pick(self, index: int) -> None:
        command = self.combo.itemData(index)
        if command:  # The blank row pre-fills nothing; whatever is typed stays.
            self.edit.setText(command)
            self._commit()


class ProfileList(QWidget):
    """The profiles as a list with Add, Remove and Make Default beside it."""

    def __init__(self, parent: QWidget, on_pick: Callable[[int], None]) -> None:
        super().__init__(parent)
        self._on_pick = on_pick
        self.list = QListWidget(self)
        self.list.setObjectName("AgentProfileList")
        self.list.currentRowChanged.connect(self._picked)
        self.add_button = QPushButton("Add", self)
        self.add_button.setObjectName("AgentProfileAdd")
        self.add_button.clicked.connect(self._add)
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.setObjectName("AgentProfileRemove")
        self.remove_button.clicked.connect(self._remove)
        self.default_button = QPushButton("Make Default", self)
        self.default_button.setObjectName("AgentProfileDefault")
        self.default_button.clicked.connect(self._make_default)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        column.addLayout(buttons)  # Parented before it is filled — CLAUDE.md's layout rule.
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.default_button)
        buttons.addStretch(1)
        self.reload(0)

    def reload(self, row: int) -> None:
        profiles = read_profiles()
        self.list.blockSignals(True)
        self.list.clear()
        for index, profile in enumerate(profiles):
            self.list.addItem(f"{profile.name} (default)" if index == 0 else profile.name)
        self.list.setCurrentRow(min(max(row, 0), len(profiles) - 1))
        self.list.blockSignals(False)
        self.remove_button.setEnabled(len(profiles) > 1)
        self.default_button.setEnabled(self.list.currentRow() > 0)
        self._on_pick(self.list.currentRow())

    def _picked(self, row: int) -> None:
        self.default_button.setEnabled(row > 0)
        self._on_pick(row)

    def _add(self) -> None:
        profiles = read_profiles()
        picked = profiles[max(self.list.currentRow(), 0)]
        # A new profile starts as a copy of the picked one: the usual reason for a second
        # profile is one thing changed — the terminal, or the agent.
        name = unique_name(f"{picked.name} copy", [p.name for p in profiles])
        write_profiles([*profiles, Profile(name, picked.agent_command, picked.launch_command)])
        self.reload(len(profiles))

    def _remove(self) -> None:
        profiles = read_profiles()
        row = self.list.currentRow()
        if len(profiles) > 1 and 0 <= row < len(profiles):
            del profiles[row]
            write_profiles(profiles)
            self.reload(min(row, len(profiles) - 1))

    def _make_default(self) -> None:
        profiles = read_profiles()
        row = self.list.currentRow()
        if row > 0:
            profiles.insert(0, profiles.pop(row))
            write_profiles(profiles)
            self.reload(0)


def build_page(
    parent: QWidget | None,
    platform: str = sys.platform,
    harnesses: tuple[AgentHarness, ...] = (),
) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("AgentSettingsPage")
    current = {"row": 0}

    name_edit = QLineEdit(page)
    name_edit.setObjectName("AgentProfileName")

    agent_combo = QComboBox(page)
    agent_combo.setObjectName("AgentPresetCombo")
    command_edit = QLineEdit(page)
    command_edit.setObjectName("AgentCommandEdit")
    command_edit.setPlaceholderText(harnesses[0].command if harnesses else "")
    agent_field = PresetField(
        agent_combo,
        command_edit,
        [(harness_label(harness), harness.command) for harness in harnesses],
        CUSTOM_LABEL,
        on_commit=lambda text: update_profile(current["row"], agent_command=text),
        canonical=lambda text: current_command(text, harnesses) if text else "",
    )

    terminal_combo = QComboBox(page)
    terminal_combo.setObjectName("AgentTerminalCombo")
    terminal_edit = QLineEdit(page)
    terminal_edit.setObjectName("AgentLaunchCommandEdit")
    terminal_edit.setPlaceholderText("ghostty -e {script}")
    terminal_field = PresetField(
        terminal_combo,
        terminal_edit,
        [
            (terminal_label(preset, is_installed(preset)), preset.command)
            for preset in terminals_for(platform)
        ],
        AUTOMATIC_LABEL,
        on_commit=lambda text: update_profile(current["row"], launch_command=text),
    )

    def show_profile(row: int) -> None:
        current["row"] = row
        profile = read_profiles()[row]
        name_edit.blockSignals(True)
        name_edit.setText(profile.name)
        name_edit.blockSignals(False)
        agent_field.show(profile.agent_command)
        terminal_field.show(profile.launch_command)

    def rename() -> None:
        name = name_edit.text().strip()
        if name and name != read_profiles()[current["row"]].name:
            update_profile(current["row"], name=name)
            profiles.reload(current["row"])

    profiles = ProfileList(page, show_profile)
    name_edit.editingFinished.connect(rename)

    limit = QSpinBox(page)
    limit.setObjectName("AgentMaxAgentsSpin")
    limit.setRange(1, MAX_AGENTS_CEILING)
    limit.setValue(max_agents())
    # Arrow steps commit as they land; typing commits on Enter or focus-out, so a
    # half-typed "1" on the way to "12" never becomes the limit for an instant.
    limit.setKeyboardTracking(False)
    limit.valueChanged.connect(lambda value: set_global(MODULE_ID, MAX_AGENTS_KEY, value))

    editor = QVBoxLayout()
    editor.addWidget(QLabel("Profile name", page))
    editor.addWidget(name_edit)
    editor.addWidget(QLabel("Agent", page))
    editor.addWidget(agent_combo)
    editor.addWidget(QLabel("Command", page))
    editor.addWidget(command_edit)
    editor.addWidget(
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
    editor.addWidget(QLabel("Terminal or multiplexer", page))
    editor.addWidget(terminal_combo)
    editor.addWidget(terminal_edit)
    editor.addWidget(
        _note(
            "How the terminal opens on the run script. Automatic takes the first installed"
            " terminal above, always a new window — a multiplexer only when nothing else"
            " is installed; picking one fills in its command, which can be edited."
            " A multiplexer adds a pane per agent to what is already running, so several"
            " selected steps land side by side. Placeholders: {script}, {workdir},"
            " {title}; two calls joined by && run in turn, {pane} in the second being"
            " what the first printed.",
            page,
        )
    )
    editor.addStretch(1)

    layout = QVBoxLayout(page)
    layout.addWidget(QLabel("Profiles", page))
    layout.addWidget(
        _note(
            "Run Agent… runs the default profile; the others are Step ▸ Run Agent With.",
            page,
        )
    )
    columns = QHBoxLayout()
    layout.addLayout(columns)
    columns.addWidget(profiles, 1)
    columns.addLayout(editor, 2)
    layout.addWidget(QLabel("Agents at once", page))
    limit_row = QHBoxLayout()
    layout.addLayout(limit_row)
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
