# Structural and entropy review — 2026-10-03

A review of DPlanner's architecture, module structure and naming, done before the v2 work
(`docs/towards-v2/build-order.md`: playbooks, a headless daemon, then a multiplayer server).
It asks three questions:

- (a) Where have entropy and over-engineering built up?
- (b) Which bad patterns are emerging?
- (c) Which seams are starting to crack?

The readable front is [report.html](report.html), which is also published as an Artifact. These
notes are its durable source. Every number here was measured on `main` at `0472101`.

| File | What it holds |
|---|---|
| [README.md](README.md) | the verdict and the findings |
| [report.html](report.html) | the report: everything below, with diagrams and code |
| [alternatives.md](alternatives.md) | what could replace or narrow the composition root, compared on one running example |
| [planning-tier.md](planning-tier.md) | added 2026-10-04: a `planning/` tier for the step ontology |
| [renaming.md](renaming.md) | which packages' names no longer say what they hold, and what each rename would cost |
| [seams.md](seams.md) | persistence and coordination seams for multiplayer and the daemon, with failure modes worked through |
| [waves.md](waves.md) | the remediation, sized as PRs, offered as options |
| [second-opinion-codex.md](second-opinion-codex.md) | added 2026-10-04: independent checks, qualifications, and an application boundary for continued growth and multiplayer |
| [response-claude.md](response-claude.md) | added 2026-10-04: Claude's assessment of the second opinion, per-module actions, enforcement by types and tests, the reconciled order |
| [how-this-review-was-made.md](how-this-review-was-made.md) | who asked what, what each of us thought, and the open questions on 4 October |

## The next move

Both reviews agree on the first step: fix the reproduced correctness bugs. Then pilot one
complete workflow, *set status*, end to end:

- `planning/` owns the status vocabulary as an `Enum`, with `Unknown` as its own type.
- `step_status/actions.py` is called by both the GUI and the CLI; the GUI gains the claim
  release it lacks today.
- The first architecture tests land with it.

The reasoning is in [response-claude.md](response-claude.md).

## Second opinion (Codex) — summary

**The diagnosis largely holds; the remediation needs a stronger application boundary.**
Keep the composition root as wiring and give shared planning rules an owner. Add small
headless APIs for complete actions, with validation and transactional changes shared by
the GUI, CLI, daemon and future server. Headless imports and an acyclic dependency graph
help, but do not by themselves contain coupling or make concurrent writes safe.

Fix the reproduced persistence bugs first, preserve the different meanings of identity,
presentation and readiness, and decide whether multiplayer coordinates workers or owns
plan edits before redesigning storage. The [full second opinion](second-opinion-codex.md)
records the evidence and alternatives separately; the original conclusions below stand
as the first review.

## Verdict

**What has held.** The layering rules hold and are enforced (`tests/test_architecture.py`).
Modules really do not import each other. The graph model knows nothing about aspects. The
CLI starts without Qt. One command vocabulary serves both surfaces. Derived facts are not
stored. Blocking work goes through `TaskRunner`. These are rare things to still have at
126k lines and 57 module packages.

**What is cracking.** The pressure those rules hold back has gone somewhere, and it has gone
to two places:

1. **The composition root** (`src/dplanner/modules/__init__.py`, 4,923 lines). It has become
   the home of every feature that touches two modules: about 1,900 lines of business logic
   with no owner. 186 of the 522 non-merge commits in the repository touch it, 36% of all
   commits. The next most-touched file has 66.
2. **The persistence layer is shaped for one writer at a time.** Commands are not operations.
   Conflicts are detected per project and resolved by a person. Step numbers are minted
   locally. Claims are machine-local, and the launch lock needs Qt.

**Recommendation in three lines.** Keep the composition root, but narrow its job to wiring.
Move the planning ontology (status, estimates, step kinds, the review workflow) into a new
headless `planning/` tier ([planning-tier.md](planning-tier.md)). Let what remains cross
modules through *headless imports* along an import graph that a test keeps acyclic. Before the daemon, make commands into identified, authored
operations, and give claims a headless lease.

## (a) Entropy and over-engineering

1. **Ten ghost packages** in `modules/`: `agent_skill`, `llm_anthropic`, `llm_openai`,
   `product`, `project_dashboard`, `project_repo`, `step_feature`, `step_handoff`,
   `step_release`, `workspaces`. Each holds only `__pycache__`, so git cannot see them but
   someone opening the folder does.
2. **An LLM stack with no consumer.** `LLMService.complete()` (`framework/llm_service.py:126`)
   has no caller outside its tests. Unused with it:
   - `framework/llm.py`, `framework/key_dialog.py`
   - `modules/llm`
   - the provider halves of `anthropic` and `openai`
   - Debug's *LLM Calls* tab

   It is plumbing waiting for v2 step 7 (the factory door). Keep it, but take it out of
   `framework/`.
3. **Callback indirection that nothing substitutes.**
   - There are 50 `*Deps` classes with 480 fields between them. `StepAgentInstructionDeps`
     has 37.
   - `_step_key` alone is handed to about 11 of them as `key_of=` / `step_key=`.
   - About ten root helpers only rename an aspect reader: `_is_wait`, `_is_cut`,
     `_is_agent_step`, `_asks_person`, `_has_run`, `_pr_base`, `_recorded_work`, …
