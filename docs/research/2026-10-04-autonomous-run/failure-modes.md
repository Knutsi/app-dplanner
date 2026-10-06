# Failure modes: what went wrong or nearly did

**Summary.** Each row below happened, or nearly happened, during the run. Six were caught in time, by an agent's question, the director's review or Codex. The overnight hang cost 7.5 hours, and the stray agent windows reached Knut's desktop before anyone noticed. The guards are what an unattended daemon (v2 step 3) would need, because a daemon has no director to read plans.

| What happened | How it was caught | The guard it needs |
|---|---|---|
| A suite hung for 7.5 h (xdist workers dead, the master waiting forever) | Knut, at 05:00 | `timeout` around every suite in briefings, or pytest-timeout; a heartbeat that actually wakes the director; an alarm for an agent that is `working` for more than N minutes with no output |
| A director check never woke it overnight | Same | Wake-ups must survive long idle periods; at minimum, a status line Knut can see |
| Memory pressure got background checks reaped | Claude Code's reaper, reported | Keep `/tmp` lean (it's RAM here); cap concurrency by memory, not cores; `-n 4` suites |
| The window crashed (SIGSEGV) under load | Knut | Bug #2; fewer parallel full suites while a window is open |
| The test suite launched real agents | Knut saw the windows | Bug #3: a spawn guard in the test session |
| Two parallel plans claimed the same code (waits; branch plan / `flows_into`) | Director, by reading both plans | DPlanner could warn when two in-flight steps plan to touch the same symbol |
| The rename list assumed modules that turned out to be coupled (`projects`, the simulator) | The agents' questions | Treat a decision made from a report as a proposal; let an executing agent amend it, with a note |
| Effect before save (claim released, then the save fails) | Codex, three rounds in a row | One owed-effects mechanism, shared and tested at the boundary |
| The director stood in for a reviewer and missed a hole | R26 later | Don't let the director replace a cross-vendor review; wait for the reviewer or switch its model |
| Steps marked done before verification (PR refresher) | Director | Separate "merged into the feature branch" from "verified", or let the director own done |
| A command wrote to another project's step | Director, by `git status` of the plan repo | Bug #1: project-scoped keys; a director always addresses by id |
| Parallel agents both numbered §77 | Merge conflict | Fixed by S22's per-file NOTES |
| Agents treated a ready-for-review subject as done-able | (nothing went wrong) | — |

## For the daemon (v2 step 3)

The run shows what a daemon must do itself, because nobody is reading plans at night:
- **Launch through one verb.** `agent run`: worktree, briefing, in-progress, run intent.
- **Bound every external process** with a wall-clock limit, and treat silence as a failure.
- **Never stand in for a review gate.** If the reviewer is unavailable, pause.
- **Keep the effect contract in one tested place.**
- **Keep resource budgets** for memory, `/tmp` and model usage as first-class inputs to concurrency.
