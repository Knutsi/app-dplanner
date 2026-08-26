"""Shared test fixtures.

Two things here are order-sensitive and must stay at module level, above the imports they
look like they should sit below. Both are commented where they are.
"""

import os

# Must precede any PySide6 import: the platform plugin is chosen when Qt's GUI layer loads.
# setdefault rather than a plain assignment so a developer can export QT_QPA_PLATFORM=xcb
# (or cocoa) to watch the tests drive a real window.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.core.storage.locations import StorageLocation

# AA_DontUseNativeMenuBar is read at QMenuBar construction time and must be set before the
# QApplication exists. pytest-qt constructs it lazily inside the `qapp` fixture, so this has
# to run at import time rather than inside a fixture.
set_early_attributes()


@pytest.fixture(scope="session")
def app(qapp, tmp_path_factory):
    """The session ``QApplication``, with our configuration applied.

    pytest-qt owns construction — only one QApplication may exist per process, and it cannot
    be safely recreated once destroyed — so this fixture only configures the instance it
    provides.

    QSettings is redirected to a throwaway ini directory first: ``configure_application``
    reads the persisted theme, and the developer's real preference must not leak into the
    suite (nor test writes into the developer's settings).
    """
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path_factory.mktemp("qsettings")),
    )
    configure_application(qapp)
    return qapp


@pytest.fixture
def close_quietly():
    """Tear a built application down without asking the user anything.

    Close guards exist to interrupt a real person ("Save before quitting?"); in a headless
    suite a modal dialog is a hang with no one to answer it. Dropping the guards is the
    honest way to say "this window is being discarded, not quit".
    """

    def close(session):
        if session.window is not None:
            session.window.close_guards.clear()
            session.window.close()
        if session.services is not None:
            session.services.autosave.stop()

    return close


@pytest.fixture
def session(app, tmp_path, close_quietly):
    """A whole application, built over a fresh workspace in a temp directory.

    Built through ``AppSession`` — the same path ``dplanner.app.main`` takes — so a test can
    never drift from production wiring. Yields the session; ``session.services`` reaches
    every part of the running application.
    """
    session = new_session()
    assert session.open_initial(StorageLocation(scheme="", target=str(tmp_path / "workspace")))
    yield session
    close_quietly(session)


@pytest.fixture
def services(session):
    """Shorthand for the built application's services."""
    return session.services


@pytest.fixture(autouse=True)
def _collect_qt_garbage():
    """Collect cyclic garbage at a safe point after each test.

    Left to its own schedule, Python's GC can free PySide wrappers mid Qt event dispatch in
    a later test — ``QObject::property`` on a half-destroyed object, a flaky SIGSEGV whose
    location shifts with any allocation change anywhere in the suite. Collecting between
    tests, while no Qt code is on the stack, keeps destruction deterministic.
    """
    yield
    import gc

    gc.collect()


@pytest.fixture(autouse=True)
def _fresh_session_settings():
    """Session state (last opened, recents) must not leak between tests.

    Any test that opens through ``AppSession`` records the workspace in QSettings; a later
    test asserting on the Open dialog's list would see it. The ``modules`` group holds
    per-module global preferences.
    """
    yield
    from PySide6.QtCore import QSettings

    settings = QSettings()
    for group in ("workspaces", "appearance", "modules", "layout"):
        settings.beginGroup(group)
        settings.remove("")
        settings.endGroup()
