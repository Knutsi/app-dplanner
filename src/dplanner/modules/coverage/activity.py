"""The Coverage tab: one project's trace, drawn — with a strip above it saying, per
document, how much of the spec is cited, the verb that lights what wants a look, and the
switch that stands the steps between the spec and its tests.

The tab owns nothing the trace does not: it asks ``trace_of`` on every coalesced change
of its project, hands the answer to the scene, and turns the scene's gestures into the
same verbs every other view runs — the picks publish their steps, a double-click opens
the thing through the callbacks the composition root wired, a right-click renders the
Step menu. It never reaches another module.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QKeyEvent, QPainter, QResizeEvent
from PySide6.QtWidgets import QGraphicsView, QHBoxLayout, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, Project, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import EntityActivity, follow_project
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import SETTLE_MS, Debounced, DebounceService
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.tabs import TabHost
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import EmptyState, note
from dplanner.modules.coverage.scene import GUTTER, LANE_MIN_W, MARGIN, CoverageScene
from dplanner.modules.coverage.trace import (
    FEATURES,
    MILESTONES,
    OUTCOMES,
    SPEC,
    STEPS,
    Trace,
    flat,
)
from dplanner.theme.icons import eye_icon, graph_icon
from dplanner.theme.tokens import CONTROL_GAP, FIELD_GAP

COVERAGE_KIND = "coverage"
# The lanes, left to right: the four the tab opens on, and the same with the steps standing
# between the spec and the tests and documents that sit on them — a lane the reader asks for.
LANES = (MILESTONES, FEATURES, SPEC, OUTCOMES)
WITH_STEPS = (MILESTONES, FEATURES, SPEC, STEPS, OUTCOMES)
STEPS_TIP = "The steps each pick holds, in a lane between the spec and its tests"
# What the tab asks the layout for, and the least it can be cut to: the four lanes it opens
# on at their narrowest, and one — constants, because a hint read off the scene would grow
# with the pane.
WANTED = QSize(int(4 * LANE_MIN_W + 3 * GUTTER + 2 * MARGIN), 420)
FLOOR = QSize(int(LANE_MIN_W + 2 * MARGIN), 160)
NO_DOCUMENTS = "No spec documents — import one to trace it"
NOTHING_TRACED = (
    "Nothing to trace yet. Import a spec on the Specs tab, and cite its passages from the "
    "features that deliver them."
)

type TraceOf = Callable[[Library, Project, FilesFor], Trace]
# (project, document, quotes, focus) → the Specs tab washed at those passages.
type ShowPassages = Callable[[NodeId, str, list[str], str], None]


@dataclass(frozen=True)
class CoverageDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    debounce: DebounceService
    files: FilesFor
    trace_of: TraceOf
    parent: QWidget | None = None
    # The other surfaces a double-click reaches, each wired by the composition root and
    # None in a build without that surface.
    show_passages: ShowPassages | None = None
    open_docs: Callable[[NodeId, StepId], None] | None = None
    # What a step is, for the Step ▸ open verbs' states — the aspects' Qt-free readers.
    feature_of: Callable[[StepId], str | None] = lambda _step: None
    is_milestone: Callable[[StepId], bool] = lambda _step: False
    tests_of: Callable[[StepId], list[str]] = lambda _step: []
    # (step) → [(document, quote)]: the passages a step reaches, its own feature's or the
    # gathering feature's — "a work step reaches the spec through the feature it flows into".
    passages_of: Callable[[StepId], list[tuple[str, str]]] = lambda _step: []


class CoverageView(QGraphicsView):
    """The viewport: the lanes laid to its width, and a horizontal scroll bar only when
    the lanes at their narrowest still do not fit — a finite extent, so the bar is honest.

    **Its size hint is a constant, and it has to be.** ``QGraphicsView`` hands out the
    scene rect as its size hint, and this scene's rect is laid to the viewport — so a
    splitter honouring the hint widens the view, which widens the scene, which widens the
    hint again: opening the tab pushed the index panel off the left of the window, and
    dragging the seam jumped. Nothing here reports a width it was given.
    """

    def __init__(self, scene: CoverageScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setObjectName("GraphView")  # The canvas's ground: $BG_BASE, no frame.
        self._scene = scene
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return WANTED

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return FLOOR

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        size = self.viewport().size()
        self._scene.relayout((float(size.width()), float(size.height())))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self._scene.pick(None)
            event.accept()
            return
        super().keyPressEvent(event)


class CoverageActivity(EntityActivity):
    """One project's coverage picture."""

    def __init__(self, deps: CoverageDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self.project_id = project_id
        self.trace: Trace | None = None

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # The Specs tab's strip: flush over the view on the editor's ground, its verbs then
        # what the data says, the indicator at the far right outside the verbs.
        self.strip = QWidget(page)
        self.strip.setObjectName("EditorToolbar")
        row = QHBoxLayout(self.strip)
        row.setContentsMargins(FIELD_GAP, FIELD_GAP, FIELD_GAP, FIELD_GAP)
        row.setSpacing(CONTROL_GAP)
        self.controls = Toolbar(self.strip)
        self.review_action = self.controls.add_verb(
            "Review",
            eye_icon,
            self._review,
            tip="Light every passage that no longer simply anchors",
        )
        self.steps_action = self.controls.add_verb(
            "Show steps", graph_icon, self._show_steps, checkable=True, tip=STEPS_TIP
        )
        # The stretch is the strip's: a Toolbar's size hint is its … button.
        row.addWidget(self.controls, 1)
        self.summary = note("", self.strip)
        self.summary.setWordWrap(False)
        row.addWidget(self.summary)
        self.updating = UpdatingIndicator(self.strip)
        row.addWidget(self.updating)
        layout.addWidget(self.strip)

        self.scene = CoverageScene(LANES)
        self.scene.picked_changed.connect(self._on_picked)
        self.scene.picked_changed.connect(self._reveal_next_lane)
        self.scene.activated.connect(self._on_activated)
        self.scene.menu_requested.connect(self._on_menu)
        self.view = CoverageView(self.scene, page)
        layout.addWidget(self.view, 1)
        self.empty = EmptyState(parent=page, stands_in_for=self.view)
        layout.addWidget(self.empty, 1)
        self._widget = page

        self._refresh_soon = Debounced(
            self._refresh, delay_ms=SETTLE_MS, parent=page, service=deps.debounce
        )
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            follow_project(deps.library, project_id, self._refresh_soon.trigger),
        ]
        self._refresh()

    # -- the activity contract -------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(COVERAGE_KIND, self.project_id)

    @property
    def title(self) -> str:
        return f"{self._project().title or 'Untitled project'} — Coverage"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []
        self.controls.dispose()

    def focus(self, item_id: str) -> None:
        """Light ``item_id``'s path and bring it into view — a jump's landing."""
        self.scene.focus(item_id)

    def focus_passage(self, document: str, quote: str) -> None:
        """Land on the passage item citing ``quote`` of ``document``."""
        if self.trace is None:
            return
        key = f"{document}\0"
        for item in self.trace.column(SPEC):
            kind, target = item.target
            if (
                kind == "passage"
                and target.startswith(key)
                and flat(target[len(key) :]) == flat(quote)
            ):
                self.focus(item.id)
                return

    # -- reading -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._deps.library.project(self.project_id)

    def _refresh(self) -> None:
        if not self._deps.library.has(self.project_id):
            return
        self.trace = self._deps.trace_of(self._deps.library, self._project(), self._deps.files)
        self.scene.show_trace(self.trace, self.view.font())
        said = [f"{doc.name} · {doc.summary}" for doc in self.trace.documents]
        if self.trace.unsourced:
            count = len(self.trace.unsourced)
            said.append(f"{count} feature{'' if count == 1 else 's'} citing nothing")
        self.summary.setText("   ".join(said) or NO_DOCUMENTS)
        self.review_action.setEnabled(any(doc.review for doc in self.trace.documents))
        # Empty lanes say nothing; a project with nothing in any of them says so instead.
        traced = any(self.trace.column(column) for column in WITH_STEPS)
        self.empty.say("" if traced else NOTHING_TRACED)

    def _show_steps(self) -> None:
        self.scene.set_columns(WITH_STEPS if self.steps_action.isChecked() else LANES)

    def _review(self) -> None:
        """Pick the first passage that wants a look; the others are its neighbours."""
        if self.trace is None:
            return
        for item in self.trace.column(SPEC):
            if item.id.startswith("passage:") and item.state != "anchored":
                self.focus(item.id)
                return

    # -- gestures --------------------------------------------------------------------------

    def _step_of(self, item_id: str) -> StepId | None:
        item = self.trace.item(item_id) if self.trace is not None else None
        if item is None:
            return None
        kind, target = item.target
        if kind == "step":
            return target
        if kind == "test":
            return target.split("\0", 1)[0]
        if kind == "docs":
            return target
        if kind == "feature":
            return target  # A feature's id is its step's.
        return None

    def _reveal_next_lane(self) -> None:
        rect = self.scene.lane_after(self.scene.picked)
        if rect is not None:
            self.view.ensureVisible(rect, 0, 0)

    def _on_picked(self) -> None:
        """Every picked card's step, in the trace's own order — a pick is a selection the
        Step verbs act on, and picking three features is picking three steps."""
        steps: list[StepId] = []
        for item in self.trace.items if self.trace is not None else ():
            step_id = self._step_of(item.id) if item.id in self.scene.picked else None
            if step_id is not None and step_id not in steps and self._deps.library.has(step_id):
                steps.append(step_id)
        self.publish_selection(tuple(ContextNode(selection_uri("step", s)) for s in steps))

    def _on_activated(self, item_id: str) -> None:
        item = self.trace.item(item_id) if self.trace is not None else None
        if item is None:
            return
        kind, target = item.target
        deps = self._deps
        if kind == "step":
            self._details(target)
        elif kind == "test":
            step_id, test_id = target.split("\0", 1)
            self._details(step_id, ("test", test_id))
        elif kind == "passage" and deps.show_passages is not None:
            document, quote = target.split("\0", 1)
            deps.show_passages(self.project_id, document, [quote], quote)
        elif kind == "document" and deps.show_passages is not None:
            quotes = [
                other.target[1].split("\0", 1)[1]
                for other in (self.trace.column(SPEC) if self.trace else [])
                if other.target[0] == "passage" and other.target[1].startswith(f"{target}\0")
            ]
            deps.show_passages(self.project_id, target, quotes, "")
        elif kind == "docs" and deps.open_docs is not None:
            deps.open_docs(self.project_id, target)
        elif kind == "feature":
            # A feature is a step: its details dialog, landing on the Feature tab — the
            # same thing a test row does with the Tests tab.
            self._details(target, ("feature", target))

    def _details(self, step_id: StepId, *extra: tuple[str, str]) -> None:
        if not self._deps.library.has(step_id):
            return
        nodes = [ContextNode(selection_uri("step", step_id))]
        nodes += [ContextNode(selection_uri(kind, key)) for kind, key in extra]
        self._deps.actions.run("steps.details", Context({SCOPE_SELECTION: tuple(nodes)}))

    def _on_menu(self, item_id: str, screen: QPointF) -> None:
        step_id = self._step_of(item_id)
        if step_id is None or not self._deps.library.has(step_id):
            return
        self.scene.pick(item_id)
        menu = build_menu(self._deps.actions, self._deps.context, "Step", self.view)
        menu.exec(screen.toPoint())
