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

### Preview tabs: `TabHost.open(..., preview=True)`, and the index's `clicked` hook

**What.** The VS Code arrangement. `open` grew a keyword-only `preview` flag; the host keeps
at most one preview activity, the next preview-open replaces it (one `_announce` for the
whole replace), and a deliberate act pins it — a non-preview open of its URI, or moving its
tab (both `_move` and a `tabMoved` drag). `is_preview(activity)` answers for tests and
painting. The preview tab's title paints in italics: `_TabGroup` installs a `_PreviewTabBar`
(``setTabBar`` is protected, so the subclass exists to call it) whose `paintEvent` defers
wholly to Qt when the bar holds no preview and otherwise draws each tab through
`initStyleOption` — which carries `setTabTextColor`, so `_paint_active`'s dimming sweep keeps
working underneath, and the sweep is also what pushes the preview index to each bar.
Alongside it, `IndexSegmentView` grew a fifth hook, `clicked(item)`: the panel forwards only
plain left-clicks (a viewport event filter remembers the press's button and modifiers, since
`itemClicked` fires for every button and a Ctrl/Shift-click is building a selection).

**Why the double-click needs no timer.** The sequence is press/release (clicked → preview
opens), press again (activated → a non-preview open pins it), release (clicked again — a
preview-open of something already open is a plain focus and changes nothing). Every step is
idempotent, so the two gestures compose instead of racing.

**A trap.** `QTest.mouseDClick` sends a press that never sees a release, so
`QApplication.mouseButtons()` reports a held button for the rest of the process — anything
that consults it (the canvas's space-pan release does) misbehaves in every later test. Send a
hand-built `QMouseEvent` instead.

**Upstream?** Yes as a set: the flag, the pin rules and the bar belong together, and none is
DPlanner vocabulary. The `clicked` hook goes with them — a preview nobody can open is dead
weight.

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

### An area can be collapsed whole: `set_area_collapsed` on the dock and `PanelHost`

**What.** `framework/panels.py` gained area-level collapse — `set_area_collapsed(area, bool)`,
`is_area_collapsed(area)`, an `areas_changed: Signal[PanelArea]`, persisted at
`layout/areas/{area}/collapsed` — and `PanelHost` in `framework/window.py` carries all three,
with `main_window.py` delegating. The appshell module binds View ▸ Left/Right Side Panel to
Ctrl+B / Ctrl+Alt+B over it (the VS Code sidebar gesture).

**The part that was not obvious.** Collapse is a *third* orthogonal gate beside the per-panel
hide and immersive chrome, and it has to be tested in the **frame's** visibility formula in
`_refresh`, not by hiding the area splitter alone: a frame under a hidden parent still answers
`isHidden() == False`, so `is_panel_showing` would lie for every panel on a collapsed side.
With the term on the frame, the existing "area with no visible frames hides and takes zero
width" machinery — including the `splitterMoved` guard that refuses to persist a 0 size — does
the rest unchanged, which is why the whole feature is a set, two methods and one formula term.

**One behavioural rule, stated once:** an explicit gesture that puts a panel somewhere expands
that somewhere — switching a panel on, or moving one into a collapsed area, un-collapses it
(a checkmark that turns on with nothing appearing reads as a bug). A `ContextPanel` answering
True does *not*: collapse is the user's choice and survives selection changes.

**Deliberately not built:** a VS Code-style collapsed rail to click. New chrome against the
dock's "areas, not draggable docks" minimalism; the View menu (which renders the shortcut),
the palette and the key cover discoverability.

**Upstream?** Yes, with the panel areas themselves — it is the gesture that makes three fixed
areas feel as light as draggable docks without being them.

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

### `build_menu` greys a disabled entry instead of omitting it

**What.** `build_menu` no longer filters through `registry.runnable()`. It walks
`all_specs()`, skips only `visible=False`, and renders everything else with
`setEnabled(state.enabled)` — so a context menu now shows a disabled verb greyed, exactly as
the menu bar does. The palette still filters on `runnable()`; the two presenters now
deliberately disagree, and that split is the design: a menu is a map of what exists, a
fuzzy-searched palette is a launcher for what can run.

**Why.** The application adopted "an action that does not apply right now is DISABLED, never
HIDDEN" (a menu that reshapes itself with the selection cannot be learned; a greyed entry
teaches the precondition, and its `label` carries the reason). With that policy the popup was
the one presenter still silently dropping entries, which also broke the promise that a
greyed "Cannot Link — cycle" reaches the user from the canvas right-click.

**Upstream?** Yes, together with the policy itself — the constants (`ENABLED` / `DISABLED` /
`HIDDEN`) already exist upstream; what was missing was the statement of *which one a state
callback should return*, and one presenter honouring it inconsistently.

### `build_menu` now nests submenus like the menu bar

**What.** The `submenu=None` path no longer flattens. Specs carrying a `submenu` collapse
into a child `QMenu` keyed `(group, submenu)`, created at the first *visible* spec's sort
position — the same placement rule as `DynamicMenuBar._submenu`. A child menu whose entries
are all hidden is simply never created; a popup is rebuilt on every show, so absence is the
static equivalent of the menu bar's dynamic hide. The `submenu="X"` filter path is unchanged
(the tab bar's and the region popup's flat renders depend on it), and one local `add_entry`
helper builds flat and nested entries alike so the two can never drift.

**Why.** The docstring literally admitted the flattening. Once a menu holds three submenus
(Status, Type, Go on Step), a flat right-click renders a dozen sibling entries where the
menu bar shows three folders — the popup and the menu bar were the same registry wearing
two different shapes for no reason anybody could defend.

**Upstream?** Yes — the popup builder and the menu bar should agree on what a submenu means,
and the all-hidden rule falls out for free from the rebuild-per-show model.

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

### `core/storage/github.py` grew `repository_url(checkout)`

**What.** One function beside `gh_path()`/`gh_authenticated()`: `gh repo view --json url`
run *at* an arbitrary checkout path, returning the canonical repository URL or `None` for
every refusal alike (gh missing, unauthenticated, not a repo, no GitHub remote). The
composition root wires it into `project_repo` as an injected probe, which auto-fills the
project card's empty Repository field after a checkout is set.

**Why it is DPlanner-specific.** The template's storage layer only ever asks gh about the
*workspace's* repository; asking about somebody else's checkout is a planner concern.
Upstream would want it only if the template ever grows a "point at another repo" feature.

### `core/storage/pointer.py` — the workspace pointer file, and who may touch it

**What.** `POINTER_FILE = ".dplanner"` and `write_pointer(workspace)`: drop a one-line
relative path at the enclosing git repository's root when a workspace is created inside a
checkout — skipping when there is no repo, the workspace *is* the root, or a pointer
already exists (a hand-written one is never clobbered).

