# Data formats and how they change

A workspace is a folder of plain files that people share, keep in version control, and open
with builds of the application that are not all the same age — and, in DPlanner, that a
coding agent writes to through the CLI while somebody has a window open on it. That makes
the on-disk format a public contract, and this document is the contract's rules.

There are **two independent version axes**, and keeping them independent is the whole idea:

| Axis | Covers | Version lives in | Owned by |
|---|---|---|---|
| Product format | the folder layout and the keys in `product.json` / `project.json` / `step.json` | `product.json`'s `"format"` | `domain/migrations.py` |
| Module data | each `modules/<module_id>.json`, opaque to the store | the file itself, `"format"` (absent = 1) | the module that writes it |

A module changing its own JSON never bumps the product format, and `domain/` never learns a
module's schema. **Whoever owns a piece of data owns its history.**

## Where a value goes

Three places, and the choice is not stylistic:

| Where | What | Mechanism | Travels with the workspace? |
|---|---|---|---|
| The workspace | content, and anything a collaborator should see | your model, or `module_data` / `module_text` / a module file area | yes — it is in the files, and in the commits |
| Per user, per machine | preferences: window sizes, model choices, what was open | `framework/user_config.py` | no |
| The OS keychain | credentials, API keys | `framework/secrets_store.py` | no, and never on disk |

If you are unsure, ask who the value belongs to. A colleague opening the workspace should
see the project's conventions and none of your preferences.

**One deliberate exception.** `Product.checkout` — where *this* machine has the product's
repository cloned — is a per-machine value and is stored in the workspace anyway. The CLI
has to resolve it, `framework/user_config.py` is QSettings, and the CLI is below the
framework and loads no Qt. Storing it is the honest trade; if it turns out to churn in
shared repositories the fix is a Qt-free per-user config in `core/`, not a hidden field.

## The product format

One directory per node, nested exactly like the model, with explicit container directories
for the two levels:

```
widget/
├── product.json               id, name, format, repository, checkout, children
├── modules/                   module data belonging to the product itself
└── projects/
    └── search-rewrite/        folder name, frozen at creation
        ├── project.json       id, title, summary, children
        ├── modules/
        └── steps/
            └── read-the-spec/
                ├── step.json  id, title, edges
                └── modules/
                    ├── estimation.json         structured data
                    ├── step_status.json        {"status": "done"} — absent means pending
                    ├── step_description.md     prose
                    ├── step_handoff.md         what this step passes forward
                    └── step_handoff/           files this module owns
                        └── assets/diagram.png
```

Four conventions, and each one is a lesson about diffs:

- **Ordering lives in the parent's `children` list**, never in `01-`/`02-` filename prefixes.
  Reordering two projects is then a one-line JSON diff instead of a mass rename.
- **A folder name is frozen at creation** and never follows a retitle. Identity is the id;
  the folder name is presentation. Renaming a folder churns history for no benefit.
- **Absence encodes the default.** A step with no links writes no `edges` key, and an empty
  document is deleted rather than written blank — so a diff shows exactly the nodes whose
  plan actually changed.
- **Container directories say what a level is.** `projects/` and `steps/` cost one directory
  each and buy a reader the shape of the model at a glance. They also mean children never sit
  beside `modules/`, so there are no reserved folder names to trip over.

**Edges are keyed by kind**: `"edges": {"requires": ["<step id>", …]}`. One line per edge
rather than an object per edge, and the direction cannot be read the wrong way round —
`requires` is what *this* step waits on. The kind vocabulary is the domain's
(`domain/model.py`), because a kind only some builds understood would make a shared workspace
mean different things to different people. **A kind this build does not know is loaded and
written back untouched**, so a colleague's newer link survives an older build opening the
file.

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

## What a module may store

Three siblings under a node's `modules/`, and one naming rule covers all of them:
**`modules/<id>.json` is a module's data, `modules/<id>.md` is its prose, and
`modules/<id>/` is its files.** Every one is round-tripped by name, so **data belonging to a
module this build does not have survives untouched**.

