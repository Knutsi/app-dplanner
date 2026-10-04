# Second opinion (Codex)

*4 October 2026. Independent review of the structural review and its planning-tier
follow-up, against checkout `b9f7fe0`. The source and tests had no diff from the original
review's `0472101` baseline. This review changed no application code.*

## Summary

**The diagnosis largely holds; the remediation needs a stronger application boundary.**
Keep the composition root as wiring and give shared planning rules an owner. Add small
headless APIs for complete actions, with validation and transactional changes shared by
the GUI, CLI, daemon and future server. Headless imports and an acyclic dependency graph
help, but do not by themselves contain coupling or make concurrent writes safe.

Fix the reproduced persistence bugs first, preserve the different meanings of identity,
presentation and readiness, and decide whether multiplayer coordinates workers or owns
plan edits before redesigning storage. Renames and documentation cleanup are useful,
but the success measure is a lower cost of changing a feature safely.

## What the evidence confirms

The composition root owns substantial business logic. `_status_in`, `_auto_progresses`
and `_due_now` make product decisions, rather than merely connecting dependencies.
They need discoverable owners outside application assembly.

Isolated probes over temporary files and in-memory models reproduced the following.
These were one-off diagnostic probes, not additions to the regression suite.

| Probe | Observed result | Evidence |
|---|---|---|
| Pause writer A before its rename, complete writer B, then resume A | A raises `FileNotFoundError`: both used the same temporary path | `core/fsio.py:54` |
| Another writer adds a project and checkout, then the old store calls `set_checkout` and flushes membership | The foreign checkout disappears immediately; project membership falls from two projects to one on the later flush | `domain/store.py:568` |
| Apply a local rename, apply a foreign rename, then undo the local command | The original title replaces the foreign title | `domain/commands.py:96` |
| Capture claims, end one, then renew from the captured read | The ended claim reappears | `domain/at_work.py`, `AtWorkBoard.touch` |
| Apply a composite whose second command names a missing node | The first command's change remains after the second raises | `domain/commands.py:317` |
| Give an otherwise eligible agent step an unknown future status | The reader returns `pending`, and due-step selection includes it | `modules/step_status/aspect.py:81`; `domain/progression.py`, `due` |

The first four confirm concerns already raised. The last two add concrete reasons to
prioritise transaction boundaries and compatibility before unattended execution. The
unknown-status probe exercised selection, not an actual agent launch.

## Qualifying the proposed remedies

### Give planning concepts owners without flattening their policies

A `planning/` tier is a good direction for status, readiness, estimates and scope. It
does not require declaring the model permanently fixed: ownership and versioned contracts
are the useful commitments.

One ordered kind list should not replace every kind-related decision. A key chooses a
primary identity; medallions show several aspects; a primary glyph identifies who works
the step; body colour incorporates completion; scope defines traversal boundaries.
`modules/__init__.py:2975–3107` and `_scope_kinds` show those different questions today.
Centralise shared facts, but keep the policies explicit and separate.

A restrictive status state machine would also be a product change. The current
`domain/progression.py` deliberately honours manually recorded, out-of-order completion.
Moving status ownership should preserve that behaviour unless it is deliberately changed.
Unknown states, however, must not silently authorise execution.

### Headless and acyclic is necessary, but not a public API

An acyclic graph can still couple every feature to other features' internal schemas and
helper functions. Permit imports through small, explicit headless APIs; keep internal
files private by convention and enforce the boundary in architecture tests. Pure queries
can be ordinary functions. Storage, clocks, execution and external services still benefit
from injected dependencies, even where production has only one implementation.

Callback counts, line counts and template divergences are warning signals, not proof of
over-engineering. Similarly, off-stack writes are not automatically violations:
`record_started` and `record_merged` explicitly record external facts that undo should
not reverse (`modules/step_status/aspect.py:140–174`). The concern is consistent ownership
of validation and effects across all writers.

### Add a small application layer for complete actions

The preferred alternative is a **modular monolith with explicit application actions**:
approve a review, record completion, link steps. The GUI, CLI, daemon and server call the
same headless action. It coordinates validation, related changes, persistence and the
notifications of accepted changes. Generic field commands remain internal building blocks;
UI undo remains a separate concern.

`modules/step_status/cli.py:67` already combines actor-specific rules, decision notes,
claim release and the status write. Sharing `SetModuleDataCommand` does not share that
whole behaviour. An application boundary gives it one owner without introducing a generic
message bus, microservices or an interface around every pure function. This is a useful
middle ground missing from the alternatives comparison.