4. **The docs read like diaries.**
   - `ARCHITECTURE.md` is 8,843 lines in 75 sections, in the order they were written, with
     37 "used to", 26 "no longer" and 20 "retired".
   - `NOTES-FOR-APPFRAME.md` is 4,932 lines, and §§7–75 are "From the X pass…".
   - `CLAUDE.md`'s *Mechanical facts* (~140 lines) are area rules, which `CLAUDE.md`'s own
     policy sends to `.claude/rules/`.
5. **`HEADLESS_FILES` matches a bare filename anywhere in the tree**
   (`tests/test_architecture.py:54`, 59 names). Two names match no file (`categories.py`,
   `catalogue.py`), and any future `schedule.py` or `edits.py` is forced headless.
6. **Small duplications:**
   - three git runners: `core/storage/git.py`, and two in `core/storage/sparse.py`
   - two `gh` wrappers: `core/storage/github.py`, `modules/github/gh.py`
   - three detached spawns. Only the launcher sets the Windows flags; `spawn_instance`
     (`library/module.py:45`) relies on `start_new_session`, which is POSIX-only.

## (b) Emerging bad patterns

1. **The composition root is where cross-module features live.** `default_modules()` is
   one function of 2,061 lines. The business-logic clusters in the root:

   | Cluster | Approximate lines |
   |---|---|
   | agent briefing and prompt text | ~800 |
   | status, time and due | ~360 |
   | step identity and card look | ~320 |
   | coverage and collectors | ~250 |
   | branches and worktrees | ~200 |
   | ledger | ~70 |
2. **The step ontology has no owner.** The ranking (milestone > feature > check > wait > cut
   > review > agent) is written separately in about six places:
   - `_step_key` (`__init__.py:2837`)
   - `_step_kind` (2874)
   - `_step_type_icons` (2975)
   - `step_accent`'s body tone (717)
   - `_scope_kinds` (3783)
   - the template list (812–863)
   - plus `docs/activity.py:550` and the prose in `project_editor/renderers.py:238`

   "Done" means three things:
   - `_is_done`: the raw status
   - `_card_status(...) == DONE`: a wait or a cut is never done
   - `_status_in`: a wait counts as done once it is over

   Vocabulary is copied as literals: `"done"` (root:704, 719, `coverage/trace.py:361,452`),
   the agent-run states (root:685–691), the PR states (root:707). The root admits the
   duplication at 879: "change one, change the other".
3. **Package names that no longer say what they hold**, detailed in [renaming.md](renaming.md):
   - `projects` holds the `step` CLI noun.
   - `project_editor` is the canvas.
   - `progression` is the Step statuses tab and the Control Centre.
   - `step_order` holds Expenditure.
   - `step_agent_instruction` holds Run Agent.
   - `step_agent_run` holds a second module id, `agent_usage`.
4. **No file-role convention for a tab.**
   - A tab lives in `activity.py` in 7 modules and inside `module.py` in 3.
   - `view.py` means five things across 10 modules.
5. **`framework/` is gathering features**: `llm*`, `key_dialog`, `dictation*`, `recording`,
   `motion/`. Each is a divergence from app-framework.
6. **`domain/` is gathering aspect vocabulary.**
   - `progression.py:71` owns the status words.
   - `shelf.py` reserves a `module_data` key.
   - `schedule.py` mixes formatting (`format_date`, `axis_ticks`) with simulation.
7. **Off-stack mutations are spreading** beyond the two documented kinds.
   - `.redo(library)` is called directly in `step_status/aspect.py:154,173`,
     `step_agent_run/aspect.py:105,116` and `step_review/rounds.py:205`.
   - `projects/cli.py:765,1030,1052` call membership without an origin.
8. **Tests are flat.** `tests/modules/` has 110 files, and 48 of them are not named for their
   package, so the rules files' `paths:` list test globs by hand.

## (c) Cracking seams

The summary is below; [seams.md](seams.md) has the detail.

1. **Two two-writer bugs (verified).**
   - `write_atomic` uses the fixed temporary name `.{name}.tmp` (`core/fsio.py:54`).
   - `set_checkout` writes the other writer's rows and then re-stamps, so their membership
     change is never adopted and the next membership flush drops it
     (`domain/store.py:584-593`).
2. **Commands are not operations.** They hold live `Node` objects, capture `before` lazily,
   use `object()` origins, and carry no id, author or base.
3. **Stale-check-then-write is not atomic.** Conflict entries are coarse: step `meta` bundles
   title, edges and number, and `project.dproj` bundles the children order and
   `last_number`, so every concurrent step add conflicts.
4. **Step numbers are minted locally** (`model.py:113`), so two writers both mint S8.
5. **Claims are machine-local with no agent identity.** `touch` can resurrect a claim that
   was ended. Auto-launch needs Qt (`QLockFile`, `Debounced`), and `due_here` is a closure
   in the GUI root.
6. **`load()` writes migrations**, so mixed builds migrate under each other.
7. **`Signal.emit` swallows slot exceptions** (`core/signals.py:61-66`), while the store's
   conflict bookkeeping rides on slots.
