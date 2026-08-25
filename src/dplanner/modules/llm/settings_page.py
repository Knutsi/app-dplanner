"""The "LLM" settings page: pick the preferred provider from whatever is registered.

Read live from the registry/service every time the page is built — provider modules may
register after this page's factory is defined but always before a user can open it, so
there is no ordering dependency to get right (see the module's docstring)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

from dplanner.framework.llm import LLMProviderRegistry
from dplanner.framework.llm_service import LLMService

_NONE_LABEL = "— none —"


def build_page(registry: LLMProviderRegistry, llm: LLMService, parent: QWidget | None) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("LlmSettingsPage")
    layout = QFormLayout(page)

    combo = QComboBox(page)
    combo.setObjectName("LlmPreferredProviderCombo")
    combo.addItem(_NONE_LABEL, None)
    for provider in registry.providers():
        combo.addItem(provider.label, provider.id)

    preferred = llm.preferred_provider_id()
    index = combo.findData(preferred) if preferred is not None else 0
    combo.setCurrentIndex(index if index != -1 else 0)

    def on_changed(index: int) -> None:
        llm.set_preferred_provider_id(combo.itemData(index, Qt.ItemDataRole.UserRole))

    combo.currentIndexChanged.connect(on_changed)
    layout.addRow("Preferred provider", combo)

    return page
