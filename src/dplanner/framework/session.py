"""The session: which workspace is open, and how that changes.

:class:`AppBuilder` owns one build. The session owns the *sequence* of builds. Opening a
different workspace does not reconfigure the running application — it constructs an
entirely new window, services and module instances, shows it, then closes and discards the
old one.

That sounds heavy and is in fact the cheap option. Every registry refuses a duplicate id,
so a switch *cannot* be implemented as a re-registration; and the alternative — teaching
every registry, service and module to forget everything and start over — is teardown logic
exercised on exactly one code path, which is where bugs live. A rebuild is correct by
construction, and the only thing it costs is a fraction of a second nobody notices.

The memory of what was opened lives here too, in ``QSettings``: ``workspaces/last`` is
reopened at startup, ``workspaces/recent`` feeds the Open menu, and ``workspaces/roots``
names the folders the Open dialog scans.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from dplanner.core.formats import UnsupportedFormatError
from dplanner.core.repository import RepositoryFactory
from dplanner.core.storage.locations import (
    StorageLocation,
    describe_location,
    open_storage,
    parse_location,
)
from dplanner.core.storage.provider import StorageError
from dplanner.framework.action_registry import MenuStructure
from dplanner.framework.builder import AppBuilder, ModuleFactory, SeedFactory
from dplanner.identity import APP_NAME

if TYPE_CHECKING:
    from dplanner.framework.main_window import AppWindow
    from dplanner.framework.services import AppServices

logger = logging.getLogger(__name__)

LAST_KEY = "workspaces/last"
RECENT_KEY = "workspaces/recent"
ROOTS_KEY = "workspaces/roots"
RECENT_LIMIT = 10


def last_opened() -> StorageLocation | None:
    value = QSettings().value(LAST_KEY)
    return parse_location(str(value)) if value else None


def set_last_opened(location: StorageLocation) -> None:
    QSettings().setValue(LAST_KEY, str(location))


def recent_workspaces() -> list[StorageLocation]:
    """Most recent first. Entries whose directory is gone are dropped on read, so a
    deleted workspace quietly leaves the menu instead of failing when picked."""
    value = QSettings().value(RECENT_KEY) or []
    if isinstance(value, str):  # QSettings collapses a one-element list to a string.
        value = [value]
    locations = [parse_location(str(v)) for v in value]
    return [loc for loc in locations if loc.path is None or loc.path.is_dir()]


def add_recent(location: StorageLocation) -> None:
    others = (str(other) for other in recent_workspaces() if other != location)
    entries = [str(location), *others]
    QSettings().setValue(RECENT_KEY, entries[:RECENT_LIMIT])


def workspace_roots() -> list[Path]:
    """Folders the Open dialog offers to scan. Defaults to ``~/<DPlanner>``."""
    value = QSettings().value(ROOTS_KEY) or []
    if isinstance(value, str):
        value = [value]
    roots = [Path(str(v)).expanduser() for v in value]
    return roots or [Path(f"~/{APP_NAME}").expanduser()]


@dataclass(frozen=True)
class OpenFailure:
    """Why a workspace did not open, in the user's terms: what happened (``text``), what to
    do about it (``informative``) and the technical line behind it (``detail``)."""

    text: str
    title: str = "Open Workspace"
    informative: str = ""
    detail: str = ""


def describe_open_error(error: Exception, location: StorageLocation) -> OpenFailure:
    """Turn an exception into something worth reading.

    The newer-format case gets its own message because it is the one failure that is not a
    problem with the data: the workspace is fine and the application is behind, and the
    usual cause is a colleague's push or a branch switch rather than damage.
    """
    where = describe_location(location)
    if isinstance(error, UnsupportedFormatError) and error.is_newer:
        return OpenFailure(
            title=f"This workspace needs a newer {APP_NAME}",
            text=(
                f"{where} was saved in format {error.found}; "
                f"this build reads up to format {error.newest}."
            ),
            informative=(
                f"Update {APP_NAME} to open it. If this happened after a pull or a branch "
                "switch, that branch was written by a newer build — switching back will "
                "open again."
            ),
            detail=str(error),
        )
    if isinstance(error, UnsupportedFormatError):
        return OpenFailure(
            title=f"{APP_NAME} cannot read this workspace",
            text=f"{where} does not say which format it is in.",
            informative=(
                "Its metadata carries no usable format number. It may be damaged, or not a "
                f"{APP_NAME} workspace at all."
            ),
            detail=str(error),
        )
    return OpenFailure(text=f"Could not open {where}.", detail=str(error))


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


class WorkspaceSwitcher(Protocol):
    """What modules may do to the session: switch workspaces, and guard the switch.

    The narrow face of :class:`AppSession`. Modules depend on this and never on the session
    itself, so the builder can hand them a real capability instead of a back-reference that
    might be None.
    """

    def switch_to(self, location: StorageLocation) -> bool: ...

    def reload(self) -> bool: ...

    def add_switch_guard(self, guard: Callable[[], str | None]) -> None: ...


class AppSession:
    """Owns the current (window, services) pair and replaces it on open, switch and reload.

    ``pre_open`` runs before each build — before anything is read from disk — so it may
    still change what is *on* disk; the sync module uses it to settle which branch is
    checked out. Its second argument says whether the user explicitly chose this workspace
    (a dialog, File ▸ Open) or it was restored silently (last-opened, the command line),
    because those deserve different amounts of interruption.
    """

    def __init__(
        self,
        module_factory: ModuleFactory,
        repository: RepositoryFactory[Any],
        menus: MenuStructure,
        seed: SeedFactory | None = None,
        pre_open: Callable[[StorageLocation, bool], None] | None = None,
        clone_into: Path | None = None,
    ) -> None:
        self._module_factory = module_factory
        self._repository = repository
        self._menus = menus
        self._seed = seed
        self._pre_open = pre_open
        self._clone_into = clone_into
        self.window: AppWindow | None = None
        self.services: AppServices | None = None
        self.location: StorageLocation | None = None
        # A guard returns a refusal reason (shown to the user) or None. Modules of the
        # CURRENT build register here; guards are reset on every switch, because the new
        # build's modules register their own.
        self.switch_guards: list[Callable[[], str | None]] = []

    def add_switch_guard(self, guard: Callable[[], str | None]) -> None:
        self.switch_guards.append(guard)

    # -- opening -------------------------------------------------------------------------------

    def open_initial(
        self,
        location: StorageLocation,
        interactive: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> bool:
        """The first open at startup.

        ``progress`` receives a short label at each stage boundary (the startup splash);
        switching and reloading skip it — a window is already up to look at by then.
        """
        if self._pre_open is not None:
            if progress is not None:
                progress("Checking storage…")
            self._pre_open(location, interactive)
        return self._open(location, progress)

    def switch_to(self, location: StorageLocation) -> bool:
        """Open another workspace, replacing the current one."""
        if self.window is not None and location == self.location:
            self.window.show_status("This workspace is already open", 5000)
            return True
        for guard in self.switch_guards:
            reason = guard()
            if reason is not None:
                self._report(OpenFailure(reason))
                return False
        if self._pre_open is not None:
            self._pre_open(location, True)  # File ▸ Open is always an explicit choice.
        return self._open(location)

    def reload(self) -> bool:
        """Rebuild the current workspace, after something changed it on disk.

        No ``pre_open`` — the caller has just settled whatever it was doing — and no switch
        guards, because this is not a switch and the caller has ensured nothing is mid-flight.
        """
        if self.location is None:
            return False
        return self._open(self.location)

    def _open(
        self, location: StorageLocation, progress: Callable[[str], None] | None = None
    ) -> bool:
        old_guards = self.switch_guards
        self.switch_guards = []  # The fresh build's modules register theirs instead.
        try:
            storage = open_storage(location, clone_into=self._clone_into)
            builder = (
                AppBuilder()
                .with_storage(storage)
                .with_repository(self._repository)
                .with_menus(self._menus)
                .with_switcher(self)
                .with_modules(self._module_factory)
                .with_progress(progress)
            )
            if self._seed is not None:
                builder = builder.with_seed(self._seed)
            window, services = builder.build()
        except (ValueError, OSError, StorageError) as error:
            self.switch_guards = old_guards  # The current build stays; keep its guards.
            self._report(describe_open_error(error, location))
            return False

        old_window, old_services = self.window, self.services
        self.window, self.services, self.location = window, services, location
        window.show()

        # Shown first, then the old one closed: the screen never goes empty, and the old
        # build takes any unbalanced autosave pause with it when it is discarded.
        if old_window is not None:
            old_window.close()  # Runs close hooks — the final autosave flush.
            old_window.deleteLater()
        if old_services is not None:
            old_services.autosave.stop()
            old_services.repo.close()

        set_last_opened(location)
        add_recent(location)
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
