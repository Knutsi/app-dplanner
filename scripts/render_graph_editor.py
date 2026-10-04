"""Render the graph editor's chrome in the dark and the light theme, to PNG.

    uv run python scripts/render_graph_editor.py --out docs/screenshots/s7-graph-editor
    uv run python scripts/render_graph_editor.py --menus --out docs/screenshots/f7-canvas-menus
    uv run python scripts/render_graph_editor.py --contract --out docs/screenshots/f15-contract
    uv run python scripts/render_graph_editor.py --stacks \
        --out docs/screenshots/s16-stack-one-tall-card
    uv run python scripts/render_graph_editor.py --stack-edits \
        --out docs/screenshots/s17-editing-a-stack
    uv run python scripts/render_graph_editor.py --stack-canvas \
        --out docs/screenshots/s18-stack-on-the-canvas
    uv run python scripts/render_graph_editor.py --restack \
        --out docs/screenshots/f19-restack
    uv run python scripts/render_graph_editor.py --auto-progress \
        --out docs/screenshots/f11-auto-progress
    uv run python scripts/render_graph_editor.py --review \
        --out docs/screenshots/f12-automatic-review
    uv run python scripts/render_graph_editor.py --flow --out docs/screenshots/f20-flow
    uv run python scripts/render_graph_editor.py --branches \
        --out docs/screenshots/branch-stretches
    uv run python scripts/render_graph_editor.py --waves \
        --out docs/screenshots/f28-wave-view

What S7 reworked: the strip of verbs over the canvas as glyphs in named bands, folding
whole bands into its ``…`` menu; the *Find* picker, which opens on the plan's landmarks
and searches every step; and the panel beside the canvas — the Problems list — inside the
project tab rather than across the window. Since F5, the cards themselves (``cards``):
each kind of step, who works it in the key block, the status washes, and a card at the
minimum size. Since F7, with ``--menus`` and nothing else, what a right-click offers by what
is under it; since F15, with ``--contract``, Divide's dropdown offering Contract and a
contract held mid-drag; since S16, with ``--stacks``, a stacked chain drawn as a column on
the canvas and as a frame in the report; since S17, with ``--stack-edits``, a member
deleted with the chain closing round it and a broken stack in the Problems list; since S18,
with ``--stack-canvas``, the stack's frame and its "+", the chain drawn down its middle with
an auto-progress link doubled, the whole stack picked, a link aimed at its middle landing on
its first step, a broken stack's gap, the frame's right-click and the strip's two stack
verbs; since F19, with ``--restack``, the frame's Shift hint under the pointer, a card
Shift-dragged to the top with the cards easing down to open its slot, one dragged out past
the frame, and a loose step dragged in — since S40 with no key held; since F11,
with ``--auto-progress``, parallel work handed to a step that collects it: the doubled
links, and the arrow's menu with the toggle on; since F12, with ``--review``, a step and its
review, the link into the review doubled by rule and its menu's toggle ticked and greyed; since
F20, with ``--flow``, where work moves on its own and where a person is next: the talk bubble
on the link into a review, a collector's doubled links, and the steps a person moves next
pulsing — at the height of a breath, at rest, and with the review picked; since F28, with
``--waves``, one plan as its author arranged it and then in Wave view — every card in the
column of its wave under the ruler, the strip's *Free | Waves* lit on Waves; and with
``--branches``, a stretch put on a feature branch — the right-click that puts it there, then
its cut and landing, the lane under its arrows and the strip under its cards, planned, in
flight and landed. A
whole application is built over a throwaway library — the tab is the tab host's, so nothing
here hand-wires a surface the window would build differently — and torn down per theme.
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
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.services import AppServices
from dplanner.framework.session import AppSession
from dplanner.modules import _report_sources, _step_key, _step_kind
from dplanner.modules.auto_progress.aspect import MODULE_ID as AUTO_PROGRESS_ID
from dplanner.modules.auto_progress.aspect import write as auto_progress_write
from dplanner.modules.estimation.aspect import write as estimate_write
from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.project_editor.items import StepNodeItem
from dplanner.modules.project_editor.layout_verbs import set_wave_view
from dplanner.modules.project_editor.modes import RestackMode
from dplanner.modules.project_editor.module import ProjectActivity, ProjectEditorModule
from dplanner.modules.project_editor.positions import (
    MIN_NODE_H,
    MIN_NODE_W,
    write_member,
    write_position,
)
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.project_editor.renderers import PULSE_PERIOD
from dplanner.modules.project_editor.selection import EdgeRef
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import write_state as agent_write
from dplanner.modules.step_agent_run.aspect import MODULE_ID as AGENT_RUN_ID
from dplanner.modules.step_agent_run.aspect import write as agent_run_write
from dplanner.modules.step_check.aspect import MODULE_ID as CHECK_ID
from dplanner.modules.step_check.aspect import write as check_write
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as milestone_write
from dplanner.modules.step_review.aspect import MODULE_ID as REVIEW_ID
from dplanner.modules.step_review.aspect import ReviewSettings
from dplanner.modules.step_review.aspect import write as review_write
from dplanner.modules.step_wait.aspect import MODULE_ID as WAIT_ID
from dplanner.modules.step_wait.aspect import write as wait_write
from dplanner.planning.schedule import Wait
from dplanner.planning.status import MODULE_ID as STATUS_ID
from dplanner.planning.status import read as status_for
from dplanner.planning.status import write as status_write
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
# F12: a step, its review, and what follows the review — never the step directly.
REVIEWED = (
    ("Build the parser", (0.0, 0.0), "ready-for-review", False),
    ("Review the parser", (340.0, 0.0), "in-progress", True),
    ("Ship the parser", (680.0, 0.0), "", False),
)
REVIEW_SIZE = (1100, 480)
# F20: where work moves on its own and where a person is next. Title, seat, status, the
# agent run, whether an agent works it and whether it is a review; then who waits on whom,
# and which of those links auto-progress by flag.
FLOW = (
    ("Build the parser", (0.0, -240.0), "ready-for-review", "", True, False),
    ("Review the parser", (380.0, -240.0), "in-progress", "working", True, True),
    ("Parse the dates", (0.0, -90.0), "ready-for-review", "", True, False),
    ("Map the columns", (0.0, 40.0), "in-progress", "working", True, False),
    ("Merge the import round", (380.0, -25.0), "", "", True, False),
    ("Write the release notes", (380.0, 150.0), "ready-for-review", "", False, False),
    ("Land the loader", (380.0, 280.0), "ready-to-merge", "", True, False),
    ("Ship the importer", (760.0, -25.0), "", "", False, False),
)
FLOW_LINKS = (
    ("Review the parser", "Build the parser", False),
    ("Merge the import round", "Parse the dates", True),
    ("Merge the import round", "Map the columns", True),
    ("Ship the importer", "Review the parser", False),
    ("Ship the importer", "Merge the import round", False),
    ("Ship the importer", "Write the release notes", False),
    ("Ship the importer", "Land the loader", False),
)
FLOW_SIZE = (1320, 600)

# A line of work that kept growing, stacked (S16): a chain in, three steps as one tall card,
# and the milestone after it — placed by the ambient layout, which folds the stack like
# every other arrangement.
STACKED = ("Read the fixtures", "Write the parser", "Parse the dates", "Map the columns")
STACK_SIZE = (1180, 560)

# Wave view (F28): the guide's figure, as a plan — a start, a wide first wave mostly done, one
# step everything after waits on, and a stack at the end. Each is (title, estimate, status,
# what it waits on, where its author left it). The author's arrangement is deliberately not
# by wave, so the two shots differ.
WAVE_PLAN = (
    ("Project start", 0.0, "done", (), (-320.0, 200.0)),
    ("Retire canvas renderer fallbacks", 1.0, "done", (0,), (0.0, -120.0)),
    ("Ready for review hands off to a human", 1.5, "in-progress", (0,), (320.0, 360.0)),
    ("New Project asks where it should live", 1.25, "done", (0,), (0.0, 360.0)),
    ("Primary icons on the main strip", 1.25, "done", (0,), (-320.0, -120.0)),
    ("A Start marker: a step with no inputs", 1.0, "done", (0,), (0.0, 120.0)),
    ("Right-click by what is under the cursor", 1.5, "", (1,), (320.0, 0.0)),
    ("Contract: close up the step API", 1.25, "", (6,), (640.0, -120.0)),
    ("The menu bar, sorted by task", 1.25, "", (6,), (960.0, 120.0)),
    ("Auto-progress links", 1.5, "", (6, 2), (640.0, 360.0)),
    ("A stack is one tall card", 1.5, "", (7,), (960.0, -240.0)),
    ("Editing a stack", 1.0, "", (10,), (0.0, 0.0)),
)
WAVE_STACK = (10, 11)
WAVES_SIZE = (1400, 760)


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


def press(
    view: QGraphicsView,
    kind: QEvent.Type,
    scene_pos: QPointF,
    held: bool = True,
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> None:
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
            modifiers,
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
    # Two ticks of the motion clock, so the flowing link's chevrons stand where they would a
    # moment in, as the ring beside them does.
    tab._scene.advance_motion()
    tab._scene.advance_motion()
    save(page, out, "round", theme, app)
    page.setParent(None)
    session.close()
    discard(page)


def open_stacked(
    app: QApplication, theme: Theme, workspace: Path, name: str
) -> tuple[AppSession, AppServices, list[StepId], ProjectActivity]:
    """A whole application over a throwaway library holding a stacked chain — a step in,
    three stacked, the milestone after — nobody having placed it, its tab open."""
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
    library = services.document

    directory = seed_project(workspace / f"{name}-{theme.name}", "Importer")
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
    return session, services, made, tab


def render_stacks(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """A stacked chain on the canvas — a column under its first member, nobody having placed
    it — and the same plan's graph in the report, where the frame is drawn and the chain's
    arrows are left out."""
    session, services, made, tab = open_stacked(app, theme, workspace, "stacks")
    library = services.document
    project = library.project_of(made[0])
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


def render_review(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """A step and its review: the link into the review doubled though nobody flagged it,
    and that arrow's right-click with *Auto-progress* ticked and greyed, saying why."""
    QSettings().clear()
    apply_theme(app, theme)
    library_file = workspace / f"review-library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)
    library = services.document

    directory = seed_project(workspace / f"review-{theme.name}", "Parser")
    project = services.repo.attach(directory)
    library.add_child(library.id, project)
    made = []
    for title, (x, y), status, review in REVIEWED:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        SetModuleDataCommand(step.id, POSITION_KEY, write_position(x, y)).redo(library)
        library.set_text(step.id, "step_description", f"{title}, in full.")
        SetModuleDataCommand(step.id, "estimation", estimate_write(0.25)).redo(library)
        SetModuleDataCommand(step.id, AGENT_ID, agent_write(True)).redo(library)
        if status:
            SetModuleDataCommand(step.id, STATUS_ID, status_write(status, today=DAY)).redo(library)
        if review:
            SetModuleDataCommand(step.id, REVIEW_ID, review_write(ReviewSettings())).redo(library)
            SetModuleDataCommand(step.id, AGENT_RUN_ID, agent_run_write("working")).redo(library)
        made.append(step.id)
    work, review_id, ship = made
    SetEdgesCommand(review_id, "requires", [work]).redo(library)
    SetEdgesCommand(ship, "requires", [review_id]).redo(library)

    tab = services.tabs.open("project", project.id)
    assert isinstance(tab, ProjectActivity)
    page = tab.widget
    page.resize(*REVIEW_SIZE)
    page.show()
    tab.frame()
    settle(app)
    # The right-click first, while the tab is the tab host's current one and publishes.
    arrow = tab._scene._edges[EdgeRef(waiter=review_id, kind="requires", source=work)]
    menu = tab.context_menu(tab._view.mapFromScene(arrow.path().pointAtPercent(0.5)))
    menu.popup(QPoint(0, 0))
    save(menu, out, "menu-review-arrow", theme, app)
    menu.hide()
    discard(menu)

    tab._scene.select_steps([])
    page.setParent(None)
    page.resize(*REVIEW_SIZE)
    page.show()
    tab.frame()
    tab._scene.advance_motion()
    tab._scene.advance_motion()
    save(page, out, "pair", theme, app)
    page.setParent(None)
    session.close()
    discard(page)


