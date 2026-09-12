"""The Tools action: one dialog for the command, the desktop launcher and the skill.

The dialog's job is to show what this machine has and to change it with one button; the
writing itself is ``cli/install.py``'s and is tested there. So these tests are about the
rows saying what the reader says, the button saying what pressing it would do, and the work
happening off the GUI thread.
"""

import subprocess
import time

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.desktop import DesktopEntry
from dplanner.cli.install import COMMAND, LAUNCHER, SKILL, install_command, tool_bin_command
from dplanner.cli.main import PROG
from dplanner.cli.skill import SKILL_FILE, generate
from dplanner.modules.install import dialog as install_dialog
from dplanner.modules.install.dialog import InstallDialog


def wait_for(app, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the install never finished"
        app.processEvents()
        time.sleep(0.01)


def composition_root_files() -> dict[str, str]:
    from dplanner.modules import aspect_specs, default_cli_commands

    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    return generate(registry, aspect_specs())


class Machine:
    """One machine's worth of state under tmp_path: launcher, skill directory, uv, PATH."""

    def __init__(self, entry, skill_dir, uv_bin):
        self.entry = entry
        self.skill_dir = skill_dir
        self.uv_bin = uv_bin
        self.calls: list[list[str]] = []
        self.installed = False

    def run(self, command):
        self.calls.append(command)
        if command == install_command():
            self.installed = True
        return subprocess.CompletedProcess(command, 0, stdout=f"{self.uv_bin}\n", stderr="")

    def which(self, _name):
        return str(self.uv_bin / PROG) if self.installed else None


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine the dialog can install onto. The dialog reaches disk through
    ``cli/install.py``, so that is where the seams are aimed."""
    quiet = lambda command: subprocess.CompletedProcess(command, 0, stdout="", stderr="")  # noqa: E731
    entry = DesktopEntry(tmp_path / "applications" / "dplanner.desktop", quiet, lambda _n: None)
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    (uv_bin / "dpw").write_text("")
    fake = Machine(entry, tmp_path / "skills" / "dplanner", uv_bin)

    monkeypatch.setattr("dplanner.cli.install.launcher_for", lambda: entry)
    monkeypatch.setattr("dplanner.cli.install.target_dir", lambda **_kwargs: fake.skill_dir)
    monkeypatch.setattr("dplanner.cli.install._run", fake.run)
    monkeypatch.setattr("dplanner.cli.install._which", fake.which)
    monkeypatch.setattr("dplanner.cli.install.worktree_warning", lambda: None)
    monkeypatch.setattr("dplanner.cli.install.window_executable", lambda *_a, **_k: uv_bin / "dpw")
    monkeypatch.setattr(install_dialog, "worktree_warning", lambda: None)
    return fake


def states(dialog) -> dict[str, str]:
    return {
        item_id: row.state.text()
        for item_id, row in zip((COMMAND, LAUNCHER, SKILL), dialog.rows, strict=True)
    }


def test_the_action_opens_the_dialog(services, machine, monkeypatch):
    opened = []
    monkeypatch.setattr(InstallDialog, "exec", lambda self: opened.append(self))

    services.actions.run("install.dplanner", services.context.current())

    (dialog,) = opened
    assert dialog.windowTitle() == "Install DPlanner"
    assert [row.label.text() for row in dialog.rows] == [
        f"{PROG} command",
        "Desktop launcher",
        "Agent skill",
    ]
    assert not machine.entry.path.exists()  # Opening the dialog writes nothing.


def test_the_rows_say_what_this_machine_has(services, machine):
    dialog = InstallDialog(services.tasks, composition_root_files(), None)

    assert states(dialog) == {COMMAND: "missing", LAUNCHER: "missing", SKILL: "missing"}
    assert dialog.primary.text() == "Install"
    assert not dialog.remove_button.isEnabled()


def test_one_button_installs_all_three(app, services, machine):
    files = composition_root_files()
    dialog = InstallDialog(services.tasks, files, None)

    dialog.primary.click()
    wait_for(app, lambda: not dialog._runner.is_busy())
    wait_for(app, lambda: dialog.output.toPlainText() != "")

    assert machine.calls == [tool_bin_command(), install_command()]
    assert machine.entry.target() == machine.uv_bin / "dpw"
    assert (machine.skill_dir / SKILL_FILE).read_text() == files[SKILL_FILE]
    # The rows re-read the disk, so what they show is what is true.
    assert states(dialog)[SKILL] == "installed"
    assert dialog.primary.text() == "Update"
    assert dialog.remove_button.isEnabled()


def test_a_hand_edited_skill_reads_as_stale(app, services, machine):
    files = composition_root_files()
    installed = InstallDialog(services.tasks, files, None)
    installed.primary.click()
    wait_for(app, lambda: not installed._runner.is_busy())
    (machine.skill_dir / SKILL_FILE).write_text("edited by hand\n")

    dialog = InstallDialog(services.tasks, files, None)

    assert states(dialog)[SKILL] == "stale"
    assert dialog.primary.text() == "Update"


def test_a_failed_install_lands_in_the_dialog(app, services, machine, monkeypatch):
    def refuse(command):
        if command == install_command():
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="no network\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("dplanner.cli.install._run", refuse)
    dialog = InstallDialog(services.tasks, composition_root_files(), None)

    dialog.primary.click()
    wait_for(app, lambda: not dialog._runner.is_busy())
    wait_for(app, lambda: dialog.output.toPlainText() != "")

    assert "no network" in dialog.output.toPlainText()
    assert dialog.primary.isEnabled()
    # One piece failing does not stop the others: the skill is still current afterwards.
    assert states(dialog)[SKILL] == "installed"


def test_remove_takes_out_the_launcher_and_the_skill(app, services, machine):
    dialog = InstallDialog(services.tasks, composition_root_files(), None)
    dialog.primary.click()
    wait_for(app, lambda: not dialog._runner.is_busy())

    dialog.remove_button.click()
    wait_for(app, lambda: not dialog._runner.is_busy())
    wait_for(app, lambda: "left alone" in dialog.output.toPlainText())

    assert not machine.entry.path.exists()
    assert not machine.skill_dir.exists()
    assert states(dialog)[LAUNCHER] == "missing"
    assert not dialog.remove_button.isEnabled()


def test_a_worktree_build_says_so(services, machine, monkeypatch):
    monkeypatch.setattr(
        install_dialog, "worktree_warning", lambda: "This build runs from a git worktree (/x)"
    )
    dialog = InstallDialog(services.tasks, composition_root_files(), None)
    assert "worktree" in dialog.worktree_note.text()

    monkeypatch.setattr(install_dialog, "worktree_warning", lambda: None)
    quiet = InstallDialog(services.tasks, composition_root_files(), None)
    assert quiet.worktree_note.isHidden()


def test_the_dialog_writes_what_the_verb_writes(app, services, machine):
    """One implementation, not two: the dialog calls the same functions the CLI runs."""
    from dplanner.cli import install as installer

    dialog = InstallDialog(services.tasks, composition_root_files(), None)
    dialog.primary.click()
    wait_for(app, lambda: not dialog._runner.is_busy())
    from_window = (machine.skill_dir / SKILL_FILE).read_text()

    installer.remove(composition_root_files())
    installer.apply(composition_root_files())

    assert (machine.skill_dir / SKILL_FILE).read_text() == from_window
