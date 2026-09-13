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
    # "project" (New Project, Open Projects) comes from the projects module, "library"
    # (New/Open Project Library, Reload) from the library module and the watcher;
    # "save"/"branch" from sync; "window" from
    # the app shell and the settings dialog. "export" holds the Export submenu — one entry
    # per feature that can write itself out: the order list's and the milestones' CSVs,
    # the plan's report as HTML and PDF, its tables as a workbook.
    "File": ("project", "library", "save", "branch", "export", "window"),
    # "history" is the app shell's Undo/Redo. "clipboard" and "selection" are the graph's:
    # Cut, Copy, Paste, Duplicate and Delete's second seat (its home is Step, which every
    # right-click renders), then Select All — registered by project_editor because the step
    # graph is the one surface with a clipboard representation. ARCHITECTURE.md's *Edit
    # verbs belong to the surface whose things they act on* has the reasoning.
    "Edit": ("history", "clipboard", "selection"),
    # "palette" is the command palette alone — the way to *any* verb, set off from the
    # panel toggles below it. "areas" is the whole-side collapse switches, ahead of the
    # per-panel checkmarks in "panels". "theme_system" and "theme" both feed the Theme
    # child menu — *System theme*, then every provider's themes — and the rule between
    # them, drawn inside it, parts what follows the desktop from what is picked; the child
    # sits at "theme_system"'s position and "theme" adds no rule to View itself, the shape
    # Step's "test_result" has. "tabs" holds the Tabs submenu, which is also what the tab
    # bar's right-click renders (build_menu's submenu filter), so the two can never be a
    # hand-maintained copy. "milestone_colors" is the Milestone Colours child menu, a
    # *sibling* of Theme and never inside it: what it picks is the project's colour map, not
    # this user's appearance, and an entry nested under Theme would read as a theme. It is
    # the one project fact in this menu, and it earns the place because it is a choice about
    # how the window looks — greyed with its reason when no project is open.
    #
    # **View is about the window.** The graph editor's own verbs used to sit here in a
    # "canvas" group, which made View half window and half drawing surface and left the
    # graph with no home of its own; they are the Graph menu below now.
    "View": (
        "palette",
        "areas",
        "panels",
        "zoom",
        "theme_system",
        "theme",
        "milestone_colors",
        "tabs",
        "window",
    ),
    # The planner's own vocabulary. "Project" is what the index tree's right-click menu
    # renders and "Step" is what the graph canvas's does — see framework/action_menu.py.
    # "link" holds the two-step verbs: the canvas publishes both ends into the selection
    # scope on a drop and runs the same action the menu does.
    # "documents" is the spec module's: what a project carries beside its steps;
    # "features" the feature module's: the catalogue of what it delivers, placed or not.
    # "tests" is the test run's two verbs — a run belongs to a project, spans its
    # steps, and there is at most one open at a time.
    "Project": ("edit", "documents", "features", "tests", "open"),
    # The canvas the plan is drawn on: how it is arranged and how it is looked at. Every
    # verb here steers the graph editor and nothing else, which is what makes it a menu
    # rather than a group inside View — and what tells the next person where to add one.
    # "arrange" is the Sort, Layout and Divide child menus: three ways of moving cards
    # about, from the wholesale to the one cut at a time. "regions" is the Region submenu —
    # the titled areas drawn behind the graph, which the canvas's own right-click renders
    # over one. "look" is what is drawn without moving anything: framing, the marks, the
    # grid and the ground — the band the canvas strip's Options face renders whole.
    # "panels" is what stands *beside* the canvas inside the tab: the graph's own chrome,
    # where View ▸ Panels is about the areas around the tabs.
    "Graph": ("arrange", "regions", "look", "panels"),
    # "edit" is New, Rename and Delete. New is one verb: a step is born plain and the
    # details dialog opens on it, where the aspect bar says what it is.
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
    # "runs" is the Agent List — the live shells this window launched, a data child menu
    # rebuilt on open — above "install", what this machine has of DPlanner itself.
    "Tools": ("runs", "install"),
    # "design" is the design system's living reference — Design Example… and its table
    # tab — what a developer bringing a surface up opens beside their own (DESIGN.md).
    "Debug": ("llm", "telemetry", "design", "windows"),
    "Help": ("about",),
}
