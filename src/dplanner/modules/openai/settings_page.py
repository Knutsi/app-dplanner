"""The "LLM Providers → OpenAI" settings page: API key (kept in the OS keychain), model
picked from the account's live model list, and reasoning effort.

The model combo stays editable — typing a name still works offline — and "Refresh"
fetches the account's chat models on a worker thread (same marshal discipline as
``TaskRunner``: the blocking call runs on a daemon thread, the result comes back through
a queued Qt signal). The fetched list is cached in global settings so the choices survive
a restart without refetching.
"""

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget

from dplanner.core.secrets import get_secret, set_secret
from dplanner.framework.llm_service import LLMService
from dplanner.framework.settings_registry import settings_page
from dplanner.framework.signalling import Spinner, StatusLine
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import GlyphButton, block, captioned
from dplanner.modules.openai.provider import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    MODULE_ID,
    current_reasoning_effort,
    list_chat_models,
)
from dplanner.theme.icons import refresh_icon
from dplanner.theme.tokens import FIELD_GAP

KEY_HINT = "Kept in this computer's keychain, never in the plan and never in a file."
MODEL_HINT = "Type a model's name, or pick one — Refresh lists the chat models this account has."
EFFORT_HINT = "How long reasoning models may think; ignored by models without reasoning."

# (label, stored value); "" means the request parameter is never sent.
REASONING_EFFORT_CHOICES = (
    ("High", "high"),
    ("Medium", "medium"),
    ("Low", "low"),
    ("Minimal", "minimal"),
    ("Off", ""),
)


class _ModelLoader(QObject):
    """Runs one ``list_chat_models`` fetch on a daemon thread; ``done`` is delivered on
    the GUI thread (queued — connected to a bound method of this GUI-owned object)."""

    _finished = Signal(object, str)  # (models: list[str] | None, error: str)

    def __init__(self, on_done: Callable[[list[str] | None, str], None], parent: QObject) -> None:
        super().__init__(parent)
        self._on_done = on_done
        self._finished.connect(self._deliver)

    def start(self) -> None:
        def work() -> None:
            try:
                models = list_chat_models()
            except Exception as error:  # Network fetch; report, never crash the dialog.
                self._finished.emit(None, str(error) or type(error).__name__)
            else:
                self._finished.emit(models, "")

        threading.Thread(target=work, daemon=True).start()

    def _deliver(self, models: object, error: str) -> None:
        self._on_done(models if isinstance(models, list) else None, error)


def cached_models() -> list[str]:
    value = get_global(MODULE_ID, "models_cache", [])
    return [str(item) for item in value] if isinstance(value, list) else []


def build_page(llm: LLMService, parent: QWidget | None) -> QWidget:
    page, layout = settings_page(parent)
    page.setObjectName("OpenAISettingsPage")

    api_key_edit = QLineEdit(page)
    api_key_edit.setObjectName("OpenAIApiKeyEdit")
    api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    api_key_edit.setText(get_secret(MODULE_ID, "api_key") or "")
    api_key_edit.setPlaceholderText("sk-…")

    def commit_api_key() -> None:
        set_secret(MODULE_ID, "api_key", api_key_edit.text())
        llm.config_changed.emit()

    api_key_edit.editingFinished.connect(commit_api_key)
    block(layout, captioned("API key", page, KEY_HINT), api_key_edit)

    model_combo = QComboBox(page)
    model_combo.setObjectName("OpenAIModelCombo")
    model_combo.setEditable(True)

    def populate(models: list[str]) -> None:
        current = model_combo.currentText() or str(get_global(MODULE_ID, "model", DEFAULT_MODEL))
        model_combo.blockSignals(True)  # Repopulating must not commit a transient value.
        model_combo.clear()
        model_combo.addItems(models)
        model_combo.setCurrentText(current)
        model_combo.blockSignals(False)

    populate(sorted(set(cached_models()) | {DEFAULT_MODEL}))
    model_combo.setCurrentText(str(get_global(MODULE_ID, "model", DEFAULT_MODEL)))

    def commit_model() -> None:
        model = model_combo.currentText().strip()
        if model:
            set_global(MODULE_ID, "model", model)
            llm.config_changed.emit()

    line_edit = model_combo.lineEdit()
    assert line_edit is not None  # Editable combo always has one.
    line_edit.editingFinished.connect(commit_model)
    model_combo.activated.connect(lambda _index: commit_model())

    # The button whose verb fetches carries a glyph, and the arc turns in it while the
    # fetch runs; where the fetch stands is a status line under the row (DESIGN.md's
    # *Signalling*), never a label rewritten by hand.
    refresh_button = GlyphButton(
        "Refresh", refresh_icon, page, tip="Fetch the account's chat models from OpenAI"
    )
    spinner = Spinner(page).attach(refresh_button)
    fetch_status = StatusLine(page)

    def on_models(models: list[str] | None, error: str) -> None:
        refresh_button.setEnabled(True)
        spinner.stop()
        if models is None:
            fetch_status.say(f"Could not fetch models: {error}", "error")
            return
        set_global(MODULE_ID, "models_cache", models)
        populate(models)
        fetch_status.say(f"{len(models)} models", "ok")

    loader = _ModelLoader(on_models, page)

    def refresh() -> None:
        refresh_button.setEnabled(False)
        spinner.start()
        fetch_status.say("Fetching the account's models…", "busy")
        loader.start()

    refresh_button.clicked.connect(refresh)

    model_row = QWidget(page)
    row = QHBoxLayout(model_row)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(FIELD_GAP)
    row.addWidget(model_combo, 1)
    row.addWidget(refresh_button)
    block(layout, captioned("Model", page, MODEL_HINT), model_row, fetch_status)

    effort_combo = QComboBox(page)
    effort_combo.setObjectName("OpenAIReasoningEffortCombo")
    for label, value in REASONING_EFFORT_CHOICES:
        effort_combo.addItem(label, value)
    index = effort_combo.findData(current_reasoning_effort())
    effort_combo.setCurrentIndex(
        index if index != -1 else effort_combo.findData(DEFAULT_REASONING_EFFORT)
    )

    def commit_effort(index: int) -> None:
        set_global(MODULE_ID, "reasoning_effort", effort_combo.itemData(index))
        llm.config_changed.emit()

    effort_combo.currentIndexChanged.connect(commit_effort)
    block(layout, captioned("Reasoning", page, EFFORT_HINT), effort_combo)
    layout.addStretch(1)
    return page
