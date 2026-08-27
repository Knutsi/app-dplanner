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
    # "canvas" is the graph editor's own view verbs — framing it is not the application's
    # font zoom, which is what "zoom" means here.
    "View": ("panels", "zoom", "canvas", "theme", "window"),
    # A noun menu like "Project" and "Step" below: it is what the tab bar's right-click
    # renders, so the two can never be a hand-maintained copy of each other. "move" is where
    # a tab goes — which is also how the window splits — and "close" is what goes away.
    "Tab": ("move", "close"),
    # The planner's own vocabulary. "Project" is what the index tree's right-click menu
    # renders and "Step" is what the graph canvas's does — see framework/action_menu.py.
    # "link" holds the two-step verbs: the canvas publishes both ends into the selection
    # scope on a drop and runs the same action the menu does.
    "Project": ("edit", "open"),
    # "open" is a surface about the selection — the Step-side mirror of Project's
    # "Show Order". "navigate" is where the canvas's movement verbs live: they select
    # rather than change, so they belong beside the step verbs but not among them.
    "Step": ("edit", "link", "open", "navigate"),
    "Tools": ("agent",),
    "Debug": ("llm",),
    "Help": ("about",),
}
