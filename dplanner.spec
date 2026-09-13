# -*- mode: python ; coding: utf-8 -*-
"""The frozen DPlanner: ``uv run pyinstaller dplanner.spec --noconfirm --clean``.

**onedir, never onefile — and that is a licence decision, not a preference.** The window is
Qt for Python, which is **LGPL v3**. Section 4 permits conveying a combined work only if the
user can relink it against a modified library; for a dynamically linked application that
means the Qt libraries must stay separate, replaceable files beside the program. A onefile
build unpacks into a private temporary directory that is deleted on exit, so somebody who
builds their own Qt has nowhere to put it — that build is a combined work with no relinking
route. onedir keeps ``_internal/PySide6/`` on disk where it can be swapped, which is what the
licence asks for. ``upx=False`` and ``strip=False`` serve the same clause twice over: a
packed or stripped library is not a drop-in replacement target, and UPX has broken Qt loads
before.

PyInstaller itself is GPL-2.0 **with an exception permitting closed and commercial builds**,
plus Apache-2.0 parts: the frozen output carries whatever licence we choose, and only
modifications to PyInstaller's own source would fall under the GPL. Nothing here modifies it.

**Two executables, one analysis.** ``pyproject.toml`` declares ``dplanner`` (console — the
surface an agent drives, whose output *is* the product) and ``dpw``
(``[project.gui-scripts]``: no console window, what a Start Menu shortcut opens). The two
differ only in the subsystem bit, so one ``Analysis`` feeds two ``EXE``s over one ``PYZ`` and
``freeze/entry.py`` reads which it is from ``sys.executable``.

**What the import graph cannot see is exactly three things**, each handled below with a
comment saying what breaks without it: distribution metadata (Help ▸ About), keyring's
entry-point backends, and pdfium's native library. Everything else is found statically — the
application contains no ``importlib.import_module`` and no ``__import__``, so a function-level
``import pypdfium2`` is followed like any other.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

ROOT = Path(SPECPATH)  # noqa: F821 — PyInstaller injects it.
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "src"))  # So the spec runs outside an editable install too.

from freeze.datas import package_datas  # noqa: E402 — the path has to be set up first.

# The icon, generated from the PNGs the package already ships rather than committed as a
# second copy of the same picture: cli/desktop.py is the one place that knows how to make an
# ICO out of them, it loads no Qt, and this keeps the executable's icon and the Start Menu
# shortcut's icon the same bytes by construction. Written into build/, already gitignored.
from dplanner.cli.desktop import ico_bytes  # noqa: E402

ICON = ROOT / "build" / "dplanner.ico"
ICON.parent.mkdir(parents=True, exist_ok=True)
ICON.write_bytes(ico_bytes())

datas = package_datas()

# Help ▸ About reads every component's version and licence from the installed distribution's
# own metadata, because a hand-kept licence table drifts. PyInstaller drops dist-info unless
# asked, and the dialog would then read "not installed" against every row — including the
# LGPL row for Qt, which is the one row an acknowledgement must never get wrong.
for distribution in (
    "PySide6-Essentials",
    "shiboken6",
    "keyring",
    "pypdfium2",
    "openai",
    "anthropic",
):
    datas += copy_metadata(distribution)

# keyring finds its backends through the `keyring.backends` **entry point group**, which lives
# in keyring's own dist-info and is reached by importlib.metadata — not by any import an
# analyser can follow. Frozen without it, keyring.get_keyring() returns backends.fail.Keyring,
# core/secrets.backend_problem() answers "no OS keychain is available on this machine", and
# every surface that keeps a credential refuses — on a Windows box whose Credential Manager is
# running perfectly well. Proved rather than assumed: `dplanner checklist show` from the
# frozen exe is what says it worked.
keyring_datas, keyring_binaries, keyring_hidden = collect_all("keyring")

# pdfium is a native library pypdfium2_raw/bindings.py loads **by path from beside itself**,
# and both pypdfium2 packages read a version.json the same way at import time. So the library
# has to land inside pypdfium2_raw/ rather than loose, and the JSON comes with it.
pdfium_datas, pdfium_binaries, pdfium_hidden = collect_all("pypdfium2_raw")
pdfium_datas += collect_data_files("pypdfium2")

datas += keyring_datas + pdfium_datas
binaries = keyring_binaries + pdfium_binaries
hiddenimports = keyring_hidden + pdfium_hidden

EXCLUDES = [
    # The application runs on PySide6-**Essentials** on purpose: QtPdf and QtWebEngine live in
    # the hundreds-of-MB Addons package, and pyproject.toml says so — pdfium is one small
    # native wheel instead. Naming them costs nothing where they are absent and is what stops
    # a stray import quietly doubling the bundle on a machine that has Addons installed.
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    # Essentials ships these and the application imports four Qt modules: QtCore, QtGui,
    # QtSvg, QtWidgets. Anything below is weight with no reader.
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtSql",
    "PySide6.QtHelp",
    "PySide6.QtSerialPort",
    # Development tools that share the venv and have no business in a shipped build.
    "pytest",
    "_pytest",
    "pytest_qt",
    "xdist",
    "execnet",
    "mypy",
    "mypyc",
    "ruff",
    "PyInstaller",
    # Not a dependency of anything here, and PyInstaller will take the whole Tcl/Tk runtime
    # along if anything so much as mentions it.
    "tkinter",
]
# QtNetwork, QtOpenGL and QtPrintSupport are deliberately **not** excluded. Nothing imports
# them from Python, but Qt6Gui and Qt6Widgets link them, and an exclude removes only the
# Python wrapper — it does not shrink the binary walk and can break it. Few megabytes to win,
# and the failure mode is a window that will not start.

analysis = Analysis(  # noqa: F821
    [str(ROOT / "freeze" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)  # noqa: F821

# exclude_binaries=True is what makes this onedir: the shared libraries go beside the
# executable rather than inside it. See the module docstring — it is the LGPL clause.
COMMON = {
    "exclude_binaries": True,
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": False,
    "disable_windowed_traceback": False,
    "argv_emulation": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
    "icon": str(ICON),
}

command = EXE(pyz, analysis.scripts, [], name="dplanner", console=True, **COMMON)  # noqa: F821
# The name is read back off sys.executable in freeze/entry.py and looked up by
# cli/desktop.window_executable. Renaming it changes behaviour.
window = EXE(pyz, analysis.scripts, [], name="dpw", console=False, **COMMON)  # noqa: F821

COLLECT(  # noqa: F821
    command,
    window,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="dplanner",
)
