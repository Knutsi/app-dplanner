"""Pluggable settings sections, presented as a tree in the Settings dialog.

Every registry in this framework has the same shape, and this one is no exception: modules
register a :class:`SettingsSection` at startup and the dialog renders whatever is there — so
a new section is one ``register`` call inside the module that owns the setting, and no
central list of preferences exists to fall out of date.

A section's ``factory`` takes only a parent widget and returns the editor. It closes over
whatever storage access it needs rather than receiving a shared "settings context", because
there is nothing generic to say about how a section persists its own values. Everything
registered so far is per user, per machine: QSettings for values, the OS keychain for
secrets — never in the workspace, never in a commit.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QVBoxLayout, QWidget

from dplanner.theme.tokens import SECTION_GAP


@dataclass(frozen=True)
class SettingsSection:
    """One page of the Settings dialog.

    ``factory`` returns a page that owns **no outer margin**: the frame owns the dialog's
    margins and the dialog gives the page its inset from the seam and scrolls it when it
    is taller than the window. Build it with :func:`settings_page` and stack its blocks
    with ``framework.widgets.block`` — a caption over each field, never a label beside
    it — so nine pages spell one shape.
    """

    id: str  # "llm.openai" — module-prefixed, globally unique.
    category: tuple[str, ...]  # ("LLM Providers", "OpenAI") — tree path, leaf last.
    factory: Callable[[QWidget | None], QWidget]


def settings_page(parent: QWidget | None) -> tuple[QWidget, QVBoxLayout]:
    """A page with no outer margin and ``SECTION_GAP`` between its blocks."""
    page = QWidget(parent)
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SECTION_GAP)
    return page, layout


class SettingsSectionRegistry:
    def __init__(self) -> None:
        self._sections: dict[str, SettingsSection] = {}

    def register(self, section: SettingsSection) -> None:
        if section.id in self._sections:
            raise ValueError(f"settings section {section.id!r} already registered")
        self._sections[section.id] = section

    def sections(self) -> list[SettingsSection]:
        """All sections, in registration order."""
        return list(self._sections.values())
