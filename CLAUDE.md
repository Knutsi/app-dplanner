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
worth the twenty minutes. `ARCHITECTURE.md` here indexes what DPlanner added on top.

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
  user. `modules/agent_launch/settings_page.py` is the worked example.
- When you spot cleanup that reduces entropy without adding over-engineering or "magic",
  suggest it.
- Only add comments that carry durable value for future developers and agents. Otherwise,
  make the code self-documenting.
- `DESIGN.md` is the standard for all UI work here, and **Debug ▸ Design Examples**
  (`modules/debug/design_example_activity.py` and `design_rows_activity.py`, rendered under
  `docs/screenshots/f1-design-example/`) is what it looks like. Its *Primitives* table maps
  what you are building — a dialog, a table, a strip of verbs, a filter, a busy state, an
  empty page — to the primitive in `framework/` and the render to compare against; build
  from those, never by styling a surface by name, and run its *Bringing a surface up* over
  any surface you touch. `FORMAT.md` is the standard for
  anything that reaches disk. `docs/architecture/<area>.md` is where a rule's *reasoning*
  lives, one file per rules area (`ARCHITECTURE.md` is their index) — when you settle an
  architectural question, write the rule here (or in the `.claude/rules/` file whose paths
  cover it) and the why there, in the present tense, and have each point at the other. What
  it replaced goes in `docs/architecture/decisions.md`, dated. A decision that lives only in
  a commit message is one the next feature rediscovers.

