"""The tab host: what it promises about activities, and about the context.

Written against the behaviour that existed before tab groups, so the refactor that introduced
them had something to be measured against. Every test here builds a `TabHost` standalone —
no window, no session — because that is what the host promises it can be.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    ContextNode,
    ContextService,
    activity_uri,
    entity_uri,
)
from dplanner.framework.tabs import TabHost


class FakeActivity(ActivityBase):
    """The smallest thing that satisfies Activity, and counts what was done to it."""

    def __init__(self, target: str | None = None, kind: str = "thing") -> None:
        self._target = target
        self._kind = kind
        self.widget: QWidget = QLabel(f"{kind}:{target}")
        self.activated = 0
        self.deactivated = 0
        self.closed = 0

    @property
    def uri(self) -> str:
        return activity_uri(self._kind, self._target)

    @property
    def title(self) -> str:
        return f"{self._kind} {self._target or ''}".strip()

    def on_activated(self) -> None:
        self.activated += 1

    def on_deactivated(self) -> None:
        self.deactivated += 1

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def context():
    return ContextService()


@pytest.fixture
def host(app, context):
    made = TabHost(context)
    made.register_factory("thing", lambda target: FakeActivity(target))
    return made


def announcements(host):
    seen: list[str | None] = []
    host.activity_changed.connect(lambda a: seen.append(a.uri if a else None))
    return seen


# -- opening and dedupe ------------------------------------------------------------------------


def test_opening_twice_focuses_the_same_tab(host):
    first = host.open("thing", "a")
    assert host.open("thing", "a") is first
    assert len(host.activities()) == 1


def test_a_factory_that_normalises_its_target_still_dedupes(app, context):
    """The second check in open(): a singleton ignores its target, so the pre-factory
    lookup misses and one tab per URI has to hold anyway."""
    host = TabHost(context)
    host.register_factory("only", lambda _target: FakeActivity(None, "only"))
    first = host.open("only", "a")
    second = host.open("only", "b")
    assert second is first
    assert len(host.activities()) == 1


def test_activities_come_back_in_the_order_they_opened(host):
    host.open("thing", "a")
    host.open("thing", "b")
    assert [a.title for a in host.activities()] == ["thing a", "thing b"]


def test_an_unregistered_kind_is_an_error(host):
    with pytest.raises(KeyError):
        host.open("nothing")


# -- the activation lifecycle ------------------------------------------------------------------


def test_opening_activates_and_announces(host):
    seen = announcements(host)
    first = host.open("thing", "a")
    assert first.activated == 1
    assert seen == [first.uri]


def test_switching_deactivates_the_old_and_activates_the_new(host):
    first = host.open("thing", "a")
    seen = announcements(host)
    second = host.open("thing", "b")
    assert (first.deactivated, second.activated) == (1, 1)
    assert seen == [second.uri]


def test_the_activity_scope_follows_the_current_tab(host, context):
    """What every action's target resolves through, so it is the thing that must be right."""

    class Publishing(FakeActivity):
        def on_activated(self) -> None:
            super().on_activated()
            context.set_scope(
                SCOPE_ACTIVITY,
                (ContextNode(self.uri, (("entity", entity_uri("thing", self._target or "")),)),),
            )

    host.register_factory("pub", lambda target: Publishing(target, "pub"))
    host.open("pub", "a")
    assert context.current().focus_entity("thing") == "a"
    host.open("pub", "b")
    assert context.current().focus_entity("thing") == "b"


def test_closing_a_tab_closes_its_activity(host):
    first = host.open("thing", "a")
    assert host.close_activity(first) is True
    assert first.closed == 1
    assert host.activities() == []
    assert host.close_activity(first) is False


def test_closing_the_current_tab_activates_what_is_left(host):
    first = host.open("thing", "a")
    host.open("thing", "b")
    host.close_current()
    assert host.current_activity() is first


def test_closing_the_last_tab_announces_nothing_current(host):
    host.open("thing", "a")
    seen = announcements(host)
    host.close_current()
    assert seen == [None]
    assert host.current_activity() is None


# -- reordering is not a switch ------------------------------------------------------------------


def test_dragging_a_tab_into_a_new_position_is_not_an_activation(host):
    """`setMovable(True)` means a drag reorders the bar, and Qt reports that as
    `currentChanged` with the *same* page still current. Treating it as a switch deactivates
    and reactivates the activity the user is looking at, seals their undo burst and flushes
    autosave — for a change that changed nothing."""
    first = host.open("thing", "a")
    host.open("thing", "b")
    host.open("thing", "c")
    host.focus(first)

    seen = announcements(host)
    before = (first.activated, first.deactivated)
    host.reorder_current(1)

    assert seen == []
    assert (first.activated, first.deactivated) == before
    assert host.current_activity() is first


