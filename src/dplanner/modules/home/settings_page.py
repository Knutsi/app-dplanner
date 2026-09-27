"""The "Home" settings page: whether Home shows its garden.

A preference, so GLOBAL scope — somebody who does not want a moving garden does not want it
in any library. The garden's own close button writes the same key, and this page is the way
back. Both announce through the module's ``garden_changed`` so an open Home tab follows at
once rather than on its next showing.
"""

from PySide6.QtWidgets import QCheckBox, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.settings_registry import settings_page
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import block, captioned

MODULE_ID = "home"
GARDEN_KEY = "garden"

GARDEN_HINT = (
    "The strip at the foot of Home, where an agent's rain makes the plan bloom. It moves"
    " only while Home is on screen."
)


def garden_wanted() -> bool:
    """On unless the person turned it off: it is what tells a newcomer what DPlanner does."""
    return bool(get_global(MODULE_ID, GARDEN_KEY, True))


def want_garden(on: bool, changed: Signal[()]) -> None:
    set_global(MODULE_ID, GARDEN_KEY, on)
    changed.emit()


def build_page(parent: QWidget | None, changed: Signal[()]) -> QWidget:
    page, layout = settings_page(parent)
    page.setObjectName("HomeSettingsPage")

    garden_box = QCheckBox("Show the garden", page)
    garden_box.setObjectName("GardenBox")
    garden_box.setChecked(garden_wanted())
    garden_box.toggled.connect(lambda on: want_garden(bool(on), changed))
    # The ✕ on the garden writes the same key while this page may be open.
    unsubscribe = changed.connect(lambda: garden_box.setChecked(garden_wanted()))
    page.destroyed.connect(lambda: unsubscribe())
    block(layout, captioned("Garden", page, GARDEN_HINT), garden_box)
    layout.addStretch(1)
    return page
