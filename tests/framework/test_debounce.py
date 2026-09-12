"""Coalescing: a burst runs once, the newest state wins, and a test can settle it all.

Real timers here — the one place the deferred path is exercised with an event loop
actually turning (``qtbot.wait``); every other test runs in immediate mode.
"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget

from dplanner.core.telemetry import current
from dplanner.framework.debounce import Debounced, DebounceService


class _View:
    def __init__(self) -> None:
        self.rebuilds = 0

    def refresh(self) -> None:
        self.rebuilds += 1


@pytest.fixture
def host(app):
    widget = QWidget()
    yield widget
    widget.deleteLater()


def test_a_burst_of_triggers_runs_once_after_the_quiet_spell(host, qtbot):
    view = _View()
    debounced = Debounced(view.refresh, 30, parent=host)
    for _ in range(5):
        debounced.trigger()
    assert view.rebuilds == 0 and debounced.pending()
    qtbot.wait(120)
    assert view.rebuilds == 1 and not debounced.pending()


def test_zero_delay_means_once_per_event_loop_turn(host, app):
    view = _View()
    debounced = Debounced(view.refresh, 0, parent=host)
    debounced.trigger()
    debounced.trigger()
    app.processEvents()
    assert view.rebuilds == 1


def test_flush_runs_what_is_pending_and_only_that(host):
    view = _View()
    debounced = Debounced(view.refresh, 30, parent=host)
    debounced.flush()  # Nothing pending: nothing runs.
    debounced.trigger()
    debounced.flush()
    assert view.rebuilds == 1 and not debounced.pending()


def test_cancel_drops_the_pending_run(host, qtbot):
    view = _View()
    debounced = Debounced(view.refresh, 30, parent=host)
    debounced.trigger()
    debounced.cancel()
    qtbot.wait(80)
    assert view.rebuilds == 0


def test_immediate_mode_runs_inline_and_settles_what_was_pending(host):
    service = DebounceService()
    view = _View()
    debounced = Debounced(view.refresh, 30, parent=host, service=service)
    debounced.trigger()
    assert view.rebuilds == 0
    service.set_immediate(True)  # Anything pending runs first...
    assert view.rebuilds == 1 and not debounced.pending()
    debounced.trigger()  # ...and from now on every trigger runs on the spot.
    assert view.rebuilds == 2


def test_the_service_settles_and_cancels_every_live_debouncer(host):
    service = DebounceService()
    views = [_View(), _View()]
    made = [Debounced(view.refresh, 30, parent=host, service=service) for view in views]
    for debounced in made:
        debounced.trigger()
    assert len(service.pending()) == 2
    service.flush_all()
    assert [view.rebuilds for view in views] == [1, 1] and service.pending() == []
    made[0].trigger()
    service.cancel_all()
    assert service.pending() == [] and views[0].rebuilds == 1


def test_a_run_is_a_refresh_span_named_for_the_view(host, qtbot):
    current().clear()
    view = _View()
    debounced = Debounced(view.refresh, 30, parent=host)
    for _ in range(3):
        debounced.trigger()
    qtbot.wait(120)
    (span,) = [span for span in current().recent() if span.kind == "refresh"]
    assert span.name.startswith("_View.refresh (test_debounce.py:")
    assert span.detail == {"coalesced": 3, "delay_ms": 30}
    assert debounced.trigger.__wrapped__ == view.refresh  # type: ignore[attr-defined]


def test_pending_changed_says_once_when_a_burst_starts_and_once_when_it_ran(host, qtbot):
    view = _View()
    debounced = Debounced(view.refresh, 30, parent=host)
    heard: list[bool] = []
    debounced.pending_changed.connect(heard.append)
    for _ in range(5):
        debounced.trigger()
    assert heard == [True]
    qtbot.wait(120)
    assert heard == [True, False] and view.rebuilds == 1


def test_immediate_mode_settles_the_pending_state_within_the_trigger(host):
    service = DebounceService()
    service.set_immediate(True)
    debounced = Debounced(_View().refresh, 30, parent=host, service=service)
    heard: list[bool] = []
    debounced.pending_changed.connect(heard.append)
    debounced.trigger()
    assert heard == [True, False]


def test_cancel_settles_the_pending_state(host):
    debounced = Debounced(_View().refresh, 30, parent=host)
    heard: list[bool] = []
    debounced.pending_changed.connect(heard.append)
    debounced.trigger()
    debounced.cancel()
    assert heard == [True, False]


def test_an_action_that_raises_still_settles(host):
    """An indicator following the view must not stay up over a rebuild that failed."""

    def broken() -> None:
        raise RuntimeError("rebuild failed")

    debounced = Debounced(broken, 30, parent=host)
    heard: list[bool] = []
    debounced.pending_changed.connect(heard.append)
    debounced.trigger()
    with pytest.raises(RuntimeError):
        debounced.flush()
    assert heard == [True, False] and not debounced.pending()


def test_a_debouncer_whose_parent_died_is_no_longer_live(app):
    """The timer goes with the widget, and the service must not ask a dead one anything."""
    service = DebounceService()
    host = QWidget()
    debounced = Debounced(_View().refresh, 30, parent=host, service=service)
    debounced.trigger()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert service.pending() == []
    service.flush_all()  # Nothing to settle, and nothing raises.
