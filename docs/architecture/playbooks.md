# Playbooks — stages, gates, loop-back, presets and headless invocations

The rules are in `.claude/rules/playbooks.md`; this is why they are what they are. The research
behind them is `docs/research/2026-10-03-playbooks/` (the shape, failures, the floor) and
`docs/research/2026-10-07-headless-agents/` (what the three CLIs do headless). Where the two
differ from this file, this file wins.

*The model, the presets, the step aspect and the project's defaults are
`modules/step_playbook/` (S15), and so is the engine (S16): `passes.py` reads where a pass
stands, `engine.py` advances it — *How the engine drives a pass* below.*

## A playbook is a list of stages around one step

Running an agent on a step is one act: a terminal opens, an agent works, a person looks. A
**playbook** is the alternative to that act, chosen **per step**: a short list of stages that
plan the work, do it, and decide whether it is good enough. It replaces two things the plan
used to spell in cards and links — a review step after the work, and an auto-progress link
to whatever takes the work next. Both made a second card do what is really a fact about how
one step gets done, and a plan of twenty steps grew twenty more. So the graph stays the plan
and the playbook stays on the step: **one card, whatever the stages** — it wears a phrase
saying where its playbook stands (*The mark on the one card*), never a card per stage.

**The stages are a list, not a graph.** Every case named in the research is a list of gates
looping back to the work. A free stage graph is the visual workflow builder that "is squeezed
from both directions", and it would need an editor nobody asked for. A list needs none: its
order is the order the stages run in.

**The kinds of stage:**

| Kind | Who acts | What it is |
|---|---|---|
| `plan` | the implementer role, read-only | the agent reads the step and answers with a plan |
| `execute` | the implementer role, allowed to edit | the step's work: code, commits, a PR |
| `review` | an agent: the same one in a fresh session, or another | a gate: reads the work and returns a verdict |
| `person` | a person — the step's owner | a gate: approve, or send back with a note |
| `coordinator` | the coordinator agent driving the run, else a person | a gate: pass, send back, or escalate to a person |
| `progress` | DPlanner | the step's work is accepted on its feature branch, so what waits on it can start |

A **gate** is any stage that decides — `review`, `person`, `coordinator`. Every gate ends in a
**verdict**: *pass* or *changes*. Nothing else is a verdict (*A failure is never a verdict*).

**A gate that asks for changes sends the work back to the nearest earlier work stage** — the
`execute` before it, or the `plan` when the gate stands between plan and execute — and the
stages after that one run again, in order. There is no `on_changes` field naming where to
go: the research's one escape hatch had no preset that needed it, and *the nearest earlier
work stage* says what every preset means. A playbook with no work stage before its gate —
*Review only* — sends the work to a **fix**: an `execute` of the implementer role, briefed with
the findings, in the step's own worktree, recorded as the stage `fix` — the one stage id a
playbook's list does not name.

**A playbook started on a step already at Ready for review starts at its first gate.** Work a
person did by hand, or a run that finished before the playbook was chosen, is reviewed by the
same playbook without a preset of its own for it.

**A pass stands.** A gate that passed is not run again because a later gate's fix changed the
code. Re-reviewing everything after every fix doubles the cost of a two-gate playbook for a
small gain; the research's exception — re-review when the fix touches a file the earlier gate
flagged — is left until a real run shows the need.

**`progress` is where *progress to the next step* happens.** The stage accepts the step's work
on its feature branch: DPlanner merges the step's PR into the branch, which sets the step done
(`record_merged(accepted_by_merge=)`, already the rule for a member's PR merged into an open
stretch). Accepted, the step no longer holds up what waits on it, so the next ready step **may
start** — started by the coordinator driving the selection or by a person, never by DPlanner
itself (*Decided at S4*, 2). **It is
refused on the mainline**: a step whose `BranchPlan` aims its PR at the default branch never
merges without a person, so there the stage becomes a `person` gate and the card says why.
That is Knut's condition — *only on a branch other than main* — and it is checked at run time,
because a step moves onto and off a branch with an ordinary edit.

## A gate gets two rounds, then somebody decides

A gate's `rounds` is how many **verdicts** it may give in a pass: 2 by default, at most 5. A
round is a verdict given, never an attempt made — a reviewer that crashed, or whose session was
replaced by a fresh one, gave no verdict and spent no round. *Changes* on the last round does
not buy another round. It **escalates**: a question of kind `decision` and purpose `round-cap`,
with the choices *accept as is*, *one more round*, *take over*, *stop*, and every finding still
open shown with both positions — the gate's and the implementer's reason for declining it. The
question goes to the coordinator when one drives the run, and to a person otherwise; the
coordinator may answer it or escalate it to a person. **There is never a silent extra round**:
two rounds and then a person is what the 2026-10-01 orchestration research settled, and an agent
pair arguing a third time is the debate the evidence advises against.

