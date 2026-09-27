"""Render Home — where a window starts — in the dark and the light theme, to PNG.

    uv run python scripts/render_home.py --out docs/screenshots/f9-home

Three shots of a whole application over a throwaway library: the program's start, before
anything was ever opened — the Home tab ``start_window`` opens, with the guide and Recent's
empty state; Home opened again from *Go ▸ Home* once a few views were kept and closed, listing
them; and the Projects folder's right-click, which renders the File menu's project group.
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
from dplanner.modules.progression.module import PROGRESSION_KIND
from dplanner.modules.project_editor.module import PROJECT_KIND
from dplanner.modules.spec.activity import SPECS_KIND
from dplanner.modules.step_order.module import ORDER_KIND
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

WINDOW_SIZE = (1180, 660)
# Kept in this order, so Recent lists them newest first: the graph at the top.
KEPT = (SPECS_KIND, ORDER_KIND, PROGRESSION_KIND, PROJECT_KIND)


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
    save(services.window, out, "home-first", theme, app)
    services.window.hide()
    session.close()

    session, services = open_library(app, theme, workspace, "kept")
    importer = services.document.projects[0]
    for kind in KEPT:
        services.tabs.open(kind, importer.id)
    for activity in services.tabs.activities():
        services.tabs.close_activity(activity)
    services.actions.run("home.open", services.context.current())
    save(services.window, out, "home", theme, app)

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
