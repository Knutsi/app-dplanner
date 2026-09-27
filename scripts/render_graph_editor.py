"""Render the graph editor's chrome in the dark and the light theme, to PNG.

    uv run python scripts/render_graph_editor.py --out docs/screenshots/s7-graph-editor
    uv run python scripts/render_graph_editor.py --menus --out docs/screenshots/f7-canvas-menus

What S7 reworked: the strip of verbs over the canvas as glyphs in named bands, folding
whole bands into its ``…`` menu; the *Find* picker, which opens on the plan's landmarks
and searches every step; and the panel beside the canvas — the Problems list — inside the
project tab rather than across the window. Since F5, the cards themselves (``cards``):
each kind of step, who works it in the key block, the status washes, and a card at the
minimum size. Since F7, with ``--menus`` and nothing else, what a right-click offers by what
is under it. A whole application is built over a throwaway library — the tab is the tab
host's, so nothing here hand-wires a surface the window would build differently — and torn
down per theme.
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSettings
from PySide6.QtWidgets import QApplication, QWidget

from dplanner.app import new_session
from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step, StepId
from dplanner.domain.schedule import Wait
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.services import AppServices
from dplanner.framework.session import AppSession
from dplanner.modules.estimation.aspect import write as estimate_write
from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.project_editor.module import ProjectActivity, ProjectEditorModule
from dplanner.modules.project_editor.positions import MIN_NODE_H, MIN_NODE_W, write_position
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.project_editor.selection import EdgeRef
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import write_state as agent_write
from dplanner.modules.step_check.aspect import MODULE_ID as CHECK_ID
from dplanner.modules.step_check.aspect import write as check_write
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as milestone_write
from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
from dplanner.modules.step_status.aspect import write as status_write
from dplanner.modules.step_wait.aspect import MODULE_ID as WAIT_ID
from dplanner.modules.step_wait.aspect import write as wait_write
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

PAGE_SIZE = (1180, 620)
NARROW = 520
PICKER_SIZE = (520, 300)

# A plan with the shapes the chrome is about: a milestone to jump to, a feature
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

# The cards, one row per question: who works it (a person, an agent, nobody — a wait), what
# it is (a feature, a check, a milestone), where it stands (in progress, ready for review,
# ready to merge, blocked, done), and the narrowest card there may be. Each row is a chain,
# so no socket is marked as empty.
DAY = date(2026, 9, 21)
CARDS = (
    (
        ("Interview the operators", ()),
        ("Write the column parser", ((AGENT_ID, agent_write(True)),)),
        ("Wait for the export window", ((WAIT_ID, wait_write(Wait(days=3.0))),)),
    ),
    (
        ("Bulk import", ((FEATURE_ID, feature_write()),)),
        ("Import holds on a real dump", ((CHECK_ID, check_write(True)),)),
        ("Ship the importer", ((MILESTONE_ID, milestone_write("Import")),)),
    ),
    (
        (
            "Map the columns",
            ((AGENT_ID, agent_write(True)), (STATUS_ID, status_write("in-progress", today=DAY))),
        ),
        (
            "Parse the dates",
            (
                (AGENT_ID, agent_write(True)),
                (STATUS_ID, status_write("ready-for-review", today=DAY)),
            ),
        ),
        ("Stage the loader", ((STATUS_ID, status_write("ready-to-merge", today=DAY)),)),
        ("Load the fixtures", ((STATUS_ID, status_write("blocked", today=DAY)),)),
        ("Read the spec", ((STATUS_ID, status_write("done", today=DAY)),)),
    ),
)
CARDS_SIZE = (1400, 520)


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


def open_importer(
    app: QApplication, theme: Theme, workspace: Path, name: str
) -> tuple[AppSession, AppServices, list[StepId], ProjectActivity]:
    """A whole application over a throwaway library holding the Importer plan, its tab open."""
    # Each theme renders the same states, so each starts from the same preferences: the
    # side panel this run opens is written to the (throwaway) store, and the second theme
    # would otherwise open with it already on.
    QSettings().clear()
    apply_theme(app, theme)
    library_file = workspace / f"{name}-library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)

    directory = seed_project(workspace / f"{name}-{theme.name}", "Importer")
    project = services.repo.attach(directory)
    services.document.add_child(services.document.id, project)
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
            SetModuleDataCommand(step.id, FEATURE_ID, feature_write()).redo(services.document)
        made.append(step.id)
    for waiter, source in EDGES:
        # Through the stack, so the strip's History band has something to say.
        services.undo.push(SetEdgesCommand(made[waiter], "requires", [made[source]]))

    tab = services.tabs.open("project", project.id)
    assert isinstance(tab, ProjectActivity)
    return session, services, made, tab


def render(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    session, services, made, tab = open_importer(app, theme, workspace, "importer")
    # A step picked, while the tab is still the window's current one and may say so — so
    # the strip and its … menu read as verbs about something rather than all greyed.
    tab.select_steps([made[3]])
    settle(app)

    # Find, while the tab is still the window's current one — it is what the verb asks.
    editor = next(m for m in services.modules if isinstance(m, ProjectEditorModule))
    picker = editor.find_picker()
    assert picker is not None
    picker.resize(*PICKER_SIZE)
    picker.show()
    save(picker, out, "find", theme, app)
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

    # The Problems list, beside the canvas where what is wrong is fixed. The verb writes
    # the preference and fans it to every *open* tab; this page was taken out of the tab
    # host to be sized, so the tab is no longer one of them and is told directly.
    services.actions.run("canvas.side_panel", services.context.current())
    tab.set_look(editor._look)
    tab.frame()
    settle(app)
    save(page, out, "problems", theme, app)

    page.setParent(None)
    session.close()
    discard(page)


def render_menus(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """What a right-click offers, by what is under it (F7): a card, an arrow, steps and an
    arrow picked together, and empty canvas — each made current by the click, as a person's
    would be, and grabbed as the pop-up the handler would show."""
    session, _services, made, tab = open_importer(app, theme, workspace, "menus")
    page = tab.widget
    page.resize(*PAGE_SIZE)
    page.show()
    tab.frame()
    settle(app)
    scene, view = tab._scene, tab._view
    arrow = scene._edges[EdgeRef(waiter=made[3], kind="requires", source=made[2])]

    def card(index: int) -> QPointF:
        node = scene.node(made[index])
        assert node is not None
        return node.body_scene_rect().center()

    def mixed() -> QPointF:
        scene.select_steps([made[1], made[2]])
        arrow.setSelected(True)
        return card(1)

    shots = (
        ("menu-card", lambda: card(3)),
        ("menu-arrow", lambda: arrow.path().pointAtPercent(0.5)),
        ("menu-mixed", mixed),
        ("menu-background", lambda: QPointF(-900.0, 600.0)),
    )
    for name, aim in shots:
        menu = tab.context_menu(view.mapFromScene(aim()))
        menu.popup(QPoint(0, 0))
        save(menu, out, name, theme, app)
        menu.hide()
        discard(menu)

    session.close()


def render_cards(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """The cards on their own, with nothing beside the canvas: what each one says at a
    glance, in the key block down its left edge and on its top edge."""
    QSettings().clear()
    apply_theme(app, theme)
    library_file = workspace / f"cards-library-{theme.name}.json"
    create_library(library_file)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)

    directory = seed_project(workspace / f"cards-{theme.name}", "Cards")
    project = services.repo.attach(directory)
    services.document.add_child(services.document.id, project)
    rows = [
        *(
            [
                (title, aspects, (column * 280.0, row * 120.0), None)
                for column, (title, aspects) in enumerate(cards)
            ]
            for row, cards in enumerate(CARDS)
        ),
        # Clear of the minimap, which stands over the canvas's bottom-left corner.
        [("Tidy the column names", (), (2 * 280.0, 3 * 120.0), (MIN_NODE_W, MIN_NODE_H))],
    ]
    for row in rows:
        previous = None
        for title, aspects, (x, y), size in row:
            step = Step(title=title)
            AddNodeCommand(project.id, step).redo(services.document)
            position = write_position(x, y, size) if size else write_position(x, y)
            SetModuleDataCommand(step.id, POSITION_KEY, position).redo(services.document)
            # Described and estimated, so lint has nothing to say and no card wears the
            # squiggle: this shot is about what a card says when nothing is wrong with it.
            services.document.set_text(step.id, "step_description", f"{title}, in full.")
            SetModuleDataCommand(step.id, "estimation", estimate_write(2.0)).redo(services.document)
            for module_id, entry in aspects:
                SetModuleDataCommand(step.id, module_id, entry).redo(services.document)
            if previous is not None:
                SetEdgesCommand(step.id, "requires", [previous]).redo(services.document)
            previous = step.id

    tab = services.tabs.open("project", project.id)
    page = tab.widget
    page.setParent(None)
    page.resize(*CARDS_SIZE)
    page.show()
    tab.frame()
    settle(app)
    save(page, out, "cards", theme, app)
    page.setParent(None)
    session.close()
    discard(page)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the PNGs")
    parser.add_argument(
        "--menus", action="store_true", help="only the right-click menus (F7), nothing else"
    )
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    with TemporaryDirectory() as tmp:
        # Opening the side panel writes a per-user preference, and a render script must not
        # touch the developer's settings — nor read them, or the shot shows whatever state
        # this machine happens to be in. The suite's conftest redirects QSettings for the
        # same two reasons.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tmp)
        for theme in (DARK, LIGHT):
            if args.menus:
                render_menus(app, theme, args.out, Path(tmp))
                continue
            render(app, theme, args.out, Path(tmp))
            render_cards(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
