# Working on DPlanner

DPlanner is a **development planner**. It plans *projects* — each one a directory inside a
git repository, listed in a per-user project library — and it is meant to be driven by a
coding agent as readily as by a person.

```
Library  ── the account level: a per-user file listing project directories. One per window.
└── Project  ── a unit of work with a beginning and an end — a folder with a project.dproj,
    │           inside a git repository (its repo root and remote are derived, never stored)
    └── Step  ── a node in that project's graph
```

Steps form a **graph**, not a list: an edge lives on the step that waits, `requires` orders
the graph and refuses cycles, `relates` is a plain link. A step also carries **aspects** —
an estimate, a ticket, a description — which the graph itself knows nothing about. An aspect
is a module's namespaced entry in `module_data` (JSON) or `module_text` (prose), versioned
by the module that writes it, so a feature arrives without the model learning anything.

Built from [app-framework](https://github.com/Knutsi/app-framework). The architecture — what
a module is, how features cooperate without importing each other, where state lives — is
documented in that repo's `docs/index.html`. Read it once before adding a feature; it is
worth the twenty minutes. `ARCHITECTURE.md` here covers what DPlanner added on top.

## Engineering principles

- **Check for entropy before you finish.** Every task ends with a look at what the change
  left behind: a near-duplicate of something that already existed, a special case beside a
  general one, a name that no longer describes its file. Review every change for
  over-engineering too, and prefer simple code over type magic.
- **Prefer refactoring the old code over tacking on the new** whenever the refactor leaves
  the result *simpler*. Covering a new case by generalising what is there beats adding a
  parallel path — and if the generalisation would be more complicated than the two cases
  separately, that is the signal to keep them separate and say why.
- **Take the new developer's view at the end.** Open `src/dplanner/modules/` and the
  directory tree and read them as somebody seeing this for the first time: does each module
  name say what that module is? Is the separation of concerns obvious? Could they find where
  to add the next feature without asking? If not, the fix is renaming and moving, not a
  comment.
- **Sane defaults, options laid out.** Anything configurable whose right value the user
  would otherwise have to research — an agent CLI's invocation, a terminal's exec flag —
  offers the known choices up front (a dropdown of presets pre-filling an editable field)
  and works untouched on the default. A bare free-text setting is a lookup pushed onto the
  user. `modules/step_agent_instruction/settings_page.py` is the worked example.
- When you spot cleanup that reduces entropy without adding over-engineering or "magic",
  suggest it.
- Only add comments that carry durable value for future developers and agents. Otherwise,
  make the code self-documenting.
- `DESIGN.md` is the standard for all UI work here. `FORMAT.md` is the standard for anything
  that reaches disk. `ARCHITECTURE.md` is where a rule's *reasoning* lives — when you settle an
  architectural question, write the rule here and the why there, and have each point at the
  other. A decision that lives only in a commit message is one the next feature rediscovers.

## Checks — run all three before finishing any task

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q   # ALWAYS prefix the env var — see below
uv run ruff check      # lint (ruff format for formatting)
uv run mypy            # strict type checking, whole tree
```

On a machine whose shell already presets `QT_QPA_PLATFORM` (Arch with a tiling WM, for
instance), the `setdefault` in `tests/conftest.py` does not kick in and a bare `pytest`
opens real windows all over the workspace. Always prefix it.

The suite runs on every core (`-n auto` in `pyproject.toml`) — about **two minutes** for the
whole thing, so run the whole thing; there is nothing to be saved by not. Two flags are worth
knowing while working:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q -n0            # single-threaded: readable failures, debuggers
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/core tests/domain tests/cli   # ~18s: the Qt-free layers
```

The second is the inner loop for work below `framework/`, and it is a *path* selection rather
than a marker because the layers already say which is which: `core/`, `domain/` and `cli/` are
the Qt-free ones. It is not a substitute for the full run before you finish — most of what
this application does lives in `modules/`, and only the full suite covers it.

**Running on every core means a test may never write into `src/`, and must quiet what the
application it built has already started.** Both rules were learned from a flake. A test that
wrote a deliberately-bad file into the source tree and tidied up afterwards raced another
worker walking that tree; and a fixture that patched a module global raced the *live*
`PrRefresher` the application it built had running, which reads the same global. A `finally`
does not help with the first and a careful assertion does not help with the second: build over
a throwaway tree, and stop what is running before you patch under it.

**A SIGSEGV is not always memory corruption: check the stack depth first.** The
2026-09-02 crash — every `time_estimates` test, deterministic, "in `resizeEvent`" — was a
**synchronous layout loop**: the calendar called `setFixedHeight` inside its own resize
event, inside a resizable scroll area, so the new height toggled the scrollbar, the
scrollbar changed the width, the width changed the height, and the process died 184,800
frames deep with `QScrollArea::eventFilter` on the stack 20,000 times. gdb's `bt | wc -l`
says so in one line, where faulthandler shows four Python frames and a symbol
(`_Pep_PrivateMangle`) that is only where the stack ran out. **A widget whose height
depends on its width implements `heightForWidth` and lets the layout ask; it never resizes
itself in `resizeEvent`.** `time_estimates/months.py` is the worked example, and its
regression test sweeps a scroll area across every width that could flip the scrollbar.

**A pytest worker dying with SIGSEGV names an innocent test.** The suite has crashed this
way before (2026-09-01, roughly one run in three): the test reported is whichever one that
worker happened to be running, and the trigger moves with the total test count. That
episode rode on working-tree module code that was rewritten before it shipped — 21+ runs
across paddings and configurations have not reproduced it on the committed tree — but the
hazard is structural: ~520 tests hand their entire app build to the boundary collector as
one reference cycle, so a single widget-lifetime bug anywhere makes gc free a `QWidget`
whose C++ side is already gone. If it comes back, diagnose before debugging the named test:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q --dist loadfile   # green while --dist load is red
                                                             # = cross-test, not the named test
```

**To prove it is not your change**, replace your new test files with the same number of
`def test_x(): assert True` stubs and rerun; if it still crashes, only the test count
mattered. **To find the poisoning test without a crash**, run one pass with a
`gc.DEBUG_SAVEALL` plugin that catalogs each test's QObject-bearing garbage — under
SAVEALL nothing is freed, so the run cannot crash and the catalog is complete. Two shapes
to suspect in the culprit: a parentless `QObject` connected to its own method, and a
long-lived plain-Python signal holding a widget's bound method.

The layering rules below are enforced by `tests/test_architecture.py`, which runs with the
normal suite. **If it fails, fix the dependency direction — don't loosen the test.** Every
rule has a supported way to get what the shortcut wanted: a capability protocol, a typed
callback on your `Deps`, or a registry.

## Architecture: the layers

Bottom to top: `core/` → `domain/` → `cli/` → `framework/` → `modules/<name>/` → the
composition root (`modules/__init__.py`) → `app.py` and `entry.py`.

**Two of these came with the template and four are yours.** `core/` (storage, persistence
contracts, signals) and `framework/` (everything Qt) came from app-framework. `domain/` (the
model and its store), `cli/` (the headless surface) and `modules/` (the features) are what
makes this application itself. The framework is still ours to evolve here — see *Deliberate
divergences* below.

1. `core/` imports no Qt and nothing from the rest of the application.
2. `domain/` imports no Qt, and imports `core` only. It is tested with plain pytest.
3. `cli/` imports no Qt and nothing above `domain/`. A module's `cli.py` and `aspect.py` are
   the same: importable without a graphics stack. The CLI is how an agent drives DPlanner,
   and it has to start in milliseconds on a machine with no GUI libraries at all.
4. `framework/` never imports `modules` or the entry points.
5. Modules never import each other. Only `modules/__init__.py` may import them all.
6. Modules never import `AppServices`, the builder, or the concrete window. Window
   capabilities come through the protocols in `framework/window.py`.
7. `app.py` and `entry.py` import the composition root and nothing deeper.
8. Only `core/storage/` and the composition root name a *concrete* storage provider.
   Everything else depends on the protocols in `core/storage/provider.py` — which is what
   keeps the application runnable against a folder, a git checkout or a GitHub clone without
   a single `if` anywhere in a feature.

## Two surfaces, one vocabulary

A menu action and a `dplanner` verb build the **same object from `domain/commands.py`**. The
GUI pushes it onto the undo stack; the CLI applies it and lets the store flush. That one rule
is what keeps the surfaces from drifting: anything the CLI can do is undoable in a window,
and neither can grow a behaviour the other lacks without somebody editing that file.

It follows that a feature has two halves in one package:

```
modules/<name>/
├── module.py    the Qt half: the module class, its Deps, its views
├── cli.py       the headless half: CliCommand specs                ← imports no Qt
├── aspect.py    for a step aspect: SPEC, DATA_FORMAT, read/write    ← imports no Qt
└── section.py   the editor it puts in the step detail panel
```

The Qt-free files are checked by **name** — see `HEADLESS_FILES` in
`tests/test_architecture.py`. If the composition root reaches a new file at CLI time, add it
to that tuple; a file the rule cannot see is a rule that is only a habit.

## How to add a feature module

1. Create `modules/<name>/` with a `module.py` defining a frozen `<Name>Deps` dataclass —
   exactly the services and capabilities the module needs, no more — and a `<Name>Module`
   class: `__init__(self, deps)` stores them, and a no-argument `register()` does all the Qt
   work (activities via `deps.tabs.register_factory`, actions via `deps.actions.register`,
   an index folder via `deps.segments.register`).
2. Menu placement: every `ActionSpec` names a `menu` and a `group` from `MENU_STRUCTURE` in
   `menus.py`; `order` ranks only within the group (10/20/30…). Separators between groups
   are automatic. **Add a group rather than smuggling structure into `order`.**
3. If the module needs something another module provides, declare a typed callback — or a
   small consumer-owned `Protocol` — on your own `Deps`, and wire it in
   `modules/__init__.py`. Never import the other module. `modules/project_editor/module.py`
   is the worked example: it names the panel interface it needs and is handed a factory.
   If what you provide is a *widget* other features host, the module that owns it registers
   nothing and exposes a `create_…()` — see `modules/step_properties/`.
4. If it stores data, declare `data_format = ModuleDataFormat(...)` on the class and read
   `node.module_data[MODULE_ID]`; prose goes in `node.module_text[MODULE_ID]` and files in
   `store.files(node_id, MODULE_ID)`. See `FORMAT.md`. **Add the format to
   `default_module_formats()` if it is not an aspect** — that list is what the CLI migrates
   with, and it is derived from the aspects plus whatever is named explicitly.
5. To put an editor in the step detail panel, register an `InspectorSection` whose `factory`
   returns an `InspectorExtension`. For one prose document that is
   `ProseSection(field_for, undo, placeholder)` and nothing else — the framework owns the
   binding mechanics.
6. To anchor a surface *beside* the tabs, register a `PanelSpec` into `deps.panels` naming an
   area (`LEFT`, `RIGHT`, `BOTTOM`) — the user can move it from its header and hide it from
   *View ▸ Panels*, so the area on the spec is a default, not a decision. A panel that should
   appear only sometimes implements `ContextPanel.show_context(context) -> bool`; the dock
   calls it on every context change and takes the panel off screen when it answers False.
   **Never build a panel inside an activity** — see the mechanical fact below.
7. If it has verbs, add `cli.py` with a `commands()` function returning `CliCommand`s, and
   list it in `default_cli_commands()`. Keep it Qt-free. When `commands()` needs a
   cross-module fact, take it as a **keyword-only parameter and close over it in one inner
   wrapper** — `modules/progression/cli.py` is the worked example; don't invent a fifth
   injection style.
8. Construct it in `default_modules()`. **List order is registration order and it matters** —
   status-bar widget order, index folder order, and whether a surface exists before whoever
   renders it is built. Put a comment on any position that is constrained.
9. Leave the package `__init__.py` as a docstring — the composition root imports
   `from dplanner.modules.<name>.module import <Name>Deps, <Name>Module`. Re-exporting the
   Qt half there would make the package's Qt-free files unreachable without loading Qt, and
   the CLI reaches them through this package. Add tests under `tests/modules/`; keep
   `README.md`'s layout map current.

If you find yourself needing to edit a file outside your own package and the composition
root, stop and look for the registry or capability you have not found yet.

## Mechanical facts worth knowing

- **Every change follows one chain: `action(context) → command → model → signal → views`.**
  A gesture is not a special case — a canvas drop runs the same `ActionSpec` the menu does, so
  the verb exists in the palette too and can be tested by handing it a constructed `Context`
  with no widget in sight. Nothing pushes an update at a view: the model emits, each view
  decides what to redraw, and the `origin` is how the view that caused the change knows to
  ignore its own echo. **`ARCHITECTURE.md` has the diagram and why each link is there** — read
  it before adding a surface that changes anything.
- **Only the active pane speaks for the user.** The window can show two or three tab groups
  side by side, and there is still exactly one context. An activity that publishes a
  selection must do it only while it is the current one — see `ProjectActivity._is_active`.
- **One panel per surface, not one per tab.** A detail panel is anchored in a window area and
  reads the context; an activity never holds one. Building it inside the tab is what made the
  step editor appear twice in a split window, and the fix deleted code rather than adding a
  visibility check — because "only the active pane publishes" already says which selection a
  panel should be showing. `ARCHITECTURE.md`'s *Where a panel goes* has the rest.
- **Two surfaces meet at a seam, and the seam belongs to the splitter.** A 1 px `$BORDER`
  hairline inside a 7 px handle, from one `QSplitter::handle` rule that reaches every splitter
  the application builds — between two tab groups, between a panel area and the tabs, between
  two panels stacked in one area. A panel area therefore draws no border of its own: a surface
  that draws its own edge where a seam already falls gets two lines a pixel apart. **The two
  orientations are built differently on purpose** — Qt gives a horizontal handle the box model
  and fills a vertical one's whole rect, so the rule that centres a line in the first renders a
  7 px slab in the second, and nothing says so. `tests/test_theme.py` renders both rather than
  reading them. `ARCHITECTURE.md`'s *A seam belongs to the splitter* has the reasoning.
- **A pane is marked only while there is another pane.** The accent edge on the group you are
  in appears when the window splits and goes when it stops being split — the same condition
  that installs `_ActiveGroupWatcher`, because it is the same fact. It lives on a one-widget
  `_Pane` frame, never on the `QTabWidget`: `documentMode` paints no pane frame for QSS to
  reach, a widget's children paint over anything it draws itself, and QSS on the `QTabBar`
  would replace the native rendering the dimmed titles rely on. `_drop_group` clears the mark
  itself — `_announce` short-circuits on exactly the case that needs it.
- **A toggleable aspect's tab follows the aspect.** Milestone, Feature, Agent, Ticket, Test
  and Check are Step ▸ Type toggles (independent, never a radio group), and each registers its
  `InspectorSection` with a `shown_for` predicate so its tab exists only on a step that
  carries the aspect. **The description is an agent step's instructions** — the briefing's
  `## Instructions` block, decided by the composition root's `_briefing_instruction`; a
  *separate* instruction (the checkbox in the Details tab's Description block,
  `dplanner agent set`; dropped atomically with `agent set --clear`) is the opt-out for a
  step whose how-to-execute differs from what-it-is. `ARCHITECTURE.md`'s *The description
  is the instructions* has the reasoning.
- **Every step tab follows a toggle, and absence encodes the default — in both directions.**
  Estimate, Description, Handoff and GitHub are toggles too now. For most aspects absence
  means *off* and the stored `{"on": true}` marker records the claim; for **Estimate and
  Description absence means *on*** and the marker (`{"off": true}`) records the opt-out,
  because most steps are work and work has a size and a name. That is one `FORMAT.md` rule
  applied honestly, and it is what makes the change cost existing projects nothing. The
  Details tab is its blocks, and always shows: the name leads it, and a step always has one.
  The CLI half of the two opt-outs is `dplanner estimate clear` and `describe clear`, which
  therefore mean **off**, not "empty" — for an aspect whose default is on there is nothing
  else clearing could sensibly mean, and lint skips a step that has opted out.
- **Turning an aspect off shelves it; nothing asks and nothing is lost.** The entry and
  the prose move to `modules/shelf.json` beside the step (`domain/shelf.py`: `turn_off`,
  `turn_on`) and come back on the next toggle-on; with the entry genuinely absent, no
  reader learns a new key. Every Type toggle is one `framework/aspect_toggle.py` call —
  the module hands over `enabled`, a `fresh` entry and (for the two opt-out aspects) what
  to `leave` — and every CLI `clear`/`off` verb applies the same `turn_off`. The migration
  pass reaches into the shelf (`migrate_shelved`) and the asset catalog counts a shelved
  prose's links as uses. `FORMAT.md` has the shape; `ARCHITECTURE.md`'s *Turning an
  aspect off shelves it* has the reasoning.
- **The aspect bar across the panel's top renders the Type submenu, never a copy of it.**
  `framework/aspect_bar.py` puts every Type toggle in a right `QToolBar` as a glyph and
  runs each through `ActionRegistry.run`, so a toggle keeps its own undo command. Its left
  `QToolBar` is **templates** — `StepPropertiesDeps.templates`, named by the composition
  root: a label and the *set* of toggles that are on (Step, Milestone, Feature, Agent,
  Check), worded and wearing a body tone from `theme/tones.py`. Clicking one runs every
  toggle that differs inside **one `UndoService.gesture`**, and a template reads as
  selected exactly when the step carries its set and nothing else — a combination is a
  template, both ways, computed on every refresh and never stored — and **Step is the
  catch-all**, lit for any combination no other template names. **Overflow is
  `QToolBar`'s own » button**, which lists what no longer fits as checkable menu
  entries. It takes the context as a **function**, so the panel inside the details
  dialog names its own step. **"This type can never carry that aspect" needs no new
  mechanism** — a toggle returning `ActionState(enabled=False, label=…)` is the existing
  *disabled, never hidden* rule; do not build one until it is asked for.
- **Tests can be read grouped by what collects them.** The Tests tab's third selector groups
  rows by feature, milestone or check, filled by `scope.gatherers()` in the one place rows
  are ordered (`TestsActivity._rows`); `TestsTable` draws a spanned heading wherever the key
  changes, and a step nothing gathers lands under *Not in any feature* — the same steps
  `dplanner project lint` reports as `scope.ungathered`. A step two features both wait on
  gets one **joint** heading rather than two rows: a test listed twice is a test marked
  twice.
- **The step panel's first tab is Details, composed from blocks.** A module that wants its
  editor there instead of behind a tab of its own registers into `services.step_details` —
  the `InspectorSectionRegistry`'s third instantiation; estimate, description and the spec
  figures are the registrants, and `modules/step_properties/details.py` stacks them
  (`stretch` on the section says who gets the leftover height, `shown_for` hides a block
  with nothing to say). `ARCHITECTURE.md`'s *The Details tab hosts the same contract, as
  blocks* has the reasoning — including why a host is a registry instance, never a flag.
- **A large text field expands into a modal editor** — `framework/text_dialog.py`: a
  second `TextBinding` over the same `TextField`, live-synced through the foreign-change
  path, opened from the corner button `attach_expand` pins onto the editor.
  `ARCHITECTURE.md`'s *Expanding an editor is a second binding, not a copy* has the
  reasoning; never copy text out into a dialog and back.
- **A file pasted or dropped into a prose editor is attached, then linked.** `ProseEdit`
  (`framework/prose_edit.py`) content-addresses it into the module's file area — the same
  place `describe attach`, `handoff attach` and `test attach` write — and types
  `![alt](assets/…)` at the caret, or `[name](assets/…)` when it is not an image. A plain-text
  markdown editor cannot embed a picture without breaking `TextBinding`, so it does not
  pretend to; the gallery under it shows the thumbnail. The link is undoable and the blob is
  not (`FORMAT.md`), and the insert **seals the undo step on both sides** or it would merge
  into the sentence being typed. The editor never resolves the area itself: it is handed
  `AssetGallery.attach_bytes`, and `ProseSection.set_area` aims both — called by the host,
  because a test's body is keyed by the test while its images belong to the step. What counts
  as an arriving file is `framework/mime_files.py`, shared with the spec module's rich-text
  editor so the two cannot disagree about a drop. The Description, test bodies and both agent
  instructions have it; **`modules/step_handoff/section.py` does not** — it predates
  `ProseSection` and still hand-rolls its own Attach button and file list, so it is the one
  prose editor that takes no paste. That is a gap, not a rule. `ARCHITECTURE.md`'s *A pasted
  image is an attachment and a link, not an embed* has the reasoning.
- **The asset library is a derived union, and reuse is a copy.** Every file-carrying module
  exports an `asset_source()` from its Qt-free half saying what its areas hold and what
  still uses each file; `domain/assets.catalog()` is one derivation with three readers —
  the Assets tab (`modules/project_assets/`), `dplanner asset list`/`uses` and `asset
  prune` — and the composition root's `_asset_sources()` is the one assembly both surfaces
  read. Picking an existing asset into an editor (`Insert from Assets…`, wired as
  `ProseSection.set_picker` beside `set_area`) copies bytes into the target's *own* area
  through the ordinary attach path, so a link never points into another module's
  directory; identical bytes carry identical content-addressed names, which is what lets
  the browser group them as one asset. Display names are the browser module's project
  metadata (`{"titles": …}`), never part of a link — renaming cannot break a reference.
  Handoff and agent-instruction files are used *by existence* (briefings carry those areas
  wholesale); the pool (`asset attach`) is `prunable=False`; `asset prune` is dry-run by
  default and never enters a directory no source scanned. `ARCHITECTURE.md`'s *An asset
  library is a view, not a store* and *Inserting an existing asset is a paste with a
  different source* have the reasoning.
- **Double-clicking a step anywhere runs `steps.details`** — a modal dialog hosting a second
  `StepPanel`, disposed on close. It is the one gesture across canvas, order, progression and
  estimates; a table runs it against a context naming exactly the row's step. Reveal-in-graph
  is the `steps.reveal` verb in the Step menu, not a double-click. `ARCHITECTURE.md`'s *The
  same panel, briefly modal* has the reasoning.
- **Where the user left off is remembered by key, per library.** Which index folders are
  open and which tabs the window had are written to the per-user store under
  `library_scope(library path)` — `framework/user_config.py`'s `get_scoped`, never the
  project directory, which is one person's window and not the plan. Both restore by **node
  id**: a remembered id that names nothing restores nothing, so a library that changed
  underneath comes back with *fewer* folders and tabs rather than wrong ones — no version
  stamp, no migration, the check is the lookup. The tree's folders are the index panel's own
  bookkeeping; tabs are `modules/reopen_tabs/`, which must be listed after every module that
  registers an activity factory and carries the *Settings ▸ Startup* switch.
  `ARCHITECTURE.md`'s *Where the user left off is remembered by key* has the reasoning,
  including why the write happens on every change rather than at close.
- **A single click in the index opens a preview tab** (`tabs.open(..., preview=True)`): at
  most one preview exists, the next preview replaces it, and a deliberate act — activation,
  or moving the tab — pins it. A preview-open of anything already open is a plain focus.
  `ARCHITECTURE.md`'s *A click is a glance* has the rules and why no timer is involved.
- **Canvas input is a stack of modes, and Escape pops one.** A mode handles input and has
  power over the view; a hook that returns False lets the event fall through to the canvas
  keymap and then to Qt, which is why `IdleMode` is nine lines and why a mode that claims a
  press suppresses node dragging without a flag anywhere. A mode still only *reports* — the
  activity turns its signals into commands. The current mode is published into the context, so
  a mode-switch action's `checked` stays a pure function of it. `ARCHITECTURE.md`'s *Who owns
  the canvas's input* has the reasoning; add a behaviour as a mode, never as a field.
- **A canvas key names action ids; it is never an `ActionSpec.shortcut`.** A bare `h` on a
  menu-bar QAction fires application-wide and eats a keystroke in the step editor. Bind it in
  `modules/project_editor/keymap.py`, where a key names the verbs it means in order and the
  first the context allows runs — that is how one Delete key covers links and steps.
- **Lasso is a mode, and it touches cards.** `LassoMode` draws a `QPainterPath`, and on
  release the scene answers `nodes_touching(path)` by the node's *body* rect — never
  `scene.items(path)`, whose hit shape is the body plus `PAINT_MARGIN` and includes the
  edges. One lasso ends the mode, Shift on the release adds to the selection, and the mode
  switch is `steps.lasso` (`S` on the canvas), the same shape as `steps.connect`. Region and
  lasso share one `OutlinePreviewItem` through `Canvas.aim_outline`.
- **Isolate is one domain question and one domain command.** `Library.boundary_edges()`
  names every edge with exactly one end in a set (both kinds, skipping edges to a deleted
  step, as the canvas skips them) and `remove_edges_command()` turns edges into one
  `CompositeCommand` of per-`(waiter, kind)` replacements — Unlink, `steps.isolate` and
  `dplanner step isolate` all build from those two, so the surfaces cannot drift.
- **Marks are a way of looking, remembered per user.** Starts, Ends and Orphans
  (`project_editor/marks.py`, Qt-free) are one `Marks` value on the module, written to
  `user_config` and fanned to every scene like `RenderHints`; a tab opened later wears them.
  Which sockets a node has connected is `marks.ports()` over the drawn edges, derived every
  sync. The toggles' `checked` reads the module and the module calls `context.refresh()` —
  the theme-toggle pattern, deliberately not an edge on the activity node, because a
  preference outlives any tab. `ARCHITECTURE.md`'s *Marks are a way of looking* has the
  reasoning.
- **A scrollable area's extent must never depend on what the user is moving.** The canvas is
  a *plane*: a constant scene rect centred on the origin, far larger than any graph. That is
  what lets panning go on for as long as anybody wants, and it is also the answer to the older
  bug — an extent recomputed from the items moved under every node drag, and the canvas
  appeared to pan away under it. A constant cannot. The scroll bars are hidden with it (a
  handle a two-hundredth of its groove says nothing true) and the minimap orients instead.
- **A painter never trusts `option.palette`.** Qt fills `QStyleOptionGraphicsItem.palette`
  once, when the scene is created, and never refreshes it, so every canvas item kept the
  colours of whatever theme its tab opened in. `items.live_palette()` is the only source of
  colour on the canvas. Its cousin: **a colour copied out of the palette onto a widget goes
  stale** — `TabHost` tints its tab titles, so it re-tints on `QEvent.PaletteChange`. If a
  surface stores a colour, it owes that hook.
- **Work may leave the GUI thread; mutation may not.** `core.signals.Signal` is synchronous
  and has no thread affinity, so the model is only ever changed on the GUI thread. Anything
  computed off it returns through `TaskRunner`, the one place that uses real Qt signals.
- **There is no Save-file action.** Autosave writes 1.5 s after the last change; *Save*
  means recording a version: **one commit per dirty repository, scoped to that repository's
  project directories** — several projects in one repo save as one commit, and the user's
  source code is never swept up. Quitting with dirty repos asks once, listing them
  (`modules/sync/exit_dialog.py`). Branch verbs act on the focused project's repository.
  The CLI has no timer: a run is a transaction that flushes once, at the end, and writes
  nothing if the verb failed.
- **Every model change goes through a command** on the single undo stack, and carries an
  `origin` so the view that made the edit can ignore its own echo.
- **A background sync of an external fact applies its command directly, off the undo
  stack, with its own origin** — undoing the user's edit must never restore a stale PR
  state instead. `modules/github/refresh.py` is the example; `ARCHITECTURE.md`'s *Syncing
  an external fact* has the reasoning.
- **Two writers are expected.** An agent runs `dplanner` against a project a window has
  open. The store records what each project directory last looked like and **refuses to
  flush over anything that changed underneath** (`StaleWorkspaceError`) — checked **per
  project**, so one project's outside edit never blocks saving another; the library file
  has its own stamp. The window notices and reloads when it owes nothing, and says so when
  it does. That one check also makes a lock between CLI runs unnecessary. **What it looks
  at is the plan, not the directory**: `PLAN_ENTRIES` (`project.dproj`, `modules/`,
  `steps/`) — a project directory is often the repository root, and counting the source
  tree or an agent worktree under `.dplanner/` as another writer reloaded the window on
  every edit anyone made.
- **Reloading the library is a full rebuild**, not a reset. Registries refuse duplicate
  ids, which is what makes that the only implementable answer — and the correct one.
  Opening a *different* library is not even a reload: File ▸ New/Open Project Library
  spawns a detached instance (`modules/library/module.py::spawn_instance`).
- **Discarding a build is `discard_build()`, and closing the window is not enough.** Qt keeps
  a closed `QWidget` in `topLevelWidgets()`, so without `deleteLater()` the whole build —
  services, model, every module — stays reachable forever. Nobody notices in the application;
  the test suite builds one per test, and the omission made it quadratic and cost it 80% of
  its running time. Never hand-roll the close sequence: a reload and a test both call that
  one function. Anything that discards Qt objects with **no event loop to follow** must
  dispatch the deferred deletes itself (`sendPostedEvents(None, DeferredDelete)` — never
  `processEvents`, which skips them); `AppSession.close()` is the only place that does.
  `ARCHITECTURE.md`'s *Closing a window is not discarding it* has the measurements.
- **Project membership changes bypass the undo stack.** New/Open Project may `git init` and
  always writes outside any store; Remove from Library only forgets. Neither is honestly
  reversible, so they apply directly with `LIBRARY_ORIGIN` and the library file is
  rewritten by the ordinary flush (a structure mark on the library root).
- **Blocking work runs through `TaskRunner`**, never on the GUI thread: storage operations,
  LLM calls, anything that touches the network. It appears in the task centre for free.
  The one documented exception — storage operations that rewrite the working tree, which
  must complete before the app touches anything else — is `ARCHITECTURE.md`'s *Storage
  operations that rewrite the working tree are synchronous*.
- **An edge lives on the step that waits**, is validated against the project, and is
  deliberately *not* rewritten when a step is deleted — undo has to restore the graph
  exactly. `Library.requires()` skips ids it cannot resolve. Edge kinds this build does not
  know are loaded and written back untouched.
- **`Library.link_refusal()` is the only authority on a legal edge.** `set_edges` asks it
  before writing, and `steps.link`'s state asks it to decide whether the menu entry is enabled
  and what a greyed one says. Never write a second reachability check in a view — the one that
  existed refused every drop for a fortnight because it read gesture state that had already
  been cleared.
- **An action that exists but does not apply right now is DISABLED, never HIDDEN.** A greyed
  entry teaches the precondition — its `label` carries the reason where there is one. HIDDEN
  is reserved for a capability absent from this build (a feature flag, a storage provider
  without history) and for a verb whose opposite occupies its slot (`steps.link` stands down
  while Unlink is offered). The palette filters on runnable; every other presenter — menu
  bar, toolbars, `build_menu` popups — shows the greyed entry. `ARCHITECTURE.md`'s *Hidden
  means absent; disabled means not now* has the reasoning.
- **A right-click renders a menu, never a copy of one.** `build_menu` takes a name from
  `MENU_STRUCTURE`, so anything with a context menu owns a menu in that table — the canvas has
  `Step`, the index tree has `Project`, the tab bar renders View's Tabs submenu (via
  `build_menu`'s `submenu` filter), and a toolbar button may drop a submenu down the same
  way (`ActionToolbar`'s `menus`). Make the thing under the cursor current *first*, then
  build; the menu then reads the same context every other presenter does.
  **A text widget's own standard menu is the exception**: `ProseEdit` appends *Insert
  Image…* to `createStandardContextMenu()`, because a verb acting on one widget's caret
  belongs in no menu bar and would be greyed everywhere else.
- **A submenu is one child menu per title, and a group change draws the rule *inside* it.**
  Both presenters agree (`framework/menubar.py`, `framework/action_menu.py`), so two groups
  can feed one submenu — what a test *is* and what it *did* — and a group that only feeds an
  existing child menu costs the menu itself no line. Several submenus therefore sit in one
  group as a band (Step's `classify` holds Type, Status and Test), and since a child menu
  sits at its first entry's `order`, siblings in one group claim bands of it — the one place
  `order` says more than "rank inside this group", written down in `menus.py`.
  `ARCHITECTURE.md`'s *A submenu is one child menu per title* has the reasoning.
- **An `ActionSpec` may carry a glyph, and only the pop-ups paint it.** `icon` is a
  `(QColor) -> QIcon` painter, rendered by `build_menu`, `append_action` and a toolbar
  dropdown — all built fresh on every open. The menu bar's QActions outlive every theme
  change, so a colour baked into one goes stale; that is the same trap as `option.palette`.
  Every Type toggle carries the glyph its node's medallion wears (`theme/icons.py`'s
  `GLYPH_ICONS` vocabulary), so the Type submenu, the aspect bar and the node agree.
- **A picked node is lifted, not recoloured.** Selection thickens the border to the accent,
  *gains* whatever fill the node already had (so a picked milestone is still purple), lifts
  the card two pixels over a soft shadow — faint, and clipped to the ground around it rather
  than under it, since the fill is translucent — and claims a Z of its own. The rings
  composite, so the shadow's alpha buys twice what it looks like. `PAINT_MARGIN` is the one
  number every decoration is measured against and `boundingRect` is exactly it, **constant
  whether or not the node is selected**. `ARCHITECTURE.md`'s *A picked node is lifted, not
  recoloured* has the reasoning.
- **Derived facts are computed, never stored** — the topological order in
  `domain/ordering.py` is the reference, and `domain/schedule.py` is the same walk carrying
  estimates. Storing one means it can disagree with what it came from, and the CLI is what
  catches you out: `dplanner step link` changes a graph with no window running to notice.
  Availability comes from exposing the function everywhere — the view, `dplanner order show`,
  `--json` — not from writing the answer down.
- **A domain derivation is handed a function, never a schema.** `domain/schedule.py` asks for
  `days_for(step)` rather than reading `module_data["estimation"]`, so the module that owns
  the estimate still owns its shape and the domain works for whatever answers next. That is
  the same seam a module's `Deps` uses on the module layer, one level down.
- **Renaming a module is a `Takeover`, not a migration.** The on-disk id is the contract
  between the old module and the new one, so the successor's package carries the retired
  id and a converter and the data moves at open — see `modules/estimation/aspect.py` and
  `FORMAT.md`'s *Retiring a module*. No project-format change, and no module importing
  another.
- **Automatic graph layout is never persisted; an explicit sort is.** A node nobody moved is
  placed by dependency depth every time the project opens — storing that would make merely
  opening a tab dirty the project, and every CLI-created step would grow a position file
  behind the user's back. A sort *action* (`canvas.sort_*`, `dplanner layout sort`) is a
  user gesture, so it writes through the undo stack like a drag. Named layouts and regions
  are project-level entries under the same `project_editor` id — `ARCHITECTURE.md`'s *An
  explicit sort persists; the ambient layout never does* has the reasoning.
- **A module that writes a number owes it a `float`.** An `int` writes as `5` where a
  reloaded float writes as `5.0`, making a file's bytes depend on whether the project had
  been reopened. `module_data` is opaque to the model, so the coercion belongs in the
  aspect's `write()` — see `modules/estimation/aspect.py`.
- **Editing a spec in-app is a replace, and markdown has no read mode.** Picking a markdown
  row opens the editor and starts the session; picking another row or closing the tab ends
  it; the idle flush persists in between. The Specs tab's markdown editor flushes a session
  as one `spec import`-style replace: blob written straight to the file area, the index
  through one merged command, `previous` pinned to the session's base so `spec diff` shows
  the session. Markdown only — PDFs and plain text stay view-only — and the editor prunes
  only blobs its own session superseded. `ARCHITECTURE.md`'s *Editing a spec in-app is a
  replace* has the reasoning.
- **Running an agent launches a peer, never a task.** *Run Agent* spawns a detached terminal
  the user owns — not a `TaskRunner` body, which would promise cancel and progress nobody
  can honestly deliver. The terminal opens at the project's **git repository root** (via
  the `workdir_for` seam the composition root wires from `find_repo_root`). The prompt goes
  to a per-run temp directory, never the project. The agent reports back through the CLI
  (`status set`, `agent-state set`, `handoff set`). `ARCHITECTURE.md`'s *Running an agent
  launches a peer, not a task* has the reasoning.
- **The peer reports its end through its run directory, and the window clears the chip.**
  The wrapper script is the one process that knows when the agent exits, so it writes the
  shell's facts (`shell`: tty, pid, tmux pane, terminal program, window title) beside the
  prompt on start and the exit status (`exit`; `closed` on a hang-up) at the end — no
  terminal-specific hook, so it is the same on every platform and terminal. The agent-run
  module (`step_agent_run/`) polls the runs it launched, clears the step's state when a
  shell ends — directly, with the launch origin, the way the launch was stamped — and
  **stands down while the plan changed underneath**: the reload rebuilds it and it
  re-adopts its runs from the per-user store, so an exit is never written over the agent's
  own last `dplanner` call. Runs are per-user, per-machine facts (`user_config`), never the
  plan. The Agents browser (status-bar button, *View ▸ Agents…*) is the management view;
  *Step ▸ Show Agent Terminal* focuses the window through `terminal.py`'s per-platform
  provider (tmux pane, tty via AppleScript, ancestor pid via xdotool, PowerShell pid) and
  is greyed with the reason where the desktop cannot; *Clear Agent Run* is the window's
  twin of `agent-state clear`. `ARCHITECTURE.md`'s *The peer reports back through its run
  directory* has the reasoning.
- **Which terminal opens is a table, not a chain.** `launcher.TERMINALS` is one row per
  known terminal per platform with a probe saying whether it is installed; *Automatic* is
  the first installed row (the platform's own default), and the settings dropdown lists the
  same rows and pre-fills the editable template — the agent presets' pattern. A new
  terminal is a row, never an `if`.
- **A live agent run is a chip and a marching ring.** The chip on the bottom edge names the
  state; the dashed ring round the body moves, which is what says "somebody is on this one
  right now". One `QTimer` on the scene advances every ring and runs only while a node
  wears one — `GraphScene._settle_ring_timer` after every sync. The ring is derived from the
  chip (`NodeAccent.chip_text`), so one field says both.
- **Inherited handoffs are computed, never stored** — `step_handoff/handoff.py` is one
  function with three readers (tab, CLI, agent prompt). Same rule as the ordering, and the
  reasoning is in `ARCHITECTURE.md`'s *Pass-forward is derived at read time*.
- **Progression is derived, never stored** — `domain/progression.py` is the graph's
  readiness with a `status_for(step)` handed in like `days_for`; the board, `dplanner
  progression show` and `--json` are three readers of one function, and the frontier is a
  per-step check, not `ordering.ready()`'s wave one. `ARCHITECTURE.md`'s *Progression is
  the status-aware frontier* has the partition rules and why each was a decision.
- **Staffing what-ifs are derived; only the assumptions are stored.** The time estimates
  tab and `dplanner schedule matrix` are one derivation — `domain/schedule.py`'s
  `phases` over `parallel_finish`, a deterministic two-pool greedy simulation (longest
  remaining chain first, ties by project order) handed `days_for`, `is_agent` and
  `is_milestone` as functions. **Milestones run in sequence**: each stretch is a
  milestone's `scope.cone` truncated at the milestones before it, simulated on its own
  (`parallel_finish`'s `among`) from the working day after the previous one lands — or
  from a date of its own, when it has one and that is later; an earlier date is *pushed*
  and reported, never silently overlapped. Calendar time is the same walk over a wrapped
  `days_for` (`time_estimates/schedule.py`'s `stretched`), so the domain never learns what
  an efficiency is. Three things reach disk, all under `time_estimates`: the focus factor
  on the project node, and a milestone's start date and colour on its step — written by
  the tab's controls and `dplanner schedule focus` / `schedule milestone` alike. A cycle a
  hand-edited file smuggled in is named by `ordering.cyclic()` and the tab says so instead
  of drawing a calendar over a broken walk. `ARCHITECTURE.md`'s *Time estimates: two
  worker pools, one greedy simulation* has the reasoning.
- **A test belongs to a step, and a step carries several.** A description says what a step
  *is*; a test says how you would prove it, and it outlives the step. A test is **not a
  node** — it is a record in the step's `testing` aspect with its own id, title, markdown
  body and per-run result, so forty steps with three tests each do not become a hundred and
  sixty nodes. The body is a **string in the record**, not a `.md`: a node holds one prose
  document and a step holds N tests. Ids are minted **per project** and meant to be read
  (`T100, T101, …`; runs are `R100, …`), which is what lets a run's results be flat, an id be
  quotable, and a rename never detach a test's history. The tab is **master-detail** — a list of tests
  and an editor for the selected one, side by side where the width allows and stacked in the
  narrow dock — because a stack of equal cards stops working at the third test.
  `ARCHITECTURE.md`'s *A test belongs to a step, and a step carries several* has the
  reasoning, including the diff trade the string body accepts.
- **Documentation is a fragment per step and a document per collector.** The `docs` aspect
  is what one step adds to the product's documentation; `docs_compiled` is what a feature or
  a milestone makes of everything it gathers. Two aspect ids in one package, because a node
  holds one prose document per module and a feature legitimately has both. **There is no
  step kind for compiling** — a feature and a milestone already *are* the collectors, so
  Compile is a verb on them. A milestone reads its features' *compiled* documents, not their
  notes again (`ScopeKind.gathers` says so), which is also what makes recompiling a feature
  mark its milestone out of date. **Staleness is a digest, never a timestamp**: a compile
  stores the digest of what it read, and "out of date" is a comparison — so a relink that
  changes what a collector gathers says so by itself. The CLI is where an agent compiles:
  `docs status`, `docs collect`, then `compiled set`, which re-stamps. `ARCHITECTURE.md`'s
  *Documentation is fragments, and a collector compiles them* has the reasoning.
- **An LLM call is a task, and the service is GUI-bound.** `framework/llm_service.py`'s
  `complete()` is blocking network I/O, so it runs in a `TaskRunner` body and the answer
  comes back on the owner's own Qt signal — the runner has no result seam. Every call is
  already in its ring buffer, so nothing logs one. An AI-gated control is **disabled, never
  hidden**, carrying `status().message`, and re-asks on `config_changed`. The service reads
  its provider through QSettings and its key through the keychain, so **`cli/` cannot call
  it** — the agent loop above is the headless answer. `ARCHITECTURE.md`'s *An LLM call is a
  task* has the rest.
- **A collector is a cone truncated at the next collector.** `domain/scope.py`'s `cone()`
  walks `requires` backwards and refuses to pass through a step the `stops_at` predicate
  claims — so a **check** stops at nothing and stands for everything behind it, a
  **milestone** stops at milestones and holds what is new since the last one, and a
  **feature** stops at features and milestones and holds its own work. One walk, six
  readers: the Covers tab, the Tests tab's scope selector and its Group by, `dplanner scope
  show`, `test-run start --scope`, and three lint checks. `ordering.upstream()` is the same
  function with nothing to stop it. Never store what a collector holds — `dplanner step
  link` relinks a graph with no window running to notice.
- **A `ScopeKind` is wired, never inferred.** `modules/__init__.py::_scope_kinds()` writes
  the three predicates literally: what carries a kind, where its cone stops, and — a
  separate question — which kind it is *read as a list of* (`gathers`). A milestone is read
  as its features; a feature is the finest grain and reads flat. `step_check` is a bare
  marker with no tab of its own; a feature step names the catalogue record it realises and
  its tab edits that record; `modules/testing/` renders what any of them gathers, because a
  list of tests is testing's business. That keeps the wiring one-directional. `ARCHITECTURE.md`'s *A check is a scope over the graph* has the
  reasoning, including why exclusivity is a predicate rather than a stored list.
- **A kind is what a node *is*; a facet is what it carries.** Milestone, Feature, Check and
  Agent Step are kinds — a node exists in order to be one, and wears a body colour for it:
  purple a milestone, **teal a feature**, green a done step (`BODY_TONES` in
  `theme/tones.py`; done outranks milestone outranks feature, and the medallion still says
  what else the node is). An estimate or a description is a facet. The **aspect bar's
  left** words *templates* — a kind with the facets it usually carries — which is why that
  list is named in the composition root (`StepPropertiesDeps.templates`) rather than
  derived from the Type submenu; the bar's right is every toggle, as a glyph. **Step ▸ New is one verb**: a step is born plain, titled "New
  step", and the details dialog opens on it with the name selected, where the bar says
  what it is.
- **A step placed by pointing at a spot earns a stored position.** `StepVerbs.create()` is
  the one place a step is born on the canvas — New and the double-click on empty space both
  come through it — and it writes the position **in the same command** as the node,
  because a gesture is one undo. Where it lands is `GraphView.last_click`, which
  every button press records *before* the mode stack sees it, and which a right-click
  refreshes so the menu's own New lands where the menu was raised. No click yet means no
  stored position, which is the ambient layout doing what it always did. The step then
  becomes the **selection**, the remembered point steps one row down (`placement.below()`),
  and `steps.details` opens on it — the first two through the `placed` seam a paste shares,
  the dialog through `created`, which only a birth calls — because they belong to the
  canvas, not to the verb — so New twice in a row leaves two nodes rather than one hiding
  another, and naming a step is the gesture's second half. A step that arrives *carrying*
  something — a dropped feature's marker — arrives named, so it is placed but not `created`.
- **A feature is a record, and a feature step is its instance.** The project's catalogue
  (`modules/feature/catalogue.py`, `dplanner feature list`) holds every feature whether or
  not it is on the graph — read out of a spec with `feature add --document --quote --page`
  (the quote checked through the spec module's `anchor_quote`, handed across by the root),
  or added by hand. A feature step carries only the record's id, and a record has **one**
  instance: the Features panel's drag onto the canvas, the Type toggle, `feature set` and
  `step add --feature` all refuse a second in the same words. Toggling off shelves the
  marker like any aspect; deleting the step or `clear-steps` leaves the record unplaced —
  only the feature verbs create and remove records. A work step's briefing names the
  features it *flows into* (`scope.gatherers`); it carries no link of its own.
  `ARCHITECTURE.md`'s *A feature is a record, and a feature step is its instance* has the
  reasoning.
- **The topology is read before the graph is edited.** A project's topology (`dplanner
  topology set|show`; the Specs tab's pinned first row; `modules/spec.md`) says how its
  graph is shaped, and every CLI verb that reshapes a graph declares `edits_graph` on its
  `CliCommand` — `cli/gate.py` then refuses until `topology show` has recorded the current
  text's digest in the per-user `config_dir()/topology-read.json`, and refuses again when
  the text changes or when there is none. The skill marks those verbs; the window is never
  gated; the test suite's registry runs behind a gate with no record file. Declare it on a
  verb that changes shape, never on one that changes content. `ARCHITECTURE.md`'s *The
  topology is read before the graph is edited* has the reasoning.
- **A drop on the canvas is the third caller of `StepVerbs.create`.** `GraphView` accepts
  the mime types the composition root lists as `CanvasDrop`s on `ProjectEditorDeps`
  (`project_editor/drops.py`), records the point like a click and hands the payload up;
  the handler lives in the root because it reads one module's catalogue and births
  through another's `create_step`. A dropped feature is born **as the Feature template**
  — marker and estimate opt-out in the one command, the same set the template names, so
  the modal lights *Feature* and not the catch-all. Not a mode: Qt's drag events never
  reach the mouse handlers, and a drop has no state to leave.
- **The Edit menu's Cut, Copy, Paste, Duplicate, Delete and Select All are the graph's.**
  Registered by `project_editor` as ordinary `ActionSpec`s — no dispatcher until a second
  surface needs a clipboard, because a shortcut can be owned by one enabled QAction at a
  time. Cut/Copy/Duplicate act on `verbs.chosen_steps` exactly as Delete does; only Paste
  needs a current canvas. The Ctrl keys are **menu shortcuts** (every text widget reclaims
  them through `ShortcutOverride`; measured, not assumed) and Delete is **not** (a bare `Del`
  would fire in every list, and `StandardKey.Delete` also claims Ctrl+D). Deleting steps and
  regions no longer asks — undo is the safety net. A copy is a **clone**
  (`project_editor/clipboard.py`): fresh ids, links between copies remapped and every link
  to the outside dropped, files in the payload and written after the one composite
  command, and a `PastePolicy` per module with a say (`testing` re-mints ids,
  `step_agent_run` forgets, `feature` drops the marker — one instance per record).
  `dplanner step duplicate` is the same function.
  `ARCHITECTURE.md`'s *Edit verbs belong to the surface whose things they act on* and *Copy
  and paste are a clone through the same command* have the reasoning.
- **What a collector gathers is one verb: `dplanner scope show`.** In `cli/scopes.py`, the
  cross-feature home — a check, a feature and a milestone are one derivation asked three
  ways, so three near-copies of the report is exactly what that file prevents. It also owns
  `scope.gathers-nothing`, `scope.shared` and `scope.ungathered`. The marker modules keep
  only `set`/`clear`.
- **A test result is not a step status, and it gates nothing.** `pending/in-progress/done/
  blocked` is where the *work* stands; `ok/failed/skipped`/absent is what happened when
  somebody *ran* a test. No word is shared, on purpose. A failing test does not block a
  milestone and does not reach `progression()` — folding it in would make `dplanner
  progression show` answer a different question. `ARCHITECTURE.md`'s *A test result is not a
  step status* has the why.
- **A project has at most one open test run, and a run freezes its membership.** Starting one
  closes the last, which is what makes "mark these twelve ok" a pure function of the context
  — no hidden "which run", and a greyed verb that says *"start a test run first"*. A run
  stores the ids it was opened over, so a closed run cannot change meaning when the graph
  does; a missing result reads as pending, and the latest result is the newest run that
  actually recorded one. `ARCHITECTURE.md`'s *One open run per project* has the reasoning.
- **A module's project-level editor is a card, registered into `services.detail_cards`.**
  Same `InspectorSection` contract as a step tab, with a project id in `show_target`; the
  project panel renders the stack. Register before `project_editor` in `default_modules()` —
  the panel is built from whatever has registered by then. The agent instruction's card is
  the example; `ARCHITECTURE.md`'s *The project panel hosts the same contract, as cards*
  has the reasoning.
- **Repository facts are derived, never stored.** A project lives in its repository, so the
  repo root is `find_repo_root(project dir)` and the remote URL is git's own answer
  (`origin_url`) — both re-exported through `core/storage/locations.py`, the one import
  path allowed above the storage layer. Run Agent and the github module read them through
  seams wired by the composition root; never store a URL beside them. `ARCHITECTURE.md`'s
  *Repository facts are derived from the project's directory* has the reasoning.
- **The skill is generated, never written.** `dplanner skill install` renders `SKILL.md` and
  `reference.md` from the command registry, so they cannot describe a command that does not
  exist. Edit `cli/skill_preamble.md` for the hand-written half; never the output.
- **A cross-feature verb lives in `cli/`, fed by the composition root.** `cli/aspects.py`,
  `cli/lint.py` and `cli/authoring.py` are the examples: the verb owns the shapes and the
  report; a module contributes by exporting Qt-free pieces (an `AspectSpec`, a
  `lint_checks()`, a `step_author()`) from its own package, and `default_cli_commands()`
  assembles the list. `cli/` never imports a module. `ARCHITECTURE.md`'s *Lint belongs to
  no feature* and *Authoring a step is one verb, many modules* have the reasoning — the
  latter includes why the CLI transaction, not per-author rollback, is what makes a
  multi-module `step add` safe.

## Deliberate divergences from the template

`framework/` and `core/` came from app-framework, and in this application they are still ours
to evolve — but every change to them is a divergence somebody will one day diff against
upstream, and one nobody wrote down gets merged away by accident.

**If you change anything under `framework/` or `core/`, record it in `NOTES-FOR-APPFRAME.md`
in the same commit** — what you changed, why, and whether you think it belongs upstream. That
file is also where to put anything the framework taught us that is not a code change here:
a trap, a missing assumption, a number worth knowing. The point is that a later pass can carry
the good ones back to app-framework instead of rediscovering them.

`.appframe` records the commit we forked from, so `git -C ../app-framework diff <revision> --
template/` still shows what changed upstream since.
