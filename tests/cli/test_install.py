"""Installing DPlanner as one act: the command, the desktop launcher and the agent skill.

Every test here builds over a ``tmp_path`` launcher and skill directory with a recording
process runner, so nothing reaches the machine the suite runs on — which is the same reason
``apply`` takes all three as arguments.
"""

import json
import subprocess
from io import StringIO
from pathlib import Path

import pytest
from tests.platforms import executable_name

from dplanner.cli import install as installer
from dplanner.cli.desktop import DesktopEntry
from dplanner.cli.install import (
    COMMAND,
    LAUNCHER,
    SKILL,
    apply,
    install_command,
    items,
    remove,
    summary,
    tool_bin_command,
    uninstall_command,
)
from dplanner.cli.main import PROG, run
from dplanner.cli.skill import SKILL_FILE
from dplanner.modules import default_module_formats

FILES = {SKILL_FILE: "the skill, as this build renders it\n"}


class Recorder:
    """A process runner that records what it was asked and answers success."""

    def __init__(self, stdout: str = "") -> None:
        self.calls: list[list[str]] = []
        self.stdout = stdout

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=self.stdout, stderr="")


def nothing(_name: str) -> str | None:
    return None


@pytest.fixture
def launcher(tmp_path):
    """A Linux entry under tmp_path — the contract is the same on every platform."""
    return DesktopEntry(tmp_path / "applications" / "dplanner.desktop", Recorder(), nothing)


@pytest.fixture
def skill_dir(tmp_path):
    return tmp_path / "skills" / "dplanner"


@pytest.fixture
def main_checkout(monkeypatch):
    """This build reads as a main checkout, so the command is ours to write."""
    monkeypatch.setattr(installer, "worktree_warning", lambda: None)


def read(launcher, skill_dir, which=nothing):
    return items(FILES, launcher=launcher, directories=(skill_dir,), which=which)


def by_id(read_items):
    return {item.id: item for item in read_items}


# -- what this machine has ---------------------------------------------------------------------


def test_a_bare_machine_is_missing_all_three(launcher, skill_dir):
    found = by_id(read(launcher, skill_dir))

    assert [item.state for item in read(launcher, skill_dir)] == ["missing"] * 3
    assert summary(read(launcher, skill_dir)) == "missing"
    assert "Not on PATH" in found[COMMAND].note
    assert found[LAUNCHER].where == launcher.path
    assert found[SKILL].where == skill_dir


def test_the_command_is_installed_or_missing_and_never_stale(launcher, skill_dir, tmp_path):
    """Whether the dplanner on PATH came from this build cannot be told without running
    it, and a status read may not — so the honest answer has two values."""
    where = tmp_path / "bin" / PROG
    found = by_id(read(launcher, skill_dir, which=lambda _name: str(where)))

    assert found[COMMAND].state == "installed"
    assert found[COMMAND].where == where
    assert str(where) in found[COMMAND].note


def test_each_piece_reads_its_own_state(launcher, skill_dir, tmp_path):
    launcher.write(tmp_path / "elsewhere" / "dpw")  # Opens something that is not this build.
    skill_dir.mkdir(parents=True)
    (skill_dir / SKILL_FILE).write_text("edited by hand\n")

    found = by_id(read(launcher, skill_dir, which=lambda _name: str(tmp_path / "bin" / PROG)))

    assert found[COMMAND].state == "installed"
    assert found[LAUNCHER].state == "stale"
    assert found[SKILL].state == "stale"
    assert summary(list(found.values())) == "stale"


def test_a_current_skill_says_so(launcher, skill_dir):
    skill_dir.mkdir(parents=True)
    (skill_dir / SKILL_FILE).write_text(FILES[SKILL_FILE])

    assert by_id(read(launcher, skill_dir))[SKILL].state == "installed"


# -- the one act -------------------------------------------------------------------------------


def test_installing_writes_all_three_in_order(launcher, skill_dir, tmp_path, main_checkout):
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    (uv_bin / executable_name("dpw")).write_text("")
    runner = Recorder(stdout=f"{uv_bin}\n")

    outcomes = apply(FILES, launcher=launcher, directories=(skill_dir,), run=runner, which=nothing)

    # uv is asked where it puts executables before anything, so the launcher can be aimed
    # at the dpw beside the command rather than the one beside this build.
    assert runner.calls == [tool_bin_command(), install_command()]
    assert [outcome.id for outcome in outcomes] == [COMMAND, LAUNCHER, SKILL]
    assert all(outcome.ok for outcome in outcomes)
    assert launcher.target() == uv_bin / executable_name("dpw")
    assert (skill_dir / SKILL_FILE).read_text() == FILES[SKILL_FILE]


