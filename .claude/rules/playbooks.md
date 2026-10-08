---
paths:
  - "docs/architecture/playbooks.md"
  - "src/dplanner/domain/agents.py"
  - "src/dplanner/domain/headless.py"
  - "tests/domain/test_headless.py"
  - "tests/modules/test_agent_turns.py"
  - "tests/fixtures/agent_turns/**"
  - "src/dplanner/modules/{agent_claude,agent_codex,agent_opencode}/harness.py"
  - "docs/research/2026-10-03-playbooks/**"
  - "docs/research/2026-10-07-headless-agents/**"
  - "src/dplanner/modules/step_playbook/**"
  - "src/dplanner/modules/agent_briefing/stages.py"
  - "tests/modules/step_playbook/**"
  - "tests/cli/test_playbook.py"
---

# Playbooks — stages, gates, loop-back, presets and headless invocations

- **A playbook is a list of stages on one step, and the step stays one card.** The kinds are
  `plan`, `execute`, the gates `review`, `person` and `coordinator`, and `progress`. Never a
  stage graph, never a card per stage, never a review step beside it:
  the card wears one phrase derived from the step's runs and questions (*Review 1/2*, *Waits
  for you*), never stored. `docs/architecture/playbooks.md`'s *A playbook is a list of stages
  around one step* has the reasoning.
- **A gate's *changes* goes back to the nearest earlier work stage** (`execute`, or `plan`
  when the gate stands between plan and execute), and the stages after it run again; with no
  work stage before it, to a fix run of the implementer. No `on_changes` field. A pass stands
  after a later gate's fix. A playbook started on a step at Ready for review starts at its
  first gate.
- **`progress` accepts the step on its feature branch and is refused on the mainline**, where
  it becomes a `person` gate — checked at run time, from the step's `BranchPlan`.
- **Rounds: 2 by default, at most 5, counted in verdicts given, never attempts** — a failed or
  replaced reviewer spends no round. ***Changes* on the last round is a `decision` question** of
  purpose `round-cap`, to the coordinator when one drives the run, else a person. Never a silent
  extra round. `docs/architecture/playbooks.md`'s *A gate gets two rounds, then somebody
  decides*.
- **A loop-back resumes the work stage's session**; it runs fresh with the findings only when
  there is no session, the resume fails, or the context is past its ceiling. **A review is
  always a fresh session** — *same agent* means the same harness and model, never the
  implementer's own context. `docs/architecture/playbooks.md`'s *A loop-back resumes the
  session that did the work*.
- **A failure is never a verdict.** Only a gate's typed verdict (*pass*/*changes*) spends a
  round; a turn that ended asked, denied, limit, failed or stopped parks, retries or asks.
- **The run record is the ledger; a playbook keeps no record of its own.** A **pass** (one run
  of a playbook on a step) has an id every run and gate question carries, and pins its resolved
  `settings` (preset and revision, rounds, roles, overrides) once, on its first record. Each
  agent stage attempt is one run (`pass`, `stage`, `attempt`, `turns`), and a loop-back is a new
  attempt, never a turn; each gate question is `plan-approval` after a plan, else `decision`,
  with a typed `purpose` (`gate`, `round-cap`, `escalation`). Identity is stored, never derived
  from the order of records. Findings are on the review run's `verdict`, declines on the fix
  run's `declined`. The coordinator may answer a `coordinator` gate and must escalate a `person`
  gate. `docs/architecture/playbooks.md`'s *The run record is the ledger* maps every
  review-round fact to its new home.
