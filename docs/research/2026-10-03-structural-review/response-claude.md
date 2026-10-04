# Response to the second opinion (Claude)

*4 October 2026. A review of [second-opinion-codex.md](second-opinion-codex.md), against the
same source (`0472101`; no code changed since). It assesses the opinion on what matters for
DPlanner:*

- *performance*
- *readiness for v2*
- *keeping the modularity we have*
- *scaling with features*
- *ease of refactoring, debugging and understanding*
- *not over-engineering*

> **Renamed after this was written:** the pattern is `workflows.py`, returning a `Change`,
> because "action" already means `ActionSpec` in this codebase. Read `actions.py` and
> `Action` below as those names. See [decisions-2026-10-04.md](decisions-2026-10-04.md).

## Verdict

A strong second opinion. I agree with roughly 80% of it:

- It corrects three overreaches in my review.
- It adds two real defects.
- It names the decision my report assumed without asking: what the multiplayer server is
  the *authority* for.

Where I qualify it: the idea of application actions ("units of work") is right. It should
be **a per-module pattern**, an `actions.py` of plain builder functions beside `aspect.py`,
and not a central application layer. A central layer would become the next composition root.

## Checked in code, beyond Codex's probes

- **The GUI and CLI paths for one workflow already diverge.**
  - The window's *Set Status* (`modules/step_status/module.py:120-133`) only pushes
    `status_command`.
  - `dplanner status set` (`modules/step_status/cli.py:67-85`) does four more things:
    - refuses a status on a wait or cut
    - refuses an agent's done-without-review
    - records a `--because` decision note
    - **ends the at-work claim**, which only happens through `modules/__init__.py:4368`

  So a person marking a step done in the window leaves the agent's claim standing. That
  proves Codex's point that sharing `SetModuleDataCommand` does not share the action. It
  also contradicts CLAUDE.md's "neither can grow a behaviour the other lacks".
- **An unknown status reads as `pending`** (`modules/step_status/aspect.py:81`). A status
  written by a newer build therefore becomes due again, which is dangerous once a daemon
  runs a different build from the window.
- **`launch_due` spawns the agent and only then claims the step**
  (`modules/step_agent_instruction/module.py:824-827`). A crash between the two leads to a
  second launch.
- **`domain/progression.py:36` keeps out-of-order recording on purpose**: "the graph gates
  *launching*, not *recording*". My state-machine sketch would have broken it.
- **`CompositeCommand.redo` is not atomic** (`domain/commands.py:329-331`).

## Corrections I accept

1. **One ordered kind list was too much.**
   - The key and the kind word share one ranking.
   - The other questions are separate policies: the primary glyph (who works the step), the
     medallions (several marks at once), the body tone (which includes done) and the scope
     rules (where traversal stops).
   - `planning/` owns the *facts* (the predicates) and the one ranking; the policies stay
     explicit and read those facts.
2. **No restrictive state machine.** `planning/` owns the vocabulary and the *readiness*
   rules. Transitions are not policed, so out-of-order recording still works. An unknown
   state must never make a step due.
3. **Off-stack writes were overstated.** `record_started` and `record_merged` are documented
   external facts. Only the membership calls without an origin remain a finding.
4. **The planning model needs no "fixed" declaration.** The commitment is to ownership and
   versioned contracts.
5. **Repairing step numbers by lint is not harmless.** Numbers are public references, so
   they need authoritative allocation.
6. **The gaps Codex found in my sketches are real:**
   - Per-entry versions miss graph-wide invariants: two edges that are each fine can
     together make a cycle, so `link_refusal` must run when a change is accepted.
   - A lease needs fencing: check ownership at the moment the protected write is accepted.
   - A launch is an external effect: record run intent *before* spawning, and reconcile
     on start.

## Where I qualify Codex

1. **Actions belong to their owner, not to a layer.**
   - A complete workflow is a plain headless function in the owning module's `actions.py`,
     for example `step_status/actions.py: set_status(view, step, status, *, actor, because,
     today) -> Action`.
   - It returns one composite command, which is one undo gesture in the GUI and one flush in
     the CLI. It also returns the follow-up effects, such as ending the claim, which the
     caller runs once the change is accepted.
   - This is the existing rule that both surfaces build the same object, moved up from the
     command to the workflow. `status_command` and `rewire_command` are already builders of
     this kind.
   - There is no registry, bus or handler interface. A central `application/` package would
     be a horizontal layer that every feature has to edit.
2. **Import facts, inject effects. Here the two reviews agree.**
   - Pure readers are imported. A module's importable surface is **only `aspect.py` (facts)
     and `actions.py` (workflows)**. That is tighter than my earlier "any headless file",
     and a test can enforce it.
   - Effectful services stay injected, even when there is only one implementation, because
     tests need fakes for them: the store, clock, launcher, at-work board and network.
3. **Don't make the facts refactor wait for the authority decision.**
   - Extracting the planning facts and narrowing the root are pure refactors that don't
     depend on multiplayer.
   - Only operations, versions and the server wait for that decision.
   - `docs/towards-v2/build-order.md` already puts the server last, behind "git plus
     advisory claims". That is Codex's first option, a coordination service.
