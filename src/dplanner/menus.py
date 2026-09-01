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
    # "project" (New/Open Project) and "library" (New/Open Project Library, Reload) come
    # from the library module and the watcher; "save"/"branch" from sync; "window" from
    # the app shell and the settings dialog. "export" holds the Export submenu — one entry
    # per feature that can write itself out (the order list's CSV today).
    "File": ("project", "library", "save", "branch", "export", "window"),
    "Edit": ("history",),
    # "palette" is the command palette alone — the way to *any* verb, set off from the
    # panel toggles below it. "areas" is the whole-side collapse switches, ahead of the
    # per-panel checkmarks in "panels". "canvas" is the graph editor's own view verbs —
    # framing it is not the application's font zoom, which is what "zoom" means here.
    # "tabs" holds the Tabs submenu, which is also what the tab bar's right-click renders
    # (build_menu's submenu filter), so the two can never be a hand-maintained copy.
    "View": ("palette", "areas", "panels", "zoom", "canvas", "theme", "tabs", "window"),
    # The planner's own vocabulary. "Project" is what the index tree's right-click menu
    # renders and "Step" is what the graph canvas's does — see framework/action_menu.py.
    # "link" holds the two-step verbs: the canvas publishes both ends into the selection
    # scope on a drop and runs the same action the menu does.
    # "documents" is the spec module's: what a project carries beside its steps.
    # "tests" is the test run's two verbs — a run belongs to a project, spans its
    # steps, and there is at most one open at a time.
    "Project": ("edit", "canvas", "documents", "tests", "open"),
    # "edit" holds the New submenu — one entry per *kind* a step can be born as, named by
    # the composition root (project_editor/kinds.py), beside Rename and Delete.
    # "open" is a surface about the selection — the Step-side mirror of Project's
    # "Show Order". "navigate" is where the canvas's movement verbs live: they select
    # rather than change, so they belong beside the step verbs but not among them.
    # "classify" is the band of child menus that say what a step *is* and how it is doing:
    # Type (one independent checkable toggle per type-ish aspect — never a radio group, a
    # step can be several things at once, and each aspect's tab follows its toggle), then
    # Status, then Test. They are one group because a rule between two adjacent child menus
    # separates nothing: the names already do. A child menu sits at its first entry's order,
    # which is why the three claim bands of it — Type the 10s, Status the 200s, Test the
    # 300s — and ``order`` still only ranks inside this one group.
    # "test_result" feeds that same Test submenu with what a run *recorded*, so the rule
    # between what a test is and what it did is drawn inside the child menu — and, holding
    # no top-level entry of its own, the group adds no rule to the menu itself.
    # "docs" is Compile Docs: an LLM writing a feature's or a milestone's document from
    # the documentation it gathers. Its own group rather than "agent"'s, because launching
    # a coding agent in a terminal and filling one field are not two of a kind.
    "Step": ("edit", "link", "classify", "test_result", "agent", "docs", "open", "navigate"),
    "Tools": ("agent",),
    "Debug": ("llm",),
    "Help": ("about",),
}
