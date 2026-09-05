"""Putting DPlanner on the desktop: a launcher an applications menu can open.

``dplanner window`` is a word a person types and ``dpw`` is the word typed for you; a
desktop wants neither, it wants a file. Each platform has its own — a ``.desktop`` entry in
the XDG applications directory on Linux, an application bundle in ``~/Applications`` on
macOS, a Start Menu shortcut on Windows — and each is one class here behind one contract:
where it goes, what it opens, how it is taken out. ``dplanner desktop install``, ``status``
and ``uninstall`` read the same on every machine, and the window's *Install dplanner
Command…* writes the launcher in the same go as the command.

What the launcher opens is ``dpw`` by absolute path — a menu entry has no shell and no PATH
to resolve anything with — and ``dpw`` rather than ``dplanner window`` because it is a
``gui-scripts`` entry: on Windows that is an executable with no console window behind it.
Which ``dpw``: the one beside the ``dplanner`` running the command, so the launcher opens
the DPlanner you installed it from; ``status`` says where it points and reads *stale* when
that is not where this build's ``dpw`` is. Every platform's launcher is testable on every
other, because the home directory, the environment and the process runner are arguments.

The Linux entry is named after ``APP_ID`` because that is the ``app_id`` the application
declares (``app.py``'s ``setDesktopFileName``) and a compositor matches a window to its
entry by that name. No icon yet: the application has none to give, and a launcher without
one wears the platform's generic icon rather than nothing.
"""

import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dplanner.cli.command import CliCommand, CliError
from dplanner.cli.main import PROG, WINDOW_SHORTCUT
from dplanner.identity import APP_DOMAIN, APP_ID, APP_NAME, APP_VERSION

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

# macOS registers a bundle when Finder sees it; asking directly makes a fresh one show up
# in Spotlight and Launchpad without waiting for that.
LSREGISTER = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework"
    "/Support/lsregister"
)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


class Launcher(Protocol):
    """One platform's way of opening DPlanner from its applications menu."""

    @property
    def path(self) -> Path: ...

    def write(self, executable: Path) -> None: ...

    def target(self) -> Path | None:
        """What the installed launcher opens, or None when there is none."""
        ...

    def remove(self) -> bool: ...


# -- Linux: a .desktop entry ------------------------------------------------------------------

_EXEC_PLAIN = re.compile(r"^[A-Za-z0-9_./:@+,=%-]+$")


def _exec_quote(argument: str) -> str:
    """One argument of a ``.desktop`` ``Exec`` line, as the specification quotes it: a
    literal ``%`` doubled (it introduces a field code), and anything the spec reserves
    inside double quotes with ``"``, `````, ``$`` and ``\\`` backslashed."""
    argument = argument.replace("%", "%%")
    if _EXEC_PLAIN.match(argument):
        return argument
    return '"' + re.sub(r'(["`$\\])', r"\\\1", argument) + '"'


def _exec_first(line: str) -> str:
    """The first argument of an ``Exec`` value, unquoted — the executable."""
    if not line.startswith('"'):
        return line.split()[0].replace("%%", "%") if line.split() else ""
    out: list[str] = []
    escaped = False
    for char in line[1:]:
        if escaped:
            out.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            break
        else:
            out.append(char)
    return "".join(out).replace("%%", "%")


def desktop_entry(executable: Path) -> str:
    return (
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                f"Name={APP_NAME}",
                "Comment=Plan a project as a graph of steps, with a coding agent or by hand",
                f"Exec={_exec_quote(str(executable))}",
                f"TryExec={executable}",
                "Terminal=false",
                "Categories=Development;ProjectManagement;",
                "Keywords=planner;plan;steps;agent;",
                f"StartupWMClass={APP_ID}",
                "StartupNotify=true",
            ]
        )
        + "\n"
    )


