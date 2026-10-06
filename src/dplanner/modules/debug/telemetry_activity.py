"""The Telemetry tab: what ran and how long it took, newest first, one span in full below.

The same shape as the LLM Calls tab beside it — a table polled from the journal on a
one-second timer while the tab is current, a detail pane for the selected row — and for
the same reason: spans arrive from worker threads and the watchdog's thread, and polling is
what keeps every widget touch on the GUI thread. Two switches narrow the table to what
took long or what went wrong; the detail pane shows a span's children (the slow listeners
an action fanned out to), its traceback, or a stall's stack samples.
"""

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.telemetry import SLOW_MS, Span, Telemetry
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import SCOPE_ACTIVITY, ContextNode, ContextService, activity_uri

TELEMETRY_KIND = "telemetry"
REFRESH_MS = 1000

_ID_ROLE = Qt.ItemDataRole.UserRole
_COL_TIME, _COL_KIND, _COL_NAME, _COL_DURATION, _COL_OUTCOME = range(5)


class TelemetryActivity(ActivityBase):
    def __init__(self, telemetry: Telemetry, context: ContextService) -> None:
        self._telemetry = telemetry
        self._context = context

        self.uri = activity_uri(TELEMETRY_KIND)
        self.title = "Telemetry"

        self.widget = QWidget()
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        switches = QHBoxLayout()
        switches.setSpacing(12)
        self.slow_only = QCheckBox(f"Slow only (≥ {SLOW_MS:.0f} ms)")
        self.failures_only = QCheckBox("Failures and stalls only")
        self.slow_only.toggled.connect(lambda _on: self.refresh())
        self.failures_only.toggled.connect(lambda _on: self.refresh())
        switches.addWidget(self.slow_only)
        switches.addWidget(self.failures_only)
        switches.addStretch(1)
        layout.addLayout(switches)

        self.tree = QTreeWidget()
        self.tree.setObjectName("TelemetryTable")
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Time", "Kind", "Name", "Duration", "Outcome"])
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        header = self.tree.header()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._refresh_detail)

        self.detail = QPlainTextEdit()
        self.detail.setObjectName("TelemetryDetail")
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText(
            "Select a span to see what it ran inside, what it fanned out to, and what went wrong"
        )

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 200])
        layout.addWidget(splitter, stretch=1)

        self.timer = QTimer(self.widget)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.refresh)
        self.refresh()
        self.timer.start()

    # -- activity contract -----------------------------------------------------------------

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))
        self.timer.start()

    def on_deactivated(self) -> None:
        self.timer.stop()

    # -- table -----------------------------------------------------------------------------

    def shown(self) -> list[Span]:
        """The rows, newest first, through the two switches."""
        spans = self._telemetry.recent()
        if self.slow_only.isChecked():
            spans = [span for span in spans if (span.duration_ms or 0.0) >= SLOW_MS]
        if self.failures_only.isChecked():
            spans = [span for span in spans if not span.ok or span.kind == "stall"]
        return list(reversed(spans))

    def refresh(self) -> None:
        selected = self._selected_id()
        self.tree.clear()
        for span in self.shown():
            item = QTreeWidgetItem(
                [
                    _time_text(span),
                    span.kind,
                    ("    " if span.parent is not None else "") + span.name,
                    _duration_text(span),
                    _outcome_text(span),
                ]
            )
            item.setTextAlignment(_COL_DURATION, Qt.AlignmentFlag.AlignRight)
            item.setData(0, _ID_ROLE, span.span_id)
            self.tree.addTopLevelItem(item)
            if span.span_id == selected:
                item.setSelected(True)
        for column in (_COL_TIME, _COL_KIND, _COL_DURATION, _COL_OUTCOME):
            self.tree.resizeColumnToContents(column)
        self._refresh_detail()

    def _selected_id(self) -> int | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        span_id: int | None = items[0].data(0, _ID_ROLE)
        return span_id

    # -- detail pane -----------------------------------------------------------------------

    def _refresh_detail(self) -> None:
        span_id = self._selected_id()
        spans = self._telemetry.recent()
        span = next((s for s in spans if s.span_id == span_id), None)
        text = render_detail(span, spans) if span is not None else ""
        # An unchanged setPlainText would still reset the reader's scroll position.
        if text != self.detail.toPlainText():
            self.detail.setPlainText(text)


def _time_text(span: Span) -> str:
    return datetime.fromtimestamp(span.started_at).strftime("%H:%M:%S.%f")[:-3]


def _duration_text(span: Span) -> str:
    if span.duration_ms is None:
        return "…"
    if span.duration_ms >= 1000.0:
        return f"{span.duration_ms / 1000.0:.2f} s"
    return f"{span.duration_ms:.1f} ms"


def _outcome_text(span: Span) -> str:
    if span.kind == "stall":
        return "stalled"
    if not span.ok:
        return "failed"
    exit_code = span.detail.get("exit_code")
    if exit_code not in (None, 0):
        return f"exit {exit_code}"
    return "ok"


def render_detail(span: Span, spans: list[Span]) -> str:
    """One span in full: its line, where it ran, what it carried, what ran inside it."""
    parts = [
        f"{span.kind} {span.name} — {_duration_text(span)} — {_outcome_text(span)}",
        f"started {_time_text(span)} · {span.thread} · {span.surface} {span.pid}"
        + (f" · inside #{span.parent}" if span.parent is not None else ""),
    ]
    detail = {key: value for key, value in span.detail.items() if key != "samples"}
    if detail:
        parts.append("")
        parts.extend(f"{key}: {value}" for key, value in detail.items())
    children = [s for s in spans if s.parent == span.span_id and s.pid == span.pid]
    if children:
        parts.append("")
        parts.append("--- ran inside it ---")
        parts.extend(f"{_duration_text(s):>10}  {s.kind} {s.name}" for s in children)
    if not span.ok:
        parts.append("")
        parts.append("--- error ---")
        if span.error_type or span.error_message:
            parts.append(f"{span.error_type or 'error'}: {span.error_message or ''}")
        if span.traceback:
            parts.append(span.traceback.rstrip())
    for number, sample in enumerate(span.detail.get("samples") or (), start=1):
        parts.append("")
        parts.append(f"--- stack sample {number} ---")
        parts.append(str(sample).rstrip())
    return "\n".join(parts)
