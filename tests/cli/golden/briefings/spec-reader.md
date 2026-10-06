# Step: Spec reader

Project: Widget

## Before you start

First, confirm you can drive DPlanner: run `dplanner skill status`. If the command is missing or the skill is not installed, STOP — do not carry out the step — and tell the developer this step needs the DPlanner skill (`dplanner skill install`).

Then say you are working, before you touch anything: `dplanner agent-work start '<what you are about to do>' --step S4`. A developer may have a DPlanner window open on this plan, and that is what tells them somebody else is editing it — without it they will edit the same steps you are rewriting and be asked to settle collisions they did not cause. Keep it current as you go (`dplanner agent-work set '<what now>' --done N --of M`); setting the step's status when you finish ends it, and if you stop without one, end it yourself (`dplanner agent-work end --step S4`).

Second, confirm you are in this step's own git worktree: `git rev-parse --show-toplevel` must end in `.dplanner-worktrees/s4-spec-reader` and `git branch --show-current` must print `agent/s4-spec-reader`. If either differs, STOP — do not touch the main checkout — and tell the developer the worktree was not prepared. Commit on that branch; every `dplanner` command still reaches the plan the window shows.

WARNING: this plan lives inside the code repository it plans: its files (`project.dproj`, `steps/`, `modules/`) sit in the checkout beside the code. Every `dplanner` command reaches the plan of record — the copy the window shows, in the main checkout — never a branch's copy, so do not edit those files by hand, and do not stage or commit them with your work. Do not move the plan on your own; when the developer asks for it, `dplanner project move <project> --into <plan repository>` (`--init-repo` to start one) moves it, commits both sides and re-points the library, and every verb keeps reaching the plan where it lands.

The project's locations — which repositories it is about, and where each is on this machine (`dplanner location list` prints them again): Code: acme/widget — `<tmp>/widget`.

Other agents may be working beside you in this repository, each in a worktree of its own, and their processes carry the same names and paths as yours. Never kill a process by name or pattern (`pkill -f`, `killall`, `kill $(pgrep …)`): kill only by a pid your own shell started.

## Topology — how this project's graph is shaped

Views are features; a release follows them.

## Flows into

- **Sign in**, from auth
  > Operators MUST

## Instructions

Read the auth spec.

## Notes so far

The project's record of what was decided and handed on, one line each. Read the ones that touch your work before you start; every note carries its reasoning. `dplanner note show Widget <id>` prints one and `dplanner note list Widget` the whole log — this index is what reaches *this* step, keeping the most recent where a label has many. `dplanner note add Widget <label> <title>` records yours — the DPlanner skill says when.

Decisions standing (1):
- N1 · Parse line by line (1 October, on S1)

Handoffs from the steps before this one (1):
- N2 · The lexer is half done (2 October, on S1)

## When you are done

This step is S4. Its branch and worktree carry that key; open the PR title with it (`S4: …`) and record the branch and the PR on the step as they exist: `dplanner github set S4 --branch $(git branch --show-current)`, then `dplanner github set S4 --pr <number>`. Open it against `main`: `gh pr create --base main`. Once the PR is open, set the status (below) straight away: it takes the window's banner down with it.
As you work, keep the run state current:
- `dplanner agent-state set S4 plan-for-review` when your plan is ready to review
- `dplanner agent-state set S4 working` while implementing
- `dplanner agent-state set S4 pending-approval` while waiting on an approval
- `dplanner agent-state set S4 needs-input` when you have a question the developer must answer before you can go on
As you go, leave notes — the project's record, indexed into the briefing of every step that comes after the one you made them on. That is the reach: add `--reach project` when what you settled belongs to the whole plan rather than this branch. `dplanner note add --help` lists the labels:
- `dplanner note add Widget decision '<what you chose>' --step S4 --text '<why>'` for each choice the plan should remember (`--supersedes N3` when it reverses an earlier one)
- `dplanner note add Widget spec-change '<what differs>' --step S4 --text '<what and why>'` where the work had to depart from the spec
- `dplanner note add Widget later '<what>' --step S4` for work you noticed and did not do
When the work is finished, record it in DPlanner:
- `dplanner status set S4 ready-for-review` and `dplanner agent-state clear S4` — ready for review, never done: a person or a reviewing agent looks next and sets it done. That is the step's work finished, not the mid-run `plan-for-review` above, which is your plan waiting for a look. If nothing needs reviewing, `dplanner status set S4 done --because '<why>'` keeps the reason as a decision note.
- S5 collects this step's work: it may start as soon as you set ready-for-review, and takes your branch or PR from there — so push everything and open the PR first. Leave this step's done to it.
- `dplanner note add Widget handoff '<one line the next worker needs>' --step S4 --file -` with what whoever picks up after you must know — where things are, what is half done, what bit you. Title it as the fact it is; the body carries the detail. Add `--for S12` for a step that must read it in full, `--reach project` if every step should see it regardless; `dplanner note attach Widget <id> <file>` for files.
If you cannot finish, `dplanner status set S4 blocked` and say why in the handoff note.
Each of those statuses ends your working claim. If you stop without setting one, end it yourself: `dplanner agent-work end --step S4` — a banner nobody ended is one nobody believes next time.
