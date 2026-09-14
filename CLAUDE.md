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
- `DESIGN.md` is the standard for all UI work here, and **Debug ▸ Design Example…** with its
  table tab (`modules/debug/design_example.py`, rendered under
  `docs/screenshots/f1-design-example/`) is what it looks like. Its *Primitives* table maps
  what you are building — a dialog, a table, a strip of verbs, a filter, a busy state, an
  empty page — to the primitive in `framework/` and the render to compare against; build
  from those, never by styling a surface by name, and run its *Bringing a surface up* over
  any surface you touch. `FORMAT.md` is the standard for
  anything that reaches disk. `ARCHITECTURE.md` is where a rule's *reasoning* lives — when
  you settle an architectural question, write the rule here (or in the
  `.claude/rules/` file whose paths cover it) and the why there, and have each point at the
  other. A decision that lives only in a commit message is one the next
  feature rediscovers.

## Checks — run all four before finishing any task

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q   # ALWAYS prefix the env var — see below
uv run ruff check      # lint (ruff format for formatting)
uv run mypy            # strict type checking, whole tree
uv run mypy --platform win32   # the same tree as Windows sees it
```

**`--platform win32` is a check, not a curiosity.** The application ships on Windows, and
almost none of the suite can run there from here, so the type checker is the only reader we
have of the Windows half — mypy skips a `sys.platform == "win32"` branch entirely on Linux,
so that code is otherwise read by nobody until somebody runs it. It takes thirty seconds and
it found four real errors the day it was first run. Keeping it clean costs one habit:
**compare `sys.platform` inline where you branch on the platform**, never through a module
constant, because mypy narrows on the comparison and a constant is opaque to it
(`modules/spec_git/client.py` is the worked example).

On a machine whose shell already presets `QT_QPA_PLATFORM` (Arch with a tiling WM, for
instance), the `setdefault` in `tests/conftest.py` does not kick in and a bare `pytest`
opens real windows all over the workspace. Always prefix it. The same shell usually presets
`QT_QPA_PLATFORMTHEME=gtk3`, which `conftest.py` blanks for an offscreen run: with it every
worker initialises GTK — eight threads and a live compositor connection — and an offscreen
window becomes active one event round late, so a focus-dependent test
(`test_the_editor_ignores_the_echo_of_its_own_write_while_editing`) passed one evening and
failed every run the next morning. A headless suite must not depend on the desktop's state.

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

**Qt objects: what the crashes taught, as rules.** Each line is one the suite has died of.
The diagnoses, the recipes and the shiboken detail are the **`suite-crash` skill**
(`.claude/skills/suite-crash/SKILL.md`) — load it before debugging the test a crash named, because
a worker dying with SIGSEGV names an innocent one.

- **Never read a layout back** (`layout.itemAt(i)`): keep your own list of what you put in it
  (`StatusColumn._held`, `MilestoneList._rows`). `takeAt` in a loop that drops the wrapper each
  turn is fine.
- **Add a child layout to its parent before filling it**, and **never construct a
  `QLayoutItem` in Python** — `addStretch`/`addSpacing` instead.
- **A widget whose height depends on its width implements `heightForWidth`** and lets the layout
  ask; it never resizes itself in `resizeEvent`, and its `minimumSizeHint` is the least it can
  ever need — one row — never its `sizeHint` (`time_estimates/months.py`).
- **A worker thread never holds the last reference to a Qt object**: any hand-written
  thread-plus-signal goes through `TaskRunner`.
- **A test that builds a top-level widget of its own disposes it with `deleteLater`**, and a
  headless script that copies clears the clipboard before it returns
  (`scripts/measure_scaling.py`'s `discard`).
- **To make a lifetime bug fault where it happens**, poison freed memory:
  `MALLOC_PERTURB_=165 QT_QPA_PLATFORM=offscreen uv run pytest -q` (macOS: `MallocScribble=1`).

**A test asserts what the code produced, in the terms the code produced it.** An expected
string carrying a path, a separator or a quoting is built from the *same object the test
handed in* and run through the *same formatter production used* (`shlex.quote`,
`_exec_quote`) — never retyped in one platform's spelling. Nearly every Windows failure in
the suite was an assertion that rebuilt a path as an f-string with `/` in it, and the fix is
not a skip: comparing against the `Path` that went in is portable **and** a better test,
because it stops duplicating the value under test. A platform mark goes only on a test whose
whole subject is that platform's own concept or a capability the host may not have — a POSIX
mode bit, making a symlink — and it is phrased as the **capability**, in `tests/platforms.py`,
so it switches itself on when a Windows developer enables Developer Mode. There are five in
the whole suite. When the code itself reads `sys.platform`, the answer is neither: give it a
`platform` argument with a default, as `cli/desktop.py`'s `launcher_for` does.

**The Windows check is a disposable target, run by hand.** `scripts/windows_check.py` is the
one command; `scripts/windows/README.md` is the recipe. It targets the developer's own
Omarchy VM by default — installed, persistent, and driven through its shared folder by
`runner.ps1`, because adding a port would mean recreating a container that is not this
check's to recreate — or `--target box`, a throwaway `dockurr/windows` container on ports
nothing else uses. There is deliberately **no CI**: Windows is checked rarely, on purpose, and
`mypy --platform win32` above is the cheap guard that runs on every machine in between. Never
leave a VM running for a check, and `clean` gives the disk back.

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
├── report.py    what it says in a report: report_source()           ← imports no Qt
├── harness.py   for an agent CLI provider: HARNESS, and nothing else  ← imports no Qt
├── checks.py    what this machine needs for it: checks()              ← imports no Qt
├── themes.py    for a theme provider: the ThemeProvider it offers        ← imports no Qt
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

## Rules by area: the rest of the rulebook loads where you work

**This file is the core — the rules that bind an edit anywhere in the tree.** Every rule about
one area lives in `.claude/rules/<area>.md`, whose `paths:` name the files it governs, and Claude
Code loads it the moment you read one of them: the canvas's rules arrive with the first canvas
file you open, and a report change never carries them. Three things no path trigger reaches, and
what reaches them:

- **A plan is written before the files are read** — and the Explore and Plan subagents do the
  reading for you. Before writing one, run `uv run python scripts/rules.py for <paths you expect
  to touch>` and read what it prints.
- **An edit made through the shell, a `cat`, and a brand-new file load nothing.** Before you
  finish, run `uv run python scripts/rules.py diff` and reread every rule it prints against the
  change.
- **An agent CLI other than Claude Code never reads `.claude/rules/`**, so those two commands are
  its only way in (`AGENTS.md` says so).

**A new rule goes in the area file whose paths cover what it governs**, and in this file only
when it binds edits no one area's paths reach — so adding to the core means trimming it:
`tests/test_rules.py` holds it under 32 KiB, and claims every module package for an area.
`ARCHITECTURE.md`'s *The rulebook is loaded by where you work* has the measurements and the
reasoning.

| Area file | What it covers |
|---|---|
| `canvas.md` | the graph editor's modes, gestures, cards and marks |
| `shell-ui.md` | seams, panes, primitives, menus, toolbars, glyphs and themes |
| `step-panel.md` | aspect toggles, the shelf, Details blocks, prose editors and assets |
| `agents.md` | Run Agent, worktrees, run directories, usage, harnesses and profiles |
| `specs.md` | the spec editor and its document sources |
| `schedule.md` | order, progression, time estimates, progress and milestone colour |
| `collectors.md` | scopes, features, citations, tests, documentation and notes |
| `persistence.md` | save, two writers, outside changes, reload and repositories |
| `cli.md` | the entry word, install, the checklist, the topology gate, the skill and reports |
| `runtime.md` | telemetry, diagnostics, discarding a build, LLM calls and dictation |
| `graph-model.md` | edges, step numbers and isolation |

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
- **Double-clicking a step anywhere runs `steps.details`** — a modal dialog hosting a second
  `StepPanel`, disposed on close. It is the one gesture across canvas, order, progression and
  estimates; a table runs it against a context naming exactly the row's step. Reveal-in-graph
  is the `steps.reveal` verb in the Step menu, not a double-click. `ARCHITECTURE.md`'s *The
  same panel, briefly modal* has the reasoning.
- **A canvas key names action ids; it is never an `ActionSpec.shortcut`.** A bare `h` on a
  menu-bar QAction fires application-wide and eats a keystroke in the step editor. Bind it in
  `modules/project_editor/keymap.py`, where a key names the verbs it means in order and the
  first the context allows runs — that is how one Delete key covers links and steps.
- **A painter never trusts `option.palette`.** Qt fills `QStyleOptionGraphicsItem.palette`
  once, when the scene is created, and never refreshes it, so every canvas item kept the
  colours of whatever theme its tab opened in. `items.live_palette()` is the only source of
  colour on the canvas. Its cousin: **a colour copied out of the palette onto a widget goes
  stale** — `TabHost` tints its tab titles, so it re-tints on `QEvent.PaletteChange`. If a
  surface stores a colour, it owes that hook.
- **Work may leave the GUI thread; mutation may not.** `core.signals.Signal` is synchronous
  and has no thread affinity, so the model is only ever changed on the GUI thread. Anything
  computed off it returns through `TaskRunner`, the one place that uses real Qt signals.
- **A view of one project hears that project's changes, and a rebuild is coalesced.** A tab
  subscribes through `follow_project(library, project_id, changed)` (`framework/activity.py`;
  `follow_target` for a panel section whose step moves), which asks the model's
  `belongs_to` about the node each signal names — a rename in project B is nothing for
  project A's table to redraw for. What it calls is a `Debounced` (`framework/debounce.py`):
  `trigger()` restarts a single-shot timer, so a burst runs the rebuild once, over the latest
  state, and nothing queues — the canvas at 0 ms (once per event-loop turn, so a title still
  lands on its node as it is typed), tables and lists after `SETTLE_MS` (300 ms), the Time tab
  after 500 ms. **Tests run in immediate mode**: the `session` fixture sets
  `services.debounce.set_immediate(True)`, so every trigger runs inline and a test asserts on
  a view the line after a push exactly as before; the deferred path is tested once with real
  timers and once per view by switching it off and calling `flush_all()`. Never
  `qtbot.wait` for a rebuild. **A settle behind a modal waits for it**: one owned outside
  the active modal re-arms rather than runs, so typing in Step Details rebuilds nothing
  behind it; a 0 ms run never waits (`ARCHITECTURE.md`'s *A settle behind a modal waits
  for it*).
  **And a coalesced view says that a rebuild is owed**: an
  `UpdatingIndicator` (`framework/signalling.py`) at the right end of the strip — the
  caption row, in a view with no strip — `follow()`ing the view's one `Debounced`, whose
  `pending_changed` settles on a rebuild that raised as much as one that returned. Wire it
  where the `Debounced` is built; never show and hide a label by hand. **It is a turning
  arc and no words** — the same `Spinner` a working button turns, which drives a button's
  glyph slot or a bare `QLabel` that is one; *something is running here* is one motion to
  recognise, not a word in one place and a glyph in another. Never move a derivation to a worker thread for speed: it is
  pure Python competing for the GIL, and a thread alive at teardown is the suite's SIGSEGV
  shape — `ARCHITECTURE.md`'s *A view refresh is coalesced, and hears one project* has the
  measurements (67 ms → 0.3 ms of synchronous work per keystroke with seven tabs open).
- **The context is announced once per event-loop turn, and a gesture changes the
  selection once.** `ContextService.set_scope`/`clear_scope`/`refresh` update the snapshot
  synchronously — `current()` is always true, which is all a verb run right after a
  publish reads — but the fan-out to every action state, toolbar, panel and the menu bar
  goes through `announce`, a 0 ms `Debounced` the builder wires, so a gesture that
  publishes seven times costs one re-evaluation over the final state and never shows a
  panel a selection that was empty for a microsecond. Three rules keep it that way:
  `GraphScene.select_steps` announces once (it reconciles Qt's selection item by item
  behind a `_reselecting` guard); a verb that needs a selection the user did not make is
  handed a **constructed `Context`** (`_on_link_requested`) rather than having the canvas
  select for it; and **a panel that steps aside keeps its content** (`ProjectPanel`
  returns False for a selected step without clearing its cards — clearing tore down and
  rebuilt every card twice per gesture). **No subprocess in an action state or a structure
  listener**: `origin_url` is memoised on the config file's mtime, and the sync module
  asks git about membership only when the *library's* children change. **And no walk
  over a project in an action state**: a state runs on every announce, so a derivation
  over every step is paid per keystroke — *Compile Out of Date*'s label once re-walked
  every collector's cone on each one (198 ms at 400 steps, from a flat 4). The pattern
  is the Problems count's: the module settles the answer once per burst in a `Debounced`
  and the state *reads* it (`DocsModule._frontier_of`), with the settle announcing the
  context so the label catches up; the gesture itself computes fresh. Measured on a
  74-step, 344-note plan: connect 1.7 s → tens of ms, paste 0.6 s → tens of ms; the
  suite runs the debounce service immediate, so a test that asserts coalescing switches
  it off and `flush_all()`s. `scripts/measure_scaling.py --scenarios connect,paste` is the number to
  quote. `ARCHITECTURE.md`'s *The context is announced once per turn* has the reasoning.
- **Every model change goes through a command** on the single undo stack, and carries an
  `origin` so the view that made the edit can ignore its own echo. Two kinds of change
  bypass the stack, never the vocabulary: an external fact (the bullet below) and
  **reading disk** — `load`, membership, and the store adopting another writer's change —
  which apply the library's mutators directly with an origin of their own.
- **A background sync of an external fact applies its command directly, off the undo
  stack, with its own origin** — undoing the user's edit must never restore a stale PR
  state instead. `modules/github/refresh.py` is the example; `ARCHITECTURE.md`'s *Syncing
  an external fact* has the reasoning.
- **Blocking work runs through `TaskRunner`**, never on the GUI thread: storage operations,
  LLM calls, anything that touches the network. It appears in the task centre for free.
  The one documented exception — storage operations that rewrite the working tree, which
  must complete before the app touches anything else — is `ARCHITECTURE.md`'s *Storage
  operations that rewrite the working tree are synchronous*.
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
