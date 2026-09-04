"""Why did it hang, and what killed it: the hooks that explain a stall or a crash after the fact.

Three things, all started from ``app.main`` and from nowhere else — a test process has no
event loop, so a heartbeat there would read as one long stall, and pytest-qt owns the
exception hooks while a test runs:

- :class:`StallWatchdog`. A 100 ms ``QTimer`` on the GUI thread stamps the clock; a daemon
  thread wakes a few times a second and, when the stamp is older than :data:`STALL_MS`,
  samples the GUI thread's stack through ``sys._current_frames()`` and opens a ``stall``
  span carrying the sample and whatever spans were open on that thread — "stall 1.2 s
  during action steps.delete → command Delete 5 Steps", with the frames that were running.
  More samples follow every :data:`SAMPLE_MS` while it lasts; the next heartbeat closes it
  with the true duration. A modal dialog runs a nested event loop, so the heartbeat keeps
  beating and a dialog never reads as a stall. The sampler needs the GIL, so a stall inside
  a C++ call is sampled when the GIL is next released and shows the Python frame that made
  the call, which is the one worth reading. With a crash log to write to, the heartbeat
  also re-arms ``faulthandler.dump_traceback_later``: a hang that holds the GIL for
  :data:`DUMP_AFTER_S` gets its stacks dumped there by faulthandler's own C thread.
- :func:`capture_failures`. ``sys.excepthook`` (PySide prints a slot's exception through it),
  ``threading.excepthook`` and Qt's own message handler are chained into ``failure`` spans,
  so a warning Qt printed a minute before the crash is in the journal beside it. Each
  previous hook still runs; nothing here silences anything.
- :func:`open_crash_log`. ``faulthandler.enable`` on ``crash.log`` beside the journal, for a
  SIGSEGV or SIGABRT: the Python stack at a native crash, appended to — the class of crash
  the test suite has met, now with a post-mortem. ``dplanner telemetry show --failures``
  prints its tail.
"""

import faulthandler
import sys
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TextIO

from PySide6.QtCore import QMessageLogContext, QObject, QTimer, QtMsgType, qInstallMessageHandler

from dplanner.core.telemetry import Span, Telemetry, current

HEARTBEAT_MS = 100
STALL_MS = 250
SAMPLE_MS = 500
MAX_SAMPLES = 6  # A stall of minutes is a handful of samples, not a novel.
STACK_DEPTH = 30  # Innermost frames per sample.
DUMP_AFTER_S = 2.0


