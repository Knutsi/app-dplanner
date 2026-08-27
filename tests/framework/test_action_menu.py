"""build_menu: one menu's verbs as a popup, whole or filtered to one submenu."""

import pytest
from PySide6.QtWidgets import QWidget

from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry, ActionSpec, MenuStructure
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
    return [a.text() if not a.isSeparator() else "|" for a in popup.actions()]


def test_a_popup_holds_one_menus_entries_with_group_separators(app, registry):
    parent = QWidget()  # Kept alive: the popup is parented to it and dies with it.
    popup = build_menu(registry, ContextService(), "View", parent)
    assert entries(popup) == ["panel", "|", "move", "close"]


def test_a_submenu_popup_holds_exactly_that_submenus_entries(app, registry):
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent, submenu="Tabs")
    assert entries(popup) == ["move", "close"]
