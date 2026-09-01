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

- **`framework/action_dialog.py` — actions as a dialog of checkboxes.** The fifth presenter
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
