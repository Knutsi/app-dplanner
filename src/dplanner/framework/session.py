"""The session: which library is open, and how the build is replaced.

:class:`AppBuilder` owns one build. The session owns the *sequence* of builds. Reloading
the library does not reconfigure the running application — it constructs an entirely new
window, services and module instances, shows it, then closes and discards the old one.

That sounds heavy and is in fact the cheap option. Every registry refuses a duplicate id,
so a reload *cannot* be implemented as a re-registration; and the alternative — teaching
every registry, service and module to forget everything and start over — is teardown logic
exercised on exactly one code path, which is where bugs live. A rebuild is correct by
construction, and the only thing it costs is a fraction of a second nobody notices.

Opening a *different* library is not even a reload: it is a new process (File ▸ Open
Project Library spawns one), because two libraries are two applications' worth of state
and the registries above make sharing a process the expensive answer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from dplanner.core.formats import UnsupportedFormatError
from dplanner.core.repository import RepositoryFactory
from dplanner.core.storage.provider import StorageError
from dplanner.framework.action_registry import MenuStructure
from dplanner.framework.builder import AppBuilder, ModuleFactory, SeedFactory
from dplanner.identity import APP_NAME

if TYPE_CHECKING:
    from dplanner.framework.main_window import AppWindow
    from dplanner.framework.services import AppServices

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenFailure:
    """Why a library did not open, in the user's terms: what happened (``text``), what to
    do about it (``informative``) and the technical line behind it (``detail``)."""

    text: str
    title: str = "Open Project Library"
    informative: str = ""
    detail: str = ""


def describe_open_error(error: Exception, path: Path) -> OpenFailure:
    """Turn an exception into something worth reading."""
    if isinstance(error, UnsupportedFormatError):
        return OpenFailure(
            title=f"{APP_NAME} cannot read this library",
            text=f"{path} could not be read.",
            informative="It may be damaged, or not a project library at all.",
            detail=str(error),
        )
    return OpenFailure(text=f"Could not open {path}.", detail=str(error))


def _failure_box(failure: OpenFailure, parent: QWidget | None) -> QMessageBox:
    box = QMessageBox(parent) if parent is not None else QMessageBox()
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(failure.title)
    box.setText(failure.text)
    box.setInformativeText(failure.informative)
    box.setDetailedText(failure.detail)
    return box


def show_startup_failure(failure: OpenFailure) -> None:
    """Before any window exists the dialog is parentless and modal, so the startup flow
    can wait for the user to read it."""
    _failure_box(failure, None).exec()


class SessionControl(Protocol):
    """What modules may do to the session: ask for the current library to be rebuilt.

    The narrow face of :class:`AppSession`. Modules depend on this and never on the session
    itself, so the builder can hand them a real capability instead of a back-reference that
    might be None.
    """

    def reload(self) -> bool: ...


class AppSession:
    """Owns the current (window, services) pair and replaces it on open and reload."""

    def __init__(
        self,
        module_factory: ModuleFactory,
        repository: RepositoryFactory[Any],
        menus: MenuStructure,
        seed: SeedFactory | None = None,
    ) -> None:
        self._module_factory = module_factory
        self._repository = repository
        self._menus = menus
        self._seed = seed
        self.window: AppWindow | None = None
        self.services: AppServices | None = None
        self.library_path: Path | None = None

    # -- opening -------------------------------------------------------------------------------

    def open_initial(
        self, library_path: Path, progress: Callable[[str], None] | None = None
    ) -> bool:
        """The first open at startup.

        ``progress`` receives a short label at each stage boundary (the startup splash);
        reloading skips it — a window is already up to look at by then.
        """
        return self._open(library_path, progress)

    def reload(self) -> bool:
        """Rebuild the current library, after something changed it on disk.

        The caller has ensured nothing is mid-flight — a reload is only ever asked for by
        the watcher when nothing is pending, or after a synchronous operation settled.
        """
        if self.library_path is None:
            return False
        return self._open(self.library_path)

    def _open(
        self, library_path: Path, progress: Callable[[str], None] | None = None
    ) -> bool:
        try:
            builder = (
                AppBuilder()
                .with_source(library_path)
                .with_repository(self._repository)
                .with_menus(self._menus)
                .with_session(self)
                .with_modules(self._module_factory)
                .with_progress(progress)
            )
            if self._seed is not None:
                builder = builder.with_seed(self._seed)
            window, services = builder.build()
        except (ValueError, OSError, StorageError) as error:
            self._report(describe_open_error(error, library_path))
            return False

        old_window, old_services = self.window, self.services
        self.window, self.services, self.library_path = window, services, library_path
        window.show()

        # Shown first, then the old one closed: the screen never goes empty, and the old
        # build takes any unbalanced autosave pause with it when it is discarded.
        if old_window is not None:
            old_window.close()  # Runs close hooks — the final autosave flush.
            old_window.deleteLater()
        if old_services is not None:
            old_services.autosave.stop()
            old_services.repo.close()
        return True

    # -- errors --------------------------------------------------------------------------------

    def _report(self, failure: OpenFailure) -> None:
        if failure.detail:
            logger.error("%s %s", failure.text, failure.detail)
        if self.window is not None:
            # open(), not exec(): non-blocking, so a refusal can never deadlock a caller
            # (or a headless test) waiting on a modal loop.
            box = _failure_box(failure, self.window)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            box.open()
        else:
            show_startup_failure(failure)
