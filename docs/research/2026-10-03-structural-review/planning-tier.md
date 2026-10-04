# A planning tier between the graph and the features

*Added 2026-10-04, as a follow-up question to the review.*

**Summary.** The idea is a new headless tier, `planning/`, between `domain/` (the graph) and
the feature modules. It would hold the planning ontology: status, estimates, step kinds and
the review workflow.

- **A good move if it holds the ontology and nothing else.** In simulation it absorbs 23 of
  the 62 root helpers that read other modules. It also gives v2's server and daemon something
  to import that is not a feature.
- **A poor move if it becomes "the important aspects".** Then it is a second composition
  root, and the admission test below is the guard.

The rest stays out of the tier:

- the execution family: briefing, launch, PR refs, notes
- the knowledge family: spec, docs, testing

Those go through the hybrid's headless imports (see [alternatives.md](alternatives.md)),
mostly within one family.

## The tier already half-exists

Status is split across three tiers today:

| Part | Where it lives |
|---|---|
| the words | `domain/progression.py:71`; `step_status` and 16 other module files import them |
| the storage format | `modules/step_status/aspect.py` |
| the rules | the root: `_status_in`, `_card_status`, `_time_readers` |

The split comes from the rule that "a domain derivation is handed a function, never a
schema". The only real second implementation is the time simulator.

Every `aspect.py` imports only `core` and `domain`, so the files are already shaped like a
lower tier.

## Fan-in and churn

Measured on 2026-10-04. "Root helpers" counts the helpers in `modules/__init__.py` that import
the aspect. "Commits" counts non-merge commits to its `aspect.py`.

| Aspect | Root helpers | Commits | Since 1 Sep | In the tier? |
|---|---|---|---|---|
| step_review | 14 | 3 | 3 | yes: the review relation |
| step_milestone | 12 | 1 | 0 | yes |
| step_agent_instruction | 11 | 9 | 4 | yes: the agent flag and contract |
| feature | 9 | 4 | 4 | yes: the marker |
| step_status | 9 | 13 | 11 | yes, as a state machine |
| step_wait | 9 | 2 | 2 | yes |
| estimation | 7 | 7 | 2 | yes |
| github | 7 | 6 | 3 | borderline: as vendor-neutral work refs |
| testing | 7 | 11 | 8 | no |
| branches | 6 | 1 | 1 | yes: cut and land markers |
| step_description | 6 | 7 | 2 | no |
| spec | 5 | 7 | 3 | no |
| auto_progress | 4 | 1 | 1 | yes |
| step_agent_run | 4 | 8 | 4 | no |
| step_check | 4 | 1 | 0 | yes |
| step_start | 1 | 1 | 1 | yes (scope needs it) |

Two things stand out:

- **The ontology is wider than estimates and status.** The workflow aspects are read the
  most: the review relation, the agent flag, waits and branch cuts.
- **The contracts are stable**, except status, which is still gaining review and merge
  states.

## Simulation

The tier tested was `status, estimation, milestone, wait, start, check, feature, review,
agent flag, branches, auto_progress`.

- **23 of the 62 root helpers** that read other modules need only that tier: every key,
  kind, status, wait and cut rule.
- **The other 39** need feature files from one of two families:
  - execution: `prompt`, `launcher`, `rounds`, `github.aspect` (read by 6 helpers),
    `notes.log`, `notes.reach`
  - knowledge: the coverage trace over `spec`, `docs` and `testing`

## Shape

```
core/      storage, signals
domain/    the graph: nodes, edges, opaque aspect blobs, commands, store
planning/  NEW, headless: status (a state machine), estimate, kinds, review workflow,
           waits, cuts, auto-progress; schedule, progression, scope move up into it
cli/ → framework/ → modules/   the features
```

`domain/` never imports `planning/`, and `planning/` imports no Qt and no module.
DPlanner becomes a development planner with a fixed planning model and open-ended
features.

## Why it helps

- **Dependencies point toward stability.** Everything reads status and kind, so they belong
  low.
- **One concept lives in one place.**
- **Long-tail features import `planning/`** and need no root callbacks. A change to the
  ontology (playbook stages, claims) is deliberate.
- **The v2 server can import `domain` and `planning` only.** That lets it validate status
  transitions, mint step numbers, and merge the core aspects with real rules. Long-tail
  aspects stay opaque blobs merged per entry. "What is due" is a planning question, which
  the daemon needs.
- **The edges that remain are mostly inside one family.** Bounded contexts would come from
  the data, not from a design drawn up front.

## Risks and guards

1. **Creep.** The admission test: an aspect belongs in `planning/` only if a headless server
   or daemon must *interpret* it to order, claim, validate or merge, without loading any
   feature. `domain/` already shows creep: `agents.py`, `dictation.py`, `ledger.py`,
   `document_folder.py`.
2. **Work refs.** Branch and PR are borderline. Decide when the daemon lands. If they move,
   `github` becomes the provider that fills them in.
3. **Changes split across tiers.** About 11 features would have their contract in
   `planning/` and their UI in `modules/`. That cost is acceptable for stable data only.
4. **Status is still moving.** Move it as a state machine with transitions. Check
   transitions on change, never on load.
5. **Presentation leaking in.** The tier says "milestone" and "M". Glyphs and colours stay
   in the canvas and theme.
6. **Substitution.** Keep function parameters only where a second implementation exists
   (the simulator), with the planning readers as defaults.
7. **Naming.** Not `core`, which already exists. `planning/` says what it holds.

## The decision it asks for

It asks you to declare the planning model fixed. Status, estimates, kinds and the review
workflow would become DPlanner's own concepts rather than something replaceable.
