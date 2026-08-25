"""Application bootstrap.

Split into small functions rather than one ``main`` so the application is testable. Exactly
one ``QApplication`` may exist per process and it cannot safely be recreated, so tests must
not construct their own; :func:`configure_application` applies our configuration to *any*
``QApplication``, which lets a test suite reuse a session-scoped instance.

This file and :mod:`dplanner.menus` are the two places that name the application itself. It
may import the composition root (:mod:`dplanner.modules`) and nothing deeper — reaching into
a module subpackage from here is a layering violation the architecture test refuses.
"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from dplanner.core.storage.locations import StorageLocation, parse_location
from dplanner.domain.sample import create_sample
from dplanner.domain.store import PlanStore
from dplanner.framework.action_registry import MenuStructure
from dplanner.framework.session import AppSession, last_opened, workspace_roots
from dplanner.framework.splash import StartupSplash
from dplanner.framework.theme_service import saved_theme
from dplanner.identity import APP_DOMAIN, APP_ID, APP_NAME, APP_VERSION
from dplanner.menus import MENU_STRUCTURE
from dplanner.modules import choose_workspace, default_modules
from dplanner.theme import apply_theme


def set_early_attributes() -> None:
    """Set application attributes that must precede ``QApplication`` construction.

    ``AA_DontUseNativeMenuBar`` is read by ``QMenuBar`` at *construction* time, so it has to
    be in place before any menu bar exists. Keeping the menu bar in-window on macOS is both
    a preference and a technical requirement: Qt applies no stylesheet to a menu bar merged
    into the macOS system menu bar, so a dark theme could not otherwise reach it.
    """
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)


def configure_application(app: QApplication) -> None:
    """Apply identity metadata and the theme to an existing ``QApplication``."""
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setOrganizationDomain(APP_DOMAIN)
    # Sets the xdg-shell app_id on Wayland; without it a compositor cannot match the window
    # to a .desktop file, giving the wrong icon and broken window grouping.
    app.setDesktopFileName(APP_ID)

    # After the identity metadata: saved_theme() reads QSettings, which resolves its storage
    # location from the organisation and application names set above.
    apply_theme(app, saved_theme())


def build_application(argv: list[str]) -> QApplication:
    set_early_attributes()
    app = QApplication(argv)
    configure_application(app)
    return app


def explicit_workspace(argv: list[str]) -> StorageLocation | None:
    """A workspace named on the command line or in the environment, or None.

    An explicit location is a request: a directory that holds nothing yet is *seeded*, which
    is how a new workspace is started. Everything implicit goes through the last-opened
    setting and the Open dialog instead, which only ever open what already exists.
    """
    if "--workspace" in argv:
        return parse_location(argv[argv.index("--workspace") + 1])
    env = os.environ.get(f"{APP_ID.upper()}_WORKSPACE")
    return parse_location(env) if env else None


def main(argv: list[str] | None = None) -> int:
    """Entry point for the console script."""
    # Qt consumes -style, -platform and -stylesheet from argv, and argv[0] names the
    # process, so the real sys.argv is passed through rather than an empty list.
    args = list(sys.argv if argv is None else argv)
    explicit = explicit_workspace(args)
    # Our own arguments must not reach Qt's argv parsing.
    if "--workspace" in args:
        index = args.index("--workspace")
        del args[index : index + 2]

    app = build_application(args)

    # QSettings resolves its storage from the identity set in configure_application, so the
    # last-opened lookup has to come after build_application.
    location = explicit or last_opened()
    interactive = location is None
    if location is None:
        location = choose_workspace()
    if location is None:
        return 0  # Cancelled the Open dialog with nothing to open.

    session = new_session()
    if not open_at_startup(session, location, interactive):
        return 0
    return app.exec()


def new_session() -> AppSession:
    """The session, wired to this application's model, menus and modules.

    Everything application-specific the framework needs is handed over here: how to build a
    repository over a provider, what to put in an empty workspace, what the menus are called
    and which modules exist. Swap the first two and the same framework runs a different
    application.
    """
    return AppSession(
        module_factory=default_modules,
        repository=PlanStore,
        menus=MenuStructure(MENU_STRUCTURE),
        seed=create_sample,
        clone_into=workspace_roots()[0],
    )


def open_at_startup(session: AppSession, location: StorageLocation, interactive: bool) -> bool:
    """Open the first workspace behind a splash, offering the picker again on failure.

    A failure has already been explained to the user by the session's startup reporter, so
    this only decides whether to ask again or give up.
    """
    while True:
        splash = StartupSplash()
        try:
            opened = session.open_initial(location, interactive, progress=splash.status)
        finally:
            splash.close()
        if opened:
            return True
        chosen = choose_workspace()
        if chosen is None:
            return False
        location, interactive = chosen, True


def workspace_root_hint() -> Path:
    """Where new workspaces are suggested. Exposed for tests and for the Open dialog."""
    return workspace_roots()[0]
