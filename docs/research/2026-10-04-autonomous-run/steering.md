# Steering: directing, nesting and approvals

**Summary.** The director was one Claude Code session in a herdr pane. It drove a loop: launch, watch, approve the plan, review, merge, verify. Step agents ran Claude in plan mode in one herdr tab each. Codex reviewed in its own tabs, and some agents nested subagents of their own. Most of the director's time went into reading plans and reviewing PRs. Its most valuable acts were coordination: catching two overlapping plans and amending the rename list twice. It verified every merge itself, and twice that verification caught something an agent had skipped.

## The loop

1. **Launch** (`evidence/launch_step.sh`). Read the briefing with `dplanner agent prompt`. Prepare the worktree and branch it names, exactly as Run Agent would (`.git/info/exclude`, fetch, `worktree add`). Open a herdr tab with `DPLANNER_PROJECT` set. Start `claude --permission-mode plan`, prompt it with the briefing path, and record the GitHub branch and `in-progress`.
2. **Watch** (`evidence/watch.sh`). A background poll of `herdr agent list` that exits, waking the director, on `blocked`, or on `idle`/`done` that isn't just waiting for its own background shell or subagent. Parked panes are skipped, and there's a heartbeat.
3. **Plan approval.** Read the plan from `~/.claude/plans/<name>.md`, whose path the screen shows at the bottom. Either approve it (option 1, auto mode) or send corrections through "Tell Claude what to change".
4. **Questions.** Answer Claude's question UI with `send-keys` (arrows, Enter). When none of the options fit, use "Type something" plus `herdr pane send-text`.
5. **PR review.** Read the diff. For refactors, compare real CLI output and agent briefings on the real plans, before and after (md5 of `schedule/progression/order/scope/coverage/branch show`, `step list`, `agent prompt`, `--help`). Every refactor came out byte-identical.
6. **Merge** with `gh pr merge --merge` into `refactor/arch-revision`. Take the agent down: close the tab, remove the worktree.
7. **Verify** (`evidence/verify.sh`). The full suite, ruff and both mypy runs in an integration worktree. After the memory incident: `-n 4`, run only when no agent suite is running.

## Counts

| Act | Count |
|---|---|
| Claude step agents launched | 20 |
| Codex reviewers launched | 3 (S7's PR, S8's PR, R26) |
| Plans approved | 20 (one revised after a correction, S13) |
| Design questions answered | 6 sessions, 12 decisions |
| Coordination messages sent to running agents | 9 (queued prompts) |
| Codex sandbox approvals | 21 |
| Overlaps caught before code was written | 2 (S11/S12 on waits; S13/S14 on the branch plan and `flows_into`) |
| Merge conflicts sent back to agents | 4 (S6, S14, and two expected ones) |
| Director's verifications of the integrated branch | 16 |
| Person steps decided under delegation | S10 (pilot verdict, N39), S17 (renames, N72, later amended by N77) |

## Nesting

- **Director → step agent → its own subagents.** S7 ran an Explore subagent before asking its questions. S22 forked two "History out" subagents to rewrite the NOTES entries in parallel.
- **Director → Codex reviewer → round trips with a step agent.** R26 and S25 talked through `dplanner review start/post/wait/reply/approve`, one verb per turn. The director only unblocked and prompted. That's the playbook shape: an implementer and a cross-vendor reviewer with a capped number of rounds.
- **Second rounds.** The director asked Codex for a second round on S8 (c8). When Codex ran out of allowance, the director did that second round itself, and missed a hole R26 later found (the window's release before persistence).

## What the director decided

- **The pilot verdict (S10).** Adopt `planning/` and `workflows.py`, with an explicit effect contract (N39).
- **Rename list.** Confirmed (N72), then amended when agents found coupling the report couldn't see: `projects` kept whole (N77), and the simulator kept inside `schedule/`.
- **Import surface.** The headless-package rule (a package with no `module.py` is surface all through) came out of S13's question.
- **Ratchets.** Ceilings only, so that parallel root moves don't conflict on one constant.
- **Load.** The concurrency cap went from 3 to 2 under memory pressure (Knut's choice), and suites ran at `-n 4`.

## What worked well

- **Plan mode as a checkpoint.** Every plan was readable in 1–3 minutes. Agents asked good questions instead of guessing, and the questions surfaced every real design decision.
- **Agents' own judgement.** Several agents chose sensibly where the brief didn't say:
  - S3 fixed a sibling bug in `framework/undo.py`.
  - S6 deferred a literal the layering rule forbade touching.
  - S7 added a ratcheted script-import test.
  - S19 caught that action ids are stored by toolbars and keymaps.
  - S21 caught a start date written under the wrong module id.
- **Byte-identical checks.** Comparing real output before and after was cheap and decisive for refactors.
- **DPlanner as the shared state.** Statuses, GitHub refs and about 100 decision, later and handoff notes. A compaction of the director's context lost nothing.
