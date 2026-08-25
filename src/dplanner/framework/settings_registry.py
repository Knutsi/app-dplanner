"""Pluggable settings sections, presented as a tree in the Settings dialog.

Every registry in this framework has the same shape, and this one is no exception: modules
register a :class:`SettingsSection` at startup and the dialog renders whatever is there — so
a new section is one ``register`` call inside the module that owns the setting, and no
central list of preferences exists to fall out of date.

A section's ``factory`` takes only a parent widget and returns the editor. It closes over
whatever storage access it needs rather than receiving a shared "settings context", because
there is nothing generic to say about how a section persists its own values — and the two
scopes below already say the only thing that matters.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from PySide6.QtWidgets import QWidget


class SettingsScope(Enum):
    """Where a section's values live — the dialog's two top-level tree branches."""

    # Stored in the workspace, so it travels with the data: shared through git, seen by
    # everyone who opens it. Pipeline definitions, shared conventions, project settings.
    PROJECT = "project"
    # Per user, per machine: QSettings for values, the OS keychain for secrets. Model
    # names, window preferences, API keys. Never in the workspace, never in a commit.
    GLOBAL = "global"


@dataclass(frozen=True)
class SettingsSection:
    id: str  # "llm.openai" — module-prefixed, globally unique.
    category: tuple[str, ...]  # ("LLM Providers", "OpenAI") — tree path, leaf last.
    scope: SettingsScope
    factory: Callable[[QWidget | None], QWidget]
    order: int = 50


class SettingsSectionRegistry:
    def __init__(self) -> None:
        self._sections: dict[str, SettingsSection] = {}

    def register(self, section: SettingsSection) -> None:
        if section.id in self._sections:
            raise ValueError(f"settings section {section.id!r} already registered")
        self._sections[section.id] = section

    def sections(self) -> list[SettingsSection]:
        """All sections, in registration order (the tree groups/sorts them by scope)."""
        return list(self._sections.values())
