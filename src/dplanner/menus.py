"""The menu bar's shape: which menus exist and what groups they hold, in order.

This is application vocabulary, not framework machinery, so it lives here rather than in
:mod:`dplanner.framework.action_registry`. The registry validates every registration
against this table, so a typo in a module's ``menu`` or ``group`` fails at startup with the
offending id, not silently at the bottom of the wrong menu.

Groups are what let modules place actions without coordinating. A module names a group; the
registry sorts within it and draws the separators between groups automatically. That is why
``ActionSpec.order`` only ranks inside one group and no global numbering scheme is needed.

**Add a group rather than smuggling structure into ``order``.** If two of your actions want
a separator between them, they belong to two groups — and adding one is this one line, so
there are deliberately no groups here that nothing registers into. A group naming a feature
that does not exist is vocabulary that lies, and the next person goes looking for the action.
"""

from typing import Final

MENU_STRUCTURE: Final[dict[str, tuple[str, ...]]] = {
    # "open" and "save"/"branch" come from the workspaces and sync modules; "window" from
    # the app shell and the settings dialog.
    "File": ("open", "product", "save", "branch", "window"),
    "Edit": ("history",),
    "View": ("panels", "zoom", "theme", "window"),
    # The planner's own vocabulary. "Project" is also what the index tree's right-click
    # menu renders — see framework/action_menu.py. There is deliberately no "Step" menu
    # yet: steps have no GUI surface until the graph editor, and an empty menu is worse
    # than no menu.
    "Project": ("edit", "open"),
    "Tools": ("agent",),
    "Debug": ("llm",),
    "Help": ("about",),
}
