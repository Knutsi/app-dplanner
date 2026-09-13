"""The Coverage tab: one project's trace, drawn — with a strip above it saying, per
document, how much of the spec is cited and how many passages want a look.

The tab owns nothing the trace does not: it asks ``trace_of`` on every coalesced change
of its project, hands the answer to the scene, and turns the scene's gestures into the
same verbs every other view runs — a click publishes the step, a double-click opens the
thing through the callbacks the composition root wired, a right-click renders the Step
menu. It never reaches another module.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QPainter, QResizeEvent
from PySide6.QtWidgets import (
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

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
from dplanner.modules.coverage.scene import CoverageScene
from dplanner.modules.coverage.trace import SPEC, Trace, flat

COVERAGE_KIND = "coverage"
STRIP_MARGIN = 8

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
    open_feature: Callable[[NodeId, str], None] | None = None
    # What a step is, for the Step ▸ open verbs' states — the aspects' Qt-free readers.
    feature_of: Callable[[StepId], str | None] = lambda _step: None
    is_milestone: Callable[[StepId], bool] = lambda _step: False
    tests_of: Callable[[StepId], list[str]] = lambda _step: []
    # (step) → [(document, quote)]: the passages a step reaches, its own feature's or the
    # gathering feature's — "a work step reaches the spec through the feature it flows into".
    passages_of: Callable[[StepId], list[tuple[str, str]]] = lambda _step: []


class CoverageView(QGraphicsView):
    """The viewport: the lanes laid to its width, and a horizontal scroll bar only when
    four lanes at their narrowest still do not fit — a finite extent, so the bar is honest."""

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
        self.strip = QWidget(page)
        self.strip.setObjectName("EditorToolbar")
        row = QHBoxLayout(self.strip)
        row.setContentsMargins(STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN)
        row.setSpacing(12)
        self.summary = QLabel(self.strip)
        self.summary.setObjectName("InspectorNote")
        row.addWidget(self.summary)
        row.addStretch(1)
        self.review = QToolButton(self.strip)
        self.review.setObjectName("ToolbarButton")
        self.review.setText("Review")
        self.review.setToolTip("Light every passage that no longer simply anchors")
        self.review.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.review.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.review.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.review.clicked.connect(self._review)
        row.addWidget(self.review)
        self.updating = UpdatingIndicator(self.strip)
        row.addWidget(self.updating)
        layout.addWidget(self.strip)

        self.scene = CoverageScene()
        self.scene.picked.connect(self._on_picked)
        self.scene.activated.connect(self._on_activated)
        self.scene.menu_requested.connect(self._on_menu)
        self.view = CoverageView(self.scene, page)
        layout.addWidget(self.view, 1)
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
        self.summary.setText("   ".join(said) or "No spec documents — import one to trace it")
        self.review.setEnabled(any(doc.review for doc in self.trace.documents))

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
        return None

    def _on_picked(self, item_id: str) -> None:
        step_id = self._step_of(item_id) if item_id else None
        nodes: tuple[ContextNode, ...] = ()
        if step_id is not None and self._deps.library.has(step_id):
            nodes = (ContextNode(selection_uri("step", step_id)),)
        self.publish_selection(nodes)

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
        elif kind == "feature" and deps.open_feature is not None:
            deps.open_feature(self.project_id, target)

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