def render_flow(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """Where the work moves on its own and where a person is next: the talk bubble on the
    link into a review, a collector's links doubled and one flowing, and the two steps a
    person moves next — a review nobody takes on, a merge — pulsing. Shot at the height of
    a breath, at rest, and with the review picked, its bubble lit with its arrow."""
    QSettings().clear()
    apply_theme(app, theme)
    library_file = workspace / f"flow-library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)
    library = services.document

    directory = seed_project(workspace / f"flow-{theme.name}", "Importer")
    project = services.repo.attach(directory)
    library.add_child(library.id, project)
    made: dict[str, StepId] = {}
    for title, (x, y), status, run, agent, review in FLOW:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        SetModuleDataCommand(step.id, POSITION_KEY, write_position(x, y)).redo(library)
        library.set_text(step.id, "step_description", f"{title}, in full.")
        SetModuleDataCommand(step.id, "estimation", estimate_write(0.25)).redo(library)
        if agent:
            SetModuleDataCommand(step.id, AGENT_ID, agent_write(True)).redo(library)
        if status:
            SetModuleDataCommand(step.id, STATUS_ID, status_write(status, today=DAY)).redo(library)
        if run:
            SetModuleDataCommand(step.id, AGENT_RUN_ID, agent_run_write(run)).redo(library)
        if review:
            SetModuleDataCommand(step.id, REVIEW_ID, review_write(ReviewSettings())).redo(library)
        made[title] = step.id
    waits: dict[str, list[StepId]] = {}
    flagged: dict[str, list[StepId]] = {}
    for waiter, source, flag in FLOW_LINKS:
        waits.setdefault(waiter, []).append(made[source])
        if flag:
            flagged.setdefault(waiter, []).append(made[source])
    for waiter, sources in waits.items():
        SetEdgesCommand(made[waiter], "requires", sources).redo(library)
    for waiter, sources in flagged.items():
        SetModuleDataCommand(made[waiter], AUTO_PROGRESS_ID, auto_progress_write(sources)).redo(
            library
        )

    tab = services.tabs.open("project", project.id)
    assert isinstance(tab, ProjectActivity)
    page = tab.widget
    page.resize(*FLOW_SIZE)
    page.show()
    tab.frame()
    settle(app)
    tab._scene.select_steps([])
    # The height of a breath: half a pulse's period on the motion clock.
    while tab._scene._phase < PULSE_PERIOD / 2:
        tab._scene.advance_motion()
    save(page, out, "flow", theme, app)
    while tab._scene._phase % PULSE_PERIOD:
        tab._scene.advance_motion()
    save(page, out, "flow-rest", theme, app)
    tab._scene.select_steps([made["Review the parser"]])
    while tab._scene._phase % PULSE_PERIOD != PULSE_PERIOD / 2:
        tab._scene.advance_motion()
    save(page, out, "flow-picked", theme, app)
    page.setParent(None)
    session.close()
    discard(page)


def render_stack_canvas(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """A stack on the canvas (S18): its frame and "+", the way in at the top and out under
    the "+", the chain down its middle — one link of it doubled — then the stack picked by a
    click on its frame, a link from a loose step aimed at its middle card lighting the
    first, a broken stack's gap, the frame's right-click, and the strip's Step band."""
    session, services, made, tab = open_stacked(app, theme, workspace, "stack-canvas")
    library = services.document
    project = library.project_of(made[0])
    loose = Step(title="Check the encoding")
    AddNodeCommand(project.id, loose).redo(library)
    SetModuleDataCommand(loose.id, POSITION_KEY, write_position(40.0, 360.0)).redo(library)
    SetModuleDataCommand(made[3], AUTO_PROGRESS_ID, auto_progress_write([made[2]])).redo(library)
    SetEdgesCommand(made[-1], "requires", [made[3], loose.id]).redo(library)
    # Described, so the squiggles say nothing this shot is not about.
    for step_id in (*made, loose.id):
        library.set_text(step_id, "step_description", "What the step delivers.")
    page = tab.widget
    page.resize(*STACK_SIZE)
    page.show()
    tab.frame()
    scene, view = tab._scene, tab._view
    save(page, out, "frame", theme, app)

    (frame,) = scene._frames.values()
    rect = frame.frame_scene_rect()
    pad = QPointF(rect.left() + 8.0, rect.center().y())
    press(view, QEvent.Type.MouseButtonPress, pad)
    press(view, QEvent.Type.MouseButtonRelease, pad, held=False)
    save(page, out, "picked", theme, app)
    scene.select_steps([])

    node = scene.node(loose.id)
    middle = scene.node(made[2])
    assert node is not None and middle is not None
    press(view, QEvent.Type.MouseButtonPress, node.handle_scene_pos())
    press(view, QEvent.Type.MouseMove, middle.body_scene_rect().center())
    save(page, out, "aim", theme, app)
    view.modes.pop_to_base()

    menu = tab.context_menu(view.mapFromScene(pad))
    menu.popup(QPoint(0, 0))
    save(menu, out, "menu-frame", theme, app)
    menu.hide()
    discard(menu)
    scene.select_steps([])

    tab._toolbar.resize(tab._toolbar.sizeHint().width(), tab._toolbar.height())
    save(tab._toolbar, out, "strip", theme, app)

    # Another writer's edit: the stack's second step no longer waits on its first.
    library.set_edges(made[2], "requires", [], rules=False)
    tab.frame()
    save(page, out, "broken", theme, app)
    page.setParent(None)
    session.close()
    discard(page)


def render_restack(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """Restacking one card (F19): the frame saying what Shift does while the pointer is over
    it; its last card Shift-dragged to the top, the cards above eased down to open the slot;
    its middle card dragged out past the frame, the column closed up and the card's links
    faded; and a loose step dragged in between its first two cards, a plain drag (S40)."""
    session, services, made, tab = open_stacked(app, theme, workspace, "restack")
    library = services.document
    project = library.project_of(made[0])
    loose = Step(title="Check the encoding")
    AddNodeCommand(project.id, loose).redo(library)
    SetModuleDataCommand(loose.id, POSITION_KEY, write_position(40.0, 360.0)).redo(library)
    # Described, so the squiggles say nothing this shot is not about.
    for step_id in (*made, loose.id):
        library.set_text(step_id, "step_description", "What the step delivers.")
    page = tab.widget
    page.resize(*STACK_SIZE)
    page.show()
    tab.frame()
    scene, view = tab._scene, tab._view
    first, middle, last = (scene.node(step_id) for step_id in made[1:4])
    card = scene.node(loose.id)
    assert first is not None and middle is not None and last is not None and card is not None
    shift = Qt.KeyboardModifier.ShiftModifier

    press(view, QEvent.Type.MouseMove, middle.body_scene_rect().center(), held=False)
    save(page, out, "hint", theme, app)

    def restacked(
        node: StepNodeItem, to: QPointF, name: str, keys: Qt.KeyboardModifier = shift
    ) -> None:
        grip = node.body_scene_rect().center()
        press(view, QEvent.Type.MouseButtonPress, grip, modifiers=keys)
        press(view, QEvent.Type.MouseMove, to, modifiers=keys)
        mode = view.modes.current()
        assert isinstance(mode, RestackMode)
        mode.settle()
        save(page, out, name, theme, app)
        mode.restore()
        view.modes.pop_to_base()

    top = first.body_scene_rect()
    restacked(last, QPointF(top.center().x() + 24.0, top.center().y() + 8.0), "make-way")
    frame = scene.frame("demo")
    assert frame is not None
    rect = frame.frame_scene_rect()
    away = QPointF(rect.right() + 140.0, rect.bottom() + 40.0)
    restacked(middle, away, "leaving")
    plain = Qt.KeyboardModifier.NoModifier
    restacked(card, middle.body_scene_rect().center() + QPointF(24.0, 0.0), "joining", plain)
    page.setParent(None)
    session.close()
    discard(page)


def render_stack_edits(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """Editing a stack (S17): the middle member picked, then deleted — the chain closes round
    the gap — and a stack another writer broke, named in the Problems list beside the
    canvas with the link that mends it."""
    session, services, made, tab = open_stacked(app, theme, workspace, "stack-edits")
    library = services.document
    # Described, so the squiggles and the list say what this shot is about and nothing else.
    for step_id in made:
        library.set_text(step_id, "step_description", "What the step delivers.")
    page = tab.widget
    page.resize(*STACK_SIZE)
    page.show()
    tab.select_steps([made[2]])
    tab.frame()
    save(page, out, "delete-before", theme, app)

    services.actions.run("steps.delete", services.context.current())
    tab.frame()
    save(page, out, "delete-after", theme, app)

    # Another writer's edit: the stack's last member no longer waits on its first. Carried
    # the way the store adopts it — no rule judges another writer's links.
    library.set_edges(made[3], "requires", [], rules=False)
    editor = next(m for m in services.modules if isinstance(m, ProjectEditorModule))
    services.actions.run("canvas.side_panel", services.context.current())
    tab.set_look(editor._look)
    tab.frame()
    save(page, out, "broken", theme, app)
    page.setParent(None)
    session.close()
    discard(page)


# The exploration's plan, for --branches: the menu on main, then the stacks work fanning out
# and back in, put on a feature branch between a cut and a landing, and the release after.
BRANCHED = (
    ("Menu bar", (0, 160)),
    ("Home page", (840, 0)),
    ("A stack is one card", (560, 160)),
    ("Editing a stack", (840, 100)),
    ("Stacks on the canvas", (840, 240)),
    ("Drag to reorder", (1120, 160)),
    ("Changes 2", (1680, 80)),
)
BRANCHED_LINKS = ((1, 0), (2, 0), (3, 2), (4, 2), (5, 3), (5, 4), (6, 5), (6, 1))
ON_BRANCH = (2, 3, 4, 5)
# Where the plan stands in each shot: nothing started past the menu; the branch half done;
# landed, and its lane gone.
BRANCH_STATES = {
    "planned": {0: "done"},
    "in-flight": {0: "done", 1: "in-progress", 2: "done", 3: "done", 4: "ready-for-review"},
    "landed": {0: "done", 1: "done", 2: "done", 3: "done", 4: "done", 5: "done", "land": "done"},
}
BRANCH_SIZE = (1980, 560)


def render_branches(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """A stretch on a feature branch: the cut and the landing bracketing it, the lane under
    its arrows and the strip under its cards — planned, in flight (done work still on its
    lane, since it is not on main yet) and landed (the lane gone, the strips quiet) — and
    the right-click on the picked stretch offering Put on a Branch."""
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
    from dplanner.modules import _branch_births
    from dplanner.modules.branches.edits import put_command

    QSettings().clear()
    apply_theme(app, theme)
    library_file = workspace / f"branch-library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)
    library = services.document

    directory = seed_project(workspace / f"branch-{theme.name}", "Changes")
    project = services.repo.attach(directory)
    library.add_child(library.id, project)
    made: list[StepId] = []
    for title, (x, y) in BRANCHED:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        SetModuleDataCommand(step.id, POSITION_KEY, write_position(x, y)).redo(library)
        SetModuleDataCommand(step.id, "estimation", estimate_write(0.25)).redo(library)
        library.set_text(step.id, "step_description", f"{title}, in full.")
        if title != "Changes 2":
            SetModuleDataCommand(step.id, AGENT_ID, agent_write(True)).redo(library)
        made.append(step.id)
    SetModuleDataCommand(made[-1], MILESTONE_ID, milestone_write("Changes 2")).redo(library)
    for waiter, source in BRANCHED_LINKS:
        held = library.step(made[waiter]).edges.get("requires", [])
        SetEdgesCommand(made[waiter], "requires", [*held, made[source]]).redo(library)

    tab = services.tabs.open("project", project.id)
    assert isinstance(tab, ProjectActivity)
    page = tab.widget
    page.resize(*BRANCH_SIZE)
    page.show()
    tab.frame()
    settle(app)
    # The right-click on the picked stretch, before it is on a branch.
    picked = [made[index] for index in ON_BRANCH]
    tab._scene.select_steps(picked)
    node = tab._scene._nodes[made[3]]
    menu = tab.context_menu(tab._view.mapFromScene(node.sceneBoundingRect().center()))
    menu.popup(QPoint(0, 0))
    save(menu, out, "menu", theme, app)
    menu.hide()
    discard(menu)
    tab._scene.select_steps([])

    cut, land = _branch_births(project, "feature/stacks")
    seats = [
        SetModuleDataCommand(cut.id, POSITION_KEY, write_position(280, 160)),
        SetModuleDataCommand(land.id, POSITION_KEY, write_position(1400, 160)),
    ]
    put_command(library, picked, cut, land, carrying=seats).redo(library)
    for name, states in BRANCH_STATES.items():
        for index, step_id in enumerate(made):
            word = states.get(index, "pending")
            SetModuleDataCommand(step_id, STATUS_ID, status_write(word, today=DAY)).redo(library)
        word = states.get("land", "pending")
        SetModuleDataCommand(land.id, STATUS_ID, status_write(word, today=DAY)).redo(library)
        page.setParent(None)
        page.resize(*BRANCH_SIZE)
        page.show()
        settle(app)
        tab.frame()
        save(page, out, name, theme, app)
    # And the right-click on a step already on the branch, offering to remove it whole.
    member = Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", made[3])),)})
    assert services.actions.spec("branch.remove").state(member).enabled
    page.setParent(None)
    session.close()
    discard(page)


def render_waves(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    """One plan as its author left it, then in Wave view: the ruler naming each wave and when
    it runs, the band behind every other column, the stack one tall card in its wave,
    and the strip's switch lit on Waves with the picker saying so."""
    QSettings().clear()
    apply_theme(app, theme)
    library_file = workspace / f"waves-library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)
    library = services.document

    directory = seed_project(workspace / f"waves-{theme.name}", "DPlanner changes 2")
    project = services.repo.attach(directory)
    library.add_child(library.id, project)
    made: list[StepId] = []
    for title, days, status, _sources, (x, y) in WAVE_PLAN:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        SetModuleDataCommand(step.id, POSITION_KEY, write_position(x, y)).redo(library)
        SetModuleDataCommand(step.id, "estimation", estimate_write(days)).redo(library)
        library.set_text(step.id, "step_description", f"{title}, in full.")
        if status:
            SetModuleDataCommand(step.id, STATUS_ID, status_write(status, today=DAY)).redo(library)
        made.append(step.id)
    for index, (*_rest, sources, _seat) in enumerate(WAVE_PLAN):
        if sources:
            SetEdgesCommand(made[index], "requires", [made[s] for s in sources]).redo(library)
    first, *rest = WAVE_STACK
    head = WAVE_PLAN[first][4]
    SetModuleDataCommand(made[first], POSITION_KEY, write_position(*head, stack="demo")).redo(
        library
    )
    for index in rest:
        SetModuleDataCommand(made[index], POSITION_KEY, write_member("demo")).redo(library)

    tab = services.tabs.open("project", project.id)
    assert isinstance(tab, ProjectActivity)
    tab.select_steps([made[6]])
    page = tab.widget
    page.setParent(None)
    page.resize(*WAVES_SIZE)
    page.show()
    tab.frame()
    save(page, out, "free", theme, app)
    # What the module's set_waves does: remember, then show. The page was taken out of the
    # tab host to be sized, so the tab is told directly (render()'s side panel does the same).
    set_wave_view(project.id, True)
    tab.show_waves(True)
    tab.frame()
    save(page, out, "waves", theme, app)
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
        "--stack-edits",
        action="store_true",
        help="only a stack edited: a member deleted, and a broken stack named (S17)",
    )
    parser.add_argument(
        "--restack",
        action="store_true",
        help="only a card restacked: into, through and out of a stack (F19)",
    )
    parser.add_argument(
        "--stack-canvas",
        action="store_true",
        help="only a stack on the canvas: its frame, its +, linking to it (S18)",
    )
    parser.add_argument(
        "--auto-progress",
        action="store_true",
        help="only a round of parallel work and the step that collects it (F11)",
    )
    parser.add_argument(
        "--review", action="store_true", help="only a step and its review (F12), nothing else"
    )
    parser.add_argument(
        "--flow",
        action="store_true",
        help="only the review bubble and the pulsing steps a person moves next (F20)",
    )
    parser.add_argument(
        "--branches",
        action="store_true",
        help="only a stretch on a feature branch: planned, in flight and landed",
    )
    parser.add_argument(
        "--waves", action="store_true", help="only a plan in Free and in Wave view (F28)"
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
            if args.stack_edits:
                render_stack_edits(app, theme, args.out, Path(tmp))
                continue
            if args.stack_canvas:
                render_stack_canvas(app, theme, args.out, Path(tmp))
                continue
            if args.restack:
                render_restack(app, theme, args.out, Path(tmp))
                continue
            if args.auto_progress:
                render_auto_progress(app, theme, args.out, Path(tmp))
                continue
            if args.review:
                render_review(app, theme, args.out, Path(tmp))
                continue
            if args.flow:
                render_flow(app, theme, args.out, Path(tmp))
                continue
            if args.branches:
                render_branches(app, theme, args.out, Path(tmp))
                continue
            if args.waves:
                render_waves(app, theme, args.out, Path(tmp))
                continue
            render(app, theme, args.out, Path(tmp))
            render_cards(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
