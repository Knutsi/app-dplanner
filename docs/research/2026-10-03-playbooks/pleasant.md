# What our thinking is missing for this to be pleasant

*2026-10-03.*

## In short

The mechanics (stages, rounds, verdicts) are the easy half. What makes a playbook pleasant to live with is:

- **What you see:** three layers of chatter, and a *Needs you* inbox, instead of terminals.
- **What you are asked:** typed interrupts, only at stage boundaries.
- **What you can do mid-run:** pause, take over, re-run, answer.
- **What it costs:** an estimate before *Run*, spend as it goes.
- **Whether you can trust it:** criteria before work, a cleaned-up list of findings, outcome statistics per playbook.

None of this exists yet. Several items are small, but the playbook feels broken without them.

## 1. Seeing it: three layers of chatter

| Layer | Where | What | Built from |
|---|---|---|---|
| **The ring** | the step's card on the canvas | One phrase: *Working*, *Review 1/2*, *Fixing (round 1)*, *Parked*, *Waits for you*, *Escalated*. | `round_label(due(...))`, already in the spike |
| **The round conversation** | a *Playbook* tab in Step Details; the existing conversation dialog, live | Each gate's verdict and findings (severity, file:line, evidence), the implementer's fix or decline, a person's word | the ledger rows |
| **Transcripts** | one click from a round | Each run's raw stream: tool calls, edits, test output | the run's stream-json / JSONL, **kept as run output** (today run output lives in temporary directories, `build-order.md`) |

**The industry agrees on artifacts first and transcripts behind a click:**
- Antigravity: "verify with Artifacts, not logs";
- Copilot: session logs in a tab beside the diff;
- Claude workflows: "one report at the end".

No study says this is what people want. It is consistent practice.

**Live transcripts headless** need the worker to tee the stream to a file that the window tails. That file is also the stall detector's input and the usage source, so it pays three times.

## 2. Being asked: the *Needs you* inbox

Every time `due()` answers `NeedsPerson`, it becomes a **typed interrupt** (LangChain Agent Inbox's shape):

| Kind | Example | The person's verbs |
|---|---|---|
| `approve` | the person gate | approve · send back with a note |
| `respond` | the reviewer asks a question | answer (the stage re-runs with the answer) |
| `login` | codex's login is gone | log in · switch the role to another profile |
| `decide` | escalation at the cap | accept as is · take over · give one more round · drop the finding |
| `budget` | spend reached the ceiling | raise · stop |
| `stuck` | three failures in a row | retry · take over · abandon |
| `notify` | quota parked until 21:30 | nothing (informational) |

**Interruptions cost:** 10–15 minutes to get back into code (Parnin and Rugaber), and an interruption mid-task causes about twice the errors of one at a boundary (Bailey and Konstan) ([secondary summary](https://alexriosme.substack.com/p/running-five-agents-in-parallel-is)). So:

- **pull, not push** — a count on the inbox, never a modal;
- **batched**;
- **raised only at stage boundaries.**

## 3. Acting mid-run

- **Pause** a step's playbook. No new launches; the live run finishes or is stopped.
- **Take over a stage.** The run is fenced and stopped first, then the person works in the worktree. Their "ready" is that stage's verdict.
- **Re-run one stage** (a person `reset`, which the spike's ledger has).
- **Edit the playbook mid-run.** A run **pins the playbook version** it started with. An edit applies to the next run, and the person is told.
- **Cancel.** Kill the processes; the worktree is kept, and cleaning it is offered.

## 4. Knowing the cost

- **Before *Run*:** an estimate from the playbook and this project's history. That means mean rounds × mean tokens per stage kind, from the usage ledger (`domain/ledger.py`) and the *Expenditure* tab's numbers.
- **During:** spend against budget on the ring's tooltip, and a warning at 80%.
- **The CLI's own cap is the hard stop**, because a pre-launch check overshoots by one run (`fail/budget`). Claude takes `--max-budget-usd <remaining>`; Codex has no flag, so the worker kills the run on the stream's token count.

## 5. Trusting it

- **Criteria before the work starts.** A step without acceptance criteria can only get an opinion gate. The playbook should ask for criteria, or draft a validation contract for a person to accept, *before* the work stage.
- **A cleaned-up list of findings.** Practitioners reject over half of AI review comments. So:
  - every finding carries evidence;
  - a falsification pass drops what it cannot support;
  - severity sorts the list;
  - "nit" never sends work back on its own.
- **Outcome statistics per playbook:**
  - rounds;
  - escalations;
  - cost per merged step;
  - how often the person sent back what the agents passed.

  That last one is the reviewer's real precision. These numbers are what chooses the project default, instead of opinion. AO's lesson applies: the board is derived from facts, not set by agents.
- **The same-vendor fallback is visible.** When only one CLI is installed, *Review loop* becomes a same-vendor fresh review, and the ring says so ("Review 1/2 · same vendor").
- **A playbook file is input, not code.** An agent can edit files in the plan repository, so a playbook changed on an agent's branch must not take effect until a person merges it. A worker reads playbooks from the mainline only.
