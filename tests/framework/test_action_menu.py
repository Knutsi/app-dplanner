"""build_menu: one menu's verbs as a popup, nested like the menu bar or filtered flat."""

import pytest
from PySide6.QtWidgets import QMenu, QWidget

from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import (
    DISABLED,
    HIDDEN,
    ActionRegistry,
    ActionSpec,
    ActionState,
    MenuStructure,
)
from dplanner.framework.context import ContextService

MENUS = MenuStructure({"View": ("panels", "tabs"), "File": ("open",)})


def spec(action_id, menu="View", group="tabs", order=50, **kwargs):
    return ActionSpec(id=action_id, label=action_id, menu=menu, group=group, order=order, **kwargs)


@pytest.fixture
def registry():
    registry = ActionRegistry(MENUS)
    registry.register(spec("panel", group="panels"))
    registry.register(spec("move", submenu="Tabs", order=10))
    registry.register(spec("close", submenu="Tabs", order=20))
    registry.register(spec("elsewhere", menu="File", group="open"))
    return registry


def entries(popup):
    """The popup's shape: separators as "|", child menus as (title, [their entries])."""
    rendered: list[object] = []
    for action in popup.actions():
        if action.isSeparator():
            rendered.append("|")
        elif action.menu() is not None:
            rendered.append((action.text(), entries(action.menu())))
        else:
            rendered.append(action.text())
    return rendered


def flat_actions(popup):
    return {a.text(): a for a in popup.actions() if not a.isSeparator()}


def test_a_popup_holds_one_menus_entries_with_group_separators(app, registry):
    parent = QWidget()  # Kept alive: the popup is parented to it and dies with it.
    popup = build_menu(registry, ContextService(), "View", parent)
    assert entries(popup) == ["panel", "|", ("Tabs", ["move", "close"])]


def test_a_submenu_popup_holds_exactly_that_submenus_entries(app, registry):
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent, submenu="Tabs")
    assert entries(popup) == ["move", "close"]


def test_a_disabled_entry_is_greyed_and_a_hidden_one_is_omitted(app, registry):
    """Same policy as the menu bar: disabled means "not right now" and stays readable;
    hidden means the capability is absent and leaves no trace."""
    registry.register(spec("greyed", group="panels", state=lambda _c: DISABLED))
    registry.register(spec("gone", group="panels", state=lambda _c: HIDDEN))
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    assert entries(popup) == ["greyed", "panel", "|", ("Tabs", ["move", "close"])]
    by_text = flat_actions(popup)
    assert not by_text["greyed"].isEnabled()
    assert by_text["panel"].isEnabled()


def test_the_child_menu_sits_at_the_first_specs_sort_position(app, registry):
    registry.register(spec("early", order=5))
    registry.register(spec("late", order=90))
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    assert entries(popup) == ["panel", "|", "early", ("Tabs", ["move", "close"]), "late"]


def test_a_submenu_whose_entries_are_all_hidden_never_appears(app):
    registry = ActionRegistry(MENUS)
    registry.register(spec("panel", group="panels"))
    registry.register(spec("move", submenu="Tabs", order=10, state=lambda _c: HIDDEN))
    registry.register(spec("close", submenu="Tabs", order=20, state=lambda _c: HIDDEN))
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    assert entries(popup) == ["panel"]


def test_a_hidden_submenu_entry_is_omitted_but_the_menu_survives(app):
    registry = ActionRegistry(MENUS)
    registry.register(spec("move", submenu="Tabs", order=10, state=lambda _c: HIDDEN))
    registry.register(spec("close", submenu="Tabs", order=20))
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    assert entries(popup) == [("Tabs", ["close"])]


def test_a_child_entry_is_greyed_and_checkable_like_a_flat_one(app):
    registry = ActionRegistry(MENUS)
    registry.register(spec("move", submenu="Tabs", order=10, state=lambda _c: DISABLED))
    registry.register(
        spec("close", submenu="Tabs", order=20, state=lambda _c: ActionState(checked=True))
    )
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    child = popup.actions()[0].menu()
    assert isinstance(child, QMenu)
    by_text = {a.text(): a for a in child.actions()}
    assert not by_text["move"].isEnabled()
    assert by_text["close"].isCheckable() and by_text["close"].isChecked()


def test_triggering_a_child_entry_runs_the_action(app):
    ran = []
    registry = ActionRegistry(MENUS)
    registry.register(spec("move", submenu="Tabs", order=10, run=lambda _c: ran.append("move")))
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    child = popup.actions()[0].menu()
    assert isinstance(child, QMenu)
    child.actions()[0].trigger()
    assert ran == ["move"]
