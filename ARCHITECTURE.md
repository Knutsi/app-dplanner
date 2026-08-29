# DPlanner's shape, and why

`CLAUDE.md` carries these rules in their short, imperative form — this file is where the
reasoning lives, so the short form does not have to be taken on faith.

app-framework's `docs/index.html` documents the machinery this is built on — the ten
registries, the origin token, the two version axes, where state lives. This document covers
only what DPlanner added on top, and the reasoning is the point: the code shows *what*, and
this is the file for *why*.

## The goal

Plan software work in a form that survives being shared, and that a coding agent can drive
as well as a person can. Two consequences fall out of that sentence and shape everything
below:

- **The plan is plain files in version control**, so the format is a public contract and its
  diffs are meant to be read by humans. `FORMAT.md` is that contract.
- **There are two front doors, not one and a hatch.** A window and a `dplanner` command,
  equals, over one model — and expected to be in use at the same time.

## Library → Project → Step

A planner needs a level above "the project" — but the earlier answer, a **Product** owning
its projects inside one workspace folder, put the boundary in the wrong place. A person's
projects do not all belong to one codebase, a project's planning files want to live *with*
the code they plan, and "where is the repository" turned out to be a fact the directory
already knows rather than one worth storing. So the top level is the **Library**: a per-user
file (see `FORMAT.md`) listing the project directories this user is planning. It is the
account level, not a document — the in-memory `Library` aggregate exists only to be the one
place a change can happen (the flat node index and the signals live there), and nothing on
disk stands for it but the membership list.

A **Project** is a unit of work with an end — a directory holding `project.dproj`, inside a
git repository, opened through its own storage provider. A **Step** is a node in its graph.

**Why membership changes bypass the undo stack.** Creating a project may `git init` a
repository and always writes files outside any store; removing one only forgets it. Neither
is something Ctrl+Z could honestly reverse, so File ▸ New/Open Project and Remove from
Library apply their model change directly with their own origin — the same discipline as
syncing an external fact, below.

**Why opening another library is another process.** Every registry refuses a duplicate id,
so two libraries in one process was never implementable — and unlike the old
workspace *switch* (one document replacing another in the same window), two libraries are
genuinely two applications' worth of state someone wants side by side. File ▸ New/Open
Project Library therefore spawns a detached instance and the in-process switch machinery is
gone; `reload` — the full rebuild — remains, because branch switches, pulls and external
writes still invalidate the build wholesale.

**Why a graph and not a tree.** Work has prerequisites that do not nest: the thing you must
do first is routinely in another part of the plan. A tree forces that relationship into
either a false hierarchy or a side-channel; the template's demonstration domain had exactly
that side-channel (`depends_on` beside the tree) and it was the most-explained field in the
model. Making the graph the primary structure removes the exception.

**Why edges live on the step that waits.** `"edges": {"requires": [...]}` on the waiting step
reads unambiguously — this is what *I* am waiting for — and makes a step self-contained:
delete it and its links go with it. Storing edges centrally in `project.json` would make
every link change touch one heavily-shared file, which is the wrong shape for merges.

**Why deleting a step leaves other steps' links alone.** Undo has to restore the graph
exactly. Silently rewriting other steps' edge lists would make delete-then-undo lossy, so
resolution is tolerant instead: `Library.requires()` skips ids it cannot resolve.

## Aspects

An estimate, a ticket, a description. None of them are fields on `Step`, and that is the
central design decision of the model.

The alternative — a field per useful fact — makes every new feature a change to
`domain/model.py`, a format migration, and a change to everything that serialises a step. It
also forces the model to have an opinion about facts it cannot validate. A team that tracks
work in Jira and a team that does not would be carrying each other's fields.

So an aspect is **a module's namespaced entry beside the step**, in one of three stores
chosen by what the content is:

| Store | For | Why not the others |
|---|---|---|
| `module_data` → `modules/<id>.json` | structured facts | JSON is mergeable and versioned per module |
| `module_text` → `modules/<id>.md` | one document of prose | markdown inside JSON is one escaped line per edit, and loses the text stack |
| a file area → `modules/<id>/` | images, attachments | opaque bytes nobody merges, and not undoable |

`module_text` deserves its own note, because it looks like a field and is not. The framework
already has a text stack — positional splicing with a staleness check, undo coalescing per
burst, origin-based echo suppression — and a description that lived in a JSON value would
have been a whole-document rewrite per keystroke, with a second text stack growing to fix
that. Keying prose by module id instead of naming it as a field gives any module a real
prose document and *removed* code: the demonstration domain had two hardcoded text fields
with a signal and a field class each, and this is one of each.

An aspect declares itself once, in its package's Qt-free `aspect.py`: `SPEC` (id, label,
one-line summary, data format) plus typed `read`/`write` helpers. That one declaration feeds
the CLI verb, the generated skill, `dplanner aspect list`, the module's `data_format`, and
whatever editor arrives later. Shipping an aspect with no editor is deliberate rather than
unfinished — the `data_format` declaration is what makes the project forward-compatible,
so the CLI can write the data today and a card can arrive without a migration.

## Two surfaces, one vocabulary

The rule that keeps a window and a command line from becoming two applications:

> A menu action and a `dplanner` verb build the **same object from `domain/commands.py`**.
> The GUI pushes it onto the undo stack; the CLI applies it and lets the store flush.

Everything follows from that. A CLI edit is undoable in a window. Neither surface can grow a
behaviour the other lacks without somebody editing that one file. And the validation that
refuses a cycle lives in the model, so it is the same refusal on both sides — the CLI just
renders it as one line instead of a dialog.

The layering that protects it is `core → domain → cli → framework → modules`. The
interesting rule is that `cli/` sits **below** `framework/` and imports no Qt, and that a
module's `cli.py` and `aspect.py` are held to the same standard. That is not tidiness: an
agent refining a plan makes dozens of small calls, and importing a GUI toolkit for each one
cost 792 ms and a hard dependency on graphics libraries that a container may not have.
Making the module packages' `__init__.py` files docstring-only took the same import to
18 ms, and `tests/test_architecture.py` asserts the property directly so it cannot rot.

There are therefore two composition roots, and both are in `modules/__init__.py`:
`default_modules(services)` builds the window, `default_cli_commands()` builds the verbs.
Reading that one file still answers "what is this application".

## The index tree

The template's sidebar was a tab set: one page per module, one visible at a time. DPlanner
replaced it with a single tree whose folders come from an `IndexSegmentRegistry`, and
deleted the tab set rather than keeping both.

The argument for the tree is that it shows the library's *shape* — projects, and the steps
under them — where a tab set shows one feature and hides the rest. The argument for deleting
the old one is that anything a page could hold is a folder here, so keeping both would have
been two navigation mechanisms competing for the same 275 pixels.

