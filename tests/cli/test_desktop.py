"""The desktop launcher: one contract, three platforms, every one testable here.

A person wants DPlanner in the applications menu, and the menu wants a file the platform
understands. Each platform's launcher takes its home directory, environment and process
runner as arguments, so a Linux entry, a macOS bundle and a Windows shortcut are all built
and read back on whatever machine runs the suite.
"""

import json
import plistlib
import shlex
import struct
import subprocess
from io import StringIO
from pathlib import Path

import pytest
from tests.platforms import POSIX_MODE_BITS

from dplanner.assets import ICON_SIZES, icon_path
from dplanner.cli import desktop
from dplanner.cli.desktop import (
    ICNS_TYPES,
    ICO_SIZES,
    AppBundle,
    DesktopEntry,
    StartMenuShortcut,
    _exec_quote,
    icns_bytes,
    ico_bytes,
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
    env["LOCALAPPDATA"] = str(tmp_path / "local")
    shortcut = launcher_for("win32", env, tmp_path)
    assert isinstance(shortcut, StartMenuShortcut)
    assert shortcut.icon_file == tmp_path / "local" / "DPlanner" / "dplanner.ico"
    assert launcher_for("win32", {}, tmp_path).path == (tmp_path / "AppData" / "Roaming" / programs)


# -- Linux --------------------------------------------------------------------------------------


def test_the_linux_entry_is_named_after_the_app_id_and_opens_by_absolute_path(tmp_path):
    """`app.py` declares `dplanner` as the desktop file name, so the entry is
    `dplanner.desktop`; a menu has no PATH, so Exec is the absolute `dpw`."""
    entry = DesktopEntry(tmp_path / "applications" / "dplanner.desktop", Recorder(), nothing)
    assert entry.target() is None
    dpw = Path("/opt/tools/bin/dpw")
    entry.write(dpw)
    text = entry.path.read_text()
    assert text.startswith("[Desktop Entry]\nType=Application\nName=DPlanner\n")
    assert f"\nExec={_exec_quote(str(dpw))}\n" in text
    assert f"\nTryExec={dpw}\n" in text
    assert "\nIcon=dplanner\n" in text  # By name: the hicolor theme beside the entry has it.
    assert "\nTerminal=false\n" in text
    assert "\nStartupWMClass=dplanner\n" in text
    assert entry.target() == dpw
    hicolor = tmp_path / "icons" / "hicolor"
    assert entry.icon_file(256) == hicolor / "256x256" / "apps" / "dplanner.png"
    assert all(entry.icon_file(size).is_file() for size in ICON_SIZES)
    assert entry.icon_file(48).read_bytes() == icon_path(48).read_bytes()
    assert entry.remove() and not entry.path.exists()
    assert not any(entry.icon_file(size).exists() for size in ICON_SIZES)
    assert not entry.remove()


def test_a_path_the_spec_reserves_is_quoted_as_the_spec_says(tmp_path):
    """The quoting is a string question, so it is asked of the string function:
    a Path would carry the host's separators into an assertion about backslash
    escapes and doubled percent signs, which have nothing to do with them."""
    assert _exec_quote("/opt/bin/dpw") == "/opt/bin/dpw"  # Nothing reserved: left alone.
    assert _exec_quote('/home/a b/100%/"q"/dpw') == '"/home/a b/100%%/\\"q\\"/dpw"'

    entry = DesktopEntry(tmp_path / "dplanner.desktop", Recorder(), nothing)
    reserved = Path("/home/a b/100%/dpw")  # A space and a percent on every platform.
    entry.write(reserved)
    assert entry.target() == reserved  # Whatever it quoted, it reads back.


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
    dpw = Path("/Users/me/.local/bin/dpw")
    bundle.write(dpw)
    plist = plistlib.loads((bundle.path / "Contents" / "Info.plist").read_bytes())
    assert plist["CFBundleExecutable"] == "DPlanner"
    assert plist["CFBundleIconFile"] == "DPlanner"
    assert bundle.icon_file == bundle.path / "Contents" / "Resources" / "DPlanner.icns"
    assert bundle.icon_file.read_bytes() == icns_bytes()
    assert plist["CFBundleIdentifier"] == "local.dplanner"
    assert plist["CFBundlePackageType"] == "APPL"
    assert bundle.script == bundle.path / "Contents" / "MacOS" / "DPlanner"
    handover = f'exec {shlex.quote(str(dpw))} "$@"'
    assert bundle.script.read_text() == (
        "#!/bin/sh\n"
        f'[ -n "$SHELL" ] && exec "$SHELL" -lc {shlex.quote(handover)} -- "$@"\n'
        f"{handover}\n"
    )
    assert bundle.target() == dpw

    spaced = Path("/Users/a b/dpw")  # Finder runs the script with no shell profile.
    bundle.write(spaced)
    assert f'exec {shlex.quote(str(spaced))} "$@"' in bundle.script.read_text()
    assert bundle.target() == spaced
    assert bundle.remove() and not bundle.path.exists()
    assert not bundle.remove()


def test_the_mac_bundle_hands_over_through_the_login_shell_and_falls_back(tmp_path):
    """Finder starts the bundle with launchd's four-directory PATH, so the hand-over goes
    through the user's login shell — that is where `brew shellenv` and uv's installer wrote
    themselves. `$SHELL` unset must still open a window, with a thin PATH, rather than none."""
    bundle = AppBundle(tmp_path / "Applications" / "DPlanner.app", Recorder())
    bundle.write(Path("/Users/me/.local/bin/dpw"))
    lines = bundle.script.read_text().splitlines()
    assert lines[1].startswith('[ -n "$SHELL" ] && exec "$SHELL" -lc ')
    assert lines[2].startswith("exec ")  # The fallback, and what target() reads.

    # A path with an apostrophe in it: the hand-over is a `-c` argument inside a script, so
    # it is quoted twice. Quoted once, the inner string ends early and the bundle execs
    # nothing — and `target()` must still read the executable back out of the fallback line.
    awkward = Path("/Users/o'brien/my apps/dpw")
    bundle.write(awkward)
    assert bundle.target() == awkward


@POSIX_MODE_BITS
def test_the_mac_bundle_script_is_executable(tmp_path):
    """Finder runs the script directly, so it has to carry the bit. Its own test because
    that is the one thing in the bundle Windows has no concept of — the plist, the icon
    and the hand-over line are all checked on every platform above."""
    bundle = AppBundle(tmp_path / "Applications" / "DPlanner.app", Recorder())
    bundle.write(Path("/Users/me/.local/bin/dpw"))
    assert bundle.script.stat().st_mode & 0o111


# -- Windows ------------------------------------------------------------------------------------


def test_the_windows_shortcut_goes_through_powershell(tmp_path):
    """A .lnk is a COM object; PowerShell is the COM client every Windows has."""
    run_ = Recorder()
    link = StartMenuShortcut(tmp_path / "Programs" / "DPlanner.lnk", run_)
    link.write(Path(r"C:\Users\me\.local\bin\dpw.exe"))
    (command,) = run_.calls
    assert command[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    assert command[4] == shortcut_script(
        link.path, Path(r"C:\Users\me\.local\bin\dpw.exe"), link.icon_file
    )
    assert f"$link.IconLocation = '{link.icon_file},0'" in command[4]
    assert link.icon_file == tmp_path / "Programs" / "DPlanner.ico"  # No icon named: beside it.
    assert link.icon_file.read_bytes()[:6] == b"\x00\x00\x01\x00\x04\x00"  # An ICO of 4 sizes.
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
    script = shortcut_script(
        Path("C:/O'Brien/DPlanner.lnk"), Path("C:/x/dpw.exe"), Path("C:/i.ico")
    )
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
    (beside / "dpw").write_text("")  # The code is told platform="linux": it looks for `dpw`.
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
    # Read the JSON rather than retype the path into it: a Windows path is escaped there
    # (`C:\\t\\...`) and an f-string of the raw path never matches it.
    reported = json.loads(out)
    assert reported["status"] == "installed"
    assert reported["opens"] == str(tmp_path / "bin" / "dpw")  # What the fixture planted.

    elsewhere = Path("/somewhere/else/dpw")
    launcher.write(elsewhere)  # Reinstalled elsewhere since.
    code, out, _err = invoke(registry, "desktop", "status")
    assert out == (
        f"stale  {launcher.path}\nopens {elsewhere}\nthis build's is {tmp_path / 'bin' / 'dpw'}\n"
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


# -- the icon -----------------------------------------------------------------------------------


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_the_shipped_icon_comes_at_every_size_it_claims():
    for size in ICON_SIZES:
        assert png_size(icon_path(size).read_bytes()) == (size, size)


def test_the_icns_carries_each_png_as_it_is():
    """macOS reads a PNG payload in every element type since 10.7, so nothing is re-encoded:
    the container is a header and the shipped bytes, one element per size."""
    data = icns_bytes()
    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)
    offset = 8
    seen = {}
    while offset < len(data):
        kind, length = (
            data[offset : offset + 4],
            struct.unpack(">I", data[offset + 4 : offset + 8])[0],
        )
        seen[kind] = data[offset + 8 : offset + length]
        offset += length
    assert set(seen) == set(ICNS_TYPES.values())
    for size, kind in ICNS_TYPES.items():
        assert seen[kind] == icon_path(size).read_bytes()


def test_the_ico_directory_points_at_each_png():
    data = ico_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, len(ICO_SIZES))
    for index, size in enumerate(ICO_SIZES):
        entry = data[6 + 16 * index : 6 + 16 * (index + 1)]
        width, height, _colors, _reserved, planes, bits, length, offset = struct.unpack(
            "<BBBBHHII", entry
        )
        assert (width, height) == (size % 256, size % 256) and (planes, bits) == (1, 32)
        blob = data[offset : offset + length]
        assert blob == icon_path(size).read_bytes() and png_size(blob) == (size, size)