**The implementer may decline a finding, with a reason.** It does not argue back in a chat
loop; it says *no, because…* in its fix, and the gate's next round sees the reason. A finding
the gate still holds at the cap is what the escalation is about.

## A loop-back resumes the session that did the work

When a gate asks for changes, the work stage runs again. Two ways were weighed:

| Way | Cost |
|---|---|
| **Fresh, with the findings in the briefing** | The agent rebuilds its understanding of the step from scratch: re-reading the code, re-running what it ran. Clean context, every time. |
| **Resume the work stage's session** (chosen) | One re-read of the session's prefix, uncached if the cache has gone cold. The agent already knows why it did what it did. |

**Resume is the default, and fresh is the fallback.** The headless design is park and resume
(`docs/research/2026-10-07-headless-agents/`): a question, a plan approval or a usage limit
ends the process, and the answer resumes the *same session*, hours later if need be. The
session id is already the run's durable handle, so a loop-back is one more resume with one
more prompt — the findings — and no second mechanism. The 10-03 note's rule (resume only
inside the cache's lifetime) priced per-token API use; on a subscription an uncached prefix is
quota, and it is still less than a fresh agent re-deriving the step.

**It runs fresh only when it must**: there is no session id, the resume is refused or fails,
or the session is past a context ceiling (about 150k tokens, read from the harness's stream),
where compaction would lose the step anyway. Either way the findings are on the review run
(*The run record is the ledger*), so a fresh run is briefed from the same facts a resumed one
was prompted with.

**A review is always fresh.** *Review (same agent)* means the implementer's harness and model
in a **new** session, never the implementer's own: a reviewer that shares the implementer's
context measured worst of every arrangement in the evidence. The second session is the point.
*Review (other agent)* is the reviewer role — another vendor's CLI — and falls back to the
same vendor in a fresh session when only one CLI is usable here, saying so on the card
(*· same vendor*): it is still the fresh-context control, and refusing would teach nothing.

## Who acts: roles, profiles and the four actors

**A role names a harness and, optionally, a model** — `implementer` and `reviewer` are the two
the presets use. A role is portable: it says *claude*, never a path or a terminal. At launch a
role maps to **the first launch profile whose agent command runs that harness**, and a role
no profile runs is refused rather than swapped for the default, which may be the very agent
whose work is reviewed — the lookup `launch_unattended` made, which left with it in S11; the
launch itself is `agent_launch/launch.py`'s, handed a `Profile` (*One launch under both
surfaces* in `agents.md`). A headless stage uses only the profile's agent half — no stage
opens a terminal. **Whether a role's agent can run here** — installed, a version, signed in — is
`agent_launch/availability.py`'s `why_not` over the roles' harnesses, read from a short cache
and never probed on the UI thread, so Run Playbook greys a playbook with the reason, and the
reviewer's *same vendor* fallback reads the same answer (`agents.md`'s *Installed is not
usable*).

