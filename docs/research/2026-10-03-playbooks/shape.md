# Shape: a playbook is a template wrapped around one step

*2026-10-03. The design the spike tests (`spike/playbook.py`). It builds on [proposal.md](../2026-10-01-agent-orchestration/proposal.md) §1–3: a playbook is a mark on the step, and its stages live in the step's ledger.*

## In short

**The graph is in the template, not in the plan.**
- The plan step stays one card. It is the `work` stage — the slot the template wraps.
- Every other stage is a **gate**. When a gate asks for changes, the work goes back to `work`.
- So the stage graph is a **star around the work**, written as a plain *list* of gates. This answers "is a graph overkill?" with: yes, a free graph is; a list is not.
- The 99% case, *A ⇄ B → done*, is six lines of TOML.

**There are three kinds of gate:**
- criteria (exit codes);
- checklist (yes/no questions);
- judgement (open review).

A person is a fourth stage kind, and always comes last.

**Every outcome is one of:** a verdict (`pass` / `changes`), or a *failure*. A failure is never a verdict ([failures.md](failures.md)).

## The 99% case

```toml
name = "Review loop"
budget_usd = 4
roles.implementer = { agent = "claude" }
roles.reviewer    = { agent = "codex" }

[[stage]]
id = "review"
kind = "judgement"
```

`check()` accepts it, with one warning: *no criteria gate: nothing runs the tests, so every gate is opinion.* That warning is the evidence talking ([evidence.md](evidence.md) §2–4). The preset we would ship as **Review loop** has a `tests` gate before `review`, and it costs nothing in tokens.

## Why a list and not a graph

The free graph only adds what the list cannot already say. Nearly every case is a list with loops back to the work:

| Need | As a list |
|---|---|
| A ⇄ B → done | `[review]` |
| tests, A ⇄ B, a person | `[tests, review, approve]` |
| security review only where it matters | `[…, security(when = auth/**), …]` |
| A reviewer that sends work back to a design stage rather than to code | `on_changes = "design"`, the one escape hatch |
| Parallel reviewers, voting | Not supported. The evidence says one strong cross-vendor reviewer. Add it when a real case appears. |

The canvas never shows the star. On the step it draws a ring ("Review 1/2", "Waits for you"). The star is drawn on the playbook's own page (`diagram()`, `mermaid()`), and is read, not edited.

## Gates

| Kind | Who | Decides by | Notes |
|---|---|---|---|
| **criteria** | DPlanner itself | exit codes of `run = [...]` | **Recorded by DPlanner, never reported by an agent.** That is what makes a lying lead agent harmless (`lead/lies-about-tests`). A failing test is re-run once inside the gate, and a flake is recorded, not turned into a round. It also checks that the test count has not dropped (`solo/gamed`). Re-runs on every new commit. |
| **checklist** | an agent role | yes/no per item, each with evidence | Ideally the items come from a **validation contract written before the work starts**, from the step's description, spec or Test aspect (Factory Missions' pattern). |
| **judgement** | an agent role, with lenses | open review against lenses | Fresh session, read-only sandbox, can run the tests. Findings carry severity, file:line and evidence. A falsification pass runs before the implementer sees them. |
| **person** | a person, or a role a person fills | approve or send back | Always last (`check()` refuses anything after it). Never automated. |

**When a pass stands:**
- A criteria pass counts only for the head commit it ran on.
- An agent's or a person's pass stands once given, even after a later fix requested by another gate. Re-reviewing everything after every fix would double the cost for little gain.
- This is a design choice, and it is visible in `careful/person-sends-back`: the tests re-run, the review's pass stands.

**What `rounds` means:** how many times a gate may *see* the work. *Changes* on the last round escalates to a person; there is no extra round (`review-loop/cap`). The default is 2, and the cap is 5.

## How a verdict travels back to the implementer

- Through the ledger verbs that already exist (`review post` / `take` / `reply`), extended with a `stage` key. The rounds ledger keeps unknown keys today (`modules/step_review/rounds.py:179`).
- **A fix resumes the implementer while it is warm.** That means the last event was within the cache TTL and its context is under ~100k tokens. Otherwise the fix runs fresh, with the findings in the briefing (the 1 Oct policy).
- The simulation shows both:
  - `review-loop/changes-then-pass` resumes;
  - `careful/person-sends-back` goes fresh, because the person took 50 minutes and the cache went cold.
- **The implementer may decline a finding with a reason.** It does not argue back in a chat loop (the debate evidence). A declined finding that the gate still holds at the cap goes to a person, with both positions shown.

## Roles and profiles

**Roles** (`implementer`, `reviewer`, `security`, `lead`) are portable:
- each names a harness id and optionally a model;
- they live in the plan repository with the playbook.

**Profiles** stay what they are today, per machine: `Profile(name, agent_command, launch_command)` in `modules/step_agent_instruction/profiles.py`.

**At launch, a role maps to the first profile whose command resolves to its harness.** That is exactly what `_profile_for` already does for a review's preferred harness. So a playbook written on one machine runs on another without anybody editing it.

## Presets

Following the sane-defaults principle in CLAUDE.md, a dropdown of known choices pre-fills an editable form:

| Preset | Stages | Budget | When |
|---|---|---|---|
| **Solo** | tests → self-check (same agent, fresh session, checklist) | $2 | default for small steps; the control |
| **Review loop** | tests → cross-vendor review ×2 (the spike's `review-loop.toml` is the bare A ⇄ B, so the simulation shows the case you described) | $4 | default for ordinary steps |
| **Careful change** | tests → review ×2 → security (only on sensitive paths) → a person | $12 | risky steps, and **branch landings** |

- A project sets its default, and a step may override it.
- A step on a branch takes *Solo* and its landing takes *Careful change*. That follows the 1 Oct finding that review is paid for once per branch ([proposal.md](../2026-10-01-agent-orchestration/proposal.md) §2).

## Editing

The editor is **a form, not a canvas**:
- a list of stage cards, each with a kind dropdown and its fields;
- the role table, whose dropdowns are filled from the harnesses this machine has;
- the budget;
- a read-only diagram drawn beside it;
- a *Dry run* button that shows `simulate.py`'s three layers for a few standard scripts.

**Why a form:**
- Visual workflow builders are "squeezed from both directions" (Chase), and coding tools converged on Markdown/YAML files.
- The file stays the truth. The form edits the file, and the file diffs in git.

## Open in the shape

- **The file format.** The spike uses TOML because the standard library reads it and it allows comments. Everything else in DPlanner is JSON (FORMAT.md). See [questions.md](questions.md).
- **Where a validation contract comes from**, and whether it is its own aspect.
- **Whether a checklist gate and a judgement gate are really two kinds**, or one kind with an optional item list.
