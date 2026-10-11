# Step: Test together in calcapp

Project: TwoRepos

## Before you start

First, confirm you can drive DPlanner: run `dplanner skill status`. If the command is missing or a line reads `missing`, STOP — do not carry out the step — and tell the developer this step needs the DPlanner skill (`dplanner skill install`). `stale` is not a stop: that skill came from another build of DPlanner, so say so and carry on.

Then say you are working, before you touch anything: `dplanner agent-work start '<what you are about to do>' --step S10`. A developer may have a DPlanner window open on this plan, and that is what tells them somebody else is editing it — without it they will edit the same steps you are rewriting and be asked to settle collisions they did not cause. Keep it current as you go (`dplanner agent-work set '<what now>' --done N --of M`); setting the step's status when you finish ends it, and if you stop without one, end it yourself (`dplanner agent-work end --step S10`).

Second, confirm you are in this step's own git worktree: `git rev-parse --show-toplevel` must end in `.dplanner-worktrees/s10-test-together-in-calcapp` and `git branch --show-current` must print `agent/s10-test-together-in-calcapp`. If either differs, STOP — do not touch the main checkout — and tell the developer the worktree was not prepared. Commit on that branch; every `dplanner` command still reaches the plan the window shows.

The plan is kept in its own repository, $T/remote/plan.git, apart from the code you are working in (Knutsi/temp-dplanner-test-lib): every `dplanner` command writes to the plan there, never to this checkout, so nothing you commit here carries a plan file and `git status` never shows one.

The project's locations — which repositories it is about, and where each is on this machine (`dplanner location list` prints them again): Code: Knutsi/temp-dplanner-test-lib — `$T/code/lib`; Code — App: Knutsi/temp-dplanner-test-app — `$T/code/app`.

Other agents may be working beside you in this repository, each in a worktree of its own, and their processes carry the same names and paths as yours. Never kill a process by name or pattern (`pkill -f`, `killall`, `kill $(pgrep …)`): kill only by a pid your own shell started.

## Topology — how this project's graph is shaped

# Parallel branches experiment

Project start, then two lines of work in parallel, each on its own feature branch (a cut and a landing), joining at one final Test step. No milestones.

## Instructions

The final test step, in calcapp: make `main` also handle `add A B` and `sub A B` by calling mathlib's `add` and `sub` — mathlib is the sibling repository github.com/Knutsi/temp-dplanner-test-lib, whose add/sub work should have landed on its main by now. Make calcapp depend on mathlib from that repository's main (pyproject dependency on the git URL), write `tests/test_together.py` that runs all four commands through `main`, and run the whole suite. If mathlib's main does not have add and sub, do NOT write them yourself — stop and report what you found and where you looked.

## Notes so far

The project's record of what was decided and handed on, one line each. Read the ones that touch your work before you start; every note carries its reasoning. `dplanner note show TwoRepos <id>` prints one and `dplanner note list TwoRepos` the whole log — this index is what reaches *this* step, keeping the most recent where a label has many. `dplanner note add TwoRepos <label> <title>` records yours — the DPlanner skill says when.

Decisions standing (4):
- N2 · calcapp main raises ValueError on bad input; ints stay ints (11 October, on S4)
- N4 · Done without review (11 October, on S4)
- N5 · calcapp div is true division and raises ValueError on zero divisor (11 October, on S5)
- N8 · Done without review (11 October, on S5)

Handoffs from the steps before this one (6):
- N1 · add() is in mathlib/ops.py; PR #1 into feature/a (11 October, on S2)
- N3 · calcapp main(argv) handles mul A B in calcapp/cli.py (PR #1 into feature/b) (11 October, on S4)
- N6 · calcapp main(argv) handles div A B in calcapp/cli.py (PR #2 into feature/b) (11 October, on S5)
- N7 · sub() is in mathlib/ops.py; PR #2 into feature/a (11 October, on S3)
- N9 · feature/a is up for landing as PR #3 into main (11 October, on S7)
- N10 · feature/b is open for landing as PR #3 into main (11 October, on S9)

## When you are done

This step is S10. Its branch and worktree carry that key; open the PR title with it (`S10: …`) and record the branch and the PR on the step as they exist: `dplanner github set S10 --branch $(git branch --show-current)`, then `dplanner github set S10 --pr <number>`. Once the PR is open, set the status (below) straight away: it takes the window's banner down with it.
As you work, keep the run state current:
- `dplanner agent-state set S10 plan-for-review` when your plan is ready to review
- `dplanner agent-state set S10 working` while implementing
- `dplanner agent-state set S10 pending-approval` while waiting on an approval
- `dplanner question ask '<question>' --choice '<answer>' … --step S10` when you have a question the developer must answer before you can go on, then end your turn: unattended, the answer resumes you; in a terminal it says you need input, and you wait for the reply there
As you go, leave notes — the project's record, indexed into the briefing of every step that comes after the one you made them on. That is the reach: add `--reach project` when what you settled belongs to the whole plan rather than this branch. `dplanner note add --help` lists the labels:
- `dplanner note add TwoRepos decision '<what you chose>' --step S10 --text '<why>'` for each choice the plan should remember (`--supersedes N3` when it reverses an earlier one)
- `dplanner note add TwoRepos spec-change '<what differs>' --step S10 --text '<what and why>'` where the work had to depart from the spec
- `dplanner note add TwoRepos later '<what>' --step S10` for work you noticed and did not do
When the work is finished, record it in DPlanner:
- `dplanner status set S10 ready-for-review` and `dplanner agent-state clear S10` — ready for review, never done: a person or a reviewing agent looks next and sets it done. That is the step's work finished, not the mid-run `plan-for-review` above, which is your plan waiting for a look. If nothing needs reviewing, `dplanner status set S10 done --because '<why>'` keeps the reason as a decision note.
- `dplanner note add TwoRepos handoff '<one line the next worker needs>' --step S10 --file -` with what whoever picks up after you must know — where things are, what is half done, what bit you. Title it as the fact it is; the body carries the detail. Add `--for S12` for a step that must read it in full, `--reach project` if every step should see it regardless; `dplanner note attach TwoRepos <id> <file>` for files.
If you cannot finish, `dplanner status set S10 blocked` and say why in the handoff note.
Each of those statuses ends your working claim. If you stop without setting one, end it yourself: `dplanner agent-work end --step S10` — a banner nobody ended is one nobody believes next time.

