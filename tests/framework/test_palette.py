"""The command palette: it lists verbs, and says where each one lives."""

from PySide6.QtWidgets import QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionSpec, MenuStructure
from dplanner.framework.context import ContextService
from dplanner.framework.list_rows import DETAIL_ROLE, TRAILING_ROLE
from dplanner.framework.palette import CommandPalette

MENUS = MenuStructure({"File": ("open",), "Graph": ("arrange",)})


def listed(palette):
    return [palette._list.item(row).text() for row in range(palette._list.count())]


def row(palette, label):
    return next(
        palette._list.item(i)
        for i in range(palette._list.count())
        if palette._list.item(i).text() == label
    )


def built(registry, parent, query=""):
    palette = CommandPalette(registry, ContextService(), parent)
    palette._refilter(query)
    return palette


def test_a_verbs_second_menu_placement_is_not_listed_twice(app):
    registry = ActionRegistry(MENUS)
    registry.register(ActionSpec(id="a.open", label="Open &Thing", menu="File", group="open"))
    registry.register(
        ActionSpec(id="a.open_here", label="Open &Thing", menu="File", group="open", palette=False)
    )

    parent = QWidget()  # Kept alive: the palette is parented to it and dies with it.
    palette = CommandPalette(registry, ContextService(), parent)
    assert listed(palette) == ["Open Thing"]


def test_a_row_carries_its_menu_path_and_its_shortcut(app):
    """A submenu entry's label says nothing on its own; the path under it does."""
    registry = ActionRegistry(MENUS)
    registry.register(
        ActionSpec(
            id="canvas.divide_vertical",
            label="&Vertical",
            menu="Graph",
            group="arrange",
            submenu="Divide",
            shortcut="Ctrl+D",
        )
    )
    registry.register(ActionSpec(id="a.open", label="Open", menu="File", group="open"))

    parent = QWidget()
    palette = built(registry, parent)
    assert row(palette, "Vertical").data(DETAIL_ROLE) == "Graph ▸ Divide"
    assert row(palette, "Vertical").data(TRAILING_ROLE) == "Ctrl+D"
    assert row(palette, "Open").data(DETAIL_ROLE) == "File"  # No submenu, no arrow.


def test_the_path_is_searchable_and_a_label_match_still_wins(app):
    registry = ActionRegistry(MENUS)
    registry.register(
        ActionSpec(
            id="canvas.divide_vertical",
            label="&Vertical",
            menu="Graph",
            group="arrange",
            submenu="Divide",
        )
    )
    registry.register(
        ActionSpec(
            id="canvas.divide_all",
            label="&Divide Everything",
            menu="Graph",
            group="arrange",
        )
    )

    parent = QWidget()
    palette = built(registry, parent, "divide vertical")
    assert listed(palette) == ["Vertical"]  # Found only through its path.
    palette._refilter("divide")
    assert listed(palette)[0] == "Divide Everything"  # A name beats a filing.


def test_a_nested_submenus_row_prints_the_whole_path(app):
    registry = ActionRegistry(MENUS)
    registry.register(
        ActionSpec(id="a.deep", label="Deep", menu="Graph", group="arrange", submenu="Sort ▸ More")
    )
    parent = QWidget()
    palette = built(registry, parent)
    assert row(palette, "Deep").data(DETAIL_ROLE) == "Graph ▸ Sort ▸ More"