## Multiplayer needs an authority decision

The meeting notes describe presence, claims and messaging alongside Git. Parts of the
structural review instead assume a server that accepts and merges plan edits. Both are
possible, but their costs and guarantees differ.

| Intended capability | Suggested architecture |
|---|---|
| Presence and coordinated workers; Git carries plan changes | A coordination service, with explicit limits on concurrent editing |
| Live shared plan editing | One authoritative mutation service per project, transactional acceptance and subscriptions |
| Independent offline editing that later merges | Explicit merge semantics for each data type; substantially more design work |

For live shared editing, prefer the second option initially. Serialising accepted changes
per project simplifies graph validation and numbering. This is a logical authority
boundary, not a requirement for one deployed process per project. The present
`core/storage/provider.py` explicitly requires a local working directory, so a remote
mutation service needs a boundary above file operations.

### Gaps in the current operation and coordination sketches

- **Per-entry versions do not protect graph-wide invariants.** Two writers can independently
  add opposite dependency edges on different steps. Neither entry conflicts; the combined
  graph has a cycle. Validate the resulting graph inside the acceptance transaction.
- **Composite commands are not transactions.** Multi-entry changes and their undo need
  all-or-nothing acceptance. The operation sketch needs transaction grouping as well as
  ids and versions. Compare versions for undo; matching values alone cannot establish
  that nobody else edited an entry in between.
- **A post-write check cannot guarantee detection of an overwritten Git update.**
  App-controlled checkout/pull and writes need coordinated ownership at repository scope.
  Arbitrary external writes still require an explicit recovery policy. A per-project lock
  also does not cover the separate library file.
- **Presence and exclusive ownership are different contracts.** Execution needs atomic
  acquisition, owner-checked renewal and rejection of obsolete owners at the point of
  accepting protected writes. An expiry and an owner id alone are insufficient. The
  [etcd locking contract](https://etcd.io/docs/v3.5/dev-guide/api_concurrency_reference_v3/)
  illustrates checking ownership within the write transaction; this is a design reference,
  not a recommendation to add etcd.
- **A launch is an external effect.** The current launcher spawns before `due.claim()`
  (`modules/step_agent_instruction/module.py:800`), and the auto-launch pass flushes later.
  A crash between those steps needs reconciliation, not a blind retry. Durable run intent,
  run identity and recovery belong in the execution boundary; a plan transaction cannot
  itself atomically start an external process.
- **Step numbers are already public references.** Branches, briefings and people name them.
  Do not treat collision repair by lint as harmless. Use authoritative allocation, or
  deliberately design an offline allocation scheme that preserves stable references.

## Suggested order and proof of improvement

1. Fix the reproduced persistence bugs and unsafe unknown-status interpretation, with
   regression tests. Protect foreign edits from stale undo.
2. Pilot the ownership changes on one complete workflow: planning rules with a clear home,
   a headless application action, and the same outcome through GUI and CLI. Exercise
   competing writers and failure partway through a change.
3. Settle the transaction and multiplayer authority boundaries before moving more logic
   into cross-module imports. Preserve the distinction between durable plan data, execution
   ownership and local UI state.
4. Move and rename packages as their responsibilities become clear. Keep stable on-disk
   ids. Shorten the current architecture guide while retaining dated decisions separately.

A transactional store is a credible alternative to growing a custom file transaction
system. [SQLite supplies atomic commit and recovery](https://www.sqlite.org/transactional.html).
Whether it fits depends on whether Git files must remain authoritative or can become an
export. Do not create two independently writable sources of truth. SQLite alone would
not coordinate independent machines or make external launches transactional.

Measure whether a representative feature touches fewer unrelated places, whether each
rule has one owner, and whether concurrency failures are handled predictably. A smaller
composition root is useful evidence, but not the outcome by itself. Hygiene need not be
a prerequisite for every architectural improvement.

## Validation at review time

- Full offscreen suite: **4,382 passed, 25 skipped**, four Qt deprecation warnings.
- Ruff: passed.
- Mypy on the default platform and with `--platform win32`: passed, 797 source files each.
- The six diagnostic probes above ran separately; none changed application or test files.

Passing the existing suite confirms the baseline. It does not cover the additional
concurrency and compatibility cases demonstrated by the probes.