The tree is not a slot in the window any more; it is one **panel** anchored in the left area
(below), which is why it can be moved and hidden like anything else contributed to the window.
Three things still live in the panel rather than in each segment, because a shared tree is not
the same problem as a stack of independent widgets: **selection is published exactly once** (Qt
selection is per-tree and `ContextService` has one selection scope, so segments would
otherwise fight over it); **a segment supplies its own menu** rather than the spec naming a
`MENU_STRUCTURE` menu, because a menu name is application vocabulary and has no business in
a framework spec; and **expansion state survives a rebuild** through shared helpers, because
rebuilding on change is the normal case and that bookkeeping is what every segment would
otherwise copy.

### A click is a glance: preview tabs

A single click on an entry row opens its surface as a **preview tab** — VS Code's
arrangement, adopted whole rather than reinvented. The host (`framework/tabs.py`) keeps at
most one preview; the next preview replaces it, and a deliberate act keeps it: activating
the row again (a non-preview open of the same URI), or moving the tab. A preview-open of
something already open is a plain focus that changes nothing — the tab you kept stays kept,
the preview stays where it was.

Two consequences fell out of making every step idempotent. **The double-click needs no
timer**: click one previews, click two's activation pins, and the trailing click event Qt
fires after an activation lands on "already open → focus" and disturbs nothing. And **"jump
to the thing that is open" needed no code at all** — the host already deduplicates by URI,
so a click on an entry whose tab exists anywhere simply focuses it, in whichever pane it
lives. The preview's mark is an italic title, painted by the tab bar itself so the host's
active-pane dimming keeps working underneath it.

The gesture reaches the segment through a fifth `IndexSegmentView` hook, `clicked`, and the
panel forwards only plain left-clicks — a Ctrl/Shift-click is building a selection, and a
right-click is asking for a menu. On the entry it is `open_preview`, a second callback
beside `open`, both closed over the owning module's `open(..., preview=…)` by the
composition root; `None` is an entry whose surface has no preview form.

## How a gesture becomes a change on screen

This is the application's central mechanism, and everything else here is a consequence of it.
It is one chain, and **nothing is allowed to take a shortcut through it** — the short,
imperative form of that rule is in `CLAUDE.md`; this section is why each link exists.

```
a gesture, a menu item, the command palette, or the CLI
        │
        ▼   the Context: URI strings only — never widgets, never model objects
   ActionSpec.state(context) gates it, ActionSpec.run(context) performs it
        │
        ▼   a Command from domain/commands.py — the same object either surface builds
   undo.push(command)   (the window)        command.redo(library)   (the CLI)
        │
        ▼   one mutator, one change
   the model, which emits exactly one signal carrying an `origin`
        │
        ▼   synchronous, on the GUI thread
   every view applies it — except the one whose origin it is, which already shows it
```

**The command is a step, not an implementation detail.** An action does not change data; it
pushes a command that does. That is what makes the change undoable, and it is what carries the
origin token down to the signal. A mutation made directly is a change Ctrl+Z cannot see and no
other view hears about.

**The visual update is pulled, not pushed.** An action cannot touch a view — it holds only URI
strings and has no way to reach one. Each view subscribes to the model and decides for itself
what to redraw. That is the property that lets four aspect modules render into one panel
without any of them knowing the others exist, and it is why a canvas drop belongs in an action:
the canvas should not be the thing that knows how to create an edge.

**The origin is what makes the last step safe.** The view that caused the change ignores its
own echo; undo passes a token matching no view, so everyone applies it. Without it you get the
oldest bug in desktop software — B updates from A's edit, B's update fires, A's caret jumps to
the end. Every signal on `Library` carries one, with no exception, because a convention with
one hole is one nobody can rely on.

**"On the GUI thread" is a constraint, not a formality.** `core.signals.Signal` is synchronous
and has no thread affinity, so the model may only be mutated on the GUI thread. Anything
computed off it comes back through `TaskRunner`, which is the one place in the application
using real Qt signals rather than ours — precisely so that hop is queued. The whole rule:
**work may leave the GUI thread; mutation may not.**

### When there is more than one pane on screen

Tab groups add a second way for the activity scope to change: a click in another pane, rather
than a click on a tab. **Activating a group is not a new kind of fact; it is a new cause of an
existing one.** So it runs the same routine a tab switch runs, and nothing downstream — the
menu bar, the toolbars, the right-click menus, undo coalescing, autosave — learns that groups
exist at all.

Two consequences fall out, and both are rules rather than details:

- **Only the pane the user is in may write to the selection scope.** There is one scope and
  several panes, so a background pane re-syncing its canvas — when a step is deleted, say —
  would otherwise clobber what the active pane published. `ProjectActivity` tracks this
  through `on_activated`/`on_deactivated`; anything else that publishes a selection owes the
  same guard.
- **A visible pane that is not active is showing a claim the context no longer holds.** Its
  canvas still paints a selection; an in-tab toolbar would still show the active pane's
  action state. That is inherent to one context and N visible surfaces, not a bug in this
  design — every multi-pane editor has it — and the honest answer is to make which pane is
  active obvious, which is what the dimmed tab titles are for.

The detail panels get the first rule for free, and that is the point of where they live. A
panel reads the context; only the active pane may write to it; so the panel follows the pane
the user is in without a single line about panes anywhere in it.

The tab bar's right-click is the same rule pointing the other way. **A right-click on a tab
makes it current before the menu opens** — the move the canvas already makes when it selects
the node under the cursor — so the menu is built from one notion of "what the user is on" and
every entry in it is a verb the menu bar and the palette already have. That is why the tab
verbs live in View's Tabs submenu rather than in a hand-built popup: `build_menu` renders a
*menu* (its `submenu` filter renders just that child menu), and a right-click that offered
anything else would be a hand-maintained copy waiting to drift. `TabHost` builds none of it —
it emits `tab_menu_requested` with a position, and the module that owns the tab verbs renders
them.

### What this rules out

The graph canvas is the worked example, because it got this wrong first. A drop originally ran
a private signal straight to a command: the verb existed nowhere else, its refusal was checked
by hand in the view — where it read gesture state a later line had already cleared, so *every*
drop was silently refused — and no test could reach it without a widget. Routing the drop
through `steps.link` fixed the bug by deleting the code that held it, and gave the same verb to
the Step menu and the palette for free.

So: **a gesture is not a special case.** If a view can do something, it does it by publishing
what the user picked into the context and running an action. The verb is then testable by
handing it a constructed `Context`, and `tests/modules/test_project_editor.py` does exactly
that with no canvas in sight.

### Hidden means absent; disabled means not now

