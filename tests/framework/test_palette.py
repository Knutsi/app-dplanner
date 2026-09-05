"""The command palette: it lists verbs, not menu placements."""

from PySide6.QtWidgets import QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionSpec, MenuStructure
from dplanner.framework.context import ContextService
from dplanner.framework.palette import CommandPalette

MENUS = MenuStructure({"File": ("open",)})


def listed(palette):
    return [palette._list.item(row).text() for row in range(palette._list.count())]


def test_a_verbs_second_menu_placement_is_not_listed_twice(app):
    registry = ActionRegistry(MENUS)
    registry.register(ActionSpec(id="a.open", label="Open &Thing", menu="File", group="open"))
    registry.register(
        ActionSpec(id="a.open_here", label="Open &Thing", menu="File", group="open", palette=False)
    )

    parent = QWidget()  # Kept alive: the palette is parented to it and dies with it.
    palette = CommandPalette(registry, ContextService(), parent)
    assert listed(palette) == ["Open Thing"]
