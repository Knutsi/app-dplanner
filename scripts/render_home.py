"""Render Home — where a window starts — in the dark and the light theme, to PNG.

    uv run python scripts/render_home.py --out docs/screenshots/f9-home

Three pictures of a whole application over a throwaway library: the program's start, the
Home tab ``start_window`` opens, with the guide centred over the garden part-way through a
season; the garden alone at five moments of one season, top to bottom, since a page cannot
show motion; and the Projects folder's right-click, which renders the File menu's project
group. The garden's clock is set by hand, so every run draws the same moments.
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
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from scripts.render_graph_editor import save, settle

from dplanner.app import new_session
from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.builder import INDEX_PANEL_ID
from dplanner.framework.index_panel import SEGMENT_ROLE, IndexPanel
from dplanner.framework.services import AppServices
from dplanner.framework.session import AppSession
from dplanner.modules import start_window
from dplanner.modules.home.garden import Garden
from dplanner.modules.home.page import HomePage
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

WINDOW_SIZE = (1180, 800)
# Kept in this order, so Recent lists them newest first: the graph at the top.
# The moments of one season the garden strip shows, in seconds: seeds, the rain at work,
# half in bloom, all in bloom, and gone back to seed for the next.
MOMENTS = (0.0, 9.0, 20.0, 40.0, 58.0)
STEP_S = 0.1


def season_at(seconds: float, reach: float) -> Garden:
    """The garden after ``seconds`` of the ordinary clock, in the steps a tick takes."""
    garden = Garden()
    while garden.t < seconds:
        garden.advance(STEP_S, reach)
    return garden


def open_library(
    app: QApplication, theme: Theme, workspace: Path, name: str
) -> tuple[AppSession, AppServices]:
    """A whole application over a throwaway library of two projects, nothing ever opened."""
    QSettings().clear()  # Each shot starts from nothing remembered, whatever ran before it.
    apply_theme(app, theme)
    library_file = workspace / f"{name}-library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)
    for title in ("Importer", "Billing"):
        project = services.repo.attach(seed_project(workspace / f"{name}-{title}", title))
        services.document.add_child(services.document.id, project)
        AddNodeCommand(project.id, Step(title="Read the spec")).redo(services.document)
    window = services.window
    window.resize(*WINDOW_SIZE)
    window.show()
    settle(app)
    return session, services


def index_panel(services: AppServices) -> IndexPanel:
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    assert isinstance(panel, IndexPanel)
    return panel


def render(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    session, services = open_library(app, theme, workspace, "first")
    start_window(services)  # What app.open_at_startup does once the build is up.
    home = services.tabs.current_activity()
    assert home is not None and isinstance(home.widget, HomePage)
    garden = home.widget.garden
    garden.state = season_at(20.0, garden.reach())
    save(services.window, out, "home", theme, app)

    frames = []
    for moment in MOMENTS:
        garden.state = season_at(moment, garden.reach())
        settle(app)
        frames.append(garden.grab().toImage())
    strip = QImage(frames[0].width(), sum(f.height() for f in frames), frames[0].format())
    painter = QPainter(strip)
    top = 0
    for frame in frames:
        painter.drawImage(0, top, frame)
        top += frame.height()
    painter.end()
    path = out / f"garden-{theme.name}.png"
    strip.save(str(path), "PNG")
    print(path)

    panel = index_panel(services)
    tree = panel.tree
    projects = next(
        item
        for item in (tree.topLevelItem(i) for i in range(tree.topLevelItemCount()))
        if item is not None and item.data(0, SEGMENT_ROLE) == "projects"
    )
    menu = panel.context_menu(projects)
    assert menu is not None
    menu.popup(QPoint(0, 0))
    save(menu, out, "projects-menu", theme, app)
    menu.hide()
    menu.deleteLater()
    services.window.hide()
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
