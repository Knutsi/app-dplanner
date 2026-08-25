"""The LLM Calls tab: the last 100 requests as rows, the selected one in full below.

The tab polls ``LLMService.recent_calls()`` on a one-second timer instead of observing a
signal — ``complete()`` runs on worker threads and the core ``Signal`` delivers
synchronously on the emitting thread, so polling is what keeps all widget work on the GUI
thread. The timer runs only while the tab is the current activity; a running call shows
its elapsed time counting up, which is what makes a hung request visible.
"""

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHeaderView,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import SCOPE_ACTIVITY, ContextNode, ContextService, activity_uri
from dplanner.framework.llm_service import LLMCallRecord, LLMService

LLM_CALLS_KIND = "llm_calls"

REFRESH_MS = 1000

_ID_ROLE = Qt.ItemDataRole.UserRole

_COL_TIME, _COL_PROVIDER, _COL_MODEL, _COL_STATUS, _COL_DURATION, _COL_TOKENS = range(6)


class LLMCallsActivity(ActivityBase):
    def __init__(self, llm: LLMService, context: ContextService) -> None:
        self._llm = llm
        self._context = context

        self.uri = activity_uri(LLM_CALLS_KIND)
        self.title = "LLM Calls"

        self.widget = QWidget()
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.tree = QTreeWidget()
        self.tree.setObjectName("LLMCallsTable")
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["Time", "Provider", "Model", "Status", "Duration", "Tokens"])
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_COL_MODEL, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._refresh_detail)

        self.detail = QPlainTextEdit()
        self.detail.setObjectName("LLMCallDetail")
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a call to see its request, response and errors")

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

    def refresh(self) -> None:
        records = self._llm.recent_calls()
        selected = self._selected_call_id()
        self.tree.clear()
        for record in reversed(records):  # Newest first.
            item = QTreeWidgetItem(
                [
                    datetime.fromtimestamp(record.started_at).strftime("%H:%M:%S"),
                    record.provider_id,
                    record.model,
                    _status_text(record),
                    _duration_text(record),
                    _tokens_text(record),
                ]
            )
            item.setData(0, _ID_ROLE, record.call_id)
            self.tree.addTopLevelItem(item)
            if record.call_id == selected:
                item.setSelected(True)
        for column in (_COL_TIME, _COL_PROVIDER, _COL_STATUS, _COL_DURATION, _COL_TOKENS):
            self.tree.resizeColumnToContents(column)
        self._refresh_detail()

    def _selected_call_id(self) -> int | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        call_id: int | None = items[0].data(0, _ID_ROLE)
        return call_id

    # -- detail pane -----------------------------------------------------------------------

    def _refresh_detail(self) -> None:
        call_id = self._selected_call_id()
        record = next((r for r in self._llm.recent_calls() if r.call_id == call_id), None)
        text = _render_detail(record) if record is not None else ""
        # An unchanged setPlainText would still reset the reader's scroll position.
        if text != self.detail.toPlainText():
            self.detail.setPlainText(text)


def _status_text(record: LLMCallRecord) -> str:
    return "running…" if record.status == "running" else record.status


def _duration_text(record: LLMCallRecord) -> str:
    if record.duration_s is not None:
        return f"{record.duration_s:.1f}s"
    return f"{time.time() - record.started_at:.0f}s…"  # Still running: elapsed, counting up.


def _tokens_text(record: LLMCallRecord) -> str:
    if record.tokens_in is None or record.tokens_out is None:
        return "—"
    return f"{record.tokens_in}/{record.tokens_out}"


def _render_detail(record: LLMCallRecord) -> str:
    parts = []
    for message in record.request:
        parts.append(f"--- {message.role} ---\n{message.content}")
    if record.status == "ok":
        parts.append(f"--- response ---\n{record.response_text}")
    elif record.status in ("error", "timeout"):
        code = f" (HTTP {record.http_status})" if record.http_status is not None else ""
        parts.append(f"--- {record.status} ---\n{record.error_type}{code}\n{record.error_message}")
    else:
        parts.append("--- running ---")
    return "\n\n".join(parts)