@dataclass(frozen=True)
class DesktopEntry:
    path: Path  # <XDG_DATA_HOME>/applications/dplanner.desktop
    run: Runner = _run
    which: Callable[[str], str | None] = shutil.which

    def write(self, executable: Path) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(desktop_entry(executable))
        if self.which("update-desktop-database") is not None:  # Best effort: menus refresh.
            self.run(["update-desktop-database", str(self.path.parent)])

    def target(self) -> Path | None:
        try:
            text = self.path.read_text()
        except OSError:
            return None
        for line in text.splitlines():
            if line.startswith("Exec="):
                first = _exec_first(line[len("Exec=") :])
                return Path(first) if first else None
        return None

    def remove(self) -> bool:
        if not self.path.is_file():
            return False
        self.path.unlink()
        return True


# -- macOS: an application bundle -------------------------------------------------------------


def bundle_identifier() -> str:
    """``local.dplanner`` from ``dplanner.local``: the domain, the way a bundle id reads."""
    return ".".join(reversed(APP_DOMAIN.split(".")))


def info_plist() -> bytes:
    return plistlib.dumps(
        {
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": bundle_identifier(),
            "CFBundleVersion": APP_VERSION,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundlePackageType": "APPL",
            "CFBundleExecutable": APP_NAME,
            "NSHighResolutionCapable": True,
        },
        sort_keys=True,
    )


def bundle_script(executable: Path) -> str:
    """The bundle's executable: a shell script that hands over to ``dpw``. Finder runs it
    with no shell profile behind it, which is why the path is absolute."""
    return f'#!/bin/sh\nexec {shlex.quote(str(executable))} "$@"\n'


_BUNDLE_EXEC = re.compile(r'^exec (.+) "\$@"$', re.MULTILINE)


@dataclass(frozen=True)
class AppBundle:
    path: Path  # ~/Applications/DPlanner.app
    run: Runner = _run

    @property
    def script(self) -> Path:
        return self.path / "Contents" / "MacOS" / APP_NAME

    def write(self, executable: Path) -> None:
        self.script.parent.mkdir(parents=True, exist_ok=True)
        (self.path / "Contents" / "Info.plist").write_bytes(info_plist())
        self.script.write_text(bundle_script(executable))
        self.script.chmod(0o755)
        if LSREGISTER.is_file():  # Best effort: Spotlight and Launchpad see it now.
            self.run([str(LSREGISTER), "-f", str(self.path)])

    def target(self) -> Path | None:
        try:
            text = self.script.read_text()
        except OSError:
            return None
        match = _BUNDLE_EXEC.search(text)
        if match is None:
            return None
        words = shlex.split(match.group(1))
        return Path(words[0]) if words else None

    def remove(self) -> bool:
        if not self.path.is_dir():
            return False
        shutil.rmtree(self.path)
        return True


# -- Windows: a Start Menu shortcut ------------------------------------------------------------


def _powershell_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def shortcut_script(path: Path, executable: Path) -> str:
    """PowerShell that writes the ``.lnk``: a shortcut is a COM object, and PowerShell is
    the one COM client every Windows has."""
    return "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$link = $shell.CreateShortcut({_powershell_literal(path)})",
            f"$link.TargetPath = {_powershell_literal(executable)}",
            f"$link.WorkingDirectory = {_powershell_literal(executable.parent)}",
            f"$link.Description = {_powershell_literal(APP_NAME)}",
            "$link.Save()",
        ]
    )


def shortcut_target_script(path: Path) -> str:
    shortcut = f"(New-Object -ComObject WScript.Shell).CreateShortcut({_powershell_literal(path)})"
    return f"{shortcut}.TargetPath"


def powershell(script: str) -> list[str]:
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]


@dataclass(frozen=True)
class StartMenuShortcut:
    path: Path  # %APPDATA%\Microsoft\Windows\Start Menu\Programs\DPlanner.lnk
    run: Runner = _run

    def write(self, executable: Path) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        result = self.run(powershell(shortcut_script(self.path, executable)))
        if result.returncode != 0:
            said = (result.stderr or result.stdout).strip()
            raise OSError(said or "PowerShell could not write the shortcut")

    def target(self) -> Path | None:
        if not self.path.is_file():
            return None
        result = self.run(powershell(shortcut_target_script(self.path)))
        text = result.stdout.strip()
        return Path(text) if result.returncode == 0 and text else None

    def remove(self) -> bool:
        if not self.path.is_file():
            return False
        self.path.unlink()
        return True


# -- the one contract -------------------------------------------------------------------------


