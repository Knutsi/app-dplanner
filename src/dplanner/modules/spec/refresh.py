"""Fetching a source and checking it for changes, off the GUI thread.

The ``github/refresh.py`` shape: a ``QObject`` with a ``TaskRunner``, work snapshotted on
the GUI thread into plain values, the kind's blocking call on the worker, the answer
back on a queued Qt signal, applied on the GUI thread after re-checking the world.

Two things differ from the PR refresher, on purpose. **A fetch lands on the undo stack**:
a person pressed Refresh (or added the source), so Ctrl+Z must put the documents back, where
a background sync of an external fact applies its command directly. And **a check writes
nothing**: it
compares versions and remembers the answer here, per window, so the Specs tab can say
"3 documents changed" and wait for the person. A source whose credential is refused is
remembered as *needs reconnect* until its kind says the configuration changed.

**One gesture, one undo entry — and the one-source case is not a special case.**
:meth:`SourceRefresher.refresh` is :meth:`refresh_all` over a list of one: the worker
collects a snapshot per ready source and the GUI thread lands them all inside a single
``UndoService.gesture``. A gesture holding exactly one push places that push itself, with
its own label, so refreshing one source writes what it always wrote and no branch on the
count appears anywhere. A source that refused never stops the others; it is reported after
the gesture closes.

**Per-window memory is keyed by project *and* source.** Source ids (``src1``, ``src2``)
are minted per project, so two open projects both have a ``src1``: a dict keyed on the id
alone would have one project's freshness answering for another's.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
    LOCATION_KEY,
    Applied,
    apply_snapshot,
    known_versions,
    location_of,
    resolve_locator,
    source_of,
)

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 10 * 60 * 1000

REFRESH_ALL_LABEL = "Refresh Spec Sources"


@dataclass(frozen=True)
class _Target:
    """One source's work, snapshotted on the GUI thread into plain values a worker may
    carry: never the model, never a node, never a widget."""

    source_id: str
    title: str
    kind: DocumentSourceKind
    locator: dict[str, str]
    known: dict[str, str]


@dataclass(frozen=True)
class _Result:
    """What the worker found for one source: a snapshot, or why not."""

    source_id: str
    snapshot: Snapshot | None = None
    message: str = ""
    reconnect: bool = False


class SourceRefresher(QObject):
    # Worker → GUI, queued because they are emitted off-thread. A fetch answers once with
    # every source's result: the landing has to be one synchronous turn to be one gesture.
    _fetched = QtSignal(str, object)  # (project id, tuple[_Result, ...])
    _checked = QtSignal(str, str, object)  # (project id, source id, Freshness | None)
    _refused = QtSignal(str, str, str, bool)  # (project id, source id, message, reconnect)

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
        # Keyed by (project, source): a source id is minted per project, so two open
        # projects both have a "src1".
        self._freshness: dict[tuple[str, str], Freshness] = {}
        self._reconnect: dict[tuple[str, str], str] = {}
        self._watched: set[NodeId] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._fetched.connect(self._land)
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

    def status(self, project_id: NodeId, source: SpecSource) -> SourceStatus:
        """The kind's answer, overridden by a refusal this window has seen since."""
        kind = self._kinds.get(source.kind)
        if kind is None:
            return SourceStatus(False, f"no {source.kind} support in this build")
        refused = self._reconnect.get((project_id, source.id))
        if refused:
            # A refusal the credential caused is exactly what reconnecting fixes.
            return SourceStatus(False, refused, connectable=True)
        if not self._product.has(project_id):
            return SourceStatus(False, "the project is gone")
        project = self._product.project(project_id)
        named = source.locator.get(LOCATION_KEY)
        if named and location_of(project, source) is None:
            return SourceStatus(
                False, f"its location {named} is gone from the project — Project ▸ Settings…"
            )
        return kind.status(resolve_locator(project, source))

    def needs_reconnect(self, project_id: NodeId, source_id: str) -> bool:
        return (project_id, source_id) in self._reconnect

    def freshness(self, project_id: NodeId, source_id: str) -> Freshness | None:
        return self._freshness.get((project_id, source_id))

    def stale(self, project_id: NodeId) -> list[Freshness]:
        """What the last check found for this project's sources that have updates — what a
        surface counts. Per window, never the plan."""
        return [
            found
            for (project, _source), found in self._freshness.items()
            if project == project_id and found.stale
        ]

    def is_fetching(self) -> bool:
        return self._fetcher.is_busy()

    def can_refresh(self, project_id: NodeId) -> bool:
        """Whether any of the project's sources could be fetched right now."""
        return bool(self._targets(project_id, self._sources(project_id)))

    # -- fetching --------------------------------------------------------------------------------

    def refresh(self, project_id: NodeId, source_id: str) -> bool:
        """Fetch one source. False when a fetch is already out, or it cannot be fetched."""
        source = self._source(project_id, source_id)
        return self._fetch(project_id, [source] if source is not None else [])

    def refresh_all(self, project_id: NodeId) -> bool:
        """Fetch every ready source of the project — one gesture, so one undo entry."""
        return self._fetch(project_id, self._sources(project_id))

    def _fetch(self, project_id: NodeId, sources: Sequence[SpecSource]) -> bool:
        targets = self._targets(project_id, sources)
        if not targets:
            return False
        fetched = self._fetched
        runner = self._fetcher
        total = len(targets)

        def body() -> None:  # Worker thread: plain values only, never the model.
            results: list[_Result] = []
            for position, target in enumerate(targets):
                if runner.cancel_requested():
                    break

                def report(fraction: float, done: int = position) -> None:
                    # Bound at definition, or every source reports the last one's offset;
                    # and a fraction of the whole run, or the bar resets at each source.
                    runner.report_progress((done + fraction) / total)

                try:
                    results.append(
                        _Result(
                            target.source_id,
                            target.kind.fetch(
                                target.locator, target.known, report, runner.cancel_requested
                            ),
                        )
                    )
                except SourceUnavailableError as error:
                    if runner.cancel_requested():
                        break  # The person stopped it; that is not the source refusing.
                    results.append(
                        _Result(
                            target.source_id,
                            message=str(error),
                            reconnect=error.needs_reconnect,
                        )
                    )
            fetched.emit(project_id, tuple(results))

        started = runner.run(
            self._fetch_name(targets),
            body,
            key="spec.source",
            cancellable=True,
            cancel_prompt="Stop fetching? Nothing fetched so far is kept.",
        )
        if started:
            self.changed.emit()
        return started

    def _land(self, project_id: str, results: object) -> None:
        """Every snapshot the worker brought back, as one undo entry.

        The index is re-read inside the loop because each push has already applied: the
        next source must build on what the last one wrote.
        """
        if not isinstance(results, tuple):
            return
        rows = [row for row in results if isinstance(row, _Result)]
        today = datetime.now(UTC).date().isoformat()
        landed: list[tuple[str, Applied]] = []
        # Two refreshes are two undo entries: the toolbar's buttons take no focus, so
        # nothing else would seal the top command between them.
        self._undo.break_coalescing()
        with self._undo.gesture(REFRESH_ALL_LABEL):
            for row in rows:
                source = self._source(project_id, row.source_id)
                if row.snapshot is None or source is None:
                    continue  # Refused, or removed while the worker was out.
                index = read_index(self._product.project(project_id))
                index, applied = apply_snapshot(
                    self._files(project_id), index, row.source_id, row.snapshot, today
                )
                kind = self._kinds[source.kind]
                self._undo.push(
                    SetModuleDataCommand(
                        project_id, MODULE_ID, write_index(index), label=f"Refresh {kind.name}"
                    )
                )
                self._freshness.pop((project_id, row.source_id), None)
                landed.append((row.source_id, applied))
        self.changed.emit()
        for source_id, applied in landed:
            self.applied.emit(project_id, source_id, applied)
        for row in rows:
            if row.snapshot is None:
                self._on_refused(project_id, row.source_id, row.message, row.reconnect)

    def _on_refused(self, project_id: str, source_id: str, message: str, reconnect: bool) -> None:
        if reconnect:
            self._reconnect[project_id, source_id] = message
        logger.info("source %s: %s", source_id, message)
        self.changed.emit()
        self.failed.emit(project_id, source_id, message)

    # -- checking --------------------------------------------------------------------------------

    def watch(self, project_id: NodeId) -> None:
        """A Specs tab is showing this project: check its sources now and on the interval."""
        self._watched.add(project_id)
        if not self._timer.isActive():
            self._timer.start()
        self.check_all(project_id)

    def unwatch(self, project_id: NodeId) -> None:
        self._watched.discard(project_id)
        if not self._watched:
            self._timer.stop()

    def stop(self) -> None:
        self._watched.clear()
        self._timer.stop()

    def check_all(self, project_id: NodeId) -> None:
        """Ask every fetched source of the project what changed — versions only, no bodies,
        nothing written. Skipped silently while another check or a fetch is out."""
        if self._checker.is_busy() or self._fetcher.is_busy():
            return
        targets = self._targets(project_id, self._sources(project_id), fetched_only=True)
        if not targets:
            return
        checked, refused = self._checked, self._refused

        def body() -> None:
            for target in targets:
                try:
                    checked.emit(
                        project_id,
                        target.source_id,
                        target.kind.check(target.locator, target.known),
                    )
                except SourceUnavailableError as error:
                    if error.needs_reconnect:
                        refused.emit(project_id, target.source_id, str(error), True)
                    else:
                        logger.info("source %s check: %s", target.source_id, error)

        self._checker.run("Checking spec sources", body, key="spec.check")

    def _on_checked(self, project_id: str, source_id: str, freshness: object) -> None:
        if isinstance(freshness, Freshness):
            self._freshness[project_id, source_id] = freshness
            self.changed.emit()

    def _tick(self) -> None:
        for project_id in list(self._watched):
            self.check_all(project_id)

    # -- internals -------------------------------------------------------------------------------

    def _forget_refusals(self) -> None:
        """A kind's configuration changed: every refusal is stale until the next attempt."""
        if self._reconnect:
            self._reconnect.clear()
            self.changed.emit()

    def _sources(self, project_id: NodeId) -> list[SpecSource]:
        if not self._product.has(project_id):
            return []
        return list(read_index(self._product.project(project_id)).sources)

    def _source(self, project_id: str, source_id: str) -> SpecSource | None:
        if not self._product.has(project_id):
            return None
        return source_of(read_index(self._product.project(project_id)), source_id)

    def _targets(
        self,
        project_id: NodeId,
        sources: Sequence[SpecSource],
        *,
        fetched_only: bool = False,
    ) -> list[_Target]:
        """The work, read off the model on the GUI thread — the one place both a fetch and
        a check decide what they are about to do."""
        if not self._product.has(project_id):
            return []
        project = self._product.project(project_id)
        index = read_index(project)
        return [
            _Target(
                source_id=source.id,
                title=source.title,
                kind=self._kinds[source.kind],
                locator=dict(resolve_locator(project, source)),
                known=known_versions(index, source.id),
            )
            for source in sources
            if source.kind in self._kinds
            and (source.fetched or not fetched_only)
            and self.status(project_id, source).ready
        ]

    def _fetch_name(self, targets: Sequence[_Target]) -> str:
        """What the task centre calls it: the source, or how many of them."""
        if len(targets) == 1:
            return f"Fetching {targets[0].title} from {targets[0].kind.name}"
        return f"Fetching {len(targets)} spec sources"
