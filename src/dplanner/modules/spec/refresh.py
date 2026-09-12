"""Fetching a source and checking it for changes, off the GUI thread.

The ``github/refresh.py`` shape: a ``QObject`` with a ``TaskRunner``, work snapshotted on
the GUI thread into plain values, the kind's blocking call on the worker, the answer
back on a queued Qt signal, applied on the GUI thread after re-checking the world.

Two things differ from the PR refresher, on purpose. **A fetch lands on the undo stack**:
a person pressed Refresh (or added the source), so Ctrl+Z must put the documents back —
the Compile Docs precedent, not the background sync's. And **a check writes nothing**: it
compares versions and remembers the answer here, per window, so the Specs tab can say
"3 pages changed" and wait for the person. A source whose credential is refused is
remembered as *needs reconnect* until its kind says the configuration changed.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from PySide6.QtCore import QObject, QTimer
from PySide6.QtCore import Signal as QtSignal

from dplanner.core.signals import Signal
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.document_source import Freshness, Snapshot, SourceUnavailableError
from dplanner.domain.model import Library, NodeId
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.undo import UndoService
from dplanner.modules.spec.aspect import MODULE_ID
from dplanner.modules.spec.documents import SpecSource, read_index, write_index
from dplanner.modules.spec.source_kind import DocumentSourceKind, SourceStatus
from dplanner.modules.spec.sourced import (
    Applied,
    apply_snapshot,
    known_versions,
    source_of,
)

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 10 * 60 * 1000


class SourceRefresher(QObject):
    # Worker → GUI, queued because they are emitted off-thread.
    _fetched = QtSignal(str, str, object)  # (project id, source id, Snapshot)
    _refused = QtSignal(str, str, str, bool)  # (project id, source id, message, reconnect)
    _checked = QtSignal(str, str, object)  # (project id, source id, Freshness | None)

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        tasks: TaskService,
        files: Callable[[NodeId], ModuleFileArea],
        kinds: Mapping[str, DocumentSourceKind],
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self._product = library
        self._undo = undo
        self._files = files
        self._kinds = kinds
        self._fetcher = TaskRunner(tasks, parent=self)
        self._checker = TaskRunner(tasks, parent=self)
        # Per-window memory, never the plan: what the last check found and which sources'
        # credentials were refused.
        self._freshness: dict[str, Freshness] = {}
        self._reconnect: dict[str, str] = {}
        self._watched: set[NodeId] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._fetched.connect(self._apply)
        self._refused.connect(self._on_refused)
        self._checked.connect(self._on_checked)
        # The strip says "fetching…" while the runner is busy, so its end is a change too.
        self._fetcher.busy_changed.connect(lambda _busy: self.changed.emit())
        self.changed: Signal[()] = Signal("spec.sources.changed")
        self.applied: Signal[str, str, Applied] = Signal("spec.sources.applied")
        self.failed: Signal[str, str, str] = Signal("spec.sources.failed")
        for kind in kinds.values():
            kind.config_changed.connect(self._forget_refusals)

    # -- what a surface asks ---------------------------------------------------------------------

    def status(self, source: SpecSource) -> SourceStatus:
        """The kind's answer, overridden by a refusal this window has seen since."""
        kind = self._kinds.get(source.kind)
        if kind is None:
            return SourceStatus(False, f"no {source.kind} support in this build")
        refused = self._reconnect.get(source.id)
        if refused:
            return SourceStatus(False, refused)
        return kind.status(source.locator)

    def needs_reconnect(self, source_id: str) -> bool:
        return source_id in self._reconnect

    def freshness(self, source_id: str) -> Freshness | None:
        return self._freshness.get(source_id)

    def is_fetching(self) -> bool:
        return self._fetcher.is_busy()

    # -- fetching --------------------------------------------------------------------------------

    def refresh(self, project_id: NodeId, source_id: str) -> bool:
        """Fetch the source and land the result as one undo entry. False when a fetch is
        already out, or the source cannot be fetched now."""
        source = self._source(project_id, source_id)
        kind = self._kinds.get(source.kind) if source is not None else None
        if source is None or kind is None or not self.status(source).ready:
            return False
        known = known_versions(read_index(self._product.project(project_id)), source_id)
        locator = dict(source.locator)
        fetched, refused = self._fetched, self._refused
        runner = self._fetcher

        def body() -> None:  # Worker thread: plain values only, never the model.
            try:
                snapshot = kind.fetch(
                    locator, known, runner.report_progress, runner.cancel_requested
                )
            except SourceUnavailableError as error:
                refused.emit(project_id, source_id, str(error), error.needs_reconnect)
                return
            fetched.emit(project_id, source_id, snapshot)

        started = runner.run(
            f"Fetching {source.title} from {kind.name}",
            body,
            key="spec.source",
            cancellable=True,
            cancel_prompt="Stop fetching? Nothing fetched so far is kept.",
        )
        if started:
            self.changed.emit()
        return started

    def _apply(self, project_id: str, source_id: str, snapshot: object) -> None:
        if not isinstance(snapshot, Snapshot):
            return
        source = self._source(project_id, source_id)
        if source is None:
            return  # The source was removed while the worker was out.
        index = read_index(self._product.project(project_id))
        today = datetime.now(UTC).date().isoformat()
        index, applied = apply_snapshot(self._files(project_id), index, source_id, snapshot, today)
        kind = self._kinds[source.kind]
        # Two refreshes are two undo entries: the toolbar's buttons take no focus, so
        # nothing else would seal the top command between them.
        self._undo.break_coalescing()
        self._undo.push(
            SetModuleDataCommand(
                project_id, MODULE_ID, write_index(index), label=f"Refresh {kind.name}"
            )
        )
        self._freshness.pop(source_id, None)
        self.changed.emit()
        self.applied.emit(project_id, source_id, applied)

    def _on_refused(self, project_id: str, source_id: str, message: str, reconnect: bool) -> None:
        if reconnect:
            self._reconnect[source_id] = message
        logger.info("source %s: %s", source_id, message)
        self.changed.emit()
        self.failed.emit(project_id, source_id, message)

    # -- checking --------------------------------------------------------------------------------

    def watch(self, project_id: NodeId) -> None:
        """A Specs tab is showing this project: check its sources now and on the interval."""
        self._watched.add(project_id)
        if not self._timer.isActive():
            self._timer.start()
        self.check(project_id)

    def unwatch(self, project_id: NodeId) -> None:
        self._watched.discard(project_id)
        if not self._watched:
            self._timer.stop()

    def stop(self) -> None:
        self._watched.clear()
        self._timer.stop()

    def check(self, project_id: NodeId) -> None:
        """Ask every ready source of the project what changed — versions only, no bodies,
        nothing written. Skipped silently while another check or a fetch is out."""
        if not self._product.has(project_id) or self._checker.is_busy() or self._fetcher.is_busy():
            return
        index = read_index(self._product.project(project_id))
        targets = [
            (
                source.id,
                self._kinds[source.kind],
                dict(source.locator),
                known_versions(index, source.id),
            )
            for source in index.sources
            if source.kind in self._kinds and source.fetched and self.status(source).ready
        ]
        if not targets:
            return
        checked, refused = self._checked, self._refused

        def body() -> None:
            for source_id, kind, locator, known in targets:
                try:
                    checked.emit(project_id, source_id, kind.check(locator, known))
                except SourceUnavailableError as error:
                    if error.needs_reconnect:
                        refused.emit(project_id, source_id, str(error), True)
                    else:
                        logger.info("source %s check: %s", source_id, error)

        self._checker.run("Checking spec sources", body, key="spec.check")

    def _on_checked(self, _project_id: str, source_id: str, freshness: object) -> None:
        if isinstance(freshness, Freshness):
            self._freshness[source_id] = freshness
            self.changed.emit()

    def _tick(self) -> None:
        for project_id in list(self._watched):
            self.check(project_id)

    # -- internals -------------------------------------------------------------------------------

    def _forget_refusals(self) -> None:
        """A kind's configuration changed: every refusal is stale until the next attempt."""
        if self._reconnect:
            self._reconnect.clear()
            self.changed.emit()

    def _source(self, project_id: str, source_id: str) -> SpecSource | None:
        if not self._product.has(project_id):
            return None
        return source_of(read_index(self._product.project(project_id)), source_id)
