# An autonomous run: the arch revision, directed through DPlanner and herdr

*2026-10-04 13:24 to 2026-10-05 06:31. One Claude Code session (the **director**) executed the "DPlanner arch revision" plan with step agents in herdr. The plan comes from the [structural review](../2026-10-03-structural-review/README.md). The run went all the way to a reviewed PR into `main`, and it doubled as a field test of autonomous execution. Knut set the scope and the delegation, then intervened six times.*

## Summary

**It worked.** 20 step agents and three Codex reviews took the plan from an empty branch to [PR #221](https://github.com/Knutsi/app-dplanner/pull/221): 66 commits, 529 files, +32,413/−25,869, reviewed and approved in two rounds by a model from a different vendor.

On the branch:
- 23 of 26 steps are done.
- The composition root shrank from 4,923 to 3,551 lines.
- Status and the step kinds live in a typed `planning/` tier.
- The window and the CLI share one Set Status workflow.
- Architecture tests enforce the new surface.
- The docs are references, no longer diaries.

What's left is Knut's: S23, test the branch and merge it.

**It needed a director.** No CLI verb launches a step agent, and the window's auto-launch never fires for plain links. The director therefore rebuilt Run Agent by hand: worktree, briefing, herdr tab and status. It also:
- approved 20 plans
- answered 6 design questions and 21 sandbox prompts
- caught 2 overlaps between parallel plans
- merged 20 PRs, after first checking each against the integrated branch

The agents wrote good code. The director's real value was coordination and verification.

**The strongest finding:**
- **The effect boundary is the hard part of "units of work".** The rule is to save first, then perform the side effect (for example, releasing an agent's claim).
- **The same seam failed three review rounds in a row**: Codex's review of S8, then R26 rounds 1 and 2. Each fix opened a narrower case. The pattern is right; it needs one tested mechanism rather than one fix per path.

**The second:** cross-vendor review caught what same-vendor agents and the director missed. Codex found 14 real issues across its three reviews (2 + 7 + 5), several of them reproduced as failing tests. It also hit its usage limit twice.

## Files

| File | What it holds |
|---|---|
| [timeline.md](timeline.md) | The director's log, verbatim, timestamped |
| [steering.md](steering.md) | How directing, nesting, approvals and merging went, with counts |
| [bugs.md](bugs.md) | Bugs found in DPlanner, the test suite and the environment, each with a reproduction |
| [ergonomics.md](ergonomics.md) | Friction in DPlanner, herdr, Claude Code and Codex |
| [failure-modes.md](failure-modes.md) | What went wrong or nearly did, and the guard each one needs |
| [report.html](report.html) | All of the above as one report |
| [evidence/](evidence/) | The window's crash log and the director's four scripts |

## The run in numbers

| | |
|---|---|
| Wall clock | about 17 h, including a 7.5 h overnight hang and the wait for Codex's limit |
| Step agents launched | 20 Claude agents (S2–S9, S11–S16, S18–S22, S25) plus 3 Codex reviewers |
| Agent time per step | 9 to 52 min of active work (median about 20 min) |
| PRs merged into the branch | 20 (#202–#220), then #221 into `main` |
| Director's verifications | 16 full runs on the integrated branch (4,476 → 4,510 tests) |
| Plans approved / questions answered | 20 / 6 (12 decisions) |
| Codex sandbox approvals | 21 |
| Merge conflicts / overlaps caught before code | 4 / 2 |
| Knut's interventions | 6: the in-progress status, the window crash, memory, the stray windows, the 05:00 restart, the model choice |

## What should change, in order of value

1. **`dplanner agent run <step>`, a headless launch verb.** It would take the worktree, the briefing, the status and the run intent from S15. A director or daemon could then stop rebuilding Run Agent, and both "forgot in-progress" and "landing on the feature branch" would disappear.
2. **One effect mechanism.** An owed-effects queue that runs after the save, shared by the CLI, the window and auto-launch, with tests at its boundary. That's three review rounds' worth of lessons.
3. **A suite guard against real spawns.** One stub-missing refactor made the test suite open real Ghostty windows with real agents.
4. **A timeout on suites, and a heartbeat that survives the night.** One hung xdist run cost 7.5 hours.
5. **Overlap detection.** Warn when two in-flight steps plan to touch the same symbol, because parallel plans against the same root overlapped every time.
6. **Questions from any agent reach the person.** Knut's idea: one inbox fed by agent-state and the multiplexer's blocked state, shown in the window and in future factory views.
7. **Scope keys to the project.** `--after S25` and `review set R26` resolved across the library, and one command wrote to another project.
