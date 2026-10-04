# Orchestration: who drives a playbook

*2026-10-03. Two drivers weighed evenly, as asked, plus a third form found on the way.*

## In short

**One definition, two drivers.**

The same playbook file can be run by:
- **DPlanner's engine**: a level-triggered state machine over the ledger. This is the window's `AutoLauncher`, and later the `dplanner worker`.
- **A lead agent**: an LLM that gets the playbook rendered as its briefing (`lead_briefing()` in the spike) and starts the other agents itself.

**The evidence favours the engine for a step's playbook:**
- a fixed review pipeline beat an agentic reviewer 2.2× at 5–15× fewer tokens;
- multi-agent setups made sequential tasks worse by 39–70%;
- MAST's largest failure modes are repetition, not knowing when to stop, and wrong verification — exactly what a state machine rules out.

**The lead agent earns its place one level up.** It suits splitting a *region* of the plan into steps and picking playbooks for them. That is what Devin and Factory use orchestrators for.

**Either way, the facts that matter are recorded by DPlanner, not reported by the driver:**
- criteria gate results;
- whose run holds the stage (fencing);
- the head SHA a verdict judged;
- the spend.

That is what keeps a lead agent honest (`lead/lies-about-tests`).

## The engine

**`due(playbook, ledger, facts)` is a pure function** (`spike/playbook.py`). It answers one of:

- `Launch(stage, role, mode)` — mode is fresh, resume, or nudge;
- `Wait(reason, until)`;
- `NeedsPerson(kind)`;
- `Reconcile(run)`;
- `Escalate(stage)`;
- `Done`.

**It is level-triggered.** Nothing is remembered between calls. The engine re-derives the answer from the ledger on every tick, after every run ends, and whenever the plan changes on disk. That is the same shape as `rounds.due_turns` and `progression.due` today, and as Symphony's reconcile loop.

| Property | Engine |
|---|---|
| Determinism | Same ledger → same decision. Replayable; testable with no agent running (the spike *is* the test). |
| Bounds | Round caps, error caps, backoff and budget are code. The model cannot talk its way past them. |
| Recovery | Processes are disposable. A restart re-derives everything, and an orphaned run is reconciled, never relaunched blind. |
| Harnesses | Any. It needs only `exec` + `resume` + an exit and a verdict. |
| A person mid-run | Natural. `NeedsPerson` is just another answer of `due()`, and the engine waits at no cost. |
| Cost | No orchestrator tokens. |
| Weak at | Open-ended decisions: "this needs a design stage first", "split this step". It only does what the template says. |

## The lead agent

The lead agent gets the playbook as instructions (see `lead_briefing()` in the report's Prototypes section). It starts the implementer and reviewers as headless processes and decides what runs next.

| Property | Lead agent |
|---|---|
| Determinism | None. The same situation can go two ways. MAST's "step repetition" (15.7%) and "unaware of stopping conditions" (12.4%) are its failure modes. |
| Bounds | Only as strong as what DPlanner enforces underneath. The spike enforces: criteria recorded by DPlanner, fenced verdicts, budget checked per launch. |
| Recovery | If the lead dies, its children are orphaned and its context is gone. A new lead has to rebuild the state from the ledger, so the ledger must hold everything anyway. |
| Harnesses | It needs a harness that can run shell commands and wait on children. Claude Code's agent teams do not run under `-p` ([landscape.md](../2026-10-01-agent-orchestration/landscape.md)), so the lead must spawn `claude -p` / `codex exec` itself, through DPlanner verbs. |
| A person mid-run | Awkward. The lead has to stop and wait for a person while holding a session open, burning cache TTL. |
| Cost | ~15k tokens per decision turn in the spike's assumption. Over a careful playbook that is ~$0.27, ~15% on top (`lead/lies-about-tests`). |
| Strong at | Judgement about the *process*: noticing a step is mis-scoped, choosing a playbook, splitting work, writing a validation contract before the work starts. |

## A third form: compile to a Claude Code workflow

Claude Code's dynamic workflows (research preview, 2026-05-28) are deterministic JS scripts with `agent()`, `pipeline()` and `parallel()`. They are resumable and show tokens per phase ([docs](https://code.claude.com/docs/en/workflows)). A playbook could compile to one.

**Against it:**
- the docs say "No mid-run user input… run each stage as its own workflow";
- it ties every stage to Claude Code as the host;
- DPlanner's ledger would become a copy of the workflow's state, not the truth.

**Worth knowing it exists, as a reference design. Not a driver.**

## The recommendation

| Level | Driver | Why |
|---|---|---|
| A step's playbook | **Engine** | Evidence, bounds, recovery and a person mid-run. The ledger is already shaped for it. |
| A region of the plan (a worker taking "this branch") | **Lead agent** may plan; the engine still runs each step's playbook | Decomposition is judgement. Execution is bookkeeping. |
| A lead-driven playbook (`driver = "lead"`) | Supported, for experiment | Lets the two be compared on real steps, with the same ledger, UI and costs. Only the driver differs. |

**Why keep `driver = "lead"` at all:** it is cheap once the engine's facts are enforced underneath, and it is the only way to *measure* the claim instead of trusting the literature. Run both on the same kind of step for a few weeks, and compare rounds, escalations, cost and the person's verdicts.
