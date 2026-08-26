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

## Product → Project → Step

A planner needs a level above "the project": the same codebase accumulates projects over
years, and what is true of the codebase — where its repository is, what it is called — is not
true of any one project. So the top level is the **Product**, and a window holds exactly one.
Opening another is a new window, which keeps every window's undo stack, autosave and
selection about one thing.

Below that, a **Project** is a unit of work with an end, and a **Step** is a node in its
graph.

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
resolution is tolerant instead: `Product.requires()` skips ids it cannot resolve.

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
unfinished — the `data_format` declaration is what makes the workspace forward-compatible,
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

The argument for the tree is that it shows the workspace's *shape* — projects, and the steps
under them — where a tab set shows one feature and hides the rest. The argument for deleting
the old one is that anything a page could hold is a folder here, so keeping both would have
been two navigation mechanisms competing for the same 275 pixels.

Three things live in the panel rather than in each segment, because a shared tree is not the
same problem as a stack of independent widgets: **selection is published exactly once** (Qt
selection is per-tree and `ContextService` has one selection scope, so segments would
otherwise fight over it); **a segment supplies its own menu** rather than the spec naming a
`MENU_STRUCTURE` menu, because a menu name is application vocabulary and has no business in
a framework spec; and **expansion state survives a rebuild** through shared helpers, because
rebuilding on change is the normal case and that bookkeeping is what every segment would
otherwise copy.

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
   undo.push(command)   (the window)        command.redo(product)   (the CLI)
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
the end. Every signal on `Product` carries one, with no exception, because a convention with
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

## How a panel gets editors it has never heard of

The step detail panel shows a tab per aspect — Estimate, Ticket, Description, Agent — and
nothing in it knows those four exist. Three seams do that, and they are worth naming because
the same three answer every "feature A needs feature B" question this application will have.

**A provider module.** `step_properties` owns the panel and `register()`s nothing at all. Its
whole job is `create_panel()`. That looks odd until a second host wants one, at which point it
is the only arrangement that does not duplicate the panel or make one feature import another.

**A consumer-owned Protocol.** `project_editor` declares the interface it needs — `widget`,
`show_step`, `dispose` — in its own file, and types its `Deps` field as
`Callable[[QWidget], StepPanel] | None`. The real panel satisfies it structurally and never
learns who hosts it. The `| None` is not defensiveness: an editor with no panel is a legitimate
build, and saying so in the type is cheaper than discovering it later.

**A registry for the contributors.** Aspect modules register an `InspectorSection` into
`services.inspector_sections`; the panel reads that registry when it is *built*, not when the
modules load, so a contributor's position in the composition root is free.

The composition root is the only place that knows all three, and it says so in ten lines:

```python
step_properties = StepPropertiesModule(
    StepPropertiesDeps(..., sections=services.inspector_sections)
)
project_editor = ProjectEditorModule(
    ProjectEditorDeps(..., detail_panel=step_properties.create_panel)
)
projects = ProjectsModule(ProjectsDeps(..., open_project=project_editor.open))
```

This is Writer's arrangement, borrowed wholesale. Its `segment_properties` module serves a
corkboard, a segment editor and a continuous editor the same way, which is the evidence that
the shape survives contact with a third host.

The order view's start-date bar is the same three seams again, one layer along: `estimation`
provides a `create_start_bar()` and registers nothing for it, `step_order` declares a
`StartBar` Protocol of its own and takes a `Callable[..., StartBar] | None`, and the
composition root is the only file that knows both names. The reason the bar is a `create_…`
rather than a registry entry is worth stating: a registry is for *whoever turns up*, and this
control belongs to exactly one surface. When there is only one host, a registry is ceremony
that hides which module supplies what.

**What the panel is not.** The project's name and summary are not a section. An
`InspectorExtension`'s whole contract is `show_target(step_id | None)` — one target
vocabulary — and making the project form a peer would force every aspect editor to answer
"what if this is a project?" and hide itself, which is precisely the conditional the registry
exists to delete. So the panel has two pages, the host supplies the empty one, and the project
form arrives from `project_editor` as a widget the panel never inspects.

## The graph, and what it stores

A project is a graph, so the tab is a canvas: `QGraphicsView` gives selection, dragging,
hit-testing and zoom for free. Writer's corkboard is 2,200 hand-rolled lines because cards
flow in a grid; free positions are the case Qt already handles.