def test_a_worktree_build_never_repoints_the_command(launcher, skill_dir, tmp_path, monkeypatch):
    """An editable install into a branch's scratch checkout breaks when it is removed —
    and every agent works in one, so `install all` has to be safe to run there."""
    monkeypatch.setattr(
        installer, "worktree_warning", lambda: "This build runs from a git worktree (/x)."
    )
    (tmp_path / executable_name("dpw")).write_text("")
    runner = Recorder(stdout=f"{tmp_path}\n")

    outcomes = apply(FILES, launcher=launcher, directories=(skill_dir,), run=runner, which=nothing)

    assert install_command() not in runner.calls
    command = next(outcome for outcome in outcomes if outcome.id == COMMAND)
    assert command.ok and "worktree" in command.line
    # The other two are still written from this build: that is the point of not stopping.
    assert launcher.target() == tmp_path / executable_name("dpw")
    assert (skill_dir / SKILL_FILE).exists()


def test_a_dplanner_uv_did_not_install_is_left_alone(launcher, skill_dir, tmp_path, main_checkout):
    """A pipx install, a system package or a venv is somebody's decision; a second copy
    beside it is a puzzle nobody asked for."""
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    (uv_bin / executable_name("dpw")).write_text("")
    runner = Recorder(stdout=f"{uv_bin}\n")
    elsewhere = tmp_path / "usr" / "bin" / PROG

    outcomes = apply(
        FILES,
        launcher=launcher,
        directories=(skill_dir,),
        run=runner,
        which=lambda _name: str(elsewhere),
    )

    assert runner.calls == [tool_bin_command()]
    command = next(outcome for outcome in outcomes if outcome.id == COMMAND)
    assert command.ok and str(elsewhere) in command.line
    assert launcher.target() == uv_bin / executable_name("dpw")


def test_uv_naming_its_bin_directory_with_dots_still_owns_the_command(
    launcher, skill_dir, tmp_path, main_checkout
):
    """`uv tool dir --bin` answers `~/.local/share/../bin`, and `which` finds the command in
    `~/.local/bin`: the same directory, which must read as uv's — or the command is "left
    alone" as somebody else's install and never refreshed, on every machine uv is on."""
    (tmp_path / "share").mkdir()
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    (uv_bin / executable_name("dpw")).write_text("")
    with_dots = tmp_path / "share" / ".." / "uv-bin"
    runner = Recorder(stdout=f"{with_dots}\n")

    outcomes = apply(
        FILES,
        launcher=launcher,
        directories=(skill_dir,),
        run=runner,
        which=lambda _name: str(uv_bin / PROG),
    )

    assert runner.calls == [tool_bin_command(), install_command()]
    command = next(outcome for outcome in outcomes if outcome.id == COMMAND)
    assert command.ok and "Left alone" not in command.line
    assert launcher.target() == uv_bin / executable_name("dpw")


def test_a_command_uv_installed_is_updated(launcher, skill_dir, tmp_path, main_checkout):
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    (uv_bin / executable_name("dpw")).write_text("")
    runner = Recorder(stdout=f"{uv_bin}\n")

    apply(
        FILES,
        launcher=launcher,
        directories=(skill_dir,),
        run=runner,
        which=lambda _name: str(uv_bin / PROG),
    )

    assert runner.calls == [tool_bin_command(), install_command()]


def test_a_failing_piece_does_not_stop_the_others(launcher, skill_dir, main_checkout):
    def refuse(command):
        if command == install_command():
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="no network\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    outcomes = apply(FILES, launcher=launcher, directories=(skill_dir,), run=refuse, which=nothing)

    command = next(outcome for outcome in outcomes if outcome.id == COMMAND)
    assert not command.ok and "no network" in command.line
    assert (skill_dir / SKILL_FILE).exists()
    assert by_id(read(launcher, skill_dir))[SKILL].state == "installed"


def test_removing_takes_out_the_launcher_and_the_skill_and_leaves_the_command(
    launcher, skill_dir, tmp_path, main_checkout
):
    """`uv tool uninstall dplanner` uninstalls the program running the verb: a deliberate
    act of its own, and one line the reader can copy instead."""
    (tmp_path / "dpw").write_text("")
    apply(
        FILES,
        launcher=launcher,
        directories=(skill_dir,),
        run=Recorder(stdout=f"{tmp_path}\n"),
        which=nothing,
    )

    outcomes = remove(FILES, launcher=launcher, directories=(skill_dir,))

    assert not launcher.path.exists()
    assert not skill_dir.exists()
    command = next(outcome for outcome in outcomes if outcome.id == COMMAND)
    assert " ".join(uninstall_command()) in command.line


