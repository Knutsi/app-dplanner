# Notes for app-framework

DPlanner was generated from [app-framework](https://github.com/Knutsi/app-framework), and
building it taught us things about the framework that the framework does not know yet. This
file is where those go, so that a later pass can carry the good ones upstream instead of
rediscovering them.

**The rule: if you change anything under `framework/` or `core/`, add a row here in the same
commit.** A divergence nobody wrote down is one that gets merged away by accident the first
time somebody diffs against upstream — and `.appframe` records the commit we forked from
precisely so that diff stays possible:

```bash
git -C ../app-framework diff <revision> -- template/
```

Nothing here is a complaint. The template is a running application on purpose, and most of
what follows is only visible *because* it runs.

---

## 1. Changes we made to `framework/`

Each of these is live in DPlanner. The last column is our honest read of whether it belongs
upstream, not a decision.

### The sidebar is one index tree, not a tab set

**What.** `framework/sidebar.py` is gone. `framework/index_panel.py` replaces it with a
single `QTreeWidget` whose top-level folders come from an `IndexSegmentRegistry`; a module
registers an `IndexSegment` and owns one folder and everything under it. `AppServices` lost
`sidebar_panels` and `utility_tools` and gained `index_segments`; the builder installs the
panel and pre-registers nothing.

**Why.** A tab set shows one feature at a time and makes every feature a peer; an index shows
the workspace's *shape* and grows by a folder rather than by another tab. Once the tree
existed, the tab set had nothing left that a folder could not hold, so keeping both would
have been two navigation mechanisms competing for the same 275 pixels.

**Three things that turned out to belong in the panel, not in the segments** — and this is
the part worth carrying upstream even if the rest is not:

- **Selection is published exactly once.** Qt selection is per-tree and `ContextService` has
  a single selection scope, so the panel groups the selected items by owning segment, asks
  each for its `ContextNode`s, and sets the scope once. Left to the segments, two of them
  would overwrite each other.
- **A segment supplies its own `QMenu`.** We nearly put `menu: str` on the spec; that would
  have leaked application vocabulary (`"Project"`) into a framework dataclass. A segment has
  its own `Deps` and can call `build_menu` itself.
- **Expansion state survives a rebuild**, via `expansion_of` / `restore_expansion` — plain
  functions over the items, so a segment needs no reference to the panel. Roughly a quarter
  of the old `plan_tree` module was that bookkeeping, and every segment would have copied it.

**Upstream?** The registry and the three rules above, yes — they are generic and the
template's own doctrine ("if a feature cannot be expressed through one of the registries, the
framework needs a new registry") points straight at it. *Deleting* `sidebar.py` is our call,
not necessarily the template's: an application that genuinely wants pages should still be able
to have them. A reasonable upstream shape is both registries side by side, with the walkthrough
recommending the tree.

### `AutosaveService` survives a refused write

**What.** `flush_now()` wraps `persister.flush(dirty)`; on an exception it puts the batch
back, calls `pause()`, and emits a new `failed: Signal[Exception]`.

**Why.** A store can legitimately decline to write (ours does — see §3). The two obvious
behaviours are both wrong: dropping the marks loses the user's edits, and retrying every
1.5 seconds turns one problem into an endless one. Keeping the batch and pausing makes the
decision somebody else's, and `resume()` is how they say to try again.

**Upstream?** Yes, unreservedly. It costs six lines and it is a hole in the current contract
regardless of why a flush failed — a full disk would have had the same outcome.

### `TabHost.close_activity(activity)`

**What.** The symmetric partner of `focus(activity)`. Named for the activity because a
`TabHost` is itself a `QWidget` and `close()` is taken.

**Why.** `close_current()` was the only way to close a tab, so a feature whose subject was
deleted had no way to take its tab with it — the alternative is reaching into the tab widget,
which is exactly the shortcut the layering rules exist to prevent. We hit this the first time
a project was deleted while its tab was open.

**Upstream?** Yes. Small, obviously missing once you need it.

### `AppServices.modules`

**What.** The constructed module objects, in registration order, on the services bundle.

**Why.** `services.py`'s own docstring says the bundle exists "so a test can build a whole
application and then reach into any part of it" — and the one part it could not reach was a
module. We needed it to assert on a module's internal state from a test; the alternative was
asserting only on side effects, which is thinner than it should be.

**Upstream?** Probably. The risk is that it looks like a way for modules to find each other —
it is not, because modules never see `AppServices`, and `test_architecture.py` enforces that.
Worth a sentence in the docstring saying so.

### `framework/window_watch.py`

**What.** A `WorkspaceWatcher` that polls a repository through a one-method
`WatchableRepository` protocol and emits when the workspace changed underneath it.

**Why.** See §3 — this is the framework half of "two writers, one folder".

**Upstream?** Only if the repository-side half (§3) goes too. On its own it watches for
something nothing reports.

---

## 2. Conventions the template documents that we had to change

### A module package's `__init__.py` must not re-export the Qt class

**What.** `CLAUDE.md` recipe step 6 and the walkthrough's step 5 both say to re-export
`<Name>Module` and `<Name>Deps` from the package `__init__.py`, so the composition root
imports from the package rather than from a file inside it. We made every module's
`__init__.py` a docstring instead, and the composition root imports
`from appname.modules.<name>.module import …`. The module imports in
`default_modules()` also moved inside the function.

**Why — and this is the number worth carrying upstream more than the change itself:**

```
import appname.modules      before: 792 ms, PySide6 loaded
import appname.modules      after:   19 ms, PySide6 not loaded
```

`libQt6Gui` links `libEGL`, `libGL`, `libGLX`, `libxkbcommon` and `libfontconfig`. So the
convention is not merely slow — it makes the composition root *unimportable* on a machine
with no graphics libraries. That did not matter while the window was the only front door. The
moment an application grows a second, headless one (§4), the recipe's step 6 is what stops it
working, and the failure is an `ImportError` at startup rather than anything that looks like a
design problem.

**Upstream?** We think yes, and it costs nothing for a GUI-only application. The docstring
each `__init__.py` keeps is arguably better documentation than the re-export was. If the
template would rather keep the re-export, the walkthrough should at least say what it costs.

**Also worth a line in the docs:** the composition root's promise is "read this one file to
know the application". Moving the imports inside `default_modules()` keeps that promise —
the inventory is the first fifteen lines of the function instead of the file — and
`test_architecture.py`'s `ast.walk` scanner sees them either way.

### `module_data` is not enough: a module also wants prose and files

**What.** DPlanner's store gives a node three sibling stores under `modules/`, with one
naming rule:

| | Path | Reached through | Undoable |
|---|---|---|---|
| structured data | `modules/<id>.json` | `node.module_data["<id>"]` | yes |
| one prose document | `modules/<id>.md` | `node.module_text["<id>"]` | yes, positionally |
| files | `modules/<id>/` | `store.files(node_id, "<id>")` | no |

**Why.** Our description aspect needed markdown *and* images. Markdown inside a JSON value is
one escaped-newline line per edit — against everything `FORMAT.md` says about diffs — and it
also loses the text stack: `apply_text_edit`'s positional splice with its staleness check,
`EditTextCommand`'s per-burst coalescing, and origin-based echo suppression. A module storing
prose in `module_data` would end up rebuilding all of that, badly.

**The surprising part:** keying prose by module id was *less* code than the template's own
example. `Task` hardcoded two prose fields (`description`, `notes`), each with its own signal
and its own `Field` class. One `module_text` namespace with one signal and one
`ModuleTextField(product, node_id, key)` replaced both **and** made prose available to every
module. That is the strongest argument for it: it is a simplification that happens to add a
capability.

**Upstream?** The concept, yes; the code lives in `domain/store.py`, which is the
application's. What the *template* would change:

- `core/repository.py`'s `DataOwner` protocol names only `module_data`. If prose is a
  first-class second store, it names `module_text` too.
- The template's example store, so the walkthrough has something to point at.
- `FORMAT.md`'s "Module data" section becomes "What a module may store".
- `core/module_data.py` is untouched either way — versioning stays a JSON concern, and the
  module owns its own prose and file formats. That separation held up well.

**One trap we hit**, which any implementation will hit: a file area writes straight through
the `StorageProvider`, so a store that tracks what it has written (§3) sees its own asset as
somebody else's edit. The area needs a callback back into the store.

---

## 3. Two writers, one folder — the framework's biggest missing assumption

**What we found.** The framework's contract is "memory is authoritative, disk follows"
(`autosave.py`'s docstring). That is exactly right for one window and no other writer, and it
quietly loses data the moment there is a second one. In DPlanner the second writer is a CLI
an agent drives, but a file sync, a colleague's merge into a shared git checkout, or a second
copy of the same application would all do it. The sequence:

1. Something else writes `<node>/step.json`.
2. The user types one character in the window.
3. 1.5 seconds later autosave flushes and rewrites that node from a model that never saw the
   other edit — and `_remove_orphans` deletes any directory the other writer created.

Nothing anywhere notices. There is no filesystem watching in the template; `worktree_changed`
fires only on a branch switch or a pull.

**What we did.** One rule, three consequences:

> **Nothing writes over a file it has not seen.**

`ProductStore` records what the workspace looked like when it last read or wrote it (size and
mtime per file) and raises `StaleWorkspaceError` rather than flushing over anything that
changed underneath. Then:

- A **CLI run** reports it as one line and writes nothing — a run is a transaction, so
  running it again is correct.
- A **window with nothing pending** reloads through the existing `AppSession.reload()`.
- A **window with unflushed edits** stops: autosave keeps its marks and pauses (§1), and a
  *Reload from Disk* action makes the choice the user's.

**The result worth carrying upstream is the simplification, not the code.** We had planned an
advisory lock for CLI-vs-CLI on top of all this. Once the store refused stale writes, the lock
was unnecessary — the losing run is refused for the same reason and can just be re-run. One
mechanism covers three cases.

**Upstream?** The store-side check belongs in the application's store, so what the template
can offer is the *shape*: a `changed_underneath()` on the repository protocol, the
autosave-survives-failure behaviour (§1), the watcher (§1), and a paragraph in the report
saying that "memory is authoritative" has a precondition. We would rather the template said
this out loud than shipped a half-implementation.

---

## 4. A headless surface is a real layer, and the template has no room for it

**What we did.** Added `cli/` between `domain/` and `framework/` — Qt-free, importing `core`
and `domain` only — plus `entry.py` beside `app.py` that dispatches: a registered command word
runs the CLI, anything else opens the window. A feature contributes `modules/<name>/cli.py`
beside its `module.py`, and `modules/__init__.py` grows `default_cli_commands()` next to
`default_modules(services)`.

**The one rule that made it work**, and the thing we would put in the report if we put in
nothing else:

> A menu action and a CLI verb build the **same object from `domain/commands.py`**. The GUI
> pushes it onto the undo stack; the CLI applies it and lets the store flush.

Everything follows. A CLI edit is undoable in a window. Neither surface can grow a behaviour
the other lacks without somebody editing that one file. The model's refusals are identical on
both sides — the CLI just renders them as a line instead of a dialog. We expected the shared
seam to be a service layer and it turned out to be the command objects, which already existed.

**Two traps, both of which bit us:**

- **`migrate_module_data` is called in exactly one place**, `AppBuilder.build()`. A second
  entry point that opens a repository and writes to it silently skips module-data migration —
  a module's writer then stamps the current format onto one node while its siblings stay
  behind, and the next GUI open migrates those and leaves the poisoned one alone. Corruption
  nobody finds for months. Whatever the template says about second entry points should say
  this first. (We wrapped open → migrate → collect dirty → run → flush → close in one context
  manager so no verb can forget either half.)
- **The entry-point dispatch has to skip option values.** Ours read the path in
  `dplanner --workspace ~/w project list` as the first command word and opened a window
  instead of listing anything. Found by running it, on a real screen, not by any test.

**Upstream?** Not as code — an application that only wants a window should not carry a CLI
layer. But the template's architecture report has a section for "where state lives"; it could
use one for "if your application grows a second front door", carrying the shared-command rule
and both traps.

---

## 5. Findings that need no change here, but the template should know

- **`ExportRegistry` has zero clients — in the template too.** Nothing in the generated
  application registers an `ExportSpec`, and nothing shows an export dialog, so the registry
  is documented in the ten-registry table and never exercised. We went to use it and found
  there was no dialog to register into, and put export in the CLI instead. Either the template
  should demonstrate it end to end or the report should say it is a seam, not a feature.
  (Related: `ExportSpec.run` takes a destination `Path`, so it cannot express "write to
  stdout". Anything wanting both needs a plain serializer underneath, which is what we did.)
- **`DESIGN.md` points at `modules/example_editor/`** as the reference surface. That module is
  meant to be deleted, and the reference survives the bootstrap into every application that
  deletes it — a dangling pointer in the document that is supposed to be the standard. Either
  the bootstrap should rewrite it or the standard should describe the surface rather than name
  a file.
- **`theme/theme.qss` is a different application's chrome.** It ships with rules for a
  Corkboard, a Binder, Zen mode, a Reader, Read-throughs, a Manuscript editor and an Edit
  review dialog — roughly half of its 860 lines styling widgets no generated application will
  have, under a header that still says "Writer". The generic vocabulary in it (`#ToolCard`,
  `#InspectorCaption`, `#PrimaryButton`, the scrollbars, the menus) is genuinely good and
  worth keeping; the rest is confusing to a new developer, who cannot tell which names are
  contract and which are leftovers.
- **`SidebarShell._add_panel` ended with an unconditional `setCurrentIndex(0)`.** Correct,
  because registration only happens at startup — but it is the kind of thing that stops being
  correct silently if registration ever becomes dynamic. Worth a comment upstream if the tab
  set survives.

---

## 6. Things we deliberately did *not* push into the framework

Recording these so a future backport does not over-reach:

- **`StaleWorkspaceError` and the disk snapshot live in `domain/store.py`**, not in `core/`.
  What "changed underneath" means depends on the format, and a core implementation would have
  to guess. The protocol method is the framework's business; the answer is the store's.
- **`AspectSpec` lives in `domain/`, and there is no registry class for it.** Each aspect
  package exports a module-level `SPEC` and the composition roots name the packages. We wrote
  a registry first and deleted it: there was nobody to arbitrate, and a registry in `domain/`
  fed entirely from `modules/` is an inverted dependency wearing a type.
- **Lookup by "an id, a folder name, or part of a title" lives in `cli/`**, not in the model.
  It is a command-line affordance — resolving what a person typed — and the model should not
  have opinions about fuzzy matching.