Two decisions keep it small. **Nodes diff, edges rebuild** — a node may be under the mouse
mid-drag and must keep its identity, while edges never are and there are only tens of them, so
reconciling one and replacing the other avoids a diffing engine. **The scene reports, the
activity commands** — every gesture ends in a signal, and the activity turns it into something
on the undo stack, so a drag is undoable and the model stays the only authority on what a legal
graph is.

That last point is why `Product.link_refusal()` exists. A link drag needs to know *before* the
drop whether an edge would be a cycle, and the alternative — a second reachability check in the
view — is two implementations that will eventually disagree. So the refusal is a question the
model answers, `set_edges` asks it before writing, and the canvas asks it under the cursor.
There is no error dialog anywhere in the interaction because there is never anything to
apologise for.

**Node positions are stored, automatic layout is not.** A step nobody has moved is placed by
`requires` depth, recomputed each time the project opens. Persisting that would mean merely
opening a tab dirtied the workspace, autosave flushed it 1.5 seconds later, and every step an
agent created through the CLI grew a position file the next time a window happened to open. A
test asserts the workspace is unchanged after a tab is opened, because that is the kind of rule
that decays silently.

## Two writers, one workspace

The scenario DPlanner is built for — an agent refining a plan *with* the user — means the
CLI writes while a window is open on the same folder. The framework's ordinary contract,
"memory is authoritative and disk follows", quietly loses data under those conditions: a
flush 1.5 seconds after the user's next keystroke rewrites nodes from a model that never saw
the agent's edit, and orphan removal deletes a directory the agent just created.

A lock would be the cheap fix and it is the wrong one, because both writers being live *is*
the feature. So the rule is instead:

> **Nothing writes over a file it has not seen.**

`ProductStore` records what the workspace looked like when it last read or wrote it and
raises `StaleWorkspaceError` rather than flushing over anything that changed underneath.
Around that one check:

- A **CLI run** reports it as one line and writes nothing. A run is a transaction, so
  running it again picks up the change and is correct.
- A **window** with nothing pending simply reloads — `AppSession.reload()` rebuilds the whole
  application, which is what makes a reload correct, at the cost of open tabs and undo
  history.
- A **window with unflushed edits** stops: autosave keeps its marks and pauses itself, and
  *File ▸ Reload from Disk* makes the choice the user's. Nobody else can make that call.

The same check is why **two CLI runs need no lock between them**: the second is refused for
exactly the same reason and can be run again. One mechanism, three cases.

## The skill is a projection, not a document

An agent has to be told what DPlanner is and what it can do. Writing that by hand means
writing every command twice, and the copy is wrong within a month — a skill that describes a
flag which no longer exists is worse than no skill, because it is believed.

So `dplanner skill install` **renders** `SKILL.md` and `reference.md` from the same
`CliRegistry` that `--help` renders. The hand-written half is only what a registry cannot
know: what a product is, and how to work with a person. Everything else — the command index,
every argument, the aspects, the edge kinds — comes from the objects themselves.

Two details make that safe. The parsers are built at a **fixed width** rather than the
terminal's, because the output goes into version control and a diff that depends on who ran
it is a diff nobody reads. And `build_tree()` hands back the verb parsers it built rather
than the skill digging them out of argparse afterwards, so one tree serves both.

MCP was considered and deferred. A CLI reaches every agent, including ones with no MCP
client; it is useful to people and to CI; and it needs no process lifecycle. If a
Claude-specific integration is wanted later, `dplanner mcp serve` is a thin adapter over the
same registry and introduces no second description of any command.

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

The rule generalises: **derived data may be cached, but it may not be persisted.** A cache
that is wrong is a bug you find in a session; a file that is wrong is a bug you find in a
diff, months later, in a workspace nobody can reconstruct.

## Where this is going

- **More of the canvas** — panning beyond the scroll bars, edge selection and deletion, and
  a second edge kind that can be drawn rather than only typed.
- **A schedule that knows about parallelism** — today's dates run the steps one after
  another down the order. The waves already say which of them could run side by side, so an
  earliest-finish walk is a change to `domain/schedule.py` and to nothing else.
- **Reports** — new folders in the index tree, which is the shape the registry was built for.
  `dplanner schedule show` is the first of them, and it lives in the module that owns the
  numbers rather than in the one that owns the table.
