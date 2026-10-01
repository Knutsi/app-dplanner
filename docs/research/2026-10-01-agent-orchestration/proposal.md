# How DPlanner should do it

*Written 2026-10-01, from the research in this directory and a read of the code that day. It is a proposal: nothing here is built. Paths are under `src/dplanner/` unless they start with `docs/`.*

## The finding that shapes everything

**DPlanner already has most of a playbook runtime, and its agents already talk through the plan.** The user's idea — agents read their situation and report back through `dplanner`, and the orchestrator starts the next agent — is not a new design. It is the review conversation shipped in `modules/step_review/`, which [landscape.md](landscape.md) shows to be the pattern the better orchestrators converged on:

| What the field does | What DPlanner has |
|---|---|
| A CLI verb as the only way back (`ao review submit`, `gt done`) | `status set`, `review post / take / reply / approve / escalate`, `note add` |
| A conversation ledger on the task, with derived state | `review_rounds`: texts and stamps on the step that asks; state and turn derived (`rounds.turn`) |
| A level-triggered scheduler that reconciles each tick (Symphony) | `AutoLauncher` re-derives `_due_now` = `progression.due` + `rounds.due_turns` after every change |
| A launch that happens once | The run stamp, and `party_turn_launched` / `asker_turn_launched` naming the turn |
| A round cap, then a person | `step_review`'s cap (absent = 3), and `escalate` → blocked + a handoff note |
| A reviewer from another harness (AO `SwitchReviewer`) | A review names its agent (a harness id) and its lenses |
| Usage per run | `agent_usage` rows from each harness's `report()` |

**What is missing** is a launcher that is not the Qt window, harness commands that run without a terminal, and a way to mark one step with a chain of stages rather than adding a step per stage. These are the three pieces below. Everything else is reuse.

## 1. A playbook is a mark on one step

**On the canvas** the step looks as it does today, **wrapped in a review mark**. A playbook ring round the card names the playbook ("Careful change") and shows where it stands: the current stage, and the round on a review stage — *Review 2/2*, *Security*, *Waits for you*. It is a `NodeAccent` the composition root translates, like every other accent (`modules/project_editor/renderers.py`), so the canvas never learns what a playbook is. There are no extra cards. Step Details gets a *Playbook* tab: the stages, each one's verdict and rounds, and the conversation dialog that exists today.

**In storage** it is an aspect on the step, `playbook`:

```json
{"playbook": "careful-change", "overrides": {"review": {"rounds": 1}}}
```

The stages and their conversation live in the `review_rounds` ledger the step already knows, generalised in two small ways:

