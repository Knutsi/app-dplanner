# DPlanner's shape, and why

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

## Where this is going

- **A graph editor** — a canvas for steps and their edges. It is the module that will take
  the `step` CLI group with it; a `CliCommand` moves between packages without anything else
  changing.
- **Editors for the aspects** — a card per aspect in a step's detail panel. Each is a
  `register()` that is currently a documented no-op, and the data they will edit is already
  being written.
- **Estimation and prioritisation over the graph** — `estimate rollup` is the first inch of
  it. What a planner is really for is answering "what can I start now, and when does this
  land", and both questions are walks over the graph reading aspects.
- **Reports** — new folders in the index tree, which is the shape the registry was built for.
