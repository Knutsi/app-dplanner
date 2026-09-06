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
universal, and `fill_menu` in `action_menu.py` could learn to render the same specs so a
right-click on a menu holding one cannot drift — not done here because nothing pops Tools up.

**A detail worth keeping.** The data menu's `menuAction` stays visible with an empty list, on
the *hidden means absent* rule: the menu is the capability, and the fill tells the empty
story with a disabled entry ("No agents running from this window"). Deriving its visibility
from its contents — the spec-fed child menus' rule — would make the capability flicker with
the data.


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
