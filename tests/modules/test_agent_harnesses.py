"""The agent harnesses: the contract, each provider's reader, the multiplexer rows, and
the launch profiles that pick among them."""

import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QComboBox, QLineEdit

from dplanner.domain.agents import AgentHarness, harness_by_id, harness_for_command
from dplanner.modules import agent_harnesses
from dplanner.modules.agent_codex import harness as codex
from dplanner.modules.step_agent_instruction import launcher
from dplanner.modules.step_agent_instruction.launcher import LaunchFiles

HARNESSES = agent_harnesses()

# -- the contract ------------------------------------------------------------------------------


def test_capabilities_are_derived_from_the_record_never_declared():
    bare = AgentHarness("x", "X", "x {prompt}")
    assert bare.capabilities() == ()
    named = AgentHarness("y", "Y", "y --id {session} {prompt}", resume="y --resume {session}")
    assert named.capabilities() == ("names its session", "resumes")
    found = AgentHarness(
        "z", "Z", "z {prompt}", resume="z resume {session}", report=lambda _f: None
    )
    assert found.capabilities() == ("resumes", "counts tokens")
    # A resume template alone is nothing: with no id up front and no way to find one,
    # the run cannot be picked up.
    assert not AgentHarness("w", "W", "w {prompt}", resume="w {session}").resumes


def test_a_stored_command_text_is_read_as_the_harness_that_shipped_it():
    assert harness_for_command(HARNESSES, "claude --permission-mode plan {prompt}") is HARNESSES[0]
    assert harness_for_command(HARNESSES, " codex {prompt} ") is HARNESSES[1]
    assert harness_for_command(HARNESSES, "my-agent {prompt}") is None
    assert harness_by_id(HARNESSES, "opencode") is HARNESSES[2]
    assert harness_by_id(HARNESSES, "nobody") is None


def test_every_harness_marks_its_shells_and_the_claude_rule_covers_new_names():
    assert HARNESSES[0].marks("CLAUDECODE") and HARNESSES[0].marks("CLAUDE_CODE_BRIDGE_SESSION_ID")
    assert not HARNESSES[0].marks("CLAUDE_CONFIG_DIR")
    assert HARNESSES[1].marks("CODEX_THREAD_ID") and not HARNESSES[1].marks("CODEX_HOME")
    assert HARNESSES[2].marks("OPENCODE") and not HARNESSES[2].marks("OPENCODE_DB")
    env = {"CODEX_THREAD_ID": "t", "OPENCODE": "1", "PATH": "/bin", "CODEX_HOME": "/h"}
    assert launcher.scrubbed_environment(env, HARNESSES) == {"PATH": "/bin", "CODEX_HOME": "/h"}


# -- the multiplexer rows and the staged launch ------------------------------------------------


def fake_files(tmp_path: Path) -> LaunchFiles:
    return LaunchFiles(
        directory=tmp_path,
        prompt_file=tmp_path / "prompt.md",
        script=tmp_path / "run.sh",
        shell_file=tmp_path / "shell",
        exit_file=tmp_path / "exit",
        title="dplanner: S7 Deploy",
    )


def test_herdr_is_a_row_whose_template_is_two_calls(tmp_path):
    """herdr creates the workspace with one call and runs the script into its pane with
    another; the row writes both as one template and spawn stages them."""
    row = next(p for p in launcher.terminals_for("linux") if p.id == "herdr")
    assert row.multiplexer and row.probe == "herdr"
    work = Path("/work")
    command = launcher.resolve_command(row.command, fake_files(tmp_path), work, platform="linux")
    assert command is not None
    assert launcher.stages(command) == [
        [
            "herdr",
            "workspace",
            "create",
            "--cwd",
            str(work),
            "--label",
            "dplanner: S7 Deploy",
            "--no-focus",
        ],
        ["herdr", "pane", "run", "{pane}", str(tmp_path / "run.sh")],
    ]


