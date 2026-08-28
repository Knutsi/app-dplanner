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
- **Double-clicking a step anywhere runs `steps.details`** — a modal dialog hosting a second
  `StepPanel`, disposed on close. It is the one gesture across canvas, order, progression and
  estimates; a table runs it against a context naming exactly the row's step. Reveal-in-graph
  is the `steps.reveal` verb in the Step menu, not a double-click. `ARCHITECTURE.md`'s *The
  same panel, briefly modal* has the reasoning.
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
  it does. That one check also makes a lock between CLI runs unnecessary.
- **Reloading the library is a full rebuild**, not a reset. Registries refuse duplicate
  ids, which is what makes that the only implementable answer — and the correct one.
  Opening a *different* library is not even a reload: File ▸ New/Open Project Library
  spawns a detached instance (`modules/library/module.py::spawn_instance`).
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
  `build_menu`'s `submenu` filter). Make the thing under the cursor
  current *first*, then build; the menu then reads the same context every other presenter does.
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
- **Editing a spec in-app is a replace.** The Specs tab's markdown editor flushes a session
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
  (`status set`, `handoff set`). `ARCHITECTURE.md`'s *Running an agent launches a peer, not
  a task* has the reasoning.
- **Inherited handoffs are computed, never stored** — `step_handoff/handoff.py` is one
  function with three readers (tab, CLI, agent prompt). Same rule as the ordering, and the
  reasoning is in `ARCHITECTURE.md`'s *Pass-forward is derived at read time*.
- **Progression is derived, never stored** — `domain/progression.py` is the graph's
  readiness with a `status_for(step)` handed in like `days_for`; the board, `dplanner
  progression show` and `--json` are three readers of one function, and the frontier is a
  per-step check, not `ordering.ready()`'s wave one. `ARCHITECTURE.md`'s *Progression is
  the status-aware frontier* has the partition rules and why each was a decision.
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
