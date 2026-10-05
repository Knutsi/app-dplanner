# Ergonomics: friction in the tools

**Summary.** None of these stopped the run, but each cost a round trip, a workaround or a misread state. DPlanner's gaps are about launching and claiming, herdr's about telling *idle* from *finished*, and Codex's about permission prompts.

## DPlanner

- **No headless launch verb.** Run Agent and auto-launch live only in the window. The director had to rebuild them, and got two pieces wrong at first:
  - **It forgot to set in-progress.** The launcher's `record_started` does this, and the briefing never asks the agent to. Knut noticed.
  - **It assumed `agent/…` branches.** A landing works *on* the feature branch, and git won't check out one branch in two worktrees, so the integration worktree had to be detached.
- **Auto-launch only fires for auto-progress or review turns.** A plan of plain `requires` links never launches itself, even with the window open.
- **The standing instruction reaches every briefing**, including the landing's and the review's, where "work in your worktree, open a PR into the branch" doesn't apply.
- **The window's PR refresher marks a step done** as soon as its PR merges into the feature branch. That makes a director's post-merge verification advisory: the plan says done before the integrated branch has been checked.
- **CLAUDE.md sat within 46 bytes of its cap** until S22 moved the mechanical facts out. Each new rule meant trimming another.
- **`NOTES-FOR-APPFRAME.md`'s numbered, append-only sections caused a merge conflict** between parallel agents: S2 and S6 both wrote §77. S22 replaced the numbering with one section per file.

## herdr

- **"Idle" and "done" don't mean finished.** An agent shows done while it waits on its own background shell ("1 shell still running") or on its subagents ("Waiting for 1 background agent to finish"). The watcher had to read the screen to tell them apart.
- **A plan approval sometimes shows as `done`, not `blocked`.**
- **`agent read` refuses more than the visible lines while an agent is blocked**, because of the alternate screen. The plan file whose path is printed at the bottom was the workaround.
- **Text sent into a question's free-text field arrives as a bracketed paste** ("paste again to expand"). It worked, but the screen gives no confirmation.
- **Workspace hygiene is manual.** DPlanner's own herdr launch row creates *a new workspace per run*. The director used one workspace with one tab per live agent instead. DPlanner's row should do the same.

## Claude Code (step agents)

- **Plan mode with auto-mode approval was the right gate.** Plans were thorough, questions were well-formed, and execution needed no further shell prompts.
- **The input box's autosuggestion** ("merge it", "Carry on once the suite finishes") looks like a pending instruction on screen, but nothing has been sent.

## Codex (reviewers)

- **21 sandbox approvals across three reviews.** Network (`gh pr view/diff`), test runs, `dplanner` writes to the plan repo outside the checkout, and `git fetch` each prompted, several of them per command.
  - "Don't ask again" helps, but only for that exact prefix.
  - A reviewer started by DPlanner would need its test, `gh` and `dplanner` commands, and the plan repo, allowed up front.
- **Usage limits mid-review, twice.** The first ended a second round (the director stood in and missed a hole). The second paused R26 for the night.
- **Excellent reproductions.** Every finding came with a failing test, written in a disposable copy under `/tmp` and never in the checkout.
