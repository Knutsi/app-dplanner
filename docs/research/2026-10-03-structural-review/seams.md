# Seams for multiplayer and the daemon

**Summary.** Persistence is optimistic and coarse, built for one person at a time, and two
real two-writer bugs already exist. Before the daemon (v2 step 3), the cheapest useful moves
are these:

- fix the two bugs
- close the gap between the stale check and the write with a per-project lock
- make claims a headless lease with an agent identity
- move auto-launch's *decision* out of Qt

Before the multiplayer server (v2 step 6), commands have to become operations: identified,
authored, with a base version.

## The two bugs (verified in code)

1. **`core/fsio.py:54-56`.**

   ```python
   tmp = path.with_name(f".{path.name}.tmp")
   tmp.write_text(...)
   tmp.replace(path)
   ```

   Two processes writing the same file share one temporary path. The GUI and the CLI both
   write the library file and the at-work claims. The outcomes are a torn file renamed into
   place, or `FileNotFoundError` for the slower writer.
   **Fix:** `tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")`, then `replace`.
2. **`domain/store.py:584-593` `set_checkout`** reads the file, writes
   `file.projects, self._checkouts, file.archived`, then `_remember_library_stamp()`.
   - The other writer's project rows reach the file, but the re-stamp says this window has
     already seen them, so `_adopt_library_file` never adopts them.
   - This window's next membership flush (`_write_library_file`) writes the model's list
     and drops their project.
   - Their checkout keys are replaced by this window's.

   **Fix:** merge the checkouts into the file's own checkouts, and do not re-stamp when the
   file had changed before this write.

## Commands are not operations

- `AddNodeCommand` keeps the live `Node` (`commands.py:218`), and `RemoveNodeCommand` keeps
  the removed one.
- `before` is captured on the first `redo`.
- Origins are `object()` sentinels (`UNDO_ORIGIN`, `OUTSIDE_ORIGIN`), so they cannot be
  serialised.
- There is no id, author, timestamp or base version.
- Builders (`rewire_command`, `redirect_edges_command`) produce whole-list replacements read
  from the live library, against a base nobody records.
- Undo restores captured values, so an undo overwrites whatever another writer changed since.

The shape an operation needs:

```python
@dataclass(frozen=True)
class Op:
    id: str          # uuid7: sortable, minted by the writer
    author: str      # a person or an agent run id
    entry: Entry     # (step id, "title" | "edges/requires" | "<module>.json" | "<module>.md")
    base: str        # the version of that entry this op was made against
    after: Json      # the new value; text edits keep TextEdit hunks
    before: Json     # captured eagerly, so undo is the op's inverse and can be refused
```

Undo then becomes "apply the inverse if the entry is still at `after`, otherwise refuse".
The undo service already handles the refusal: when the document raises, it drops that entry
and the history after it (`framework/undo.py:162-171`). Today, though, only a missing node
or a text mismatch raises. A value another writer changed is overwritten silently.

## Conflicts are coarse, and the check is not atomic

- `flush` checks every snapshot and then writes (`store.py:1053-1095`); another process can
  land in between.
- A step's `meta` entry holds the title, every edge list and the number, so a rename against
  a link is a conflict.
- `project.dproj` holds the children order and `last_number`, so **any two writers adding a
  step conflict**, whatever the steps are.
- Resolution is a modal choice between mine and theirs.

Finer entries make most of these disappear:

- the title on its own
- each edge list on its own
- the children order derived (or keyed per step)
- numbers minted per writer, or deduplicated by lint

## Coordination

- Claims live under `config_dir()/at-work/`, one file per (project, step), with no agent or
  host identity.
- `touch` reads every claim and rewrites each one, so an `end` in between is resurrected.
- The launch lock is a `QLockFile` (`step_agent_instruction/auto_launch.py:63`), and the
  module also uses `Debounced` and the window context.
- `due_here` is a closure inside the GUI's `default_modules()` (`__init__.py:1408`) that
  reads window state (`agent_runs.live`).
- `launcher.py` is already headless; the decision of *what is due* is not.

## The daemon as a third composition root

What it would wire, all of it headless:

- `LibraryStore` and a `Library` per plan repository
- the claim lease
- `due_now` (from the root, into `agent_launch`)
- `agent_briefing`
- `launcher` and the harnesses
- the usage ledger
- status writes through commands

The test that the hybrid has worked is that this root needs no `framework/` import.

## Failure modes, worked through

| Scenario | Today | With the proposals |
|---|---|---|
| Two writers both add a step | Both mint S8. Both rewrite `project.dproj`. The second flush is refused as stale, and its person picks mine or theirs, losing one step's place in the order. | Per-step entries plus per-writer numbering: both land. A duplicate number is linted and repaired. |
| A flush races a `git pull` | The snapshot is checked, the pull lands, the write overwrites the pulled files (a lost update). | A per-project lock is held across check and write; git's checkout is not covered, so the store also re-checks after writing and warns. |
| A daemon on build N+1 opens a plan a window on build N has open | `load()` migrates and writes; the window refuses the newer format, or adopts it blind. | Migrations are written only by a verb that writes anyway; a minimum-reader stamp makes the old build refuse with a clear message. |
| `touch` resurrects an ended claim | `end` unlinks; `touch` rewrites from its earlier read; the claim stands for 3 more minutes. | Each claim is written by its owner only; `touch` renews only claims it owns (by agent id), with O_EXCL create. |
| A store slot raises | `Signal.emit` logs and continues; `_unflushed` misses an entry; the change is never flushed or never checked. | The store connects through a non-swallowing path: an exception poisons the store and the window says so. |
| A cross-module import cycle | Impossible today (no imports). | The test fails and names the cycle; the cycle names a misplacement (two found in simulation). |
| The root is half-migrated | The logic sits in two places for a while. | One cluster per PR; each PR deletes the root copy in the same change; a `wc -l` ceiling test on the root ratchets down. |
| A rename breaks `rules.py` paths | The rules files' `paths:` stop loading for the moved files, silently. | `tests/test_rules.py` already fails it: `test_every_glob_names_a_file` and `test_every_module_package_is_claimed_by_an_area`. The rename PR moves the rules in the same change. |
| A `MODULE_ID` drifts in a rename | Stored data is orphaned; it round-trips but no module reads it. | Ids are string constants and never derived from the package name; add a test that the set of declared ids is unchanged. |
