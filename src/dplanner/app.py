"""Application bootstrap.

Split into small functions rather than one ``main`` so the application is testable. Exactly
one ``QApplication`` may exist per process and it cannot safely be recreated, so tests must
not construct their own; :func:`configure_application` applies our configuration to *any*
``QApplication``, which lets a test suite reuse a session-scoped instance.

This file and :mod:`dplanner.menus` are the two places that name the application itself. It
may import the composition root (:mod:`dplanner.modules`) and nothing deeper — reaching into
a module subpackage from here is a layering violation the architecture test refuses.
"""

import faulthandler
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from dplanner.assets import ICON_SIZES, icon_path
from dplanner.core.telemetry import crash_log_path, current
from dplanner.domain.dictation import DictationProvider
from dplanner.domain.library_file import resolve_library_path
from dplanner.domain.seed import create_library
from dplanner.domain.store import LibraryStore
from dplanner.framework.action_registry import MenuStructure
from dplanner.framework.diagnostics import (
    StallWatchdog,
    capture_failures,
    open_crash_log,
    session_ended,
    session_started,
)
from dplanner.framework.gc_policy import install_gc_policy
from dplanner.framework.session import AppSession
from dplanner.framework.splash import StartupSplash
from dplanner.framework.theme_service import apply_saved_theme
from dplanner.identity import APP_DOMAIN, APP_ID, APP_NAME, APP_VERSION
from dplanner.menus import MENU_STRUCTURE
from dplanner.modules import default_modules, dictation_providers, theme_providers
from dplanner.theme.providers import BUILTIN, ThemeProvider


def set_early_attributes() -> None:
    """Set application attributes that must precede ``QApplication`` construction.

    ``AA_DontUseNativeMenuBar`` is read by ``QMenuBar`` at *construction* time, so it has to
    be in place before any menu bar exists. Keeping the menu bar in-window on macOS is both
    a preference and a technical requirement: Qt applies no stylesheet to a menu bar merged
    into the macOS system menu bar, so a dark theme could not otherwise reach it.
    """
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)


def application_icon() -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addFile(str(icon_path(size)))
    return icon


def configure_application(
    app: QApplication, providers: Sequence[ThemeProvider] = (BUILTIN,)
) -> None:
    """Apply identity metadata and the theme to an existing ``QApplication``.

    ``providers`` is where the theme comes from — the machine's, from ``main``; the built-in
    alone by default, which is what a headless test run must never depart from.
    """
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setOrganizationDomain(APP_DOMAIN)
    # Sets the xdg-shell app_id on Wayland; without it a compositor cannot match the window
    # to a .desktop file, giving the wrong icon and broken window grouping.
    app.setDesktopFileName(APP_ID)
    # The same PNGs the desktop launcher installs, so the dock and the menu agree; every
    # size at once, and Qt picks the one the surface asks for.
    app.setWindowIcon(application_icon())

    # After the identity metadata: the saved choice is read from QSettings, which resolves
    # its storage location from the organisation and application names set above. And
    # before anything else touches the palette or the colour scheme: a provider that reads
    # the desktop is asked here whether it applies, while the reading is the platform's own.
    apply_saved_theme(app, providers)

    # Python's collector meets Qt objects on our terms: on the GUI thread, at safe points,
    # and never handing a Qt-owned object back to Python — framework/gc_policy.py has the
    # crashes this prevents.
    install_gc_policy(app)


def build_application(
    argv: list[str], providers: Sequence[ThemeProvider] = (BUILTIN,)
) -> QApplication:
    set_early_attributes()
    app = QApplication(argv)
    configure_application(app, providers)
    return app


def chosen_library(argv: list[str]) -> Path:
    """The library this instance runs on: ``--library``, ``$DPLANNER_LIBRARY``, or the
    per-user default. The default (and any explicitly named path that does not exist yet)
    is seeded by the builder, so a plain first launch opens an empty library rather than
    asking anything."""
    explicit = argv[argv.index("--library") + 1] if "--library" in argv else None
    return resolve_library_path(explicit)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the console script."""
    # Qt consumes -style, -platform and -stylesheet from argv, and argv[0] names the
    # process, so the real sys.argv is passed through rather than an empty list.
    args = list(sys.argv if argv is None else argv)
    library_path = chosen_library(args)
    # Our own arguments must not reach Qt's argv parsing.
    if "--library" in args:
        index = args.index("--library")
        del args[index : index + 2]

    # Built once and handed to both the startup apply and the session, so every reader
    # sees one tuple of providers — and the desktop's readings are taken before any theme.
    providers = theme_providers()
    app = build_application(args, providers)

    # The diagnostics live here and nowhere deeper: a test build has no event loop for a
    # heartbeat to beat in, and pytest owns the exception hooks while a test runs.
    telemetry = current()
    crash_log = open_crash_log(crash_log_path())
    restore_hooks = capture_failures(telemetry)
    watchdog = StallWatchdog(app, telemetry=telemetry, dump_to=crash_log)
    session_started(telemetry, library=library_path, version=APP_VERSION)
    code = 1
    try:
        session = new_session(providers, dictation_providers())
        if open_at_startup(session, library_path):
            # Only once the window is up: the build itself blocks the GUI thread behind the
            # splash for as long as it takes, and the session's "open" span already says so.
            watchdog.start()
            code = app.exec()
        else:
            code = 0
    finally:
        watchdog.stop()
        restore_hooks()
        session_ended(telemetry, exit_code=code)
        telemetry.close()
        if crash_log is not None:
            faulthandler.disable()
            crash_log.close()
    return code


def new_session(
    theme_providers: Sequence[ThemeProvider] = (BUILTIN,),
    dictation_providers: Sequence[DictationProvider] = (),
) -> AppSession:
    """The session, wired to this application's model, menus and modules.

    Everything application-specific the framework needs is handed over here: how to build a
    repository over its source path, what an empty library file contains, what the menus
    are called and which modules exist. Swap the first two and the same framework runs a
    different application. ``theme_providers`` is the machine's tuple from ``main``; the
    built-in alone by default, so a session built by a test never reads the desktop.
    ``dictation_providers`` likewise: none by default, so no test reaches a microphone.
    """
    return AppSession(
        module_factory=default_modules,
        repository=LibraryStore,
        menus=MenuStructure(MENU_STRUCTURE),
        seed=create_library,
        theme_providers=theme_providers,
        dictation_providers=dictation_providers,
    )


def open_at_startup(session: AppSession, library_path: Path) -> bool:
    """Open the library behind a splash.

    A failure has already been explained to the user by the session's startup reporter —
    and with a library that is auto-seeded there is nothing sensible to re-ask, so a
    failure simply gives up.
    """
    splash = StartupSplash()
    try:
        return session.open_initial(library_path, progress=splash.status)
    finally:
        splash.close()
