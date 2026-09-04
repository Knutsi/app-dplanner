"""The journal: spans nest, the ring keeps the recent past, the file keeps what matters.

Qt-free, like the module: everything here is plain Python over a ``Telemetry`` built for
the test — never the process's ``current()`` with a file behind it.
"""

import json
import logging
import threading

import pytest

from dplanner.core import telemetry as telemetry_module
from dplanner.core.telemetry import (
    Span,
    Telemetry,
    current,
    describe_slot,
    install,
    read_journal,
)


@pytest.fixture
def installed():
    """Make a throwaway journal the process's for one test, and put the old one back."""
    made = Telemetry()
    previous = install(made)
    try:
        yield made
    finally:
        install(previous)


# -- spans ---------------------------------------------------------------------------------------


def test_spans_nest_on_one_thread():
    journal = Telemetry()
    with (
        journal.span("action", "steps.link") as outer,
        journal.span("command", "Change Links") as inner,
    ):
        leaf = journal.record("slot", "OrderActivity._refresh", duration_ms=30.0)

    assert inner.parent == outer.span_id
    assert leaf.parent == inner.span_id
    assert outer.parent is None
    kinds = [span.kind for span in journal.recent()]
    assert kinds == ["slot", "command", "action"]  # Recorded as they end: leaf first.
    assert all(span.duration_ms is not None and span.ok for span in journal.recent())


def test_a_raising_span_records_the_error_and_re_raises():
    journal = Telemetry()
    with pytest.raises(RuntimeError, match="boom"), journal.span("action", "steps.delete"):
        raise RuntimeError("boom")
    (span,) = journal.recent()
    assert (span.ok, span.error_type, span.error_message) == (False, "RuntimeError", "boom")
    assert span.traceback is not None and "boom" in span.traceback


def test_open_spans_say_what_is_in_flight():
    journal = Telemetry()
    span = journal.begin("action", "steps.details")
    assert [pending.name for pending in journal.open_spans()] == ["steps.details"]

    journal.end(span)
    assert journal.open_spans() == []


def test_a_failure_is_a_span_that_never_started():
    journal = Telemetry()
    span = journal.failure("Qt: QPainter::begin", traceback_text="stack", category="qt")
    assert span.kind == "failure" and span.ok is False
    assert span.traceback == "stack" and span.detail == {"category": "qt"}


def test_a_task_that_failed_in_words_is_not_ok():
    journal = Telemetry()
    span = journal.record("task", "Saving", duration_ms=12.0, error_message="git refused")
    assert (span.ok, span.error_message) == (False, "git refused")


# -- the ring ------------------------------------------------------------------------------------


def test_the_ring_keeps_the_last_spans_oldest_first():
    journal = Telemetry(ring=3)
    for index in range(5):
        journal.record("action", f"a{index}", duration_ms=1.0)
    assert [span.name for span in journal.recent()] == ["a2", "a3", "a4"]
    journal.clear()
    assert journal.recent() == []


def test_a_quick_poll_is_not_worth_the_ring():
    journal = Telemetry(slow_ms=20.0)
    journal.record("poll", "workspace", duration_ms=1.0)
    journal.record("poll", "workspace", duration_ms=50.0)
    journal.record("action", "steps.new", duration_ms=1.0)  # Quick, but an action.
    assert [(span.kind, span.duration_ms) for span in journal.recent()] == [
        ("poll", 50.0),
        ("action", 1.0),
    ]


def test_a_snapshot_is_copies():
    journal = Telemetry()
    journal.record("action", "a", duration_ms=1.0, detail_key="value")
    snapshot = journal.recent()[0]
    snapshot.name = "tampered"
    snapshot.detail["detail_key"] = "tampered"
    assert journal.recent()[0].name == "a"
    assert journal.recent()[0].detail == {"detail_key": "value"}