| | For | Reached through | Undoable? |
|---|---|---|---|
| `modules/<id>.json` | structured facts | `node.module_data["<id>"]` | yes — `SetModuleDataCommand` |
| `modules/<id>.md` | one document of prose | `node.module_text["<id>"]` | yes — `EditTextCommand`, positional, coalescing |
| `modules/<id>/` | anything else: images, attachments | `store.files(node_id, "<id>")` | no |

Prose is model state rather than a JSON value on purpose: it diffs line by line, and it gets
the text stack — positional splicing, a staleness check, undo coalescing per burst, and
origin-based echo suppression — which a whole-value rewrite per keystroke would not.

Files are not model state, and that is also on purpose: they are opaque bytes nobody merges.
An asset add is therefore not undoable, which is the honest trade — undoing a paste would
leave the markdown pointing at a file that had gone, and an orphaned blob is recoverable
where a dangling link is not.

To version the JSON, declare a format beside the module's persistence code and expose it as
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
  would be the only key, an empty entry removes the file, an emptied file area is removed
  with its directories, and `modules/` goes when it empties.

**A module's namespace may span node kinds.** `estimation` writes `{"days": 3.0}` beside a
step and `{"start": "2026-09-01"}` beside the project those steps belong to — one module id,
one `ModuleDataFormat`, two shapes. `module_data` is on every node and `set_module_data` is
flat over ids, so nothing in the model has to know. The cost is on whoever writes the next
migration for that format: it sees both shapes and owes both a thought.

**Not every module entry is an aspect.** The graph editor stores each node's position as
`modules/project_editor.json` beside the step, and it is deliberately *not* an `AspectSpec`:
an aspect is a fact about the work that an agent may want to write, and a layout is
presentation. It is per step rather than one map on the project so that moving a node is a
one-file diff — the same reasoning as ordering living in the parent's list. The distinction
has one practical consequence worth knowing: the CLI's migration list is built from the
aspects *plus* anything like this, and a format missing from it is data the CLI silently
declines to bring forward.

**A module that writes a number owes it a `float`.** The product format used to enforce this
at the model boundary, because an `int` writes as `5` where a reloaded float writes as `5.0`
— making a file's bytes depend on whether the workspace had been reopened since it was
written. Module data is opaque to the model and `stamped()` writes whatever dict it is
handed, so on this axis the duty belongs to whoever owns the number. See
`modules/estimation/aspect.py`, which is the reference for it, and
`modules/project_editor/positions.py`, which owes it for a coordinate.

## Two writers, one folder

DPlanner expects an agent to run `dplanner` against a workspace a window has open. "Memory
is authoritative, disk follows" is therefore not the whole story, and the rule that completes
it is:

**Nothing writes over a file it has not seen.** `ProductStore` records what the workspace
looked like when it last read or wrote it and raises `StaleWorkspaceError` rather than
flushing over anything that changed underneath. A CLI run reports it and writes nothing; a
window pauses autosave, keeps the edits, and offers *File ▸ Reload from Disk*. The same check
is why two CLI runs need no lock between them: the second one is simply refused and can be
run again.

## Retiring a module

Its successor's package carries the retired module's on-disk contract — its id, its final
format and a converter — as a `Takeover`. At open, the old entry is brought up to its final
format through the carried chain, converted, merged into the successor's entry, and removed.
The retired module's *code* is gone; only its data contract survives, in the package that
inherited it. Modules never import each other, and this is why they do not have to.

`modules/estimation/aspect.py` is the worked example: `step_estimation` became `estimation`
when it grew a project's start date, and the rename cost no product-format migration and no
import. Three rules it makes concrete:

- **The retired format's version is frozen forever.** `RETIRED_STEP_ESTIMATION` is format 1
  because that is what that module last wrote, whatever the successor does next.
- **`convert` must emit the successor's *current* shape.** The engine stamps the result with
  the successor's version and does **not** run the successor's own chain over it. So a
  successor that later goes to format 2 edits its converter too. This is also the cheap way
  to retire a field: `estimation` drops the old `confidence` simply by rebuilding the entry
  from `days`, and needs no migration of its own to do it.
- **A takeover is one-way.** The old file is deleted at the first open by a build that has
  the change, so an older build opening the workspace afterwards sees that feature as empty.
  That is the same trade as any format change, and worth saying out loud before a rename.
