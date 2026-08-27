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

### `ActionToolbar` had never been instantiated, and it showed

**What.** Three changes to `framework/toolbar.py`, all found the first time the class was put
on screen (the graph canvas's verb strip in `modules/project_editor/`):

- Buttons take `Qt.FocusPolicy.NoFocus`. Without it, clicking a toolbar button moves the
  keyboard off the surface the button just acted on. A canvas with its own key bindings
  notices immediately; a form would notice eventually.
- Buttons take a `Fixed` size policy. A `QHBoxLayout` short of room shrinks its children to
  their minimum, and a 10 px wide button holding a 16 px glyph shows neither icon nor label —
  it renders as an empty rounded rectangle, which reads as a bug rather than as a tight fit.
- `_refresh` now sets the tool button style: `ToolButtonTextBesideIcon` when the button has
  text, `ToolButtonIconOnly` when the per-action override emptied it. `QToolButton` defaults
  to icon-only, so before this a button with a label and no icon drew nothing at all — which
  is what every caller with no `set_button_icons` call would have got.

**Why it belongs upstream.** None of the three is DPlanner-specific; all three are what the
class already promised (`set_button_icons`'s docstring describes exactly the icon-only case it
could not produce). Worth taking together with a test that puts one on screen — the class was
correct on paper for as long as nobody rendered it.

**What we did not change.** The multi-pane caveat in its docstring — a toolbar shows the
*active* pane's action state, not its own tab's — is still true and still the right answer.
The suggested fix there (`set_active(bool)` rather than a context per group) remains unwritten
because in practice the dimmed tab title already says which pane speaks.

### The sidebar is one index tree, not a tab set

**What.** `framework/sidebar.py` is gone. `framework/index_panel.py` replaces it with a
single `QTreeWidget` whose top-level folders come from an `IndexSegmentRegistry`; a module
registers an `IndexSegment` and owns one folder and everything under it. `AppServices` lost
`sidebar_panels` and `utility_tools` and gained `index_segments`; the builder installs the
panel and pre-registers nothing. *(Since revised: there is no sidebar slot at all now — the
tree is one panel anchored in the left area. See "Panel areas" below.)*

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

### `framework/prose_section.py`

**What.** An `InspectorExtension` over one prose document: a `QPlainTextEdit` that re-binds
when the panel shows something else and detaches when it shows nothing. It takes a
`Callable[[str], TextField | None]`, so it knows nothing about any model.

**Why.** The framework already owns the hard half of editing prose — `TextBinding` turns a
keystroke into an undo command and keeps other views in sync — and left the easy half to
every caller. That half is small and quiet when it is wrong: a binding not closed before
re-binding leaves the old one listening, and one left pointing at a deleted node reaches the
model on the next keystroke and fails to find it. We wrote it twice within an hour (a step's
description and its agent instruction) before extracting it.

**One thing it fixes on the way.** `TextBinding.close()` disconnects but never reparents or
deletes, and the binding is parented to the editor — which outlives it. A panel that re-binds
on every selection change therefore leaves one inert `QObject` behind per click, for the life
of the tab. `ProseSection` calls `setParent(None)` after `close()`; the better fix is
`deleteLater()` inside `close()` itself, since the docstring already promises that "the
editor may outlive the binding and be bound again later".

**Upstream?** Yes, and the `close()` fix regardless of the rest.

### Tab groups, and the framework's first focus watcher

**What.** `TabHost` holds a `QSplitter` of up to three `QTabWidget`s instead of one, and its
public API is unchanged — `open`, `activities`, `current_activity`, `close_activity`,
`set_tab_title` all mean exactly what they meant. `builder.py` and `main_window.py` needed no
edit at all, and neither did any module. New: `move_current_left/right`, `group_count`,
`can_move_*`, `dispose`.

**Why the API could stay still.** `_activities` was already keyed by page widget rather than
by tab index, so it was already group-agnostic; only `_current` assumed one focused tab in the
whole application. That is a good property to preserve upstream if the tab host is ever
touched.

**The interesting half is the watcher.** "Which pane did the user last interact with" has no
answer in Qt, and the template answers it nowhere. It needs **both** `QApplication.focusChanged`
*and* an application-level `MouseButtonPress` filter: focus alone misses a click on anything
that takes no focus — a caption, a heading — and the filter alone misses keyboard traversal.
The filter must also see the press *before* a right-click builds its menu, since `build_menu`
reads the context as it opens.

Three things that were not obvious and cost time:

- **The filter must exist only while the window is split.** It is application-wide, so it sees
  every mouse press in the program; installing it unconditionally cost the test suite 30% and
  bought nothing, because with one pane there is nothing to decide.
- **It must be disposed.** A host outlives its window when a workspace is reopened, so
  `TabHost.dispose()` goes in `close_hooks` beside the index panel's. Without it the suite
  accumulates one live filter per built session.
- **Focus must follow a programmatic move**, or the watcher hears the leftover focus in the
  pane the tab just left and puts the user back where they were not.

**Later addition: the tab bar's right-click.** `TabHost` now sets `CustomContextMenu` on each
group's tab bar, makes the tab under the cursor current, and emits
`tab_menu_requested: Signal[QPoint]`. It builds no menu itself — what a tab offers is
application vocabulary, and a framework that knew the answer would have to know the action
registry. `after_current()` was added beside it, because "the tabs to the right of this one"
is the one fact about groups the host cannot hide: a caller working it out would have to be
told the groups exist. Both belong upstream with the groups, if the groups go.

**A pre-existing bug it surfaced.** `setMovable(True)` means a drag-reorder fires
`currentChanged` with the *same* page current, and `_on_current_changed` treated it as a
switch: deactivate, clear both scopes, reactivate, seal the undo burst, flush autosave — for a
change that changed nothing. It is in the template too. The guard is on the (group, activity)
pair, not on the activity, because a move legitimately changes the group while keeping the
activity.

**Upstream?** The reorder guard, unreservedly. The groups and the watcher, as a pair, if the
template ever wants a split view — and the three notes above are most of what makes it work.

### `framework/window_watch.py`

**What.** A `WorkspaceWatcher` that polls a repository through a one-method
`WatchableRepository` protocol and emits when the workspace changed underneath it.

**Why.** See §3 — this is the framework half of "two writers, one folder".

**Upstream?** Only if the repository-side half (§3) goes too. On its own it watches for
something nothing reports.

### The tab host the contract promises, and where we put it

**What we found.** `framework/inspector.py` has said since the template that a section
"appears as a sibling tab beside whatever else is registered", and `#InspectorTabs` sits in
`theme.qss` styling a `QTabBar` that nothing creates. **No host has ever been written** — not
here, and not upstream, where `example_editor` renders a `CardStack` instead. So the
ten-registry table documents a surface that has no implementation, and the one worked example
contradicts the docstring above it.

Writer resolves it by hand: `segment_properties/panel.py` builds the `QTabBar` over a
`QStackedLayout` itself, and `text_panel/panel.py` builds the card variant, both taking
`sections: Sequence[InspectorSection]` as a constructor argument. Two hosts, two hand-rolled
tab/visibility loops.

**What we did.** The same — the tab host lives in `modules/step_properties/panel.py` — and
deliberately did *not* extract `framework/inspector_panel.py`, because extracting a widget for
one caller is speculative and our panel's own title header and host-supplied empty page are
host concerns that would have to leak in as parameters.

**Since revised, and half the gap is now closed.** `framework/panels.py` (below) supplies the
*anchoring* host — where the panel sits, whether it is on screen, what its header says — while
each panel still renders its own sections. That turned out to be the honest split: "where does
this surface live" is framework, "what does a section look like" is not. It also removed the
host-supplied empty page, which was the awkward parameter above: there is no host any more.

**Upstream?** The gap is real and worth closing, but the shape is not obvious yet: three
implementations exist (Writer's two, ours) and none of them is quite the others. Either ship
a host and make the docstring true, or change the docstring to say the framework supplies the
*contract* and each host renders it. What should not survive is the current position, where a
registry is documented as producing tabs and every implementation produces something else.
Note also that `tab_visible()` and `tab_visibility_changed` are honoured by **no** host in
either upstream repo; ours is the first.

### Panel areas: the window learned where a surface can be anchored

**What.** New `framework/panels.py`: `PanelArea` (left/right/bottom), `PanelSpec`,
`PanelRegistry`, a `ContextPanel` protocol, and `PanelDock` — a `QSplitter` that is the
window's central widget and holds the tab host in the middle with an area on three sides.
`AppServices` gained `panels`. `framework/window.py` lost `SidebarHost` and gained `PanelHost`
(`set_panel_visible` / `is_panel_visible` / `panels_changed`). `main_window.py` lost its
sidebar slot and its width persistence (~45 lines) and gained three delegates.
`framework/widgets.py` lost `stored_inspector_width` / `remember_inspector_width`.
`builder.py` registers the index tree as the framework's own panel rather than calling
`set_sidebar`, and `WindowFactory` now takes `(TabHost, PanelDock)`.

**Why.** DPlanner's step detail panel was built inside `ProjectActivity`, so a split window
showed two of it. The template has the same shape available to it — one hard-coded sidebar
slot, and any other anchored surface built inside a tab — so it has the same bug waiting.

**Three things that were not obvious and cost time.**

- **`isVisible()` is the wrong question while a window is being built.** Panels are installed
  during module registration, long before anything is shown, and a widget whose window is not
  visible is not visible however it was set. Every visibility decision in the dock is
  `isHidden()`.
- **A `QSplitter` normalises `setSizes` against its own current width**, so sizing the areas
  before the first layout pass silently turns pixel widths into ratios — a 275 px sidebar
  becomes 29 px in a 1100 px window. The dock therefore *is* the splitter rather than holding
  one (no layout pass in between), caches the stored sizes in memory, and re-applies them from
  `resizeEvent`. Re-applying is safe because what it applies is what the user last dragged to,
  and with stretch factors `[0, 1, 0]` a wider window is simply a wider centre.
- **The border belongs to the area, not the panel.** `#IndexPanel` had `border-right` and
  `#InspectorPanel` had `border-left`; a panel that can move between areas cannot carry a
  side. Three `#PanelArea*` rules now own it.

**Upstream?** Yes, and this is the one we would push hardest. It subsumes the sidebar slot
rather than sitting beside it, deletes two copies of "remember a splitter width", and gives
the template an answer to "my feature needs a surface that is not a tab" that does not end in
a widget built inside an activity. The `ContextPanel` contract is the interesting half: one
subscription in the dock, and a panel that already reads the context follows the active pane
for free, given the "only the active pane publishes" rule the tab groups needed anyway.

### One mutator that broke the framework's own convention

**What.** `Product.set_module_data()` and `module_data_changed` were the only mutator/signal
pair in the model without an `origin`, despite the model's own docstring saying "every mutator
takes an origin". `SetModuleDataCommand` was likewise the only command without a
`view_origin`.

**Why it mattered here.** It is invisible until a *view* edits module data. The moment an
aspect editor existed, it heard the echo of its own write and reloaded the field the user was
still typing in. The template has no such editor, which is exactly why the gap survived.

**Upstream?** The template's `example_notes` writes module data from a card and dodges the
problem with a `_loading` flag. That works, and it is the wrong lesson: the framework already
has a mechanism for this and the example quietly declines to use it. Worth fixing in the
example even if the model change is the application's business.

### `ActionSpec.palette`: a verb in two menus is two specs, and the palette lists verbs

**What.** A `palette: bool = True` field on `ActionSpec`; `CommandPalette` skips specs that
set it False. Nothing else reads it.

**Why.** "Show Order" belongs in the Project menu *and* in the Step menu (the canvas
right-click renders Step). A spec has one `(menu, group, order)` placement, so the second
placement is a second spec sharing the same `state`/`run` — twelve declarative lines. But the
palette lists *verbs*, not placements, and two specs with the same label would show as two
identical adjacent rows. The flag lets the mirror opt out.

**The rejected generalisation, for the record.** Letting one spec name several menus needs a
per-menu `(group, order)`, a per-placement sort key, and a rework of `DynamicMenuBar`'s
bookkeeping — `_keys` holds one sort key per QAction and `_refresh_decorations` reads that
key's group index for *its* menu. All of that to avoid one shared-callback spec; the
two-specs shape is plainly simpler.

**Upstream?** Yes, whenever a verb belongs in two noun menus — which any application with
context menus per noun will eventually hit.

### `build_menu` can render just one submenu

**What.** An optional `submenu: str | None = None` parameter. `None` is today's behaviour —
the whole menu, flattened. Naming a submenu renders only the specs carrying that `submenu`,
still flat.

**Why.** DPlanner's tab verbs moved from a top-level Tab menu into View ▸ Tabs, and the tab
bar's right-click renders those verbs. Building "View" for that popup would drag in panels,
zoom and themes; building the child menu is what the gesture means. Popups deliberately
flatten submenus already (the canvas's Step popup flattens Status and Go), so "render just
this submenu, flat" is the same shape one notch narrower.

**Upstream?** Yes — any application that folds a noun's verbs into a submenu and gives that
noun a right-click needs exactly this.

### A theme change is not one event, and three surfaces missed it

**What.** Three changes, all found by switching the theme with a graph on screen.

- `framework/tabs.py` gained a `changeEvent` that re-runs `_paint_active()` on
  `QEvent.PaletteChange`. The host dims the tab titles of the panes the user is not in, and it
  does so with `QTabBar.setTabTextColor` — a *copy* of a palette colour, taken when a pane was
  last activated. Nothing put it back when the palette moved, so every title kept the colour
  of the theme its pane had been activated in: readable on one theme, invisible on the next.
- `theme/style.py`'s proxy now answers `standardIcon(SP_TabCloseButton)` with a painted glyph,
  and `build_style` takes the theme so it can colour it. Qt's own cross is a bundled red
  bitmap that no palette or stylesheet reaches — on every theme in the template it is the one
  mark in the window that belongs to a different application. `QCommonStyle` caches the icon
  it is handed, which is fine only because `apply_theme` builds a fresh style each time; that
  ordering is now stated in `apply_theme`'s docstring.
- `theme/icons.py` gained `close_icon` (and `_pen` now takes a `QColor`, for its faded
  variant): two pixmaps, because Qt asks for the `Disabled` one whenever a close button is
  neither hovered nor on the current tab, and the variant Qt generates for itself is
  greyscale.

**Why it belongs upstream.** None of it is DPlanner-specific, and all three are invisible
until somebody switches theme at runtime — which the template invites, with 22 themes in a
menu. The general rule is worth stating in the template's own docs: **the palette is live;
anything copied out of it is not, and owes a `PaletteChange` hook.**

### A `QStyleOptionGraphicsItem` carries a palette from when the scene was built

Not a framework change — the fix is in a module — but the trap is the framework's to warn
about, because the template has no `QGraphicsView` and so cannot have met it.

`QStyleOptionGraphicsItem.palette` is filled once, when the `QGraphicsScene` is constructed,
and Qt never refreshes it: not on `QApplication.setPalette`, not on `QGraphicsScene.setPalette`,
not on an explicit `invalidate()`. An item that paints from `option.palette` therefore paints
in whatever theme was current when its scene was created, for as long as that scene lives. Our
canvas lost its whole graph on a switch to a light theme — the nodes were still there, drawn in
the dark theme's near-white on near-white. The fix is one helper
(`modules/project_editor/items.live_palette`) reading `item.scene().palette()`, which *does*
follow the application. Worth a line wherever the template talks about custom painting.

---

### `framework/widgets.py` grew the text-well helpers

**What.** `make_text_well(pane)` (12 px document margin) and `space_lines(pane)` (~130 %
proportional line height, reapplied per `setPlainText`) moved up from
`modules/step_handoff/section.py` when a second module (`step_agent_instruction`'s Agent tab)
needed the same read-only-well treatment and modules may not import each other. The metrics
are DESIGN.md's text-well rules, which is why they read like constants rather than options.

**Why it belongs upstream.** The well treatment is the template's own DESIGN.md speaking; any
application with a read-only prose pane wants both, and each is four lines someone will
otherwise re-derive slightly differently.

### `services.detail_cards` found its first consumer

**What.** No code change — the second `InspectorSectionRegistry` the template ships on
`AppServices` was unused here until the project panel started rendering its sections as
`ToolCard`s in a `CardStack` (see `modules/project_editor/project_panel.py`). The
tab-vs-card split the `framework/inspector.py` docstring promised held up exactly as written:
the host differs, the extension contract does not. Worth a line in the template's docs that
the card host drives `show_target` with a *project* id — the contract's target vocabulary is
whatever the host says it is, and that turned out to be the feature, not a loophole.

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
  contract and which are leftovers. This change legitimised three more of them —
  `#InspectorTabs`, `#InspectorPanel`, `#InspectorTitle` and `#InspectorNotes` now have real
  users (`#InspectorPlaceholder` briefly did too, and was deleted along with the panel's empty
  page — a panel with nothing to show goes off screen instead) — which makes the remaining
  orphans easier to name:
  `#BinderResults`, `#ReadthroughTable`, `#InspectorSynopsis`, `#InspectorName`,
  `#InspectorStats`, the Corkboard block and the Zen block.
- **`SidebarShell._add_panel` ended with an unconditional `setCurrentIndex(0)`.** Correct,
  because registration only happens at startup — but it is the kind of thing that stops being
  correct silently if registration ever becomes dynamic. Worth a comment upstream if the tab
  set survives.
- **A submenu flattens its members' groups.** The child-menu collapse keys on
  `(menu, group, submenu)`, so every entry of one submenu must share one group — two groups
  with the same submenu title would open two identical child menus — and there are no
  separators *inside* a child menu. Fine at the six tab verbs that hit it (ordering keeps the
  move verbs ahead of the close verbs); supporting it would mean keying the collapse on
  `(menu, submenu)` and pre-creating per-child separators in `DynamicMenuBar`'s decoration
  pass. Worth knowing before someone designs a fifteen-entry submenu around groups.
- **Non-root index rows have no framework re-tint path.** `IndexPanel.set_icon_color` covers
  the segment roots; a segment that puts icons on its own rows (DPlanner's projects segment
  nests entry rows under each project) has to subscribe to `theme.changed` itself and
  repaint. That is workable — the segment already owns a rebuild — but if a second segment
  grows row icons, an optional `set_icon_color` on `IndexSegmentView` that the panel calls
  alongside its root repaint would be the upstream shape.

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
- **The step detail panel's tab host stayed in its module** rather than becoming
  `framework/inspector_panel.py`. What *did* go into the framework is where the panel is
  anchored, not what it renders — `framework/panels.py` owns the area, the header and the
  visibility, and the `QTabBar`-over-`QStackedLayout` loop is still the module's. That split
  held up: the two concerns that made extraction awkward were both about placement, and one
  of them (the host-supplied empty page) stopped existing once there was no host. See §1.
- **Lookup by "an id, a folder name, or part of a title" lives in `cli/`**, not in the model.
  It is a command-line affordance — resolving what a person typed — and the model should not
  have opinions about fuzzy matching.
