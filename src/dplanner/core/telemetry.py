"""What the application did and how long it took — one journal for both surfaces.

Every action a presenter runs, every command the undo stack applies, every slow listener a
signal fanned out to, every task, autosave flush and disk poll, every CLI run, every stall
the watchdog sampled and every failure anything logged is a :class:`Span`: a kind, a name,
when it started, how long it took, whether it succeeded and — nested — what it ran inside.
The window's tab and ``dplanner telemetry show`` are two readers of the same records, and
"why did that take a second" is answered by the tree under the action rather than guessed.

**Process-wide, like ``logging``.** ``core.signals.Signal`` times its slots and can be handed
no service, so there is one :func:`current` instance per process: a default that keeps the
ring buffer and writes nothing — every test sees that one — and the file-backed one the
entry point :func:`install`s. Nothing is ever off: the hot path is two ``perf_counter``
calls per slot and an append under a lock per span, and a span that is not worth a
record is simply not made (a slot under :data:`SLOW_MS` is timed and forgotten).

**Two stores, one policy.** The ring holds the last :data:`RING_SIZE` spans, every kind,
except a poll that was quick — a 2 s poll would otherwise be most of what it held. The
file, ``journal.jsonl`` under :func:`journal_path`, is append-only JSON lines and gets
what is worth reading back after the fact: every ``failure``, ``stall``, ``session`` and
``cli`` span, and anything at all that took :data:`SLOW_MS` or longer. One ``write()`` per
line, so the window and a CLI run can append to the same file and their rows interleave
into one timeline; whoever finds the file past :data:`ROTATE_BYTES` rotates it.

**Failures arrive through ``logging``.** :func:`install` puts a handler on the root
logger, so every ``logger.exception``/``warning`` already in the tree — a raising signal
slot, a failed task, a refused open — becomes a ``failure`` span with its traceback and
its parent, and no call site learns anything.
"""

import itertools
import json
import logging
import os
import threading
import time
import traceback
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TextIO

from dplanner.core.config_dir import config_dir

# A span shorter than this is worth the ring but not the file; a slot shorter than this is
# not worth a span at all. One frame at 50 Hz: what a person can start to feel.
SLOW_MS = 20.0
RING_SIZE = 2000
ROTATE_BYTES = 5_000_000
JOURNAL_NAME = "journal.jsonl"
CRASH_LOG_NAME = "crash.log"

# Written to the file however quick they were: the rows post-hoc analysis is about.
ALWAYS_WRITTEN = frozenset({"failure", "stall", "session", "cli"})


def journal_path() -> Path:
    """Where the file-backed journal lives: the Qt-free per-user directory, so the CLI can
    read what the window wrote and write beside it."""
    return config_dir() / "telemetry" / JOURNAL_NAME


def crash_log_path() -> Path:
    """Where ``faulthandler`` writes a native crash's Python stack — beside the journal."""
    return config_dir() / "telemetry" / CRASH_LOG_NAME


@dataclass
class Span:
    """One thing that happened. Mutable while open; a copy once handed out."""

    span_id: int
    kind: str  # action | command | slot | task | autosave | poll | session | stall | cli | failure
    name: str
    started_at: float  # Wall clock (time.time()), for display and for lining two processes up.
    thread: str
    surface: str  # "window" or "cli".
    pid: int
    parent: int | None = None  # The span this one ran inside, on the same thread.
    duration_ms: float | None = None  # None while still open.
    ok: bool = True
    error_type: str | None = None
    error_message: str | None = None
    traceback: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    # perf_counter at begin(); not part of the record, the wall clock is.
    monotonic_start: float = field(default_factory=time.perf_counter, repr=False, compare=False)

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": self.span_id,
            "t": self.started_at,
            "kind": self.kind,
            "name": self.name,
            "ms": None if self.duration_ms is None else round(self.duration_ms, 3),
            "ok": self.ok,
            "pid": self.pid,
            "thread": self.thread,
            "surface": self.surface,
            "parent": self.parent,
        }
        if not self.ok:
            record["error"] = {
                "type": self.error_type,
                "message": self.error_message,
                "traceback": self.traceback,
            }
        if self.detail:
            record["detail"] = self.detail
        return record

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Span":
        error = record.get("error") or {}
        return cls(
            span_id=int(record.get("id", 0)),
            kind=str(record.get("kind", "")),
            name=str(record.get("name", "")),
            started_at=float(record.get("t", 0.0)),
            thread=str(record.get("thread", "")),
            surface=str(record.get("surface", "")),
            pid=int(record.get("pid", 0)),
            parent=record.get("parent"),
            duration_ms=record.get("ms"),
            ok=bool(record.get("ok", True)),
            error_type=error.get("type"),
            error_message=error.get("message"),
            traceback=error.get("traceback"),
            detail=dict(record.get("detail") or {}),
        )


