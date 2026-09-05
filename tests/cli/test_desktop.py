"""The desktop launcher: one contract, three platforms, every one testable here.

A person wants DPlanner in the applications menu, and the menu wants a file the platform
understands. Each platform's launcher takes its home directory, environment and process
runner as arguments, so a Linux entry, a macOS bundle and a Windows shortcut are all built
and read back on whatever machine runs the suite.
"""

import plistlib
import subprocess
from io import StringIO
from pathlib import Path

import pytest

from dplanner.cli import desktop
from dplanner.cli.desktop import (
    AppBundle,
    DesktopEntry,
    StartMenuShortcut,
    launcher_for,
    shortcut_script,
    shortcut_target_script,
    status,
    window_executable,
)
from dplanner.cli.main import run
from dplanner.modules import default_module_formats


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


# -- where each platform keeps it --------------------------------------------------------------


def test_each_platform_has_its_place(tmp_path):
    env = {"XDG_DATA_HOME": str(tmp_path / "xdg"), "APPDATA": str(tmp_path / "roaming")}
    assert launcher_for("linux", env, tmp_path).path == (
        tmp_path / "xdg" / "applications" / "dplanner.desktop"
    )
    assert launcher_for("linux", {}, tmp_path).path == (
        tmp_path / ".local" / "share" / "applications" / "dplanner.desktop"
    )
    assert launcher_for("darwin", {}, tmp_path).path == (tmp_path / "Applications" / "DPlanner.app")
    programs = Path("Microsoft") / "Windows" / "Start Menu" / "Programs" / "DPlanner.lnk"
    assert launcher_for("win32", env, tmp_path).path == tmp_path / "roaming" / programs
    assert launcher_for("win32", {}, tmp_path).path == (tmp_path / "AppData" / "Roaming" / programs)


# -- Linux --------------------------------------------------------------------------------------


def test_the_linux_entry_is_named_after_the_app_id_and_opens_by_absolute_path(tmp_path):
    """`app.py` declares `dplanner` as the desktop file name, so the entry is
    `dplanner.desktop`; a menu has no PATH, so Exec is the absolute `dpw`."""
    entry = DesktopEntry(tmp_path / "applications" / "dplanner.desktop", Recorder(), nothing)
    assert entry.target() is None
    entry.write(Path("/opt/tools/bin/dpw"))
    text = entry.path.read_text()
    assert text.startswith("[Desktop Entry]\nType=Application\nName=DPlanner\n")
    assert "\nExec=/opt/tools/bin/dpw\n" in text
    assert "\nTryExec=/opt/tools/bin/dpw\n" in text
    assert "\nTerminal=false\n" in text
    assert "\nStartupWMClass=dplanner\n" in text
    assert entry.target() == Path("/opt/tools/bin/dpw")
    assert entry.remove() and not entry.path.exists()
    assert not entry.remove()


def test_a_path_the_spec_reserves_is_quoted_as_the_spec_says(tmp_path):
    entry = DesktopEntry(tmp_path / "dplanner.desktop", Recorder(), nothing)
    entry.write(Path('/home/a b/100%/"q"/dpw'))
    assert 'Exec="/home/a b/100%%/\\"q\\"/dpw"\n' in entry.path.read_text()
    assert entry.target() == Path('/home/a b/100%/"q"/dpw')


def test_the_linux_entry_refreshes_the_menu_when_the_tool_is_there(tmp_path):
    run_ = Recorder()
    entry = DesktopEntry(
        tmp_path / "apps" / "dplanner.desktop", run_, lambda name: f"/usr/bin/{name}"
    )
    entry.write(Path("/x/dpw"))
    assert run_.calls == [["update-desktop-database", str(tmp_path / "apps")]]
    quiet = Recorder()
    DesktopEntry(tmp_path / "apps" / "dplanner.desktop", quiet, nothing).write(Path("/x/dpw"))
    assert quiet.calls == []


# -- macOS --------------------------------------------------------------------------------------


