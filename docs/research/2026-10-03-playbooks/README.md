# Research: playbooks — a chain of agents around one step

*2026-10-03. It builds on [2026-10-01-agent-orchestration](../2026-10-01-agent-orchestration/README.md), which settled several things this note takes as given:*
- *headless CLIs;*
- *warm-resume versus fresh hand-back;*
- *two rounds, then a person;*
- *branch-level review;*
- *leases.*

**Read [report.html](report.html) first.** It summarises everything here, with the prototypes' output in it.

## The question

Can a step run a **playbook** — a template that, for example, has Claude implement, Codex review the worktree, the verdict travel back, and a gate decide *finish*? Should DPlanner drive it, or a lead agent? Is it better than asking an agent to review its own work? What would make it pleasant? How does it work on the v2 floor of workers and people? And what goes wrong: hangs, timeouts, API errors, a subscription expiring under a running agent?

## What is in this directory

| File | What it answers |
|---|---|
| [report.html](report.html) | Everything below, summarised, with the prototypes' output |
| [evidence.md](evidence.md) | Self-review vs a second agent; what makes a gate work; a lead agent vs a fixed workflow; debate |
| [shape.md](shape.md) | The template: a list of gates around the work, gate kinds, verdicts, roles vs profiles, presets, the editor |
| [orchestration.md](orchestration.md) | The two drivers weighed evenly, and a third form (Claude Code workflows) |
| [pleasant.md](pleasant.md) | What is missing: three layers of chatter, the *Needs you* inbox, acting mid-run, cost, trust |
| [floor.md](floor.md) | Workers and people: step claims vs stage assignment, the review bottleneck, take over and hand back |
| [failures.md](failures.md) | Every failure we could think of: how it is detected, its class, and what happens; the probe results |
| [questions.md](questions.md) | Twelve decisions for you, each with a recommendation |
| [spike/](spike/) | The prototype: `playbook.py`, `simulate.py`, `classify.py`, `probes/`, `export.py` |

## Eight findings

1. **A second agent helps mostly because of what it runs, not who it is.**
   - Tests and execution give most of the gain.
   - A fresh context adds a little.
   - A different vendor helps only if it is at least as strong.
   - A subagent that shares the implementer's context is the worst option measured.

   So the baseline to beat is *the same agent in a fresh session, with a checklist and the tests*.
2. **A free stage graph is overkill. A list of gates looping back to the work is not.** The 99% case is six lines of TOML, and every case we could name fits the list.
3. **Failures are not verdicts.** Every ending is classified as one of: a real *changes* verdict, retry, park, person, or abandon. Only a real verdict spends a round. The simulation asserts this in 22 scenarios.
4. **The facts that matter are recorded by DPlanner, not reported by agents:**
   - criteria results;
   - which run holds the stage (fencing);
   - the SHA a verdict judged;
   - the spend.

   That makes a lying or late agent harmless, and it is what lets a lead agent drive at all.
5. **The engine should drive a step's playbook; a lead agent belongs a level up**, splitting a region of the plan. The evidence (fixed pipeline 2.2× better at 5–15× fewer tokens; multi-agent setups 39–70% worse on sequential work) and the recovery story both favour the engine.
6. **The CLIs do not protect us from their own failures.** From the free probes:
   - no CLI times out a hung API;
   - opencode loops forever on a malformed reply, emitting events all the way, so a stall detector cannot see it;
   - Claude spends three minutes retrying a dead login.

   A harness needs its own classifier, its stall threshold, a runaway detector and a preflight auth check.
7. **What makes it pleasant is not the mechanics:**
   - three layers of chatter (the ring, the round conversation, transcripts);
   - a *Needs you* inbox of typed interrupts, raised only at stage boundaries;
   - pause and take-over;
   - a cost estimate before *Run*;
   - acceptance criteria before the work starts.
8. **On the floor, a step is claimed and a person's stage is assigned.** Put the human gate on branch landings: review time, not PR count, is the bottleneck.

## The recommendation in one paragraph

**A playbook is a TOML template of gates around the plan step's work stage, run by DPlanner's level-triggered engine (`due()`), with its stages kept in the step's existing rounds ledger.**
- **Gates:** criteria gates run by DPlanner; checklist and judgement gates run by fresh agents in read-only sandboxes; a person gate last.
- **Failures:** classified per harness, and they never spend a round.
- **Presets:** *Solo*, *Review loop* and *Careful change* — Solo per step, Careful on branch landings.
- **What people see:** a ring on the card, the round conversation in Step Details, transcripts one click away, and a *Needs you* inbox.
- **The lead-agent driver** is an experiment on the same ledger, added after the engine.

## Running the spike

```bash
cd docs/research/2026-10-03-playbooks/spike
uv run python playbook.py playbooks/*.toml        # check, diagram, mermaid, lead briefing
uv run python simulate.py                         # 22 scenarios, the three chatter layers, invariants
uv run python simulate.py --playbook playbooks/careful-change.toml review=changes,quota,pass
uv run python classify.py                         # the classifier against 36 probe fixtures
uv run python probes/run_probes.py <scratch dir>  # re-probe the CLIs (~6 min, no cost)
uv run python export.py                           # rebuild report.html from report.src.html
```