**Four actors, and each is a record somebody else can read.** An agent stage is a run (S3's
record). A `person` gate, a `coordinator` gate and an escalation are each a **question** — one
file under the project's `questions/` — so the inbox, the coordinator and the engine read one
kind of thing. A gate that stands after a plan asks a `plan-approval` (the plan is its body);
a gate after the work and an escalation ask a `decision` (*pass*, or *changes* with a note).
The two gates differ only in who may answer: **the coordinator may answer a `coordinator`
gate, and must escalate a `person` gate** (the question's `escalated` state) rather than
answer it; with no coordinator driving the run, a person answers both. `progress` is
DPlanner's own act, and its trace is the merge and the status it sets, both already recorded.

## The presets

Following *sane defaults, options laid out*, a step picks a playbook from a list; nothing is
written by hand. Knut named seven, and two are added.

| Id | Name | Stages |
|---|---|---|
| `execute` | Execute | execute |
| `plan-execute-coordinator` | Plan → execute → coordinator review | plan, execute, coordinator |
| `plan-execute-person` | Plan → execute → human review | plan, execute, person |
| `plan-execute-progress` | Plan → execute → progress | plan, execute, progress |
| `plan-execute-review-self` | Plan → execute ⇄ review (same agent) | plan, execute, review (same) |
| `plan-execute-review-other` | Plan → execute ⇄ review (other agent) | plan, execute, review (other) |
| `plan-person-execute` | Plan → human review → execute | plan, person, execute |
| `review-only` | Review only | review (other, the whole PR against its base), person |
| `spike` | Spike | plan (research, read-only), person |

- **Execute** runs in the auto-approving mode and stops at Ready for review, like Run Agent
  but headless.
- In **Plan → human review → execute** the person's *changes* goes back to the plan, by resume,
  and *pass* resumes the same session to execute — the headless form of today's plan mode.
- Where a plan is not followed by a gate, it is not approved by anyone: the plan stage
  records the plan (the run directory keeps DPlanner's copy) and execute resumes with *the plan
  is approved, implement it*. The plan is there to be read, by a person or the coordinator,
  and to be cheap to stop.
- **Review only** is what review steps were used for on a branch landing. The landing's own
  run opens the PR from the branch; the playbook then reviews the whole branch once,
  cross-vendor, and ends at a person. That is the person gate paid for once per branch, where
  the floor research puts it, instead of once per step.
- **Spike** is for research and design steps: nothing to execute, and the output — a plan, a
  report, a design — is for a person to read. The person's approval sets the step done.

**Playbooks are built-in only, for now.** The presets are Qt-free data in
`modules/step_playbook/presets.py`; there are no playbook files in the plan repository. A file there would be the first
hand-authored configuration in a JSON codebase, and a file an agent can edit on its branch is
input to the next run, which needs its own rule (a worker reads playbooks from the mainline
only). Nine presets cover the brief. Custom playbooks come later (*Decided at S4*, 1).

**A stage's kind is a `StageRole`**, never a second `StageKind`: `domain/headless.py`'s
`StageKind` is the three turns a harness can run, and a playbook's six roles include three no
agent runs. `StageRole.agent_stage` maps the three onto it, so one word never names two types
and an import of the wrong one cannot type-check.

## A step names its playbook; a project names its default

**The step aspect** holds the choice: `{"format": 1, "playbook": "<preset id>"}`, with
optional overrides — `rounds` (every gate's cap) and `reviewer` (a harness id for the reviewer
role) — and **absence encodes the default**, as the review aspect's settings do, so a later
change of default reaches every step that never chose. Its id is `step_playbook`, and the
project's entry lives under the same id. `aspect.py`'s `resolve` is the order below and
`inherited` is what *Default* means for one step — the row the panel's dropdown names.

**Which playbook a step runs:**
1. its own aspect;
2. else, on a landing (a step carrying `branch_land`), the project's landing default —
   *Review only* unless the project names another;
3. else the project's default, kept as project-level module data
   (`{"default": …, "landing": …}`);
4. else none: the step has Run Agent, as today, and *Run Playbook ▸* still lists every preset.

**A pass pins its settings.** A **pass** is one run of a playbook on a step, from *Run
Playbook* until it ends. At its start the engine resolves what the pass will run — the preset
id and its revision (a built-in preset's number, raised whenever its stage list changes), the
round cap, the roles' harnesses, and every override the step's aspect had — and writes that
once, on the pass's first record (*The run record is the ledger*). An edit of the step's choice
therefore applies to the next pass, never to the one under way, even when the pass is parked
for days, and the step panel says so.

## The mark on the one card

The card wears **one phrase** derived from the step's latest runs and questions: *Planning*,
*Executing*, *Review 1/2*, *Fixing (round 1)*, *Waits for you · plan approval*, *Parked until
21:30*, *Escalated*, *Stopped*, *Done*. It is never stored — a stored phrase could disagree with
the runs it summarises — and it is `passes.standing`'s, beside `due` and reading the same
records, so the card's strip and `playbook show` say the same words. It rides **a strip of its
own under the card**, below the branch strip, with the stages behind it in the strip's tooltip
— not the agent run's chip, as first written: the chip says a run is live and a pass spends
most of its life parked, waiting or between stages, when no run is. A pass that ended shows
for a day after its last record (`engine.ENDED_SHOWN`). Stages are read in the step panel's
Playbook section and the run conversation, never as cards; `canvas.md`'s *A card running a
playbook says where its pass stands* has the canvas's half.

**Until a pass has records, the mark is a medallion.** Nothing derives a phrase before the
engine writes runs with a `pass`, and a card carries no words (`canvas.md`), so S15 gives a
step whose **own** aspect names a playbook the `playbook` glyph among its medallions. An
inherited default is not marked: every landing would wear it beside its `merge` medallion,
and a project default would mark every card. The phrase, once a pass has records, rides the
playbook strip beside it.

## A failure is never a verdict

How a turn **ended** is classified per harness from its stream, its result and its exit:
*done*, *asked*, *denied*, *limit*, *failed*, or *stopped* (S3's turn endings). Only a gate's
typed verdict is a verdict. *Asked* and *denied* park the run on a question; *limit* parks it
until the reset; *failed* retries with backoff and then asks a person; *stopped* is a person's
or a fence's. **None of them spends a round** — a reviewer that hit its quota did not ask for
changes, and counting it would escalate work nobody judged.

## The run record is the ledger

A playbook keeps no record of its own. **Every agent stage attempt is one run** in the
project's `ledger/` — S3's format 2, one file per run, one writer — and every gate a person or
the coordinator answers is one question under `questions/`. The playbook's state is read from
those, the way a review step's state was read from its stamps.

**What the run carries for a playbook:**
- `pass` — the pass's id, minted at *Run Playbook* like a run's, carried by every run and gate
  question of the pass. Identity is never derived from the order of the records.
- `settings` — on the pass's first record only, the resolved settings the pass pinned
  (*A pass pins its settings*): `{preset, revision, rounds, roles, overrides}`. The first record
  is the pass's first run, or its first gate question when the pass begins at a `person` or
  `coordinator` gate.
- `stage` — the stage's **id in that playbook**: its kind, numbered if the kind repeats in the
  list (`review`, `review-2`). An id rather than an index, so a run stays readable after the
  preset list is reordered.
- `attempt` — **how many times this stage has run in this pass, counting this one**, from 1.
  It counts executions, not rounds: a gate's round is the number of verdicts it has given in
  the pass (*A gate gets two rounds, then somebody decides*), so a review that failed and was
  replaced is attempt 2 of round 1. For a work stage it is 1 plus the fixes so far, and any
  replacements. A resume *within* an attempt — an answer, a limit's reset, *Retry
  now* — is another **turn** of the same run. **A loop-back is a new run**, the next attempt,
  naming the same `session` when it resumes it: the attempt it fixes is over (its last turn
  ended *done*, and `ended` is written once), and the next review's verdict must say which
  attempt it judged. So a new attempt is a fresh session *or* a loop-back, and only an answer,
  a reset or a retry is a turn.
- `verdict` — on a review run, the typed final message: `{outcome, summary, findings[]}`.
- `declined` — on a fix run, each finding the implementer declined: `{finding, reason}`,
  `finding` naming the review run and the finding's place in its list.
- `turns` — each process invocation and how it ended.

A gate a person or the coordinator answers has no run, so its question carries the same
`pass`, `stage` and `attempt` beside the step, and a typed **`purpose`**:
- `gate` — a `person` or `coordinator` gate asking for its verdict;
- `round-cap` — *changes* on a gate's last round (*A gate gets two rounds, then somebody
  decides*), with the open findings and both positions;
- `escalation` — anything else the pass cannot settle alone, raised by the engine or the
  coordinator: a person is asked to stop, take over or go on.

State stays derived — where a pass stands, the round, the card's phrase — but identity is
stored: which pass a record belongs to and why a question was asked are fields, read, never
reconstructed from ordering. The engine derives whatever is due from the pass's records and
launches it **once**: a stage attempt is due when its predecessor's verdict says so and no run
for it exists, and the run file, written before the process spawns (`launch.py`'s rule, *One
launch under both surfaces* in `agents.md`), is the claim.

### What of the review rounds ledger survives

The `review_rounds` entry (`modules/step_review/aspect.py`, removed at S6 — `git show
dfc0de0:src/dplanner/modules/step_review/aspect.py`) was a list of rows of texts and stamps on
the step that asks. Its lessons survive; its rows do not. Each fact moves to the
record that already owns it:

| The round fact | Becomes |
|---|---|
| `opened` | the review run's `launched` |
| `findings` (free text) | the review run's **verdict**: `{outcome, summary, findings[]}`, each finding with `severity`, `file`, `line`, `text` and `evidence` — the typed final message (`--json-schema`, `--output-schema`), recorded by the supervisor, never posted by the agent |
| `posted` | the review run's last turn ending *done* with a verdict |
| `taken` | the next `execute` attempt's `launched` |
| `reply` / `replied` | that execute run's `declined` — each `{finding, reason}`, naming a finding on the review run — and its end |
| `approved` | a verdict of *pass*: on the review run, or the answer to a `person` / `coordinator` question |
| `escalated` + `note` | a question of kind `decision`, purpose `round-cap`, its text the open findings and both positions |
| `asker_turn_launched` / `party_turn_launched` | the run file's existence for that stage and attempt — the claim |
| `with` (the party) | gone: the party is always the step itself |

**What survives as rules:**
- **State is derived, never stored.** Where a playbook stands, whose move it is, the round and
  the card's phrase are read from runs and questions, as a round's state was read from which
  stamps were there.
- **A newer build's keys are kept** when a record is rewritten, as `said()` keeps them.
- **A launch is claimed once, by a record that exists before the process does** — the turn
  stamp's job, now the run file's.
- **A conversation still going is a section of the briefing**, built from the runs and the
  questions of the pass, so a fresh fix is briefed with every finding and every answer.
- **One builder names each message** for the panel and the conversation dialog alike — the
  `message_rows` / `where_it_stands` pair S6 removed (`step_review/conversation_dialog.py` at
  `dfc0de0`) is the shape to rebuild over runs and questions.

**What left** (S6, *Remove review steps*): a review as a step (`Kind.REVIEW`, the `R` letter,
its subject read off `requires`); lenses as a step setting — they become the review stage's
prompt; `review wait`, since no process waits; the agent-written `post`, `approve` and
`escalate`; and `due_turns`. Auto-progress and the window's auto-launch left in S5, a
collector's upstream conversations with them, keeping the unattended launch's intent and
claim as `launch_unattended` for `agent run` — which S11 then replaced with the one launch
both surfaces run (`agents.md`'s *One launch under both surfaces*).

## How the engine drives a pass

**Nothing waits for the next stage.** A pass moves when a stage's run ends or one of its
questions is answered, and each of those starts `dplanner playbook advance <step>` in a
process of its own: the supervisor, when a run that carries a `pass` ends `done`
(`supervisor.advance_detached`), and `inbox.answer`, when the answer is to a pass's own
question. A person can run the verb too. The alternative was a process that outlives every
stage to start the next. That process would wait — through a review, a parked question and a
weekend — which is the one thing the headless design forbids.

**An advance reads, decides and acts once.** `step_playbook/engine.py` takes the step's
launch lock, waiting for it, because the holder is a launch moments from done. It reads the
pass's runs and questions oldest first and asks `passes.due` what is next. Then it does that
one thing:
- launch the stage's run, through `agent_launch`'s `StageLauncher`;
- write the gate's question;
- run `progress`;
- finish.

Each act writes its record before anything else can see the pass move: a run's file before
its process, the next record before the answer it acted on is marked consumed
(`questions.settled_by_pass`). So a crash leaves an answer to act on again, never one lost,
and two advances at once act once. A pass's records are stamped to the microsecond, because
"oldest first" must hold inside one second. Only the machine that launched a pass advances
it; another machine's advance says so and does nothing.

**`due` reads the latest record.**

| The latest record | What is due |
|---|---|
| a run not over | nothing — its supervisor has it |
| a run stopped or fenced, a withdrawn question, *Stop* | nothing — the pass is halted |
| a work run done | the next stage, skipping a gate that already passed in the pass |
| a review with a verdict of *pass* | the next stage |
| a review with *changes* | a loop-back, or a `round-cap` question on the last round |
| a review done with no verdict | an `escalation` question: *Retry*, *Accept as is*, *Stop* |
| an open question of the pass | nothing — somebody answers it |
| an answered gate question | what the answer says |
| a refusal card answered *Retry now*, or by the clock | what was due before the card |

A step that reads done completes its pass whatever is left. The end of the list completes the
pass too. A playbook with nothing to merge — no `execute`, no `review`: the *Spike* — sets its
step done there, since its approval was the point.

**Answers are labels, or words.** A gate offers *Pass*, *Changes* and *Stop*, and only the
label itself — case, spacing and a closing stop aside — means it. Any other words are
*changes*, and the words are the finding the work is sent back with: "Pass only after fixing
X" sends the work back to fix X. Reading the start of an answer would have let a condition
read as an approval. A round cap offers *Accept as is*, *One more round*, *Take over* and
*Stop*; each *One more round* raises that gate's cap for the pass by one, and the fix it buys
is handed the gate's latest findings — a review's, or a person's note. Nothing reads where an
answer came from: the coordinator and a person answer through the same door, and
`may_answer` keeps the coordinator off a `person` gate and off a `progress` gate
(`questions.PERSON_ONLY`).

**A pass that cannot act asks, rather than stopping silently.** When the next stage's launch
is refused — its account held (`limits.hold`), no profile running its harness any more,
anything `prepare_run` or the spawn refuses — or `progress` cannot merge, the advance writes
a card on the pass: purpose `escalation`, at the stage it could not run. A held account's
card is `limit`, with the hold's reset, and a detached `playbook wake` waits for that reset,
answers the card for the clock and advances (`engine.wake`). Any later advance answers a
lapsed one too, which covers a waker that died with its machine. Every other refusal is
`blocked`. *Retry now* — the label `inbox.retry_now` writes — answers either kind, and the
pass does again what it could not; *Stop* halts it. The alternative was a pass whose advance
exited with nothing written: no run parked, no card shown, and no reset or answer that could
ever wake it.

**A session continues by being named, never by a flag.** A run's launch resumes a session
exactly when an earlier run of its pass names the same one (`Session._continues`). The
alternative was a field the engine stores and the supervisor obeys, which is a second
statement of one fact. A work stage resumes the implementer's latest session in the pass, so
execute continues its plan — briefed *The plan is approved* — and a fix continues its execute.
A review never does. Every stage's `prompt.md` is the step's whole briefing plus what the
stage hands over (`agent_briefing/stages.py`). If the resume fails, the supervisor's retry
starts a fresh session (its existing rule), and that session knows everything the resumed
one was told: this is the design's fresh fallback, with nothing added. A plan and a review
close with their own words, in place of the work's *ready for review*: answer in the final
message, and touch neither the status, a commit nor a PR.

**A review owes its verdict, once more.** A verdict is the review's typed final message only
when it validates against `VERDICT_SCHEMA` whole (`headless.verdict_of`). opencode has no
schema flag, and its reader takes any JSON final text as typed, so a bare
`{"outcome": "pass"}` would otherwise have passed the gate. A review that ends `done` without
one is asked for it again in its own session: one turn, prompt `verdict`, which spends no
round. If it still gives none, the run ends without a verdict, and the pass escalates. One
nudge is cheap; a loop of nudges is the silent extra round the design refuses.

**A fix declines by number.** The findings are handed to a fix numbered in its briefing. Its
typed final message (`TURN_SCHEMA`'s `declined`) names the ones it will not act on by those
numbers. The engine writes what each number refers to into the run directory's
`findings.json`, and the supervisor records `declined` as references to the review run, or to
the question for a person's note. The next round reads each finding with its reason beside it,
and so does the round cap's question.

**`progress` checks everything before it merges, because a merge cannot be taken back.** The
launch reads the step's `BranchPlan` as it stands now (`StageLauncher.merge_target`): the
feature branch the PR must go into, and the step's own branch it must come from. A step moved
off its stretch while its pass ran reads as the mainline. Then `github`'s `accept_by_merge`
merges with a merge commit (`gh pr merge --merge`, the history this project keeps) only when
all of these hold:
- the branch is not the repository's default;
- the PR goes from exactly the step's branch into exactly that branch;
- the step waits on review or its merge.

It then records the PR as `github refresh` would and accepts the step through the same
`finish_merged`. When the work goes to the mainline it merges nothing — `gh` is not even
asked — and the stage becomes a person-only `gate`. Any other mismatch is a `blocked` card.

**One verb starts a pass: `agent run <step> --playbook [<preset>]`.** It is Run Agent's
launch, in Run Agent's order: the gate and the lock; the worktree; the pass's first record
(its first run, nothing started, or its first gate's question); the in-progress claim, saved;
and only then the start. A crash between the claim and the start leaves a record with no
turn, which `supervisor.revive` starts while the claim stands. A flush that fails takes the
record back. A pass's later stage is claimed by its pass rather than by the step's status, so
revive starts that one whatever the step reads. The profile's agent is the implementer, and
the pass's settings are pinned (`passes.pinned`). A role that no launch profile runs headless
is refused before anything is written. On a step at Ready for review, the pass starts at its
first gate and claims nothing, because the work is not taken up again. **A step has one pass
at a time**: until its latest pass has reached its end — complete, stopped, or given up by a
person — another `--playbook` is refused with the reason (`engine.active`, which asks
`passes.due`), between stages too, while a finished stage waits for its advance. Replacing a
pass is a verb for later. `revive` runs before that check, so a run it restarts reads as
under way; and a pass whose first run never began — no turn, no supervisor, its step not
claimed, since a start only ever follows the saved claim — is no pass: its launch died
before the claim, and a retry deletes it and begins afresh rather than refusing. A separate `playbook run` would have been a second launch flow, with the gates
written twice.

**Run Playbook in the window runs the verb.** *Step ▸ Run Playbook ▸ <playbook>*, beside Run
Agent's child menu and in the card's right-click with it, starts a pass by running `dplanner
agent run <step> --playbook <id>` as a process of this build (`supervisor.dplanner_argv`), to
its end on a task, and says its one line in the status bar. The engine, its launcher and its
merge all stand on a `CliContext` — its save, the follow-ups after the save, what a refused
save takes back — and the window applying the claim to its own model would be that order
written a second time, which is exactly what one launch under both surfaces exists to prevent.
So the window does only what is its own and the CLI refuses: it asks the graph gate (and passes
`--anyway`), clones a repository this machine lacks, and saves, so the process writes over no
unsaved edit. The claim and the pass's records arrive through the library watcher, as every
agent's own `dplanner` call does; the process runs in a session of its own, so a window closed
mid-launch does not end a process holding the step's launch lock.

The child menu lists every preset — the step's own first, marked by where it was chosen
(*this step's*, *project default*, *landing default*) — and greys each with its own reason:
Run Agent's questions of the step and the default profile's headless agent; a role no profile
runs (`passes.pinned`); an agent not usable here, `Availability.why_not` over the harnesses
the pass would run (`passes.agents_of`). The window keeps **one** `Availability`, which the
checklist's rows probe into too, and refreshes it on a task when it has gone stale — at
start, as the context changes, and as the menu opens — so a reading is never taken on the GUI
thread. A pass under way, or a run not over, is not read for the menu: it is the verb's
refusal, said in the status bar, as Run Agent leaves its own to the launch. **One step at a
time**: a step's own playbook is a fact of each step, and a selection is what *Autonomous
work* runs. A *Remote ▸* entry waits for workers to exist.

**Not yet:**
- **the context ceiling's fresh run.** A turn's summed usage counts the context once per
  call, so it is no reading of the context's size.
- **fetching and pushing** around consuming an answer.

## Each stage is one headless turn per harness

Every stage runs headless: one process, one turn, then it exits (park and resume). Each
harness's `harness.py` spells it as an argv (`domain/headless.py`'s `Headless.command` over a
`TurnSpec`), built at S8 from the 2026-10-07 experiments and the checks below it:

| Stage | Claude Code (`claude -p`) | Codex (`codex exec`) | opencode (`opencode run`) |
|---|---|---|---|
| plan | `--permission-mode plan` | `-c sandbox_mode="read-only" -c approval_policy="never"` | `--agent plan` |
| execute | `--permission-mode auto --json-schema <turn>` | `-c sandbox_mode="workspace-write" -c approval_policy="on-request" -c approvals_reviewer="auto_review" -c sandbox_workspace_write.writable_roots=[…] --output-schema <file>` | `--auto` |
| review | `--permission-mode plan --json-schema <verdict>` | read-only, as plan, `--output-schema <file>` | `--agent plan` |
| a fresh session | `--session-id <id>`, minted at launch | — (Codex mints the thread) | — |
| the next turn: an answer, a reset, a retry, a loop-back | `--resume <id>`, same mode | `codex exec resume … <id> <prompt>`, **same overrides** | `--session <id>`, same mode |

**Every turn carries:**
- the JSON stream — `--output-format stream-json --verbose`, `--json`, `--format json` — which
  the supervisor tees into the run directory and classifies;
- Claude's `--strict-mcp-config` and no MCP list, because a headless Claude otherwise inherits
  the person's claude.ai connectors (mail, calendar);
- the run directory and the **plan repository** as writable — Claude's `--add-dir`, Codex's
  `writable_roots` on an execute turn — since the 10-04 run's 21 Codex sandbox prompts were the
  plan repository outside the writable roots;
- a typed final message where the CLI has one (`--json-schema`, `--output-schema`), so a
  verdict and a question are read, not guessed from prose — `domain/headless.py`'s
  `TURN_SCHEMA` for execute and `VERDICT_SCHEMA` for review, both strict because Codex takes no
  other kind; a plan has none, because its final text *is* the plan;
- the scrubbed environment every launch already gets.

**Codex states its mode on every turn, as `-c` overrides.** The research's
`codex exec resume <id> --approve-for-me` does not parse: `exec resume` takes none of `-s`,
`--approve-for-me` or `--add-dir` (0.160.0), and a resumed thread does not keep the mode it
began in — a read-only thread resumed bare came back `workspace-write`. Read off the rollout's
`turn_context` against the fake API, `--approve-for-me --add-dir <d>` is exactly the four
overrides in the table, and they hold on `exec resume`; so a fresh turn uses them too, and the
two spellings cannot drift. A review in Claude's plan mode does run read-only Bash (a recorded
review ran `find`), which settles the review row.

**How a turn ended is one function over what the stream said.** Each harness's reader
normalises its CLI into a `TurnLog` — the session, the turn's tokens, the account's windows,
the final text and its typed form, the CLI's own error and its machine-readable code, the
denials — and `Headless.classify(exit, log, stderr, question)` reads it in one order: killed;
the CLI's error, by its code before its words (Claude's `rate_limit` is a limit whether the
words say "rate limit" or a subscription's "You've hit your limit"); a failed exit with no
message; **the question the turn recorded** through `dplanner question ask`, which the supervisor reads
from the question store and hands in, since an agent that asked through the door ends its turn
in plain words; a denial (Claude's `permission_denials` under `success`, opencode's
"auto-rejecting" on stderr, a Codex sentence refusing an act *because* of its sandbox); the
typed outcome; a wait on the agent's own background work (`failed` as `abandoned-wait`,
because headless the work died with the process and nobody wakes the agent, so "continue"
resumes it); a question in prose; done. A harness differs only in its reader and three hooks —
where its limit telemetry lives and where it names the model a turn ran on (Codex: both in the
rollout, never `--json`), and the denials it prints to stderr. **A schema-valid final message always wins; the prose heuristics run only on untyped text, read only what is still open at the very end, and when unsure park rather than say done** (`agents.md` has the accepted limits): the final
paragraph ends on the question, or asks for an answer ("Once you let me know, I'll…") with the
question just above — so an answered FAQ heading is no question — and the final paragraph
commits, in the agent's own unquoted words, to waiting on its work — so a finished fix "for the
worker waiting on the job" is no abandoned wait. A reader never raises on a vendor's odd value:
a window whose share is not a number is skipped, an impossible reset is unknown. A limit's
reset is its **fullest** window's: both real Codex limits on 10-04 struck at 98–99 %, and that
window's reset was the message's "try again at" to the minute. A hang and a runaway are the
supervisor's to detect — the log counts events since the agent last produced anything — and
what the classifier is then handed is a killed process. **Every CLI's prompt follows `--`**, so
an answer that reads like a flag (`--help`) is still the prompt; each parser was checked to
honour it against a local fake API. The recorded streams that hold all of this are
`tests/fixtures/agent_turns/`, the 10-03 probes under `probes/`.

**Why these modes.** `acceptEdits` alone denies every Bash call, so an execute stage needs the
auto-approving mode; on a model that refuses it (Claude's `auto` on Haiku denied the edit) the
turn ends *denied* and parks. None of the three CLIs blocks on a permission headless — each
fails quietly and exits 0 — which is why a turn's ending is classified, never trusted. Claude's
plan mode writes the plan into `~/.claude/plans/` even headless; DPlanner keeps its own copy,
from the final text, in the run directory. `claude --bg` is an interactive session in the
background, which sat at an approval prompt indefinitely: it is for a person to watch, never
for a stage.

## Decided at S4 (coordinator) — for Knut to confirm at the final review

Each was a product question for Knut, with a recommendation. Knut reviews the whole branch when
it lands, so the coordinator decided each at S4 as recommended, and Knut confirms or reverses
them in that review.

| # | Question | Decided | Why |
|---|---|---|---|
| 1 | **Custom playbooks in the plan repository now, or later?** | **Later.** | The nine presets cover the brief. A file an agent can edit on its branch needs a rule of its own (read playbooks from the mainline only), and the first hand-authored config in a JSON codebase needs a FORMAT.md line on why. |
| 2 | **When `progress` accepts a step, does DPlanner start the next ready step itself?** | **No: the coordinator or a person does.** | DPlanner starting what became ready is the window's auto-launch under another name, which S5 removes for its races and its terminals nobody clicked for. The coordinator already holds the selection and its claims. |
| 3 | **What does a step with no playbook get?** | **Nothing: Run Agent, as today; a landing defaults to *Review only*.** | A playbook spends tokens unattended. Making it the default for every agent step should be a project's choice, not a build's. |
| 4 | **Should DPlanner run the tests itself as a gate, judging by exit codes?** | **Yes, in a later step.** | The evidence ranks a criteria gate first — a lying agent cannot fake an exit code — but none of the seven presets names one, and it needs the project's commands as data. |
| 5 | **Two rounds, then escalation, as every gate's default?** | **Yes**, overridable per step up to five. | Two rounds then a person is what the orchestration research settled; a third round between two agents is the debate the evidence advises against. |
| 6 | **Does "same agent" mean the same harness and model, in a fresh session?** | **Yes.** | Reviewing in the implementer's own context measured worst; a fresh session is the control the evidence says to beat. |
