"""The menu bar: QActions created once and restated, and the containers that hold them.

It renders the same registry ``action_menu`` does, so the two are tested against the same
facts — a child menu per title, a rule where the group changes, and no rule for a group
that only feeds a child menu. A menu bar that disagreed with a right-click would be the
one thing four presenters of one registry exist to prevent.
"""

from typing import NamedTuple

import pytest
from PySide6.QtWidgets import QMainWindow

from dplanner.core.telemetry import current
from dplanner.framework.action_registry import (
    ActionRegistry,
    ActionSpec,
    ActionState,
    DataMenuSpec,
    MenuStructure,
)
from dplanner.framework.context import ContextService
from dplanner.framework.menubar import DynamicMenuBar

MENUS = MenuStructure({"Step": ("edit", "classify", "result", "open")})
HIDDEN = ActionState(visible=False, enabled=False)

SPECS = (
    ("rename", "edit", None, 10),
    ("add test", "classify", "Test", 10),
    ("archive test", "classify", "Test", 20),
    ("mark ok", "result", "Test", 10),
    ("details", "open", None, 10),
)


class Bar(NamedTuple):
    """Everything a test needs to hold: the menus are children of the window, and the
    DynamicMenuBar owns the QActions, so both must outlive the assertions."""

    window: QMainWindow
    menubar: DynamicMenuBar
    registry: ActionRegistry
    context: ContextService


def build(app, specs=SPECS, states=None, runs=None) -> Bar:
    """A menu bar over these specs."""
    registry = ActionRegistry(MENUS)
    for action_id, group, submenu, order in specs:
        registry.register(
            ActionSpec(
                id=action_id,
                label=action_id,
                menu="Step",
                group=group,
                submenu=submenu,
                order=order,
                state=(states or {}).get(action_id, lambda _c: ActionState()),
                run=(runs or {}).get(action_id, lambda _c: None),
            )
        )

    window = QMainWindow()
    context = ContextService()
    return Bar(window, DynamicMenuBar(window, registry, context), registry, context)


def entries(menu):
    """The menu's shape: visible separators as "|", child menus as (title, [entries])."""
    rendered: list[object] = []
    for action in menu.actions():
        if not action.isVisible():
            continue
        if action.isSeparator():
            rendered.append("|")
        elif action.menu() is not None:
            rendered.append((action.text(), entries(action.menu())))
        else:
            rendered.append(action.text())
    return rendered


def step_menu(bar: Bar):
    return next(a.menu() for a in bar.window.menuBar().actions() if a.text() == "&Step")


def test_two_groups_feeding_one_submenu_share_it_with_a_rule_inside(app):
    bar = build(app)
    assert entries(step_menu(bar)) == [
        "rename",
        "|",
        ("Test", ["add test", "archive test", "|", "mark ok"]),
        "|",
        "details",
    ]


def test_the_rule_inside_a_child_menu_goes_when_one_side_does(app):
    """The same never-leading, never-dangling rule the menu itself follows: a group with
    nothing visible in this container leaves no line behind."""
    bar = build(app, states={"mark ok": lambda _c: HIDDEN})
    assert entries(step_menu(bar)) == [
        "rename",
        "|",
        ("Test", ["add test", "archive test"]),
        "|",
        "details",
    ]


def test_a_child_menu_with_nothing_visible_disappears_with_its_rules(app):
    bar = build(
        app,
        states={
            "add test": lambda _c: HIDDEN,
            "archive test": lambda _c: HIDDEN,
            "mark ok": lambda _c: HIDDEN,
        },
    )
    assert entries(step_menu(bar)) == ["rename", "|", "details"]


def test_the_menu_bar_and_a_right_click_render_the_same_menu(app):
    """One registry, two presenters, one answer — the whole reason build_menu exists."""
    from dplanner.framework.action_menu import build_menu

    bar = build(app)
    popup = build_menu(bar.registry, bar.context, "Step", bar.window)
    assert entries(popup) == entries(step_menu(bar))


def test_a_data_child_menu_sits_in_its_group_with_the_menus_own_rules(app):
    """Entries that are data — a saved layout, a live run — cannot be specs, so the child
    menu carries a fill instead, and its placement is still the one table's business:
    same group, same sort key, same separators as any registered action."""
    bar = build(app)
    bar.registry.register_data_menu(
        DataMenuSpec(
            id="recent", menu="Step", group="result", title="Recent", fill=lambda _menu: None
        )
    )
    assert entries(step_menu(bar)) == [
        "rename",
        "|",
        ("Test", ["add test", "archive test", "|", "mark ok"]),
        "|",
        ("Recent", []),
        "|",
        "details",
    ]


def test_a_data_child_menu_is_rebuilt_every_time_it_opens(app):
    rows = ["first"]
    bar = build(app)

    def fill(menu):
        for row in rows:
            menu.addAction(row)

    bar.registry.register_data_menu(
        DataMenuSpec(id="recent", menu="Step", group="result", title="Recent", fill=fill)
    )
    assert entries(bar.menubar.data_menu("recent")) == ["first"]
    rows.append("second")
    assert entries(bar.menubar.data_menu("recent")) == ["first", "second"]


def test_a_data_menu_is_validated_and_deduplicated_like_any_spec(app):
    spec = DataMenuSpec(id="recent", menu="Step", group="result", title="R", fill=lambda _m: None)
    registry = ActionRegistry(MENUS)
    registry.register_data_menu(spec)
    with pytest.raises(ValueError):
        registry.register_data_menu(spec)
    with pytest.raises(ValueError):
        registry.register_data_menu(
            DataMenuSpec(id="other", menu="Nope", group="result", title="R", fill=lambda _m: None)
        )


def test_a_triggered_entry_runs_through_the_registry_gate(app):
    """The bar's QAction is one presenter among several, so it takes the same path they
    do: ``ActionRegistry.run``, which re-asks the state at trigger time. A state that
    changed since the bar last refreshed is honoured, and the run is timed like any other."""
    allowed = [True]
    ran = []
    bar = build(
        app,
        states={"rename": lambda _c: ActionState(enabled=allowed[0])},
        runs={"rename": lambda _c: ran.append("rename")},
    )
    current().clear()
    bar.menubar.action("rename").trigger()
    assert ran == ["rename"]
    assert [span.name for span in current().recent() if span.kind == "action"] == ["rename"]

    allowed[0] = False  # Nothing re-emits the context, so the QAction still looks enabled.
    bar.menubar.action("rename").trigger()
    assert ran == ["rename"]