- **A round names its stage.** It gains a `stage` key (absent = today's plain review), so one ledger holds *Review* rounds and *Security* rounds in order.
- **A step can be its own asker.** Today the asker is the review step and the party is its subject. Under a playbook the step holds the conversation about its own work, and the party is the step itself. `due_turns` already derives "whose turn, whose agent has gone, not yet launched for this turn". With the stage it also derives "which stage's agent to launch": the playbook definition says which harness, model and lenses that stage uses.

**Status** works as it does for a reviewed step today:

- The implementer finishes at *ready for review*, the playbook's stages run, and `post` puts the step back *in progress* for a fix.
- The last gate's `approve` — or the human stage, which is a person's approve — moves it on.
- `escalate` blocks it with a handoff note.

`progression`, the schedule and reports see one step with one status, because that is what it is.

**Why not steps.** Two other shapes were weighed:

| Shape | Why not |
|---|---|
| **Stages as cards** — the playbook stamps out Review → Security → Human steps after the work | Heavy, and the graph gets harder to read; a 30-step plan becomes 90 cards. |
| **Stages as hidden member steps**, folded into one card the way a stack is (ARCHITECTURE *A stack is presentation over a chain*) | The canvas looks right, but every listing, `order show`, the schedule, the report and every CLI walk would still see the members. A stack's members are real work; a playbook's stages are not separate work, they are care taken over one piece. |
| **A mark on the step, the stages in its ledger** (chosen) | The ledger grows a `stage` key and `due_turns` learns to read a playbook. That is a change to `step_review`, not to the model. |

**The definition** is a small file in the plan repository, versioned with the plan, checked statically (unknown harness, unbounded loop, stage after the human gate) like Symphony's `WORKFLOW.md` and ccswarm's flows. It has a dry run that prints every stage's briefing through the same `assemble()` `dplanner agent prompt` uses:

```yaml
# playbooks/careful-change.yaml
name: Careful change
stages:
  - id: review
    agent: codex          # a harness id; another vendor than the implementer, at least as strong
    lenses: [architecture, correctness]
    rounds: 2             # review→fix rounds, then escalate
  - id: security
    agent: claude
    lenses: [security]
    rounds: 1
    when: touches(auth/**, net/**)   # optional; a stage may be skipped by a rule
  - id: human
    gate: person          # waits for a person's approve; never automated
budget_usd: 6
```

**A stage is the same skill whether it runs in a playbook or as a Review step.** The lenses (architecture, security, a custom skill), the briefing (*Work you review*, the round protocol), the verbs and the conversation dialog are shared. A standalone Review step stays for the case where a review *is* separate work — a person wants it scheduled, or it reviews a collector. A playbook stage is the same thing kept on the step.

## 2. The same playbook reviews a whole branch

A **landing step** (`branch_land`, ARCHITECTURE *A branch stretch is bracketed by a cut and a landing*) already opens the branch's PR into the mainline, and today an ordinary Review step after it reads that PR. **Marking the landing with a playbook** runs the stages over the *whole branch diff* before it goes to main. Because the per-step agents are gone by then, a branch stage may also make fixes itself, on the feature branch, in the landing's worktree — a review step does not.

This is where the money is ([handback-and-review.md](handback-and-review.md), *Per step, or per branch?*):

- A review's cost is mostly its fixed context: Claude Code Review is $15–25 and ~20 min **per PR**. Five parallel steps reviewed one by one pay it five times. Reviewing the branch they land on pays it once and sees how they fit together.
- Recall drops as a diff grows, so not everything should wait for the branch.

**The default pairing:**

- **Each step on the branch: the light playbook.** Tests, lint and a self-check by the implementer before *ready for review*. Its PR merges into the feature branch on green, which an open stretch already accepts (`record_merged(accepted_by_merge=)`).
- **The landing: the careful playbook.** Cross-vendor review (2 rounds, fixing on the branch), security review where the diff touches what it should, then the human gate before the PR to main.

A step *off* any branch carries whichever playbook it is given, and the light one by default.

## 3. Hand-back: fresh reviewers, warm fixes, two rounds

From [handback-and-review.md](handback-and-review.md):

1. **A reviewer always starts fresh**, from another vendor at least as strong as the implementer, in a read-only sandbox, never in a worktree of its own (`Briefing.no_worktree` already rules one out).
2. **Findings come back structured** — severity, file:line, rationale, suggested fix — asked for with `--json-schema` / `--output-schema` and written by `review post` as today. `post` already takes a file. The structure can be a fenced JSON block in the findings text, so the ledger's shape need not change at once.
3. **A fix resumes the implementer's session while it is warm.** The worker launches `harness.resume` with *"Round N: take the findings and fix"* when:
   - the last request was inside the cache TTL;
   - the run's input stayed under ~100k tokens;
   - the worktree is the one it left.
   Otherwise it is a **fresh launch**, whose briefing already carries the *Review rounds* section. `AgentHarness.resume` exists today, and `report()` already returns the session and usage. The worker needs the last-request time, which stream-json gives it.
4. **Two rounds by default, then a person.** The briefing says which round is the last.
5. **Headless, nobody waits.** In a terminal the implementer runs `review wait`, which polls the plan for up to nine minutes. A worker does not need an agent holding a session open to wait: the implementer exits at *ready for review*, and the worker — which is the waiter — launches the next turn when the ledger says so. `review wait` stays for terminals.

## 4. The worker: `AutoLauncher` without the window

`dplanner worker` is a Qt-free, long-running CLI process that runs the same loop the window runs:

- **What is due** is the same `_due_now` (`progression.due` + `rounds.due_turns`, extended for stages). It is re-derived on a tick and when the plan changes on disk, never edge-triggered.
- **Launching.** A new **`exec`** template on `AgentHarness`, beside `command` and `resume`, runs the briefing to the end with structured output:
  - `claude -p --output-format stream-json --session-id {session} --permission-mode … --permission-prompts none`, preferably `--bare`, with the `dplanner` skill handed in through the briefing;
  - `codex exec --json --sandbox workspace-write`;
  - `opencode run --format json`.
  The briefing goes in as a file, never in argv, as now.
- **Completion** is the process exit plus the final result event. Stall detection is time since the last event, killing after a configurable silence (Symphony: 5 min). This replaces the 2-second exit-file poll, which stays for terminals.
- **Usage** is recorded from the result, through the same `agent_usage` rows.
- **One launcher per library per machine** is a plain lock file the CLI can take, replacing the `QLockFile`. The window's auto-launch and a worker on the same machine take the *same* lock, so they never both launch.
- **Run records** move to where the CLI can read them. Today they are in `user_config`, which only Qt reads (`NOTES-FOR-APPFRAME.md` §4). This is the one known gap in the layering, and the worker cannot exist without closing it.
- **Sync.** The worker pulls the plan repository before a pass and pushes after its writes, through the storage provider the store already uses.

**What carries over unchanged:** `progression.due`, `rounds.py` and `at_work.py` are Qt-free today. `launcher.prepare`, `prompt.assemble` and `runs.settle` need checking for Qt imports before the worker is built.

**Budget.** A ceiling per step and per playbook (`budget_usd` in the definition), computed from `agent_usage`, never stored as a total. The worker checks it **before each launch**: a warning at 80%, and at 100% it stops launching that step and blocks it with a handoff note, which is how DPlanner already says why a step stopped (Paperclip's pause, in our vocabulary). The `max_agents` setting is the concurrency cap. A quota error is a refusal with a retry time, not a failure.

## 5. The ladder

Each rung is useful on its own, and each is the rung below with one thing added.

| Rung | What runs | What it adds | Auth |
|---|---|---|---|
| **L0 — today** | The window launches agents in terminals | — | The developer's own |
| **L1 — a local worker** | `dplanner worker` on the developer's machine, on their own plan repo | Headless harnesses, playbooks, the lock shared with the window, budget | Subscription is fine: it is the developer's ordinary use of their own CLI. One launcher per machine. |
| **L2 — a server worker** | The same command on a server, against a plan repo it was set up to watch | Containers or the CLI sandbox, `--bare`, GitHub App tokens, push only to `agent/*`, the human gate kept | API keys, explicitly configured |
| **L3 — several workers and people** | Workers on several machines; people in windows | **Lease claims** (git refs first, [coordination.md](coordination.md)), a fencing `--run` on the status verbs, and **presence** over a tiny websocket service. The window shows who — person or worker — is on which step and stage. | Per worker |
| **L4 — the factory service** | A hosted service over many systems and projects | The system level, the overview, resource planning and reporting from the v2 build order | Organisation |

A person can open the plan in DPlanner at any rung and see where the workers are. At L1–L2 that is the run state, the at-work claims and the playbook mark. From L3 it is live presence as well. They can also check off a manual step, approve a human gate, or take a step back from a worker by setting it in progress themselves. That is the production floor the meeting note asked for, not a lights-out factory.

**The multiplayer server** comes in at L3, not before. On one machine, claims already work, and a server built before anyone collides is a service to run for nothing (the v2 build order says the same). What it then holds is *only* ephemeral — leases, presence, live events. The plan, the rounds, the findings and the usage still go to git through commands.

## 6. What not to build

- **Screen-scraping or `send-keys` into terminals** to drive agents. The non-interactive modes exist ([headless-mechanics.md](headless-mechanics.md)).
- **Agent teams or in-session swarms as the worker.** They are experimental, they do not run under `-p`, and the orchestration belongs in DPlanner, where the plan is.
- **A2A, or our own agent-to-agent protocol.** Agents talk through the plan with CLI verbs. That is cheaper in context than MCP ([costs](https://code.claude.com/docs/en/costs) says the same of `gh` vs an MCP server), it works with every harness, and it leaves a record. ACP is worth a look later only if driving many harnesses uniformly becomes the problem.
- **Role metaphors.** No Mayor, no Deacon. A stage is named for what it does.
- **Unbounded loops.** Every stage has a round cap, every playbook a budget, and the way out is a person.
- **An agent that merges.** Already the rule. A worker never merges either; the human gate or a person's merge does.
- **Many parallel reviewers by default.** The evidence supports one strong cross-vendor reviewer, a narrow security pass where it matters, and a person. Fan-out convoys (Gas Town) multiply cost for findings a person then has to deduplicate.

## 7. Open questions

1. **Which vendor pairings?** The evidence says a reviewer must be at least as strong as the author, and that the effect is asymmetric. The default pairing should be measured on our own PRs before it is fixed — the `agent_usage` rows plus the round outcomes are the data.
2. **Does L2 run a container per run, or the CLI's sandbox only?** Containers are safer and slower. The sandbox is cheaper and enough for a trusted repository.
3. **Git-ref claims, or straight to a server at L3?** Git refs need no service and are honest about latency. A server is needed for presence anyway. The answer depends on whether people want presence before workers collide.
4. **How a fix stage on a branch landing gets its worktree.** The landing's worktree is on the feature branch already (*The branch is cut lazily*). A fixing stage there is the first time a review-like agent writes, and it needs its own rule.
5. **Where the playbook definitions live.** The plan repository is the natural home — versioned with the plan, shared by everyone who opens it. At L4 a system may hold playbooks its projects share, which is one more reason the system level is next in the v2 order.

## The order this suggests

It refines step 2 and 3 of `docs/towards-v2/build-order.md`:

1. **Headless `exec` on the harnesses**, and run records the CLI can read. Small, and nothing else works without them.
2. **The playbook mark**: the aspect, the `stage` key on rounds, `due_turns` reading stages, the canvas accent, the definition file with its static check and dry run. Useful in the window at once, because the window's auto-launch runs it.
3. **`dplanner worker`** (L1): the window's loop, headless, sharing its lock. Add the budget gate here.
4. **The branch-landing playbook** as the default pairing, once 2 and 3 have run on real steps and the round and cost numbers are in.
5. **L2 hardening** (sandbox, `--bare`, App tokens), then **L3** claims and presence when a second machine actually collides.
