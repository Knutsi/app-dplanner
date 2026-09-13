"""A folder on this computer as a document source kind.

It registers nothing — the spec module mints the + menu's entry from the kinds handed to
it — so this is not a module in the composition root's list: it is constructed beside the
others and handed over. There is no credential and nothing to configure, which is why
there is no settings page and why ``connect`` has nothing to do.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QFileDialog, QWidget

from dplanner.core.signals import Signal
from dplanner.domain.document_source import (
    Freshness,
    Locator,
    Snapshot,
    SourceStatus,
    SourceUnavailableError,
)
from dplanner.modules.spec_folder.source import (
    KIND,
    check,
    fetch,
    open_url,
    title_for,
    valid_locator,
)
from dplanner.theme.icons import folder_icon

REFUSAL = "this source's address is not a folder on this computer"


class SpecFolderKind:
    """Satisfies :class:`dplanner.modules.spec.source_kind.DocumentSourceKind`."""

    id = KIND
    name = "Folder"
    label = "&Folder on This Computer…"

    def __init__(self) -> None:
        # It takes no Deps: there is no service it needs and no capability it borrows —
        # every dialog it opens is parented by the caller. Nothing here is configured, so
        # nothing ever changes it; the signal exists because every kind's hosts subscribe.
        self.config_changed: Signal[()] = Signal("spec_folder.config_changed")

    @staticmethod
    def icon(color: str | QColor) -> QIcon:
        return folder_icon(color if isinstance(color, str) else color.name())

    def locate(self, parent: QWidget) -> tuple[str, Locator] | None:
        chosen = QFileDialog.getExistingDirectory(parent, "Add Folder Source")
        if not chosen:
            return None
        path = Path(chosen)
        return title_for(path), {"path": str(path)}

    def status(self, locator: Locator) -> SourceStatus:
        """Whether it can be fetched at all — never whether the folder is there.

        This runs from an action's state on every context change; the disk is asked when a
        fetch asks it, and a folder that has gone says so in the fetch's own words.
        """
        return SourceStatus(True) if valid_locator(locator) else SourceStatus(False, REFUSAL)

    def connect(self, parent: QWidget, locator: Locator) -> bool:
        return False  # No credential: there is nothing a Connect dialog could obtain.

    def open_url(self, locator: Locator) -> str:
        valid = valid_locator(locator)
        return open_url(valid) if valid else ""

    def fetch(
        self,
        locator: Locator,
        known: Mapping[str, str],
        progress: Callable[[float], None],
        cancelled: Callable[[], bool],
    ) -> Snapshot:
        return fetch(self._demand(locator), known, progress, cancelled)

    def check(self, locator: Locator, known: Mapping[str, str]) -> Freshness:
        return check(self._demand(locator), known)

    def _demand(self, locator: Locator) -> Locator:
        valid = valid_locator(locator)
        if valid is None:
            raise SourceUnavailableError(REFUSAL)
        return valid
