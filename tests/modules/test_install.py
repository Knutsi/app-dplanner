"""The Tools actions: the skill dialog, and the install that puts dplanner on PATH."""

import shlex
import subprocess
import time

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.desktop import DesktopEntry
from dplanner.cli.skill import (
    REFERENCE_FILE,
    SKILL_FILE,
    generate,
    install_command,
    tool_bin_command,
    uninstall_command,
)
from dplanner.modules.install.command_dialog import CommandInstallDialog
from dplanner.modules.install.skill_dialog import AgentSkillDialog


def wait_for(app, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the install never finished"
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def skill_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / ".claude" / "skills" / "dplanner"


def composition_root_files() -> dict[str, str]:
    from dplanner.modules import aspect_specs, default_cli_commands

    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    return generate(registry, aspect_specs())


def test_the_action_opens_the_dialog(services, skill_home, monkeypatch):
    opened = []
    monkeypatch.setattr(AgentSkillDialog, "exec", lambda self: opened.append(self))

    services.actions.run("install.skill", services.context.current())

    (dialog,) = opened
    assert dialog._directory == skill_home
    contents = [dialog.tabs.widget(i).toPlainText() for i in range(dialog.tabs.count())]
    files = composition_root_files()
    assert contents == [files[SKILL_FILE], files[REFERENCE_FILE]]
    assert not (skill_home / SKILL_FILE).exists()  # previewing writes nothing


def test_installing_from_the_dialog_writes_what_the_cli_writes(services, skill_home):
    """One generator, not two: a second implementation would drift within a month."""
    files = composition_root_files()
    dialog = AgentSkillDialog(files, skill_home, None)
    assert dialog.primary.text() == "Install"
    assert not dialog.remove_button.isEnabled()

    dialog.primary.click()

    assert (skill_home / SKILL_FILE).read_text() == files[SKILL_FILE]
    assert (skill_home / REFERENCE_FILE).read_text() == files[REFERENCE_FILE]
    assert not dialog.primary.isEnabled()
    assert dialog.remove_button.isEnabled()


def test_a_hand_edited_skill_reads_as_stale(services, skill_home):
    files = composition_root_files()
    installer = AgentSkillDialog(files, skill_home, None)
    installer.primary.click()
    (skill_home / SKILL_FILE).write_text("edited by hand\n")

    dialog = AgentSkillDialog(files, skill_home, None)
    assert dialog.primary.text() == "Update"
    assert dialog.primary.isEnabled()

    dialog.primary.click()
    assert (skill_home / SKILL_FILE).read_text() == files[SKILL_FILE]


def test_the_dialog_says_when_the_command_is_not_on_path(services, skill_home, monkeypatch):
    monkeypatch.setattr(
        "dplanner.modules.install.skill_dialog.path_hint", lambda: "uv tool install --editable /x"
    )
    dialog = AgentSkillDialog(composition_root_files(), skill_home, None)
    assert "not on PATH" in dialog.path_note.text()
    assert "uv tool install --editable /x" in dialog.path_note.text()

    monkeypatch.setattr("dplanner.modules.install.skill_dialog.path_hint", lambda: None)
    quiet = AgentSkillDialog(composition_root_files(), skill_home, None)
    assert quiet.path_note.isHidden()


def test_remove_deletes_the_skill(services, skill_home):
    files = composition_root_files()
    dialog = AgentSkillDialog(files, skill_home, None)
    dialog.primary.click()

    dialog.remove_button.click()

    assert not skill_home.exists()
    assert dialog.primary.text() == "Install"
    assert dialog.primary.isEnabled()
    assert not dialog.remove_button.isEnabled()


# -- the command install -----------------------------------------------------------------------


def test_the_cli_install_dialog_shows_and_runs_the_command(app, services, monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="Installed dplanner\n", stderr="")

    monkeypatch.setattr("dplanner.modules.install.command_dialog.subprocess.run", fake_run)
    dialog = CommandInstallDialog(services.tasks, None)
    assert dialog.command.text() == shlex.join(install_command())

    dialog.launcher_box.setChecked(False)  # The launcher has its own tests below.
    dialog.primary.click()
    wait_for(app, lambda: not dialog._runner.is_busy())

    assert calls == [install_command()]
    assert "Installed dplanner" in dialog.output.toPlainText()
    assert dialog.primary.isEnabled()


def test_a_failed_install_lands_in_the_dialog(app, services, monkeypatch):
    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="no network\n")

    monkeypatch.setattr("dplanner.modules.install.command_dialog.subprocess.run", fake_run)
    dialog = CommandInstallDialog(services.tasks, None)

    dialog.primary.click()
    wait_for(app, lambda: not dialog._runner.is_busy())
    wait_for(app, lambda: dialog.output.toPlainText() != "")

    assert "no network" in dialog.output.toPlainText()
    assert dialog.primary.isEnabled()


