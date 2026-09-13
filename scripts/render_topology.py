"""Render the Specs tab's Topology page in the dark and the light theme, to PNG.

    uv run python scripts/render_topology.py --out docs/screenshots/s29-topology

What S29 added: the project's own topology above, the default shape under it, parted by a
splitter whose handle is the only seam. A whole application is built over a throwaway
library so nothing here hand-wires a surface the window would build differently, and the
page is torn down per theme.
"""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtWidgets import QApplication, QWidget

from dplanner.app import new_session
from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import EditTextCommand
from dplanner.domain.model import TextEdit
from dplanner.domain.seed import create_library, seed_project
from dplanner.modules.spec.aspect import MODULE_ID
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

PAGE_SIZE = (760, 900)
TOPOLOGY = """# How this graph is shaped

- **A feature is a view or a major part of the API.** A component is not one unless it is
  exported and a capability in itself.
- **Milestones are the releases**, in a chain: Private beta, then Public launch.
- A **check** follows every feature that has something to test.
"""


def settle(app: QApplication) -> None:
    for _ in range(3):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def render(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    apply_theme(app, theme)
    library_file = workspace / f"library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)

    directory = seed_project(workspace / f"discovery-{theme.name}", "Discovery")
    project = services.repo.attach(directory)
    services.document.add_child(services.document.id, project)

    activity = services.tabs.open("specs", project.id)
    # Off the tab host first: a child inside a layout takes the size its parent gives it,
    # so a resize in place leaves each theme whatever width its tab happened to have.
    page = activity.widget
    host = page.parentWidget()
    page.setParent(None)
    page.resize(*PAGE_SIZE)
    page.show()
    settle(app)
    # The pinned first row is the topology, and it leads the list while nothing else is
    # there to read — so the page below is already the one this renders.
    save(page, out, "topology-empty", theme, app)

    services.undo.push(
        EditTextCommand(TextEdit(project.id, MODULE_ID, 0, "", TOPOLOGY), label="Set Topology")
    )
    save(page, out, "topology", theme, app)

    # Back onto the host, so the tab tree disposes it with everything else at close.
    page.setParent(host)
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the PNGs")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    with TemporaryDirectory(prefix="dplanner-render-") as tmp:
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