def launcher_for(
    platform: str = sys.platform,
    env: Mapping[str, str] = os.environ,
    home: Path | None = None,
    run: Runner | None = None,
) -> Launcher:
    """This platform's launcher, at the place its desktop reads from."""
    home = home or Path.home()
    run = run or _run
    if platform.startswith("win"):
        base = Path(env.get("APPDATA", "") or home / "AppData" / "Roaming")
        programs = base / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return StartMenuShortcut(programs / f"{APP_NAME}.lnk", run)
    if platform == "darwin":
        return AppBundle(home / "Applications" / f"{APP_NAME}.app", run)
    base = Path(env.get("XDG_DATA_HOME", "") or home / ".local" / "share")
    return DesktopEntry(base / "applications" / f"{APP_ID}.desktop", run)


def window_executable(
    bin_dirs: Sequence[Path] = (),
    argv0: str | None = None,
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """Where ``dpw`` is: in a directory named first, else beside the running ``dplanner``,
    else on PATH — or None, which means the package was installed without it."""
    name = f"{WINDOW_SHORTCUT}.exe" if platform.startswith("win") else WINDOW_SHORTCUT
    beside = Path(sys.argv[0] if argv0 is None else argv0).absolute().parent
    for directory in (*bin_dirs, beside):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    found = which(WINDOW_SHORTCUT)
    return Path(found) if found else None


def status(launcher: Launcher, executable: Path | None) -> str:
    """``installed`` (opens this build's ``dpw``), ``stale`` (opens something else) or
    ``missing``."""
    target = launcher.target()
    if target is None:
        return "missing"
    if executable is None or target != executable:
        return "stale"
    return "installed"


def missing_executable_hint() -> str:
    from dplanner.cli.skill import install_command

    return (
        f"{WINDOW_SHORTCUT} is not installed beside {PROG} — reinstall with: "
        f"{shlex.join(install_command())}"
    )


def commands() -> list[CliCommand]:
    """The desktop verbs: install, status, uninstall — the skill verbs' shape."""
    from argparse import Namespace

    from dplanner.cli.command import CliContext

    def do_install(context: CliContext, _args: Namespace) -> int:
        executable = window_executable()
        if executable is None:
            raise CliError(missing_executable_hint())
        launcher = launcher_for()
        try:
            launcher.write(executable)
        except OSError as error:
            raise CliError(f"could not write {launcher.path}: {error}") from error
        context.report(
            {"installed": str(launcher.path), "opens": str(executable)},
            f"{launcher.path}\nopens {executable}",
        )
        return 0

    def do_status(context: CliContext, _args: Namespace) -> int:
        launcher = launcher_for()
        executable = window_executable()
        target = launcher.target()
        state = status(launcher, executable)
        text = f"{state}  {launcher.path}"
        if target is not None:
            text += f"\nopens {target}"
        if state == "stale" and executable is not None:
            text += f"\nthis build's is {executable}"
        if executable is None:
            text += f"\n{missing_executable_hint()}"
        context.report(
            {
                "status": state,
                "launcher": str(launcher.path),
                "opens": None if target is None else str(target),
                "executable": None if executable is None else str(executable),
            },
            text,
        )
        return 0

    def do_uninstall(context: CliContext, _args: Namespace) -> int:
        launcher = launcher_for()
        removed = launcher.remove()
        context.report(
            {"removed": [str(launcher.path)] if removed else []},
            str(launcher.path) if removed else "nothing installed",
        )
        return 0

    return [
        CliCommand(
            path=("desktop", "install"),
            summary="Add DPlanner to this desktop's applications menu.",
            run=do_install,
            needs_library=False,
            examples=(f"{PROG} desktop install",),
        ),
        CliCommand(
            path=("desktop", "status"),
            summary="Whether the desktop launcher exists and opens this build.",
            run=do_status,
            needs_library=False,
            examples=(f"{PROG} desktop status",),
        ),
        CliCommand(
            path=("desktop", "uninstall"),
            summary="Take DPlanner out of the desktop's applications menu.",
            run=do_uninstall,
            needs_library=False,
            examples=(f"{PROG} desktop uninstall",),
        ),
    ]
