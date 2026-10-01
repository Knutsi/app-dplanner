# Coordination: claims, leases and presence

*Gathered 2026-10-01.*

Two workers — two daemons, or a daemon and a person — must not do the same step. Today that is guarded by:

- **`domain/at_work.py`, the advisory claim.** One JSON file per claim under `config_dir()/at-work/`, shaped `AtWork(project, step, doing, done, of, started, seen)`. A claim goes quiet after `FRESH_MINUTES = 3` and is swept after `SWEEP_HOURS = 24`. `touch` on every `dplanner` run renews it, and a stopped status ends it. **It is per machine.**
- **The auto-launch claim.** The run stamp and status are written and flushed the moment the shell opens, so the next level-triggered pass reads the step as launched. The `QLockFile` under `config_dir()/auto-launch/` makes one window per machine the launcher.
- **The turn stamp on a review round** (`asker_turn_launched` / `party_turn_launched`). It names the turn rather than the moment, so another machine's clock cannot make it due again.

ARCHITECTURE.md's *Auto-progress is launched by the window* names the gap: across machines only the plan is shared, and it travels by commits. Two machines with auto-launch on can both launch a step within one sync interval, and "no lock can close that gap without a server". The answer today is *one machine runs the agents*. Climbing past that rung is what this note is about.

## Leases are the standard answer

A claim that may outlive its holder's process must expire. The pattern is the same everywhere:

- **A lease is a key with a TTL, renewed by compare-and-swap.**
  - [NATS KV](https://www.synadia.com/blog/renew-nats-kv-key-ttl): every CAS rewrite restarts the key's TTL, and expiry is distinguishable from a clean release.
  - [Kubernetes Leases](https://kubernetes.io/docs/concepts/architecture/leases/): holder, renewTime, leaseDuration.
  - Beads: `bd heartbeat` and `bd reclaim`, grace ≈ 2× TTL, and both longer than the sync interval ([landscape.md](landscape.md)).
- **A fencing token** — an epoch that only increases, handed out with the lease — stops a holder that stalled and lost its lease from writing afterwards. Every write carries the epoch, and a stale one is refused ([Kleppmann](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)). For DPlanner the "write" is a `status set` or `review post` from the agent's run, so the epoch is the run id. A verb from a run that no longer holds the step is refused, which is the `--run <id>` the landscape recommends.
- **A replica never reaps another replica's lease** (Beads). Otherwise a laptop that has not synced reaps the server's live claim.
- **Stall detection** is time since the agent's last event. Symphony kills a worker silent for 5 minutes ([SPEC](https://github.com/openai/symphony/blob/main/SPEC.md)), which needs the stream-json/event output from [headless-mechanics.md](headless-mechanics.md), not a terminal.

**Do not use a CRDT for a claim.** A claim needs mutual exclusion, and a CRDT's job is to merge two concurrent writes so both survive. That is right for presence and shared text, and exactly wrong for "who holds step 12".

## Where the lease lives, by scale

| Scale | Store | Latency | What it costs |
|---|---|---|---|
| One machine (L0–L1) | A file lock plus `AtWorkBoard` — what exists, minus Qt | instant | Nothing new: `QLockFile` becomes a plain lock file the CLI can take. |
| A few machines, no server (L2–L3, small) | **Claim refs in the plan's git remote**: `refs/dplanner/claims/<project>/<step>`, pointing at a tiny commit holding holder, host, run, expiry and epoch. Claiming is a push that must not be a fast-forward of someone else's claim. git refuses a non-fast-forward without `--force`, and `--force-with-lease=<ref>:<expected>` is an atomic compare-and-swap on the ref. | seconds | The plan files never conflict, because claims are not in them — Beads' lesson. Heartbeats are pushes, so the TTL is minutes, not seconds. Works with any git host and offline-tolerant. |
| Many workers and people (L3–L4) | **A tiny coordination server** — one process with SQLite, or NATS KV — holding leases with TTL and epoch, plus a websocket for presence | sub-second | Something to run, secure and keep alive. It holds *only* ephemeral facts (leases, presence, messages in flight). The plan and its outcomes still go to git through commands. |

The git-ref rung is worth having because it needs no new service, and it is honest about its latency. A step takes minutes to hours, so a claim that lands in two seconds is fine. It is the one mutual exclusion git does give us: the remote's ref update is atomic.

## Presence: who is looking where

People need softer information than a claim: *Knut has step 14 open in Details*, *the server worker is on the Review stage of step 9*. That is presence, and it is ephemeral by design:

- [Yjs awareness](https://docs.yjs.dev/api/about-awareness): each client broadcasts a small state, and is marked offline after 30 s without an update.
- [Supabase Realtime Presence](https://supabase.com/docs/guides/realtime/presence) is the hosted equivalent. [Automerge](https://automerge.org/) is for shared documents, which DPlanner does not need. Two writers already work through the store's adoption of outside changes.

Presence is **never written to git**. It is a view of who is connected now. The *outcome* of what people and agents did reaches git as commands do today.

## How this answers the meeting note's open questions

- **What can be claimed?** A **step**. A playbook runs inside one step, so its stages are not separately claimable. A branch landing is one step too, so claiming it claims the branch review. Claiming a region ("this branch of the graph is mine") is presence, not a lock: it tells people where a worker is heading without stopping anybody. Lock a region and one stalled worker freezes half the plan.
- **How is a claim released when a worker stalls?** The lease lapses: no heartbeat for one TTL, then the reaper after the grace. The epoch makes the stalled worker's late writes harmless.
- **What lives only on the server, and what goes to git?** **Only ephemeral facts live on the server:** leases, presence, live run events, messages in flight. **Everything that is a fact about the plan goes to git** through `domain/commands.py`: status, rounds, findings, usage, notes. If the server is wiped, nothing about the plan is lost, and the workers rebuild their leases. This keeps the rule that the plan is the source of truth, and that derived facts are computed, never stored.
