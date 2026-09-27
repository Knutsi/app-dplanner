"""Render the menu bar, sorted by subject, in the dark and the light theme, to PNG.

    uv run python scripts/render_menu_bar.py --out docs/screenshots/f8-menu-bar

What F8 re-filed: the bar itself, then each menu it changed as it drops from the bar — Go,
Project and its Specs child, Graph, and Step with a step picked and its Show in child. The
window is built over the Importer plan ``render_graph_editor.py`` builds, its graph tab open,
so every entry is greyed or live exactly as a person would find it.
"""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication, QMenu
from scripts.render_graph_editor import open_importer, save, settle

from dplanner.theme.themes import DARK, LIGHT, Theme

WINDOW_SIZE = (1180, 620)


def child(menu: QMenu, title: str) -> QMenu:
    found = next(action.menu() for action in menu.actions() if action.text() == title)
    assert isinstance(found, QMenu)
    return found


def render(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    session, services, made, tab = open_importer(app, theme, workspace, "menu-bar")
    window = services.window
    window.resize(*WINDOW_SIZE)
    window.show()
    settle(app)
    bar = window.menuBar()
    save(bar, out, "bar", theme, app)
    menus = {action.text().replace("&", ""): action.menu() for action in bar.actions()}

    def drop(menu: QMenu, name: str) -> None:
        menu.popup(QPoint(0, 0))
        save(menu, out, name, theme, app)
        menu.hide()

    go, project, graph, step = (menus[name] for name in ("Go", "Project", "Graph", "Step"))
    assert all(isinstance(menu, QMenu) for menu in (go, project, graph, step))
    drop(go, "menu-go")
    drop(project, "menu-project")
    drop(child(project, "Specs"), "menu-project-specs")
    drop(graph, "menu-graph")
    # The feature, so every entry Show in holds for a step can be live.
    tab.select_steps([made[3]])
    settle(app)
    drop(step, "menu-step")
    drop(child(step, "Show in"), "menu-step-show-in")

    window.hide()
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the PNGs")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    with TemporaryDirectory() as tmp:
        # A render script must neither write the developer's settings nor read them, or the
        # shot shows whatever state this machine happens to be in.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tmp)
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
