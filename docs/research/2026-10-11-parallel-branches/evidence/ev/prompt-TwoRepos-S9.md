# Step: Land feature/b

Project: TwoRepos

## Before you start

First, confirm you can drive DPlanner: run `dplanner skill status`. If the command is missing or a line reads `missing`, STOP — do not carry out the step — and tell the developer this step needs the DPlanner skill (`dplanner skill install`). `stale` is not a stop: that skill came from another build of DPlanner, so say so and carry on.

Then say you are working, before you touch anything: `dplanner agent-work start '<what you are about to do>' --step S9`. A developer may have a DPlanner window open on this plan, and that is what tells them somebody else is editing it — without it they will edit the same steps you are rewriting and be asked to settle collisions they did not cause. Keep it current as you go (`dplanner agent-work set '<what now>' --done N --of M`); setting the step's status when you finish ends it, and if you stop without one, end it yourself (`dplanner agent-work end --step S9`).

Second, confirm you are in this step's own git worktree: `git rev-parse --show-toplevel` must end in `.dplanner-worktrees/s9-land-feature-b` and `git branch --show-current` must print `feature/b`. If either differs, STOP — do not touch the main checkout — and tell the developer the worktree was not prepared. Commit on that branch; every `dplanner` command still reaches the plan the window shows.

The plan is kept in its own repository, $T/remote/plan.git, apart from the code you are working in (Knutsi/temp-dplanner-test-lib): every `dplanner` command writes to the plan there, never to this checkout, so nothing you commit here carries a plan file and `git status` never shows one.

The project's locations — which repositories it is about, and where each is on this machine (`dplanner location list` prints them again): Code: Knutsi/temp-dplanner-test-lib — `$T/code/lib`; Code — App: Knutsi/temp-dplanner-test-app — `$T/code/app`.

Other agents may be working beside you in this repository, each in a worktree of its own, and their processes carry the same names and paths as yours. Never kill a process by name or pattern (`pkill -f`, `killall`, `kill $(pgrep …)`): kill only by a pid your own shell started.

## Topology — how this project's graph is shaped

# Parallel branches experiment

Project start, then two lines of work in parallel, each on its own feature branch (a cut and a landing), joining at one final Test step. No milestones.

## Work you land

- **S4** P1 mul command — pending · no branch recorded · no worktree of it on this machine
- **S5** P2 div command — pending · no branch recorded · no worktree of it on this machine

## Instructions

Land the feature branch `feature/b` into the repository's default branch: every step on it has merged its work into that branch, and this step brings the branch back as one pull request.

1. `git fetch origin`. Make sure every step under *Work you land* has merged into `origin/feature/b` — its PR reads merged into feature/b, or its branch is contained in it. One that has not: stop, and tell the developer which.
2. Merge `origin/HEAD` into `feature/b` as a merge commit — never a rebase or a squash, since a branch cut from this one keeps its history — settle every conflict, and run the project's checks.
3. `git push origin feature/b`, then `gh pr create --head feature/b`, the title opening with this step's key.
4. Leave `feature/b` on the remote until this step is done: a step still working on it would lose what it starts from.

## When you are done

This step is S9. Its branch and worktree carry that key; open the PR title with it (`S9: …`) and record the branch and the PR on the step as they exist: `dplanner github set S9 --branch $(git branch --show-current)`, then `dplanner github set S9 --pr <number>`. Once the PR is open, set the status (below) straight away: it takes the window's banner down with it.
As you work, keep the run state current:
- `dplanner agent-state set S9 plan-for-review` when your plan is ready to review
- `dplanner agent-state set S9 working` while implementing
- `dplanner agent-state set S9 pending-approval` while waiting on an approval
- `dplanner question ask '<question>' --choice '<answer>' … --step S9` when you have a question the developer must answer before you can go on, then end your turn: unattended, the answer resumes you; in a terminal it says you need input, and you wait for the reply there
As you go, leave notes — the project's record, indexed into the briefing of every step that comes after the one you made them on. That is the reach: add `--reach project` when what you settled belongs to the whole plan rather than this branch. `dplanner note add --help` lists the labels:
- `dplanner note add TwoRepos decision '<what you chose>' --step S9 --text '<why>'` for each choice the plan should remember (`--supersedes N3` when it reverses an earlier one)
- `dplanner note add TwoRepos spec-change '<what differs>' --step S9 --text '<what and why>'` where the work had to depart from the spec
- `dplanner note add TwoRepos later '<what>' --step S9` for work you noticed and did not do
When the work is finished, record it in DPlanner:
- `dplanner status set S9 ready-for-review` and `dplanner agent-state clear S9` — ready for review, never done: a person or a reviewing agent looks next and sets it done. That is the step's work finished, not the mid-run `plan-for-review` above, which is your plan waiting for a look. If nothing needs reviewing, `dplanner status set S9 done --because '<why>'` keeps the reason as a decision note.
- `dplanner note add TwoRepos handoff '<one line the next worker needs>' --step S9 --file -` with what whoever picks up after you must know — where things are, what is half done, what bit you. Title it as the fact it is; the body carries the detail. Add `--for S12` for a step that must read it in full, `--reach project` if every step should see it regardless; `dplanner note attach TwoRepos <id> <file>` for files.
If you cannot finish, `dplanner status set S9 blocked` and say why in the handoff note.
Each of those statuses ends your working claim. If you stop without setting one, end it yourself: `dplanner agent-work end --step S9` — a banner nobody ended is one nobody believes next time.

