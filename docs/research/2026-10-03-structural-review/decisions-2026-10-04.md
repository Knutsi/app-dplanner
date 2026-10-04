# Decisions and direction, 4 October

*Knut's answers to the three open questions, and what follows from them. This settles the
multiplayer authority question that both reviews left open, and renames the `actions.py`
pattern.*

## 1. Multiplayer is a ladder, coordinated, with git as the only authority

**Knut:** "We need to find a balance where DPlanner can move simply from a person with a
planning repo, to two people sharing that repo, or a person sharing it with a worker (or a
worker with a worker), then potentially scaling a little more, but not too much."

His design is a **coordination service, linked from the planning repo**. It broadcasts:

- presence ("worker XX present")
- claims on areas of the graph
- pushes ("I pushed, others need to pull")

The data format is shaped so that the plain git structure keeps working while people
collaborate.

**Assessment: this is the minimal design for the ladder, and the right one.** It has three
layers, and each has one job:

| Layer | Job | Authority |
|---|---|---|
| The data format | make concurrent edits merge on their own | git merges it |
| git | source of truth and transport for plan changes | yes: the only one |
| The coordination service | awareness: presence, area claims, "pushed, please pull" | none: advisory only |

- **The service never holds plan data.** If it is down, everything still works through git,
  with less awareness of who is doing what.
- **Claims are leases** that expire unless renewed, so a crashed worker frees its area by
  itself.
- **The authority question is settled.** Nothing on the ladder needs a server that accepts
  plan edits, so commands-as-operations, version logs and per-type merge rules drop out of
  the plan. What remains of that work is authorship (`Actor`) and a finer format.

### One mechanism, two transports

The events are defined once: presence, claim an area, release, pushed. They travel by one of
two transports:

- **Local**: files, which is what `domain/at_work.py` already does once its races are fixed.
  It is used when the plan repo links to no service.
- **Remote**: the small service, used when the plan repo's `.dplanner` index
  (`domain/plan_repo.py`) links to one.

So the same mechanism works for two people and for a person with a worker on one machine.

**The data path differs, and the difference is honest.** On one machine, the window and the
worker write the same files in one checkout:

- collisions are concurrent writes that the store adopts
- that needs the flush lock and the `write_atomic` fix

Across machines, collisions meet at git merge. Both paths are already in the plan.

### Areas of the graph

The graph already names its areas:

- a branch stretch (cut → land)
- a feature or milestone cone (`domain/scope.py`)
- a single step

A claim carries a set of step ids and a label. The service broadcasts ids and never needs to
understand the graph.

### The format: the lever that matters most

- **Already merge-friendly.** `store.py:1286` writes JSON with `indent=2, sort_keys=True`:
  one key per line, one list item per line. Prose (`.md`) merges by line.
- **Every step add still collides.** `project.dproj` holds the `children` order and
  `last_number`. Two adds both append to the same list position and both bump the counter,
  so git conflicts every time. The fix is to derive the order, or store it per step, and to
  drop the stored counter.
- **Step numbers are the one real open design.** Two writers can both mint S8, and S8 is a
  public name, used by branches, briefings and people. One option is for the service to hand
  out numbers while connected, with an offline fallback. It needs a small design of its own,
  and it is the first thing rung 2 hits.

With area claims reducing overlap and the format absorbing the rest, real conflicts should be
rare. When one does happen, git shows it in the usual way.

### The ladder

| Rung | New | Needs |
|---|---|---|
| One person | — | today, plus the correctness fixes |
| Two people, one repo | edits meet at pull and merge | `project.dproj` stops colliding on adds; the step-number design; the service, or claims pushed through git |
| Person + worker, one machine | two processes on one checkout | the flush lock, `write_atomic`, claims with identity, run intent before launch; the local transport |
| Worker + worker, across machines | claims visible to others | the remote transport |
| "A little more" | — | the same |

## 2. The director has authority over the worker

**Knut:** "A person operating the window is the director, and that has authority over the
worker or agent."

This settles the claim question: **when the director sets a step done or blocked in the
window, the agent's at-work claim ends**, and the agent finds out at its next CLI call.

It also gives the ladder its collision policy:

- director against worker: the director wins, and the worker stands down
- worker against worker: whoever holds the claim wins

In code this is one typed branch on `Actor`:

- a `Person` may set done directly
- an `AgentRun` goes through review

## 3. `workflows.py`: one function per thing a person or agent does

**Knut:** "It seems reasonable, as long as we keep the underlying context system. I believe
that has kept the UI clean and easy to shape."

**The context system stays exactly as it is.** The workflow functions sit *under* it:

```
today:  ActionSpec(context) → command → model → signal → views
with:   ActionSpec(context) → set_status(view, the context's steps, …) → change.command → undo → model → signal → views
                               ↑ the ActionSpec's state calls refusal() to grey the entry and say why
```

The context still decides:

- which steps a verb acts on
- whether it is enabled
- the menus, the palette and the right-click bands

Only the middle step, building the command, moves into one shared function, which the CLI
and a future worker call too.

**Renamed.** "Action" already means `ActionSpec` in this codebase, so the file is
**`workflows.py`** and its return type is **`Change`**: the command plus its follow-ups. That
replaces "`actions.py`" and "`Action`" in §12 and in
[response-claude.md](response-claude.md).

**`refusal()` runs in an action state.** It therefore inherits CLAUDE.md's rule: no walk over
a whole project, only the steps the context names.

The multiplayer direction is also kept on its own, for when that work starts:
[2026-10-04-multiplayer](../2026-10-04-multiplayer/README.md).

## What changes in the next move

- **The pilot** uses `step_status/workflows.py`. The window's *Set Status* gains the claim
  release, under the director rule.
- **The multiplayer step of the reconciled order** becomes the ladder: the format fix for
  `project.dproj`, the step-number design, and the coordination events with a local
  transport first.
- **Still open:** whether `workflows.py` goes into CLAUDE.md after the pilot. The step-number
  design is the first item for rung 2.