def test_uninstall_runs_the_uninstall_command(app, services, monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="Uninstalled dplanner\n", stderr="")

    monkeypatch.setattr("dplanner.modules.install.command_dialog.subprocess.run", fake_run)
    monkeypatch.setattr(
        "dplanner.modules.install.command_dialog.shutil.which",
        lambda _name: "/home/x/.local/bin/dplanner",
    )
    dialog = CommandInstallDialog(services.tasks, None)
    assert dialog.primary.text() == "Reinstall"
    assert dialog.uninstall_button.isEnabled()

    dialog.uninstall_button.click()
    wait_for(app, lambda: not dialog._runner.is_busy())
    wait_for(app, lambda: dialog.output.toPlainText() != "")

    assert calls == [uninstall_command()]
    assert "Uninstalled dplanner" in dialog.output.toPlainText()


def test_uninstall_is_disabled_when_nothing_resolves(services, monkeypatch):
    monkeypatch.setattr("dplanner.modules.install.command_dialog.shutil.which", lambda _name: None)
    dialog = CommandInstallDialog(services.tasks, None)
    assert not dialog.uninstall_button.isEnabled()


def test_a_worktree_build_warns_in_the_dialog(services, monkeypatch):
    monkeypatch.setattr(
        "dplanner.modules.install.command_dialog.worktree_warning",
        lambda: "This build runs from a git worktree (/x)",
    )
    dialog = CommandInstallDialog(services.tasks, None)
    assert "worktree" in dialog.worktree_note.text()

    monkeypatch.setattr("dplanner.modules.install.command_dialog.worktree_warning", lambda: None)
    assert CommandInstallDialog(services.tasks, None).worktree_note.isHidden()


# -- the desktop launcher, in the same go ------------------------------------------------------


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    """The dialog over a Linux entry under tmp_path, with a known dpw to point it at."""
    quiet = lambda command: subprocess.CompletedProcess(command, 0, stdout="", stderr="")  # noqa: E731
    entry = DesktopEntry(tmp_path / "applications" / "dplanner.desktop", quiet, lambda _n: None)
    monkeypatch.setattr("dplanner.modules.install.command_dialog.launcher_for", lambda: entry)
    monkeypatch.setattr(
        "dplanner.modules.install.command_dialog.window_executable",
        lambda *_a, **_k: tmp_path / "bin" / "dpw",
    )
    return entry


def test_installing_the_command_writes_the_desktop_launcher_in_the_same_go(
    app, services, monkeypatch, launcher, tmp_path
):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="Installed dplanner\n", stderr="")

    monkeypatch.setattr("dplanner.modules.install.command_dialog.subprocess.run", fake_run)
    dialog = CommandInstallDialog(services.tasks, None)
    assert dialog.launcher_box.isChecked()
    assert str(launcher.path) in dialog.launcher_box.text()

    dialog.primary.click()
    wait_for(app, lambda: not dialog._runner.is_busy())
    wait_for(app, lambda: dialog.output.toPlainText() != "")

    assert calls == [install_command(), tool_bin_command()]  # Asks uv where dpw went.
    assert launcher.target() == tmp_path / "bin" / "dpw"
    assert f"Desktop launcher: {launcher.path}" in dialog.output.toPlainText()


def test_unticked_the_launcher_is_left_alone(app, services, monkeypatch, launcher):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="Installed dplanner\n", stderr="")

    monkeypatch.setattr("dplanner.modules.install.command_dialog.subprocess.run", fake_run)
    dialog = CommandInstallDialog(services.tasks, None)
    dialog.launcher_box.setChecked(False)
    dialog.primary.click()
    wait_for(app, lambda: not dialog._runner.is_busy())
    wait_for(app, lambda: dialog.output.toPlainText() != "")
    assert calls == [install_command()]
    assert launcher.target() is None


def test_uninstalling_the_command_removes_the_launcher(app, services, monkeypatch, launcher):
    launcher.write(launcher.path.parent.parent / "bin" / "dpw")

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="Uninstalled dplanner\n", stderr="")

    monkeypatch.setattr("dplanner.modules.install.command_dialog.subprocess.run", fake_run)
    monkeypatch.setattr(
        "dplanner.modules.install.command_dialog.shutil.which",
        lambda _name: "/home/x/.local/bin/dplanner",
    )
    dialog = CommandInstallDialog(services.tasks, None)
    dialog.uninstall_button.click()
    wait_for(app, lambda: not dialog._runner.is_busy())
    wait_for(app, lambda: dialog.output.toPlainText() != "")
    assert not launcher.path.exists()
    assert f"Removed the desktop launcher: {launcher.path}" in dialog.output.toPlainText()
