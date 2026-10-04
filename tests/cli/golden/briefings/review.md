# Step: Review

Project: Widget

## Before you start

First, confirm you can drive DPlanner: run `dplanner skill status`. If the command is missing or the skill is not installed, STOP — do not carry out the step — and tell the developer this step needs the DPlanner skill (`dplanner skill install`).

Then say you are working, before you touch anything: `dplanner agent-work start '<what you are about to do>' --step R3`. A developer may have a DPlanner window open on this plan, and that is what tells them somebody else is editing it — without it they will edit the same steps you are rewriting and be asked to settle collisions they did not cause. Keep it current as you go (`dplanner agent-work set '<what now>' --done N --of M`); setting the step's status when you finish ends it, and if you stop without one, end it yourself (`dplanner agent-work end --step R3`).

This step runs in the checkout itself, with no worktree of its own — a review reads the work it reviews and commits none of its own. Leave the checkout as you found it: no commits, no branch switches, no stashes. Other agents may be in worktrees beside you, and this checkout is the developer's.

WARNING: this plan lives inside the code repository it plans: its files (`project.dproj`, `steps/`, `modules/`) sit in the checkout beside the code. Every `dplanner` command reaches the plan of record — the copy the window shows, in the main checkout — never a branch's copy, so do not edit those files by hand, and do not stage or commit them with your work. Do not move the plan on your own; when the developer asks for it, `dplanner project move <project> --into <plan repository>` (`--init-repo` to start one) moves it, commits both sides and re-points the library, and every verb keeps reaching the plan where it lands.

The project's locations — which repositories it is about, and where each is on this machine (`dplanner location list` prints them again): Code: acme/widget — `<tmp>/widget`.

Other agents may be working beside you in this repository, each in a worktree of its own, and their processes carry the same names and paths as yours. Never kill a process by name or pattern (`pkill -f`, `killall`, `kill $(pgrep …)`): kill only by a pid your own shell started.

## Topology — how this project's graph is shaped

Views are features; a release follows them.

## Work you review

- **S2** Parser — in progress · branch `feat/parser` · PR #12 · worktree `<tmp>/widget/.dplanner-worktrees/s2-parser`

Read the work where it is, and change nothing in it: in its worktree when the line names one here; otherwise from its PR (`gh pr diff <number>`) or its branch (`git fetch origin <branch>`, then read `FETCH_HEAD`) — never by checking its branch out in this checkout.

## Review rounds with S2

Where it stands: S2 has R3's findings for round 1.

### Round 1 — R3's findings

The parser drops the last line.

## Instructions

You review **S2** Parser — *Work you review* says where its work is. You comment; you never commit, push or edit its files: S2's own agent makes every change, in answer to what you find.

Look at it through these lenses:
- **Architecture** — Does the change fit the codebase it lands in — dependencies pointing the way the layers do, a general path generalised rather than a parallel one added beside it, names that say what each thing is, and nothing left behind (a near-duplicate, a dead branch, a stale comment) for the next change to trip on?
- **Security** — Could anything the change reads be turned against it — input reaching a shell string, a query or a path unescaped, a secret logged or committed, a permission or an exposed surface widened, a check a caller can skip?

The review goes in rounds, at most 3 with S2:
1. `dplanner review wait R3` returns once S2 reads ready for review; exit 3 means nothing yet after nine minutes — run it again.
2. `dplanner review start R3` opens the round. Read the work through every lens, then `dplanner review post R3 --file <findings.md>`: each finding with its file and line, what is wrong and what would settle it. Posting puts S2 back in progress.
3. `dplanner agent-state set R3 pending-approval`, then `dplanner review wait R3` for the answer — read the reply and what changed since your last round.
4. Nothing left to ask: `dplanner review approve R3` — S2 is done, and this review is ready to merge, carrying S2's branch and PR. Something left: back to 2 for the next round. After round 3, approve, or hand it to a person: `dplanner review escalate R3 --text '<what they must decide>'`.

## Notes so far

The project's record of what was decided and handed on, one line each. Read the ones that touch your work before you start; every note carries its reasoning. `dplanner note show Widget <id>` prints one and `dplanner note list Widget` the whole log — this index is what reaches *this* step, keeping the most recent where a label has many. `dplanner note add Widget <label> <title>` records yours — the DPlanner skill says when.

Decisions standing (1):
- N1 · Parse line by line (1 October, on S1)

Handoffs from the steps before this one (1):
- N2 · The lexer is half done (2 October, on S1)

## When you are done

This step is R3. A review opens no branch and no PR of its own — approving carries its subject's onto it — and its verdict is its status: `dplanner review approve R3` leaves the subject done and this review ready to merge; `dplanner review escalate R3 --text '<what they must decide>'` leaves it blocked, with a note for a person. Never `status set` either step yourself.
As you work, keep the run state current:
- `dplanner agent-state set R3 working` while you read the work and write findings
- `dplanner agent-state set R3 pending-approval` while you wait on the answer
- `dplanner agent-state set R3 needs-input` when you have a question the developer must answer before you can go on
As you go, leave notes — the project's record, indexed into the briefing of every step that comes after the one you made them on. That is the reach: add `--reach project` when what you settled belongs to the whole plan rather than this branch. `dplanner note add --help` lists the labels:
- `dplanner note add Widget decision '<what you chose>' --step R3 --text '<why>'` for each choice the plan should remember (`--supersedes N3` when it reverses an earlier one)
- `dplanner note add Widget spec-change '<what differs>' --step R3 --text '<what and why>'` where the work had to depart from the spec
- `dplanner note add Widget later '<what>' --step R3` for work you noticed and did not do
- `dplanner note add Widget handoff '<one line the next worker needs>' --step R3 --file -` with what whoever picks up after you must know — where things are, what is half done, what bit you. Title it as the fact it is; the body carries the detail. Add `--for S12` for a step that must read it in full, `--reach project` if every step should see it regardless; `dplanner note attach Widget <id> <file>` for files.
Once the review has its verdict, `dplanner agent-state clear R3` — the verdict's status ends your working claim. If you stop without one, end it yourself: `dplanner agent-work end --step R3` — a banner nobody ended is one nobody believes next time.
