"""Render the agents-at-work band and the dialog behind it, in the dark and the light theme.

    uv run python scripts/render_agents_at_work.py --out docs/screenshots/s23-agents-at-work

A whole application over a synthetic library, with claims written to a throwaway board the
way `dplanner agent-work` writes them. It renders the window's foot with one agent at work
(that agent's own line), then with three at once (one band that counts them, filled by
everything they counted), and then the *Agents at Work* dialog a click on that band opens.
"""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication, QWidget
from scripts.synthetic_library import build_library

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.domain.at_work import AtWorkBoard
from dplanner.modules.agent_at_work.module import AgentAtWorkModule
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

WINDOW_SIZE = (1180, 720)
ABOVE_BAR = 44  # How much of the tabs over the band the grab keeps, for context.
STEPS = 24
# A claim's stamp carries whole seconds and claims begun within one are listed by step id,
# so each is begun a second after the last for the rows to read in the order they began.
BEGIN_APART_S = 1.1


def settle(app: QApplication, turns: int = 6) -> None:
    for _ in range(turns):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def save_foot(window: QWidget, bar: QWidget, out: Path, name: str, theme: Theme, app) -> None:
    """The window from just over the band to its status bar — where the band is read."""
    settle(app)
    top = max(0, bar.mapTo(window, bar.rect().topLeft()).y() - ABOVE_BAR)
    path = out / f"{name}-{theme.name}.png"
    window.grab(QRect(0, top, window.width(), window.height() - top)).save(str(path), "PNG")
    print(path)


def render(app: QApplication, theme: Theme, out: Path, root: Path) -> None:
    apply_theme(app, theme)
    board = AtWorkBoard(root / f"at-work-{theme.name}")
    session = new_session(at_work=board)
    assert session.open_initial(build_library(root / theme.name, steps=STEPS, projects=1))
    services = session.services
    window = session.window
    assert services is not None and window is not None
    services.debounce.set_immediate(True)
    window.resize(*WINDOW_SIZE)
    window.show()
    project = services.document.projects[0]
    steps = list(project.steps)
    services.tabs.open("project", project.id)
    module = next(m for m in services.modules if isinstance(m, AgentAtWorkModule))
    bar = window.notices

    board.start(project.id, steps[3].id, "Linking the steps under the payments milestone", of=8)
    board.set(project.id, steps[3].id, done=3)
    module.refresh()
    save_foot(window, bar, out, "banner-one", theme, app)

    time.sleep(BEGIN_APART_S)
    board.start(project.id, steps[7].id, "Writing the migration and its tests", of=10)
    board.set(project.id, steps[7].id, done=9)
    time.sleep(BEGIN_APART_S)
    board.start(project.id, doing="Reading the spec before cutting the next steps")
    module.refresh()
    save_foot(window, bar, out, "banner", theme, app)

    (notice,) = bar.notices()
    assert notice.open is not None
    notice.open()
    dialog = module.dialog()
    assert dialog is not None
    save(dialog, out, "dialog", theme, app)
    dialog.hide()
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s23-agents-at-work"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    set_early_attributes()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    with tempfile.TemporaryDirectory(prefix="dplanner-s23-") as tmp:
        # Per-user settings into the throwaway directory, before anything reads them, so the
        # render neither reads nor writes the developer's own.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, f"{tmp}/settings")
        configure_application(app)
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
