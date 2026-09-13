"""Render the graph editor's chrome in the dark and the light theme, to PNG.

    uv run python scripts/render_graph_editor.py --out docs/screenshots/s7-graph-editor

What S7 reworked: the strip of verbs over the canvas as glyphs in named bands, folding
whole bands into its ``…`` menu; the *Jump to* picker, which opens on the plan's landmarks
and searches every step; and the Features list, standing beside the canvas inside the
project tab rather than across the window. A whole application is built over a throwaway
library — the tab is the tab host's, so nothing here hand-wires a surface the window would
build differently — and torn down per theme.
"""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication, QWidget

from dplanner.app import new_session
from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.domain.seed import create_library, seed_project
from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.feature.catalogue import FeatureRecord, write_catalogue
from dplanner.modules.project_editor.module import ProjectEditorModule
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.project_editor.positions import write_position
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as milestone_write
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

PAGE_SIZE = (1180, 620)
NARROW = 520
PICKER_SIZE = (520, 300)

# A plan with the shapes the chrome is about: a milestone to jump to, a feature to drag
# from the list beside it, and work leading to both.
STEPS = (
    ("Read the fixtures", (-300.0, -60.0), ""),
    ("Write the parser", (20.0, -180.0), ""),
    ("Map the columns", (20.0, 60.0), ""),
    ("Bulk import", (340.0, -60.0), "feature"),
    ("Ship the importer", (660.0, -60.0), "milestone"),
)
# Who waits on whom, by position in STEPS: the graph reads as a graph rather than as five
# orphans, which is what the orphan mark would otherwise say about every card.
EDGES = ((1, 0), (2, 0), (3, 1), (3, 2), (4, 3))


def settle(app: QApplication) -> None:
    for _ in range(3):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def discard(widget: QWidget) -> None:
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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

    directory = seed_project(workspace / f"importer-{theme.name}", "Importer")
    project = services.repo.attach(directory)
    services.document.add_child(services.document.id, project)
    services.document.set_module_data(
        project.id,
        FEATURE_ID,
        write_catalogue([FeatureRecord("f1", "Bulk import"), FeatureRecord("f2", "Dark mode")]),
    )
    made = []
    for title, (x, y), kind in STEPS:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(services.document)
        SetModuleDataCommand(step.id, POSITION_KEY, write_position(x, y)).redo(services.document)
        if kind == "milestone":
            SetModuleDataCommand(step.id, MILESTONE_ID, milestone_write("Import")).redo(
                services.document
            )
        elif kind == "feature":
            SetModuleDataCommand(step.id, FEATURE_ID, feature_write("f1")).redo(services.document)
        made.append(step.id)
    for waiter, source in EDGES:
        # Through the stack, so the strip's History band has something to say.
        services.undo.push(SetEdgesCommand(made[waiter], "requires", [made[source]]))

    tab = services.tabs.open("project", project.id)
    # A step picked, while the tab is still the window's current one and may say so — so
    # the strip and its … menu read as verbs about something rather than all greyed.
    tab.select_steps([made[3]])
    settle(app)

    # Jump to, while the tab is still the window's current one — it is what the verb asks.
    editor = next(m for m in services.modules if isinstance(m, ProjectEditorModule))
    picker = editor.jump_picker()
    assert picker is not None
    picker.resize(*PICKER_SIZE)
    picker.show()
    save(picker, out, "jump", theme, app)
    discard(picker)

    page = tab.widget
    page.setParent(None)
    page.resize(*PAGE_SIZE)
    page.show()
    tab.frame()
    settle(app)
    save(page, out, "strip", theme, app)

    # The whole band, folded: what a canvas dragged narrow says instead of "D…e".
    strip = tab._toolbar.tools
    page.resize(NARROW, PAGE_SIZE[1])
    settle(app)
    more = strip._more
    more.menu().popup(more.mapToGlobal(QPoint(0, more.height())))
    settle(app)
    save(more.menu(), out, "overflow", theme, app)
    more.menu().hide()
    page.resize(*PAGE_SIZE)
    settle(app)

    # The Features list, beside the canvas where the drag onto it is a short one.
    services.actions.run("canvas.side_panel", services.context.current())
    tab.frame()
    settle(app)
    save(page, out, "features", theme, app)

    page.setParent(None)
    session.close()
    discard(page)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the PNGs")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    with TemporaryDirectory() as tmp:
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
