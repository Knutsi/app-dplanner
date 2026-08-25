"""The menu bar's shape: which menus exist and what groups they hold, in order.

This is application vocabulary, not framework machinery, so it lives here rather than in
:mod:`dplanner.framework.action_registry`. The registry validates every registration
against this table, so a typo in a module's ``menu`` or ``group`` fails at startup with the
offending id, not silently at the bottom of the wrong menu.

Groups are what let modules place actions without coordinating. A module names a group; the
registry sorts within it and draws the separators between groups automatically. That is why
``ActionSpec.order`` only ranks inside one group and no global numbering scheme is needed.

**Add a group rather than smuggling structure into ``order``.** If two of your actions want
a separator between them, they belong to two groups.
"""

from typing import Final

MENU_STRUCTURE: Final[dict[str, tuple[str, ...]]] = {
    # "open" and "save"/"branch" come from the workspaces and sync modules; "window" from
    # the app shell and the settings dialog.
    "File": ("open", "save", "branch", "export", "window"),
    "Edit": ("history", "find"),
    "View": ("panels", "zoom", "theme", "window"),
    # The planner's own vocabulary. This is also what the tree's right-click menu renders —
    # see framework/action_menu.py.
    "Task": ("edit", "status", "open"),
    "Tools": ("run",),
    "Debug": ("llm",),
    "Help": ("about",),
}
