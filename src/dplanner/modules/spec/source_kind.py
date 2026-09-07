"""What a *document source kind* is to the spec module: the contract a module such as
``spec_confluence`` satisfies, structurally, without either importing the other.

The spec module runs a kind. It owns the source records, the nested list, the write, the
task, the undo entry and the freshness note; the kind knows only how to ask a person for
a location, whether it is connected, how to connect, and how to fetch and check. So a
second kind — a wiki, a shared drive — is a fetcher and a dialog, nothing else. The
composition root hands the kinds in as ``SpecDeps.kinds``; the Qt-free shapes they
exchange are :mod:`dplanner.domain.document_source`'s. Consumer-owned, like
``project_editor/drops.py``'s ``CanvasDrop``, and promoted to ``framework/`` only when a
second consumer appears.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QWidget

from dplanner.core.signals import Signal
from dplanner.domain.document_source import Freshness, Locator, Snapshot

# What a fetch reports as it goes: a fraction — TaskRunner.report_progress's shape.
type Progress = Callable[[float], None]


@dataclass(frozen=True)
class SourceStatus:
    """Whether a source can be fetched right now, and if not, why — the words beside the
    Connect button and the greyed verb's reason."""

    ready: bool
    message: str = ""


class DocumentSourceKind(Protocol):
    id: str  # "confluence" — also the index's ``kind`` on a source record.
    name: str  # "Confluence" — how prose names it: "from Confluence", "Refresh Confluence".
    label: str  # "Confluence Page or Folder…" — the + menu's entry.
    icon: Callable[[str | QColor], QIcon]  # One painter for the menu (QColor) and a row (str).
    config_changed: Signal[()]  # After connect or forget: hosts re-ask status.

    def locate(self, parent: QWidget) -> tuple[str, Locator] | None:
        """Ask the person where the source is: (title, locator), or None. No network."""
        ...

    def status(self, locator: Locator) -> SourceStatus:
        """GUI thread, from an action's state on every context change — so it reads a
        preference, never the keychain."""
        ...

    def connect(self, parent: QWidget, locator: Locator) -> bool:
        """The guided dialog; True when a credential is now stored."""
        ...

    def open_url(self, locator: Locator) -> str: ...

    def fetch(
        self,
        locator: Locator,
        known: Mapping[str, str],
        progress: Progress,
        cancelled: Callable[[], bool],
    ) -> Snapshot:
        """Blocking, on a worker thread. ``known`` is key → version as the index holds it."""
        ...

    def check(self, locator: Locator, known: Mapping[str, str]) -> Freshness:
        """Blocking, on a worker thread, no bodies."""
        ...
