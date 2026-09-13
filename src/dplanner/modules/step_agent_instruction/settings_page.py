"""The "Agent" settings page: the launch profiles, how many agents may start at once, and
what a launch records on the step.

A **profile** (``profiles.py``) is one answer to Run Agent's two questions — which agent
CLI, and which terminal or multiplexer it opens in — under a name. The page is a list of
them beside an editor for the picked one; the first is the default *Run Agent…* runs, all
of them are the entries of *Step ▸ Run Agent*, and *Make Default* moves one to the top.
*Add Detected…* (``detect_dialog.py``) pairs the agents and terminals installed on this
machine and adds the ticked ones.

**Sane defaults, options laid out.** Both of a profile's choices are a dropdown of known
rows over an editable field: the agent is one of the harnesses this build knows — Claude
Code, Codex, OpenCode — and the terminal is one of the known terminals and multiplexers
for this platform, each marked when it is not installed. Picking a row pre-fills the
field, so nobody has to research an invocation to use the feature; the free-text field
exists for the person who already knows exactly what they want. The defaults work
untouched: one profile, Claude Code in plan mode, in the platform's own default terminal.
A harness row also says what the CLI can do — *resumes*, *counts tokens* — words derived
from the harness record itself.

**A profile's name follows its choices until somebody types one.** A new profile is a
copy of the picked one named by what it does — *Claude Code in herdr* — and stays named
that way through the edits that usually follow, the terminal and then the agent, numbered
when the name is taken. A name typed into the field is the person's and is kept; a typed
duplicate is numbered rather than refused. The rule lives with the write, in
``profiles.update_profile``; this page only re-reads the list after each commit.

**How many at once is here too**, because it is a fact about this desk rather than about
the plan: how many terminals, worktrees and live sessions one machine can carry is the
person's to say, and Run Agent over a multi-selection refuses past it. Four is the default
— enough for the gesture the limit exists for, few enough that a stray lasso cannot fill
the screen.

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
from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.agents import AgentHarness
from dplanner.framework.settings_registry import settings_page
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import block, caption, captioned
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID
from dplanner.modules.step_agent_instruction.detect_dialog import DetectedProfilesDialog
from dplanner.modules.step_agent_instruction.launcher import (
    TerminalPreset,
    current_command,
    is_installed,
    terminals_for,
)
from dplanner.modules.step_agent_instruction.profiles import (
    Profile,
    add_profiles,
    default_profile,
    read_profiles,
    suggested_name,
    unique_name,
    update_profile,
    write_profiles,
)
from dplanner.theme.icons import find_icon, plus_icon, star_icon, trash_icon
from dplanner.theme.tokens import FIELD_GAP, SECTION_GAP

MAX_AGENTS_KEY = "max_agents"
START_IN_PROGRESS_KEY = "start_in_progress"

CUSTOM_LABEL = "Custom"
# What a preset dropdown asks room for: a harness row reads long, and a dropdown sized to its
# longest row would make the page wider than the dialog it scrolls in.
PRESET_CHARS = 16
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


def start_in_progress() -> bool:
    """On unless the user turned it off: a launch is the moment the work starts, and a
    step somebody is working on that still reads *pending* is the plan telling a lie
    nobody asked it to tell. Switching it off is the deliberate act."""
    return bool(get_global(MODULE_ID, START_IN_PROGRESS_KEY, True))


def terminal_label(preset: TerminalPreset, installed: bool) -> str:
    label = f"{preset.label} — multiplexer" if preset.multiplexer else preset.label
    return label if installed else f"{label} — not found"


def harness_label(harness: AgentHarness) -> str:
    """The harness's name with what it can do — words derived from the record."""
    abilities = ", ".join(harness.capabilities())
    return f"{harness.label} — {abilities}" if abilities else harness.label