## Checks — run all four before finishing any task

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q   # ALWAYS prefix the env var — see below
uv run ruff check      # lint (ruff format for formatting)
uv run mypy            # strict type checking, whole tree
uv run mypy --platform win32   # the same tree as Windows sees it
```

**`--platform win32` is a check, not a curiosity.** The application ships on Windows, and
almost none of the suite can run there from here, so the type checker is the only reader of
the Windows half — on Linux mypy skips a `sys.platform == "win32"` branch entirely.
Keeping it clean costs one habit: **compare `sys.platform` inline where you branch on the
platform**, never through a module constant, because mypy narrows on the comparison and a
constant is opaque to it (`core/storage/sparse.py` is the worked example).

On a machine whose shell already presets `QT_QPA_PLATFORM` (Arch with a tiling WM), the
`setdefault` in `tests/conftest.py` does not kick in and a bare `pytest` opens real
windows. Always prefix it. The same shell usually presets
`QT_QPA_PLATFORMTHEME=gtk3`, which `conftest.py` blanks for an offscreen run: with it every
worker initialises GTK and an offscreen window becomes active one event round late, so a
focus-dependent test passed one evening and failed every run the next morning. A headless
suite must not depend on the desktop's state.

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

**And it never opens a real terminal or agent CLI**: once a stub that stopped matching opened
real windows running `claude` against the suite's temp repositories. `tests/conftest.py`'s
`_no_real_spawns` fails a test that starts one, or anything detached; a test that runs a
*fake* agent CLI hands its path to `allow_spawn`. A test that hangs fails after 120 s
(`pytest-timeout`) with every thread's stack, so a hung worker cannot cost a night.

**Qt objects: what the crashes taught, as rules.** Each line is one the suite has died of.
The diagnoses, the recipes and the shiboken detail are the **`suite-crash` skill**
(`.claude/skills/suite-crash/SKILL.md`) — load it before debugging the test a crash named, because
a worker dying with SIGSEGV names an innocent one.

- **Never read a layout back** (`layout.itemAt(i)`): keep your own list of what you put in it
  (`framework/notices.py`'s `NoticeBar._rows`). `takeAt` in a loop that drops the wrapper each
  turn is fine.
- **Add a child layout to its parent before filling it**, and **never construct a
  `QLayoutItem` in Python** — `addStretch`/`addSpacing` instead.
- **A widget whose height depends on its width implements `heightForWidth`** and lets the layout
  ask; it never resizes itself in `resizeEvent`, and its `minimumSizeHint` is the least it can
  ever need — one row — never its `sizeHint` (`schedule/months.py`).
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

Bottom to top: `core/` → `domain/` → `planning/` → `cli/` → `framework/` → `modules/<name>/`
→ the composition root (`modules/__init__.py`) → `app.py` and `entry.py`.

**`core/` (storage, persistence contracts, signals) and `framework/` (everything Qt) came
from app-framework**; `domain/` (the graph and its store), `planning/` (status, readiness,
the schedule), `cli/` (the headless surface) and `modules/` (the features) are this
application. The framework is still ours to evolve — see *Deliberate divergences* below.

1. `core/` imports no Qt and nothing from the rest of the application.
2. `domain/` imports no Qt, and imports `core` only. It is tested with plain pytest.
3. `planning/` imports `core` and `domain` only. A status is a `planning.status.Status`,
   never a word — `docs/architecture/core.md`'s *Planning owns status*.
4. `cli/` imports no Qt and nothing above `planning/`. A module's `cli.py` and `aspect.py` are
   the same: importable without a graphics stack. The CLI is how an agent drives DPlanner,
   and it has to start in milliseconds on a machine with no GUI libraries at all.
5. `framework/` never imports `modules` or the entry points.
6. A module reaches another only through its headless `aspect.py` (facts) or `workflows.py`
   (a verb returning a `Change`) — or any file of a package with no `module.py`, which is
   headless all through (`modules/agent_briefing`). Only `modules/__init__.py` imports the
   rest. `docs/architecture/core.md`'s *What holds the tier and the workflows in place*.
7. Modules never import `AppServices`, the builder, or the concrete window. Window
   capabilities come through the protocols in `framework/window.py`.
8. `app.py` and `entry.py` import the composition root and nothing deeper.
9. Only `core/storage/` and the composition root name a *concrete* storage provider.
   Everything else depends on the protocols in `core/storage/provider.py` — which is what
   keeps the application runnable against a folder, a git checkout or a GitHub clone without
   a single `if` anywhere in a feature.

## Two surfaces, one vocabulary

A menu action and a `dplanner` verb build the **same object from `domain/commands.py`**. The
GUI pushes it onto the undo stack; the CLI applies it and lets the store flush. That one rule
is what keeps the surfaces from drifting: anything the CLI can do is undoable in a window,
and neither can grow a behaviour the other lacks without somebody editing that file.
**A whole verb is a workflow**: a `workflows.py` function returns a `Change`; each surface
applies its command as one command, persists it, and only then performs the follow-ups
(`CliContext.after_flush`; after the gesture) — each attempted, failures reported, never
rolled back (`docs/architecture/core.md`'s *A workflow is one function under both surfaces*).

It follows that a feature has two halves in one package:

```
modules/<name>/
├── module.py    the Qt half: the module class, its Deps, its views
├── cli.py       the headless half: CliCommand specs                ← imports no Qt
├── aspect.py    for a step aspect: SPEC, DATA_FORMAT, read/write    ← imports no Qt
├── report.py    what it says in a report: report_source()           ← imports no Qt
├── harness.py   for an agent CLI provider: HARNESS, and nothing else  ← imports no Qt
├── roles.py     the location role it acts on (spec, reporting): ROLE   ← imports no Qt
├── checks.py    what this machine needs for it: checks()              ← imports no Qt
├── themes.py    for a theme provider: the ThemeProvider it offers        ← imports no Qt
└── section.py   the editor it puts in the step detail panel (Step Details…)
```

**A Qt file's name says its role** (architecture rule 15): `activity.py` or `<x>_activity.py`
holds a tab, `dialog.py` or `<x>_dialog.py` a modal, `scene.py` a `QGraphicsScene`,
`panel.py` a side panel, `status_widget.py` a status-bar widget, `settings_page.py` a
settings page — and nothing is `view.py`. `docs/architecture/core.md`'s *A file name has one
meaning*.

The Qt-free files are checked by **path** — `HEADLESS_ROLES`, and per package
`HEADLESS_FILES`, in `tests/test_architecture.py`. If the composition root reaches a new file
at CLI time, list it there; a file the rule cannot see is a rule that is only a habit.

## How to add a feature module

1. Create `modules/<name>/` with a `module.py` defining a frozen `<Name>Deps` dataclass —
   exactly the services and capabilities the module needs, no more — and a `<Name>Module`
   class: `__init__(self, deps)` stores them, and a no-argument `register()` does all the Qt
   work (activities via `deps.tabs.register_factory`, actions via `deps.actions.register`,
   an index folder via `deps.segments.register`).
2. Menu placement: every `ActionSpec` names a `menu` and a `group` from `MENU_STRUCTURE` in
   `menus.py`; `order` ranks only within the group (10/20/30…). Separators between groups
   are automatic. **Add a group rather than smuggling structure into `order`.**
3. Another module's facts come from its `aspect.py`, a whole verb from its `workflows.py`, a
   planning fact from `planning/`. Anything else, and anything effectful, is a typed
   callback — or a small consumer-owned `Protocol` — on your own `Deps`, wired in
   `modules/__init__.py`. `modules/canvas/module.py` is the worked example: it
   names the panel interface it needs and is handed a factory.
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
   **A panel that belongs to one tab is a `SidePanel` the tab hosts** through
   `framework/side_panel.py`, never a `PanelSpec` (`shell-ui.md`).
7. If it has verbs, add `cli.py` with a `commands()` function returning `CliCommand`s, and
   list it in `default_cli_commands()`. Keep it Qt-free. When `commands()` needs a
   cross-module fact, take it as a **keyword-only parameter and close over it in one inner
   wrapper** — `modules/status_board/cli.py` is the worked example; don't invent a fifth
   injection style.
8. Construct it in the root's builder for its cluster (`_agents`, `_graph`, `_aspects`, …) and
   list it in `default_modules()`. **List order is registration order and it matters** —
   status-bar widget order, index folder order, and whether a surface exists before whoever
   renders it is built. Put a comment on any position that is constrained.
9. Leave the package `__init__.py` as a docstring — the composition root imports
   `from dplanner.modules.<name>.module import <Name>Deps, <Name>Module`. Re-exporting the
   Qt half there would make the package's Qt-free files unreachable without loading Qt, and
   the CLI reaches them through this package. Add tests under `tests/modules/<name>/`; keep
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
`docs/architecture/core.md`'s *The rulebook is loaded by where you work* has the measurements and
the reasoning.

| Area file | What it covers |
|---|---|
| `canvas.md` | the graph editor's modes, gestures, cards and marks |
| `shell-ui.md` | seams, panes, primitives, menus, toolbars, glyphs and themes |
| `step-panel.md` | aspect toggles, the shelf, Details blocks, prose editors and assets |
| `agents.md` | Run Agent, worktrees, run directories, usage, harnesses, profiles and reviews |
| `specs.md` | the spec editor and its document sources |
| `schedule.md` | order, progression, time estimates, progress and milestone colour |
| `collectors.md` | scopes, features, citations, tests, documentation and notes |
| `persistence.md` | save, two writers, outside changes, reload and repositories |
| `cli.md` | the entry word, install, the checklist, the topology gate, the skill and reports |
| `runtime.md` | telemetry, diagnostics, discarding a build, LLM calls and dictation |
| `graph-model.md` | edges, auto-progress links, step numbers and isolation |
| `playbooks.md` | stages, gates, loop-back, presets, the step's playbook and headless invocations |

## The one chain every change follows

**`action(context) → command → model → signal → views`.** A gesture is not a special case — a
canvas drop runs the same `ActionSpec` the menu does, so the verb exists in the palette too and
can be tested by handing it a constructed `Context` with no widget in sight. Every model change
is a command on the single undo stack carrying an `origin`; nothing pushes an update at a view —
the model emits, each view decides what to redraw, and the `origin` is how the view that caused
the change ignores its own echo. `docs/architecture/core.md`'s *How a gesture becomes a change
on screen* has the diagram and why each link is there — read it before adding a surface that
changes anything. The mechanics of each link are area rules now: the context and its
announcing (`shell-ui.md`), commands and legal edges (`graph-model.md`), threads, `TaskRunner`
and coalesced views (`runtime.md`), derived facts (`schedule.md`).

## Deliberate divergences from the template

`framework/` and `core/` came from app-framework, and in this application they are still ours
to evolve — but every change to them is a divergence somebody will one day diff against
upstream, and one nobody wrote down gets merged away by accident.

**If you change anything under `framework/` or `core/`, record it in `NOTES-FOR-APPFRAME.md`
in the same commit, under that file's own heading** (`` ## `framework/tabs.py` ``; a new file
gets a new heading in path order) — what differs from the template *now*, why, and whether it
belongs upstream. Rewrite the entry rather than appending to it: the file answers "what differs
in this file?", and its history is git's. A trap, a missing assumption or a number worth
knowing that is not a code change goes under *Lessons*. The point is that a later pass can
carry the good ones back to app-framework instead of rediscovering them.

`.appframe` records the commit we forked from, so `git -C ../app-framework diff <revision> --
template/` still shows what changed upstream since.