class StallWatchdog(QObject):
    """Notices the GUI thread not turning its event loop, and says what it was doing."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        telemetry: Telemetry | None = None,
        heartbeat_ms: int = HEARTBEAT_MS,
        stall_ms: float = STALL_MS,
        sample_ms: float = SAMPLE_MS,
        dump_to: TextIO | None = None,
    ) -> None:
        super().__init__(parent)
        # Built on the thread it watches: the one whose event loop drives the timer.
        self._gui_thread_id = threading.get_ident()
        self._gui_thread_name = threading.current_thread().name
        self._telemetry = telemetry
        self._stall_s = stall_ms / 1000.0
        self._sample_s = sample_ms / 1000.0
        self._dump_to = dump_to
        self._lock = threading.Lock()
        self._last_beat = time.perf_counter()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(heartbeat_ms)
        self._timer.timeout.connect(self._beat)

    def start(self) -> None:
        self._beat()
        self._timer.start()
        self._thread = threading.Thread(target=self._watch, name="stall-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._timer.stop()
        if self._dump_to is not None:
            faulthandler.cancel_dump_traceback_later()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- the GUI thread ------------------------------------------------------------------------

    def _beat(self) -> None:
        with self._lock:
            self._last_beat = time.perf_counter()
        if self._dump_to is not None:
            # Re-armed every beat: only a GUI thread that stops beating lets it fire.
            faulthandler.dump_traceback_later(DUMP_AFTER_S, repeat=False, file=self._dump_to)

    # -- the watching thread -------------------------------------------------------------------

    def _watch(self) -> None:
        telemetry = self._telemetry or current()
        stall: Span | None = None
        last_sample = 0.0
        poll_s = min(self._stall_s, self._sample_s) / 4.0
        while not self._stop.wait(poll_s):
            now = time.perf_counter()
            with self._lock:
                last_beat = self._last_beat
            age = now - last_beat
            if age >= self._stall_s:
                if stall is None:
                    stall = telemetry.begin(
                        "stall",
                        self._gui_thread_name,
                        during=[f"{span.kind} {span.name}" for span in self._open_gui_spans()],
                        samples=[self._sample()],
                    )
                    # The stall began when the beats stopped, not when it was noticed.
                    stall.monotonic_start = last_beat
                    stall.started_at = time.time() - age
                    last_sample = now
                elif now - last_sample >= self._sample_s:
                    samples = stall.detail["samples"]
                    if len(samples) < MAX_SAMPLES:
                        samples.append(self._sample())
                    last_sample = now
            elif stall is not None:
                telemetry.end(stall)
                stall = None
        if stall is not None:
            telemetry.end(stall, stopped=True)

    def _open_gui_spans(self) -> list[Span]:
        telemetry = self._telemetry or current()
        return telemetry.open_spans(thread=self._gui_thread_name)

    def _sample(self) -> str:
        frame = sys._current_frames().get(self._gui_thread_id)
        if frame is None:
            return "(no frame)"
        return "".join(traceback.format_stack(frame, limit=STACK_DEPTH))


def capture_failures(telemetry: Telemetry | None = None) -> Callable[[], None]:
    """Chain the process's exception hooks and Qt's message handler into failure spans.

    Returns the undo: a test installs, asserts, and puts the previous hooks back.
    """
    journal = telemetry or current()
    previous_excepthook = sys.excepthook
    previous_threading_hook = threading.excepthook

    def excepthook(
        kind: type[BaseException], error: BaseException, tb: TracebackType | None
    ) -> None:
        journal.failure(
            f"uncaught: {kind.__name__}",
            error,
            traceback_text="".join(traceback.format_exception(kind, error, tb)),
        )
        previous_excepthook(kind, error, tb)

    def threading_hook(args: threading.ExceptHookArgs) -> None:
        name = args.thread.name if args.thread is not None else "?"
        text = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
        journal.failure(
            f"thread {name}: {args.exc_type.__name__}", args.exc_value, traceback_text=text
        )
        previous_threading_hook(args)

    def message_handler(mode: QtMsgType, context: QMessageLogContext, message: str) -> None:
        # Qt's default handler is gone once ours is installed, so the console line is ours
        # to print — the journal is in addition to it, never instead.
        print(message, file=sys.stderr)
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            where = f"{context.file}:{context.line}" if context.file else ""
            journal.failure(f"Qt: {message}", category="qt", level=mode.name, where=where)

    sys.excepthook = excepthook
    threading.excepthook = threading_hook
    previous_handler = qInstallMessageHandler(message_handler)

    def restore() -> None:
        sys.excepthook = previous_excepthook
        threading.excepthook = previous_threading_hook
        qInstallMessageHandler(previous_handler)

    return restore


def open_crash_log(path: Path) -> TextIO | None:
    """Point faulthandler at ``path`` (appending) and return the handle it needs kept open;
    None when the directory cannot be written, which is not worth failing a launch over."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
    except OSError:
        return None
    faulthandler.enable(file=handle, all_threads=True)
    return handle


def session_started(telemetry: Telemetry, *, library: Path, version: str) -> None:
    """The journal's session header: what was running, so a run of rows can be attributed
    — and a start with no end after it is the sign of a session that did not exit."""
    import platform

    from PySide6 import __version__ as pyside_version

    telemetry.record(
        "session",
        "start",
        app=version,
        python=platform.python_version(),
        pyside=pyside_version,
        platform=f"{platform.system()} {platform.release()}",
        library=str(library),
        at=datetime.now().isoformat(timespec="seconds"),
    )


def session_ended(telemetry: Telemetry, *, exit_code: int) -> None:
    telemetry.record("session", "end", exit_code=exit_code)