def test_the_mac_bundle_is_a_plist_and_a_script_handing_over(tmp_path):
    bundle = AppBundle(tmp_path / "Applications" / "DPlanner.app", Recorder())
    assert bundle.target() is None
    bundle.write(Path("/Users/me/.local/bin/dpw"))
    plist = plistlib.loads((bundle.path / "Contents" / "Info.plist").read_bytes())
    assert plist["CFBundleExecutable"] == "DPlanner"
    assert plist["CFBundleIdentifier"] == "local.dplanner"
    assert plist["CFBundlePackageType"] == "APPL"
    assert bundle.script == bundle.path / "Contents" / "MacOS" / "DPlanner"
    assert bundle.script.read_text() == '#!/bin/sh\nexec /Users/me/.local/bin/dpw "$@"\n'
    assert bundle.script.stat().st_mode & 0o111
    assert bundle.target() == Path("/Users/me/.local/bin/dpw")

    bundle.write(Path("/Users/a b/dpw"))  # Finder runs the script with no shell profile.
    assert "exec '/Users/a b/dpw' \"$@\"" in bundle.script.read_text()
    assert bundle.target() == Path("/Users/a b/dpw")
    assert bundle.remove() and not bundle.path.exists()
    assert not bundle.remove()


# -- Windows ------------------------------------------------------------------------------------


