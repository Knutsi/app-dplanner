# Data formats and how they change

A workspace is a folder of plain files that people share, keep in version control, and open
with builds of the application that are not all the same age. That makes the on-disk format
a public contract, and this document is the contract's rules.

There are **two independent version axes**, and keeping them independent is the whole idea:

| Axis | Covers | Version lives in | Owned by |
|---|---|---|---|
| Plan format | the folder layout and the keys in `plan.json` / `task.json` | `plan.json`'s `"format"` | `domain/migrations.py` |
| Module data | each `modules/<module_id>.json`, opaque to the store | the file itself, `"format"` (absent = 1) | the module that writes it |

A module changing its own JSON never bumps the plan format, and `domain/` never learns a
module's schema. **Whoever owns a piece of data owns its history.**

## Where a value goes

Three places, and the choice is not stylistic:

| Where | What | Mechanism | Travels with the workspace? |
|---|---|---|---|
| The workspace | content, and anything a collaborator should see | your model, or `module_data` | yes — it is in the files, and in the commits |
| Per user, per machine | preferences: window sizes, model choices, what was open | `framework/user_config.py` | no |
| The OS keychain | credentials, API keys | `framework/secrets_store.py` | no, and never on disk |

If you are unsure, ask who the value belongs to. A colleague opening the workspace should
see the project's conventions and none of your preferences.

## The plan format

One directory per task, nested exactly like the plan — `plan.json` at the root, `task.json`
below it, with `description.md`, `notes.md` and `modules/` beside each. Three conventions,
and each one is a lesson about diffs:

- **Ordering lives in the parent's `children` list**, never in `01-`/`02-` filename prefixes.
  Reordering two things is then a one-line JSON diff instead of a mass rename.
- **A folder name is frozen at creation** and never follows a retitle. Identity is the id;
  the folder name is presentation. Renaming a folder churns history for no benefit.
- **Absence encodes the default.** A task at its default status writes no `status` key, an
  unestimated one writes no `estimate_days`, and an empty `description.md` is deleted rather
  than written blank — so a diff shows exactly the tasks whose plan actually changed.

One more rule specific to this format: **numeric fields are normalised before they are
stored.** `estimate_days` is coerced to `float` at the model boundary, because an int would
write as `5` where a reloaded float writes as `5.0` — making the file's bytes depend on
whether the plan had been reopened since it was created.

### Changing it

The chain lives in `domain/migrations.py` and the engine in `core/formats.py`. DPlanner is
at format 1, so the chain is still empty.

1. **Append a `Migration` to the end of the tuple.** `current_version` is derived from the
   chain, so that edit *is* the version bump.
2. **Never edit an existing migration.** A folder written by version 1 still walks the
   entire chain, and each step's output is the next step's input. Editing step 2 silently
   changes what step 3 receives from every old workspace on every machine — including ones
   you will never see. If step 2 was wrong, fix it by appending step 4.
3. **Two hooks, for two different jobs.** `node` runs per node as it loads, with the raw
   dict it came from, so it can reach keys the model no longer has fields for. `whole` runs
   once over the finished aggregate, for anything that needs to see the shape.
4. **Migrate once, at open, then save the whole workspace.** Never leave a half-migrated
   folder for a later partial autosave to finish.

A folder written by a *newer* build is refused outright rather than partly read, and never
written to. `UnsupportedFormatError.is_newer` distinguishes that from damage, because it is
not a problem with the data — the usual cause is a colleague's push or a branch switch.

## Module data

A module that wants to store something in the workspace writes to
`task.module_data["<module_id>"]`, which the store persists as
`<task>/modules/<module_id>.json`. A workspace-global value goes on the root. The store
treats the contents as opaque JSON and round-trips every `modules/*.json` by filename — so
**data belonging to a module this build does not have survives untouched**.

To version it, declare a format beside the module's persistence code and expose it as
`data_format`:

```python
DATA_FORMAT = ModuleDataFormat(MODULE_ID, version, migrations)
# invariant, checked in __post_init__: len(migrations) == version - 1
```

Two behaviours follow, and both matter once a workspace is shared:

- **Data newer than the module declares is left untouched and logged.** An older build keeps
  the workspace readable and never overwrites a newer build's data — that feature simply
  looks empty until the application is updated.
- **Writing nothing leaves nothing behind.** `stamped()` returns `{}` when the format stamp
  would be the only key, an empty entry removes the file, and the `modules/` directory goes
  when it empties.

### Retiring a module

Its successor's package carries the retired module's on-disk contract — its id, its final
format and a converter — as a `Takeover`. At open, the old entry is brought up to its final
format through the carried chain, converted, merged into the successor's entry, and removed.
The retired module's *code* is gone; only its data contract survives, in the package that
inherited it. Modules never import each other, and this is why they do not have to.
