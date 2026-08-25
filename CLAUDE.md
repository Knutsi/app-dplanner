# Working on DPlanner

Built from [app-framework](https://github.com/Knutsi/app-framework). The architecture — what
a module is, how features cooperate without importing each other, where state lives — is
documented in that repo's `docs/index.html`. Read it once before adding a feature; it is
worth the twenty minutes.

## Engineering principles

- Review every change for over-engineering before finishing. Prefer simple code over type
  magic.
- Get a good overview of the relevant code before editing. Prevent entropy increase: prefer
  refactoring existing code to cover a new case over adding a special case, if that lowers
  total entropy.
- When you spot cleanup potential that reduces entropy without adding over-engineering or
  "magic", suggest it.
- End every task by taking the view of a new developer or agent seeing the code fresh: is
  the separation of concerns easy to understand? Are the directory structure, file names and
  module contents self-documenting?
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

Bottom to top: `core/` → `domain/` → `framework/` → `modules/<name>/` → the composition root
(`modules/__init__.py`) → `app.py`.

**Two of these are given to you and two are yours.** `core/` (storage, persistence
contracts, signals) and `framework/` (everything Qt) come from the template and are the same
in every application built from it. `domain/` (your model and its repository) and `modules/`
(your features) are what makes this application itself.

1. `core/` imports no Qt and nothing from the rest of the application.
2. `domain/` imports no Qt, and imports `core` only. It is tested with plain pytest.
3. `framework/` never imports `modules` or `app`.
4. Modules never import each other. Only `modules/__init__.py` may import them all.
5. Modules never import `AppServices`, the builder, or the concrete window. Window
   capabilities come through the protocols in `framework/window.py`.
6. `app.py` imports the composition root and nothing deeper.
7. Only `core/storage/` and the composition root name a *concrete* storage provider.
   Everything else depends on the protocols in `core/storage/provider.py` — which is what
   keeps the application runnable against a folder, a git checkout or a GitHub clone without
   a single `if` anywhere in a feature.

## How to add a feature module

1. Create `modules/<name>/` with a `module.py` defining a frozen `<Name>Deps` dataclass —
   exactly the services and capabilities the module needs, no more — and a `<Name>Module`
   class: `__init__(self, deps)` stores them, and a no-argument `register()` does all the Qt
   work (activities via `deps.tabs.register_factory`, actions via `deps.actions.register`).
2. Menu placement: every `ActionSpec` names a `menu` and a `group` from `MENU_STRUCTURE` in
   `menus.py`; `order` ranks only within the group (10/20/30…). Separators between groups
   are automatic. **Add a group rather than smuggling structure into `order`.**
3. If the module needs something another module provides, declare a typed callback — or a
   small consumer-owned `Protocol` — on your own `Deps`, and wire it in
   `modules/__init__.py`. Never import the other module.
4. If it stores data, declare `data_format = ModuleDataFormat(...)` on the class and read
   `task.module_data[MODULE_ID]`. See `FORMAT.md`.
5. Construct it in `default_modules()`. **List order is registration order and it matters** —
   status-bar widget order, sidebar page order, and whether a surface exists before whoever
   renders it is built. Put a comment on any position that is constrained.
6. Re-export the module and its `Deps` from the package `__init__.py`; add tests under
   `tests/modules/`; keep `README.md`'s layout map current.

If you find yourself needing to edit a file outside your own package and the composition
root, stop and look for the registry or capability you have not found yet.

## Mechanical facts worth knowing

- **There is no Save-file action.** Autosave writes 1.5 s after the last change; *Save*
  means recording a version, and it only exists when the storage provider has a history.
- **Every model change goes through a command** on the single undo stack, and carries an
  `origin` so the view that made the edit can ignore its own echo.
- **Opening a different workspace is a full rebuild**, not a reset. Registries refuse
  duplicate ids, which is what makes that the only implementable answer — and the correct one.
- **Blocking work runs through `TaskRunner`**, never on the GUI thread: storage operations,
  LLM calls, anything that touches the network. It appears in the task centre for free.
- **A phase's status and estimate are derived**, never stored: `Task.is_done()` and
  `rolled_up_estimate()` read the children. Anything that offers to set them on a phase is a
  way for the plan to start disagreeing with itself.
- **Dependencies live on the task that waits**, are validated against the tree, and are
  deliberately *not* rewritten when a task is deleted — undo has to restore the plan
  exactly. `Plan.blockers()` skips ids it cannot resolve.
- **`estimate_days` is coerced to float at the model boundary.** An int would write as `5`
  where a reloaded float writes as `5.0`, making a plan's bytes depend on whether it had been
  reopened. Any numeric field you add needs the same treatment.