def test_the_windows_shortcut_goes_through_powershell(tmp_path):
    """A .lnk is a COM object; PowerShell is the COM client every Windows has."""
    run_ = Recorder()
    link = StartMenuShortcut(tmp_path / "Programs" / "DPlanner.lnk", run_)
    link.write(Path(r"C:\Users\me\.local\bin\dpw.exe"))
    (command,) = run_.calls
    assert command[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    assert command[4] == shortcut_script(link.path, Path(r"C:\Users\me\.local\bin\dpw.exe"))
    assert "$link.TargetPath = 'C:\\Users\\me\\.local\\bin\\dpw.exe'" in command[4]
    assert "$link.Save()" in command[4]
    assert link.path.parent.is_dir()

    assert link.target() is None  # The recorder wrote no file: nothing to read.
    link.path.write_bytes(b"lnk")
    reader = Recorder(stdout="C:\\Users\\me\\.local\\bin\\dpw.exe\r\n")
    assert StartMenuShortcut(link.path, reader).target() == Path(
        "C:\\Users\\me\\.local\\bin\\dpw.exe"
    )
    assert reader.calls[0][4] == shortcut_target_script(link.path)
    assert link.remove() and not link.path.exists()


def test_a_failed_powershell_is_an_error_carrying_its_words(tmp_path):
    def failing(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Access denied\n")

    with pytest.raises(OSError, match="Access denied"):
        StartMenuShortcut(tmp_path / "DPlanner.lnk", failing).write(Path("C:/dpw.exe"))


def test_a_powershell_literal_doubles_its_quotes():
    script = shortcut_script(Path("C:/O'Brien/DPlanner.lnk"), Path("C:/x/dpw.exe"))
    assert "CreateShortcut('C:\\O''Brien\\DPlanner.lnk')" in script.replace("/", "\\")


# -- the contract -------------------------------------------------------------------------------


def test_status_reads_installed_stale_or_missing(tmp_path):
    entry = DesktopEntry(tmp_path / "dplanner.desktop", Recorder(), nothing)
    assert status(entry, Path("/new/dpw")) == "missing"
    entry.write(Path("/old/dpw"))
    assert status(entry, Path("/new/dpw")) == "stale"
    assert status(entry, None) == "stale"  # This build has no dpw to compare with.
    entry.write(Path("/new/dpw"))
    assert status(entry, Path("/new/dpw")) == "installed"


def test_dpw_is_found_in_a_named_directory_then_beside_dplanner_then_on_path(tmp_path):
    beside = tmp_path / "bin"
    beside.mkdir()
    (beside / "dpw").write_text("")
    elsewhere = str(tmp_path / "elsewhere" / "dplanner")
    assert window_executable(argv0=str(beside / "dplanner"), platform="linux", which=nothing) == (
        beside / "dpw"
    )
    on_path = window_executable(argv0=elsewhere, platform="linux", which=lambda _n: "/usr/bin/dpw")
    assert on_path == Path("/usr/bin/dpw")
    assert window_executable(argv0=elsewhere, platform="linux", which=nothing) is None
    tool = tmp_path / "tool"
    tool.mkdir()
    (tool / "dpw.exe").write_text("")
    found = window_executable(
        [tool], argv0=str(beside / "dplanner.exe"), platform="win32", which=nothing
    )
    assert found == tool / "dpw.exe"


# -- the verbs ----------------------------------------------------------------------------------


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    """The verbs on a Linux entry under tmp_path, whatever platform runs the suite, with
    this build's dpw at a known place."""
    entry = DesktopEntry(tmp_path / "applications" / "dplanner.desktop", Recorder(), nothing)
    executable = tmp_path / "bin" / "dpw"
    executable.parent.mkdir()
    executable.write_text("")
    monkeypatch.setattr(desktop, "launcher_for", lambda: entry)
    monkeypatch.setattr(desktop, "window_executable", lambda *_a, **_k: executable)
    return entry


def invoke(registry, *argv):
    out, err = StringIO(), StringIO()
    code = run(registry, default_module_formats(), list(argv), out, err)
    return code, out.getvalue(), err.getvalue()


def test_the_verbs_install_report_and_uninstall(registry, launcher, tmp_path):
    code, out, _err = invoke(registry, "desktop", "status")
    assert code == 0 and out.startswith(f"missing  {launcher.path}")

    code, out, _err = invoke(registry, "desktop", "install")
    assert code == 0
    assert out == f"{launcher.path}\nopens {tmp_path / 'bin' / 'dpw'}\n"
    assert launcher.target() == tmp_path / "bin" / "dpw"

    code, out, _err = invoke(registry, "desktop", "status", "--json")
    assert code == 0
    assert '"status": "installed"' in out and f'"opens": "{tmp_path / "bin" / "dpw"}"' in out

    launcher.write(Path("/somewhere/else/dpw"))  # Reinstalled elsewhere since.
    code, out, _err = invoke(registry, "desktop", "status")
    assert out == (
        f"stale  {launcher.path}\nopens /somewhere/else/dpw\n"
        f"this build's is {tmp_path / 'bin' / 'dpw'}\n"
    )

    code, out, _err = invoke(registry, "desktop", "uninstall")
    assert code == 0 and out == f"{launcher.path}\n"
    assert not launcher.path.exists()
    code, out, _err = invoke(registry, "desktop", "uninstall")
    assert code == 0 and out == "nothing installed\n"


def test_install_refuses_when_the_package_has_no_dpw(registry, launcher, monkeypatch):
    monkeypatch.setattr(desktop, "window_executable", lambda *_a, **_k: None)
    code, _out, err = invoke(registry, "desktop", "install")
    assert code == 1
    assert "dpw is not installed beside dplanner" in err and "uv tool install" in err
    assert launcher.target() is None
    code, out, _err = invoke(registry, "desktop", "status")
    assert code == 0 and "dpw is not installed beside dplanner" in out


def test_a_launcher_that_cannot_be_written_is_one_line_on_stderr(registry, launcher, monkeypatch):
    entry = launcher

    class Refusing:
        path = entry.path

        def write(self, _executable: Path) -> None:
            raise OSError("read-only file system")

        def target(self) -> Path | None:
            return None

        def remove(self) -> bool:
            return False

    monkeypatch.setattr(desktop, "launcher_for", lambda: Refusing())
    code, _out, err = invoke(registry, "desktop", "install")
    assert code == 1 and f"could not write {entry.path}: read-only file system" in err


def test_the_desktop_verbs_need_no_library(registry, launcher, tmp_path):
    code, out, _err = invoke(
        registry, "--library", str(tmp_path / "nowhere.json"), "desktop", "status"
    )
    assert code == 0 and out.startswith("missing")