# -- groups --------------------------------------------------------------------------------------


def press(app, widget):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    app.sendEvent(
        widget,
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(1.0, 1.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_a_host_starts_with_one_group(host):
    assert host.group_count() == 1


def test_moving_right_creates_a_group_and_carries_the_page(host):
    first = host.open("thing", "a")
    second = host.open("thing", "b")
    host.move_current_right()

    assert host.group_count() == 2
    # The page survived the move: removeTab leaves it parented to the old group, so a
    # teardown in the wrong order would have taken it.
    assert second.widget.parent() is not None
    assert second.closed == 0
    assert {a.uri for a in host.activities()} == {first.uri, second.uri}
    assert host.current_activity() is second


def test_moving_the_last_tab_back_removes_the_group(host):
    host.open("thing", "a")
    host.open("thing", "b")
    host.move_current_right()
    assert host.group_count() == 2

    host.move_current_left()
    assert host.group_count() == 1
    assert len(host.activities()) == 2


def test_moving_right_is_refused_when_it_would_change_nothing(host):
    host.open("thing", "a")
    assert not host.can_move_right()
    host.move_current_right()
    assert host.group_count() == 1


def test_left_never_creates_a_group(host):
    host.open("thing", "a")
    host.open("thing", "b")
    assert not host.can_move_left()
    host.move_current_left()
    assert host.group_count() == 1


def test_there_are_never_more_than_three_groups(host):
    """Getting a third pane takes deliberate work, because a group will not create another
    by emptying itself: you have to send two tabs right, then send one of those on."""
    opened = [host.open("thing", name) for name in "abcd"]
    host.move_current_right()  # d into a new second group
    host.focus(opened[2])
    host.move_current_right()  # c joins it, so the second group has two
    host.move_current_right()  # and now one of those can go on into a third
    assert host.group_count() == 3

    for _ in range(5):
        host.move_current_right()
    assert host.group_count() == 3


def test_a_move_announces_once_even_though_the_activity_is_unchanged(host):
    host.open("thing", "a")
    second = host.open("thing", "b")
    seen = announcements(host)
    host.move_current_right()

    # The activity did not change; its group did, and that is a change to what the user is
    # doing — so it announces, exactly once.
    assert seen == [second.uri]


def test_opening_something_already_open_elsewhere_focuses_its_group(host):
    first = host.open("thing", "a")
    host.open("thing", "b")
    host.move_current_right()
    assert host.group_count() == 2

    assert host.open("thing", "a") is first
    assert host.current_activity() is first
    assert host.group_count() == 2


def test_closing_a_tab_in_a_background_group_does_not_steal_the_user(host):
    """`_close_orphan_tabs` does this on every structural change; it must not move anybody."""
    background = host.open("thing", "a")
    front = host.open("thing", "b")
    host.move_current_right()
    assert host.current_activity() is front

    host.close_activity(background)
    assert host.current_activity() is front
    assert host.group_count() == 1


# -- the watcher ---------------------------------------------------------------------------------


def test_clicking_a_widget_in_another_group_activates_it(app, host, context):
    first = host.open("thing", "a")
    second = host.open("thing", "b")
    host.move_current_right()
    assert host.current_activity() is second

    press(app, first.widget)
    assert host.current_activity() is first


def test_clicking_something_that_takes_no_focus_still_activates(app, host):
    """The reason the filter exists at all: a caption or a heading never takes focus, so
    `focusChanged` would never fire for it."""
    from PySide6.QtWidgets import QLabel

    first = host.open("thing", "a")
    second = host.open("thing", "b")
    host.move_current_right()

    label = QLabel("a caption", first.widget)
    assert label.focusPolicy() == Qt.FocusPolicy.NoFocus
    press(app, label)
    assert host.current_activity() is first
    assert second is not host.current_activity()


def test_clicking_outside_every_group_changes_nothing(app, host):
    from PySide6.QtWidgets import QWidget

    host.open("thing", "a")
    second = host.open("thing", "b")
    host.move_current_right()

    stray = QWidget()
    press(app, stray)
    assert host.current_activity() is second


def test_a_disposed_host_stops_watching(app, context):
    """A host outlives its window when a workspace is reopened. One that kept filtering
    would answer for a window that has gone — and in a test suite they would pile up."""
    first = TabHost(context)
    first.register_factory("thing", lambda target: FakeActivity(target))
    left = first.open("thing", "a")
    first.open("thing", "b")
    first.move_current_right()

    seen = announcements(first)
    first.dispose()
    press(app, left.widget)
    assert seen == []
