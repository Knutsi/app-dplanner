# Multiplayer: a ladder, coordinated, with git as the only authority

> **Status: discussed and kept, not designed.** This came up on 4 October 2026 during the
> [structural review](../2026-10-03-structural-review/README.md), between Knut, Claude and
> Codex. We agreed on the direction and want to keep it for when multiplayer work starts.
> Nothing here is built, and nothing is scheduled. When that work begins, start from this
> note and write a dated design note beside it, linking back here.

## The aim

Knut's words: DPlanner should move simply from one person with a planning repo, to two
people sharing that repo, or a person sharing it with a worker (or a worker with a worker),
and then scale "a little bit more, but not too much".

So this is a ladder, not a platform. Each rung adds only what it needs.

## The direction

The design is Knut's. A **coordination service, linked from the planning repo**, broadcasts
three things:

- **presence**: "worker XX present"
- **area claims**: who has taken which part of the graph
- **pushes**: "I pushed, others need to pull"

The **data format is shaped so the plain git structure still supports collaboration.**

That gives three layers, each with one job:

| Layer | Job | Authority |
|---|---|---|
| The data format | make concurrent edits merge on their own | git merges it |
| git | source of truth, and the transport for plan changes | **yes, the only one** |
| The coordination service | awareness: presence, area claims, "pushed, please pull" | none; advisory |

- **The service never holds plan data.** If it is down, everything still works through git,
  just with less awareness of what others are doing.
- **Claims are leases.** They expire unless renewed, so a crashed worker frees its area by
  itself.
- **Nothing on the ladder accepts plan edits on a server.** So these stay out of scope:
  commands as operations, version logs, and merge rules per data type. Authorship (who did
  what) and a merge-friendly format are what remain.

## One mechanism, two transports

The events are defined once: presence, claim an area, release, pushed. They travel by one of
two transports.

- **Local**: files on the machine. This is what `domain/at_work.py` already is, once its
  races are fixed. It is used when the plan repo links to no service. It covers a person and
  a worker on one machine.
- **Remote**: the small service. It is used when the plan repo's `.dplanner` index
  (`domain/plan_repo.py`) links to one. It covers two people, or workers on several
  machines.

**The data path differs between the two, and that is fine.** On one machine, the window and
the worker write the same files in one checkout, so collisions are concurrent writes that the
store adopts. That needs a flush lock and the `write_atomic` fix. Across machines, collisions
meet at git merge.

## Areas of the graph

The graph already names its areas:

- a branch stretch, from cut to land
- a feature or milestone cone (`domain/scope.py`)
- a single step

A claim is a set of step ids plus a label. The service only broadcasts ids, so it never needs
to understand the graph.

## The director rule

"A person operating the window is the director, and has authority over the worker or agent."

- **Director against worker:** the director wins, and the worker stands down. When the
  director sets a step done or blocked, the agent's claim ends, and the agent learns this at
  its next CLI call.
- **Worker against worker:** whoever holds the claim wins.

In code this is one typed branch on who is acting.

## The format: what still collides

| File | Today | Merges in git? |
|---|---|---|
| `step.json`, `modules/<id>.json` | `indent=2, sort_keys=True`: one key per line, one list item per line | mostly; edits on different lines merge, adjacent lines can still conflict |
| `modules/<id>.md` | prose | yes, by line |
| `project.dproj` | holds the `children` order and `last_number` | **no**: two step adds append to the same place and bump the same counter |
| step numbers | minted locally (`domain/model.py:113`) | **open design**: two writers both mint S8, and S8 is a public name |

**The two things to fix before rung 2:**

1. **`project.dproj` must stop colliding on adds.** Derive the order, or store it per step,
   and drop the stored counter.
2. **Step numbers need a small design of their own.** Branches, briefings and people use the
   numbers as names, so renumbering after the fact is not free. One option: the service
   hands out numbers while connected, with an offline fallback such as a per-writer range or
   a provisional number that is fixed on first push.

## The ladder

| Rung | What's new | What it needs |
|---|---|---|
| One person | — | today, plus the structural review's correctness fixes |
| Two people, one repo | edits meet at pull and merge | `project.dproj` stops colliding on adds, the step-number design, and the service (or claims pushed through git) |
| Person + worker, one machine | two processes on one checkout | the flush lock, `write_atomic`, claims with identity, run intent recorded before launch, and the local transport |
| Worker + worker, across machines | claims must be visible to others | the remote transport |
| "A little bit more" | — | the same |

## Prerequisites from the structural review

These are in that review's reconciled order. They are useful on their own, and they are the
ground the ladder stands on.

- **The two-writer bugs:** `write_atomic`'s fixed temporary file, and `set_checkout` hiding
  membership changes.
- **Claims:** `touch` no longer brings back ended claims, and claims gain the identity of
  who holds them.
- **Composite commands become all-or-nothing.**
- **An unknown status is never due**, so a worker on an older build never relaunches
  something newer.
- **A launch records run intent before spawning**, and reconciles after a crash.
- **`workflows.py`**: one function per thing a person or agent does, called with an `Actor`.
  That is where the director rule lives.

## Failure modes to work through when this starts

| Situation | Proposed answer |
|---|---|
| The service is down or unreachable | Everything works through git, and the window says awareness is off. Claims fall back to the local transport, or to claims pushed through git. |
| A worker crashes holding a claim | The lease expires. The next renewal attempt by a restarted worker is refused, because the claim was released. |
| Clocks differ between machines | Lease expiry is judged by the service's clock, never by the claimant's. The local transport uses one machine's clock. |
| Someone pushes without a broadcast (a plain `git push`, or the service is down) | Nothing breaks. Others see the change at their next pull or fetch. The broadcast is a courtesy, not a guarantee. |
| A broadcast arrives for a push that is not yet visible on the remote | Pull is a request, not an order. Retry after a short delay, and never pull over unsaved local edits. |
| The director overrides a worker mid-commit | The worker's next CLI call is refused, because the claim has ended. Its uncommitted work stays in its worktree for the director to keep or discard. |
| Two claims overlap | The second is refused, naming who holds the area. The director can take over any area. |
| A merge conflict happens anyway | Git shows it as usual. The format work keeps these rare. The window's outside-change adoption already handles files changed underneath it. |
| A step is numbered offline and collides | This is the step-number design's job. Until it lands, don't move to rung 2. |
| Two directors | Not on the ladder yet. When it is, director against director is resolved by who holds the claim, the same as worker against worker. |

## Where this came from

- [Structural review §14, decisions of 4 October](../2026-10-03-structural-review/decisions-2026-10-04.md),
  with the conversation in
  [how-this-review-was-made.md](../2026-10-03-structural-review/how-this-review-was-made.md).
- [Codex's second opinion](../2026-10-03-structural-review/second-opinion-codex.md) asked the
  authority question that this answers. Its first option ("a coordination service, with
  explicit limits on concurrent editing") is the one chosen.
- The meeting notes in [notes-after-meetings.md](../../towards-v2/notes-after-meetings.md)
  (idea 6) and the [build order](../../towards-v2/build-order.md), step 6.
