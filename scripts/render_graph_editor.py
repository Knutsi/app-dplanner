"""Render the graph editor's chrome in the dark and the light theme, to PNG.

    uv run python scripts/render_graph_editor.py --out docs/screenshots/s7-graph-editor
    uv run python scripts/render_graph_editor.py --menus --out docs/screenshots/f7-canvas-menus
    uv run python scripts/render_graph_editor.py --contract --out docs/screenshots/f15-contract
    uv run python scripts/render_graph_editor.py --stacks \
        --out docs/screenshots/s16-stack-one-tall-card
    uv run python scripts/render_graph_editor.py --auto-progress \
        --out docs/screenshots/f11-auto-progress

What S7 reworked: the strip of verbs over the canvas as glyphs in named bands, folding
whole bands into its ``…`` menu; the *Find* picker, which opens on the plan's landmarks
and searches every step; and the panel beside the canvas — the Problems list — inside the
project tab rather than across the window. Since F5, the cards themselves (``cards``):
each kind of step, who works it in the key block, the status washes, and a card at the
minimum size. Since F7, with ``--menus`` and nothing else, what a right-click offers by what
is under it; since F15, with ``--contract``, Divide's dropdown offering Contract and a
contract held mid-drag; since S16, with ``--stacks``, a stacked chain drawn as a column on
the canvas and as a frame in the report; since F11, with ``--auto-progress``, parallel work
handed to a step that collects it: the doubled links, and the arrow's menu with the toggle
on. A whole application is built over a throwaway library — the tab is the tab host's, so
nothing here hand-wires a surface the window would build differently — and torn down per
theme.
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

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QGraphicsView, QWidget

from dplanner.app import new_session
from dplanner.cli.report.assemble import build as build_report
from dplanner.cli.report.drawings import DARK as REPORT_DARK
from dplanner.cli.report.drawings import LIGHT as REPORT_LIGHT
from dplanner.cli.report.drawings import graph_svg
from dplanner.cli.report.parts import Graph
from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step, StepId
from dplanner.domain.schedule import Wait
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.services import AppServices
from dplanner.framework.session import AppSession
from dplanner.modules import _report_sources, _step_key, _step_kind
from dplanner.modules.auto_progress.aspect import MODULE_ID as AUTO_PROGRESS_ID
from dplanner.modules.auto_progress.aspect import write as auto_progress_write
from dplanner.modules.estimation.aspect import write as estimate_write
from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.project_editor.module import ProjectActivity, ProjectEditorModule
from dplanner.modules.project_editor.positions import (
    MIN_NODE_H,
    MIN_NODE_W,
    write_member,
    write_position,
)
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.project_editor.selection import EdgeRef
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import write_state as agent_write
from dplanner.modules.step_agent_run.aspect import MODULE_ID as AGENT_RUN_ID
from dplanner.modules.step_agent_run.aspect import write as agent_run_write
from dplanner.modules.step_check.aspect import MODULE_ID as CHECK_ID
from dplanner.modules.step_check.aspect import write as check_write
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as milestone_write
from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
from dplanner.modules.step_status.aspect import read as status_for
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
WINDOW_SIZE = (1400, 720)
# How far right the contract shot pushes the feature and the milestone, opening the hole the
# gesture then closes: two empty columns.
HOLE = 600.0

# A round of parallel work and the step that collects it (F11): three agents — one done
# with its work, one working now, one still going — and a plain prerequisite already done,
# all waited on by the step that lands them. The three are auto-progress links.
ROUND = (
    ("Parse the dates", (0.0, -200.0), (("ready-for-review", ""),)),
    ("Map the columns", (0.0, -70.0), (("in-progress", "working"),)),
    ("Stage the loader", (0.0, 60.0), (("in-progress", ""),)),
    ("Read the spec", (0.0, 190.0), (("done", ""),)),
    ("Merge the import round", (420.0, -5.0), ()),
)
ROUND_SIZE = (1100, 560)

# A line of work that kept growing, stacked (S16): a chain in, three steps as one tall card,
# and the milestone after it — placed by the ambient layout, which folds the stack like
# every other arrangement.
STACKED = ("Read the fixtures", "Write the parser", "Parse the dates", "Map the columns")
STACK_SIZE = (1180, 560)


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


def press(view: QGraphicsView, kind: QEvent.Type, scene_pos: QPointF, held: bool = True) -> None:
    """A mouse event at a point on the plane, sent where a real one arrives: the viewport,
    with a real global position — the scene picks what is under the *screen* point."""
    viewport = view.viewport()
    local = QPointF(view.mapFromScene(scene_pos))
    left = Qt.MouseButton.LeftButton
    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            kind,
            local,
            QPointF(viewport.mapToGlobal(local.toPoint())),
            left,
            left if held else Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def render_contract(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """Contract (F15): the Divide button's arrow offering it beside Divide, and the whole
    window mid-drag — the side pulled back, the band it has closed, and the status line
    naming the pair that stopped it."""
    session, services, made, tab = open_importer(app, theme, workspace, "contract")
    # The parser in the feature's row, so the row reads as a chain with a hole in it; then
    # the feature and the milestone two columns further out than they belong.
    seats = {index: seat for index, (_title, seat, _kind) in enumerate(STEPS)}
    seats[1] = (seats[1][0], seats[0][1])
    seats[3] = (seats[3][0] + HOLE, seats[3][1])
    seats[4] = (seats[4][0] + HOLE, seats[4][1])
    for index in (1, 3, 4):
        services.undo.push(
            SetModuleDataCommand(made[index], POSITION_KEY, write_position(*seats[index]))
        )
    window = services.window
    window.resize(*WINDOW_SIZE)
    window.show()
    settle(app)
    tab.frame()
    settle(app)

    button = tab._toolbar.button("canvas.divide_vertical")
    popup = tab._toolbar.menu_for("canvas.divide_vertical")
    assert button is not None and popup is not None
    popup.popup(button.mapToGlobal(QPoint(0, button.height())))
    save(popup, out, "dropdown", theme, app)
    popup.hide()

    services.actions.run("canvas.contract_vertical", services.context.current())
    view, scene = tab._view, tab._scene
    parser = scene.node(made[1])
    assert parser is not None
    body = parser.body_scene_rect()
    cut = QPointF(body.right() + HOLE / 2, body.bottom() + 60.0)
    held = cut + QPointF(-2 * HOLE, 0.0)
    press(view, QEvent.Type.MouseButtonPress, cut)
    press(view, QEvent.Type.MouseMove, held)
    # Framed on the graph as the pull has it, then the same point again, so the band is
    # re-aimed edge to edge of what the new frame shows.
    tab.frame()
    settle(app)
    press(view, QEvent.Type.MouseMove, held)
    save(window, out, "closing", theme, app)

    press(view, QEvent.Type.MouseButtonRelease, cut, held=False)
    window.hide()
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


def render_auto_progress(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """Parallel work handed to a step that collects it: the three auto-progress links doubled,
    chevrons pointing at the collector, the plain link beside them single — and the arrow's
    right-click with *Auto-progress* ticked."""
    QSettings().clear()
    apply_theme(app, theme)
    library_file = workspace / f"round-library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)
    library = services.document

    directory = seed_project(workspace / f"round-{theme.name}", "Importer")
    project = services.repo.attach(directory)
    library.add_child(library.id, project)
    made = []
    for title, (x, y), states in ROUND:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        SetModuleDataCommand(step.id, POSITION_KEY, write_position(x, y)).redo(library)
        library.set_text(step.id, "step_description", f"{title}, in full.")
        SetModuleDataCommand(step.id, "estimation", estimate_write(0.25)).redo(library)
        SetModuleDataCommand(step.id, AGENT_ID, agent_write(True)).redo(library)
        for status, run in states:
            SetModuleDataCommand(step.id, STATUS_ID, status_write(status, today=DAY)).redo(library)
            if run:
                SetModuleDataCommand(step.id, AGENT_RUN_ID, agent_run_write(run)).redo(library)
        made.append(step.id)
    collector, sources = made[-1], made[:3]
    SetEdgesCommand(collector, "requires", made[:-1]).redo(library)
    SetModuleDataCommand(collector, AUTO_PROGRESS_ID, auto_progress_write(sources)).redo(library)

    tab = services.tabs.open("project", project.id)
    assert isinstance(tab, ProjectActivity)
    page = tab.widget
    page.resize(*ROUND_SIZE)
    page.show()
    tab.frame()
    settle(app)
    # The right-click first, while the tab is the tab host's current one and publishes.
    arrow = tab._scene._edges[EdgeRef(waiter=collector, kind="requires", source=sources[0])]
    menu = tab.context_menu(tab._view.mapFromScene(arrow.path().pointAtPercent(0.5)))
    menu.popup(QPoint(0, 0))
    save(menu, out, "menu-arrow", theme, app)
    menu.hide()
    discard(menu)

    tab._scene.select_steps([])
    page.setParent(None)
    page.resize(*ROUND_SIZE)
    page.show()
    tab.frame()
    # Two ticks of the ring clock, so the flowing link's chevrons stand where they would a
    # moment in, as the ring beside them does.
    tab._scene.advance_rings()
    tab._scene.advance_rings()
    save(page, out, "round", theme, app)
    page.setParent(None)
    session.close()
    discard(page)


def render_stacks(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """A stacked chain on the canvas — a column under its first member, nobody having placed
    it — and the same plan's graph in the report, where the frame is drawn and the chain's
    arrows are left out."""
    QSettings().clear()
    apply_theme(app, theme)
    library_file = workspace / f"stacks-library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)
    library = services.document

    directory = seed_project(workspace / f"stacks-{theme.name}", "Importer")
    project = services.repo.attach(directory)
    library.add_child(library.id, project)
    made = []
    for title in (*STACKED, "Ship the importer"):
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        SetModuleDataCommand(step.id, "estimation", estimate_write(0.25)).redo(library)
        made.append(step.id)
    SetModuleDataCommand(made[-1], MILESTONE_ID, milestone_write("Import")).redo(library)
    for waiter, source in zip(made[1:], made, strict=False):
        SetEdgesCommand(waiter, "requires", [source]).redo(library)
    for step_id in made[1:4]:
        SetModuleDataCommand(step_id, POSITION_KEY, write_member("demo")).redo(library)

    tab = services.tabs.open("project", project.id)
    assert isinstance(tab, ProjectActivity)
    page = tab.widget
    page.resize(*STACK_SIZE)
    page.show()
    tab.frame()
    save(page, out, "canvas", theme, app)

    report = build_report(
        library,
        project,
        services.repo.files,
        _report_sources(),
        key_of=_step_key,
        kind_of=_step_kind,
        status_for=status_for,
        today=DAY,
    )
    graph = next(part for part in report.sections["plan"] if isinstance(part, Graph))
    colors = REPORT_DARK if theme is DARK else REPORT_LIGHT
    renderer = QSvgRenderer(graph_svg(graph, colors).encode())
    image = QImage(renderer.defaultSize() * 2, QImage.Format.Format_ARGB32)
    image.fill(QColor(colors.surface))
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    path = out / f"report-{theme.name}.png"
    image.save(str(path), "PNG")
    print(path)
    page.setParent(None)
    session.close()
    discard(page)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the PNGs")
    parser.add_argument(
        "--menus", action="store_true", help="only the right-click menus (F7), nothing else"
    )
    parser.add_argument(
        "--contract", action="store_true", help="only the Contract gesture (F15), nothing else"
    )
    parser.add_argument(
        "--stacks",
        action="store_true",
        help="only a stacked chain on the canvas and in the report (S16)",
    )
    parser.add_argument(
        "--auto-progress",
        action="store_true",
        help="only a round of parallel work and the step that collects it (F11)",
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
            if args.contract:
                render_contract(app, theme, args.out, Path(tmp))
                continue
            if args.stacks:
                render_stacks(app, theme, args.out, Path(tmp))
                continue
            if args.auto_progress:
                render_auto_progress(app, theme, args.out, Path(tmp))
                continue
            render(app, theme, args.out, Path(tmp))
            render_cards(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
