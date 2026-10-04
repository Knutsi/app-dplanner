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
    # "project" (New Project, Open Project, Share Project) comes from the projects module
    # and "library" (New/Open Project Library, Reload) from the library module and the
    # watcher; the two are a band each because one is about *a* project and the other about
    # which library this window is. Share Project sits in the first even though it acts on
    # the focused project: it is Open Project's other half — what one writes, the other
    # reads — and a round trip split across two menus is one nobody finds.
    # "save"/"branch" from sync; "window" from
    # the app shell and the settings dialog. "export" holds the Export submenu — one entry
    # per feature that can write itself out: the order list's and the milestones' CSVs,
    # the plan's report as HTML and PDF, its tables as a workbook.
    "File": ("project", "library", "save", "branch", "export", "window"),
    # "history" is the app shell's Undo/Redo. "clipboard" and "selection" are the graph's:
    # Cut, Copy, Paste, Duplicate and Delete's second seat (its home is Step, which a card's
    # right-click renders), then Select All — registered by canvas because the step
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
    # **Go is the places**: every surface a project has, so the bar reaches each without the
    # index beside it. "home" is Home, the index's first row and where a window starts;
    # "views" is the surfaces that stand as rows under a project in the
    # index — Specs, Assets, Steps, Order, Step Statuses, Time Estimates, Coverage, Tests —
    # in the index's order; "survey" the two looks over the whole plan that have no row
    # there, Estimate Steps and Preview Report, which is also what empty canvas's right-click
    # offers; "archive" the library's Archive tab. No right-click renders Go whole: a row's
    # own right-click never repeats the rows beside it (the Project menu below), and a table's
    # Step menu reaches the views about a step through Step ▸ Show in. ARCHITECTURE.md's *The
    # menu bar is sorted by subject* has the reasoning.
    "Go": ("home", "views", "survey", "archive"),
    # The planner's own vocabulary. "Project" is the verbs on a project — what the index
    # tree's right-click renders — and "Step" the verbs on picked steps, which every table
    # renders whole and a card renders in part (canvas/menus.py).
    # "edit" is the project's own form and where its plan lives: Settings, Move Plan.
    # "membership" is whether a project is in this library at all — Archive, Restore and
    # Remove from Library — and it is the whole of what an archived project's right-click
    # renders, through `fill_menu`'s `group` filter.
    # "documents" and "sources" are the spec module's, and both feed the Specs child menu:
    # adding a spec (the Add Spec child inside it) and what acts on the document picked in
    # the Specs tab, then what acts on the source it came from — the rule between them drawn
    # inside the child, and "sources" adding none to Project itself.
    # "agent" is Open Agent in Code: the same launch profiles Run Agent offers, opening an
    # agent in the project's code with no briefing at all. It is the project's and not a
    # step's because it is what the planning *before* the steps needs — a spec has landed,
    # the graph is empty, and there is no step for the verb to be about.
    # "docs" is Compile Out of Date: one agent per document in this project whose fragments
    # have moved on. It is the project's because it is about all of them at once — the
    # per-collector launch is a Step verb, beside Run Agent. It is a band of its own below
    # the one above: bringing a set of documents up to date is not opening a terminal.
    # "tests" is the test run's two verbs — a run belongs to a project, spans its
    # steps, and there is at most one open at a time — the categories and the Test panel.
    "Project": (
        "edit",
        "membership",
        "documents",
        "sources",
        "agent",
        "docs",
        "tests",
    ),
    # The canvas the plan is drawn on: every verb whose subject is picked *on the canvas*
    # rather than being a step — a point, the plane's steps as a place, an arrow — and how
    # the graph is arranged and looked at. That is what makes it a menu rather than a group
    # inside View, and what tells the next person where to add one.
    # "new" is what lands where the canvas was clicked: New Step, New Stack, and Paste's
    # second seat (its home is Edit, with Ctrl+V). "select" is the ways to a step on the
    # plane — Find, Lasso, Select Nearest. "narrow" keeps one kind of a mixed pick: steps, or links.
    # "links" is what a picked arrow is for: Remove Link, Auto-progress and the Redirect
    # pair. The canvas's right-click renders these bands by what it lands on, which is why
    # each is a group of its own.
    # "arrange" is the Sort, Layout and Divide child menus: three ways of moving cards
    # about, from the wholesale to the one cut at a time. "contract" feeds that same Divide
    # child menu with the verbs that take room back, so the rule between opening a gap and
    # closing one is drawn inside it — and, holding no top-level entry of its own, the group
    # adds no rule to the menu itself. "look" is what is drawn without
    # moving anything: framing, the marks, the grid and the ground — the band the canvas
    # strip's Options face renders whole. "panels" is what stands *beside* the canvas
    # inside the tab: the graph's own chrome, where View ▸ Panels is about the areas around
    # the tabs.
    "Graph": ("new", "select", "narrow", "links", "arrange", "contract", "look", "panels"),
    # Every table that lists steps renders this menu whole; a card on the canvas renders
    # only the bands about the step itself — edit, link, track, agent, open — and leaves
    # the rest to the index beside it (menus.py's CARD).
    # That split is why some neighbours below are separate groups.
    # "edit" is Rename, Delete and Insert Wait Before — New is the Graph menu's, since what
    # it needs is a place.
    # "stack" is Make Stack, which turns the picked steps into a stack, and "stacked" what
    # acts on the stack a picked step stands in — Add Step Below, Take Out, Dissolve. Both
    # feed the one Stack child menu, the rule between them drawn inside it, and a stack's
    # frame on the canvas leads its right-click with "stacked" alone: a stack is never made
    # of itself. New Stack is Graph's "new", beside New Step.
    # "branch" is Put on a Branch and Remove Branch: a cut before the picked steps and a
    # landing after, or the whole bracket taken away again — a band of its own because a
    # branch is not a stack, though both are drawn round steps that are already there.
    # "track" is where a step stands and how long it takes: the Status and Estimate child
    # menus, acting on every picked step. A child menu sits at its first entry's order, so
    # the two claim bands of it — Status the 200s, Estimate the 400s — and ``order`` still
    # only ranks inside one group.
    # "classify" is what a step *is*, and it is in no menu: Type (one independent checkable
    # toggle per type-ish aspect — never a radio group, a step can be several things at
    # once) is the aspect bar across Step Details, and Test (add, archive, record a result)
    # is the step's Tests tab there, the Tests strip and the Test panel. Its verbs are
    # `in_menus=False`, so the palette finds them under *Step ▸ Type* and *Step ▸ Test*.
    # "agent" carries a step's work out: Run Agent and what follows one — its terminal, a
    # shell of your own in its worktree, its pull request, clearing the run. "compile" is
    # Compile with Agent, which writes a collector's documentation from the fragments behind
    # it — a band of its own because a card does not offer it; the Docs tab does.
    # "open" is where this step is seen: Step Details, then the Show in child menu's
    # Coverage, Spec Passage and Documentation. "surfaces" is what a table adds from a step —
    # Show in's Graph, Order, Step Statuses and Tests, then Test Details — which a card
    # leaves to the index beside it, or has no use for on the graph it is already on. The
    # two groups feed one Show in, so a card's is the first three and a table's all seven.
    "Step": (
        "edit",
        "link",
        "stack",
        "stacked",
        "branch",
        "track",
        "classify",
        "agent",
        "compile",
        "open",
        "surfaces",
    ),
    # "runs" is the Agent List — the live shells this window launched, a data child menu
    # rebuilt on open — above "install", what this machine has of DPlanner itself.
    "Tools": ("runs", "install"),
    # "design" is the design system's living reference — the Design Examples child menu,
    # one entry per page of it — what a developer bringing a surface up opens beside their
    # own (DESIGN.md). A new example is a line in modules/debug/module.py and nothing here.
    "Debug": ("llm", "telemetry", "design", "simulation", "windows"),
    "Help": ("about",),
}