**Why it is core.** The constant used to live in `cli/workspace.py`, but the writer is
`domain/seed.py` (called through the framework's seed seam) and framework/domain may not
import `cli/`. `core/storage` is the one layer both sides see. The lesson worth carrying:
a file format with a reader on one layer and a writer on another belongs below both.

**Belongs upstream?** The pattern yes; the filename is DPlanner's.

### `core/png.py` — an RGB buffer as PNG bytes, stdlib only

**What.** One function, `encode_rgb(width, height, stride, pixels)`: IHDR + one IDAT +
IEND, filter 0, a fixed zlib level, no ancillary chunks. ~40 lines. Added for the spec
module's `dplanner spec render`, which rasterises a PDF page (pdfium) into a content-
addressed image asset from the CLI, where Qt must not load and Pillow is not a dependency.

**Why it is core.** It is Qt-free, application-independent, and any headless surface that
ever produces an image hits the same wall: the framework's only encoder is QImage. The
determinism (fixed compression level, no timestamps) is part of the contract — content
addressing has to see that identical pixels are identical bytes.

**Belongs upstream?** Probably, the day the template has a second headless image producer;
it is small enough that carrying it here until then costs nothing.

### `framework/asset_gallery.py` — the attached-files grid, promoted from a module

**What.** `AssetGallery`: thumbnails for images, filename chips for the rest, click
opens `ImagePreviewDialog`, optional Attach…/✕ when editable. Two source modes with two
path vocabularies, never mixed: a node's content-addressed `ModuleFileArea` (editable,
area-relative names) or an explicit list of workspace-relative paths plus a byte reader
(read-only — how a briefing's file list is previewed). Thumbnails are rendered at
`devicePixelRatioF()` and cached by name+ratio; the old module-private strip was soft on
every HiDPI screen.

**Why.** Promoted from `modules/step_agent_instruction/asset_strip.py` at its third
consumer (the `make_text_well` lesson again): agent instruction, the step's spec figures
and the description's images all want the same grid, and modules cannot import each
other. Carries forward the two traps the strip learned: the *provider*-not-area seam
(`KeyError` while a node is unflushed, answered in words) and attach/remove being
deliberately not undoable.

**Belongs upstream?** Yes, for any application adopting the module-files +
content-addressed-assets convention — the widget knows nothing DPlanner-specific.

*Later refinement*: thumbnails grew to 76 px and the grid packs left (all spare width on
a phantom trailing stretch column) — a short row used to spread its few thumbnails across
the whole panel, which read as scattered rather than listed.

### `framework/image_preview.py` — one modal lightbox for everything

**What.** `ImagePreviewDialog(image, name, parent, caption=, path=)`: fitted to ≤80 % of
the screen, **never upscaled past 1:1**, pixmap built at the device pixel ratio, optional
Copy Path button. 20 px dialog margins per DESIGN.md.

**Why.** Every module with a picture would otherwise grow its own dialog. The trap worth
stating upstream: `QPixmap.scaled` without `setDevicePixelRatio` is blurry on every HiDPI
screen — this generalises the `_PdfPage` pattern the spec viewer already got right.

**Belongs upstream?** Yes, verbatim.

### The entropy pass: template machinery a year of building never called

**What.** A whole-codebase review deleted every piece of `framework/`/`core/` surface that
had accumulated zero callers across 27 modules, on the theory that git remembers and a
dormant seam misleads more than it serves:

- **Immersive mode, whole.** `enter_immersive`/`leave_immersive`/`is_immersive` and the
  Escape shortcut on `AppWindow`, the `ImmersiveHost` protocol in `framework/window.py`,
  `PanelDock.set_chrome_visible` and `TabHost.set_tab_bar_visible`. Fully implemented,
  reachable from nothing — no action, no menu entry, no shortcut ever called it here.
- **`ExportRegistry`** (`framework/exports.py`, the `AppServices.exports` field). §5 already
  recorded that it has no clients in the template either; we have now acted on that here.
- **`InspectorExtension.tab_visible()` / `tab_visibility_changed`.** Nine implementations,
  every one `return True`; zero emitters. The protocol shrank to
  `widget`/`show_target`/`dispose`, and both hosts (the step panel's tab bar, the project
  panel's card stack) lost their dead visibility plumbing. If a section that genuinely
  appears-and-disappears ever arrives, reintroduce the signal *with* that section — the
  contract survived nine implementations without one, which is the evidence it was
  speculative.
- **`SettingsScope`, `SettingsSection.scope` and `.order`.** Every registrant said
  `GLOBAL`; the dialog's "Project settings" tab was permanently empty, and `order` was never
  set nor read. The dialog is now one tree. Workspace-scoped settings remain a plausible
  future — the enum is one `git show` away, and the right time to restore it is with its
  first real section.
- **Dead methods:** `Context.has`/`has_prefix`, `TaskRunner.current_task`/`abandon`,
  `TabHost.reannounce_current`, `AppBuilder.with_window`, `core/fsio.write_json_atomic`/
  `read_json`, the `HIDDEN` action-state constant (the one hide site needs a label, so it
  spells its `ActionState` out). The `domain/` and `core/` package `__init__` re-exports
  went too — every consumer already imported from the defining module.
- **Kept deliberately:** `secrets_store.delete_secret` — unused, but a secrets store you
  can write into and never clear is a trap, not a seam.

**Why the template should know.** Most of these came with the bootstrap. A generated
application that never grows an exporter, an immersive mode or a project settings scope
carries this surface forever, and each unused seam reads as a promise the application does
not keep. The upstream question per item is the same: demonstrate it end to end, or ship it
as documentation rather than code.

### `framework/module_data_section.py` — the structured twin of `prose_section.py`

**What.** `ModuleDataSection(product, undo, *, module_id, undo_label)`: the scaffold every
structured aspect editor was hand-rolling — the `module_data_changed` subscription and
teardown, reload-on-target with commits suppressed, the no-op-when-unchanged commit through
the undo stack, and the echo rule (*ignore the echo of your own write only while one of
your fields is being edited; an undo carries `UNDO_ORIGIN`, never the view, so it always
lands*). A subclass builds widgets, implements `load_step(step)` / `entry(step)`, and calls
`commit()` from its edit-finished handlers; `editing()` defaults to focus-inside-me.

**Why.** `prose_section.py`'s own rationale — "the binding mechanics are the
easy-to-get-wrong half, and getting it wrong is quiet" — held for JSON too: by the time we
wrote this, four hand-rolled copies existed and one had drifted (its echo guard swallowed
an undo made while its field was focused). Ticket, Release, Estimate and GitHub sections
are the ports; the drift died in the port.

**Belongs upstream?** Yes, next to `prose_section.py` — any application with aspects-like
per-module data will re-derive it worse.

### `EntityActivity` and `follow_entity_tabs` in `framework/activity.py`

**What.** `ActivityBase` grew a sibling: `EntityActivity(context, entity_kind, entity_id)`
owns `_is_active`, publishes the activity scope with an entity edge on activation
(`activity_nodes()` overridable for extra edges — the canvas adds its input mode), and
`publish_selection(nodes)` enforces *only the active pane speaks for the user*.
`follow_entity_tabs(tabs, activity_type, still_exists, closes_on=…, retitles_on=…)`
closes tabs whose entity is gone and retitles survivors — feature-blind via a
`still_exists` predicate and two core signals.

**Why.** Five modules carried byte-identical copies of both obligations (the fifth copy
arrived with the newest feature — evidence the pattern recruits). The rule the base
enforces is CLAUDE.md's most-repeated comment; now it is enforced by construction and the
sixth entity tab gets it for free.

**Belongs upstream?** Yes, both — the template's docs already state the rule; this is the
rule as code.

### `append_action` in `framework/action_menu.py`

**What.** The per-spec body factored out of `build_menu`: greyed when disabled, omitted
only when hidden, state label over spec label, checkable per state, context re-read at
trigger time. For a widget that assembles its popup by hand (a toolbar button mixing data
rows with verbs) and must still render entries under the one presenter policy.

**Why.** The canvas's layout button had reimplemented the policy line for line — its
docstring admitted it — and had already drifted on separators. A copy of a policy is a
fork waiting to happen; a function is not.

### `selection_of` / `restore_selection` beside the expansion pair in `index_panel.py`

**What.** The same shape as `expansion_of`/`restore_expansion`, for the tree's selection.
`restore_selection` returns what it actually restored, so a segment can rebuild under
blocked signals and only announce a selection change when a selected row truly vanished.

**Why.** A rebuild that drops the selection does not just lose a highlight: the tree
publishes the now-empty selection scope and every context-following panel abandons what
the user was looking at. DPlanner's projects segment hit exactly that — any rename
rebuilt the folder and hid the step panel. The expansion helpers existed for this reason;
selection needed the same treatment plus the announce-only-real-changes subtlety.

**Belongs upstream?** Yes, as a pair with the expansion helpers.

### Two small honesty fixes: `window_watch` and the startup-failure dialog

**What.** `WorkspaceWatcher` now takes a typed `WatchableRepository` instead of `repo:
object` with an `isinstance` fallback to a watcher that silently never fires — a wiring
mistake is a type error again, and the composition root passes its already-narrowed
store. `AppSession` lost the `report_startup_failure` injection point nothing ever
injected, and its two near-identical `QMessageBox` builders collapsed into one
`_failure_box(failure, parent)` used by both the modal pre-window path and the
non-blocking in-window path.

**Why the template should know.** Both are the same lesson as the entropy list above: a
defensive `object` parameter and an unused injection seam each read as flexibility and
behave as a trap — the silent-`None` watcher especially, because the failure mode is "the
feature just doesn't run".

### `core/config_dir.py` — a Qt-free per-user config location

**What.** One function, `config_dir(app)`: the platform's per-user configuration directory
(XDG / `%APPDATA%` / `~/Library/Application Support`), hand-rolled, no dependency. DPlanner's
project-library file lives there.

**Why.** The template's answer to "per user, per machine" is QSettings via
`framework/user_config.py` — which a headless CLI cannot read (see §4: the CLI loads no Qt).
Any application with a real CLI surface eventually needs one value both halves can reach,
and FORMAT.md had already named "a Qt-free per-user config in core/" as the sanctioned fix
before anything used it. Upstream candidate: yes — small, and the trap it resolves is
structural, not app-specific.

### `GitStorage` grew multiple commit scopes, `init_repo`, `origin_url`

**What.** The single `self._scope` pathspec became `self._scopes: tuple[str, ...]`
(constructor arg `scopes=None` keeps the old derive-from-root behaviour), threaded through
`refresh_dirty/diff/commit/history`. Module-level `init_repo(path)` (plain `git init`) and
`origin_url(path)` (`git remote get-url origin`, "" when absent) joined `find_repo_root`.
`core/storage/locations.py` grew `grouped_by_repo(providers)`: one scoped provider per
distinct `repo_root`, so a Save over several planned directories in one repository is one
commit covering exactly those directories.

**Why.** The scoping policy ("a Save must never sweep up whatever else is in the tree") was
already the class's one policy decision; multiple scopes is the same decision when one
repository holds several planned directories. `origin_url` replaces storing a repository URL
that git already knows. Upstream: the multi-scope change is honest generalisation; the
grouping helper only matters to applications whose document spans providers.

Related: `VersionedStorage` gained `dirty_file_count()` (the cached count `GitStorage`
always had beside `is_dirty()`); an aggregator over several providers needs the number, not
just the flag, and shadowing it from signal payloads was worse than promising it.

### A repository is built over a source path, not a storage provider

**What.** `Repository` lost its `storage` attribute and `RepositoryFactory` became
`Callable[[Path], Repository[DocT]]`; `AppBuilder.with_storage(provider)` became
`with_source(path)` and `SeedFactory` takes the path; `AppServices.storage` is gone.
DPlanner's `LibraryStore` is built over the library *file* and opens one provider per
project directory underneath.

**Why.** The framework assumed one document = one provider, and the assumption was wired
into three seams (`repo.storage`, the builder's stage 1, the services bundle) that nothing
in the framework actually used beyond construction. A repository that spans several
providers only had to stop *announcing* one. Upstream candidate: yes — it deletes API and
widens what a template application's document can be.

### A replaced window's close guards must not run

**What.** `AppSession._open` clears `old_window.close_guards` before closing the window it
is replacing; close *hooks* (the final autosave flush) still run.

**Why.** Guards exist to interrupt a person quitting ("Record changes before quitting?").
A rebuild is not a quit: the changes are on disk and the new window shows the same dirty
state — but the guard cannot know that, so a watcher-triggered reload with anything
uncommitted opened a modal nobody was there to answer. Found as a test hang; a real user's
reload would have blocked the same way. Upstream candidate: yes — any application with
both a close guard and a rebuild path has this bug latent.

### `discard_build()`, and the `deleteLater` that a template will lose

**What.** The teardown in `AppSession._open` became a module-level `discard_build(window,
services)` — clear close guards, `close()`, **`deleteLater()`**, stop autosave — and
`AppSession.close()` is a new public method that calls it and then dispatches the deferred
deletes (`QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)`). The store
close stayed in `_open`, where a new store is genuinely replacing the old one.

**Why.** Our test suite builds a whole application per test, and its teardown was a
hand-written copy of `_open`'s that had dropped the `deleteLater`. A closed `QWidget` is
still alive — Qt keeps it in `topLevelWidgets()` — so every application the suite ever built
stayed reachable: 28 top-level widgets and ~2,700 objects each, forever. Nothing about that
is slow on its own, but the suite also collects cyclic garbage after every test (it must:
otherwise Python frees PySide wrappers mid event dispatch and the run SIGSEGVs somewhere
else each time), and a full collection costs what the live graph costs. Linear leak times
per-test collection is a quadratic suite: `tests/modules` took 25m20s, and 4m36s once the
line was back.

Two things are worth carrying up beyond the fix itself:

- **The duplication was the bug.** Two callers needed the same five steps and only one of
  them was written by somebody thinking about Qt ownership. A framework that lets an
  application hand-roll "discard this build" will get a subtly different copy every time.
- **`processEvents()` does not run deferred deletes.** Qt skips `DeferredDelete` in it by
  design, so the obvious way to flush them silently does nothing. Anything that discards Qt
  objects without an event loop to follow needs `sendPostedEvents(None, DeferredDelete)`.
  The dispatch belongs at the caller and not inside `discard_build`, because only a caller
  on no Qt stack can promise it is safe: `_open` runs with the discarded window's close
  hooks still unwinding, and deleting it under them is a crash.

The running application was never affected — we measured it rather than assuming: nine
reloads driven from inside `app.exec()` and the top-level widget count settles and stays
flat, because a real event loop dispatches the deferred deletes. This is a bug that only a
test suite, or a headless script, can have.

**Upstream?** Yes, all of it. The template ships `AppSession` with the reload path and no
`close()`, so *every* application generated from it will write this teardown by hand in its
`conftest.py`, and any that forgets the line gets a quadratic suite that looks like "Qt tests
are just slow". A `close()` on the session and a line in the template's own conftest closes
it for everyone. `tests/framework/test_builder.py` has the regression test — counting
top-level widgets across two build-and-close cycles — and it is worth copying up with it.

### The session lost switching; a different document is a different process

**What.** `AppSession.switch_to`, the switch guards, and the `workspaces/last|recent|roots`
QSettings all went; the `WorkspaceSwitcher` protocol shrank to `SessionControl.reload()`.
DPlanner opens a different library by spawning a detached instance instead.

**Why.** With a default library that always exists, "last opened" and "recent" had no
remaining job, and the in-process switch was the one caller of the guard machinery. The
full-rebuild discipline stays — reload after a branch switch or an external write is
unchanged — but the switch-shaped half of it was scaffolding for a flow that no longer
exists. Upstream: the rebuild reasoning holds either way; whether a template keeps
`switch_to` depends on whether its documents are cheap enough to share a process.

### `InspectorSection` grew an optional `shown_for` visibility predicate

**What.** `framework/inspector.py`'s `InspectorSection` gained
`shown_for: Callable[[str | None], bool] | None = None`. `None` (the default) is the old
behaviour — the tab is always there. The host still builds every extension once; the
predicate governs only tab visibility, re-asked by DPlanner's step panel on every target
change and on model writes to the shown target (`QTabBar.setTabVisible`, indices stable).

**Why.** DPlanner made three aspects per-step toggleable (Release, Agent, Ticket), and a
tab for an aspect the step does not carry taught nothing while burying the ones it does.
The alternative — an extension reporting "nothing to say" through its own contract — would
have forced every section to answer a question only toggleable ones have. Belongs
upstream, in my view: it is one optional field and a small host loop, and it is the
difference between "a section registry" and "a section registry every conditional surface
has to work around". The trap worth documenting with it: the host must re-ask on *model*
changes, not just selection changes, or a toggle only takes effect on reselect.

### `InspectorSection` grew `stretch`, and the registry its third instantiation

**What.** Two small things, one feature. `framework/inspector.py`'s `InspectorSection`
gained `stretch: int = 0` — how much of the leftover height a *vertically stacking* host
gives the section's widget; tab and card hosts ignore it. And `AppServices` gained a third
`InspectorSectionRegistry` instance, `step_details`: blocks composed into the step panel's
first tab ("Details"), rendered by a composite that is itself an ordinary section
(`modules/step_properties/details.py` — app side, not framework).

**Why.** The editors a step should show *first* (estimate, description, its figures) were
one tab each; stacking them needed a host that knows who takes the room, and a frozen field
on the section is the honest way to say it — sniffing size policies would be implicit.
Addressing the host by registry instance rather than a `placement` flag on the section is
the `detail_cards` reasoning, third time: each host's registrants stay greppable and no
host filters every section by a mode field. The `stretch` field belongs upstream with the
type; the third instance is per-application composition.

### `framework/prose_section.py` gained a `margin` parameter

**What.** `ProseSection(…, margin: int = PANEL_MARGIN)` — the outer margins, previously
hard-coded to 16 px. Hosts that own the spacing themselves (a card, DPlanner's Details tab
block) pass 0; every existing caller keeps the default. Retires the
`layout.setContentsMargins(0, 0, 0, 0)` mutation the project card was doing from outside.

**Why.** A reusable section cannot know whether its host already provides the panel
margin, and double 16 px reads as a layout bug. One constructor parameter beats mutating
the layout after the fact. Belongs upstream.

### `framework/text_dialog.py` — expand any bound editor into a modal

**What.** New file, two exports. `ExpandedTextDialog(field, undo, *, title, placeholder,
parent)`: a `QPlainTextEdit` text well sized to 80 % of the screen, holding its own
`TextBinding` over the caller's `TextField`; the opener owes `dispose()` after `exec()`,
the same contract as DPlanner's step-details dialog. `attach_expand(editor)`: a small
auto-raise `⤢` `QToolButton` pinned to the editor's top-right corner by an event filter,
returned for the caller to wire and enable/disable. `ProseSection` wires it in for every
subclass (`expand_title` names the dialog).

**Why.** Side-panel prose is a few hundred pixels tall and instructions run to screens.
Because `TextBinding` already treats every other binding's commands as foreign changes,
the dialog is *only* a second binding — live-synced both ways, one undo stack, nothing
that can be lost on close — where a copy-out/copy-back dialog would have invented a second
home for the text and a Cancel that discards work. Belongs upstream beside `text_binding`;
the corner-button affordance is the part to review (it assumes the editor is a
`QPlainTextEdit` with a vertical scrollbar).

### The window remembers where the user left it: `user_config` grew a second scope

**What.** Three changes, one feature.

- `framework/user_config.py` now has two scopes rather than one. `get_global`/`set_global`
  are unchanged (a preference, the same in whichever document is open); `get_scoped`/
  `set_scoped` take a scope string from `library_scope(path)` — a truncated SHA-256 of the
  resolved source path — for what is only true of *one* document. The two `QSettings`
  accessors collapsed into a shared `_read`/`_write` pair, and the first parameter is now
  called `owner` rather than `module_id`, because framework surfaces store things here too.
- `framework/index_panel.py` takes a keyword-only `scope` and persists which rows are open,
  merged per segment. The folder root carries its own id as its expansion key, so a
  collapsed folder is remembered by the same walk as the rows under it. An empty scope
  (the default) remembers nothing, which is what a bare panel in a test wants.
- `framework/tabs.py` grew `tabs_changed: Signal[()]` and `can_open(kind) -> bool`.
- `AppServices` grew `source_scope: str`, derived once in the builder from the source it was
  handed, so the panel and the composition root cannot disagree about which slice is which.

**Why.** `activity_changed` is about which tab is *current*, and a listener that wants the
tab *list* — anything that persists it, anything that counts tabs — never hears about a
tab closing in a pane the user is not in, because `_announce` guards on the (group,
activity) pair and neither changed. That is not a bug in `_announce`; it is a second fact
the host had no way to say. `can_open` is the same shape of gap one level up: `open` is
right to raise for a kind the caller registered itself, and wrong as the way to ask about
a kind read back from disk, where the feature may simply be gone from this build.

**The one that generalises.** Restoring by *key* rather than by position is what makes
both halves safe against a document that changed underneath: a remembered key naming no
row restores nothing, so a library that lost a project comes back with *fewer* folders and
fewer tabs rather than wrong ones. No validation pass, no version stamp, no migration —
the check is the lookup. Worth saying in the template, because the alternative (indexes,
or a saved tree shape) is the obvious first design and it is the one that breaks.

**Belongs upstream?** All of it. The scoped store and the tab-list signal are template-level
gaps; the index panel's persistence is ten lines on top of helpers that were already there.
DPlanner's own half — the preference, and asking the model whether a target still exists —
stayed in `modules/reopen_tabs/`, which is the line we would draw upstream too.

### Prose editors show markdown structure without leaving plain text

**What.** New `framework/markdown_highlight.py`: a `QSyntaxHighlighter` that bolds
headings, fades structure markers (`#`, `-`, `1.`, `>`) to the secondary ink, bolds
`**spans**` and sets inline code in monospace — colours read from the widget's palette on
every pass, re-inked by `rehighlight()` on `PaletteChange` (the hook `ProseSection` now
provides). Installed in `ProseSection` and `ExpandedTextDialog`, so every prose document —
description, handoff, agent instruction, test body — shows its structure for free.

**Why not a rich-text editor.** `setMarkdown`/`toMarkdown` edits a document tree and writes
back a normalised serialisation, which breaks `TextBinding`'s positional splices and can
reformat a file the user never touched (the spec editor pays that cost knowingly, with a
session-replace model). A highlighter keeps the text byte-identical to disk.

**Upstream?** Yes, if the template keeps the premise that module prose is markdown — the
highlighter has no DPlanner in it. The `PaletteChange` → `rehighlight` hook belongs with it.

### A prose editor attaches what you paste into it

**What.** New `framework/prose_edit.py` (`ProseEdit`) and `framework/mime_files.py`. A file
arriving by paste, drop, or the editor's own *Insert Image…* is content-addressed into the
node's module file area and referenced from the caret as `![alt](assets/…)` — or
`[name](assets/…)` when it is not an image. `ProseSection` and `ExpandedTextDialog` now build
a `ProseEdit`; `ProseSection` also builds the `AssetGallery` when given an `attach_title`,
which deleted the hand-wired gallery from two hosts that had each grown their own.
`AssetGallery` gained a public `attach_bytes(data, filename) -> str | None` (was
`_attach_bytes`, returning nothing) and a `hide_when_empty` flag.

**Why the editor does not write the file.** It is handed an `Attach` callable — the gallery's
`attach_bytes` — because attaching is three steps: resolve the area, write, redraw the
thumbnails. An editor doing only the middle one puts a pasted image on disk with no thumbnail
beside it, and needs a second answer for a node the store has never flushed. It was written
the other way first; the missing refresh is what found it.

**Why `set_area` is a call and not another `…_for` callable.** The node a document is *keyed
by* is not always the node its *files* live beside — a test's body is keyed by the test, its
images by the step. A `Callable[[str], AreaFor | None]` hands the callee an id it must
discard, which reads correct and is wrong. The host makes the call from its own
`show_target`, where the right id is in scope.

**Why the undo step is sealed on both sides of the insert.** `EditTextCommand` coalesces an
append at exactly the caret — which every paste is — so without
`UndoService.break_coalescing()` before and after, one Ctrl+Z takes the sentence being typed
along with the link. Worth knowing for any template feature that inserts text
programmatically into a bound editor: coalescing is tuned for keystrokes and will happily
swallow something that was not one.

**Qt facts worth writing down** (measured on PySide6 6.9+, offscreen):

- `QPlainTextEdit` routes **drops** through `insertFromMimeData`, the same override paste
  uses. No `setAcceptDrops`, no `dragEnterEvent`/`dropEvent` — `acceptDrops()` is already
  true on the widget and its viewport.
- Overriding `canInsertFromMimeData` is **not** cosmetic: Qt's own answer is `False` for
  image-only clipboard data, which greys **Paste** in the standard context menu. `paste()`
  itself does not consult it, so Ctrl+V works either way — only the menu entry depends on it.
- Qt asks `canInsertFromMimeData` on **every drag-move**, so it must not read a byte. Hence
  the split into `carries_files()` (a `stat` at worst) and `payloads()` (reads, once).
- A URL-only `QMimeData` auto-synthesises `hasText()` as the path string, which is why local
  files must be checked before falling through to Qt's paste — and why "falling through" for
  an editor with no area usefully inserts the path.
- A child widget of a never-shown parent reports `isVisible() == False` whatever it was told;
  `isHidden()` is the property that reflects the widget's own state.

**Upstream?** Yes. "A prose editor attaches what you paste" has no DPlanner in it, and
`mime_files.py` is pure Qt. The one judgement to carry with it: a plain-text markdown editor
inserts a *link* rather than embedding, because embedding means a rich-text widget and that
costs the positional binding (see the highlighter note above, which is the same trade seen
from the other side).


### A submenu was keyed by group, so one name could render twice

**What.** `framework/menubar.py` and `framework/action_menu.py` both keyed a child menu by
*(menu, group, title)*. Two groups naming the same submenu therefore produced **two child
menus with the same name**, one after the other, with a group rule between them — which is
exactly what DPlanner's Step ▸ Test looked like (what a test *is*, and what a run *recorded*,
are two groups of verbs and one menu to a person).

Now a child menu is keyed by *(menu, title)* and is a **container of the same kind the menu
is**: it holds the menu's groups and draws a rule where its entries change group, under the
same never-leading, never-dangling rule the menu bar already applied to top-level groups.
`menubar.py` pre-creates one hidden separator per group boundary per container (the
bookkeeping generalised from "per menu" to "per menu *or* child menu"); `action_menu.py` does
the same as it builds. Two consequences the application wanted immediately: a group that only
feeds an existing child menu adds no rule to the menu itself, and several child menus can
therefore sit in one group as a band.

**The cost, stated honestly.** A child menu still sits at its first entry's `order`, so two
child menus in one group have to claim bands of it. `order` was documented as ranking only
inside a group; it now also decides which of that group's child menus comes first. The
alternative — a table naming each group's submenus in order — is more vocabulary for one
menu's benefit, and we did not build it.

`MenuStructure.items()` went with it — the construction loop it existed for now walks
`menus()` and asks `groups()` per container, and nothing else ever called it.

**Upstream?** Yes, the keying certainly: rendering two menus with one name is a bug in any
application, and no template user would choose it. The internal rules come with it for free
since they are the same code path. `tests/framework/test_menubar.py` (new here — the template
has no menu-bar test at all) asserts the menu bar and `build_menu` render the same shape,
which is the property four presenters of one registry exist to have.

### `ActionSpec.icon`, and why the menu bar deliberately ignores it

**What.** `ActionSpec` gained `icon: Callable[[QColor], QIcon] | None`. A **painter**, not a
`QIcon`: the presenter hands over its own ink and gets a glyph back. `build_menu`,
`append_action` and a toolbar button's dropdown render it; `DynamicMenuBar` does not.

**Why the split.** A pop-up is built fresh every time it opens, so its glyph is painted in the
theme that is current. The menu bar's QActions are created once and live for the application
— a colour baked into one at startup is still there three themes later. That is the same trap
as `QStyleOptionGraphicsItem.palette` (§5), one layer up, and the honest answer for now is
that the presenter which cannot refresh does not render. If upstream wants menu-bar icons it
needs a palette-change hook there first.

**Upstream?** Yes, with that caveat written next to it.

### `ActionToolbar`: a button may drop its verb's submenu down

**What.** `ActionToolbar` takes `menus: Mapping[str, tuple[str, str]]` — action id →
`(menu, submenu)`. Such a button gets `MenuButtonPopup`: the face still runs its own verb,
the arrow renders that child menu through `fill_menu` on every open. `build_menu` was split
into `fill_menu(target, …)` + a one-line `build_menu` wrapper so a menu owned by a button can
be refilled rather than replaced.

**Why it is not a widget.** DPlanner's first instinct was a `NewStepButton` in the module,
which would have meant the module hand-building a list of the kinds a step can be — the one
thing the composition root exists to keep it from knowing. Rendering the registry's own
submenu keeps *a right-click renders a menu, never a copy of one* true for a toolbar too.

**Upstream?** Yes. It is six lines and it is the only way a toolbar can offer a verb's
variants without duplicating them.

### A styled `QToolButton` loses the room for its own menu arrow

Not a framework change — a Qt fact that cost us a clipped button in the canvas toolbar's
layout picker, and any template application that styles `QToolButton` will meet it. Once a
QSS rule sets the button's box model, Qt's size hint stops accounting for the drop-down
indicator, and the arrow lands on the last letter of the label. The fix is to say where it
goes and leave room for it:

```css
#Button::menu-indicator { subcontrol-origin: padding; subcontrol-position: right center;
                          width: 10px; }
#Button { padding-right: 20px; }
```

`MenuButtonPopup` does not need it — that mode gives the arrow its own section — so it is
specifically `InstantPopup` plus a stylesheet that bites.

### A split window had no seams, and no way to tell which pane spoke

**What.** Two changes, one in `framework/tabs.py` and one in `theme.qss` (which the template
also ships):

- One `QSplitter::handle` rule, application-wide: a 1 px `$BORDER` line inside a 7 px handle.
  It reaches the tab host's splitter, the dock's, each panel area's, and every splitter written
  after it. The three `#PanelArea*` rules **lost** their `border-right`/`border-left`/
  `border-top` in the same change and kept only their ground.
- `TabHost` seats each group in a new `_Pane(QFrame)` — object name `ActivityPane`, one
  zero-margin layout — and `_paint_active` marks the active one with a 2 px accent edge
  whenever `len(self._groups) > 1`. `_new_group` and `_drop_group` gained the plumbing.

**Why it matters upstream.** The template ships split panes and the same gap: `move_tab_left`
produced two `QTabWidget`s in a `QSplitter` with nothing between them, on a `documentMode` bar
whose only cue was the dimmed titles `_paint_active` already wrote. Neither half of the fix has
any DPlanner in it.

**Why the mark is a wrapper and not the group.** `setDocumentMode(True)` makes
`QTabWidget::paintEvent` skip the pane frame entirely, so a `#ActivityTabs::pane` rule renders
nothing; and a widget's children paint over anything it draws for itself, so a `paintEvent`
override is covered by the page. Styling the `QTabBar` is out for the reason already in
`_paint_active`'s docstring — QSS replaces its native rendering, and `setTabTextColor` stops
being the thing that shows. A frame around the group has none of those problems and costs one
`group.parentWidget()` instead of a second map.

**A Qt trap worth the whole entry: a splitter handle's two orientations paint differently.**
Measured on PySide6 6.9, offscreen, on a 7 px handle:

- `QSplitter::handle:horizontal` honours the box model. `width: 1px` with
  `border-left/right: 3px solid <ground>` renders exactly `[3 ground][1 line][3 ground]`.
- `QSplitter::handle:vertical` does **not**. It fills its whole rect with `background-color`
  and paints its borders *outside* that rect. The same rule turned on its side renders a
  7 px slab of the line colour, with the ground drawn over the neighbours. `margin` is
  ignored the same way; a `qlineargradient` works but interpolates, so the line comes out soft.
  What does work is `height: 6px; background-color: transparent; border-bottom: 1px solid …`
  — the line is the border and the transparent 6 px shows the splitter's own ground, which is
  why no panel area has to name a colour for a vertical seam.

Nothing warns about any of this: a stylesheet is as silent about a rule that renders wrong as
about one that never matched. `tests/test_theme.py::test_a_splitter_seam_is_exactly_one_hairline`
therefore renders a splitter in each orientation and counts the `$BORDER` pixels across the
handle — it caught the slab, and it is the shape any handle rule should be checked in.

### `DataMenuSpec`: a menu-bar child menu whose entries are data

**What.** Two changes. `framework/action_registry.py` gained `DataMenuSpec` — `id`, `menu`,
`group`, `title`, `order` and a `fill(QMenu)` callback — with `register_data_menu`,
`data_menus()` and a `data_menu_registered` signal beside the spec machinery, and a
`MenuPlacement` protocol so `MenuStructure.validate`/`sort_key` type against what placement
actually needs rather than against `ActionSpec`. `framework/menubar.py` renders one: the
child `QMenu` is inserted at its sort key like any entry (so the group separators just
work), stays visible when empty, and is cleared and refilled on `aboutToShow`;
`data_menu(spec_id)` returns it freshly filled, which is how a test asks what it offers.

**Why.** The menu bar's create-once-and-restate QActions cannot say a list whose entries are
born and die at runtime — live agent runs, in DPlanner's case; recent files, in anybody's.
Registering ephemeral `ActionSpec`s would leak ids into the palette and need the
un-registration door the registry deliberately keeps shut. The toolbar already had the
answer (DPlanner's layout picker builds its popup fresh on open); this is the same rule given
to the one presenter that never rebuilds. Belongs upstream, we think: "Recent…" menus are
universal. `fill_menu` in `action_menu.py` renders the same specs since 2026-09-12 — merged
into the one sorted walk by the same `sort_key`, placed with the same group rule, filled on
`aboutToShow` like the bar's — because *Step ▸ Run Agent With* became a data menu and the
canvas pops Step up: a right-click that lacked it was the drift the one-builder rule exists
to prevent. A named-`submenu` render leaves data menus out; they are children of the menu.

**A detail worth keeping.** The data menu's `menuAction` stays visible with an empty list, on
the *hidden means absent* rule: the menu is the capability, and the fill tells the empty
story with a disabled entry ("No agents running from this window"). Deriving its visibility
from its contents — the spec-fed child menus' rule — would make the capability flicker with
the data.


### `framework/step_selection.py` — "which entity does this verb act on", in one place

**What.** `focused_step` moved out of `framework/aspect_toggle.py` and `chosen_steps` out of
`modules/project_editor/verbs.py` into a file that holds both, with one parameter order
(`(context, library)`). Nothing else changed: the two bodies are what they were.

**Why.** `chosen_steps` — *the selection, else what the activity is about* — had been the
private rule of the module that owns Delete, Cut, Copy, Duplicate and Isolate. Run Agent
learned to act on a multi-selection too, and it lives in a module that may not import that
one, so the rule was about to exist twice; a second copy is how two verbs come to disagree
about what "these steps" means, which is the very drift the original docstring was written
against. Its twin was already in the framework, under a filename that named a Type toggle
rather than a selection.

**For upstream.** The pair generalises past steps: the questions are *the one entity to act
on* and *the entities to act on*, and every application built from the template asks them.
An upstream version would be `focused_entity(context, kind, exists)` /
`chosen_entities(context, kind, exists)` over any entity kind, with the model lookup handed
in — the template's `Context` already speaks kinds, and `framework/` has no model to ask.
We kept ours typed to `Library`/`Step` because that is what every call site here wants and a
generic pair would have made both call sites longer than the function.


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

---

## 7. From the aspect-toggling pass

- **`framework/action_dialog.py` — actions as a dialog of checkboxes.** *Retired in the step
  modal pass (§10) in favour of `aspect_bar.py`; the design note stands.* The fifth presenter
  beside the menu bar, palette, toolbar and `action_menu`'s pop-ups, and it follows the same
  one policy: render the registry, never a copy of it. `TogglesDialog(actions, context, menu=,
  submenu=)` lists every spec in one submenu as a checkbox with its `tip` as a second line,
  runs each through `ActionRegistry.run`, and rebuilds after every click because one toggle
  can change another's state. **This belongs upstream.** It is entirely generic — nothing in
  it names an aspect, a step or DPlanner — and any application with a submenu of independent
  toggles wants the same dialog. One deliberate choice worth carrying with it: the context
  arrives as a `Callable[[], Context]` rather than a `ContextService`, so a caller whose
  target is not the window's selection (a panel hosted in a modal) can hand over one naming
  its own.
- **`InspectorSection.hint`.** A standing convention — the unit a number is in — rendered by
  a captioned host as an info glyph beside the caption, with the sentence as its tooltip.
  **Belongs upstream**, though the glyph does not: `info_icon()` is ours, and upstream would
  need its own. The field is three lines and the alternative is what we deleted, a
  `#InspectorNote` line under every such field that is re-read on every visit and earns none
  of them. `DESIGN.md`'s *Words* section is the rule; only the block host renders it today,
  and `ToolCard` is the obvious second.
- **A `QTabBar` has no corner widget.** `QTabWidget.setCornerWidget` does not exist on the
  bare bar, so a button that should sit beside the last tab needs the host to build the row
  (`QHBoxLayout`: bar, stretch, button). Worth knowing before somebody reaches for the
  method that is not there — and an argument for the framework growing a small tab-row
  widget if a second host ever wants one.
- **A widget added to a `QToolBar` does not carry its own visibility.** `addWidget` wraps it
  in a `QWidgetAction`, and hiding the widget leaves the action's slot behind; it is the
  action you must hide. The template's own toolbar code sidesteps this by never hiding one.
  The tests tab's Group-by selector holds the returned action for exactly this reason.

## 8. From the documentation pass

- **`framework/markdown_view.py` — a read-only markdown well whose images come from the
  store.** Extracted from `modules/spec/viewer.py`, which had it first and had the only copy.
  The rule it exists for is worth carrying: a relative `![](assets/…)` must resolve through
  a `ModuleFileArea`, never `QUrl.fromLocalFile`, or the well works against a folder provider
  and silently shows nothing against a git or GitHub one. It takes a *sequence* of areas
  rather than one, because a document assembled from several nodes carries images from each
  of theirs — and since assets are content-addressed, "ask each in turn, first hit wins" is
  exact rather than a heuristic. **Belongs upstream** once the template has any markdown
  surface; it also deleted a duplicate of `DOCUMENT_MARGIN`/`LINE_HEIGHT_PERCENT` that had
  grown beside `framework/widgets.py`'s.
- **`framework/project_list_segment.py` — the flat index folder, extracted at its third
  user.** `modules/testing/index.py` wrote the shape and its docstring asked for exactly
  this: *"If a third segment ever wants this shape, that is the moment to extract it — not
  before."* The Docs folder was the third. What it holds is the half that is genuinely the
  same — rebuilding on the model's and the theme's signals, restoring which rows were open,
  and answering the panel's five hooks. **The menu name is an argument**, not a constant:
  `"Project"` is application vocabulary and has no business in a framework file, the same
  reason `IndexSegment` names a factory rather than a menu. The richer `projects/index.py`
  (nested entries, greyed unavailable rows, selection restored across a rebuild) is
  deliberately *not* folded in — it is a different problem that happens to draw rows too.
  **Belongs upstream** only if the template grows a second list-of-entities segment; on its
  own it is thin.
- **`LLMService` had no tests at all, and now has some.** It shipped complete and dormant —
  the first consumer found the API entirely sound, which is the good news — but nothing
  pinned the three refusal sentences an AI-gated control shows, the ring buffer, or the fact
  that a timeout is a distinct outcome. `tests/framework/test_llm_service.py` does, with a
  duck-typed fake provider and no `qapp`, which also proves the service needs no graphics
  stack beyond its settings accessors. **Belongs upstream with the service.**
- **A Qt suite on `-n auto` will eventually crash a worker, and the crash names an innocent
  test.** Ours does, in about one full run in three. `coredumpctl` gives
  `gc_collect -> subtype_dealloc -> ~QWidget -> deleteChildren -> QWidget::window()`: the
  collector freeing a widget cycle whose C++ side Qt had already destroyed. The template's
  `_collect_qt_garbage` fixture is the right guard and is not sufficient on its own — it
  works only while *every* test releases what it built, and one that does not poisons a
  worker for whatever runs next. Two things worth carrying upstream even before a fix: the
  reported test is only whichever one the worker was executing, so **do not debug it**; and
  `--dist loadfile` being green while `--dist load` is red is the signature that says the
  problem is cross-test rather than in the test. The cheap way to clear a new change of
  suspicion is to swap its new test files for the same number of `assert True` stubs — if
  the crash survives that, the change is innocent and the total test count was all that
  mattered.
- **A parentless `QObject` that connects a signal to its own method is a segfault waiting
  for the garbage collector.** The cycle keeps it alive past the build that made it, and
  Python frees it whenever the collector next runs — possibly inside another window's event
  dispatch, where Qt has already destroyed a parent. Park a worker's marshalling signal on a
  small QObject **parented to the window** instead, so `discard_build()` reaches it. The
  same applies to a plain Python signal holding a *widget's* bound method: use a Qt signal,
  which Qt disconnects when the widget dies.

## 9. From the asset-library pass

### `framework/asset_picker.py` — a modal picker over named files (new)

**What.** `AssetPickerDialog(entries, parent, title=)` over `PickerEntry(key, title,
detail, filename, read)`: an IconMode grid of DPR-aware thumbnails, extended selection,
double-click accepts, `chosen()` answers in `mime_files.Payload`s — bytes and a filename,
never a path. An entry whose `read` answers None (the file is gone; the catalog can be a
beat stale) is skipped, not fatal. Empty entries render a sentence, not an empty grid.

**Why.** The reuse half of the asset story. Payloads-not-paths is the load-bearing
choice: the dialog cannot know where a caller will put its choice, and a path handed
across that line becomes a link into somebody else's directory — the caller attaches the
bytes into its *own* area, which is the same copy-by-value rule `spec attach-to-step`
established.

**Belongs upstream?** Yes, with `asset_gallery` and `image_preview` — it knows nothing
but titles, details and byte readers.

### `framework/prose_edit.py` — `set_pick` beside `set_attach`

**What.** A second injected callable, `Pick = Callable[[], list[Payload]]`, and an
"Insert from Assets…" entry appended to the standard context menu beside "Insert Image…"
(disabled, never hidden, until both pick *and* attach are set). A picked payload travels
`_embed` exactly as a paste does — same copy, same link, same undo sealing.

**Why.** Two seams rather than one because they answer different questions — where a file
*goes* and where one can come *from* — and a host may have the first without the second.
Nothing new became undoable; the whole feature is a paste with a different source.

**Belongs upstream?** Yes, with the picker.

### `framework/prose_section.py` — `set_picker`, `set_area`'s sibling

**What.** Aims the editor's pick the way `set_area` aims its paste; cleared in
`show_target` alongside it (a re-pointed section must not pick for the old node), and
passed through to the expanded editor so the ⤢ dialog's menu matches the inline one.

**Belongs upstream?** Yes, wherever the other two go. `text_dialog.py` grew the matching
`pick=` pass-through in the same commit.

### `framework/image_preview.py` — Open Externally beside Copy Path

**What.** When a `path` is given, a second action button hands the file to
`QDesktopServices.openUrl`. The existence check runs at click time, never earlier — the
file can be gone by then, and a dead path handed to the OS fails silently on some
desktops.

**Belongs upstream?** Yes; it completes the lightbox's "let me actually see that" with
"…in the tool I trust for it".

---

## 10. From the step modal glow-up

### `framework/aspect_bar.py` — one submenu's toggles as a bar

**What.** Replaces `action_dialog.py`. `AspectBar(registry, context, templates, undo=,
menu=, submenu=)` renders every spec in one `(menu, submenu)` as a checkable `QAction` on
the right `QToolBar`, icon-only, and the `templates` — `AspectTemplate(label, toggles,
tone, glyph, catch_all)`, each a *set* of those spec ids — on the left, worded, with an
optional tone it wears when selected (a per-button stylesheet over the `:checked` rule);
one may be the catch-all, lit whenever no other matches. A template click
runs every differing spec through `registry.run` inside `undo.gesture(...)`; a template is
checked when the checked set equals its set, computed on every `refresh()`. `paint(ink)`
repaints the specs' `icon` painters and the templates' named glyphs. Overflow is
`QToolBar`'s own » extension button — no code of ours.

**Why.** A dialog you summon to see what a thing already is was the wrong reading of the
same registry. And the split into two bars is the Tests tab's trick: the left bar takes the
slack, so the side that folds first is the one whose entries still read as words in a menu.

**Belongs upstream?** Yes, as the sixth presenter in `action_dialog`'s place. Nothing in it
names an aspect. The `kinds` split and the tone are the only application-shaped inputs, and
both are plain data. The context is a `Callable[[], Context]` for the same reason the dialog's
was.

### `framework/undo.py` — `gesture(label)`: several pushes as one step

**What.** A context manager on `UndoService`. Every `push` inside the block is applied at
once (so later verbs see earlier ones' effects) and collected; on exit the collection lands
on the stack as one step named `label` — a private composite that redoes in order and
undoes in reverse, never merges — or as the single command when there was only one, or
nothing at all when there was none. A gesture inside a gesture belongs to the outer one.

**Why.** A template click runs five *other modules'* verbs. The alternatives were every
verb learning to hand back its command for a caller it cannot see, or the bar building
commands it has no business knowing — the gesture keeps each verb as it is and makes the
click one Ctrl+Z.

**Belongs upstream?** Yes, wholesale. It is thirty lines with no application in them, and
any presenter that runs several registered actions as one user gesture wants it.

### `framework/aspect_toggle.py` — a checkable toggle over a shelved entry

**What.** `aspect_toggle(...)` returns the `ActionSpec` for one on/off aspect: `state`
reads a predicate, `run` pushes `domain/shelf.turn_off`/`turn_on`. `focused_step()` beside it
is the six-line "the step the context focuses, if the library still has it" that eleven
modules had each copied.

**Belongs upstream?** The factory is DPlanner-shaped (it knows `Step` and `Project`); the
*shape* — a `(menu, submenu)` of independent checkable toggles built from one declaration
each — is worth a paragraph in the template's docs. `focused_step` is the kind of helper
`Context` could grow: `context.focused(kind, library.has)`.

### `framework/builder.py` — migrating what the domain shelved

**What.** The builder appends the domain's `shelf.DATA_FORMAT` to the modules' formats and
runs `migrate_shelved` after `migrate_module_data`, so data a module shelved at format *n*
comes back at the module's current format. The CLI's `discovery.py` does the same.

**Why.** Shelved data is a module's data at rest somewhere the module cannot see. Either the
migration pass reaches in, or turning an aspect on hands the module a shape it stopped
reading two versions ago.

**Belongs upstream?** The hook, if the template ever grows a shelf. `migrate_module_data`'s
private `_migrated` became public `migrated()` for it — that rename is worth carrying.

### `theme/tones.py`, and four icon painters widened

**What.** The canvas's body tones moved out of `project_editor/renderers.py` into the theme
package so a framework widget (the bar) can wear them. `edit_icon`, `read_icon`,
`branch_icon` and `gauge_icon` now accept `str | QColor` like the medallion painters, so any
of them can be an `ActionSpec.icon`. Two new glyphs: `ticket_icon`, `handoff_icon`.

**Belongs upstream?** The signature widening, yes — an `ActionSpec.icon` is `(QColor) ->
QIcon`, and a painter that only takes a `str` cannot be one.

### `QTabBar.setTabVisible` — a trap any per-target tab host will hit

**What.** Qt 6.11's `setTabVisible` begins `layoutDirty = (visible != tab->visible)` and
returns when unchanged — so it *clears* the dirty flag a previous call set — and it lays
nothing out itself (that happens lazily in `sizeHint()`), nor does it call
`updateGeometry()`. A loop that sets every tab's visibility from a predicate therefore ends
with the flag clean, the new tabs' rects empty, and the strip painting what it painted
before. `StepPanel._refresh_tab_visibility` calls it only on a change and then
`updateGeometry()`. A modal that used to open and close beside the strip had been hiding
this: its close relaid the parent.

**Belongs upstream?** As a note beside whatever tab host the template grows; the fix is two
lines wherever `setTabVisible` is driven from a predicate.

---

## 11. From the time-estimates crash

### A widget that sets its own height in `resizeEvent` loops inside a scroll area

**What.** Not a framework change — the fix is in a module — but a trap the template's docs
should name. `MonthsView` computed how many months fit the width in `resizeEvent` and
called `setFixedHeight` with the result. Inside a `widgetResizable` `QScrollArea` whose
vertical bar is *as needed*, that is a cycle: the new height decides whether the bar shows,
the bar takes 16 px of width, the width changes the column count, the column count changes
the height. Every step is synchronous (`setFixedHeight` → `updateGeometry` → the layout
re-activates → `setGeometry` → another resize event), so it is not a flicker but a
recursion, and it ended 184,800 frames deep in whatever function happened to touch the
guard page — `_Pep_PrivateMangle` in shiboken, which had nothing to do with it.

**The rule.** A widget whose height follows from its width is a *height-for-width* widget:
`sizePolicy().setHeightForWidth(True)`, `hasHeightForWidth()`, `heightForWidth(w)` as a pure
function of the width, and `resizeEvent` only re-reading the columns it will paint. Layouts
and `QScrollArea` both understand that contract and settle; a widget that answers a resize
by resizing does not.

**How to see it.** `gdb -batch -ex run -ex bt` on the crashing test and count the frames;
faulthandler's four-line Python trace and the symbol at the top of the C stack both
mislead here.

**Belongs upstream?** As a paragraph in the template's widget guidance, beside the palette
snapshot trap.

---

## 12. From the features-and-topology pass

### `framework/list_rows.py` — `TwoLineDelegate` (new)

**What.** The two-line list row the Specs tab had as a private delegate — name over a
quieter detail line, `DETAIL_ROLE` for the second line, `MUTED_ROLE` to draw a whole row in
the secondary tone — promoted into the framework, and taught three things there: an item's
icon (the text starts past the decoration the style draws), `EMPHASIS_ROLE` (a bold first
line) and `RULE_ROLE` (a hairline under the row), which together make a pinned row read as
a header. The Features panel turned out to want one-line rows and uses the stock delegate.

**Belongs upstream?** Yes; a side-panel list of named things with a second line wants it.

### `framework/asset_gallery.py` — `set_files(…, remove=)`

**What.** The files mode can now be given what removing a thumbnail means. Before, only the
area mode was editable; a record that *names* its images (a feature's `images` list) needs
the ✕ to drop the reference while the file stays for the sweep, and the gallery cannot know
that.

**Belongs upstream?** Yes, with the gallery.

### `project_editor/graph.py` — drop hooks on `GraphView` (module code, pattern worth noting)

**What.** `accepts(QMimeData) -> bool` and `dropped(QMimeData, QPointF)` on the view,
`setAcceptDrops(True)`, and the three drag events forwarding to them. The point is recorded
through `note_click` before the handler runs, so a dropped thing is placed the way a
clicked-for one is.

**Why note it here.** A drop is deliberately *not* a mode on the input stack — Qt's drag
events are a separate family that never reaches `mousePressEvent`, and a mode has state to
enter and leave. If the framework ever grows a canvas base class, this is the shape.

## 13. From the adopt-outside-changes pass

The window used to answer every outside change with `AppSession.reload()` — a second
window shown, the first discarded. It now reads the change into the live model
(`ARCHITECTURE.md`'s *Adopting the other writer's changes in place*). Four framework files
moved for it.

### `framework/window_watch.py` — the protocol widened, the busy guard dropped

**What.** `WatchableRepository` gains `adopt_outside_changes(*, take=)` and
`mark_seen(conflicts)`; `WorkspaceWatcher.__init__` no longer takes `is_busy`.

**Why.** The guard skipped the poll while this window owed a write, so that a pending
write of our own was never reported as somebody else's. Two things made it unnecessary: a
flush re-stamps the record *as it writes*, so our own files never read as foreign; and an
entry both sides changed is now the repository's per-entry conflict, which is a finer
answer than "not now". Keeping the guard would have delayed taking an agent's edit for as
long as the user kept typing.

**Upstream?** With the repository half, as before. The lesson that travels on its own: a
watcher that only reports is half a feature — the thing that knows what changed is the
thing that should take it in.

### `framework/session.py` — `refresh()` beside `reload()`, and the replacement's geometry

**What.** `SessionControl.refresh(*, forget_history=False) -> RefreshResult` adopts in
place and falls back to `reload()` when the repository says it must; `forget_history`
clears the undo stack once anything was taken. `_open()` hands the old window's
`saveGeometry()` to the new one and activates it.

**Why.** The rebuild is now the fallback, not the rule, and one seam had to say so for
three callers (the watcher, branch switch, pull). The geometry: a replacement that appears
at the default size in the WM's default place *is* the close-and-reopen the user sees,
even when the rebuild itself is instant.

**Upstream?** Yes. A session that can refresh is what any two-writer application needs;
the geometry hand-over is a one-liner every reload path should have had.

### `framework/undo.py` — `clear()`, and an entry the document refuses is dropped

**What.** `clear()` forgets the history and announces it. `undo()`/`redo()` catch
`KeyError`/`ValueError` from the command, drop that entry and the redo tail after it, and
seal — instead of decrementing the pointer first and leaving the stack pointing past a
still-applied command.

**Why.** Once a document can change under the stack, some entries stop being true: one
naming a step another writer removed, a positional text edit whose offsets moved under
adopted hunks. Clearing the whole history on every outside change would have thrown away
the user's work for an agent's status flip; dropping the one refused entry keeps the rest.

**Upstream?** Yes, both. The pointer-order bug was latent in the template.

### `framework/main_window.py` — geometry in the per-user store

**What.** `GEOMETRY_KEY` saved on close, restored on construction after the default size.
Bare `QSettings`, the convention for a window-level fact. Tests clear the `window` group.

**Upstream?** Yes.

### A module that used to die with the build now survives it

**What we found.** `modules/sync/module.py` kept a `pending_reload` flag set by
`worktree_changed` and consumed by the rebuild. With the window surviving a branch switch,
a flag nothing reset would have fired a spurious rebuild after the next Save. The general
form: **any state a module let the rebuild garbage-collect is state it now has to reset
itself.** Worth a look at every module that reads `SessionControl` when a reload path is
replaced by an in-place one.

## 14. From the telemetry-and-coalescing pass

The window was choppy on edits, and nothing in the framework could say why: every model
signal fanned out synchronously to every view, no view filtered by project, and no span
anywhere was timed. This pass gave the framework a journal, timed the seams it already
owns, and taught a view of one project to hear that project alone. Each change below is a
divergence from the template; every one is generic.

### `core/telemetry.py` — the journal, and `Signal.emit` timing its slots (new)

**What.** A Qt-free `Telemetry` — a ring of the last 2000 `Span`s plus an append-only
JSONL file under `config_dir()/telemetry/` — installed once per process like `logging`
(`install()`/`current()`; the default instance writes nothing, which is what every test
sees). `Signal.__init__` grew an optional `name` and `Signal.emit` times each slot: one
over `SLOW_MS` becomes a `slot` span named `Class.method (file:line)` (`describe_slot`,
which follows `__wrapped__` so a closure between the signal and the view names the
view). A raising slot is still logged, and the logging handler `install()` puts on the
root logger turns that — and every other `logger.exception`/`warning` in the tree — into
a `failure` span with its traceback, so no call site learned anything.

**Why it is the framework's.** `Signal.emit` is the one place a change's cost per listener
can be read, and the framework's own services are the seams worth timing:
`ActionRegistry.run` (an `action` span — every presenter goes through it now, see below),
`UndoService.push/undo/redo` (`command` spans: typing never passes through an action),
`TaskService.finish` (`task`), `AutosaveService.flush_now` (`autosave` — disk I/O on the
GUI thread), `WorkspaceWatcher._check` (`poll`), `AppSession._open`/`refresh` (`session`,
the largest stall the application has). `AppServices.telemetry` is the handle a module or
a test reads it through; the entry point installs the file-backed instance for both
surfaces, so a CLI run's row lands beside the window's in one file.

**Upstream?** Yes, whole. The trap worth stating with it: a handler on the root logger
swallows Python's last-resort stderr output, so `install()` adds a stream handler when
the root has none — the console keeps saying what it said.

### `framework/menubar.py` — a triggered entry runs through `ActionRegistry.run`

**What.** The bar's QAction called `spec.run(context)` directly, the one presenter that
did; it now calls `self._registry.run(sid, context)` like the pop-ups, the toolbar, the
palette and the aspect bar. Side effect, and a correct one: the state gate is re-asked at
trigger time rather than as of the last refresh.

**Why.** One path is one span site and one gate. Wrapping every spec at registration
(`dataclasses.replace` before `registered.emit`) would also have worked and was rejected
as the wrong cut: a per-spec closure to cover one caller.

### `framework/activity.py` — `follow_project` and `follow_target`; `retitle` names its entity

**What.** `follow_project(library, project_id, changed, *, signals=None)` connects a
callback to the model's signals — all five, or the ones named — filtered by the model's
own `belongs_to(node_id, project_id)` over the node each signal names (the parent of a
structure change, the step of an edge or text edit, the node of a field or module-data
write). `follow_target(library, target_of, changed, …)` is the same for a panel section
whose step moves under it. `follow_entity_tabs.retitle` retitles only the tab whose entity
the field signal names. The closure the signal sees carries `__wrapped__`, so the journal
names the view's method rather than the plumbing — without it every view's cost landed
under one `_follow.<locals>.on_change` line, which the first measurement showed.


**Why.** Seven modules carried the same unfiltered `lambda *_: self._refresh()` on every
signal, so a rename in one project rebuilt every other project's tabs. The filter is one
function beside `follow_entity_tabs`, which is the same shape (feature-blind upkeep
every entity tab was copying). The `Library` import into `framework/` follows
`module_data_section.py`'s precedent.

**Upstream?** The pair belongs beside `follow_entity_tabs` wherever that goes. The
`belongs_to` question is the model's; the template's model would answer it over its
own parent index the same way.

### `framework/debounce.py` — coalesced refreshes, and the service that settles them (new)

**What.** `Debounced(action, delay_ms, *, parent, service)`: `trigger()` restarts a
single-shot `QTimer`, so a burst runs the action once, after the quiet spell, over the
latest state; `flush()`, `cancel()`, `pending()`. A zero delay is "once this event-loop
turn is over". Each run is a `refresh` span in the journal named for the view's method
(the trigger carries `__wrapped__`), with how many triggers it folded — the number that
says whether coalescing earned its place. `DebounceService` on `AppServices` holds every
live one (a `WeakSet`, `shiboken6.isValid`-guarded) for `flush_all`/`cancel_all`, and
carries the **immediate** switch: `trigger()` runs inline. `discard_build` cancels them
all; the test suite's `session` fixture sets immediate.

**Why.** `AutosaveService` and the assets tab each hand-rolled the same timer, and every
other tab rebuilt synchronously on every signal — a paste of forty steps forty times, a
typed sentence once per keystroke. The first cut generalised `AutosaveService`; it was not
folded in, because autosave's timer also nests `pause()` and its flush is a transaction,
not a redraw — two policies in one class would have been the entropy the rule warns of.

**The part worth carrying up whole is immediate mode.** A suite that asserts on views
synchronously — every generated application's will — cannot adopt deferred rebuilds by
sprinkling `qtbot.wait` over a hundred tests; a per-build switch the fixture flips makes
the conversion cost zero test churn, and the deferred path is then tested exactly once
with real timers.

### `framework/diagnostics.py` — a stall watchdog, chained failure hooks, a crash log (new)

**What.** `StallWatchdog`: a 100 ms heartbeat `QTimer` on the GUI thread and a daemon
thread that, when the beat is older than 250 ms, samples the GUI thread's stack through
`sys._current_frames()` and opens a `stall` span carrying the sample and the spans open
on that thread, sampling again every 500 ms until the next beat closes it with the real
duration; with a crash log handle it also re-arms `faulthandler.dump_traceback_later`
every beat, so a hang that never releases the GIL still gets its stacks dumped by
faulthandler's own C thread. `capture_failures()` chains `sys.excepthook`,
`threading.excepthook` and `qInstallMessageHandler` into `failure` spans and returns the
undo; `open_crash_log()` is `faulthandler.enable` on `crash.log` beside the journal;
`session_started`/`session_ended` write the journal's session header and footer. All of
it is called from `app.main` and from nowhere deeper.

**Why nowhere deeper.** A test build has no event loop, so a heartbeat there reads as one
long stall; pytest-qt swaps `sys.excepthook` per test and pytest's thread plugin wraps
`threading.excepthook`, so a chain installed by the builder would be bypassed or would
fail tests that exercise a raising slot. The entry point is the one place that knows it
is the real application.

**Qt facts worth stating with it.** PySide6 prints a slot's or a virtual's uncaught
exception through `PyErr_Print`, which calls `sys.excepthook` and carries on — so a chained
hook sees them. Installing a Qt message handler *replaces* the default one, so the console
line is the handler's to print; forgetting that silences every Qt warning. A modal dialog
runs a nested event loop, so the heartbeat keeps beating through one and a dialog never
reads as a stall. `sys._current_frames()` from another thread is safe: it takes the GIL and
snapshots each thread's current frame.

**Upstream?** Yes, whole — with the journal it reports into.

### `framework/cards.py` — `CardStack.cards()` removed: never read a layout back

**What.** `CardStack.cards()` iterated `layout.itemAt(i)`; nothing called it, and it is
gone. The same read-back in two module views (`progression`'s `StatusColumn.cards()`,
`time_estimates`' `MilestoneList.keys`) now reads a list the view keeps itself, and a
test on each pins the rule by making `QLayout.itemAt` raise.

**Why — the crash.** 2026-09-04: one xdist worker died with SIGSEGV in the boundary
`gc.collect()`, deterministic for its four tests, gone with `-n0`, and it appeared when
an unrelated `Debounced` was added to the app shell — which only moved objects in the
collector's list. gdb: `~QBoxLayout` → `delete item` through a null vtable, an item freed
twice. `scripts/gc_catalog.py` (a `gc.DEBUG_SAVEALL` plugin, now checked in) showed the
`QWidgetItem`/`QSpacerItem` wrappers *before* their layout in the collector's order.

**The shiboken mechanics** (6.11.2, `libshiboken/basewrapper.cpp`). `SbkObject_tp_clear`
calls `Shiboken::Object::removeParent(self)` — whose default `giveOwnershipBack = true`
sets `hasOwnership` on the wrapper being cleared — and only then
`_destroyParentInfo(self, true)`, which *invalidates* that wrapper's own children. So in a
collected cycle, whichever wrapper is cleared first owns its C++ object from then on; its
children are made safe, its C++ owner is not told. PySide's glue for `QLayout::itemAt`
(`addownership-item-at` → `addLayoutOwnership` → `Shiboken::Object::setParent(layout,
item)`) makes every item wrapper such a child of the layout wrapper. A `QObject` in that
position is harmless — `~QObject` removes itself from its C++ parent — but
`~QLayoutItem` tells nobody, and `~QBoxLayout` deletes the item again. `takeAt` is
annotated `parent action="remove"` and its item is the caller's to delete, so a loop that
drops the wrapper each turn is correct. The order the collector clears a cycle in is not
allocation order once earlier collections have rescued and re-appended objects, which is
why the crash moved with an unrelated change and why the natural minimal reproducer does
not crash: the layout wrapper is cleared first there and invalidates its items.

**Upstream?** The rule, yes: a generated application's views will read a layout back the
first time somebody writes a test for one. A `framework/` helper cannot make it safe —
nothing short of `shiboken6.invalidate` un-parents the wrapper from Python, and that is
the magic the rule exists to avoid — so the answer is the list the view keeps. The
plugin is worth carrying up whole.

### `framework/asset_gallery.py` — a child layout joins its parent before it is filled

**What.** `AssetGallery.__init__` built its attach row as a parentless `QHBoxLayout()`,
gave it the button and a stretch, and only then `column.addLayout(attach_row)`. The row is
now added to the column first and filled after; nothing else changed.

**Why.** The suite's boundary `gc.collect()` segfaulted a worker (2026-09-04, evening) on
`test_asset_gallery.py::test_clicking_a_thumbnail_opens_the_preview`, on a branch that
changed nothing near it — the crash moved with an unrelated change, as §14's did.
`scripts/gc_catalog.py` listed the test's garbage in the collector's order: the bare
`AssetGallery` (a live Python-owned top-level widget, so its whole C++ tree dies inside the
collector), its layouts, and then a `QWidgetItem` and a `QSpacerItem` wrapper *after* the
layouts they belong to — cleared before their layout, handed ownership of an item the C++
layout still holds, deleted twice. Where the two wrappers came from was the surprise: a
parentless box layout given `addWidget` and `addStretch` *before* `addLayout` leaves both
alive on the Python side (a ten-line script shows 2 wrappers that way and 0 when the row is
added first, or built as `QHBoxLayout(self)`). PySide's ownership tracking for a layout
that is still Python-owned records the items as its children; once the layout is handed to
a C++ parent the records stay, unowned, and outlive every reason to exist. The reproducer
is in the commit that carried this note.

**The rule it adds.** Beside §14's *never read a layout back*: **add a child layout to its
parent before filling it** — `QHBoxLayout(self)` for a widget's own layout, or
`parent.addLayout(row)` first. And a *test* that builds a bare top-level widget disposes it
with `deleteLater` (the conftest dispatches deferred deletes before it collects), so the
tree dies under Qt's rules and never inside the collector; `test_asset_gallery.py`'s
`make_gallery` fixture is the shape. The pattern of a parentless row filled before joining
its parent occurs in 22 more files here, harmless while every one of those widgets is
deleted by `discard_build()` before any collection — the risk is only a bare widget left to
the collector — and worth a sweep upstream rather than one here.

**Upstream?** Yes: the rule, the reproducer, and the fixture shape.

## 15. From the segfault investigation

Three fixes in two days (§14's `cards()`, the gallery's row, the board's rows) had each
moved the suite's crash rather than ended it, and the desktop died on a click with a trace
no test covers. This pass reproduced both crash families on demand, with backtraces, and
moved the guard from convention into the framework. Each change below is generic; every
one belongs upstream.

### `framework/task_runner.py` — the worker never holds the last reference to a Qt object

**What.** `run()` no longer starts its thread with a closure over `self` and `body`. The
worker holds the signal instance (which keeps no reference to its QObject) and a
`_Handoff` carrying the runner, the body and its task; `_on_completed` schedules
`handoff.release()` with `QTimer.singleShot(0, …)`, so those references die on the GUI
thread on the next turn of the event loop, the way `deleteLater` works. A completion
whose runner was torn down mid-run logs a warning instead of dying with a thread
traceback. Nothing else changed.

**Why.** shiboken deletes a Python-owned QObject the instant its last Python reference
goes, on whatever thread that happens (`SbkDeallocWrapperCommon`). The old closure died
as the worker unwound — *after* it had queued the completion — and whenever nothing on
the GUI side still held the runner (a test that had returned; in the application, a body
closing over a parentless service), the C++ object was deleted on the worker while the
GUI thread delivered the very event just posted for it: SIGSEGV in
`QCoreApplication::notify` under `sendPostedEvents`, later, somewhere else. A 3000-round
stress of the real class under `MALLOC_PERTURB_` (create a runner, run an instant body,
drop the runner, pump events) killed the committed class 3 of 3 — SIGSEGV, SIGABRT,
SIGBUS: one bug, three allocator moods — and the new one survives 3 of 3 with every
completion delivered. `tests/framework/test_task_runner.py` records the freeing thread
with `weakref.finalize` and fails deterministically on the old code. Two simpler designs
were tried and rejected by the stress: releasing inside the completion slot frees the
runner's owner — and with it the runner — under its own slot (`Signal source has been
deleted` in `busy_changed.emit`); handing the references over inside `emit` leaves the
worker still inside `emit` when the GUI thread has already consumed the event.

**The rule it adds.** A worker thread holds nothing Qt-related except a signal instance,
and whatever it had to carry goes back to the GUI thread to be dropped there. A
thread-plus-queued-signal written by hand inherits the same hazard and goes through
`TaskRunner` instead.

**Upstream?** Yes, whole: the template's runner is the same file.

### `framework/gc_policy.py` (new), `app.py`, `tests/conftest.py` — the collector on our terms

**What.** `configure_application` calls `install_gc_policy(app)`, which does two things.
It switches Python's automatic cyclic collector off and runs `collect_if_due()` — one step
of the interpreter's own generational policy, thresholds and all — from a 200 ms timer on
the GUI thread, so a collection never happens on a worker thread or inside an event
handler. And it gives every QObject wrapper a finalizer (`QObject.__del__ =
release_cpp_children`, a `shiboken6.invalidate(self)`) that invalidates the wrappers of
its C++-created children while the tree is still intact. The conftest installs the same
policy for every test that has an application, and its per-test `gc.collect()` is now
*the* collection point of the suite (the timer rarely gets to run while tests pump events
by hand).

**Why — the finalizer.** §14's double delete needs a `QLayoutItem` wrapper cleared
*before* its layout, and the reproducer that eluded that pass is now a script. Python's
collector clears garbage in its list order, and a full collection walks generation 0
before generation 1 (each younger generation is appended to the tail of the oldest,
generation 0 first), so a young collection that lands between the creation of a layout's
wrapper and the creation of its items' wrappers puts the items ahead of the layout.
`gc.collect(0)` at that spot makes the crash deterministic —
`scripts/layout_item_double_delete.py`: `~QBoxLayout` through the deleted item's vtable,
3 of 3, for both the row-filled-before-`addLayout` shape and the `itemAt` read-back, with
or without the allocator poison — and explains why the crash moved with any allocation
elsewhere in the build: the young-generation threshold crossed at that spot, or it did
not. Python runs every finalizer of a garbage cycle before it clears any object in it
(PEP 442), so a finalizer on the parents sees the tree whole and invalidates the items
before `tp_clear` can hand one back; released shiboken (every 6.x through 6.11.2) hands it
back, and its `dev` branch's `tp_clear` detaches the children and keeps the parent link
instead, with a comment naming the second delete — the same fix, in C++, that no release
carries yet. With the finalizer both shapes survive 3 of 3, and
`tests/framework/test_gc_policy.py` pins them (without the guard that test segfaults the
worker — the crash is its finding). §14's *"nothing short of `shiboken6.invalidate`
un-parents the wrapper from Python, and that is the magic the rule exists to avoid"* was
right about the call and wrong about the moment: from a finalizer, at the one point where
the tree is intact and no wrapper has been touched, it is exactly what shiboken itself
does on the ordinary dealloc path (`_destroyParentInfo`). The one shape it cannot see is a
`QLayoutItem` constructed in Python and handed to `addItem` — shiboken counts it as
Python-made and `invalidate` leaves it alone; nothing here builds one.

**Why — the GUI-thread collector.** Left to itself the collector runs wherever an
allocation trips its threshold: on an LLM worker thread (the SDKs allocate plenty), where
deleting a QObject races the GUI thread's event delivery, or inside a Qt event handler on
the GUI thread, mid-dispatch, with half-built objects on the stack. The desktop crash of
2026-09-04 — a click on the graph canvas, `QGraphicsItem::setSelected` → a section's
`textChanged` slot → `QPlainTextEdit.clear()` → `QWidget::screen` →
`QGuiApplication::screenAt` on a garbage pointer — has the signature of exactly that: a
use-after-free surfacing far from its cause, in code that is correct on its own.
Collecting only from a timer slot on the GUI thread removes the trigger; the finalizer
removes the double delete; the runner removes the worker-side delete.

**The rule it adds.** §14's *never read a layout back* and the gallery's *add a child
layout to its parent before filling it* stay as hygiene, but the framework no longer
depends on them. New: never construct a `QLayoutItem` in Python; a worker thread never
frees a Qt object; and the amplifier for this whole family is `MALLOC_PERTURB_=165`
(Linux) / `MallocScribble=1` (macOS) — freed memory poisoned, so a use-after-free faults
at the first bad access instead of somewhere random. The suite's "random" crashes were
never random, only unpoisoned.

**Upstream?** Yes, both halves, the tests, and the script beside `gc_catalog.py`.

### `modules/github/module.py` — a deferred notice names its window (module code, pattern worth noting)

**What.** The one-time "gh not installed" notice was `QTimer.singleShot(0, lambda: …)`;
it now names `deps.parent` as the context object. **Why.** A build closed before that
turn came (every builder test) raised the notice's `QMessageBox` over a deleted window —
`RuntimeError: Internal C++ object (AppWindow) already deleted` in
`test_builder.py::test_a_closed_session_leaves_nothing_of_its_build_behind`, on all three
baseline runs of this pass. **The rule.** A zero-timer that touches a widget names that
widget as its context; CLAUDE.md already says so for views, and modules are no exception.

## 16. From the spec-coverage pass

### `theme/cards.py` — the card primitives, out of the canvas module (new)

**What.** `Shadow`, `RESTING_SHADOW`/`LIFTED_SHADOW`, `paint_shadow`, `over`, `title_font`,
`title_lines` and the card metrics (`RADIUS`, `PADDING`, `PAD_Y`, `LINE_GAP`,
`TITLE_POINTS`, `LIFT`, `SECONDARY_ALPHA`, `FILL_ALPHA`, `SELECTED_BORDER_W`,
`SELECTED_FILL_GAIN`) moved verbatim from `modules/project_editor/renderers.py` into
`theme/`, beside the tones and glyphs they were already painted with. **Why.** A second
surface paints cards — the coverage view's four columns — and modules never import each
other, so the shared half had to live in a layer both may reach. `renderers.py` keeps
everything that is the graph's own (ports, marks, rings, badges, `PAINT_MARGIN`) and
composes from here. **Upstream?** Yes: a template with a canvas will paint cards elsewhere
sooner or later, and `theme/` is where a painter's vocabulary belongs.

### `framework/inspector.py` — `FocusableExtension`, an optional answer to "show this thing of yours"

**What.** A second, `runtime_checkable` protocol beside `InspectorExtension`:
`focus_entity(kind, entity_id) -> bool`. A section that holds addressable things — the
Tests tab a test, the Feature tab a record — implements it; the host (`StepPanel.focus`)
asks each visible section in turn and brings forward the first that answers True. **Why.**
A jump from the coverage view names a *test*, not a step, and `steps.details` should land
on it. The kinds are the selection scope's own (`"test"`, `"feature"`), so a caller
synthesises a context carrying the step and the thing and no verb grew a parameter; a
section with nothing addressable implements nothing and is never asked. **Upstream?** Yes —
the protocol and `StepPanel.focus` together; it is the general "open the detail panel on a
sub-item" every inspector eventually wants.

## 17. From the multi-agent worktree pass

### `core/storage/git.py` — `main_checkout(root)` beside `find_repo_root` (new)

**What.** One function: the main checkout a linked worktree belongs to, read from the
worktree's `.git` *file* (`gitdir: <main>/.git/worktrees/<name>`), or the root itself
when it is not a worktree. Re-exported through `core/storage/locations.py` like
`find_repo_root`. **Why.** Two callers above the storage layer needed the same six lines:
the CLI's project discovery — an agent running `dplanner` inside its worktree has to
resolve the library's project, not the branch's copy of the plan — and the skill's
caution against an editable install into a worktree, which had the parse inline.
**Upstream?** Yes, with `find_repo_root`: any template application that opens a
repository and can be run from a linked worktree wants the same answer, and the `.git`
file's format is git's contract, not ours.

## 18. From the plan-repository pass

### `core/storage/git.py` — `canonical_remote`, `remote_label`, `activity` (new)

**What.** `canonical_remote(url)` folds every spelling git accepts for one remote — https,
ssh, scp-like, with a user, a port, `.git` — into `host/owner/repo`, lowercased, and a
local path into its resolved self. `remote_label(url)` is the same split kept readable
(`Acme/Widget` for GitHub, `host/…` elsewhere), and `GitHubStorage.remote_label()` now
delegates to it instead of parsing on its own. `activity(root, path, limit)` reads the last
commits under one directory: who touched it last and when, everyone who did, how many.
**Why.** A project's code repository is stored as its remote URL and matched against a
checkout's `origin` on every `dplanner` call, so two spellings of one repository must
compare equal; the project browser lists a plan repository's projects with who is on each.
**Upstream?** Yes: any application that records a repository by its remote needs the first
two, and the third is one `git log` format worth keeping.

### `core/storage/locations.py` — `repo_storage(repo_root, scopes)` (new)

**What.** The whole-repository provider `grouped_by_repo` already builds, exposed at the
front door with explicit pathspecs. **Why.** Moving a plan commits in two repositories the
store holds no project in, and the Project dialog reads a code repository's log; both live
above the storage layer and may not name a provider class. **Upstream?** Yes, with
`grouped_by_repo`.

### `core/storage/pointer.py` — the `.dplanner` file is an index, and `WORKTREES_DIR` lives beside it

**What.** `write_pointer` became `add_to_index`: one line per project directory,
appended, never rewriting a hand-written line; `remove_from_index`, `read_index`,
`resolve_index` and `write_index` beside it. A one-line file is exactly the pointer it was.
`WORKTREES_DIR` moved here from the agent launcher, because the plan repository scan in
`domain/` has to skip that directory and may not import a module. **Why.** A plan
repository holds several projects for several people, and the committed list of them is
what a clone needs to say which projects it holds. **Upstream?** The index, yes, with the
pointer it grew from; the constant is DPlanner's.

### `core/storage/git.py` — `GitStorage.commit` leaves out a scope nothing matches

**What.** Before staging, each scope is checked to exist in the tree or to be known to
the index; one that is neither is dropped, and a commit with no scope left answers False.
**Why.** Moving a plan commits its removal from the repository it left; when the plan was
never tracked there — created and moved before anybody saved — `git add -A -- planning`
fails on the pathspec, and that failure would have failed a move whose files were already
where they belonged. **Upstream?** Yes: a scoped commit that cannot fail on an absent
scope is what every caller wants.

### `core/storage/github.py` — `GitHubStorage.create(name, dest)` (new)

**What.** The third classmethod beside `clone` and `publish`: `gh repo create --clone`
for a repository nobody has started yet, cloned into a chosen directory (gh lands the
clone under the repository's own name beside where it runs, so it runs in the parent and
renames). **Why.** The Project dialog's *new code repository* glyph: a plan that names
code nobody has started. **Upstream?** Yes, with the other two.

### `core/storage/github.py` — `push` rebases onto origin first, `pull` rebases instead of fast-forwarding

**What.** Both fetch, then rebase the checkout onto `origin/<branch>` when the two
diverged (`--autostash`, so an uncommitted edit rides along); a conflict is aborted —
the stash restored — and refused with the tree as it was, the same refusal the old
`--ff-only` gave. `push` emits `worktree_changed` when the rebase brought commits in,
so the window reads them the way it reads a pull. **Why.** A plan repository is written
by several people and every *Save* is a commit, so two clones' branches diverge on an
ordinary afternoon, and the second Save used to be rejected by the remote for being
second. Two Saves are commits to different files far more often than a conflict. It
applies to a code repository holding its plan as well, and the failure mode — a real
conflict — is exactly what the old refusal was. **Upstream?** Yes: any application whose
Save is a push wants the second writer's push to land.

### `framework/window_watch.py` — `WorkspaceWatcher` takes a parent

**What.** The watcher's constructor takes the window as its parent, and the library-watch
module hands it over. **Why.** A reload discards a build with `deleteLater` on the window
but stopped nothing the modules had started: the watcher's poll timer kept firing every
two seconds against the discarded build, and its adoption ran into the deleted status-bar
button (`libshiboken: Internal C++ object (OutsideChangesButton) already deleted`, once
per poll, after a Move Plan reload and at close). A QObject owned by the window dies with
it, timer and all — the same reason the module's ask-soon timer was already the window's.
**Upstream?** Yes: a watcher that outlives what it watches for is a bug in any host.

## 19. From the reporting pass

### `core/markdown.py` — a stdlib markdown-subset renderer (new)

**What.** `render(text, *, image_src=None) -> str`: headings, paragraphs, emphasis, code
spans and fences, one level of nested lists, blockquotes, rules, links, images through a
callback, GFM tables; every user string HTML-escaped, `javascript:` and relative links
rendered inert, never raises. **Why.** The report inlines descriptions, decisions and
handoffs into a single HTML file. Python-Markdown is BSD-3, which would have been fine on
licence, but the project judges a dependency on supply-chain surface too, and a bounded
subset is ~300 lines of stdlib — the same trade `core/png.py` made. **Upstream?** Yes: any
template application that shows user markdown outside Qt wants it, and the escaping
discipline is the part worth sharing.

### `core/xlsx.py` — a stdlib `.xlsx` writer (new)

**What.** `Sheet(name, columns, rows)` and `workbook_bytes(sheets)` / `write_xlsx(path,
sheets)`: inline strings, numbers, dates with a date style, a bold frozen header, column
widths, sanitised sheet names, and byte-for-byte deterministic output (fixed zip
timestamps and order). Verified against LibreOffice. **Why.** Spreadsheet export without
`openpyxl`, for the same dependency rule; an `.xlsx` is a zip of six XML parts.
**Upstream?** Yes, as-is.

### `core/fsio.py` — `write_csv(path, rows)`

**What.** The five-line utf-8-sig CSV writer, moved here from `modules/step_order/export.py`.
**Why.** A second module (time estimates) needed it and modules never import each other.
**Upstream?** Yes, beside `write_atomic`.

### `core/storage/provider.py`, `git.py` — `commit(message, also=())`

**What.** `VersionedStorage.commit` takes extra repository-relative pathspecs recorded in
the same version as the scoped workspace; `GitStorage` adds them to `add -A`, `diff
--cached` and `commit --`. `refresh_dirty` and `diff` stay scoped. **Why.** A publication
written beside the plan (the reports site) must land in the plan's own commit without
becoming "unsaved work" when stale, and the sync module may not name the concrete
provider, so the parameter belongs to the protocol. **Upstream?** Yes: any application
that generates an artefact beside what it versions has this need.

## 20. From the Time tab refinements

### `framework/toolbar.py` — `control_bar(parent)` (new)

**What.** The `QToolBar` a tab page uses as a strip of its *own* controls — movable and
floatable off, the icon size set, the inner layout's spacing and margins set, object name
`#ControlBar` (was `#TestsToolBar`; `theme.qss`'s rule renamed with it). **Why.** The tests
page and the docs page each hand-rolled the same ten lines, and the Time tab was about to
be the third: a `QToolBar` is the one widget in Qt that degrades a full control row
gracefully (the » overflow menu) instead of overlapping it, so every page that has a row
of controls wants exactly this. **Upstream?** Yes, beside `ActionToolbar`; the QSS rule
with it.

### `framework/cards.py` — `card_rule(parent, *, vertical=False)`

**What.** The 1 px rule can stand up: `vertical=True` fixes the width instead of the
height. **Why.** The estimate input parts *Does not add time* from the size chips with a
rule in one row. **Upstream?** Yes, trivially.

## 21. From the notes pass

### `core/module_data.py` — `ModuleDataFormat.absorb`, and `migrate_module_data` takes the document

**What.** A format may declare an `absorb(repo, document) -> changed owner ids` pass, run
once per open after every per-entry migration and takeover; `migrate_module_data` grew a
third argument, the loaded aggregate, which it hands through untyped. The builder and the
CLI's `open_library` pass it, and the builder flushes `module_text` beside `module_data`
for every owner the pass names. **Why.** A `Takeover` converts one entry on one owner; it
cannot move a step's prose into a record on its project, which is what retiring the
handoff aspect into the notes log needed. Only the aggregate knows how owners relate, and
only the module knows the record it is building, so the pass is the module's and the
document is its argument. **Upstream?** Yes: the shape (per-entry chain, takeover,
absorption) is complete now, and the third is the one a merge of two features always ends
up wanting.

### `core/repository.py` — `FileArea`, and `Repository.files(owner_id, module_id)`

**What.** A `FileArea` protocol (`names`, `read_bytes`, `write_bytes`, `remove`) and a
`files` accessor on the repository protocol. `ModuleFileArea` already satisfied it; the
protocol only names what an absorption is allowed to touch. **Why.** The absorb pass moves
a module's files with its data, and the framework's protocol was the only face it had.
**Upstream?** With the absorption, yes.

## 22. From the redirect and menu pass

### `framework/palette.py` — a palette row is the two-line row, and the path is searchable

**What.** The command palette renders `list_rows.TwoLineDelegate` instead of
`label\tshortcut` in a plain item: the label on line one with the shortcut right-aligned
beside it, the verb's **menu path** (`Graph ▸ Divide`) on line two, and the spec's `icon`
as the row's decoration. `menu_path(spec)` is the one place that path is built. Filtering
scores the label first and the path second — a match that needed the path ranks below every
match on a name, as a `(where, -score)` sort key rather than a fudged constant.

**Why.** Submenu entries are written for their submenu, so the palette listed *Vertical* and
*Horizontal* with nothing to say which pair they were. The label cannot be lengthened — the
menu would then read *Divide ▸ Divide Vertically* — so the missing half is the path, and once
it is on the row it may as well be searchable: somebody who remembers the submenu and not
the entry types "divide vertical". The glyph is free and correct here for the same reason it
is in a pop-up: the palette is built fresh on every open, so a colour baked into it cannot
go stale the way the menu bar's QActions can.

**Upstream?** Yes, whole. Nothing in it is DPlanner's vocabulary.

### `framework/list_rows.py` — `TRAILING_ROLE`, a note at the right of the first line

**What.** A fourth role on `TwoLineDelegate`: text drawn right-aligned on the *first* line in
the secondary tone. It is measured before the name is drawn, so the name elides against what
is left rather than under it.

**Why.** A shortcut is a fact about the row, not part of its name, and every command palette
in every application puts it in that exact place. The delegate already owned the row's two
lines; this is the only spot on them that was unspoken for. **Upstream?** Yes, with the row.

### `theme/icons.py` — `_arrow(painter, start, end)`, and seven glyphs on it

**What.** A shared painter for "a line with a chevron at the end", plus `link_icon`,
`connect_icon`, `redirect_to_icon`, `redirect_from_icon`, `divide_vertical_icon` /
`divide_horizontal_icon` (one `_divide_icon` rotated), `sort_icon`, `region_icon` and
`grid_icon`. `trash_icon` and `frame_icon` widened from `str` to `str | QColor` like their
neighbours, because an `ActionSpec.icon` is handed a `QColor`.

**Why.** Three of the new glyphs are arrows and were about to hand-roll the same trigonometry.
The widening is the older half of the file catching up with `ActionSpec`'s signature — mypy
found it the moment those verbs were given icons. **Upstream?** The `_arrow` helper and the
signature fix; the glyphs are this application's vocabulary.


### `framework/toolbar.py` + `theme/theme.qss` — a button's dropdown arrow is a target

**What.** `ActionToolbar._attach_menu` sets `hasMenu` on the buttons it gives a menu, and the
stylesheet turns Qt's `::menu-button` into a real half: `ARROW_W` (20 px) wide, parted from
the button half by a `$BORDER` hairline (`$ON_ACCENT` while the button is checked, where a
border-coloured line would vanish into the accent fill), with `ARROW_ROOM` of right padding
on the button so the words step aside for it.

**Why.** Qt sizes that arrow from `PM_MenuButtonIndicator` — about ten pixels — and a styled
`QToolButton` renders it as a thin raised sliver at the button's edge: unaimable, and it
reads as a rendering fault rather than as an arrow. The padding is the other half of the
same fact, and the trap worth writing down: **a styled subcontrol sits outside Qt's size
hint**, so widening `::menu-button` alone paints the arrow over the last letter — which
looks exactly like a rule that did not apply. `tests/test_theme.py` renders the button and
asserts both, in the splitter seam's spirit: it fails when either half is removed.

**Upstream?** Yes, both. Any application whose toolbar buttons carry menus hits it.


## 23. From the spotlight pass

### `theme/cards.py` — `DIM_OPACITY`, what a lit surface fades the rest to

**What.** `DIM_OPACITY = 0.35`, moved out of `modules/coverage/scene.py` (where it was
written for the trace's lit path) and now read by the canvas's spotlight too.

**Why.** Two surfaces light part of themselves and fade the remainder, and modules never
import each other, so the number had to live where both may reach — the same argument that
put the card primitives here. The rest of the pattern is worth carrying with it: **fade by
`QGraphicsItem.setOpacity`, never by a paint-level flag.** One number takes a card's fill,
border, title, glyphs and the shadow under it down together, which is what receding is; the
painter never learns that a lit state exists, and there is no second "muted" path to keep
agreeing with the first. **Upstream?** Yes, with the card primitives — any canvas that can
light a subset of itself wants the constant and the rule.


## 24. From the spec-sources pass

### `framework/secrets_store.py` — `backend_problem()`

**What.** Asks keyring which backend it chose and returns a sentence when a secret could
not be kept safely: the `fail`/`null` backends (no keychain service — on Linux, the
GNOME Keyring / KWallet remedy), a `keyrings.alt` plaintext backend, or a backend that
cannot even be asked. `set_secret` keeps swallowing errors; this is for the surface
*about to* store a credential, so it can refuse with the remedy instead of storing nowhere
silently — the lesson `gh auth login` learned the hard way. It probes the backend rather
than writing a probe value, because a write is what raises a keychain prompt.

**Why.** A Confluence token goes through a guided Connect dialog on macOS, Linux and
Windows, and "connected" must never be a lie. **Upstream?** Yes, as-is.

## 25. From the snappy-edits pass

### `framework/context.py` + `framework/builder.py` — the context is announced once per turn

**What.** `ContextService` grew `announce: Callable[[], None]`, defaulting to
`announce_now()` (`changed.emit(current())`); `set_scope`, `clear_scope` and `refresh`
update the snapshot synchronously and call `announce()`. The builder, once the window
exists, sets `context.announce = Debounced(context.announce_now, 0, parent=window,
service=debounce).trigger`. The app shell's own `poke_context` `Debounced` (an undo push,
a tab switch, a theme or panel change re-asking every state) went with it — it was a
debounce of a debounce — and `AppShellDeps` lost its `debounce` field.

**Why.** The docstring said emission was synchronous because "menu-state re-evaluation is
cheap (a few dozen pure callbacks)". On a real plan it was ~150 states, six toolbars per
canvas, the menu bar and the panel dock, and a connect gesture published seven times with
an empty selection in between — so the step panel stepped aside and came back twice, at
`QSplitter.setSizes` prices, per gesture: 1.7 s on the GUI thread. `current()` is all any
"publish then act" path reads, and every `changed` listener is display, so one
announcement per turn over the final state changes nothing visible and removes the
multiplier for good. The test suite runs `DebounceService` immediate, which keeps every
existing test synchronous — the determinism argument the docstring made now lives there.
The `action` span in the journal no longer contains the fan-out; it moves to the
`refresh ContextService.announce_now` span, whose `coalesced` count says how many
publishes one announcement stood for.

**Upstream?** Yes, whole. The seam is three lines and the builder's wiring one; any
application with a context service and a dock will hit the same multiplier the day a
gesture publishes twice.

### `framework/panels.py` — nothing changed, and that is the note

The dock relays itself only when a panel's `show_context` answer flips, which is right.
What made a flip cost 200 ms was a *module's* panel clearing its cards when it stepped
aside (`ProjectPanel`, fixed in the module) and the widget tree under it. Worth saying to
whoever brings a `ContextPanel` upstream: "off screen" and "showing nothing" are different
states, and the dock only ever asks for the first.

## 26. From the Docs-folder pass

### `framework/project_list_segment.py` — child rows under each project

**What.** Beside `LeadingRow` (a row above the projects) the segment takes `children:
Sequence[ChildRow]` — a label, an icon and `open(project_id, preview)` — and draws one row
per child under every project row, keyed `<prefix>:<project>:<index>` in `UserRole` so
`expansion_of`/`restore_expansion` keep the project row's open state across a rebuild.
`KIND_ROLE` gains `"child"` and a `CHILD_ROLE` carries the index; `selection_nodes` and
`context_menu` treat a child as its project (`PROJECT_KINDS`), so every Project verb and
the Project menu work from it. The Docs folder is the user: *Documentation* and
*Implementation notes* under each project, each opening its own tab.

**Why.** The notes had been a second reading inside the Docs tab behind a switch, and the
index — where a reader looks first — said nothing about it. Generalising the flat segment
was smaller than a second segment class and leaves the two folders one code path; the
richer `projects/index.py` (nested *contributed* entries, greyed rows) is still a
different problem and stays separate.

**Upstream?** Yes, with the segment itself if it goes: a folder of entities whose surface
has more than one reading is the ordinary case, not this application's.

### `framework/widgets.py` — `EmptyState`

**What.** A widget for what an empty page says: one line at a readable measure
(`centered_column`), a point smaller, `#EmptyStateText` in the secondary ink, centred
both ways; `say("")` hides it. The Docs, Tests, Assets and Implementation notes pages use
it in place of a `QLabel` each had appended to the end of its layout.

**Why.** Each page's label landed wherever the layout left room — the bottom-left corner
of a tall empty page — and read as a stray footer. One widget, one look, and DESIGN.md's
*Empty states* names the rule.

**Upstream?** Yes: every application has empty pages, and the trap (a label after a
stretched widget) is generic.

## 27. From the theme-providers pass

### `framework/theme_service.py` — a choice over providers, followed by a poll

**What.** `ThemeService(app, providers, parent=…)` resolves a persisted choice (`"system"`,
`"<provider>/<name>"`, or a legacy bare name) over a tuple of `theme/providers.py`
records; `set_theme(choice)`, `set_enabled(id, on)` (a per-user switch through
`user_config`), `check()` (the poll body, on a `QTimer` at `window_watch.POLL_MS` while a
following provider serves the choice), `effective_choice` (a field), cached `refusal()`s,
and `apply_saved_theme(app, providers)` for the startup apply. `apply_theme` grew
`follow_system`, which clears the colour-scheme override instead of setting one.

**Why.** Themes were a table; a desktop that changes underneath the window needs a
reader, and Qt's own reading echoes the application's override once one is set, so the
service owns both the poll and the override. The reasoning is in `ARCHITECTURE.md`'s *A
theme is provided, never listed*.

**Upstream?** Yes, with the contract: a template that ships twenty-two themes in a menu
wants a provider seam more than it wants the twenty-two.

### `framework/builder.py`, `framework/session.py` — `with_theme_providers`

**What.** The builder carries `_theme_providers` (default `(BUILTIN,)`, not in
`_require()`), the session takes `theme_providers=` and hands it through, and the
service is built with `parent=window` so a discarded build takes its timer.

**Why.** Modules must not build a second tuple, and a test build must never read the
desktop: the machine's tuple is named once, in `app.main`.

**Upstream?** With the service.

### `framework/action_registry.py`, `menubar.py`, `action_menu.py` — a child menu may nest

**What.** `PATH_SEPARATOR` moved from the palette to the registry, beside
`ActionSpec.submenu`, and a submenu title holding it (`"Theme ▸ Omarchy"`) nests: the bar
walks the path creating each level at the first spec's key (keyed by path in
`_submenus`/`_separators`) and computes child-menu visibility deepest first (`reversed`
creation order); the popup walks the same path with the group bookkeeping per container.
The `submenu=` filter still names one level.

**Why.** Twenty-five themes in one child menu, and the palette keeps every entry only if
they stay specs — a `DataMenuSpec` would have nested for free and lost the palette.

**Upstream?** Yes: nesting is a general want, and the visibility-order bug is a trap.

### `framework/debounce.py` — a settle is deterministic

**What.** `DebounceService` keeps its `Debounced`s in a `WeakValueDictionary` keyed by
registration count, and `flush_all` re-runs what a flush made pending, up to
`SETTLE_ROUNDS`.

**Why.** A `WeakSet` iterates in hash order, which moves with every allocation in the
process: a Time-tab test that asserts "Recalculating…" is hidden after `flush_all` passed
on one commit and failed on the next, because the progress recorder (which writes after a
change the tab then hears) flushed after the tab instead of before. A settle that runs in
build order and to completion cannot do that.

**Upstream?** Yes — this is a flake generator in any application with two views that
wake each other.

### `theme/__init__.py` — the package imports without Qt

**What.** The Qt-bearing imports (`Qt`, `ui_font`, `build_palette`, `build_style`) moved
inside `apply_theme`; `QApplication` is a `TYPE_CHECKING` import.

**Why.** A theme provider is Qt-free by contract and reads `theme.themes`,
`theme.providers` and `theme.omarchy`; `tests/test_architecture.py` now probes it.

**Upstream?** Yes, trivially.

## 28. From the design-system pass

### `framework/dialog.py` — `DialogFrame` and `LinePrompt` (new)

**What.** A `QDialog` with the anatomy DESIGN.md's *Dialogs* names: the title printed in
the body (`#DialogTitle`, +2 pt via `theme.cards.title_font`), a lead (`#DialogLead`), a
body (`#DialogBody`, a `QVBoxLayout` the subclass fills) inside a page that carries the
dialog's margins, and below it a footer band (`#DialogFooter`, edge to edge on the elevated
ground under a faint hairline) whose slots run destructive · status · stretch · secondaries
· dismiss · primary.
`set_primary`, `add_button(destructive=)`, `add_dismiss`, `refuse(reason)`; the dismiss is
default only while there is no primary; Ctrl+Enter is the primary from a multi-line field;
`showEvent` sets the Tab chain (body → primary → secondaries → destructive) and puts focus
on the first field or the default button. Three sizes: fit (a 420 px floor), framed
(clamped to `SCREEN_SHARE`), editor. `LinePrompt` is one captioned field and a verb, refused
while blank or while `validate` objects, with a class method `ask`.

**Superseded by §30 (S6):** the title and the lead were taken out of the body. A
heading inside a dialog repeats the title bar and pushes the content down; `title` now
names the window only, and what a dialog is about is said by its content.

**Why.** Twenty-four dialogs, two button strategies, margins of 20/16/12/8/none, four that
set focus, a footer whose default was *Clear*. The frame names its parts so the stylesheet
reaches every dialog through two constant names — the enumerated `#X QPushButton` lists
were the alternative, and they are what made a new dialog Fusion by default.

**Upstream?** Yes, whole. Every application has dialogs, and the specificity trap
(`#Host QPushButton` beats `#PrimaryButton`; `QPushButton#PrimaryButton` ties and wins by
position) is Qt's, not this application's.

### `framework/table.py` — `Table`, `Column`, `Cell`, `TableDelegate` (new)

**What.** A `QTableWidget` (`#Table`) whose columns are declared (numeric, glyph, two-line,
resize mode) and whose configuration is applied once; the row height computed from the
font (`row_height`) and set on the vertical header; a delegate that blanks the option's
text and icon in `initStyleOption` and paints the row tint, the hover wash (from a hovered
row the view tracks through `entered`/`viewportEntered`/`leaveEvent` — Qt's `State_MouseOver`
is per cell), a 2 px `QPalette.Accent` edge on column 0 of a picked row, the reserved glyph
slot, elided one- or two-line text in the palette's `Text` (never `HighlightedText`: the
picked ground is the quiet overlay). `add_row` stamps a tint and the host's roles on every
cell; `add_heading` is a spanned `NoItemFlags` row; `fit_columns` opens interactive columns
at their content; `initStyleOption` also strips `State_HasFocus`, since the style's focus
frame round the current cell lingered as a box on the last cell clicked. `list_rows.py`
gains `TINT_ROLE` and `HEADING_ROLE`.

**Why.** Three hand-written copies of one configuration disagreeing on nine settings, and
four widgets borrowing `#OrderTable` by name. The per-row `setRowHeight` versus
`setDefaultSectionSize` split was a real bug in the Tests table.

**Upstream?** Yes, with the delegate. `QTableWidget` over model/view is this application's
choice (no table here has more than a few hundred rows); the delegate and the configuration
transfer to a `QTableView` unchanged.

### `framework/list_rows.py`, `theme/cards.py` — the second line a point smaller, the icon on the first line

**What.** `theme.cards.detail_font(base)` is the secondary face (`DETAIL_POINTS = 1.0`
down; `EmptyState` takes it too). `rich_row_height(font)` is the one formula both delegates
size a two-line row from — two lines at two sizes, the gap, the padding. `TwoLineDelegate`
now paints its own icon, on the first line, rather than letting the style centre it on the
row; `TableDelegate.glyph_rect` does the same for a table.

**Why.** A row's second line is *about* the first and should say so in size; and a glyph
centred between a title and its key belonged to neither.

**Upstream?** Yes, with the delegates.

### `framework/toolbar.py` — `Toolbar`: glyphs with tooltips, folding into a … menu

**What.** `Toolbar(QWidget)`: `add_verb(text, painter, slot, shortcut=, checkable=)` puts a
`QToolButton` with a default `QAction` on the strip — icon only, the words and shortcut as
the tooltip, re-inked from the palette's text at `SECONDARY_ALPHA` on a palette change;
`add_widget`, `add_divider`. `resizeEvent` shows what fits from the left and hides the
rest; a `…` button lists the hidden verbs as glyph and words in a `QMenu` rebuilt on open,
a widget never enters it, and a divider never ends what is shown. Every control is
`CONTROL_HEIGHT` tall by `setFixedHeight`. Its `sizeHint` is the … button's.

`FilterButton`: a face (`#FilterButtonFace`, the funnel and the word, an `InstantPopup`
over a `_StayOpenMenu` of checkable `QAction`s that stays open on a toggle) joined to a
clear button (`#FilterButtonClear`, greyed until a filter is on); `add_filter(key, text)`,
`active()`, `set_active()`, `clear()`, a `changed` Signal. The indicator is the glyph
(`theme.icons.filter_icon(active=)`, 24 px wide with the dot's slot at its left) and a
dynamic `active` property the stylesheet reads for the accent wash (`$ACCENT_WASH`, derived
in `as_qss_mapping`) and border.

**Why.** `QToolBar`'s » pops the hidden buttons up as glyphs again, which is nothing once
the words live in tooltips; and a worded button, a glyph button and a button with a menu
disagree by a few pixels under the style, so the height is set in code. The filter's
indicator lives in the glyph so the face never changes size.

**Upstream?** Yes. `ActionToolbar` becomes this fed by the registry.

### `theme/__init__.py`, `theme/icons.py`, `theme/tokens.py` — the arrow, the key badge, derived tokens

**What.** `drop_arrow_url(theme)` writes a 10×6 SVG in the theme's secondary ink to the temp
dir (per colour, once) and `load_stylesheet` substitutes it as `$DROP_ARROW`; `key_badge_icon(text, colour)` paints `F1`/`M2` as a rounded chip `KEY_BADGE_W` wide at a glyph's
height; `refresh_icon`; `tokens.mix` and a derived `$BORDER_FAINT` (the border halfway into
the ground) beside `CONTROL_HEIGHT`. `Table`'s glyph slot is `KEY_BADGE_W` wide.

**Why.** Styling a combo's drop-down takes Fusion's arrow away, Qt draws a stylesheet
image only from a file, and a border-drawn triangle flattens into a bar at a 2× scale.
A derived token spares every theme provider a field it would never set.

**Upstream?** The arrow and the derived token, yes; the badge is this application's.

### `framework/signalling.py` — `UpdatingIndicator`, `StatusLine` (new)

**What.** `UpdatingIndicator.follow(debounced)` connects `pending_changed` to a weakly-held
`setVisible`; `retainSizeWhenHidden` so a strip never reflows. `StatusLine.say(text, tone)`
sets rich text — a `●` coloured by `theme.tones.STATUS_TONES` for busy/ok/error, the label's
own ink for info — and hides on "". Both `$TEXT_SECONDARY` in the stylesheet.

`Spinner(parent).attach(button | action).follow(debounced)` turns a three-quarter arc
(`theme.icons.spinner_frames`, twelve frames, one turn a second) in the target's glyph slot
while the debouncer owes a run — or between `start()` and `stop()` — and puts the glyph it
had back; it refuses a target with no glyph, since a spinner appearing beside the words is
a size jump.

**Why.** Every busy state was a `QLabel` rewritten by hand, and only one view said anything
during its settle. The weak reference is the gc rule from `CLAUDE.md`: a long-lived
plain-Python signal holding a widget's bound method is the shape that crashes the collector.

**Upstream?** Yes. The tones are the theme's; a framework that ships `Debounced` should
ship the thing that shows it.

### `framework/debounce.py` — `pending_changed`

**What.** `Debounced.pending_changed: Signal[bool]` — True on the first trigger of a burst,
False from a `finally` after `_run` and from `cancel()`; in immediate mode both arrive
inside the one `trigger()`. (This pass and the theme-providers pass each found `flush_all`
walking a `WeakSet` in hash order on the same day; §27's deterministic settle is the one
that stayed.)

**Why.** The indicator above: the Time tab's wrapper that showed a label before `trigger()`
and hid it as the first line of the rebuild was two statements paired by hand that a test
could never see up.

**Upstream?** Yes. A framework that ships `Debounced` should say when a run is owed.

### `framework/widgets.py` — `EmptyState.stands_in_for`, `caption`, `note`, `confirm` on the frame

**What.** `EmptyState(stands_in_for=content)`: `say()` shows itself and hides the content
or the reverse. `caption(text)` and `note(text)` make the `#InspectorCaption` and
`#InspectorNote` labels. `confirm()` keeps its signature (a `verb` keyword added) and builds
a `DialogFrame` — the question as the lead, the verb quiet, Cancel the default — with the
frame imported inside the function, since the frame is built from this module's helpers.

**Why.** Five empty-state mechanisms; the two labels hand-built in twenty-two files; a
`QMessageBox.question` that printed a platform icon and arranged its buttons the platform's
way for the one moment a person must read carefully.

**Upstream?** Yes.

### `theme/tokens.py`, `theme/tones.py`, `theme/theme.qss` — tokens, status tones, and a stylesheet that names only what exists

**What.** Spacing tokens (`DIALOG_MARGIN`, `SECTION_GAP`, `FIELD_GAP`, `CAPTION_GAP`,
`PANEL_MARGIN`, `CONTROL_GAP` — out of `framework/toolbar.py`, and 12 now — `ROW_PADDING_*`,
`ROW_LINE_GAP`, `CELL_PADDING_*`, `SECONDARY_ALPHA`, `SCREEN_SHARE`) replace copies in `text_dialog.py`, `asset_picker.py`, `image_preview.py`,
`cards.py`, `list_rows.py`, `markdown_highlight.py` and `theme/cards.py`. `STATUS_TONES`
(`VALID_TINT`, `INVALID_TINT`, `BUSY_TINT`) move in from the canvas renderer. The
stylesheet loses fifty-six object names the template's Writer app set — forty per cent of
the file — the three enumerated `#X #PrimaryButton` lists (one `QPushButton#PrimaryButton`
rule, last), and the task-browser-scoped progress bar (one bare `QProgressBar` rule); it
gains the `#Table`, `#DialogBody`/`#DialogFooter` and `#UpdatingIndicator`/`#StatusLine`
rules, and a `QComboBox` on a `#ControlBar` or in a `#DialogBody` wears the quiet bordered
look with its arrow drawn as borders — styling `::drop-down` takes Fusion's arrow away, and
Qt's stylesheet has no other way to draw one without an image file. `tests/test_theme.py`
asserts every `#Name` is a literal under `src/`, and renders the combo.

**Why.** A stylesheet that describes another application is one the next reader copies
from. A float token is skipped by `as_qss_mapping` on purpose.

**Upstream?** The tokens and the guard test, yes. The template's own stylesheet should
ship with the guard and without Writer.

### `modules/debug/design_example.py` — a living example module (a recommendation)

**What.** A Debug-menu module that builds nothing real: one modal and one tab over sample
data, made from every shared primitive the framework offers — the dialog frame with a form
and a refused primary, the table with a heading, a badge and a picked row, the toolbar with
its filter and its overflow, every signalling state, the empty state — plus a script that
renders both in every theme to a committed folder of images, and a README naming what each
image shows. DESIGN.md's *Primitives* table points every rule at the image that shows it.

**Why.** A design rule that lives only in a document is followed by whoever remembers it;
one that lives in a primitive is followed by whoever uses the primitive; but a developer
still has to *see* the intended result to know whether their surface matches. The example
module is the place to look, and it is also the harness every primitive change is judged
in: the review rounds of the design-system pass — a smaller second line, the glyph on the
first line, a spinner in a button's own slot, a footer band — each started from a render
of it. Sample data keeps it honest: it can never be mistaken for a feature, and it costs
nothing to open.

**Upstream?** Yes, and early: a template that ships primitives should ship the module
that shows them together, the render script, and the rule that a change to a primitive
re-renders it. It is the cheapest design tool there is.

### `tests/conftest.py` — `themed` shared

**What.** The `themed` fixture (apply a theme application-wide, restore the default
afterwards) moves up from two test modules; a render test of a delegate needs it, since a
delegate paints from the palette and a stylesheet on the widget alone is not enough.

**Why.** Three test modules would otherwise carry the same seven lines.

**Upstream?** With the primitives' tests.

## 29. From the milestone-colours pass

### `theme/palettes.py` — colour maps, Qt-free (new)

**What.** Nine perceptually ordered colour maps (viridis, mako, rocket, …) as `Palette(id,
name, stops)`, with `palette(id)`, `shade(found, position)` and `shades(found, count)` —
`count` shades dealt evenly along a map, centred, so nothing lands on an end. Hex strings
throughout; no `QColor`, no Qt import at all. `tests/test_architecture.py`'s Qt-free probe
covers it.

**Why.** This application deals a *sequence* of related shades — one per milestone, by
place in the roadmap — and the consumers are spread across layers: the feature that owns
the sequence, the menu that lists the maps, and every painter that draws one. `theme/` is
the leaf all of them may import, and staying Qt-free is what lets a module's headless half
and the CLI reach it. The maps are the legible *interior* of each published map: the
darkest and lightest ends are dropped, because a fill that vanishes into a light or a dark
theme is no colour at all.

**Upstream?** The `shade`/`shades`/`_mix` machinery, yes — an ordered ramp sampled by
position is generic, and any application that colours a sequence wants it. The nine maps
themselves are data, and a template could ship one or two.

### `theme/tones.py` — `toned(name, color)` and `recoloured(tone, color)`

**What.** `toned` returns a body tone's `(fill, border)`, optionally recoloured to another
hue **at the tone's own alphas**; `recoloured` is that one operation on its own.
`button_tone` now goes through `toned`.

**Why.** Ten painters wanted "the milestone tone, but this milestone's hue". Without one
function each of them re-derives the alphas from the constants, and the first one to be
edited makes a card louder than its row. It is also the honest expression of the rule: a
semantic tint is a *weight* plus a hue, and only the hue is ever the caller's.

**Upstream?** Yes. Any template with a tone table gains from the recolour being one
function rather than a convention.

### `theme/icons.py` — `palette_strip_icon`, `PALETTE_STRIP`

**What.** A colour map drawn as a horizontal gradient strip, for a picker row or a menu
entry. Moved here from the feature that had it, because two surfaces now show it.

**Why.** The usual one: two surfaces drawing the same thing from two painters drift. Worth
recording only because it is the third time in this tree that a "local" painter turned out
to have a second caller — a painter beside its one widget is a reasonable place to start
and a bad place to stay.

**Upstream?** Only with the palettes.

### A note on where a "which of these" preference should live

**What we learned, not a code change.** The obvious home for *View ▸ Milestone Colours* was
a per-user preference beside the theme — the template's `user_config`/`ThemeService` shape
fits it perfectly. It was wrong, for a reason the framework cannot see: the value reaches a
*published artefact* (a committed report), so two users would churn it between them, and a
second control that already named the stored value would have been lying about what the
window painted. The rule that came out of it: **a preference that reaches something the
project commits is the project's, however much it looks like an appearance setting.** The
menu then presents the shared value rather than owning one.

**Upstream?** As a paragraph in the docs' preference guidance, not as code.
## 30. From the step-details pass (S6)

The first surface brought up to the design system after it landed — which is exactly the
job of finding out what a primitive is missing. Three of the four notes below are things
`Toolbar` needed the moment it was fed from an action registry rather than from hand-wired
slots, which DESIGN.md's *Toolbars* predicted would happen "in the design passes".

### `framework/toolbar.py` — `Toolbar(dense=True)`

**What.** A mode that keeps `CONTROL_HEIGHT` and narrows a strip's button sides and gaps to
`DENSE_GAP`. Set as a Qt *property* on the widget, so the stylesheet reaches it as
`#ControlBar[dense="true"] #ToolbarButton`; no new object name.

**Why.** A strip of *verbs* may fold gracefully into the `…` menu, because losing a verb
costs a click. The aspect bar is not a strip of verbs: it answers *what does this step
carry*, and a row that folds stops answering. Measured — the step panel cannot be narrower
than 479 px (its tab pages set that, not the bar), leaving the strip about 356; at the verb
strip's 45 px buttons that seats **five** of the ten Type toggles, and at the dense 29 px it
seats **all ten**. The alternative was the surface-named exception this replaced
(`#AspectBarTools #ToolbarButton { padding: 5px 4px }`), which is precisely what DESIGN.md
forbids: "never styling one surface by name".

**Upstream?** Yes. Any template with a state strip beside a verb strip wants the
distinction, and expressing it as a property rather than a name is what keeps the
stylesheet from growing a rule per surface.

### `framework/toolbar.py` — `add_verb(tip=…)`

**What.** An optional standing tooltip. `_retip` prefers it over the action's words.

**Why.** `_retip` is connected to `action.changed` and forces the tooltip to equal the
action's text, so a host that sets a tooltip has it reverted on the next `setText`. That is
right for a hand-wired verb — "a verb is a glyph, and its words are the tooltip" — but a
registry's `ActionSpec` carries both a label *and* a `tip`, and a host that rewords an
action to carry a refusal (*disabled, never hidden*) would lose the standing explanation
with it. The tip stands in the tooltip; the words still name the `…` menu's entry.

**Upstream?** Yes, with the note that it exists for registry-fed toolbars.

### `framework/dialog.py` — `showEvent` skips the tab-order pass with no footer

**What.** The `setTabOrder` loop runs only when `footer_buttons()` is non-empty.

**Why.** The rule it implements is "the first Tab out of the body lands on the primary".
With no footer there is nothing to land on, and the loop still walks every tab-focusable
widget in the body and re-links them in `findChildren` order. For a dialog whose body is a
whole panel — the step details dialog, the frame's own worked example of a button-less
dialog — that is about a hundred `setTabOrder` calls that make the tab order *worse* than
the one the panel built. The focus block is untouched.

**Upstream?** Yes; it is a bug in the frame, not a divergence.

### `framework/dialog.py` — no title and no lead in the body

**What.** `DialogFrame` no longer prints a heading: `title_label` and `lead_label` are gone
with the `lead` parameter, `set_title` sets the window title alone, and `confirm()` puts its
question in the body. `LinePrompt` loses its `lead` too — its caption already says what it
wants. Supersedes §28's anatomy.

**Why.** Seen on a real surface rather than on the example, the two lines read as chrome: a
title repeating the title bar, and a lead repeating what the content below already showed,
between them pushing a small dialog's content a line and a half down. A dialog is opened for
its content, and its content is what should be at the top. A confirmation's question is not
a heading over the dialog — it *is* the dialog.

**Upstream?** Yes. It is the sort of rule that only a second surface disproves, which is
what design passes are for.

### `framework/aspect_bar.py` — a `refreshed` signal, and no `visible`

**What.** Its state triple is `(enabled, checked)` rather than `(visible, enabled,
checked)`. (A `refreshed` signal was added here too, for the dialog lead that repeated the
bar's answer; the lead went in the same pass and the signal with it — noted because the
*reason* it was needed outlives it.)

**Why.** Two things a host learns only by building a second reader of the bar's answer.
(1) A host that repeats a derived control's answer cannot get it by listening to the
*model*: applying a template ends with the bar's own `refresh()`, after the last write
anybody heard, so a model listener renders one gesture behind. The derived thing must
announce. (2) `state().visible` was dead and also unhonourable: a
`Toolbar` re-shows whatever fits on every reflow, so a hidden verb would be resurrected by
the next resize. *Hidden means absent; disabled means not now* already covers the case, and
an aspect a build does not ship never reaches the registry at all.

**Upstream?** The announcement rule, as a paragraph rather than as code. The `visible`
removal is specific to a strip that owns widget visibility, and is worth saying out loud in
`Toolbar`'s docstring upstream.
## 31. From the signalling pass

### `framework/signalling.py` — one motion, two places to put it

**What.** `Spinner.attach` takes a bare `QLabel` as well as a `QAction | QAbstractButton`.
A button or verb has a glyph slot the spinner borrows and gives back; a label *is* the
slot — it shows nothing when idle, so it is fixed to `ICON_SIZE` and keeps its room while
hidden. `UpdatingIndicator` is that second case with a `Debounced` attached: it was a
`QLabel` reading *Updating…* and is now the same three-quarter arc a working button turns,
with the words in its tooltip. `Spinner` is defined above it, since the indicator is one.

**Why.** A word at the end of a control strip is the only prose on a row of glyphs, four
times the arc's width where the row is already competing for room, and the one thing there
a translation would have to reach. But the real reason is the vocabulary: *something is
running here* should be one motion to recognise, not a word in one place and a turning
glyph in another. The alternative — a second timer loop inside the indicator — would have
been about fifteen duplicated lines and two ways to turn the same arc.

**Watch.** The `#UpdatingIndicator` colour rule left `theme.qss`: a pixmap ignores `color`,
and the arc is painted from the palette at `SECONDARY_ALPHA` by `Spinner._ink()`. The
object name stays, because `tests/test_theme.py` checks that every styled name is set by a
widget, not the converse. Frames are re-inked on every `start()`, so a theme change between
runs is picked up — a theme change *mid-spin* is not, and has not been worth a hook.

**Upstream?** Yes. The union in `attach` is six lines and it is what stops a template
growing two spinners.

### `framework/tasks.py` — the duration memory survives the session

**What.** `TaskService(remember=True)` reads its `key → seconds` memory from the per-user
store at construction and writes it back on every successful finish; `duration_of(key)`
exposes it. The default is off, so a test and a throwaway service carry no history. The
cap that keeps an overrunning estimate short of full is now `ESTIMATE_CAP`, public, because
a second surface draws a remembered duration as progress.

**Why.** The memory was per build, which means per window. The estimate that matters most
is for an operation the *current* window has not run yet — in this application, the save at
quit, in a session where nobody pressed Ctrl+S — and per-build memory is empty exactly
then. Persisting it is one read and one small write per completed task.

**Watch.** A bar drawn from it must not be the only thing the bar reads. In
`modules/sync/save_progress.py` the known count leads and the estimate only fills between
landings (`max(landed, estimated)`), so a guess can never contradict a fact; with nothing
remembered the bar is the count alone. Failed, cancelled and timed-out runs already do not
poison the memory, which matters more once it outlives the session.

**Upstream?** Yes, behind the same default-off flag. A template's `TaskService` should be
able to estimate on a machine's second run without the host application inventing its own
store.

## 32. From the agent-profiles pass

### `framework/action_registry.py` — `ActionSpec.in_menus`, and `ActionRegistry.data_menu(id)`

**What.** A spec flag, default True. False keeps the spec out of the menu bar
(`menubar.py`'s `_add_spec` creates no QAction) and out of every pop-up (`action_menu.py`'s
`fill_menu` skips it), while the spec keeps its `menu`/`group`/`submenu` for validation and
for the palette's path, and stays runnable from the palette, a button or a data menu's
`append_action`. `register` refuses such a spec with a `shortcut`. And a by-id accessor for
`DataMenuSpec`s, the sibling of `spec(id)`.

**Why.** The Step menu held *Run Agent…* flat beside *Run Agent With ▸*, two entries for
one act. Folding the verb into the data child menu — the profiles, the default marked,
then *Manage Agent Profiles…* — left `agent.run` with no seat: it must stay registered
(the Agent tab's button, the progression board and the palette run it), and the registry
required a menu for every spec. The alternatives were a fake `menu` (the validator refuses
it, rightly) or `visible=False` in its state (which also takes it out of the palette and
makes `run` refuse it). The shortcut refusal is the trap the flag would otherwise set: a
QAction is what fires a shortcut, and an unseated spec has none. The accessor is for a
button elsewhere — the progression board's *Run N Agents* — that drops the same child
menu down: the root hands over `registry.data_menu(id).fill`, so the second surface
renders the menu and never a copy.

**Upstream?** Yes, both. Any template whose child menus are data will meet a verb whose
seat is that menu's entries. The `palette: bool` flag already set the shape.

## 33. From the graph-editor pass

### `framework/toolbar.py` — bands, a registry feed, a menu face, and a checked glyph's ink

**What.** Four additions to the `Toolbar` primitive, and one correction.

- `add_group(label)` opens a **band**: what follows lands in it, `DENSE_GAP` apart, under a
  name in `#ToolbarGroupLabel`, and a divider is placed before every band but the first. A
  band is one `_Group` widget and therefore one item of the reflow, so what folds into the
  `…` menu is a whole band, listed as glyph *and* words with a rule where each begins.
- `add_action(registry, context, action_id, *, menu=…)` fills a verb from the registry: the
  glyph is `ActionSpec.icon`, the words and the reason come from `action_words(spec, state)`
  (which `ActionToolbar._refresh` now shares, so there is one definition of what a button
  says), the state is restated on every context change, and `menu` gives the button the
  arrow that drops its own child menu. `dispose()` lets the context go.
- `add_menu_face(...)` is a button that is *only* a menu — no verb under it, so no split
  arrow. Folded, it becomes a child menu of the same entries.
- A **checked verb's glyph is re-inked in `$ON_ACCENT`**, which `theme/palette.py` now
  carries in `QPalette.ColorRole.BrightText` (it held `accent_hover`, which nothing read).

**Why.** DESIGN.md already said "on a real surface the verbs come from the registry —
`ActionToolbar` over registered `ActionSpec`s becomes a `Toolbar` fed by them in the design
passes". The canvas strip was the first such pass. The bands are what a drawing surface's
strip is; folding by band is what keeps the `…` menu readable.

The checked ink is the interesting one: `#ToolbarButton:checked` fills with the accent, and
a glyph painted in the secondary tone disappears into it — which is why that strip's mode
switches carried *words* for as long as they did, and why the aspect bar's ten toggles have
the same fault today. A painter has no stylesheet, so the palette is the only way it can
learn a colour the stylesheet writes.

**Watch.** Four Qt traps, all found the hard way.

1. `QToolButton.setMenu()` on a button that already has a default action **detaches the
   default action**, and the button then renders the action's text in place of a glyph it
   no longer follows. A face therefore sets its own icon and tooltip and is kept in step by
   `_ink`, rather than using `setDefaultAction`.
2. A `QToolButton` copies its default action's icon **at `setDefaultAction` time**. Ink the
   action before seating it, or a button given a null icon falls back to drawing its words.
3. `_reink()` repaints every glyph on the strip. Calling it once per added verb makes a
   nineteen-verb strip paint 361 pixmaps to build; `add_*` inks only the action it made.
4. **A dense strip's padding shorthand outranks the rules that ask for an arrow's room.**
   `#ControlBar[dense="true"] #ToolbarButton { padding: 6px 4px }` is two names and an
   attribute; `#ToolbarButton[hasMenu="true"] { padding-right: … }` is one. So a dense strip
   silently took the room back and Qt painted a 20 px subcontrol straight over a 16 px
   glyph — a clipped icon and nothing else to show for it, because a styled subcontrol
   widens no button by itself. `theme.qss` now states both dense variants, and
   `tests/test_theme.py` renders a dense strip and asserts a button that drops a menu is
   wider than a plain one by the room it was promised. The literal a *face* leaves is
   `INDICATOR_ROOM` now, so the three rules that shared it share a name too.

**Upstream?** Yes, all of it. A template with a drawing surface wants bands; a template
with an action registry wants the registry feed; and the checked-glyph ink is a bug fix
wherever a checkable glyph button exists.

### `framework/picker.py` — the fuzzy picker, with the palette rebuilt on it

**What.** `PickerDialog` over `PickerRow(id, label, detail, trailing, icon, also, landmark)`:
the field, the ranking, the `TwoLineDelegate` rows, the arrow keys and the after-close pick.
`fuzzy_score` moved here from `palette.py`, and `CommandPalette` is now the half that turns
the registry into rows.

**Why.** A second fuzzy picker (the graph's *Jump to*) would otherwise have been a
hundred-and-thirty-line near-copy of the palette, whose registry and context were wired
into its constructor. Two surfaces are what justify a primitive.

**Watch.** `also` is what a row is *searched* by beyond its name, and is deliberately not
`detail` or `trailing`: a palette row shows its shortcut at the right, and folding that
into the haystack makes "ctrl" match every verb that has one. `landmark` is what a picker
over hundreds of rows opens on; a list with no landmarks opens whole, which is what the
palette wants.

**Upstream?** Yes. The template ships the palette, and the palette is this with rows from
a registry.

### `framework/action_menu.py` — `fill_menu(..., group=…)`

**What.** A filter beside the existing `submenu` one: naming a `group` renders just that
band of a menu, child menus nested as usual.

**Why.** A toolbar face that stands for a band — the graph strip's *Options* for *Graph*'s
`look` — must render the menu rather than keep a copy of it, which is the rule every other
pop-up in the application follows.

**Watch.** The nested `child_menu` helper had a parameter also called `group`; it is
`entry_group` now, or the new filter would have been shadowed inside it.

**Upstream?** Yes, with `submenu`. It is eight lines and the same idea.

### `theme/icons.py` — every glyph painted at the screen's device pixel ratio

**What.** `_canvas()` makes its pixmap `ICON_SIZE * ratio` across, stamps that ratio on it
and scales the painter by it, so the forty-odd painters below keep writing plain 16-unit
coordinates. `key_badge_icon`, `filter_icon` and `palette_strip_icon` went through it too,
rather than making pixmaps of their own.

**Why.** A glyph painted into a 16-pixel pixmap and shown at 16 logical points on a 2x
display is upscaled by the compositor, and every stroke in it goes soft. That is most of
what "the icons look a bit blurry" turns out to mean, and it is four lines to fix.

**Watch.** **Do not scale the painter as well.** A paint device that declares a device
pixel ratio already maps logical coordinates, so `painter.scale(ratio, ratio)` applies it
twice and a 16-unit glyph lands in the top-left quarter of its own icon. That shipped, and
nothing here could show it: the offscreen platform reports a ratio of 1, so every render
and every test was correct and every glyph on the developer's 2x screen was a fragment.
`tests/test_theme.py` forces the ratio now and asserts a known glyph still spans its own
16 units — it fails on the double scale and on no scale at all.

The ratio is read from `QGuiApplication` when the glyph is painted, not when the screen
changes. Icons are repainted on a theme change, so a window dragged between a 1x and a 2x
screen keeps the ratio it was painted at until then — the same trade every
`QIcon`-from-`QPixmap` in the application already makes, and the fix if it ever matters is a
`screenChanged` hook, not a different painter.

**Upstream?** Yes. Any template that paints its own glyphs has this.

### `theme/tokens.py` — `$BORDER_FAINT` fades towards the elevated ground

**What.** `mix(theme.border, theme.bg_elevated, 0.5)` where it was `bg_base`.

**Why.** A strip of verbs sits on `$BG_ELEVATED`, and faded into the *page's* ground the
divider came out three levels from the canvas strip on the light theme — a divider that
parts nothing. Its only consumers are strip dividers (`#ToolbarDivider`,
`#ControlBar::separator`), so the change is contained and strictly an improvement on both
grounds.

**Upstream?** Yes.

### A render script must redirect QSettings

Not a framework change — a rule for `scripts/render_*.py`. `render_graph_editor.py` opens
the graph's side panel, which writes a per-user preference; the first run wrote it into the
developer's real settings, and every later run then started with the panel already open, so
the "closed" screenshot could not be taken twice. The suite's `conftest.py` already
redirects `QSettings` to a throwaway ini directory for both reasons — a render script wants
the same two lines, and to `clear()` between themes so each renders from the same state.

### `theme/icons.py` — the glyphs are a vendored SVG set

**What.** Forty-odd hand-painted `QPainter` glyphs became fifty-two Tabler SVGs (MIT) under
`theme/glyphs/`, fetched by `scripts/vendor_tabler_icons.py`, which holds the mapping from
*what a glyph means here* to the icon that says it. `paint_glyph(painter, rect, name,
colour)` is the one painter; `glyph_icon(name, colour)` wraps it in a `QIcon`. The module
went from 1,075 lines to 461, and the five `paint_*_glyph` functions and the if/elif chain
that chose between them are gone — the kind *is* the glyph's name.

**Why.** A handful of painters did not justify a resource pipeline; forty did not justify
hand-drawing. The strokes drifted between glyphs and nobody could add one that matched.
Copied in rather than depended on: 212 KB of files against a package, a version to resolve
and a release cadence — and only the ones used, because the full set is six thousand files.

**Watch.** Two things. **Qt's SVG renderer knows no `currentColor`** — substitute the ink
into the source before rendering (cache the substitution; the canvas asks for the same few
glyphs in the same few colours on every repaint). And **an SVG stroke colour carries no
alpha**, so the colour's alpha has to become the painter's opacity; a strip's glyphs are the
text colour at `SECONDARY_ALPHA`, so getting that wrong makes every toolbar read a shade
too loud.

**Upstream?** The mechanism, yes — a template that paints its own glyphs wants this loader.
The set is an application's choice, and its licence notice travels with it.
