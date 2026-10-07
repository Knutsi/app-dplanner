# Notes for app-framework

DPlanner was generated from [app-framework](https://github.com/Knutsi/app-framework), and
building it taught us things the framework does not know yet. This file says, **file by file,
how `framework/` and `core/` differ from the template today**, and why — so that a later pass
can carry the good ones upstream instead of rediscovering them, and so that nobody diffing
against upstream merges a divergence away by accident.

`.appframe` records the commit we forked from, so the diff stays possible:

```bash
git -C ../app-framework diff <revision> -- template/
```

**The rule: if you change anything under `framework/` or `core/`, rewrite that file's entry
here in the same commit** — or add one, in path order, if the file is new. An entry states the
divergence as it stands, never the passes that produced it: the file answers "what differs in
`framework/x.py`?", and git keeps its history. Each ends with *Upstream?* — yes, no or maybe,
and why. A trap, a missing assumption or a number worth knowing that is not a code change goes
under [*Lessons*](#lessons-no-code-change). `tests/test_rules.py` holds every heading to a file
that exists and the headings to path order.

Not listed, because only the package name differs: `framework/__init__.py`, `framework/llm.py`, `framework/llm_service.py`, `framework/module.py`, `framework/splash.py`, `framework/text_binding.py`, `framework/zoom.py`, `core/formats.py`, `core/storage/__init__.py`, `core/storage/local.py`.
The diary this file was regrouped from, in the order it was written up to 4 October 2026, is
[`docs/history/notes-for-appframe-to-2026-10-04.md`](docs/history/notes-for-appframe-to-2026-10-04.md).

Nothing here is a complaint. The template is a running application on purpose, and most of
what follows is only visible *because* it runs.

## `framework/action_menu.py`

**Changed** from the template.

The template's `build_menu` listed a menu's *runnable* actions flat. Here a pop-up is a render
of the registry under the menu bar's own policy, and it can be composed:

- `fill_menu` renders into an existing `QMenu`: a disabled entry is greyed with its state's
  label (only the palette filters on runnable), child menus nest **one per title** wherever
  the groups feeding them come from, with a rule inside where the group changes, and a
  `PATH_SEPARATOR` title nests one child inside another. `submenu=` renders one child menu
  flat, `group=` one band or several, and a `DataMenuSpec` is placed by the same sort key
  and filled on open. `build_menu` is `fill_menu` over a fresh `QMenu`.
- `append_action` is one registered verb as an entry under that same policy, for a widget
  that assembles its pop-up by hand (a toolbar button mixing data rows with verbs).
- `Band` and `fill_bands` lay several renders into one pop-up, with a rule above a band only
  when something is above it and the band drew something — the canvas composes its
  right-click per thing under the cursor, the Tests tab leads with its band and offers
  *Step* as a child.
- `menu_ink` paints an `ActionSpec.icon` in the menu's own text colour, read when the pop-up
  is built, which is why glyphs are a pop-up presenter's business and never the bar's.

Why: a right-click must offer exactly what the menu offers, never a copy, and every surface
whose subject is narrower or wider than one menu was otherwise writing entries by hand.

**Upstream?** yes — nothing in it knows DPlanner, and the template's own right-click rule needs every piece.

## `framework/action_registry.py`

**Changed** from the template.

- `ActionSpec` gains `palette` (a second placement kept out of the palette), `in_menus` (a
  verb seated somewhere else — a data menu's rows, the aspect bar, an index row — which
  still names its menu so the palette can say where it lives, and may carry no shortcut;
  `register` refuses one), and `icon`, a glyph painted in the ink the presenter hands over.
- `submenu` collapses by `(menu, title)` rather than `(menu, group, title)`: two groups
  feeding one child menu share it, ruled where the group changes. A title holding
  `PATH_SEPARATOR` (` ▸ `, moved here from the palette) nests.
- `DataMenuSpec` and `register_data_menu`/`data_menus`/`data_menu`: a child menu whose
  entries are data, cleared and refilled on every open. `MenuPlacement` is the protocol both
  spec kinds satisfy, so one table validates and sorts them.
- `run` is the one path every presenter takes, and it opens an `action` telemetry span, so a
  verb's cost includes every view's reaction to it.
- `HIDDEN` and `MenuStructure.items()` are gone: they had no callers, and the one hide site
  spells its `ActionState` out with a label.

**Upstream?** yes — data menus, nesting and the single timed `run` are general; the deletions are the template's to judge.

## `framework/activity.py`

**Changed** from the template.

Three additions on top of the `Activity` protocol and `ActivityBase`:

- `EntityActivity`: an activity that views one entity, publishes its activity scope with an
  entity edge on activation, and publishes a selection **only while current**
  (`publish_selection`). Five modules had copied that by hand; a background pane republishing
  its selection made the detail panel flicker between two tabs.
- `follow_project_tabs` and `project_tab_title`: one place that closes a project tab when
  its project leaves the library and retitles the survivors on every project's field change
  (titles are short titles unique among siblings, so renaming one project can relabel
  another's tabs). `retitles_on` adds signals for a title that says something the model does
  not hold.
- `follow_project` / `follow_target`: subscribe a view to one project's changes only, by
  asking `Library.belongs_to` about the node each signal names; `follow_target` for a surface
  whose subject moves. One unsubscribe for the lot.

This file now imports `dplanner.domain` (`Library`, `Project`, `short_titles`): the follow
helpers are written against the application's model.

**Upstream?** maybe — `EntityActivity` and the only-while-current rule yes; the follow helpers only once the template has an entity model for everyone to follow.

## `framework/aspect_bar.py`

**Added** here.

`AspectBar`: one child menu of the action table — Step ▸ Type — rendered as a dense
`Toolbar` of checkable glyphs, with a *Template* dropdown beside it whose `AspectTemplate`s
are named combinations of those toggles. Picking a template runs whichever toggles differ
inside one undo gesture; the ticked template is a comparison on every refresh, never stored,
and one template may be the catch-all. It never keeps a list of its own, so an aspect a
build does not ship has no button. The context arrives as a function, because the panel in
Step Details shows a step nobody selected.

A toggle's state never returns `visible=False`; a strip re-shows whatever fits on every
reflow, so it could not honour it. The template had no such surface because it has no
aspects.

**Upstream?** maybe — as a generic "one submenu's toggles as a bar" presenter; the template dropdown is DPlanner's.

## `framework/aspect_toggle.py`

**Added** here.

`aspect_toggle(...)` returns the one `ActionSpec` an aspect module registers for its Type
toggle: checkable, off through `domain.shelf.turn_off` and on through `turn_on`, so nothing
is lost on the way out and the CLI's `clear` builds the same command. `refusal=` greys it
with a reason. The verb is `in_menus=False`: its seat is the aspect bar, and the palette
still finds it under *Step ▸ Type*. Eleven aspects carried the same three functions before.

It imports `domain.model` and `domain.shelf`, so it is DPlanner-shaped.

**Upstream?** no — the template has no aspects or shelf; the pattern (a verb seated outside the menus, greyed with its reason) is what carries back.

## `framework/asset_gallery.py`

**Added** here.

`AssetGallery`: a grid of attached files — thumbnails for images, chips for the rest, click
to open `ImagePreviewDialog`. Promoted from a module's private strip when a second and third
surface wanted it, since modules cannot import each other. Two source modes never mixed:
`set_area` over a node's content-addressed module area (the only editable mode; attach and
remove are deliberately not undoable — an orphaned blob is recoverable, a dangling link is
not) and `set_files` over explicit paths and a byte reader, with an optional `remove=`.
Thumbnails are cached by name and rendered at the device pixel ratio.

Trap still worth stating: its attach row is added to the column **before** it is filled. A
parentless box layout given `addWidget`/`addStretch` before `addLayout` leaves item wrappers
alive on the Python side, and the boundary `gc.collect()` deleted them twice.

**Upstream?** yes — for any application with module file areas; the layout rule regardless.

## `framework/asset_picker.py`

**Added** here.

`AssetPickerDialog` over `PickerEntry`s (title, detail, byte reader): a modal on
`DialogFrame` that lets a person choose existing files and returns
`mime_files.Payload` values — bytes and a filename, never a path, because the chooser cannot
know where the caller will put the copy. `ProseEdit` attaches what it returns exactly as it
attaches a paste. It knows nothing about projects, steps or modules.

**Upstream?** yes — with `asset_gallery` and `image_preview`.

## `framework/autosave.py`

**Changed** from the template.

**A refused write keeps its marks and stops trying.** When the persister raises (usually
because another writer changed the folder), the batch goes back into `_dirty`, autosave
pauses itself and emits `failed(error)`; whoever listens settles the collision and calls
`resume()`. Dropping the marks would lose the edit and retrying every 1.5 s would turn one
problem into an endless one. The nesting `pause()` counter now serves both this and the
reload that discards a build.

Each flush is an `autosave` telemetry span, because it is disk I/O on the GUI thread.

**`saved()` flushes now and answers whether everything is on disk after it** — False while
paused or when the write was refused. An effect that may only follow a saved change (ending
an agent's claim after the window sets a stopped status, forgetting a launch intent once its
claim is written) is handed `saved` as a `Callable[[], bool]` seam.

**Upstream?** yes — the template assumes one writer, and this is the minimum a second writer needs.

## `framework/builder.py`

**Changed** from the template.

- **A source path, not a storage provider.** `with_source(path)` replaces `with_storage`;
  the repository is built over the library file and `SeedFactory` takes a `Path`.
  `with_session(SessionControl)` replaces `with_switcher`. `with_window` is gone (no caller).
- **The shell is panels.** Stage 3 builds a `PanelRegistry` and `PanelDock` and hands both
  to the window factory; the index tree (`IndexPanel` over `IndexSegmentRegistry`) is the
  framework's own panel, registered as `INDEX_PANEL_ID` on the left. The template's sidebar
  and utility panel are gone. `library_scope(source)` keys every per-user remembered fact
  by the open library.
- **New services on the bundle:** `DebounceService`, a `Clock` with the window's `DayWatch`,
  `DictationService` (providers via `with_dictation`, none by default so a headless build
  never reaches a recorder), themes from `with_theme_providers` (the built-in one alone by
  default, so a test never reads the desktop), `TaskService(remember=True)`, telemetry,
  and the registries `panels`, `index_segments`, `project_settings`, `step_details`.
- **The context is announced once per turn:** the builder routes `ContextService.announce`
  through a 0 ms `Debounced`.
- **Migration covers the shelf:** `migrate_module_data` also runs the domain's shelf format,
  then `migrate_shelved` migrates what each module shelved; the flush writes `module_text`
  too, because an absorption may move prose.
- `services.modules` holds the built modules; close hooks dispose the index, the dock and
  the tab host's application watcher.

The builder imports `dplanner.domain` (dictation, shelf) for these.

**Upstream?** maybe — the announce wiring, the debounce service and the panel shell yes; the library source and shelf migration are DPlanner's.

## `framework/cards.py`

**Changed** from the template.

Only metrics and a rule are left: `CARD_PADDING`, `STACK_SPACING`, and
`card_rule(parent, *, vertical=False)`, a 1 px rule that splits a card or, stood up, parts two
groups of controls in one row. `ToolCard` and `CardStack` are deleted; a card is a
`#ToolCard` well on a `#CardLane` (a check's Covers tab), and the box is the stylesheet's.

The deleted `CardStack.cards()` read its layout back with `itemAt`, the shape that
double-deletes `QLayoutItem` wrappers under the cyclic collector: **never read a layout
back; keep your own list**.

**Upstream?** maybe — the template still hosts its own stack; the rule against reading a layout back yes.

## `framework/context.py`

**Changed** from the template.

- **The announcement is a seam.** `current()` is true the moment `set_scope` returns, but the
  fan-out goes through `ContextService.announce`, which defaults to `announce_now` and which
  the builder routes through a 0 ms `Debounced`. A gesture that publishes several times (a
  re-selection clears first) costs one re-evaluation of every action state, toolbar, panel
  and the menu bar, over the final state. Tests run the debounce service immediate.
- `Context.selected_entity(kind)` answers "is exactly one of these in front of the user",
  distinct from `focus_entity`, so a panel that shows a step and one that steps aside for it
  share one definition.
- `changed` is a named signal (`"context.changed"`) for the journal.
- `Context.has`/`has_prefix` are deleted (no callers).

**Upstream?** yes — the seam is three lines and any large application pays for synchronous announcement.

## `framework/day_watch.py`

**Added** here.

`DayWatch` is the window's side of `core.clock.Clock`: it asks the clock to check at local
midnight (`ms_to_midnight`), re-arming each time, and again whenever the application becomes
active, because a timer pauses while the machine sleeps and a laptop opened next morning
would otherwise show yesterday. The builder hangs it on the window.

**Upstream?** yes — any application that dates anything has the same problem.

## `framework/debounce.py`

**Added** here.

`Debounced` wraps a view's rebuild: `trigger()` restarts a single-shot timer, so a burst
runs once over the latest state and nothing queues. A zero delay means "after this event-loop
turn"; `SETTLE_MS` (300 ms) means "after a quiet spell". `pending_changed` says when a run is
owed and when it happened, which `UpdatingIndicator` follows.

`DebounceService` holds every `Debounced` and carries the suite's switch: **immediate mode**
runs `trigger()` inline, so a test asserts the line after a push. Its `flush_all` runs in
registration order (a `WeakValueDictionary` keyed by count — a `WeakSet` iterates in hash
order and made a test flip between commits) and re-runs what a flush made pending, up to
`SETTLE_ROUNDS`. **A settle behind a modal waits for it**: a run owned outside the active
modal re-arms instead, and a zero delay never waits. Each run is a `refresh` span carrying
how many triggers it folded.

**Upstream?** yes — it knows no feature; the deterministic settle and modal rule are traps any application with two views meets.

## `framework/diagnostics.py`

**Added** here.

Started from `app.main` only (a test has no event loop, and pytest-qt owns the hooks):

- `StallWatchdog`: a 100 ms GUI-thread heartbeat and a daemon thread that, past `STALL_MS`
  (250 ms), samples the GUI thread's stack every `SAMPLE_MS` into a `stall` span with the
  spans open at the time; it re-arms `faulthandler.dump_traceback_later` (`DUMP_AFTER_S`) for
  a hang that holds the GIL. A modal's nested loop keeps it beating.
- `capture_failures` chains `sys.excepthook`, `threading.excepthook` and Qt's message handler
  into `failure` spans, without silencing anything.
- `open_crash_log`: `faulthandler` on `crash.log` beside the journal, for a native crash.

**Upstream?** yes — whole, with the journal it reports into.

## `framework/dialog.py`

**Added** here.

`DialogFrame` is DESIGN.md's *Dialogs* written once: a body the subclass fills
(`#DialogBody`) and a footer (`#DialogFooter`) whose slots run destructive · status · stretch ·
secondaries · primary. Enter runs the primary, Escape dismisses, the dismiss is default only
while there is no primary, and the first Tab out of the body lands on the primary
(`showEvent` skips that pass when there is no footer). It prints **no title and no lead**:
`title` names the window, and a question a confirmation asks is body content.
`set_heading` is the one exception, for a dialog that opens itself (the Setup Checklist).
The frame names its parts and leaves its own object name to the subclass, so the stylesheet
reaches every dialog through two constant names. `LinePrompt` is one captioned field and a
verb, refused while blank or invalid.

**Upstream?** yes — every application has dialogs, and the stylesheet-specificity trap it avoids is general.

## `framework/dictation.py`

**Added** here.

`DictationService` is to `domain.dictation` what `LLMService` is to the LLM registry: is
dictation ready, and "have this said", without naming an engine. Provider and recorder are
per-user preferences; `status()` is memoised between changes (a keychain round trip per ask
otherwise). The service owns the one `TaskRunner`, parented to the window, so a transcription
outlives the editor that asked; one transcription at a time, a second refused in words.
`Dictation` is the state machine — idle → recording → transcribing, or idle → listening →
finishing for a live provider — with a generation counter that drops whatever arrives after
`abandon()`.

**Upstream?** yes — the service and state machine, with `domain/dictation.py`'s provider protocol.

## `framework/dictation_verb.py`

**Added** here.

`DictationVerb` is the markdown strip's face of `Dictation`: *Dictate* on a `Toolbar` over
one `ProseEdit`, its key a `WidgetShortcut` on the editor, the verb checked while recording,
a Spinner while words are on their way, greyed with the reason when nothing can happen. A
batch transcript is one sealed insert at the caret; a live session writes at its own cursor
so the person can read on, and the whole session is **one undo step** (an open undo gesture
from first word to stop). A host that re-binds its editor calls `abandon()` first.

**Upstream?** yes — with the service.

## `framework/gc_policy.py`

**Added** here.

The cyclic collector on our terms where it meets Qt (`install_gc_policy`, from `app.py`):

- **Collect on the GUI thread only, at safe points.** Automatic collection is off;
  `GuiThreadGarbageCollector` collects from a timer slot on the interpreter's own thresholds.
  Otherwise a collection on a worker thread or mid-dispatch deletes a QObject at a random
  moment. The suite collects after each test instead (`tests/conftest.py`).
- **Never hand a Qt-owned object back to Python.** Released shiboken (all 6.x through 6.11)
  clears a cycle one wrapper at a time, and `SbkObject_tp_clear` hands a child wrapper
  ownership of a C++ object its parent still holds — a double delete (PYSIDE-2221, fixed only
  on `dev`). Python runs every finalizer before clearing (PEP 442), so each QObject wrapper's
  `__del__` calls `release_cpp_children` while the tree is intact. It cannot see a
  `QLayoutItem` constructed in Python: never build one; use `addStretch`/`addSpacing`.

`scripts/layout_item_double_delete.py` reproduces it and `tests/framework/test_gc_policy.py`
pins it.

**Upstream?** yes — both halves, the tests and the reproducer.

## `framework/image_preview.py`

**Added** here.

`ImagePreviewDialog`: one modal lightbox for any image, on `DialogFrame`. Fitted to the
screen share but **never upscaled past 1:1**, and built at the device pixel ratio
(`QPixmap.scaled` without `setDevicePixelRatio` is blurry on every HiDPI screen). Close is
the only way out, with *Copy Path* and *Open Externally* beside it.

**Upstream?** yes — verbatim.

## `framework/index_panel.py`

**Added** here.

Replaces the template's sidebar of pages with **one tree**: `IndexPanel` over an
`IndexSegmentRegistry`, where each module's `IndexSegment` owns one folder and everything
under it through an `IndexSegmentView` (selection nodes, click, activation, its own context
menu built with `build_menu` — the spec names no menu, since menu names are application
vocabulary). `SurfaceSegment` is a folder that is one row and a way in. The panel owns what
a shared tree needs: selection published once across segments, a folder's own row reaching
its segment, and expansion and selection remembered by key (`expansion_of`/
`restore_expansion`, `selection_of`/`restore_selection`) and written to the per-user store
under the library's scope — so a changed library restores to less, never to wrong.

**Upstream?** yes — the template's index has the same folder rows that are really buttons.

## `framework/inspector.py`

**Changed** from the template.

- `InspectorExtension.tab_visible()`/`tab_visibility_changed` are gone: nine implementations
  all returned True and nothing emitted. Visibility is `InspectorSection.shown_for(target)`,
  asked on every target change and on model changes to the shown target, so a toggled-off
  aspect's tab disappears.
- `InspectorSection` gains `stretch` (how much leftover height a stacking host gives it) and
  `hint` (a standing convention shown behind an info glyph beside the caption, DESIGN.md's
  *Words*).
- `FocusableExtension`, an optional protocol (`focus_entity(kind, id) -> bool`) for a section
  that can put one of its own things in front — a test, a passage.
- The registry is instantiated per host (panel tabs, project settings, step Details blocks);
  a host is addressed by which registry you register into, never by a mode field.

**Upstream?** yes — the slimmer protocol and `FocusableExtension`; `hint`/`stretch` with the hosts that read them.

## `framework/key_dialog.py`

**Added** here.

`ApiKeyDialog`: adding a service's API key as one guided modal — where the key is made and a
button to that page, the field, *Test* on a task runner with the service's own probe, and
*Save* refused with its reason until the test passed; the key reaches the keychain only then,
and a machine whose keychain cannot keep it is told so up front. The words, address, probe
and save are the provider module's, handed in.

**Upstream?** yes — beside `dialog.py`.

## `framework/list_rows.py`

**Added** here.

`TwoLineDelegate`: a `QListWidget` row of a name and a quieter, smaller second line
(`DETAIL_ROLE`), the icon on the first line, Qt's focus frame stripped. Further roles say what
a row is: `EMPHASIS_ROLE` and `RULE_ROLE` (a pinned header row), `TRAILING_ROLE` (a note at the
right), `MUTED_ROLE`, `TINT_ROLE`, `HEADING_ROLE`, `INK_ROLE`, `VALUE_ROLE`, the grouping roles,
and `FINISHED_ROLE` (a finished row drawn in italic). `HOST_ROLE` is where a view's own item
roles start. `MENU_GLYPH` is the row-menu mark shared with `table.py`. `RichList` is the list
those rows live in — the table's well and picked row, so a list and a table read as one family
(DESIGN.md's *Lists of rich items*).

**Upstream?** yes — any side panel listing named things wants it.

## `framework/main_window.py`

**Changed** from the template.

- **No panel slot of its own.** The window takes a `PanelDock` and puts it in a column with a
  `NoticeBar` **below** it: a standing notice is a band at the foot of the content, so one
  coming or going moves only the bottom edge. The `PanelHost` methods
  (`set_panel_visible`, `set_area_collapsed`, `area_of`, …) and the `NoticeHost` pair delegate
  to them. The template's sidebar splitter and its width keys are gone.
- **Immersive mode is deleted** (`enter_immersive`/`leave_immersive`, the Escape shortcut):
  reachable from nothing.
- **Geometry** is restored from and saved to the per-user store (`window/geometry`).
- The window holds `day_watch` beside `dynamic_menubar`.

**Upstream?** yes — geometry and the notice bar's placement; the panel dock goes with `panels.py`.

## `framework/markdown_highlight.py`

**Added** here.

`MarkdownHighlighter`: markdown structure made visible while the source stays plain text. A
rich-text editor would break `TextBinding`'s positional splices, so a highlighter is the middle
way. Calm by design — bold headings, markers in the secondary ink, emphasis slanted, inline and
fenced code monospace — with colours read from the palette at highlight time, so a theme change
only needs `rehighlight`.

**Upstream?** yes — for any application whose prose is markdown.

## `framework/markdown_toolbar.py`

**Added** here.

`MarkdownToolbar`: the marks as verbs over a `ProseEdit`. **Each verb is one `Splice`**
(start, end, replacement, where the selection lands) applied in one `insertText`, because Qt
reports one `contentsChange` per edit block and two operations in one block would push an
`EditTextCommand` carrying the whole document. A verb leaves selected what a second press would
act on. The strip never takes focus and its keys are `WidgetShortcut`s on the editor, never
`QAction` shortcuts. It is dense rather than banded so twelve verbs fit the 360 px dock. A
`dictation=` argument seats the microphone.

**Upstream?** yes — the transforms are pure and worth having as functions.

## `framework/markdown_view.py`

**Added** here.

`MarkdownView`: a read-only markdown well whose images resolve **through the store, never the
filesystem** — it is handed `ModuleFileArea`s and asks each in turn, first hit wins (exact,
because assets are content-addressed), so a document renders against a folder, a git checkout
or a GitHub clone alike. Colours come from the palette only.

**Upstream?** maybe — with module file areas, if the template adopts them.

## `framework/menubar.py`

**Changed** from the template.

- Every triggered entry runs through `ActionRegistry.run` (one gate, one timed span).
- **A child menu is a container like a menu**: one per `(menu, path)` whatever group feeds
  it, with its own hidden group separators; a `PATH_SEPARATOR` path nests, and visibility is
  computed deepest child first.
- **Data child menus** (`DataMenuSpec`) are the one exception to create-once-and-mutate: cleared
  and refilled on every open, their menu entry visible even when empty. `data_menu(id)` lets a
  test ask what one offers.
- `marked_titles` deals each top-level title the first letter no earlier menu took, so two
  menus never share a mnemonic and Alt+letter opens one.
- A spec with `in_menus=False` is not added to the bar.

**Upstream?** yes — nesting, data menus and the mnemonic fix are all general.

## `framework/mime_files.py`

**Added** here.

The one reading of a `QMimeData` that both file-accepting editors share — local files first,
clipboard pixels second. `carries_files` answers "would you take this?" on every drag-move
without reading a byte; `payloads` reads once, on the drop, into `Payload` (bytes and a name).
`IMAGE_SUFFIXES`/`IMAGE_FILTER` are the application's one answer to "what is an image", for a
drop and a file dialog alike.

**Upstream?** yes — with the asset widgets.

## `framework/module_data_section.py`

**Added** here.

`ModuleDataSection`: the structured twin of `prose_section.py`. It owns the
`module_data_changed` subscription and teardown, reload on every target change with commits
suppressed, the no-op-when-unchanged `SetModuleDataCommand` through the undo stack, and the echo
rule — **ignore the echo of your own write only while one of your fields is being edited**, so
an undo made with the panel focused still reaches the widgets. A subclass implements
`load_step` and `entry` and calls `commit`. Four editors had hand-rolled this and one had
drifted. It imports `domain.commands` and `domain.model`.

**Upstream?** yes — next to `prose_section.py`, for any application with namespaced module data.

## `framework/motion/`

**Added** here.

A small motion library: `curves.py` (easings, a tween, a spring, a breeze, a Bézier) and
`particles.py` are plain arithmetic with no Qt, so a model that moves is tested without a
window; `clock.py` is the one Qt driver, riding Qt's own animation driver (about sixty ticks a
second) and running only while the widget it `follow()`s is shown, handing each listener the
seconds since the last tick; `draw.py` paints glows, tapered strokes and whole particle systems
as one gradient or one path each, with colours handed in. Home's garden is the first user; the
canvas is the one it was shaped for.

The template has no surface that moves. A hand-rolled `QTimer` at a typed interval keeps
ticking in a background tab, which is the cost this removes.

**Upstream?** yes — the clock and the Qt-free half name nothing of DPlanner; `draw.py` only if
the template wants a painted surface.

## `framework/notices.py`

**Added** here.

`Notice` and `NoticeBar`: a standing fact about the whole window — *an agent is editing this
plan*, *these entries changed here and outside* — as a band across the foot of the content,
one row per notice, keyed by its owner, gone while nothing stands. A row is a `StatusLine` in
one of the tones, the `Spinner` when the notice is about something running, and one quiet
verb; the row itself is washed in its tone, and doubles as the meter. `Notice.open` /
`open_tip` let a notice open what it sums up. Modules reach it through `NoticeHost` in
`window.py`.

The template has only the status bar, which says what a gesture *came to* and then goes; a
fact that is true until it stops being true had nowhere to stand. The bar sits below the
`PanelDock` rather than above the tabs, so a band that comes or goes moves only the content's
bottom edge.

**Upstream?** yes — application-neutral, made of `signalling.py`'s vocabulary.

## `framework/palette.py`

**Changed** from the template.

`CommandPalette` is a `PickerDialog` (`framework/picker.py`) fed rows built from the registry:
the field, the fuzzy ranking, the keyboard and the run-after-close live in the picker, and this
file is only the half that knows what a verb is. Each row is the two-line row — the label, the
verb's menu path (`menu_path(spec)`: `Graph ▸ Divide`, the group left out because no menu shows
it), the shortcut at the right and the verb's glyph — and the path is searchable through the
row's `also`, though a label match always ranks first. A verb with `ActionSpec.palette` False
is left out, so a verb listed in two menus appears once. The label comes from
`toolbar.action_words`, the same words a strip shows.

The template's palette was a `QDialog` with its own `fuzzy_score` and a one-line list, which
made *Vertical* and *Horizontal* riddles once two menus had them.

**Upstream?** yes — nothing in it is DPlanner's vocabulary, and it needs `picker.py` with it.

## `framework/panels.py`

**Added** here.

`PanelSpec`, `PanelRegistry` and `PanelDock`: a surface anchored beside the tabs in the
window's `LEFT`, `RIGHT` or `BOTTOM` area. A module registers a spec naming a default area; the
dock builds it once, the user moves it from its header's right-click menu, hides it from
*View ▸ Panels*, and collapses a whole side at once — all remembered. A panel that should
appear only sometimes implements `ContextPanel.show_context(context) -> bool`; the dock calls
it on every context change and takes the panel off screen on False, so there is one context
subscription and no panel listens on its own.

The template had one sidebar slot and a panel built inside an activity, which duplicates the
moment the window is split. "Off screen" and "showing nothing" are different states, and a
`ContextPanel` brought upstream should keep them apart.

**Upstream?** yes — with `PanelHost` in `window.py` and the View menu that drives it.

## `framework/picker.py`

**Added** here.

`PickerDialog` over a list of `PickerRow`s: a field, fuzzy ranking, two-line rows and the
keyboard, with the pick reported after the dialog closes so a verb that opens a dialog of its
own is not nested in this one's modality. A label match always outranks a match through
`also` (the menu path for a verb, the key for a step).

Two surfaces wanted it — the command palette and the canvas's *Jump to* — and differed only in
where their rows came from. A third picker is a list of rows, not a third dialog.

**Upstream?** yes — the template ships the palette, and the palette is this.

## `framework/popover.py`

**Added** here.

`Popover`, a `Qt.Popup` frame a strip control drops, and `PopoverButton`, whose face says what
is set. It closes on an outside click or Escape like a menu, but the controls in it keep their
keys and state — a slider gets its arrows, a pressed button stays pressed. A `QMenu` owns the
keyboard while open and closes at the first click, which is why a menu could not hold these.

**Upstream?** yes — names nothing of DPlanner.

## `framework/project_list_segment.py`

**Added** here.

An index folder of projects, one row per project opening that project's surface, extracted at
its third user (the Docs folder). It rebuilds on the model's and the theme's signals, restores
which rows were open, and answers the index panel's hooks so a project row stands for its
project and every Project verb works from the folder. A folder may add a `LeadingRow` above the
projects and `ChildRow`s under each. The menu name arrives as an argument, because `"Project"`
is application vocabulary. The richer `modules/projects/index.py` is deliberately not folded
in.

**Upstream?** maybe — only with the index panel and an entity kind every folder follows.

## `framework/prose_edit.py`

**Added** here.

`ProseEdit`, the editor for markdown kept as plain text. A file pasted or dropped into it is
attached through a handed-in `Attach` callable and a markdown link to it is typed at the caret,
so the link is an ordinary edit through `TextBinding` and the undo stack, while the file write
deliberately stays off the stack: undoing a paste must never leave prose pointing at a file
that is gone. `set_pick` adds *Insert Image…* (an existing file, through the asset picker) to
the standard context menu; `insert_at_caret` is how dictation lands its words.

The template edits prose through `TextBinding` alone and has no notion of attached files.

**Upstream?** yes — with `asset_picker.py`, `asset_gallery.py` and the module file area.

## `framework/prose_section.py`

**Added** here.

`ProseSection(field_for, undo, placeholder)`: a detail-panel section over one prose document
that re-binds its `TextBinding` when the panel shows another target and closes it when the
panel shows nothing — the quiet half that, done wrong, reaches a deleted node on the next
keystroke or leaves the old binding listening. Every prose editor wears the markdown strip
(`markdown_toolbar.py`); `attach_title` grows an `AssetGallery` under the editor wired to its
paste and drop; `margin`, `set_picker` and `dictation=` cover the hosts that need them.

**Upstream?** yes — the `close()`-before-rebind discipline regardless of the rest.

## `framework/recording.py`

**Added** here.

The microphone, read through a peer process: a recorder command (a row of
`domain.dictation.RECORDERS` or one the user typed) streams raw signed 16-bit mono samples to
stdout, and one long-lived `QProcess` on the GUI thread reads the pipe — no worker thread, no
lock. Raw samples have no trailer, so whatever reached the pipe before the recorder died is the
clip (`core/wav.py` puts the header on). Stopping is one sequence everywhere: `q` on stdin, then
`terminate()`, then `kill()` after a grace — on Windows only the last reaches a console
process. The process is parented and restarted per clip, because a `QProcess` dropped mid-run
kills its child from a destructor.

PySide6-Essentials ships no QtMultimedia, and the Addons package is refused for its weight.

**Upstream?** yes — as a framework primitive for any application that wants a microphone
without QtMultimedia.

## `framework/row_well.py`

**Added** here.

`RowWell` and `WellRow`: a framed, scrolling well of widget rows, each with its own buttons,
status line, bar and copyable line — the task centre and the Agents browser. `reconcile` builds
only rows that are new and drops only those gone, because a roster that ticks four times a
second must not rebuild a pressed Cancel or a half-made selection. A well asked to adjust to its
contents does, rather than holding the template-style height cap. Parts are named
(`#RowWell`, `#WellRow`, `#WellRowDismiss`) and styled in the stylesheet.

**Upstream?** yes — any application with a task centre has this roster.

## `framework/segmented.py`

**Added** here.

`Segmented`: exclusive choices drawn as one joined control — the quiet button's look, the
picked one in the accent, shared hairlines — carrying values rather than indices. A combo box
hides the choices and a row of toggles reads as that many verbs. The stylesheet keeps a
segmented group's words in a banded strip.

**Upstream?** yes — names nothing of DPlanner.

## `framework/services.py`

**Changed** from the template.

The `AppServices` bundle differs field by field:

- **Gone:** `storage` (a repository is built over a source path, not a provider),
  `sidebar_panels`/`utility_tools` (no sidebar), `detail_cards`, `exports` (no exporter ever
  registered).
- **Added:** `source_scope` (the key under which `user_config` keeps per-library state),
  `debounce` (every coalesced refresh, so a test can settle them and a discarded build drop
  them), `index_segments`, `panels`, `project_settings` and `step_details` (two more hosts of
  the `InspectorSection` contract — the Project dialog's tabs and the step's Details blocks),
  `clock`, `dictation`, `telemetry`, and `modules`, the constructed feature modules in
  registration order so a test can reach any of them.
- `switcher` is a `SessionControl` (refresh/reload), not a `WorkspaceSwitcher`.

Modules never see this bundle; `test_architecture.py` enforces it, which is what keeps
`modules` from becoming a way for modules to find each other.

**Upstream?** maybe — each field travels with the service it names; `modules` probably.

## `framework/session.py`

**Changed** from the template.

- **No switching.** `switch_to`, switch guards, `pre_open`, the recent-workspaces and roots
  memory in `QSettings` and `StorageLocation` are gone: a different library is a new process
  (*File ▸ Open Project Library* spawns one). The session opens one `library_path` and
  replaces its own build.
- **`refresh()` before `reload()`.** `SessionControl.refresh` asks a `WatchableRepository` to
  `adopt_outside_changes()` into the document every view already holds — window, tabs,
  selection and undo history stay — and rebuilds only when the adoption says it must.
  `forget_history` clears undo after a branch switch or pull. A replacement window stands where
  the old one stood.
- **`discard_build(window, services)`**, shared by a reload and a test: clears the close guards
  (a reload is not a quit and must not block on a quit-time modal), closes, `deleteLater()`s
  the window, stops autosave and cancels pending debounces. **A closed `QWidget` is still
  alive** in `topLevelWidgets()`, keeping its whole build reachable for every later
  `gc.collect()`; the copy that left out `deleteLater` cost the suite most of its running time.
- Open and reload are telemetry spans; `describe_open_error` takes a path; theme and dictation
  providers are handed through to the builder.

The session imports `domain.store.Adoption`, `domain.dictation` and `theme.providers`, so it is
no longer domain-blind.

**Upstream?** yes — `refresh()` and `discard_build` are what any two-writer application needs;
dropping switching is our call.

## `framework/settings_registry.py`

**Changed** from the template.

`SettingsScope`, `SettingsSection.scope` and `.order` are gone: every section was `GLOBAL`, the
dialog's project tab was always empty, and `order` was never read, so the dialog is one tree.
Everything registered is per user and per machine. `settings_page(parent)` builds a page with
no outer margin and `SECTION_GAP` between blocks — the dialog owns the margins and the
scrolling, and pages stack `widgets.block`s, a caption over each field.

**Upstream?** yes — `settings_page` with the dialog; the scope removal only if the template has
no project-scoped section either.

## `framework/side_panel.py`

**Added** here.

A panel a *tab* hosts beside its main surface — one per tab, fed a context the tab constructs,
gone with the tab — as against a dock panel that follows the window. The host is handed a
`SidePanel(title, icon, build)` by the composition root and never learns whose it is;
`HostedSidePanel` is the frame, the strip button that opens it and the splitter written once.
`ReadingPanel` lets the panel publish one short reading (a count) that the button shows beside
its glyph, read from the panel's last settled rebuild. The Problems list beside the canvas and
the Test panel beside a roster are the hosts.

**Upstream?** yes — nearly verbatim; it names nothing of the planner.

## `framework/signalling.py`

**Added** here.

DESIGN.md's *Signalling* as widgets: `Spinner`, the one turning arc in the application, used
in a working button's glyph slot and as `UpdatingIndicator` at the right end of a strip while a
coalesced view owes a rebuild (it `follow()`s the view's `Debounced`, and settles on a rebuild
that raised as on one that returned); `StatusLine`, a tone glyph beside secondary words, for
where a piece of work stands. Five tones — busy, ok, warn, error, info — with *warn* for
"somebody else is at it", never red. `TICKED`/`UNTICKED` are the shared check glyphs. The
indicator keeps its room while hidden so a strip does not reflow on every settle, and carries
no words.

**Upstream?** yes — a framework that ships `Debounced` should ship the thing that shows it.

## `framework/slider_row.py`

**Added** here.

`SliderRow`: a slider with a glyph button either side that steps once and greys at its end,
reporting every move — dragged, stepped or keyed — through one signal as it happens. A bare
`QSlider` is hard to land on one step of many, and its arrows need focus.

**Upstream?** yes — names nothing of DPlanner.

## `framework/step_selection.py`

**Added** here.

`focused_step` (the selection, else what the activity is about), `chosen_steps` (the same rule
for a verb that acts on several) and `focused_project` (the context's project, else the focused
step's own): which step a verb acts on, answered in one place so Delete, Cut, Copy, Duplicate,
Isolate and Run Agent cannot disagree about what "this step" means.

**Upstream?** maybe — as `focused_entity(context, kind, exists)` and friends; this file knows
steps.

## `framework/step_table.py`

**Added** here.

`StepTable`, a `Table` of steps in order — index, title and glyph, then the host's columns —
narrowable to the steps or the features without renumbering, with the done mark and italic
title on a finished step. The Order tab and the Expenditure tab both host it, and neither
package may import the other's widgets.

**Upstream?** no — it knows steps, milestones and the kind vocabulary. The lesson is the
placement: a widget two features host lives below both.

## `framework/table.py`

**Added** here.

`Table`, `Column`, `Cell` and `TableDelegate`: DESIGN.md's *Tables* applied once —
left-aligned headers over one hairline, no grid, whole-row selection, row height from the font
on the vertical header, hover wash, a 2 px accent edge on a picked row, reserved glyph slots,
right-aligned numbers, a secondary line, group headings that fold and are remembered by key, a
check column (`check_under`, `toggle_row`), a menu column, chips, one editable column through
`NumberEditor`/`TextEditor`/`DateEditor`, and `Cell.finished` drawn in italic. Two traps it
encodes:

- **A cell is measured in the weight and width it is drawn in.** `font_for` and `elided` serve
  both `paint` and `sizeHint`, and `sizeHint` uses `boundingRect` rather than
  `horizontalAdvance`, because a glyph's right bearing can push `elidedText` a pixel past its
  advance — `"10"` came back as `"…"` in a column sized to contents.
- **A `Table` built under a page already on screen keeps an unpadded header** (18 px instead of
  31); one built parentless and placed with `replaceWidget` comes up styled. Cause in Qt's
  stylesheet style not found.

**Upstream?** yes — nothing in it knows DPlanner.

## `framework/tabs.py`

**Changed** from the template.

`TabHost` holds up to `MAX_GROUPS` (3) tab groups in a splitter while its public API means what
it always meant — `open` may focus a tab in another group, `activities()` is everything,
`current_activity()` is the active group's. A group becomes active only by a deliberate act
(open, close, move, touching a pane), never by a background `currentChanged`.
`_ActiveGroupWatcher` answers "which pane did the user last touch" with **both**
`focusChanged` and an application-level `MouseButtonPress` filter — focus misses a click on
something that takes none — installed only while the window is split. `_paint_active` dims the
other panes' tab titles and draws an accent edge on the active pane, and re-tints on
`PaletteChange` because a copied colour goes stale.

Also added: `close_activity(activity)` (a deleted subject takes its tab with it), preview tabs
(`open(..., preview=True)`, italic title, replaced by the next preview), `move_current_left/
right`, `reorder_current`, `after_current`, `tab_title`, `tabs_changed`, `tab_menu_requested`,
`dispose`. Immersive mode's `set_tab_bar_visible` is gone.

**Upstream?** yes — the API held still across the split, which is the property worth keeping.

## `framework/task_runner.py`

**Changed** from the template.

**The worker thread never holds the last reference to a Qt object.** PySide deletes a
Python-owned `QObject` when its last reference goes, on whatever thread; a worker still holding
the runner after queueing its completion could delete it while the GUI thread delivers that
event — a segfault in `QCoreApplication::notify`, later, elsewhere. The worker keeps only the
signal instance and a `_Handoff` (runner, body, task), which the GUI thread empties on the next
event-loop turn after delivery. A completion emitted after the runner's C++ side is gone is
logged and dropped.

`current_task`, `abandon` and `detail_factory` are gone (no callers).

**Upstream?** yes — whole; the template's runner is the same file with the same hazard.

## `framework/tasks.py`

**Changed** from the template.

`TaskService(remember=True)` keeps the per-key duration memory across sessions in
`user_config`, so the first save at quit in a fresh session still gets an estimate; off by
default so a test is hermetic. Every finished task is journaled to telemetry (duration, error,
timed out, cancelled). `ESTIMATE_CAP` is public, shared with the save-progress dialog.
`detail_factory` is gone, and a task row is a bar or a busy line.

**Upstream?** yes — behind the same default-off flag.

## `framework/text_dialog.py`

**Added** here.

`ExpandedTextDialog`: expanding an editor is a second view, never a copy, so closing loses
nothing. `over_field` opens the same model field with its own `TextBinding` — the inline editor
stays live because each binding sees the other's commands as foreign changes. `over_document`
shows the *same* `QTextDocument` for an editor whose buffer is the authority (the Specs tab's
session), so the two views are one document with one undo history. It sits on the dialog frame
and takes `dictation=`.

**Upstream?** yes — beside `text_binding.py`.

## `framework/theme_service.py`

**Changed** from the template.

The service chooses among themes that `ThemeProvider`s offer (built-in, Omarchy, the system),
persisted under `appearance/theme` as `"system"` or `"<provider>/<name>"`; absence means
system. Following the desktop is a `QTimer` poll at the workspace watcher's cadence that
re-reads the serving provider and applies on a difference (never `is` — a provider rebuilds its
`Theme` on every read); a file watch dies with the directory Omarchy replaces and Qt's
`colorSchemeChanged` hears the application's own override. A choice naming nothing on this
machine resolves to the default for the run and is never written back. Availability is asked
once per build, and `effective_choice` is a field, so a check mark costs a comparison.

**Upstream?** yes — with the provider contract; a template shipping many themes in one menu
wants it.

## `framework/toolbar.py`

**Changed** from the template.

`Toolbar` is the strip of verbs: glyphs with their words in tooltips (`_retip` composes the
words, key and standing explanation), folding into a `…` menu, cut into named bands with
hairline dividers, fed by the host (`add_verb`, with `tip=` and `keys=`) or the registry
(`add_action`, with an optional worded `face`), a band able to end in a menu face, a host's own
widgets through `add_widget`/`set_shown`, and `dense` for a state strip. It re-folds on a
`LayoutRequest`, not only on resize, because a control that grows never resizes the strip.
`FilterButton` is `[funnel] Filter` with a clear button, its face saying what is chosen.
`action_words` is shared with the palette.

`ActionToolbar`, the template's presenter, stays — it now really disposes, and a button may drop
its verb's submenu through `fill_menu` — but only the Order and Expenditure tabs still wear it;
nothing new is written on it.

Qt fact behind the QSS: a styled `QToolButton` in `InstantPopup` loses the room for its menu
arrow, so the stylesheet places the indicator and pads for it.

**Upstream?** yes — `ActionToolbar` becomes `Toolbar` fed by the registry.

## `framework/undo.py`

**Changed** from the template.

- **`gesture(label)`**, and `begin_gesture`/`end_gesture` for one that outlives a call (a live
  dictation): every push inside lands as **one** step, each command applied as pushed; no undo
  or redo while one is open. `_Gesture` replays all or nothing — if one command refuses, those
  replayed are reversed before the refusal reaches the stack.
- **A refused entry is dropped.** `undo`/`redo` catch `KeyError`/`ValueError` from a command —
  a step another writer removed, prose moved by an adopted edit, a value changed since — and
  drop that entry and everything after it.
- **`clear()`** forgets history after a branch switch or pull.
- Every push, undo and redo is a telemetry `command` span; typing never passes an action, so
  this is where a keystroke's cost is read.

**Upstream?** yes — wholesale; it holds no application.

## `framework/user_config.py`

**Changed** from the template.

Two scopes. `get_global`/`set_global(owner, key, …)` is a preference that follows the user into
every library; `get_scoped`/`set_scoped(scope, owner, key, …)` is where the user left off in
one library, under `library_scope(path)` — a digest, because a path as a QSettings key would
fan out into empty groups. An empty scope reads and writes nothing, which is what a test's build
gets. Neither reaches the workspace.

**Upstream?** yes — the scoped store is template-level.

## `framework/widgets.py`

**Changed** from the template.

The shared helpers grew to DESIGN.md's vocabulary: `confirm` and `notice` on the dialog frame,
`caption` and `note` (`one_line=True` builds an `ElidedLabel`), `captioned` with a hint glyph
that re-inks on a theme change, `block`, `quiet`, `well`, `GlyphButton`, `ink_of`,
`EmptyState` (with `stands_in_for`), `NumberBox` (prints "0.25", not "0.25000"),
`StatusBarButton`, and the text-well helpers `make_text_well`/`space_lines`. The template's
`stored_inspector_width`/`remember_inspector_width` are gone with the inspector splitter.

**Upstream?** yes — each is the template's DESIGN.md as code.

## `framework/window.py`

**Changed** from the template.

The window's capability protocols changed with the shell: `SidebarHost` and `ImmersiveHost` are
gone (no sidebar, no immersive mode — the latter had no caller); `NoticeHost`
(`show_notice`/`clear_notice`) and `PanelHost` (per-panel visibility, whole-area collapse,
`area_of`, with `panels_changed` and `areas_changed`) are added.

**Upstream?** yes — with `notices.py` and `panels.py`.

## `framework/window_watch.py`

**Added** here.

`WorkspaceWatcher` asks the repository, on a timer, whether the workspace changed underneath
the window, and `WatchableRepository.adopt_outside_changes` is how the change is taken in — so
the poll is also the debounce. It asks the repository rather than the filesystem because the
repository knows what it last read and wrote, and the store checks the same thing before it
writes. It takes a parent, because a watcher that outlives its window polls for nobody.

**Upstream?** maybe — only with the repository half of the two-writers contract.

## `core/__init__.py`

**Changed** from the template.

The package re-exports nothing (`Signal` is no longer re-exported); import from the defining
module. Every consumer already did.

**Upstream?** yes — one import path per name.

## `core/anchors.py`

**Added** here.

Re-anchors a quoted spec passage on every read — exact (case and whitespace folded, mapped back
to raw offsets), fuzzy (a passage at least `DRIFT_RATIO` similar), or nothing — because a stored
offset goes stale on every keystroke and on every `dplanner spec import`. `locate_many` and a
`fold` parameter serve the finders from one body.

**Upstream?** no — the anchoring is this application's.

## `core/clock.py`

**Added** here.

`Clock`: today, handed in. `today()` is the machine's day or a pinned one; `pin` fixes it for a
test or the simulator; `day_changed` fires when it moves, which the window checks at local
midnight and on reactivation (`framework/day_watch.py`). Qt-free, so the CLI holds one too.
`AppServices.clock` carries the window's.

**Upstream?** yes — any application that dates anything has the same three problems.

## `core/config_dir.py`

**Added** here.

The Qt-free per-user configuration directory, for what the CLI must also read — QSettings is out
of reach for a surface that loads no graphics stack. The project library file is the first
resident.

**Upstream?** yes — small, and needed the first time a headless surface reads a preference.

## `core/fsio.py`

**Changed** from the template.

`write_atomic` writes through a `mkstemp` temporary unique to the call (two processes write one
path, and a shared `.<name>.tmp` let one writer rename the other's half-written file), keeps the
target's mode, unlinks the temporary on failure, and writes LF on every platform — the format is
LF, and `write_text` translating to `os.linesep` turned a Windows save into a whole-file diff.
`write_csv` writes `utf-8-sig`, the BOM being what makes Excel read Unicode. `write_json_atomic`
and `read_json` are gone (no callers).

**Upstream?** yes — the template's `write_atomic` has the same shared temporary.

## `core/markdown.py`

**Added** here.

A standard-library renderer of DPlanner's markdown subset to safe HTML for the report: every
piece of user text escaped, a link only for `http:`, `https:` and `mailto:`, images through a
callback, deterministic, never raising. The window renders the same text through Qt; the CLI
may not load Qt or a markdown library.

**Upstream?** yes — any template whose headless surface publishes prose.

## `core/module_data.py`

**Changed** from the template.

`ModuleDataFormat.absorb`: data that changes *owner* (a step's prose becoming a record on its
project) runs once per open, after every per-entry migration, over the repository and the loaded
document, returning the owners it changed; it must be idempotent. `migrate_module_data` takes the
document for it. `migrated` is public.

**Upstream?** yes — the shape (per-entry chain, takeover, absorption) is general.

## `core/png.py`

**Added** here.

An RGB buffer as PNG bytes with the standard library, deterministic (fixed zlib level, no
ancillary chunks) so content addressing sees an unchanged re-render. One caller: the spec module
rendering PDF pages from the CLI.

**Upstream?** maybe — the day the template has a headless image producer.

## `core/process.py`

**Added** here.

`spawn_detached()` and `detached_flags()`: start a process the user owns — an agent's terminal,
a second window — so that closing the application never takes it down; `start_new_session` on
POSIX, creation flags on Windows. One place, where there had been several.

`ProcessStamp`, `stamp_of()`, `is_live()` and `process_alive()`: whether a recorded process is
*still that process* — its pid, the machine's boot id and the process's start time, all three
matching — because a pid alone is reused and a record kept across a reboot would read a
stranger as its own process running. `process_alive` (pid only) moved here from
`step_agent_run/runs.py` so there is one per-platform probe.

**Upstream?** yes — any desktop application that opens a second window of itself; the stamp
for any application that records a process it must find again after a restart.

## `core/repository.py`

**Changed** from the template.

A repository is constructed from a *source path* (`RepositoryFactory = Callable[[Path], …]`)
rather than a `StorageProvider`, because it may span several providers — DPlanner's opens one
per project — and the `storage` attribute is gone. `FileArea` and `Repository.files(owner_id,
module_id)` give an absorption the files a module keeps beside an owner.

**Upstream?** yes — a provider per repository is the template's assumption, not a necessity.

## `core/secrets.py`

**Added** here.

The OS credential store through `keyring`: `get_secret`, `set_secret`, `delete_secret` and
`backend_problem()`, which a surface asks before storing so it can refuse with the remedy; a
plaintext backend (`keyrings.alt`) counts as a problem, never a fallback. Every call degrades to
"no secret stored" rather than raising. It is the template's `framework/secrets_store.py`, moved
because the CLI and Qt-free module files must ask it; `APP_ID` stays the service name, so
nothing stored is orphaned. `delete_secret` is kept: a store you can write and never clear is a
trap.

**Upstream?** yes — a per-user fact the headless surface must read belongs in `core/`.

## `core/signals.py`

**Changed** from the template.

`Signal(name)` carries a name for the journal, and `emit` times every slot: one taking
`telemetry.SLOW_MS` or longer is recorded by name with the signal it was heard through. Emission
is where a model change turns into every view's work, so it is the one place that cost is read
per listener.

**Upstream?** yes — with `core/telemetry.py`.

## `core/storage/git.py`

**Changed** from the template.

- `GitStorage` takes several `scopes` (pathspecs, `as_posix` on every platform): one repository
  holds several planned directories, and scoping keeps a Save from sweeping up the user's own
  source. `commit(message, also=())` records extra paths (the `.dplanner` index) in the same
  commit without making them part of the dirty count, and leaves out a scope nothing matches.
- Repository facts beside `find_repo_root`: `main_checkout` (a linked worktree's main checkout),
  `init_repo`, `origin_url` (memoised on `.git/config`'s mtime — an action state asks it on
  every context change), `canonical_remote` and `remote_label` (one spelling for a remote, and
  how it is named to a person), and `activity` (who worked under a path, from the last commits).

**Upstream?** yes — any template application that opens a repository by path meets each of
these.

## `core/storage/github.py`

**Changed** from the template.

`pull` rebases onto origin rather than fast-forwarding, and `push` fetches and rebases first, so
a Save from a second clone is never refused for being second; a conflict is aborted (autostash
restored) and raised as `DivergedError`. `GitHubStorage.create(name, dest)` creates an empty
repository and clones it. `repository_url(checkout)` asks `gh` and answers None on any refusal.
`has_origin` goes through the memoised `origin_url`, and the label is `remote_label`'s.

**Upstream?** yes — any application whose saves are commits from several clones.

## `core/storage/kept.py`

**Added** here.

The second clone door: a full working checkout the application keeps under the per-user
configuration directory for a verb that needs a repository on this machine and a person who
never chose a folder — never inside a plan repository, a project directory or the person's
repositories folder. Hardened only while it is made (validated transport, no hooks, no template
directory), through the environment rather than `-c`, which `git clone` would write into the
clone's config.

**Upstream?** yes — with `sparse.py`; the two doors are one story.

## `core/storage/locations.py`

**Changed** from the template.

The storage layer's public front door: it re-exports the repository facts from `git.py`
(`find_repo_root`, `main_checkout`, `origin_url`, `canonical_remote`, `remote_label`, `activity`,
`init_repo`) because no caller above it may name a provider module, and adds
`open_project_storage(directory)`, `repo_storage(repo_root, scopes)` (a provider at a root that
holds no project), `repo_group_for` and `grouped_by_repo` (one provider per repository, so a
Save commits each repository once over exactly its projects' directories).

**Upstream?** yes — with the scoped `GitStorage`.

## `core/storage/pointer.py`

**Added** here.

The `.dplanner` index: one line per project directory a plan repository holds, which is how a
fresh clone or an agent at the repository root finds the plan with no configuration.
`indexed(path, repo_root)` answers membership; `WORKTREES_DIR` lives beside it. It sits in
`core/storage` because `cli/discovery.py`, `domain/seed.py` and `domain/relocate.py` all touch it
from different layers.

**Upstream?** maybe — the pattern yes, the filename is DPlanner's.

## `core/storage/provider.py`

**Changed** from the template.

`DivergedError(StorageError)` carries the repository root and branch, because the answer is not
"try again" but somebody reconciling the two — and a window that knows where can offer to send
an agent. `dirty_file_count()` beside `is_dirty`. `commit(message, also=())` on the protocol.

**Upstream?** yes — any template with a remote meets the same conflict.

## `core/storage/sparse.py`

**Added** here.

The read-only clone door: a blobless, shallow, sparse clone of a folder in somebody else's
repository under a per-user cache root, keyed on remote, ref and folder so two positions never
share sparse patterns. It never commits or pushes. **The address is validated on every read** —
a leading dash, `ext::`, or a gitignore metacharacter in the path are refused by character set,
and the URL is passed after `--` as well — because a colleague's plan file is input.

**Upstream?** yes — it names nothing of the planner.

## `core/telemetry.py`

**Added** here.

One process-wide journal of `Span`s — actions, commands, slow slots, tasks, autosave flushes,
disk polls, CLI runs, sampled stalls and logged failures — nested, read by the window's tab and
`dplanner telemetry show`. Process-wide like `logging`, because `Signal` times its slots and can
be handed no service: `current()` is a ring buffer that writes nothing until the entry point
`install`s the file-backed one. Nothing is ever off; the hot path is two `perf_counter` calls per
slot. A handler on the root logger journals failures, and must not itself log through the root.

**Upstream?** yes — whole.

## `core/user_path.py`

**Added** here.

Repairs `PATH` for a desktop launch, which inherits the launcher's (`/usr/bin:/bin:…` from
launchd) and so finds no `gh`, `uv`, agent CLI or whisper: a login shell is asked once, before the
window is built, and every later `shutil.which` answers what a terminal would.

**Upstream?** yes — any desktop application that shells out.

## `core/wav.py`

**Added** here.

Raw signed 16-bit PCM to a WAV, and a clip's level, with the standard library (`audioop` left in
3.13). The dictation stack needs exactly those two.

**Upstream?** yes — beside `png.py`, with `recording.py`.

## `core/xlsx.py`

**Added** here.

A deterministic standard-library `.xlsx` writer — fixed timestamps, compression and part order;
inline strings, dates as serials, a bold frozen header, columns sized to their text — so the CLI
exports a spreadsheet without an office library or Qt.

**Upstream?** yes — as-is.

## Removed from the template

### `framework/exports.py`

`ExportRegistry` and `AppServices.exports` had no clients here, and none in the template
either. Git remembers it; a dormant seam reads as a promise the application does not keep.

**Upstream?** maybe — demonstrate it end to end or ship it as documentation.

### `framework/secrets_store.py`

Moved, unchanged in substance, to `core/secrets.py` (see that entry): a headless surface — the
CLI and a module's Qt-free files — must be able to ask whether this machine can keep a
credential, and neither may import `framework/`. Nothing in the file was Qt.

**Upstream?** yes — move it to `core/` in the template too.

### `framework/sidebar.py`

Replaced by `framework/index_panel.py` (one tree whose top-level folders come from an
`IndexSegmentRegistry`) anchored as a panel through `framework/panels.py`. An index shows the
workspace's shape and grows by a folder; a tab set made every feature a peer competing for the
same column.

**Upstream?** no — the index registry should go up beside it; deleting pages is this
application's choice.

## Lessons, no code change

### Conventions the template documents that we had to change

#### A module package's `__init__.py` must not re-export the Qt class

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
moment an application grows a second, headless one, the recipe's step 6 is what stops it
working, and the failure is an `ImportError` at startup rather than anything that looks like a
design problem.

**Upstream?** We think yes, and it costs nothing for a GUI-only application. The docstring
each `__init__.py` keeps is arguably better documentation than the re-export was. If the
template would rather keep the re-export, the walkthrough should at least say what it costs.

**Also worth a line in the docs:** the composition root's promise is "read this one file to
know the application". Moving the imports inside `default_modules()` keeps that promise —
the inventory is the first fifteen lines of the function instead of the file — and
`test_architecture.py`'s `ast.walk` scanner sees them either way.

#### `module_data` is not enough: a module also wants prose and files

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
the `StorageProvider`, so a store that tracks what it has written sees its own asset as
somebody else's edit. The area needs a callback back into the store.

### Two writers, one folder — the framework's biggest missing assumption

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
- A **window with unflushed edits** stops: autosave keeps its marks and pauses, and a
  *Reload from Disk* action makes the choice the user's.

**The result worth carrying upstream is the simplification, not the code.** We had planned an
advisory lock for CLI-vs-CLI on top of all this. Once the store refused stale writes, the lock
was unnecessary — the losing run is refused for the same reason and can just be re-run. One
mechanism covers three cases.

**Upstream?** The store-side check belongs in the application's store, so what the template
can offer is the *shape*: a `changed_underneath()` on the repository protocol, the
autosave-survives-failure behaviour, the watcher, and a paragraph in the report
saying that "memory is authoritative" has a precondition. We would rather the template said
this out loud than shipped a half-implementation.

### A headless surface is a real layer, and the template has no room for it

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

### Findings that need no change here, but the template should know

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

### Things we deliberately did *not* push into the framework

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
  of them (the host-supplied empty page) stopped existing once there was no host.
- **Lookup by "an id, a folder name, or part of a title" lives in `cli/`**, not in the model.
  It is a command-line affordance — resolving what a person typed — and the model should not
  have opinions about fuzzy matching.