class Telemetry:
    """The ring buffer, the file sink and the open-span bookkeeping — thread-safe."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        surface: str = "window",
        ring: int = RING_SIZE,
        slow_ms: float = SLOW_MS,
    ) -> None:
        self._path = path
        self.surface = surface
        self.slow_ms = slow_ms
        self.pid = os.getpid()
        self._lock = threading.Lock()
        self._ring: deque[Span] = deque(maxlen=ring)
        self._open: dict[int, Span] = {}
        self._ids = itertools.count(1)
        self._local = threading.local()
        self._file: TextIO | None = None
        self._handler = _FailureHandler(self)

    @property
    def path(self) -> Path | None:
        return self._path

    # -- recording -----------------------------------------------------------------------------

    def begin(self, kind: str, name: str, **detail: Any) -> Span:
        """Open a span on this thread, nested under whatever is open here already."""
        span = Span(
            span_id=next(self._ids),
            kind=kind,
            name=name,
            started_at=time.time(),
            thread=threading.current_thread().name,
            surface=self.surface,
            pid=self.pid,
            parent=self._current_id(),
            detail=dict(detail),
        )
        with self._lock:
            self._open[span.span_id] = span
        self._stack().append(span.span_id)
        return span

    def end(self, span: Span, *, error: BaseException | None = None, **detail: Any) -> Span:
        span.duration_ms = (time.perf_counter() - span.monotonic_start) * 1000.0
        if error is not None:
            _fail(span, error)
        span.detail.update(detail)
        stack = self._stack()
        if span.span_id in stack:
            del stack[stack.index(span.span_id) :]
        with self._lock:
            self._open.pop(span.span_id, None)
            self._record(span)
        return span

    @contextmanager
    def span(self, kind: str, name: str, **detail: Any) -> Iterator[Span]:
        """``with telemetry.span("action", "steps.link"):`` — an exception is recorded on the
        span and re-raised; nothing here swallows."""
        span = self.begin(kind, name, **detail)
        try:
            yield span
        except BaseException as error:
            self.end(span, error=error)
            raise
        else:
            self.end(span)

    def record(
        self,
        kind: str,
        name: str,
        *,
        duration_ms: float = 0.0,
        ok: bool = True,
        error: BaseException | None = None,
        error_message: str | None = None,
        traceback_text: str | None = None,
        **detail: Any,
    ) -> Span:
        """A span that is already over: a slow slot its signal timed, a task whose worker
        has returned, a failure that had no beginning. Nested under this thread's open
        span, if any. ``error_message`` marks a failure that arrived as words rather than
        as an exception (a task's)."""

        span = Span(
            span_id=next(self._ids),
            kind=kind,
            name=name,
            started_at=time.time() - duration_ms / 1000.0,
            thread=threading.current_thread().name,
            surface=self.surface,
            pid=self.pid,
            parent=self._current_id(),
            duration_ms=duration_ms,
            ok=ok,
            detail=dict(detail),
        )
        if error is not None:
            _fail(span, error)
        if error_message is not None:
            span.ok = False
            span.error_message = error_message
        if traceback_text is not None:
            span.ok = False
            span.traceback = traceback_text
        with self._lock:
            self._record(span)
        return span

    def failure(
        self,
        name: str,
        error: BaseException | None = None,
        *,
        traceback_text: str | None = None,
        **detail: Any,
    ) -> Span:
        """Something went wrong and nothing timed it — an uncaught exception, a Qt warning,
        a log record at WARNING or above. Marked failed before it is recorded, so the file
        line says so too."""
        return self.record(
            "failure", name, ok=False, error=error, traceback_text=traceback_text, **detail
        )

    # -- reading -------------------------------------------------------------------------------

    def recent(self) -> list[Span]:
        """The ring, oldest first — copies, so a reader never sees a span still being
        written on another thread (the ``LLMService.recent_calls`` rule)."""
        with self._lock:
            return [replace(span, detail=dict(span.detail)) for span in self._ring]

    def open_spans(self, thread: str | None = None) -> list[Span]:
        """What is in flight right now — what a stall interrupted — outermost first."""
        with self._lock:
            found = [
                replace(span, detail=dict(span.detail))
                for span in self._open.values()
                if thread is None or span.thread == thread
            ]
        return sorted(found, key=lambda span: span.span_id)

    def clear(self) -> None:
        with self._lock:
            self._ring.clear()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    # -- internals -----------------------------------------------------------------------------

    def _stack(self) -> list[int]:
        stack: list[int] | None = getattr(self._local, "stack", None)
        if stack is None:
            stack = []
            self._local.stack = stack
        return stack

    def _current_id(self) -> int | None:
        stack = self._stack()
        return stack[-1] if stack else None

    def _record(self, span: Span) -> None:
        """Under the lock: ring it, and file it when it is worth reading back."""
        quick = (span.duration_ms or 0.0) < self.slow_ms
        if not (span.kind == "poll" and quick):
            self._ring.append(span)
        if self._path is not None and (span.kind in ALWAYS_WRITTEN or not quick):
            self._write(span)

    def _write(self, span: Span) -> None:
        path = self._path
        if path is None:
            return
        try:
            if self._file is None:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.stat().st_size > ROTATE_BYTES:
                    path.replace(path.with_name(path.stem + ".1.jsonl"))
                self._file = path.open("a", encoding="utf-8")
            self._file.write(json.dumps(span.to_record(), ensure_ascii=False, default=str) + "\n")
            self._file.flush()
        except OSError:
            self._file = None  # A journal that cannot be written is not worth a crash.


def _fail(span: Span, error: BaseException) -> None:
    span.ok = False
    span.error_type = type(error).__name__
    span.error_message = str(error)
    span.traceback = "".join(traceback.format_exception(error))


class _FailureHandler(logging.Handler):
    """Every WARNING-or-worse log record becomes a failure span, traceback included."""

    def __init__(self, telemetry: Telemetry) -> None:
        super().__init__(level=logging.WARNING)
        self._telemetry = telemetry

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = None
            error: BaseException | None = None
            if record.exc_info and record.exc_info[0] is not None:
                error = record.exc_info[1]
                text = "".join(traceback.format_exception(*record.exc_info))
            self._telemetry.failure(
                f"{record.name}: {record.getMessage()}",
                error,
                traceback_text=text,
                level=record.levelname,
            )
        except Exception:  # A logging handler must never raise into its caller.
            self.handleError(record)


def describe_slot(slot: object) -> str:
    """A listener's name for a span: ``OrderActivity._refresh (module.py:216)``.

    A closure wrapping another callable says so with ``__wrapped__`` and is named for what
    it wraps — the span should name the view, not the plumbing between it and the signal.
    """
    target = slot
    for _ in range(8):
        inner = getattr(target, "__wrapped__", None)
        if inner is None:
            break
        target = inner
    func = getattr(target, "__func__", target)
    qualname = getattr(func, "__qualname__", None) or type(target).__qualname__
    code = getattr(func, "__code__", None)
    if code is None:
        return qualname
    return f"{qualname} ({Path(code.co_filename).name}:{code.co_firstlineno})"


# -- the process-wide instance -----------------------------------------------------------------

_current = Telemetry()


def current() -> Telemetry:
    return _current


def install(telemetry: Telemetry) -> Telemetry:
    """Make ``telemetry`` the process's journal and route log failures into it; returns the
    one it replaced, so a test can put things back. Console output for warnings stays: the
    root logger gets a stream handler if it has none, exactly as Python's last-resort
    handler would have printed them."""
    global _current
    previous = _current
    root = logging.getLogger()
    root.removeHandler(previous._handler)
    if not root.handlers:
        logging.basicConfig(level=logging.WARNING)
    root.addHandler(telemetry._handler)
    _current = telemetry
    return previous


def read_journal(path: Path) -> list[Span]:
    """Every span in the file, in the order written; a torn last line is skipped."""
    if not path.is_file():
        return []
    found: list[Span] = []
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                found.append(Span.from_record(json.loads(line)))
            except (ValueError, TypeError):
                continue
    return found