4. **Versions don't belong in the git files.** A per-entry version counter stored in the
   plan files conflicts in *every* concurrent git merge, because both sides bump it.
   Versions belong in the authority's log.
5. **No SQLite for now.** Git-mergeable plan files are a product pillar: FORMAT.md, plan
   repositories, review in PRs. A second writable source of truth would be worse. Codex
   itself notes that SQLite doesn't coordinate machines.

## How the planning tier and actions scale, and fit with the modules

*Added at Knut's request. Everything in this section is a proposal; this PR adds no tests.*

```
planning/            facts + readiness, pure            imports core, domain only
   ↑
<module>/aspect.py   storage of non-planning aspects    imports planning
   ↑
<module>/actions.py  complete workflows → Action        imports planning, any module's aspect.py / actions.py
   ↑
<module>/cli.py · <module>/module.py (Qt) · daemon root · (server)
   call actions: the GUI pushes Action.command as one undo gesture, the CLI applies and
   flushes, and both run Action.effects afterwards
```

**How each part grows:**

- **The planning tier grows with the ontology, not with features.**
  - It holds about ten aspects plus the readiness rules. A new feature lands as a module.
  - Creep is the way it fails. The guard is `PLANNING_ASPECTS`, an explicit list in
    `tests/test_architecture.py`, so adding an aspect is a deliberate diff someone reviews.
  - If the list passes about 15 entries, stop and reconsider.
- **Actions grow with verbs**, roughly one per plan-changing verb. That is the growth curve
  `CliCommand`s already follow, spread across their owners, so no single file lists them.
  - A workflow that spans modules composes by calling: approving a review calls
    `step_status.actions.set_status(...)` and combines the result into one composite.
  - The risk is an `actions.py` that grows into a god file. The guard is one function per
    verb, and splitting the module when its `actions.py` outgrows its `cli.py`.
- **Modules stay vertical slices.** The only cross-module surface is two files per module,
  both visible to a test.

**Enforced by mypy.** `strict = true` is already on, and it includes `--strict-equality`;
`warn_unreachable` is on too.

- **`Status` and `Kind` are `enum.Enum`, not `StrEnum` or `str`.**
  - `--strict-equality` then rejects `status == "done"`, because the types don't overlap.
    That ends the class of bug where literals are copied (`modules/__init__.py:704,719`,
    `coverage/trace.py:361,452`).
  - The enum's `.value` is the word on disk, so the format doesn't change.
- **`planning.status.stored(step) -> Status | Unknown`.**
  - Readiness accepts `Status` only, so `Unknown` must be handled before asking whether a
    step is due.
  - With `match` and `assert_never`, mypy flags a branch that forgets it. Codex's
    unknown-status probe becomes a type error.
- **Actions build; they don't mutate.**
  - An action takes `PlanView`, a `Protocol` in `domain/` holding only `Library`'s queries,
    and returns `Action(command, effects, label)`.
  - mypy rejects a mutator call on a `PlanView`.
- **`Actor = Person | AgentRun | Daemon`.**
  - Actor-specific rules become typed branches.
  - It is also the author field v2 needs, at no cost now.

**Enforced by `tests/test_architecture.py`:**

1. `planning/` imports only `core` and `domain`.
2. A module imports another module only through `aspect.py` and `actions.py`, and both are
   headless. The check is per package, not by bare filename.
3. The module import graph is acyclic, and a failure names the cycle.
4. `actions.py` imports no `framework`, no Qt and no `domain.store`.
5. Ratchets that may only go down:
   - the root's line count
   - the number of direct pushes or applies of built-in commands outside `actions.py`
6. The set of declared `MODULE_ID`s does not change.

A rule kept "by convention" erodes. A test that names the offending import does not.

## Performance

- **Actions** are plain calls that build commands. There is no dispatch.
- **An atomic composite** costs extra only when a command fails partway.
- **Validating the whole graph on acceptance** is O(V+E) per batch, well under a
  millisecond at today's plan sizes. `scripts/measure_scaling.py` is the check.
- **None of this touches the debounce or announce paths.**

## Reconciled order

1. **Correctness:**
   - `write_atomic` and `set_checkout`
   - an atomic composite
   - an unknown status is never due
   - `touch` no longer revives ended claims
   - undo is refused when the value is no longer the one this command wrote
2. **A pilot on one complete workflow, *set status*:**
   - `planning/` owns the status vocabulary, readers and readiness.
   - `step_status/actions.py` serves both the GUI and the CLI, and the GUI gains the claim
     release.
   - The first architecture tests land with it.
   - Measure how many places a status change touches, before and after.
3. **Planning facts and a narrower root:**
   - kind predicates and one key ranking, with the policies kept separate
   - cross-module imports only through `aspect.py` and `actions.py`
   - clusters moved out of the root
4. **Treat a launch as an external effect:** durable run intent before spawning, and
   reconciliation. This has to land before the daemon.
5. **Decide the multiplayer authority**, then design operations and versions.
6. **Renames and docs**, as responsibilities settle.

## Open questions for Knut

1. Should the multiplayer server only coordinate (presence, claims, messages), or be the
   authority over plan edits?
2. Should the GUI's *Set Status* release an agent's claim, as the CLI does? I'd say yes.
3. After the pilot, should the `actions.py` pattern go into CLAUDE.md?