def test_removing_nothing_says_so(launcher, skill_dir):
    taken = remove(FILES, launcher=launcher, directories=(skill_dir,))
    outcomes = {outcome.id: outcome.line for outcome in taken}

    assert "nothing installed" in outcomes[LAUNCHER]
    assert "nothing installed" in outcomes[SKILL]


# -- the verbs ---------------------------------------------------------------------------------


class Machine:
    """A machine with a uv that installs: the runner answers where its bin directory is,
    and `dplanner` starts resolving there once the install command has run."""

    def __init__(self, bin_dir: Path) -> None:
        self.bin_dir = bin_dir
        self.calls: list[list[str]] = []
        self.installed = False

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if command == install_command():
            self.installed = True
        return subprocess.CompletedProcess(command, 0, stdout=f"{self.bin_dir}\n", stderr="")

    def which(self, _name: str) -> str | None:
        return str(self.bin_dir / PROG) if self.installed else None


@pytest.fixture
def machine(launcher, skill_dir, tmp_path, monkeypatch, main_checkout):
    """The three verbs over a machine under tmp_path, with uv answering where dpw went."""
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    (uv_bin / executable_name("dpw")).write_text("")
    fake = Machine(uv_bin)
    monkeypatch.setattr(installer, "launcher_for", lambda: launcher)
    monkeypatch.setattr(installer, "target_dirs", lambda **_kwargs: (skill_dir,))
    monkeypatch.setattr(installer, "_run", fake)
    monkeypatch.setattr(installer, "_which", fake.which)
    # What the suite's own dpw is must not decide whether the launcher reads stale.
    monkeypatch.setattr(installer, "window_executable", lambda *_a, **_k: uv_bin / "dpw")
    return fake


def invoke(registry, *argv):
    out, err = StringIO(), StringIO()
    code = run(registry, default_module_formats(), list(argv), out, err)
    return code, out.getvalue(), err.getvalue()


def test_the_verbs_report_install_and_remove(registry, machine, launcher, skill_dir):
    code, out, _err = invoke(registry, "install", "status")
    assert code == 0
    assert out.count("missing") == 3

    code, out, _err = invoke(registry, "install", "all")
    assert code == 0
    assert str(launcher.path) in out and str(skill_dir) in out

    code, out, _err = invoke(registry, "install", "status")
    assert code == 0
    assert "missing" not in out and "stale" not in out

    code, out, _err = invoke(registry, "install", "remove")
    assert code == 0 and not launcher.path.exists() and not skill_dir.exists()

    code, out, _err = invoke(registry, "install", "status")
    assert out.count("missing") == 2  # The command is not what remove takes out.


def test_status_answers_in_json(registry, machine):
    _code, out, _err = invoke(registry, "install", "status", "--json")
    answer = json.loads(out)

    assert answer["status"] == "missing"
    assert [item["item"] for item in answer["items"]] == [COMMAND, LAUNCHER, SKILL]
    assert all(item["status"] == "missing" for item in answer["items"])


def test_status_reports_rather_than_judging(registry, machine):
    """It exits 0 whatever it finds, as `skill status` and `desktop status` do — the
    checklist is the verb that fails a machine."""
    code, _out, _err = invoke(registry, "install", "status")
    assert code == 0


def test_installing_exits_one_when_a_piece_failed(registry, machine, monkeypatch):
    def refuse(command):
        if command == install_command():
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="no network\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(installer, "_run", refuse)

    code, out, _err = invoke(registry, "install", "all")

    assert code == 1 and "no network" in out


def test_the_verbs_need_no_library(registry, machine, tmp_path, monkeypatch):
    """An agent on a fresh machine runs them before there is a library to open."""
    monkeypatch.setenv("DPLANNER_LIBRARY", str(tmp_path / "nowhere" / "library.json"))
    monkeypatch.chdir(tmp_path)

    for verb in ("status", "all", "remove"):
        code, _out, err = invoke(registry, "install", verb)
        assert code == 0, err


def test_the_skill_lists_the_one_act(registry):
    """Registered into the registry the skill is rendered from, so an agent learns it."""
    ids = {command.id for command in registry.commands()}

    assert {"install all", "install status", "install remove"} <= ids
    assert {"skill install", "desktop install"} <= ids  # The pieces it is made of stay.


def test_where_a_path_is_absent_the_row_still_has_one(launcher, skill_dir):
    found = by_id(read(launcher, skill_dir))

    assert found[COMMAND].where is None  # Nothing on PATH: there is no path to name.
    assert isinstance(found[LAUNCHER].where, Path)