def test_recording_from_several_threads_is_safe():
    journal = Telemetry(ring=100)

    def burst() -> None:
        for _ in range(200):
            with journal.span("action", "threaded"):
                pass

    workers = [threading.Thread(target=burst) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert len(journal.recent()) == 100
    assert journal.open_spans() == []


# -- the file ------------------------------------------------------------------------------------


def test_with_no_path_nothing_reaches_disk(tmp_path):
    journal = Telemetry()
    journal.failure("nothing")
    assert journal.path is None
    assert current().path is None  # The process default a test sees writes nothing.
    assert list(tmp_path.iterdir()) == []


def test_the_file_gets_what_is_worth_reading_back(tmp_path):
    path = tmp_path / "telemetry" / "journal.jsonl"
    journal = Telemetry(path, surface="cli", slow_ms=20.0)
    journal.record("action", "quick", duration_ms=1.0)  # Ring only.
    journal.record("action", "slow", duration_ms=45.0)
    journal.record("cli", "project list", exit_code=0)  # Quick, but always written.
    journal.failure("broken", RuntimeError("boom"))
    written = read_journal(path)
    assert [span.name for span in written] == ["slow", "project list", "broken"]
    assert [span.surface for span in written] == ["cli"] * 3
    assert written[1].detail == {"exit_code": 0}
    assert written[2].ok is False and written[2].error_type == "RuntimeError"
    assert "boom" in (written[2].traceback or "")


def test_a_record_survives_the_round_trip(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal = Telemetry(path, slow_ms=0.0)  # Everything is worth the file, for the test.
    with journal.span("action", "steps.link", steps=2):
        journal.record("slot", "GraphScene.sync", duration_ms=30.0, signal="edges_changed")
    slot, action = read_journal(path)

    assert slot.parent == action.span_id
    assert slot.detail == {"signal": "edges_changed"} and action.detail == {"steps": 2}
    assert slot.kind == "slot" and slot.thread and slot.pid == journal.pid


def test_a_torn_last_line_is_skipped(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal = Telemetry(path)
    journal.failure("first")
    journal.close()
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"id": 2, "kind": "failure", "name": "torn"')
    assert [span.name for span in read_journal(path)] == ["first"]


def test_a_full_file_is_rotated_once(tmp_path, monkeypatch):
    path = tmp_path / "journal.jsonl"
    path.write_text("x" * 200)
    monkeypatch.setattr(telemetry_module, "ROTATE_BYTES", 100)
    journal = Telemetry(path)
    journal.failure("after rotation")
    assert (tmp_path / "journal.1.jsonl").read_text() == "x" * 200
    assert [span.name for span in read_journal(path)] == ["after rotation"]


def test_records_are_one_line_of_json_each(tmp_path):
    path = tmp_path / "journal.jsonl"
    Telemetry(path).failure("with\nnewline", traceback_text="a\nb")
    (line,) = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["error"]["traceback"] == "a\nb"


# -- logging becomes failures ----------------------------------------------------------------------


def test_a_logged_exception_becomes_a_failure_with_its_traceback(installed):
    logger = logging.getLogger("dplanner.test.telemetry")
    try:
        raise ValueError("bad value")
    except ValueError:
        logger.exception("slot %r failed", "x")
    logger.warning("merely a warning")
    logger.info("not worth a record")
    exception, warning = installed.recent()
    assert exception.kind == "failure" and exception.error_type == "ValueError"
    assert "bad value" in (exception.traceback or "") and "slot 'x' failed" in exception.name
    assert warning.detail["level"] == "WARNING" and warning.traceback is None


def test_installing_puts_the_previous_journal_back(installed):
    previous = install(Telemetry())
    assert previous is installed
    assert install(installed) is not installed
    assert current() is installed


# -- naming a listener ---------------------------------------------------------------------------


class _View:
    def refresh(self) -> None:
        pass


def test_a_slot_is_named_for_its_method_and_line():
    name = describe_slot(_View().refresh)
    assert name.startswith("_View.refresh (test_telemetry.py:")


def test_a_wrapper_is_named_for_what_it_wraps():
    view = _View()

    def on_change(*_args: object) -> None:
        view.refresh()

    on_change.__wrapped__ = view.refresh  # type: ignore[attr-defined]
    assert describe_slot(on_change).startswith("_View.refresh")
    assert describe_slot(lambda: None).startswith("test_a_wrapper_is_named_for_what_it_wraps")


def test_a_span_round_trips_through_its_record():
    span = Span(1, "cli", "step add", 5.0, "MainThread", "cli", 42, duration_ms=3.5, ok=True)
    assert Span.from_record(span.to_record()) == span
