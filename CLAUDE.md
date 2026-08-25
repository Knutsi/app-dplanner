# Working on DPlanner

DPlanner is a **development planner**. It plans a *product* — one codebase, its repository,
and the work planned against it — and it is meant to be driven by a coding agent as readily
as by a person.

```
Product  ── the system level: a name, a repository URL, a checkout. One per window.
└── Project  ── a unit of work with a beginning and an end
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
- When you spot cleanup that reduces entropy without adding over-engineering or "magic",
  suggest it.
- Only add comments that carry durable value for future developers and agents. Otherwise,
  make the code self-documenting.
- `DESIGN.md` is the standard for all UI work here. `FORMAT.md` is the standard for anything
  that reaches disk.

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
├── cli.py       the headless half: CliCommand specs             ← imports no Qt
└── aspect.py    for a step aspect: SPEC, DATA_FORMAT, read/write ← imports no Qt
```

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
   `modules/__init__.py`. Never import the other module.
4. If it stores data, declare `data_format = ModuleDataFormat(...)` on the class and read
   `node.module_data[MODULE_ID]`; prose goes in `node.module_text[MODULE_ID]` and files in
   `store.files(node_id, MODULE_ID)`. See `FORMAT.md`.
5. If it has verbs, add `cli.py` with a `commands()` function returning `CliCommand`s, and
   list it in `default_cli_commands()`. Keep it Qt-free.
6. Construct it in `default_modules()`. **List order is registration order and it matters** —
   status-bar widget order, index folder order, and whether a surface exists before whoever
   renders it is built. Put a comment on any position that is constrained.
7. Leave the package `__init__.py` as a docstring — the composition root imports
   `from dplanner.modules.<name>.module import <Name>Deps, <Name>Module`. Re-exporting the
   Qt half there would make the package's Qt-free files unreachable without loading Qt, and
   the CLI reaches them through this package. Add tests under `tests/modules/`; keep
   `README.md`'s layout map current.

If you find yourself needing to edit a file outside your own package and the composition
root, stop and look for the registry or capability you have not found yet.

## Mechanical facts worth knowing

- **There is no Save-file action.** Autosave writes 1.5 s after the last change; *Save*
  means recording a version, and it only exists when the storage provider has a history. The
  CLI has no timer: a run is a transaction that flushes once, at the end, and writes nothing
  if the verb failed.
- **Every model change goes through a command** on the single undo stack, and carries an
  `origin` so the view that made the edit can ignore its own echo.
- **Two writers are expected.** An agent runs `dplanner` against a folder a window has open.
  The store records what it last read or wrote and **refuses to flush over anything that
  changed underneath** (`StaleWorkspaceError`); the window notices and reloads when it owes
  nothing, and says so when it does. That one check also makes a lock between CLI runs
  unnecessary.
- **Opening a different workspace is a full rebuild**, not a reset. Registries refuse
  duplicate ids, which is what makes that the only implementable answer — and the correct one.
- **Blocking work runs through `TaskRunner`**, never on the GUI thread: storage operations,
  LLM calls, anything that touches the network. It appears in the task centre for free.
- **An edge lives on the step that waits**, is validated against the project, and is
  deliberately *not* rewritten when a step is deleted — undo has to restore the graph
  exactly. `Product.requires()` skips ids it cannot resolve. Edge kinds this build does not
  know are loaded and written back untouched.
- **A module that writes a number owes it a `float`.** An `int` writes as `5` where a
  reloaded float writes as `5.0`, making a file's bytes depend on whether the workspace had
  been reopened. `module_data` is opaque to the model, so the coercion belongs in the
  aspect's `write()` — see `modules/step_estimation/aspect.py`.
- **The skill is generated, never written.** `dplanner skill install` renders `SKILL.md` and
  `reference.md` from the command registry, so they cannot describe a command that does not
  exist. Edit `cli/skill_preamble.md` for the hand-written half; never the output.

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
