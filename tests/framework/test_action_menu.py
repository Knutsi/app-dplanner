"""build_menu: one menu's verbs as a popup, nested like the menu bar or filtered flat."""

import pytest
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
    DataMenuSpec,
    MenuStructure,
)
from dplanner.framework.context import ContextService

MENUS = MenuStructure({"View": ("panels", "tabs"), "File": ("open",)})
HIDDEN = ActionState(visible=False, enabled=False)


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


def test_a_data_child_menu_sits_in_the_popup_and_fills_when_it_opens(app, registry):
    """The bar's rule in the popup: placed by the same key, cleared and refilled on open —
    so a right-click offers the same live list the menu does, never a copy of it."""
    rows = ["first"]

    def fill(child):
        for row in rows:
            child.addAction(row)

    registry.register_data_menu(
        DataMenuSpec(id="recent", menu="View", group="tabs", title="Recent", order=15, fill=fill)
    )
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    assert entries(popup) == ["panel", "|", ("Tabs", ["move", "close"]), ("Recent", [])]
    recent = next(a.menu() for a in popup.actions() if a.text() == "Recent")
    assert isinstance(recent, QMenu)
    recent.aboutToShow.emit()
    assert entries(recent) == ["first"]
    rows.append("second")
    recent.aboutToShow.emit()
    assert entries(recent) == ["first", "second"]
    # A child of the menu itself: a named-submenu render is that submenu, flat, and no more.
    flat = build_menu(registry, ContextService(), "View", parent, submenu="Tabs")
    assert entries(flat) == ["move", "close"]


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


# -- one submenu per title, groups separating inside it ----------------------------------------

NESTED = MenuStructure({"Step": ("edit", "classify", "result", "open")})


def nested_registry():
    """Two groups feeding one "Test" child menu, with flat entries either side of it."""
    registry = ActionRegistry(NESTED)
    for action_id, group, submenu, order in (
        ("rename", "edit", None, 10),
        ("add test", "classify", "Test", 10),
        ("archive test", "classify", "Test", 20),
        ("mark ok", "result", "Test", 10),
        ("details", "open", None, 10),
    ):
        registry.register(
            ActionSpec(
                id=action_id,
                label=action_id,
                menu="Step",
                group=group,
                submenu=submenu,
                order=order,
            )
        )
    return registry


def test_two_groups_feeding_one_submenu_share_it_with_a_rule_inside(app):
    """What a test *is* and what it *did* are two groups and one child menu. Keying the
    child by (group, title) rendered two menus both called Test, which is what a person
    saw before this: the same name twice with a rule between them."""
    parent = QWidget()
    popup = build_menu(nested_registry(), ContextService(), "Step", parent)
    assert entries(popup) == [
        "rename",
        "|",
        ("Test", ["add test", "archive test", "|", "mark ok"]),
        "|",
        "details",
    ]


def test_a_group_that_only_feeds_a_submenu_draws_no_rule_of_its_own(app):
    """The child menu sits at its first group's position and later groups land inside it,
    so the menu itself gains no line for a group holding no entry of its own."""
    parent = QWidget()
    popup = build_menu(nested_registry(), ContextService(), "Step", parent)
    assert [e for e in entries(popup) if e == "|"] == ["|", "|"]


def test_a_submenu_popup_gathers_every_group_that_feeds_it(app):
    """Rendered flat — a toolbar's dropdown, the tab bar's right-click — it is the same
    list the child menu holds, rules and all."""
    parent = QWidget()
    popup = build_menu(nested_registry(), ContextService(), "Step", parent, submenu="Test")
    assert entries(popup) == ["add test", "archive test", "|", "mark ok"]


def test_an_entry_wears_the_glyph_its_spec_carries(app, registry):
    """A verb may name a glyph; the pop-up presenters paint it in their own ink, which is
    why it is theirs and not the menu bar's — they are built fresh on every open."""
    inks: list[QColor] = []

    def glyph(colour: QColor) -> QIcon:
        inks.append(colour)
        pixmap = QPixmap(16, 16)
        pixmap.fill(colour)
        return QIcon(pixmap)

    registry.register(spec("glyphed", group="panels", order=10, icon=glyph))
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    by_text = flat_actions(popup)
    assert not by_text["glyphed"].icon().isNull()
    assert by_text["panel"].icon().isNull()
    assert inks and inks[0] == popup.palette().text().color()


def test_a_submenu_path_nests_in_the_popup_as_in_the_bar(app, registry):
    registry.register(spec("rescue", submenu="Tabs ▸ More", order=30))
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    assert entries(popup) == ["panel", "|", ("Tabs", ["move", "close", ("More", ["rescue"])])]


def test_a_nested_child_is_its_parents_entry_for_the_rule_inside(app):
    """A nested child created from one group and entries from another get the rule between
    them inside the parent child, as any two entries of it would."""
    registry = ActionRegistry(MENUS)
    registry.register(spec("other", group="panels", submenu="Tabs ▸ More"))
    registry.register(spec("panel", group="panels"))
    registry.register(spec("move", submenu="Tabs", order=10))
    parent = QWidget()
    popup = build_menu(registry, ContextService(), "View", parent)
    assert entries(popup) == [("Tabs", [("More", ["other"]), "|", "move"]), "panel"]