def test_a_staged_spawn_feeds_the_pane_the_first_call_printed_into_the_second(
    tmp_path, monkeypatch
):
    calls: list[list[str]] = []

    def fake_run(argv, **_kw):
        calls.append(argv)
        out = '{"result": {"workspace": {"workspace_id": "w3"}, "root_pane": {"pane_id": "w3:p1"}}}'
        return subprocess.CompletedProcess(
            argv, 0, stdout=out if len(calls) == 1 else "", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    command = ["herdr", "workspace", "create", "&&", "herdr", "pane", "run", "{pane}", "x"]
    assert launcher.spawn(command, tmp_path) == ""
    assert calls[1] == ["herdr", "pane", "run", "w3:p1", "x"]
    assert launcher.pane_from("%5\n") == "%5" and launcher.pane_from("") == ""


def test_a_stage_that_fails_is_a_reason_and_never_a_run(tmp_path, monkeypatch):
    def fake_run(argv, **_kw):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no herdr server running\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    reason = launcher.spawn(
        ["herdr", "workspace", "create", "&&", "herdr", "pane", "run"], tmp_path
    )
    assert reason == "herdr workspace create failed: no herdr server running"


def test_a_profiles_terminal_is_judged_by_its_rows_probe():
    none = lambda _n: None  # noqa: E731 - a stand-in for shutil.which
    herdr = next(p for p in launcher.terminals_for("linux") if p.id == "herdr")
    assert launcher.template_refusal(herdr.command, "linux", which=none, env={}) == (
        "herdr is not installed"
    )
    assert launcher.template_refusal(herdr.command, "linux", which=lambda _n: "/bin/herdr") == ""
    tmux = next(p for p in launcher.terminals_for("linux") if p.id == "tmux")
    assert "TMUX is not set" in launcher.template_refusal(tmux.command, "linux", which=none, env={})
    assert launcher.template_refusal("", "linux", which=none, env={}) == ""  # Automatic falls back.
    assert launcher.template_refusal("myterm -e {script}", "linux", which=none, env={}) == ""


def test_the_wrapper_records_the_multiplexers_own_names_for_the_pane(tmp_path):
    posix = launcher.prepare("p", tmp_path, platform="linux", harnesses=HARNESSES)
    script = posix.script.read_text()
    assert "herdr_workspace=%s" in script and '"$HERDR_WORKSPACE_ID" "$HERDR_TAB_ID"' in script
    assert '"$WEZTERM_PANE"' in script
    windows = launcher.prepare("p", tmp_path, platform="win32", harnesses=HARNESSES)
    assert "'herdr_workspace=' + $env:HERDR_WORKSPACE_ID" in windows.script.read_text()


# -- profiles ---------------------------------------------------------------------------------


def test_the_two_old_settings_read_as_the_default_profile(app):
    from dplanner.framework.user_config import set_global
    from dplanner.modules.step_agent_instruction.profiles import (
        AGENT_COMMAND_KEY,
        LAUNCH_COMMAND_KEY,
        Profile,
        default_profile,
        read_profiles,
        write_profiles,
    )
    from dplanner.planning.agent import MODULE_ID

    set_global(MODULE_ID, AGENT_COMMAND_KEY, "codex {prompt}")
    set_global(MODULE_ID, LAUNCH_COMMAND_KEY, "kitty {script}")
    assert read_profiles() == [Profile("Default", "codex {prompt}", "kitty {script}")]
    write_profiles([Profile("Mine", "", ""), Profile("Codex in herdr", "codex {prompt}", "h")])
    assert default_profile() == Profile("Mine", "", "")
    assert [p.name for p in read_profiles()] == ["Mine", "Codex in herdr"]


def test_the_known_pairings_are_seeded_once_and_never_doubled(app):
    """Every harness in Ghostty, herdr and Automatic, added after what is stored — a
    pairing already there by its choices is skipped whatever it is named, the stored
    default stays first, and a second seed (or a removal) is honoured by the flag."""
    from dplanner.framework.user_config import get_global
    from dplanner.modules.step_agent_instruction.launcher import HERDR_COMMAND
    from dplanner.modules.step_agent_instruction.profiles import (
        SEEDED_KEY,
        Profile,
        read_profiles,
        seed_profiles,
        write_profiles,
    )
    from dplanner.planning.agent import MODULE_ID

    write_profiles([Profile("Mine", "", "ghostty -e {script}"), Profile("Codex", "codex {prompt}")])
    added = seed_profiles(HARNESSES, platform="linux")
    names = [p.name for p in read_profiles()]
    assert names[:2] == ["Mine", "Codex"]  # The stored list, its default still first.
    assert (
        [p.name for p in added]
        == names[2:]
        == [
            "Claude Code in herdr",
            "Claude Code",
            "Codex in Ghostty",
            "Codex in herdr",
            "OpenCode in Ghostty",
            "OpenCode in herdr",
            "OpenCode",
        ]
    )
    herdr = next(p for p in added if p.name == "Codex in herdr")
    assert (herdr.agent_command, herdr.launch_command) == ("codex {prompt}", HERDR_COMMAND)
    assert get_global(MODULE_ID, SEEDED_KEY) is True
    # Seeded: a removal stands, and nothing is added twice.
    write_profiles(read_profiles()[:3])
    assert seed_profiles(HARNESSES, platform="linux") == []
    assert len(read_profiles()) == 3


def test_a_fresh_machine_is_seeded_around_its_default_and_no_harness_seeds_nothing(app):
    from dplanner.framework.user_config import get_global
    from dplanner.modules.step_agent_instruction.profiles import (
        SEEDED_KEY,
        read_profiles,
        seed_profiles,
    )
    from dplanner.planning.agent import MODULE_ID

    assert seed_profiles((), platform="linux") == [] and get_global(MODULE_ID, SEEDED_KEY) is None
    seed_profiles(HARNESSES, platform="darwin")
    names = [p.name for p in read_profiles()]
    # The unnamed old-settings profile — Claude Code in Automatic — is named by its
    # choices as it is first written, and stands for that pairing, so it is not doubled.
    assert names[:3] == ["Claude Code", "Claude Code in Ghostty", "Claude Code in herdr"]
    assert names.count("Claude Code") == 1 and len(names) == 9
    assert len({(p.agent_command, p.launch_command) for p in read_profiles()}) == 9


def test_the_window_seeds_the_profiles_when_it_is_built(services):
    from dplanner.modules.step_agent_instruction.profiles import read_profiles

    assert len(read_profiles()) == 9


def test_manage_agent_profiles_opens_settings_on_the_profiles_page(services, monkeypatch):
    from dplanner.modules.settings.module import SettingsModule
    from dplanner.modules.step_agent_instruction.module import SETTINGS_SECTION

    settings = next(m for m in services.modules if isinstance(m, SettingsModule))
    monkeypatch.setattr(settings.dialog, "show", lambda: None)
    services.actions.run("agent.profiles", services.context.current())
    current = settings.dialog._tree.currentItem()
    assert current is not None and current.text(0) == "Agent profiles"
    assert settings.dialog._pane.currentWidget() is settings.dialog._pages[SETTINGS_SECTION]
    spec = services.actions.spec("agent.profiles")
    assert (spec.menu, spec.submenu, spec.in_menus) == ("Step", "Run Agent", False)


def test_detection_pairs_what_this_machine_has_and_says_what_it_lacks(app):
    """Every harness in every terminal row and Automatic: the agent by its command on
    PATH, the terminal by its row's probe, a stored pairing marked present."""
    from dplanner.modules.step_agent_instruction.launcher import HERDR_COMMAND
    from dplanner.modules.step_agent_instruction.profiles import (
        Profile,
        detect_pairings,
        write_profiles,
    )

    write_profiles([Profile("Mine", "", "ghostty -e {script}")])
    found = {"claude": "/bin/claude", "ghostty": "/bin/ghostty", "herdr": "/bin/herdr"}
    rows = detect_pairings(HARNESSES, platform="linux", which=found.get, env={})
    by_name = {row.profile.name: row for row in rows}
    assert by_name["Claude Code in Ghostty"].present  # "Mine" already means it.
    assert by_name["Claude Code in Ghostty"].remark == "already in the list"
    herdr = by_name["Claude Code in herdr"]
    assert herdr.runnable and not herdr.present and herdr.remark == ""
    assert herdr.profile.launch_command == HERDR_COMMAND
    assert by_name["Claude Code"].runnable  # Automatic is always found.
    assert by_name["Codex in herdr"].remark == "codex not found"
    assert by_name["Codex in kitty"].remark == "codex not found, terminal not found"
    assert not by_name["Claude Code in tmux"].terminal_found  # env probe, $TMUX unset.
    assert [r.profile.name for r in rows if r.runnable and not r.present] == [
        "Claude Code in herdr",
        "Claude Code",
    ]


def test_the_detected_profiles_dialog_ticks_the_runnable_and_adds_the_ticked(app):
    from PySide6.QtCore import Qt

    from dplanner.modules.step_agent_instruction.detect_dialog import (
        NOTHING_TICKED,
        DetectedProfilesDialog,
    )
    from dplanner.modules.step_agent_instruction.profiles import (
        Profile,
        add_profiles,
        read_profiles,
        write_profiles,
    )

    write_profiles([Profile("Mine", "", "ghostty -e {script}")])
    found = {"claude": "/bin/claude", "codex": "/bin/codex", "ghostty": "/bin/ghostty"}
    dialog = DetectedProfilesDialog(HARNESSES, platform="linux", which=found.get, env={})
    ticked = [p.name for p in dialog.chosen()]
    assert ticked == ["Claude Code", "Codex in Ghostty", "Codex"]
    assert dialog.primary_button.text() == "Add 3 Profiles" and dialog.primary_button.isEnabled()
    present = next(i for i in range(dialog.list.count()) if "already" in dialog.list.item(i).text())
    assert not dialog.list.item(present).flags() & Qt.ItemFlag.ItemIsEnabled
    for index in range(dialog.list.count()):
        dialog.list.item(index).setCheckState(Qt.CheckState.Unchecked)
    assert not dialog.primary_button.isEnabled() and dialog.status.words() == NOTHING_TICKED
    dialog.list.item(dialog.list.count() - 1).setCheckState(Qt.CheckState.Checked)  # OpenCode.
    assert dialog.primary_button.text() == "Add Profile"
    added = add_profiles(dialog.chosen(), HARNESSES, "linux")
    assert [p.name for p in added] == ["OpenCode"]
    assert [p.name for p in read_profiles()] == ["Mine", "OpenCode"]
    assert add_profiles(dialog.chosen(), HARNESSES, "linux") == []  # Meant already.
    dialog.deleteLater()


def test_the_settings_page_adds_the_detected_profiles(app, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from dplanner.modules.step_agent_instruction import settings_page
    from dplanner.modules.step_agent_instruction.detect_dialog import DetectedProfilesDialog
    from dplanner.modules.step_agent_instruction.profiles import (
        Profile,
        read_profiles,
        write_profiles,
    )

    write_profiles([Profile("Mine", "", "")])
    found = {"claude": "/bin/claude", "ghostty": "/bin/ghostty"}

    class Detected(DetectedProfilesDialog):
        def __init__(self, harnesses, parent=None, *, platform):
            super().__init__(harnesses, parent, platform=platform, which=found.get, env={})

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(settings_page, "DetectedProfilesDialog", Detected)
    page = settings_page.build_page(None, platform="linux", harnesses=HARNESSES)
    profiles = page.findChild(settings_page.ProfileList)
    assert profiles is not None
    profiles.detect_action.trigger()
    assert [p.name for p in read_profiles()] == ["Mine", "Claude Code in Ghostty"]
    page.deleteLater()


def test_a_profile_is_named_by_its_choices():
    from dplanner.modules.step_agent_instruction.profiles import Profile, suggested_name

    def named(agent, terminal):
        return suggested_name(Profile("", agent, terminal), HARNESSES, platform="linux")

    assert named("", "") == "Claude Code"  # The first harness, in Automatic.
    assert named("codex {prompt}", launcher.HERDR_COMMAND) == "Codex in herdr"
    assert named("", "tmux new-window -c {workdir} {script}") == "Claude Code in tmux"
    assert named("aider --yes {prompt}", "foot {script}") == "aider in foot"
    assert named("", "myterm -x {script}") == "Claude Code in myterm"


def test_a_name_nobody_typed_follows_the_choices_and_a_typed_one_stays(app):
    from dplanner.modules.step_agent_instruction.profiles import (
        Profile,
        read_profiles,
        update_profile,
        write_profiles,
    )

    def change(index, **changes):
        update_profile(index, harnesses=HARNESSES, platform="linux", **changes)
        return [p.name for p in read_profiles()]

    write_profiles([Profile("Default"), Profile("Claude Code"), Profile("Claude Code 2")])
    # A numbered name is still the derived one, and follows.
    assert change(2, launch_command=launcher.HERDR_COMMAND)[2] == "Claude Code in herdr"
    assert change(2, agent_command="codex {prompt}")[2] == "Codex in herdr"
    assert change(2, name="Mine")[2] == "Mine"
    assert change(2, launch_command="")[2] == "Mine"  # A person's word is kept.
    assert change(1, name="Mine") == ["Default", "Mine 2", "Mine"]  # Never two of a name.


def test_the_settings_page_adds_removes_and_promotes_profiles(app):
    from dplanner.framework.list_rows import EMPHASIS_ROLE
    from dplanner.modules.step_agent_instruction.profiles import read_profiles
    from dplanner.modules.step_agent_instruction.settings_page import ProfileList, build_page

    page = build_page(None, platform="linux", harnesses=HARNESSES)
    profiles = page.findChild(ProfileList)
    name = page.findChild(QLineEdit, "AgentProfileName")
    agent = page.findChild(QComboBox, "AgentPresetCombo")
    terminal = page.findChild(QLineEdit, "AgentLaunchCommandEdit")
    assert profiles is not None and isinstance(agent, QComboBox)
    assert isinstance(name, QLineEdit) and isinstance(terminal, QLineEdit)
    listing = profiles.table
    add, remove = profiles.add_action, profiles.remove_action
    promote = profiles.default_action
    assert listing.rowCount() == 1 and not remove.isEnabled() and not promote.isEnabled()
    # Disabled, never hidden — and the reason is in the verb's own words.
    assert remove.text() == "Remove — the only profile"
    assert promote.text() == "Make Default — already the default"

    add.trigger()  # A copy of the picked profile, named by its choices.
    assert [p.name for p in read_profiles()] == ["Default", "Claude Code"]
    assert listing.currentRow() == 1 and remove.isEnabled() and promote.isEnabled()
    name.setText("Codex in herdr")
    name.editingFinished.emit()
    codex_row = next(i for i in range(agent.count()) if agent.itemText(i).startswith("Codex"))
    agent.setCurrentIndex(codex_row)
    agent.activated.emit(codex_row)
    terminal.setText(launcher.HERDR_COMMAND)
    terminal.editingFinished.emit()
    second = read_profiles()[1]
    assert (second.name, second.agent_command, second.launch_command) == (
        "Codex in herdr",
        "codex {prompt}",
        launcher.HERDR_COMMAND,
    )

    promote.trigger()
    assert [p.name for p in read_profiles()] == ["Codex in herdr", "Default"]
    first = listing.item(0, 0)
    assert first is not None
    assert first.text() == "Codex in herdr" and first.data(EMPHASIS_ROLE)  # The bold row.
    listing.setCurrentCell(1, 0)
    remove.trigger()
    assert [p.name for p in read_profiles()] == ["Codex in herdr"]
    page.deleteLater()


def test_the_settings_page_renames_a_profile_as_its_choices_change(app):
    """Add, then pick a terminal, then an agent: the name keeps up, and the list shows
    it. Type a name and it is yours through every later change."""
    from dplanner.modules.step_agent_instruction.profiles import read_profiles
    from dplanner.modules.step_agent_instruction.settings_page import ProfileList, build_page

    page = build_page(None, platform="linux", harnesses=HARNESSES)
    profiles = page.findChild(ProfileList)
    name = page.findChild(QLineEdit, "AgentProfileName")
    terminal = page.findChild(QLineEdit, "AgentLaunchCommandEdit")
    assert profiles is not None
    assert isinstance(name, QLineEdit) and isinstance(terminal, QLineEdit)
    listing, add = profiles.table, profiles.add_action

    add.trigger()
    terminal.setText(launcher.HERDR_COMMAND)
    terminal.editingFinished.emit()
    assert [p.name for p in read_profiles()] == ["Default", "Claude Code in herdr"]
    second = listing.item(1, 0)
    assert second is not None and second.text() == "Claude Code in herdr"
    assert name.text() == "Claude Code in herdr"
    add.trigger()  # A copy of the herdr profile: the same name, numbered.
    assert read_profiles()[2].name == "Claude Code in herdr 2"
    terminal.setText("ghostty -e {script}")
    terminal.editingFinished.emit()
    assert read_profiles()[2].name == "Claude Code in Ghostty"
    name.setText("Mine")
    name.editingFinished.emit()
    terminal.setText("")
    terminal.editingFinished.emit()
    assert read_profiles()[2].name == "Mine"  # Typed, so it stays.
    page.deleteLater()


@pytest.fixture
def step(services, make_project):
    from dplanner.domain.commands import AddNodeCommand
    from dplanner.domain.model import Step

    project = make_project("Discovery", legacy=True)
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    return step


def select(services, *steps):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(
        SCOPE_SELECTION, tuple(ContextNode(selection_uri("step", s.id)) for s in steps)
    )


def test_run_agent_with_lists_the_profiles_and_launches_through_the_picked_one(
    services, step, monkeypatch
):
    """The child menu is rebuilt on open with one entry per profile — the default marked,
    a profile whose terminal is missing greyed with that reason — and an entry runs the
    same launch as Run Agent, through that profile's agent and terminal."""
    from dplanner.modules.step_agent_instruction.profiles import Profile, write_profiles

    write_profiles(
        [
            Profile("Claude in Ghostty", "", "ghostty -e {script}"),
            Profile("Codex in herdr", "codex {prompt}", launcher.HERDR_COMMAND),
        ]
    )
    monkeypatch.setattr(
        launcher,
        "template_refusal",
        lambda t, *a, **k: "herdr is not installed" if t == launcher.HERDR_COMMAND else "",
    )
    select(services, step)
    menu = services.window.dynamic_menubar.data_menu("agent.run_with")
    labels = [a.text() for a in menu.actions()]
    assert labels == [
        "Claude in Ghostty (default)",
        "Codex in herdr — herdr is not installed",
        "",  # The rule before the way to Settings.
        "&Manage Agent Profiles…",
    ]
    assert menu.actions()[0].isEnabled() and not menu.actions()[1].isEnabled()
    assert menu.actions()[2].isSeparator() and menu.actions()[3].isEnabled()
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.enabled  # Run Agent… is the default profile, whose terminal is fine.
    # The verb's seat is the child menu: neither it nor the Settings link is listed flat.
    step_menu = services.window.dynamic_menubar._menus["Step"]
    flat = [a.text() for a in step_menu.actions() if not a.isSeparator()]
    assert "Run &Agent…" not in flat and "&Manage Agent Profiles…" not in flat
    assert "Run Agent" in flat  # The child menu's own entry.

    monkeypatch.setattr(launcher, "template_refusal", lambda *a, **k: "")
    launched: list[tuple[list[str], str]] = []

    def fake_spawn(command, _cwd, **_kw):
        launched.append((command, ""))
        return ""

    monkeypatch.setattr(launcher, "spawn", fake_spawn)
    menu = services.window.dynamic_menubar.data_menu("agent.run_with")
    assert menu.actions()[1].isEnabled()
    menu.actions()[1].trigger()
    ((command, _),) = launched
    assert command[:3] == ["herdr", "workspace", "create"] and "&&" in command
    from dplanner.modules.step_agent_run.aspect import MODULE_ID as RUN_ID

    runs = next(m for m in services.modules if m.id == RUN_ID).runs()
    assert [(run.harness, run.session) for run in runs] == [("codex", "")]  # Found afterwards.
    # The wrapper the real launcher wrote for *this* host — run.sh here, run.cmd on Windows —
    # and the assertion is that the picked harness is the one in it, not how a shell quotes.
    run_dir = Path(runs[0].shell_file).parent
    (script,) = [path for path in run_dir.iterdir() if path.stem == "run"]
    assert "codex" in script.read_text(encoding="utf-8") and "Read your briefing" in (
        script.read_text(encoding="utf-8")
    )


def test_run_agent_records_the_harness_and_the_session_it_named(services, step, monkeypatch):
    monkeypatch.setattr(launcher, "spawn", lambda *_a, **_k: "")
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    select(services, step)
    services.actions.run("agent.run", services.context.current())
    from dplanner.modules.step_agent_run.aspect import MODULE_ID as RUN_ID

    (run,) = next(m for m in services.modules if m.id == RUN_ID).runs()
    assert run.harness == "claude" and len(run.session) == 36


def test_a_multiplexer_that_refuses_is_no_shell_at_all(services, step, monkeypatch):
    """A workspace herdr could not create stamps nothing: the fallback hands the prompt over."""
    import dplanner.modules.step_agent_instruction.module as agent_module
    from dplanner.modules.step_agent_run.aspect import read as run_state

    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["herdr", "x", "&&", "y"])
    monkeypatch.setattr(launcher, "spawn", lambda *_a, **_k: "herdr workspace create failed: down")
    shown = []

    class SilentDialog:
        def __init__(self, *args, **kwargs):
            shown.append(args)

        def exec(self):
            return 0

    monkeypatch.setattr(agent_module, "PromptFallbackDialog", SilentDialog)
    select(services, step)
    services.actions.run("agent.run", services.context.current())
    assert shown and run_state(services.document.step(step.id)) == ""


def test_open_agent_in_code_offers_the_same_profiles_over_the_project(services, step, monkeypatch):
    """One list of profiles, two child menus: *Open Agent in Code* asks each entry the
    project's questions instead of the step's, and the entry launches through that
    profile's agent and terminal exactly as Run Agent's does."""
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
    from dplanner.modules.step_agent_instruction.profiles import Profile, write_profiles

    write_profiles(
        [
            Profile("Claude in Ghostty", "", "ghostty -e {script}"),
            Profile("Codex in herdr", "codex {prompt}", launcher.HERDR_COMMAND),
        ]
    )
    monkeypatch.setattr(
        launcher,
        "template_refusal",
        lambda t, *a, **k: "herdr is not installed" if t == launcher.HERDR_COMMAND else "",
    )
    project = services.document.project_of(step.id)
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    menu = services.window.dynamic_menubar.data_menu("agent.open_with")
    assert [a.text() for a in menu.actions()] == [
        "Claude in Ghostty (default)",
        "Codex in herdr — herdr is not installed",
        "",  # The rule before the way to Settings.
        "&Manage Agent Profiles…",
    ]
    assert menu.actions()[0].isEnabled() and not menu.actions()[1].isEnabled()
    # The verb's seat is the child menu: it is not listed flat beside it.
    project_menu = services.window.dynamic_menubar._menus["Project"]
    flat = [a.text() for a in project_menu.actions() if not a.isSeparator()]
    assert "&Open Agent in Code…" not in flat and "Open Agent in Code" in flat

    monkeypatch.setattr(launcher, "template_refusal", lambda *a, **k: "")
    launched: list[list[str]] = []
    monkeypatch.setattr(launcher, "spawn", lambda command, _cwd, **_kw: launched.append(command))
    prepared: list[LaunchFiles] = []
    real = launcher.prepare

    def capture(*args, **kwargs):
        prepared.append(files := real(*args, **kwargs))
        return files

    monkeypatch.setattr(launcher, "prepare", capture)
    menu = services.window.dynamic_menubar.data_menu("agent.open_with")
    menu.actions()[1].trigger()
    ((command),) = launched
    assert command[:3] == ["herdr", "workspace", "create"]
    # Codex's bare invocation, in the wrapper the real launcher wrote for this host, and
    # no briefing anywhere near it.
    (files,) = prepared
    assert not files.prompt_file.exists() and files.opening == ""
    script = files.script.read_text(encoding="utf-8")
    assert "codex" in script and "Read your briefing" not in script


def test_plan_mode_is_read_off_the_command_a_profile_runs():
    """Claude's preset starts in plan mode and waits for a person; a profile edited out of
    it does not, and neither does a CLI with no such mode."""
    harnesses = agent_harnesses()
    assert launcher.plans_first("", harnesses)  # Blank is the first harness's preset.
    assert launcher.plans_first("claude --permission-mode plan {prompt}", harnesses)
    assert not launcher.plans_first("claude --permission-mode acceptEdits {prompt}", harnesses)
    assert not launcher.plans_first(codex.HARNESS.command, harnesses)