# What used to be prose under each field: standing conventions, so behind the caption's
# glyph (DESIGN.md's *Words*), read once rather than on every visit.
PROFILES_HINT = (
    "Run Agent… runs the default profile — the first, set in bold; Step ▸ Run Agent lists them all."
)
AGENT_HINT = (
    "What the terminal runs. {prompt} is the opening line — one sentence pointing the agent"
    " at the briefing file, never the briefing itself (appended when omitted); {session} is"
    " the run's session id, for an agent that can resume one; {run_dir} is the directory"
    " holding the briefing and its staged files, for an agent that must be allowed to read"
    " there. Picking an agent fills this in."
)
TERMINAL_HINT = (
    "How the terminal opens on the run script. Automatic takes the first installed terminal,"
    " always a new window — a multiplexer only when nothing else is installed; picking one"
    " fills in its command, which can be edited. A multiplexer adds a pane per agent to what"
    " is already running, so several selected steps land side by side. Placeholders:"
    " {script}, {workdir}, {title}; two calls joined by && run in turn, {pane} in the second"
    " being what the first printed."
)
LIMIT_HINT = (
    "How many agents Run Agent may launch from one selection. Each is a terminal, a worktree"
    " and a session of its own; select more than this and the verb says so instead of"
    " filling the desk."
)
LAUNCH_HINT = (
    "Run Agent sets the step's status to in progress as the terminal opens, so the board"
    " shows the work has started without waiting for the agent to say so. It is not undone"
    " when the agent stops: finishing is the agent's own claim, or yours from Step ▸ Status."
)


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
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(PRESET_CHARS)
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
    """The profiles as a table with its verbs on a strip above it (DESIGN.md's *Tables*):
    Add, Remove and Make Default — greyed, with the reason in their words, when they
    cannot run — then Add Detected…. A row is the name over the two commands; the default
    is the first row and the one bold row, the fixed point among them."""

    def __init__(
        self,
        parent: QWidget,
        on_pick: Callable[[int], None],
        harnesses: tuple[AgentHarness, ...] = (),
        platform: str = sys.platform,
    ) -> None:
        super().__init__(parent)
        self._on_pick = on_pick
        self._harnesses, self._platform = harnesses, platform
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(FIELD_GAP)

        self.strip = Toolbar(self)
        self.add_action = self.strip.add_verb(
            "Add", plus_icon, self._add, tip="A copy of the picked profile, named by its choices"
        )
        self.remove_action = self.strip.add_verb("Remove", trash_icon, self._remove)
        self.default_action = self.strip.add_verb(
            "Make Default", star_icon, self._make_default, tip="What a plain Run Agent… runs"
        )
        self.strip.add_divider()
        self.detect_action = self.strip.add_verb(
            "Add Detected…",
            find_icon,
            self._detect,
            tip="Find the agent CLIs and terminals installed here and add their pairings",
        )
        column.addWidget(self.strip)

        self.table = Table((Column("Profile", detail=True, resize="stretch"),), parent=self)
        self.table.horizontalHeader().hide()  # The caption over the block already names it.
        self.table.currentCellChanged.connect(lambda *_cells: self._picked())
        column.addWidget(self.table, 1)
        self.reload(0)

    def reload(self, row: int) -> None:
        profiles = read_profiles()
        chosen = min(max(row, 0), len(profiles) - 1)
        self.table.blockSignals(True)
        self.table.clear_rows()
        for index, profile in enumerate(profiles):
            detail = f"{agent_command(self._harnesses, profile)} · "
            detail += launch_command(profile) or AUTOMATIC_LABEL
            self.table.add_row([Cell(profile.name, detail=detail, emphasis=index == 0)])
        self.table.setCurrentCell(chosen, 0)
        self.table.blockSignals(False)
        self._reword()
        self._on_pick(chosen)

    def _picked(self) -> None:
        self._reword()
        row = self.table.currentRow()
        if row >= 0:
            self._on_pick(row)

    def _reword(self) -> None:
        """Disabled, never hidden — and the reason in the verb's own words."""
        count, row = self.table.rowCount(), self.table.currentRow()
        only = count <= 1
        self.remove_action.setText("Remove — the only profile" if only else "Remove")
        self.remove_action.setEnabled(not only and row >= 0)
        already = row == 0
        self.default_action.setText(
            "Make Default — already the default" if already else "Make Default"
        )
        self.default_action.setEnabled(row > 0)

    def _add(self) -> None:
        profiles = read_profiles()
        picked = profiles[max(self.table.currentRow(), 0)]
        # A new profile starts as a copy of the picked one: the usual reason for a second
        # profile is one thing changed — the terminal, or the agent. It is named by its
        # choices, so the name follows that change until somebody types one.
        copy = Profile("", picked.agent_command, picked.launch_command)
        taken = [p.name for p in profiles]
        name = unique_name(suggested_name(copy, self._harnesses, self._platform), taken)
        write_profiles([*profiles, Profile(name, copy.agent_command, copy.launch_command)])
        self.reload(len(profiles))

    def _remove(self) -> None:
        profiles = read_profiles()
        row = self.table.currentRow()
        if len(profiles) > 1 and 0 <= row < len(profiles):
            del profiles[row]
            write_profiles(profiles)
            self.reload(min(row, len(profiles) - 1))

    def _make_default(self) -> None:
        profiles = read_profiles()
        row = self.table.currentRow()
        if row > 0:
            profiles.insert(0, profiles.pop(row))
            write_profiles(profiles)
            self.reload(0)

    def _detect(self) -> None:
        """Add Detected…: the pairings this machine can run, ticked in a modal, appended
        through the same rule the seed uses — a pairing already meant is never doubled."""
        dialog = DetectedProfilesDialog(self._harnesses, self, platform=self._platform)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            before = len(read_profiles())
            add_profiles(dialog.chosen(), self._harnesses, self._platform)
            self.reload(before)
        dialog.deleteLater()