- **The engine advances a pass once, and nothing waits for it.** A run of a pass that ends
  `done` and an answer to a pass's question each start `dplanner playbook advance <step>`
  detached (`supervisor.advance_detached`); `step_playbook/engine.py` takes the step's launch
  lock, reads the pass's records oldest first, asks `passes.due` — the one derivation, pure —
  and does one thing, writing its record before the answer it acted on is consumed. **A pass
  starts only as `agent run --playbook`**, Run Agent's own gates and claim (none on a step at
  Ready for review, which starts at its first gate) — *Step ▸ Run Playbook ▸* in the window
  runs that very verb as a process (`AgentLaunchModule.start_playbook`, `launch.run_dplanner`)
  after only the window's own asks: the graph gate (answered `--anyway`), the clone, the save.
  Its entries — every preset, the step's own first and marked — are each greyed by Run Agent's
  step gates, `passes.pinned` and `why_not` over `passes.agents_of`; one step at a time, and
  no *Remote ▸* until workers exist. **A launch resumes a session exactly when
  an earlier run of its pass names it** — no flag; every stage's `prompt.md` is the whole
  briefing plus the stage's parts (`agent_briefing/stages.py`), so a fresh fallback knows what
  a resume knew. **A verdict is one only when it validates against `VERDICT_SCHEMA`**
  (`headless.verdict_of`); a review done without one gets one `verdict` turn, then escalates.
  **An answer is a label exactly** (case and a closing stop aside) — other words are *changes*,
  the words the finding. A fix declines findings by their number, recorded through
  `findings.json`. **A pass that cannot act writes a card on itself** — `limit` with the reset
  for a held account (`playbook wake` answers it for the clock), else `blocked` — and *Retry
  now* re-runs what was due; never an advance that exits with nothing written. **`progress`
  checks before it merges** — the plan's feature branch now (`merge_target`), the PR's base
  and head, the step under review — merges (`--merge`) only into a non-default branch, makes
  the mainline a person-only gate (`questions.PERSON_ONLY`) and anything else a `blocked`
  card. **One pass at a time**: until the latest pass reaches its end (`passes.due` says
  complete or halted) — between stages too — another `--playbook` is refused; `revive` runs
  first, and a first run that never began on an unclaimed step is a dead launch a retry
  replaces. The first record is written before the claim is
  saved, and started after it.
  `docs/architecture/playbooks.md`'s *How the engine drives a pass* has the reasoning.
- **A role names a harness, never a profile or a path**, and maps at launch to the first
  profile running it; an unrunnable role is refused, never swapped for the default. Whether
  its agent can run *here* is `Availability.why_not` (`agents.md`'s *Installed is not usable*).
- **Presets are built-in data** (`modules/step_playbook/presets.py`), no playbook files in the
  plan repository yet; a preset's `revision` rises whenever its stage list changes. A step's
  choice is its aspect (absence encodes the default), then the project's landing default on a
  landing, then the project default, then none (Run Agent) — `aspect.py`'s `resolve`, one
  function every surface reads. **A stage's kind is a `StageRole`, never a second
  `StageKind`**; `agent_stage` maps it onto `domain/headless.py`'s. Until the engine writes
  passes, the card's mark is the `playbook` medallion on a step's **own** choice only.
- **Every stage is one headless turn**, with the invocation per harness in
  `docs/architecture/playbooks.md`'s *Each stage is one headless turn per harness*: the JSON stream,
  Claude's `--strict-mcp-config`, the plan repository and the run directory writable,
  a typed final message where the CLI has one.
  Never `claude --bg`, and never a terminal. **A harness spells a turn as an argv**
  (`AgentHarness.headless`, `domain/headless.py`), and **Codex states its stage's mode as `-c`
  overrides on every turn**, fresh and resumed alike — `exec resume` takes no `-s`,
  `--approve-for-me` or `--add-dir`, and does not keep the mode its thread began in.
- **How a turn ended is `Headless.classify`, one function over the `TurnLog` the harness's
  reader filled** — never the exit alone, never a per-harness copy of the rules. A CLI's quirk
  goes in its reader or one of the two hooks (`limits`, `stderr_denials`); a new ending shape
  goes in as a recorded, scrubbed stream under `tests/fixtures/agent_turns/` with its expected
  end in `tests/modules/test_agent_turns.py`.