An `ActionState` distinguishes *invisible* from *greyed*, and the two are different claims,
not two strengths of the same one. **Disabled says "this exists here, but not right now"** —
the verb belongs to the program, the user just hasn't given it what it needs, and the greyed
entry teaches the precondition (its label carries the reason where there is one:
`steps.link`'s "Cannot Link — cycle" is the worked example). **Hidden says "this capability
is not in front of you at all"** — a storage provider without history has no *Save Version*,
a feature behind a flag leaves no trace. The rule's short form is in `CLAUDE.md`.

The reason it is a rule and not taste: a menu that reshapes itself with the selection cannot
be learned. The user who saw *Open Specs* yesterday and cannot find it today has no way to
know whether the feature is gone or their context is wrong — a greyed entry answers that
question before it is asked. It also keeps every surface stable: a toolbar row that reflows
as the selection changes cannot be read, and the menubar's separators stop jumping.

One documented exception: a verb whose *opposite* currently occupies its slot may hide.
`steps.link` stands down when the pair is already linked, because *Remove Link* is the verb
that belongs in that position and a greyed "Already linked" beside it would state the same
fact twice. The label still rides on the hidden state — the canvas status bar reads it after
a refused drop.

The presenters split accordingly: the menu bar, toolbars and `build_menu`'s right-click
popups all render a disabled action greyed; only the command palette filters to what is
runnable, because a fuzzy search over verbs that cannot run helps nobody.

## Where a panel goes

The window has a centre — the tab groups — and three areas around it: **left, right and
bottom**. Anything anchored in one is a `PanelSpec` in `services.panels`, and the framework's
`PanelDock` puts it there. The index tree is one; the step detail panel and the project form
are two more. Right-clicking a panel's header moves it between areas or hides it, and
*View ▸ Panels* switches it back on.

**One panel, not one per tab.** This is the whole reason the dock exists, and it was learned by
getting it wrong: the step detail panel used to be built *inside* `ProjectActivity`, so opening
a second project built a second panel with a second set of aspect editors, and splitting the
window put both on screen at once. Two copies of one editor is not a richer window — it is the
same 360 pixels spent twice, and it raises a question with no good answer ("which one is the
real one?"). So a panel belongs to the window.

**It follows the user by reading the context, not by being told.** A panel that cares implements
`ContextPanel.show_context(context) -> bool`; the dock calls it on every context change and
takes the panel off screen when it answers False. Nothing pushes at a panel, and no panel
subscribes to the context itself — there is one subscription, in the dock.

That one decision is what makes "follow the focused tab" cost nothing. The rule that *only the
active pane may write to the selection scope* already existed, for a different reason; a panel
that reads the scope therefore shows the active pane's selection by construction, and
`ProjectActivity` **lost** its `_panel` field rather than gaining an "am I the visible one?"
check. It also means a surface nobody planned for gets the panel for free: the order table
publishes step selections and never had a detail panel, and now has one without a line of code.

**Areas, not draggable docks.** `QDockWidget` gives floating windows, tear-off drags and a
serialized layout blob nobody can read or reason about. What this needs is "put that over
there" — three fixed places and a menu — so that is what it has, and where each panel sits is
three legible `QSettings` keys under `layout/`.

**An area with nothing in it takes no space.** An empty right side is a wider canvas, not a
blank column, which is what lets two panels share one area and be mutually exclusive: the step
panel shows while exactly one step is selected, the project form shows the rest of the time,
and neither has heard of the other.

## How a panel gets editors it has never heard of

The step detail panel shows a tab per aspect — Estimate, Ticket, Description, Agent — and
nothing in it knows those four exist. Two seams do that, and they are worth naming because they
answer every "feature A needs feature B" question this application will have.

**Nobody hosts the panel.** `step_properties` owns it and registers it into `services.panels`;
where it sits is the dock's business and what it shows is the context's. Before the dock existed
this was a *consumer-owned Protocol* — `project_editor` declared `widget`/`show_step`/`dispose`
and the composition root handed it a factory — which worked, and cost a panel per tab. Anchoring
it deleted the Protocol, the `detail_panel` dependency, and the question of who owns the one
that is on screen. The Protocol-plus-factory shape is still the right answer when one module
needs a *widget* from another; it stopped being the right answer here when the answer to "how
many are there" became one.

**A registry for the contributors.** Aspect modules register an `InspectorSection` into
`services.inspector_sections`; the panel reads that registry when it is *built*, not when the
modules load, so a contributor's position in the composition root is free — its position
*ahead* of `step_properties` is not, and the root says so.

The composition root is the only place that knows both, and the wiring it used to need between
the two panel modules is gone:

```python
step_properties = StepPropertiesModule(
    StepPropertiesDeps(..., panels=services.panels, sections=services.inspector_sections)
)
project_editor = ProjectEditorModule(ProjectEditorDeps(..., panels=services.panels))
projects = ProjectsModule(ProjectsDeps(..., open_project=project_editor.open))
```

**Where provider-and-Protocol is still the answer.** The order view's start-date bar is
exactly the shape the panel used to have, and it survives the panel's move because the two
questions are different: a *widget one surface hosts* is not a *surface the window anchors*.
`estimation` provides a `create_start_bar()` and registers nothing for it, `step_order`
declares a `StartBar` Protocol of its own and takes a `Callable[..., StartBar] | None`, and
the composition root is the only file that knows both names. Why a `create_…` rather than a
registry entry is worth stating too: a registry is for *whoever turns up*, and this control
belongs to exactly one surface. When there is only one host, a registry is ceremony that hides
which module supplies what. (This is Writer's arrangement, borrowed wholesale — its
`segment_properties` serves a corkboard, a segment editor and a continuous editor the same
way, which is the evidence that the shape survives a second host and a third.)

**What the panel is not.** The project's name and summary are not a section. An
`InspectorExtension`'s whole contract is `show_target(step_id | None)` — one target vocabulary —
and making the project form a peer of the aspects would force every aspect editor to answer
"what if this is a project?" and hide itself, which is precisely the conditional the registry
exists to delete. It is a peer of the *panel* instead: a second panel in the same area, with its
own answer to `show_context`. Both ask `Context.selected_entity("step")`, so "there is exactly
one step in front of the user" has one definition rather than two that can drift apart.

**The same panel, briefly modal.** `steps.details` puts a second `StepPanel` in a dialog —
what every view's double-click on a step runs. That is not a breach of "one panel, not one
per tab": the rule forbids a panel *per surface*, where N tabs meant N copies on screen at
once; the dialog is one transient host the user summoned, disposed when it closes. Building
a second stack is the section contract's sanctioned use — one extension instance per host —
and the project panel's cards were already the proof. The dialog never reads the context:
it is opened *about* a step and stays on it, driven by `show_step` directly, which is what
lets a table row open it for the row under the cursor even when that pane's publish was
suppressed. The double-click the tables used to spend on reveal-in-graph moved to the Step
menu as `steps.reveal`, where every view's right-click already renders it.

**The project panel hosts the same contract, as cards.** A module with something to say about
a *project* registers an `InspectorSection` into `services.detail_cards` — the registry type
is deliberately instantiated twice, because "a module-owned surface that appears when it has
something to say" turned out to be identical for a panel tab and for a card stacked inside
one. The project panel renders each as a `ToolCard` and drives the same lifecycle the step
panel does, with a project id in `show_target`. That is what retired `project_repo`'s
provider-and-Protocol handover (`RepoFields` + a `repo_fields` factory on the editor's Deps):
the moment a second module wanted a project surface, "whoever turns up" became the right
question, and a registry is for whoever turns up. The `step_agent_instruction` card — the
project's standing instruction — is the second registrant, and each card must be registered
before `project_editor` builds the panel, which the composition root's list order says.

## The graph, and what it stores

A project is a graph, so the tab is a canvas: `QGraphicsView` gives selection, dragging,
hit-testing and zoom for free. Writer's corkboard is 2,200 hand-rolled lines because cards
flow in a grid; free positions are the case Qt already handles.

Two decisions keep it small. **Every item diffs by key** — nodes by step id, edges by
`(waiter, kind, source)` — because an item the user is holding on to has to keep its identity:
a node may be under the mouse mid-drag, and an edge may be selected, waiting for Delete. That
was two rules once, and edges were the ones rebuilt wholesale; the second rule was exactly what
made edges unselectable, so making them selectable *removed* a rule rather than adding one.
**The scene reports, the activity commands** — every gesture ends in a signal, and the activity
turns it into something on the undo stack, so a drag is undoable and the model stays the only
authority on what a legal graph is.

That last point is why `Library.link_refusal()` exists. A link drag needs to know *before* the
drop whether an edge would be a cycle, and the alternative — a second reachability check in the
view — is two implementations that will eventually disagree. So the refusal is a question the
model answers, `set_edges` asks it before writing, and the canvas asks it under the cursor.
There is no error dialog anywhere in the interaction because there is never anything to
apologise for.

### Who owns the canvas's input

Interaction is a **stack of modes**. A mode is an object that handles input and has power over
the view; pushing one changes what the canvas does, and popping it puts back exactly what was
there before. Escape pops. `GraphView` normalises each event and offers it to the current mode,
then to the canvas keymap, then to Qt.

The alternative was the shape this replaced: one set of Qt handlers on the scene with the
gesture's state in fields beside them — `_link_from` next to `_press_at`. That works for one
gesture. It produced its first bug at one: a handler cleared `_link_from` on its first line and
asked about it on its third. A mode has a beginning and an end, so there is no field anybody
has to remember to clear, and `exit()` is where "put the cursor and the drag mode back" lives
whatever happened while the mode was on.

Three properties make it cheap rather than another layer:

- **Declining an event costs nothing.** A hook that returns False lets the event fall through,
  and Qt still does rubber-band selection, item dragging and hand-scrolling for free. `IdleMode`
  is nine lines: it catches a press on a link handle and declines everything else.
- **A mode that claims a press suppresses node dragging for free.** The scene's remaining mouse
  handling is the record of what Qt's own item drag moved, which has to run *after* Qt updates
  the selection — so it lives on the scene, where the event arrives already handled. Connect
  and Pan consume the press, the scene never sees it, and nothing anywhere asks "which mode?".
- **A mode reports; it never writes.** It emits the canvas's signals and the activity turns
  those into commands. The chain above is untouched; the mode is one more way to reach its top.

`modes.Canvas` is a written-out protocol rather than "pass the scene around", because it is the
whole of a mode's power. A new mode cannot quietly grow a reach nobody sanctioned, and a mode
can be driven in a test by anything that satisfies it.

**The mode is published into the context**, as an edge on the activity node. That is what lets
`steps.connect`'s toolbar button check itself: its `state(context)` stays a pure function, so
the button, the menu entry and a test all read the mode the same way and nothing reaches for a
widget to ask.

**Canvas keys name action ids; they are never `ActionSpec.shortcut`s.** A bare `h` on a menu-bar
QAction fires wherever the application has focus and would eat a keystroke in the step
description editor. `keymap.py` binds keys that exist only while the canvas has focus, and what
they run is the same verb the menu runs. A key names the verbs it means *in order* and the first
one the context allows runs — which is how one Delete key means "remove these links" when edges
are picked and "remove these steps" when steps are, with no branch on the canvas at all.

That leaves two families of verb, and the distinction is worth stating: **step verbs change the
plan** (they push commands and are undoable), while **canvas verbs steer a surface** — move the
selection, enter a mode, frame the graph. Canvas verbs push nothing, and they reach the current
canvas through a typed callback on their own `Deps`. Where a node *is* is still a fact about the
model — `layout.positions()` answers it — so "the nearest node to the right" is a pure function
and only the last step, telling the canvas what to select, needs a window.

### An explicit sort persists; the ambient layout never does

Two things place a node, and they persist differently on purpose. The **ambient layout** —
where a never-moved node sits — is recomputed from the graph every time the project opens
(`layout.auto_positions`, which is `sorts.layered_flow`). Storing it would mean opening a tab
dirties the project, autosave flushes it 1.5 seconds later, and every step an agent creates
through the CLI grows a position file the next time a window happens to open. A **sort
action** (`canvas.sort_*`, or `dplanner layout sort`) is different in kind: somebody asked
for that arrangement, so it is a gesture like a drag — one `CompositeCommand` of position
writes on the undo stack, and one Ctrl+Z takes the whole arrangement back. The rule
"derived facts are computed, never stored" survives intact because what is stored is not the
derivation but the user's decision to keep its output.

The same line separates the two other things this feature stores. A **named layout** is a
snapshot a person saved — authored, not derived — kept as one entry on the *project* node
under the same `project_editor` id as the per-step positions (the `estimation` cross-level
precedent in `FORMAT.md`). Applying one builds the same position commands a sort does, which
is what makes a CLI `layout apply` undoable in an open window. **Which layout is currently
applied** is per-user presentation state and lives in `user_config` (QSettings), never the
project: two people sharing a repository can be looking at different layouts of the same
graph. The picker's modified dot is a comparison against the snapshot, recomputed — never
stored.

**Regions** ride the same project-level entry: titled rectangles painted below the edges,
annotation the model never learns about. Every region gesture is one command writing the
whole list; a body drag also carries the steps whose centres lie inside, as one composite —
undo restores frame and steps together. A named layout snapshots region rects along with
step positions, and applying it moves regions it still finds — never creates or deletes one.

### The canvas is a plane, and why that is one decision rather than three

`GraphScene` sets its scene rect once, in its constructor: a square centred on the origin,
`CANVAS_EXTENT` out in every direction and never touched again. Three things follow from that
one line, which is the reason it is worth a section.

**Panning does not stop.** The complaint was that it did — a few hundred pixels past the last
step, most obviously downwards, because the extent was the graph's bounds plus a margin. A
plane two hundred viewports across has an edge nobody reaches.

**Nothing about the graph can move the extent.** The older code recomputed the rect from
`itemsBoundingRect` on every model change, and a move *is* a model change: dragging a node
changed the rect's origin, the scroll bars re-ranged under a fixed value, and the canvas slid
out from under the drag. The fix at the time was a floor that only grew and was left alone
mid-drag — a constant is the same rule with nothing left to get wrong. The alignment fix that
came with it (a scene *smaller* than the viewport re-centres itself whenever its rect changes)
went away with it too: this scene is never smaller than a viewport. The rule generalises past
this canvas: **a scrollable area's extent must not be a function of what the user is moving.**

**The scroll bars go.** On an extent like that a scroll bar is a nub that says nothing true
about where you are, so both are `ScrollBarAlwaysOff` — and still there, so the wheel still
scrolls. What replaces them is `minimap.py`, anchored in the canvas's lower-left corner: the
graph small, the viewport as a frame on it, and a click to go anywhere. It is *given* node
rectangles rather than reaching for a scene, so it imports nothing from the module around it
and cannot outlive what it draws; `GraphView` pushes on `QGraphicsScene.changed` and on every
scroll, and is the one object in a position to know whether there is still a scene to ask.
And it is parented to the view rather than to the viewport, because `QGraphicsView` pans by
`QWidget::scroll`, which drags the viewport's children along with the pixels.

### The palette a painter is handed is a snapshot

`QStyleOptionGraphicsItem.palette` is filled once, when the scene is constructed, and Qt never
refreshes it. Nothing about that is visible until the application changes its palette: a theme
switch repainted the canvas with the *old* theme's ink, and light-on-light lost the graph
altogether. `items.live_palette()` reads the scene's palette instead, which follows the
application's, and no canvas item may read `option.palette` again.

The same shape one layer up, with a different cause: `TabHost` copies a palette colour onto
each tab with `setTabTextColor` to dim the panes the user is not in, and a copy does not
follow the original. It re-tints on `QEvent.PaletteChange`. **A surface that stores a colour
owes that hook** — the palette is live, everything derived from it is not.

Two more colours reach past both: Qt's tab-close cross is a bundled red bitmap that no
stylesheet or palette touches, so `theme/style.py`'s proxy answers `SP_TabCloseButton` with a
painted glyph — and the style is rebuilt on each theme change because `QCommonStyle` caches
the icon it is given.

**Node positions are stored, automatic layout is not.** A step nobody has moved is placed by
`requires` depth, recomputed each time the project opens. Persisting that would mean merely
opening a tab dirtied the project, autosave flushed it 1.5 seconds later, and every step an
agent created through the CLI grew a position file the next time a window happened to open. A
test asserts the project is unchanged after a tab is opened, because that is the kind of rule
that decays silently.

## Two writers, one folder

The scenario DPlanner is built for — an agent refining a plan *with* the user — means the
CLI writes while a window is open on the same folder. The framework's ordinary contract,
"memory is authoritative and disk follows", quietly loses data under those conditions: a
flush 1.5 seconds after the user's next keystroke rewrites nodes from a model that never saw
the agent's edit, and orphan removal deletes a directory the agent just created.

A lock would be the cheap fix and it is the wrong one, because both writers being live *is*
the feature. So the rule is instead:

> **Nothing writes over a file it has not seen.**

`LibraryStore` records what each project directory looked like when it last read or wrote
it and raises `StaleWorkspaceError` rather than flushing over anything that changed
underneath. The check is **per project** — flush verifies exactly the projects it is about
to write, so an agent editing project B never blocks saving project A, and the refusal
names the project. The library file is a third written thing with the same treatment under
its own stamp, because two instances can both add a project; membership reaches disk
through the ordinary flush, as a structure mark on the library root. Around that one check:

- A **CLI run** reports it as one line and writes nothing. A run is a transaction, so
  running it again picks up the change and is correct.
- A **window** with nothing pending simply reloads — `AppSession.reload()` rebuilds the whole
  application, which is what makes a reload correct, at the cost of open tabs and undo
  history.
- A **window with unflushed edits** stops: autosave keeps its marks and pauses itself, and
  *File ▸ Reload from Disk* makes the choice the user's. Nobody else can make that call.

The same check is why **two CLI runs need no lock between them**: the second is refused for
exactly the same reason and can be run again. One mechanism, three cases.

### Storage operations that rewrite the working tree are synchronous

CLAUDE.md's rule says blocking work runs through `TaskRunner`, and the sync module's own
Save and Update honour it. Four of its operations deliberately do not, and the exception is
a decision, not a leak:

- **Branch switch and create** (`SyncService.switch_branch_sync` / `create_branch_sync`,
  run through `_run_guarded` in `modules/sync/module.py`). A checkout rewrites the very
  files the application is showing; the full rebuild must follow *immediately*, not after
  an event-loop round trip during which a paint, a context change or an autosave could read
  a model that no longer matches the tree. `_run_guarded` pauses autosave around the body
  for the same reason.
- **The branch list** before the switch dialog opens: a subprocess, but a local one, and
  the dialog's contents must be current at the moment it appears.
- **Save at quit** (`service.save_sync()` in the close guard). The window is closing; there
  is no task centre left to watch a task in, and returning to the event loop mid-teardown
  is exactly the window a lost write needs.

The boundary to keep: an operation whose completion the *running* application must observe
before doing anything else at all may be synchronous; anything the user merely waits on goes
through the runner. A new storage verb defaults to the runner.

## Syncing an external fact

The GitHub aspect stores each PR's *last-seen* state so a merged PR stays green offline —
which means something has to keep that cache current, and in a window that something is a
background refresher, not the user.

The refresher builds the same `SetModuleDataCommand` every other writer builds, but calls
`redo()` directly instead of pushing it onto the undo stack, with an origin of its own
(`REFRESH_ORIGIN` in `modules/github/refresh.py`). The reasoning:

- **Undo is for decisions.** The stored state is a cache of something GitHub decided; an
  undo entry here would make Ctrl+Z restore a *stale* state instead of undoing the user's
  last edit, and the user never asked for the refresh in the first place.
- **The stack is not what persists.** Autosave flushes on the store's dirty signal, which
  `Library` emits for every model change regardless of who applied it — so the write
  reaches disk without the stack's help.
- **There is precedent, not exception.** The CLI applies commands the same way (a run is a
  transaction; version control is the undo). The rule "every model change goes through a
  command" is about having one vocabulary of change, not about the stack: the stack is the
  *GUI user's* journal, and a background sync is not the GUI user. (The format migrations
  at open sit *below* the vocabulary: they run in `core/`, which may not import
  `domain/commands`, so they write through the `Repository` protocol directly — before any
  surface that could undo exists.)

The concurrent-writer story needs nothing new: the refresh dirties the project like any
edit, and *Two writers, one folder* above already covers an agent flushing underneath.

## The skill is a projection, not a document

An agent has to be told what DPlanner is and what it can do. Writing that by hand means
writing every command twice, and the copy is wrong within a month — a skill that describes a
flag which no longer exists is worse than no skill, because it is believed.

So `dplanner skill install` **renders** `SKILL.md` and `reference.md` from the same
`CliRegistry` that `--help` renders. The hand-written half is only what a registry cannot
know: what a project is, and how to work with a person. Everything else — the command index,
every argument, the aspects, the edge kinds — comes from the objects themselves.

Two details make that safe. The parsers are built at a **fixed width** rather than the
terminal's, because the output goes into version control and a diff that depends on who ran
it is a diff nobody reads. And `build_tree()` hands back the verb parsers it built rather
than the skill digging them out of argparse afterwards, so one tree serves both.

MCP was considered and deferred. A CLI reaches every agent, including ones with no MCP
client; it is useful to people and to CI; and it needs no process lifecycle. If a
Claude-specific integration is wanted later, `dplanner mcp serve` is a thin adapter over the
same registry and introduces no second description of any command.

## Lint belongs to no feature

`dplanner project lint` asks whether a plan is complete enough to hand to an agent — and
completeness is a fact about *every* feature at once: an unestimated step is estimation's
concern, an uncited requirement is the spec's, a dangling edge is the graph's. No module can
own that question without importing the others, so the verb lives in `cli/lint.py` beside
`cli/aspects.py`, whose rationale it repeats: a command that answers a question *about* the
features takes them as arguments.

The split is what makes it right rather than merely legal. `cli/lint.py` owns the shapes
(`LintFinding`, `LintCheck`), the report and the exit code; each owning module's Qt-free
`cli.py` exports `lint_checks()`, so the knowledge of *what missing looks like* — and which
verb closes the gap, which every message names — stays with the module that owns the aspect.
`default_cli_commands()` assembles the list, and its order is the report's order. The
alternative — a verb inside `projects/cli.py` with injected predicates — would put a
cross-feature report inside one feature and grow that module's signature with facts that are
not its business.

Two deliberate behaviours: findings exit 1, so an agent gates a handover on lint exactly as
it gates on a test suite; and the conditional checks (spec citations only where requirements
exist, a start date only where estimates do) keep the report an obligation list rather than
noise about features a project never adopted.

A check is handed the store's file lookup as its third argument (`FilesFor`) alongside the
library and project, because some facts live *beside* a node rather than in it: whether a
requirement's quote still anchors in its document's text layer, whether a description's
`![](assets/…)` resolves to a file actually attached. The check re-derives those answers on
every run rather than trusting anything stored at mark time — `spec import` can replace a
document with no window open to notice, which is the same argument the ordering makes.

## Authoring a step is one verb, many modules

A fully authored step needs a description, an instruction, an estimate, its requirement
links and its figures — five modules' facts, and five commands when every module keeps to
its own verb. Measured against a real plan, that was most of the invocations. So `step add`
takes **authors**: each contributing module's Qt-free `cli.py` exports a `StepAuthor` — the
flags it registers on the verb's parser, and what it applies to the fresh step — and the
composition root assembles the list into `projects_cli.commands(step_authors=…)`, exactly
as it assembles lint's checks. The shape lives in `cli/authoring.py` for lint's reason: the
contributing modules may not import each other, and `cli/` sits below them all.

Two decisions carry the weight. **The transaction is the rollback**: an author that raises
aborts the whole run, and `open_library` flushes nothing — the step included — so no author
writes compensation code. Any future refactor that flushed eagerly mid-run would silently
break every author's atomicity; this paragraph is the guard. And **stdin is claimed before
it is read**: each author declares whether its parsed flags would consume stdin, so two
`--…-file -` on one call are refused before either swallows the other's document.

## Editing a spec in-app is a replace

The Specs tab can author a markdown document, not just import one, and the editor had to
answer the question every document editor faces here: spec bodies are content-addressed
blobs in a file area — outside the model, outside the undo stack, outside autosave. The
answer is that **an editing session is one replace**, the same operation `dplanner spec
import` performs on an existing name, so the CLI needed no new editing verb and the two
surfaces still speak one vocabulary.

Concretely: the editor flushes on the autosave rhythm (a pause in typing) and at session
boundaries, and every flush writes a new blob and pushes the index update as a
`SetModuleDataCommand` with one label — command merging turns however many flushes into a
single undo entry, and `previous` stays pinned to the blob that was current when editing
began, so `spec diff` answers "what did this session change". Undo restores the
pre-session index, and the pre-session blob is still on disk — the same invariant every
replace relies on. The one carve-out from "orphans are never pruned": a blob the session
itself wrote and then superseded is churn, not history, and is removed once nothing in the
index names it (`prune_blob`). Typing inside the editor is the widget's own undo stack;
the application stack holds only the session-level replaces — two stacks because they hold
two different kinds of fact, keystrokes and index states.

Three edges are decisions, not accidents. **Only markdown edits in-app**: a PDF is not
text, and plain text pushed through a rich-text round-trip would come back as markdown —
`spec.edit` is disabled with the reason on both, per *Hidden means absent; disabled means
not now*. **Qt normalises the markdown it writes**, so the editor only saves a document
the user actually modified — opening one never reformats it — and says so inline when the
first save would. **A foreign change to the edited document ends the session**: the model
is the authority, unflushed keystrokes yield, and anything already flushed survives as a
recoverable blob. An agent replacing the document under an open window resolves through
*Two writers, one folder* like every other write.

## Deriving rather than storing

`domain/ordering.py` answers "what order can this be done in" as a pure function, and the
choice not to store the answer is the same one the canvas made about node positions — for a
sharper reason. The CLI is a first-class writer here: `dplanner step link` changes a graph
with no window running, so a stored index would be stale exactly when an agent is driving,
unless the recompute moved into the model and every `step add` rewrote every step file whose
index shifted.

The index a step carries — its position in that order — is therefore computed with it, by
`ordering.placed()`, which is the shape both the table and `dplanner order show` render. One
function decides what step four is, so the window and the terminal cannot disagree about it.

What "always available" actually requires is not a file but a function every surface can
reach. So the walk lives in the domain, and the canvas layout, the order view and
`dplanner order show --json` are three readers of one implementation. Nothing can disagree
with the graph, because there is nothing else to disagree.

`domain/schedule.py` is the second reader of that same walk, and the one that shows what the
shape was for. "When does this land" is "in what order can this be done", carrying estimates
instead of counting hops — so it takes `ordering.placed()`'s answer and lays the days end to
end from a start date. The order table, `dplanner schedule show` and its `--json` are three
renderings of one function, and none of them can date a step differently from another.

**It is handed a function, not a schema.** An estimate is a module's `module_data`, and the
domain must not learn what key it lives under — so `schedule()` asks for `days_for(step)` and
the composition root closes over the estimation module's reader. That keeps the two
directions of the rule intact at once: whoever owns a piece of data owns its shape, and
whoever derives from it needs one implementation rather than one per surface. It is also why
the derivation works for a build with no estimation module at all: the honest empty answer is
the same function, asked a question with no answer.

The start date itself is the smallest case of the same rule. **A project nobody has dated
starts today**, and that answer is computed (`estimation.schedule.start_of`) rather than
written when the tab opens. Writing it would dirty a project for the act of looking at it,
and it would be wrong by tomorrow — so the only date on disk is one a person chose, and every
other plan answers "if you start now". Which also deleted a state: there is no "no start
date" any more, so no empty Date column to explain and no branch to carry it.

The rule generalises: **derived data may be cached, but it may not be persisted.** A cache
that is wrong is a bug you find in a session; a file that is wrong is a bug you find in a
diff, months later, in a project nobody can reconstruct.

One carve-out, stated so it stops looking like an oversight: **a derivation keyed by the
content hash of its input is not a stored answer**, because it cannot disagree with what it
came from — the input changing changes the key, and the stale entry is simply never read
again. The worked example is the spec module's PDF text layer
(`modules/spec/documents.py`): extraction is expensive, so the text is written into the
module's file area under a name derived from the content-addressed document blob, and the
read path falls back to extracting in memory when the file is absent. What the rule above
forbids is a persisted answer that *can* drift from its source; a hash-keyed derivation
has no way to.

## Status is an aspect, and step types are emergent

There is no `type` field on a step, and none is coming. A *release* is a step carrying the
`step_release` aspect; an *agent task* is one carrying `step_agent_instruction`; a step can
be both at once, which no exclusive type field could say. What a step "is" emerges from
which aspects have something to say about it — the same way its subtitle on the canvas
already does.

Status went the same way after being weighed as a model field. It is a stored fact, not a
derivation — the graph can say what is *ready*, but only a person or an agent can say what
is *finished* or *stuck* — yet storing it does not make it a field: `VALUE_FIELDS["step"]`
is still `("title",)`, and that is the central design decision of the model holding. As an
aspect it costs no project-format migration, absence encodes `pending`, both surfaces got
the verb from one declaration (`dplanner status set '<step>' done` is how an agent reports
back), and the derivation that wants it — the progression board's status-aware frontier —
is handed a `status_for(step)` function, exactly as `schedule()` is handed `days_for`.

The one enum also shows where an aspect's GUI does not have to be a tab: status registers a
*Status* submenu of checkable Step verbs instead, and the canvas right-click, the order
table, the menu bar and the palette all grew it from that single registration. The canvas
never learned the vocabulary either — it renders a neutral `NodeAccent(muted, badge)`, and
the composition root translates "done" into muted and a release label into the badge.

The *Type* submenu is the same idea one step further: one checkable toggle per type-ish
aspect (Release today), each independent, because a Type radio group would reintroduce the
exclusive type field this section rules out. Toggling Release on generates the next label
from the project's existing ones (`next_release_label` in `step_release/aspect.py`, shared
with `dplanner release set`); toggling off asks first, since the label is not kept — and
the Release tab stays visible on every step precisely so a generated label has somewhere
to be edited.

## Pass-forward is derived at read time

A handoff (`modules/step_handoff/`) stores only what the step itself says: a note, a scope
(`downstream` by default, `project` to reach everyone), files. Who *receives* it is never
written down. `handoff.inherited()` walks the topological order collecting the transitive
`requires` ancestors plus every project-scoped entry — the same rule as ordering, for the
same reason: `dplanner step link` rewires inheritance with no window running to notice, and
a stored answer would be wrong exactly when an agent is driving. The Handoff tab, `dplanner
handoff show --inherited` and the assembled agent prompt are three readers of that one
function, sharing even the text rendering, so no surface can describe an inheritance
another surface would dispute.

The seam repeats one level down: `inherited()` is handed a `files(step_id, module_id)`
function rather than a store, so the derivation runs headless and never learns where a
project lives.

## Running an agent launches a peer, not a task

*Run Agent* writes the briefing to a per-run temp directory — never the project, which
would dirty it and end up in version control — and spawns a terminal detached
(`start_new_session`). Deliberately **not** through `TaskRunner`: a task promises progress,
cancellation and a completion that returns to the GUI thread, and none of those are honest
about a terminal the user owns from the moment it opens. The agent reports back through the
CLI instead (`status set`, `handoff set`), which the two-writers machinery already handles.

The briefing opens with the **project's standing instruction** — the same module's prose on
the project node, edited in the project panel's Agent card and in the Agent tab's Project
part (two bindings over one field, one undo stack) — ahead of the step's own instruction and
the inherited context.

The briefing is deliberately **self-contained**: between the standing instruction and the
step's own sit the step's facts — its description (with attached figures), the requirements
it implements (titles *and* quotes, so the agent reads the obligation rather than chasing an
id), and the branch or PR the work lands on. The agent module renders these as opaque
blocks; the composition root words them, exactly as it words the preamble and epilogue,
because each names another module's vocabulary. Two block kinds, two framings: *parts* are
context handed forward from earlier steps (`### From "…"`), *sections* are facts about this
step (`## …`). One builder per kind lives in `modules/__init__.py` and both surfaces — Run
Agent and `dplanner agent prompt` — call the same two functions, so the window and the CLI
cannot brief a step two ways. An executing agent needs `agent prompt` and nothing else;
needing five verbs to reconstruct a briefing was the failure this replaces. Files attached at either level are **staged into the per-run
directory** beside `prompt.md` and referenced by their staged absolute paths: the agent runs
in the repository it opened at, so the prompt's file paths are absolute — anything else would point at
nothing it can reach. Asset names are content-addressed, so staging is a flat, collision-safe
copy; an unreadable path stays in the prompt as itself rather than vanishing.

Resolution is settings template first (`{script}`, `{prompt_file}`, `{workdir}`), then a
platform table, then `None` — and `None` is an answer: the fallback dialog delivers the
prompt itself, because the prompt is the deliverable and the terminal was only one way to hand
it over. `dplanner agent prompt` prints the same assembly (with the same absolute paths —
the run directory does not exist yet), and *Preview Agent Prompt* shows it in the window.

The assembly is also where the CLI grew the composition root's other seam:
`agent_cli.commands(prompt_parts=…, epilogue=…)` takes typed callables the way a module's
`Deps` does, supplied by `default_cli_commands()`. A `cli.py` never imports another module;
what crosses modules arrives as arguments — `skill_commands(specs, described)` made that
shape first, and this is its second use.

## Repository facts are derived from the project's directory

A project *lives in* its repository now, so "which repository does this project's work
belong to" stopped being a stored association and became a derivation: the repo root is
`find_repo_root(project directory)`, and the remote URL is git's own answer
(`origin_url`). This retired a whole module (`project_repo`) and the recorded trade that
funded it — per-machine checkout paths stored in shared files so the Qt-free CLI could
resolve them. Nothing stored can now disagree with git, which is the same argument as
never storing the topological order.

Two readers, both wired by the composition root: Run Agent receives `workdir_for`
(step → its project's repo root — where the terminal opens), and the github module
receives `repository_for` (step → the remote URL its PRs live under). `dplanner project
show` prints the same derived facts. A project directory whose repository has vanished
disables Run Agent with the reason in the label rather than guessing.

The git requirement is **gating at membership, honest afterwards**: File ▸ New Project
offers to `git init`, Open Project refuses a non-repo (the plan's history *is* the repo's
history now), but a project whose repository breaks later degrades to disabled verbs, not
a broken library.

## Save spans repositories; the exit dialog says what it records

One library can hold projects in several repositories, so *Save* (record a version) means:
**one commit per dirty repository, covering exactly that repository's project
directories**. The store owns the grouping (`LibraryStore.repo_groups()` — one provider
per distinct repo root, its git operations scoped to the member projects' paths), which is
what keeps two truths at once: several projects in one repo save as one commit, and a Save
can never sweep up the user's source code sitting beside the plan. Branch operations are
different — a branch belongs to one repository — so New/Switch Branch act on the focused
project's repo and are disabled, with the reason in the label, until a project is focused.

Quitting with uncommitted planning changes asks once, honestly: a dialog listing each dirty
repository (checked by default, with its file count and project titles) over one optional
commit message. *Commit & Quit* records the checked rows synchronously — the documented
save-at-quit exception to TaskRunner — and *Quit Without Committing* is a real choice, not
a scare: autosave already put the files on disk, so nothing is lost either way; only the
version history goes unrecorded until next time.

## Progression is the status-aware frontier

`ordering.ready()` answers what the *graph* allows — wave one, nothing waited on. During
execution that is the wrong question: a step deep in the graph whose prerequisites have all
been finished is launchable today, and no wave number says so. `domain/progression.py`
answers the execution question — every step in exactly one of *done / running / attention /
ready / upcoming / waiting* — and it is deliberately a **new derivation beside the old one,
not a refactor of it**: the frontier is a per-step check ("every `requires` target reads
done"), not wave membership, and the two only coincide in a project where nothing has been
finished yet. A test pins that equivalence; shared code would have pinned a coincidence.

The rules worth writing down, because each was a decision:

- **A stored claim beats the graph.** A step marked done whose prerequisites are not is
  honoured as done, and its dependents may become ready through it. The graph gates
  *launching*, not *recording* — an agent reporting `status set … done` out of order is
  reporting a fact, and a derivation that refused it would be arguing with reality.
- **Blocked is attention, not waiting.** A blocked step is stuck on a person, so it leads
  the running column wearing a warning rather than disappearing into the waited-on mass —
  it is the row that needs eyes, and the board exists to route eyes.
- **A blocked prerequisite still counts as "on the board"** for the one-move lookahead:
  its dependents stay in *upcoming*, pointing at it. The alternative — demoting them to
  waiting — would make the queue churn every time a prerequisite flips between in-progress
  and blocked, and would hide exactly the lane that stalled.
- **The lookahead is one move, not a forecast.** A step whose prerequisite is merely
  *upcoming* stays in waiting. Anything deeper is the order table's job.
- **The frontier ranks by unlocks** — the count of transitive not-done dependents — because
  all of the frontier is valid and the ranking is what makes some of it urgent. A done
  dependent is walked through but not counted: its own dependents still wait through it.

The seam is the one the schedule made: `status_for(step)` and `days_for(step)` are handed
in by the composition root from the aspects' Qt-free readers, so the domain never learns
what either is stored as, and the derivation is tested with a dict-backed function. Nothing
is persisted, for the ordering's reason — `dplanner status set` changes the answer with no
window running to notice. The tab (`modules/progression/`), `dplanner progression show` and
`--json` are three readers of the one function, so no surface can recommend a launch
another surface would dispute. The Run Agent button on a ready card is the same rule at the
module layer: it renders the real `agent.run` action's state — evaluated against a context
synthesised for exactly that card's step — so the gate's reason appears verbatim and no
second copy of "what launching needs" exists.

## Pressure points, named before they hurt

A whole-codebase review (2026-08) found the architecture holding; these are the places
where growth has a known cost curve, written down so the feature that crosses the line
recognises the moment. None needs action today.

- **`_briefing_sections()` in the composition root grows one hand-rolled block per aspect**
  with a briefing presence — four blocks today, each with its own empty-check. The exit is
  the shape `cli/lint.py` and `cli/authoring.py` already use: each module exports a Qt-free
  block builder, the root assembles the list. When the function hits about six blocks, make
  that move rather than adding a seventh `if`.
- **The step panel's tab order is a cross-module number line.** Each aspect module picks its
  `InspectorSection(order=…)` against numbers that live in six other packages — the GitHub
  module's comment literally names two of them. Fine at this size, and
  `tests/modules/test_aspect_editors.py` pins the resulting sequence; the tenth aspect
  author will have to read seven files to pick a number, and that is the moment the order
  belongs in one place (the composition root already knows it).
- **`project_editor` accretes by construction.** *Modules never import each other* means a
  feature that lives *on* the canvas — regions, named layouts, sorts, the minimap — cannot
  become its own package, so the surface-owning module grows instead (a quarter of all
  module code). The answer today is internal seams: Qt-free files per concern, split item
  and mode files, the keymap as a table. If a canvas feature ever needs its *own* Deps and
  registration, that is the day the module boundary rule earns a canvas-extension registry.
- **Every GUI test builds all modules.** The `services` fixture constructs the real
  composition root so a test can never drift from production wiring — a strong property,
  deliberately kept. The cost grows with the module count, and the `Deps` dataclasses are
  exactly what would make cheap isolated module tests possible; nothing uses that yet.
  If suite time becomes the complaint, the seam is already there.

## Where this is going

- **A second edge kind that can be drawn rather than only typed.** The mode stack is where it
  goes: a `relates` variant of the linking mode, and nothing else moves.
- **Rebindable keys.** `modules/project_editor/keymap.py` is the table a settings page would
  read; nothing reads it yet, which is the only reason it is a constant.
- **A schedule that knows about parallelism** — today's dates run the steps one after
  another down the order. The waves already say which of them could run side by side, so an
  earliest-finish walk is a change to `domain/schedule.py` and to nothing else.
- **Reports** — new folders in the index tree, which is the shape the registry was built for.
  `dplanner schedule show` is the first of them, and it lives in the module that owns the
  numbers rather than in the one that owns the table.
