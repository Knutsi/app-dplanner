# The factory floor: workers and people sharing playbooks

*2026-10-03. How playbooks fit the v2 production floor ([notes-after-meetings.md](../../towards-v2/notes-after-meetings.md) ideas 4–7, [coordination.md](../2026-10-01-agent-orchestration/coordination.md)).*

## In short

- **A step is claimed whole. A person's stage is *assigned*.**
  - A worker's lease covers the step and every agent stage in its playbook.
  - A `person` stage drops into an inbox for a role ("any reviewer", "the tech lead") or a named person.
  - Answering it does not take the step from the worker.
- **People become the bottleneck, so the playbook must save their attention.** Teams heavy on AI merged 98% more PRs with 91% longer review times and no gain in delivery (Faros).
  - Put the human gate on the **branch landing**, not on every step.
  - Show a person the gates' evidence, not the diff alone.
- **People own the work; agents are delegated to** (Linear's rule). A step's accountable owner is always a person, even when a daemon does every stage.
- **Handing a step back and forth is one gesture each way**: take over (fence the run, then work) and hand back (set *ready*, and the next gate runs).

## Who does what on the floor

| Actor | Claims | Runs | Answers |
|---|---|---|---|
| A **worker** (daemon) | steps, by lease | agent stages (work, review, checklist), and criteria gates through DPlanner | nothing; it never approves |
| A **person at a window** | steps they work by hand (as today) | their own work stage, or a taken-over stage | `person` stages assigned to them or their role; `decide`, `login` and `budget` interrupts for steps they own |
| A **product owner** | nothing | nothing | budget raises; the *decide* on escalations they own; reads cost per stage and per playbook |

## Stage assignment, not stage claims

The 1 Oct coordination note made the **step** the unit of claim, and that still holds. A playbook adds one thing: **a `person` stage names who answers it.**

```toml
roles.owner = { person = true, who = "role:tech-lead" }   # filled at run time: a role, or a named person

[[stage]]
id = "approve"
kind = "person"
by = "owner"
```

- **At run time** the inbox shows the stage to everyone who can fill the role. The first to *open* it takes a soft hold (presence, not a lock), and the answer is a command like any other.
- **On one machine** that is the window. On the floor it is the presence service at L3 ([proposal.md](../2026-10-01-agent-orchestration/proposal.md) §5).

## The review bottleneck

The numbers:
- **Faros** (secondary summary): +98% PRs merged, +154% PR size, +91% review time, no DORA improvement ([summary](https://soladipupo.substack.com/p/the-ai-productivity-paradox)).
- **GitHub:** more than one review in five now involves an agent ([blog](https://github.blog/ai-and-ml/generative-ai/agent-pull-requests-are-everywhere-heres-how-to-review-them/)).

What the playbook does about it:
1. **No person gate per step** on a branch. The per-step playbook is *Solo* or *Review loop*.
2. **One person gate per branch landing.** It covers the merged work of several steps, and it comes after the careful agent stages.
3. **The approval screen leads with evidence:**
   - criteria results;
   - each gate's verdict and the findings it fixed;
   - what was declined and why;
   - the cost.

   The diff comes second.
4. **The person's send-back rate is measured** per playbook ([pleasant.md](pleasant.md) §5), so a playbook whose gates pass work people reject is visible.

## Taking over and handing back

- **Take over:**
  - the person runs *Take Over* on a running step;
  - the worker's run is fenced (its later verdicts are refused) and stopped;
  - the lease passes to the person;
  - the playbook pauses at the current stage.
- **Hand back:** the person sets the stage's outcome (*ready* for work, or a verdict for a gate) and releases the step. The worker's next tick re-derives `due()` and carries on.
- **Interrupting a worker never loses work:** the worktree and the session stay, and a resume picks them up.

## Cost on the floor

- **Cost is per stage, per playbook, per step and per project** — all derived from the usage ledger, never stored as totals (CLAUDE.md: derived facts are computed).
- **The budget a product owner sets is a policy per project.** It is a ceiling per playbook run plus a monthly ceiling per project, warning at 80% and pausing at 100% (Paperclip).
- **Resource planning** needs a worker's capacity next to a person's: concurrent runs × hours, and quota windows per account. The quota parks seen in `fail/quota` are exactly the capacity a plan must not assume.

## What changes at each rung

| Rung | Playbooks | People |
|---|---|---|
| L0 window | the window's `AutoLauncher` runs `due()`; agents in terminals | as today, plus the inbox |
| L1 local worker | the worker runs `due()` headless; the window shows rings and the inbox | the developer answers person stages in the window |
| L2 server worker | same, on API keys, in sandboxes | via the window, with the plan repo synced through git |
| L3 floor | several workers, leased steps | inboxes by role, presence on person stages |
