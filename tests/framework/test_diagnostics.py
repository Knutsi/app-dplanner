"""The hooks that explain a hang or a crash after the fact.

Each test installs its own journal and its own hooks and puts every one of them back:
pytest-qt owns ``sys.excepthook`` while a test runs, and the process's watchdog is never
started by a test build — a suite has no event loop, so it would read as one long stall.
"""

import logging
import sys
import threading
import time

import pytest
from PySide6.QtCore import QTimer, qWarning

from dplanner.core.telemetry import Telemetry, install
from dplanner.framework.diagnostics import (
    StallWatchdog,
    capture_failures,
    open_crash_log,
    session_ended,
    session_started,
)


@pytest.fixture
def journal():
    made = Telemetry()
    previous = install(made)
    try:
        yield made
    finally:
        install(previous)


def test_a_blocked_gui_thread_is_a_stall_span_with_its_stack(app, qtbot, journal):
    watchdog = StallWatchdog(telemetry=journal, heartbeat_ms=10, stall_ms=30, sample_ms=20)
    watchdog.start()
    try:
        qtbot.wait(50)  # Beating.
        with journal.span("action", "steps.delete"):
            QTimer.singleShot(0, lambda: time.sleep(0.12))  # The GUI thread stops turning.
            qtbot.wait(200)
    finally:
        watchdog.stop()
    (stall,) = [span for span in journal.recent() if span.kind == "stall"]
    assert stall.duration_ms is not None and stall.duration_ms >= 90
    assert stall.ok and stall.detail["during"] == ["action steps.delete"]
    samples = stall.detail["samples"]
    assert samples and "sleep" in samples[0]
    assert stall.thread == "stall-watchdog" and stall.name == threading.main_thread().name


def test_a_turning_event_loop_is_not_a_stall(app, qtbot, journal):
    watchdog = StallWatchdog(telemetry=journal, heartbeat_ms=10, stall_ms=60)
    watchdog.start()
    try:
        qtbot.wait(150)
    finally:
        watchdog.stop()
    assert [span for span in journal.recent() if span.kind == "stall"] == []


def test_stop_ends_a_stall_in_flight_and_joins(app, qtbot, journal):
    watchdog = StallWatchdog(telemetry=journal, heartbeat_ms=10, stall_ms=20)
    watchdog.start()
    qtbot.wait(30)
    time.sleep(0.08)  # Nothing turns the loop: a stall opens on the watching thread.
    watchdog.stop()
    assert watchdog._thread is None
    (stall,) = [span for span in journal.recent() if span.kind == "stall"]
    assert stall.detail.get("stopped") is True


def _quiet(*_args: object) -> None:
    """A previous hook that says nothing: pytest-qt's own would fail the test on the
    chained call, and pytest's thread plugin would warn — the chaining is what is under
    test, not what the previous hook then does."""


def test_uncaught_exceptions_and_qt_warnings_become_failures(app, journal, capsys):
    saved = sys.excepthook
    sys.excepthook = _quiet
    restore = capture_failures(journal)
    try:
        try:
            raise ValueError("from a slot")
        except ValueError as error:
            sys.excepthook(type(error), error, error.__traceback__)
        qWarning("QPainter::begin: Paint device returned engine == 0")
    finally:
        restore()
        sys.excepthook = saved

    uncaught, qt = [span for span in journal.recent() if span.kind == "failure"]
    assert uncaught.name == "uncaught: ValueError" and "from a slot" in (uncaught.traceback or "")
    assert qt.name.startswith("Qt: QPainter::begin") and qt.detail["category"] == "qt"
    assert "QPainter::begin" in capsys.readouterr().err  # Still printed, never silenced.


def test_a_thread_that_dies_is_a_failure_too(journal):
    saved = threading.excepthook
    threading.excepthook = _quiet
    restore = capture_failures(journal)
    try:

        def die() -> None:
            raise RuntimeError("worker broke")

        worker = threading.Thread(target=die, name="worker-1")
        worker.start()
        worker.join()
    finally:
        restore()
        threading.excepthook = saved

    (failure,) = [span for span in journal.recent() if span.kind == "failure"]
    assert failure.name == "thread worker-1: RuntimeError"
    assert "worker broke" in (failure.traceback or "")


def test_the_hooks_are_put_back(journal):
    before = (sys.excepthook, threading.excepthook)
    capture_failures(journal)()
    assert (sys.excepthook, threading.excepthook) == before


def test_the_crash_log_is_appended_beside_the_journal(tmp_path):
    import faulthandler

    path = tmp_path / "telemetry" / "crash.log"
    path.parent.mkdir()
    path.write_text("earlier\n")
    handle = open_crash_log(path)
    try:
        assert handle is not None and faulthandler.is_enabled()
        faulthandler.dump_traceback(file=handle)
        handle.flush()
    finally:
        faulthandler.disable()
        if handle is not None:
            handle.close()
    text = path.read_text()
    assert text.startswith("earlier\n") and "test_the_crash_log_is_appended" in text


def test_an_unwritable_crash_log_is_not_a_launch_failure(tmp_path):
    blocked = tmp_path / "file-not-dir"
    blocked.write_text("")
    assert open_crash_log(blocked / "telemetry" / "crash.log") is None


def test_a_session_is_a_start_and_an_end(tmp_path, journal):
    session_started(journal, library=tmp_path / "library.json", version="0.1.0")
    session_ended(journal, exit_code=0)
    start, end = journal.recent()
    assert (start.kind, start.name, start.detail["app"]) == ("session", "start", "0.1.0")
    assert start.detail["pyside"] and start.detail["python"] and start.detail["platform"]
    assert (end.name, end.detail) == ("end", {"exit_code": 0})


def test_the_console_keeps_its_warnings_when_the_journal_is_installed():
    """A handler on the root logger swallows Python's last-resort stderr output; install()
    adds a stream handler when the root has none (the application's case — under pytest
    the root already carries the capture handlers, and then nothing is added)."""
    root = logging.getLogger()
    had, level = list(root.handlers), root.level
    for handler in had:
        root.removeHandler(handler)
    try:
        previous = install(Telemetry())
        try:
            streams = [h for h in root.handlers if type(h) is logging.StreamHandler]
            assert len(streams) == 1
        finally:
            install(previous)
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in had:
            root.addHandler(handler)
        root.setLevel(level)
