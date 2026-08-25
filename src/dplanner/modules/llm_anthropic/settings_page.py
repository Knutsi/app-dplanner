"""The "LLM Providers → Anthropic" settings page: API key (OS keychain) + model."""

from PySide6.QtWidgets import QFormLayout, QLineEdit, QWidget

from dplanner.framework.llm_service import LLMService
from dplanner.framework.secrets_store import get_secret, set_secret
from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.llm_anthropic.provider import DEFAULT_MODEL, MODULE_ID


def build_page(llm: LLMService, parent: QWidget | None) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("AnthropicSettingsPage")
    layout = QFormLayout(page)

    api_key_edit = QLineEdit(page)
    api_key_edit.setObjectName("AnthropicApiKeyEdit")
    api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    api_key_edit.setText(get_secret(MODULE_ID, "api_key") or "")
    api_key_edit.setPlaceholderText("sk-ant-…")

    def commit_api_key() -> None:
        set_secret(MODULE_ID, "api_key", api_key_edit.text())
        llm.config_changed.emit()

    api_key_edit.editingFinished.connect(commit_api_key)
    layout.addRow("API key", api_key_edit)

    model_edit = QLineEdit(page)
    model_edit.setObjectName("AnthropicModelEdit")
    model_edit.setText(get_global(MODULE_ID, "model", DEFAULT_MODEL))

    def commit_model() -> None:
        set_global(MODULE_ID, "model", model_edit.text())
        llm.config_changed.emit()

    model_edit.editingFinished.connect(commit_model)
    layout.addRow("Model", model_edit)

    return page