def build_page(
    parent: QWidget | None,
    platform: str = sys.platform,
    harnesses: tuple[AgentHarness, ...] = (),
) -> QWidget:
    page, layout = settings_page(parent)
    page.setObjectName("AgentSettingsPage")
    current = {"row": 0}

    def commit(**changes: str) -> None:
        """The picked profile's fields written, then the list re-read: the name may have
        followed the change, and the row is what shows it."""
        update_profile(current["row"], harnesses=harnesses, platform=platform, **changes)
        profiles.reload(current["row"])

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
        on_commit=lambda text: commit(agent_command=text),
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
        on_commit=lambda text: commit(launch_command=text),
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
            commit(name=name)

    profiles = ProfileList(page, show_profile, harnesses, platform)
    name_edit.editingFinished.connect(rename)

    limit = QSpinBox(page)
    limit.setObjectName("AgentMaxAgentsSpin")
    limit.setRange(1, MAX_AGENTS_CEILING)
    limit.setValue(max_agents())
    # Arrow steps commit as they land; typing commits on Enter or focus-out, so a
    # half-typed "1" on the way to "12" never becomes the limit for an instant.
    limit.setKeyboardTracking(False)
    limit.valueChanged.connect(lambda value: set_global(MODULE_ID, MAX_AGENTS_KEY, value))

    started_box = QCheckBox("Mark the step in progress when a run starts", page)
    started_box.setObjectName("AgentStartInProgressBox")
    started_box.setChecked(start_in_progress())
    started_box.toggled.connect(lambda on: set_global(MODULE_ID, START_IN_PROGRESS_KEY, bool(on)))

    # The profiles beside the editor for the picked one, as one block under one caption.
    columns_host = QWidget(page)
    columns = QHBoxLayout(columns_host)
    columns.setContentsMargins(0, 0, 0, 0)
    columns.setSpacing(SECTION_GAP)
    columns.addWidget(profiles, 1)
    editor_host = QWidget(columns_host)
    editor = QVBoxLayout(editor_host)
    editor.setContentsMargins(0, 0, 0, 0)
    editor.setSpacing(SECTION_GAP)
    columns.addWidget(editor_host, 1)
    block(editor, caption("Profile name", editor_host), name_edit)
    block(editor, captioned("Agent", editor_host, AGENT_HINT), agent_combo, command_edit)
    block(
        editor,
        captioned("Terminal or multiplexer", editor_host, TERMINAL_HINT),
        terminal_combo,
        terminal_edit,
    )
    editor.addStretch(1)
    block(layout, captioned("Profiles", page, PROFILES_HINT), columns_host)

    limit_row = QWidget(page)
    limit_layout = QHBoxLayout(limit_row)
    limit_layout.setContentsMargins(0, 0, 0, 0)
    limit_layout.addWidget(limit)
    limit_layout.addStretch(1)
    block(layout, captioned("Max agents launched at once", page, LIMIT_HINT), limit_row)
    block(layout, captioned("On launch", page, LAUNCH_HINT), started_box)
    layout.addStretch(1)
    return page
