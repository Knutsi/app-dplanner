"""Render Debug ▸ Windows Check in the dark and the light theme, to PNG.

    uv run python scripts/render_windows_check.py --out docs/screenshots/s17-windows

The Debug menu in both of the entry's states, because the interesting one is the refusal: a
machine without Omarchy's VM gets the entry *greyed with the reason in its own label*, never a
missing line. That is CLAUDE.md's *disabled means not now*, and what it actually reads like is
the thing worth reviewing.

The two states are rendered by handing the module's probe a machine rather than by finding
one: ``windows_check.probe`` takes its ``which`` as an argument for exactly this.
"""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication, QWidget

from dplanner.app import new_session
from dplanner.core.storage.locations import init_repo
from dplanner.domain.seed import create_library
from dplanner.framework.action_menu import build_menu
from dplanner.modules.debug import module as debug_module
from dplanner.modules.debug import windows_check
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    for _ in range(3):
        app.processEvents()
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def discard(widget: QWidget) -> None:
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def render(app: QApplication, theme: Theme, out: Path, workspace: Path, run: int) -> None:
    """One session per machine we want to show.

    The module asks ``probe()`` once, when it is built — an action state may not walk PATH —
    so the machine is chosen by swapping that function *before* the session, never by reaching
    into the built module afterwards.
    """
    QSettings().clear()
    apply_theme(app, theme)
    library_file = workspace / f"library-{theme.name}-{run}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None

    menu = build_menu(services.actions, services.context, "Debug", services.window)
    menu.popup(services.window.mapToGlobal(services.window.rect().topLeft()))
    name = "debug-menu" if run == 0 else "debug-menu-refused"
    save(menu, out, name, theme, app)
    menu.hide()
    discard(menu)
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s17-windows"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    # debug/module.py does `from ... import probe`, which binds the function into *its*
    # namespace at import time — so this is the name that has to be swapped.
    real = windows_check.probe
    with TemporaryDirectory() as directory:
        harness = Path(directory) / "windows_check.py"
        harness.write_text("", encoding="utf-8")
        machines = (
            lambda name: f"/usr/bin/{name}",  # Omarchy: the entry is live.
            lambda _name: None,  # Anywhere else: greyed, with the reason in its label.
        )
        try:
            for run, machine in enumerate(machines):
                debug_module.probe = (  # type: ignore[assignment]
                    lambda _s=harness, _w=machine, **_kw: real(script=_s, which=_w)
                )
                for theme in (DARK, LIGHT):
                    render(app, theme, args.out, Path(directory), run)
        finally:
            debug_module.probe = real  # type: ignore[assignment]
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
