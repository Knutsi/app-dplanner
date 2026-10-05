# Bugs found during the run

**Summary.** These are bugs in DPlanner, the test suite and the environment, found by running the plan rather than by reading code. They do not include the correctness bugs the plan itself fixed (S2–S6) or the ones Codex found in the branch, which were fixed on the branch. Each has a reproduction, and they are ranked by harm.

## DPlanner

1. **Step keys and titles resolve across the whole library.**
   - In a plan repo with several projects, `--after S25`, `review set R26` and title arguments resolve library-wide, even with `DPLANNER_PROJECT` set.
   - An ambiguous key is refused, but a key that exists in only one *other* project is not.
   - **`review set R26` turned "DPlanner changes 2"'s S26 into a review.** That was reverted by deleting the new, untracked `modules/step_review.json`.
   - *Repro:* two projects in one plan repo; run `DPLANNER_PROJECT=<A> dplanner review set R26 …` where only project B has a key 26.
   - *Fix:* scope keys to `--project` or `$DPLANNER_PROJECT`.
2. **The window segfaults in table sizing under load** (`evidence/crash-2026-10-04-1332.log`).
   - SIGSEGV in `framework/list_rows.py:92 rich_row_height` ← `framework/table.py:370 text_width` ← `table.py:1012 sizeHint`, on the GUI thread.
   - It came after stalls of 849 ms and 441 ms, with a load average of 61 on 22 cores, while agents were writing the plan through the CLI. Load exposes this; it doesn't cause it.
   - *Repro to try:* `MALLOC_PERTURB_=165`, plus a burst of outside changes while a table rebuilds.
3. **The test suite can launch real agents.**
   - `tests/modules/test_sync.py` stubs the reconcile launch by monkeypatching `StepAgentInstructionModule.reconcile_remote` *after* the app is built.
   - S16 briefly turned two wiring lambdas into direct method references, so the stub missed, and the suite opened two real Ghostty windows running `claude` against pytest's temp repos.
   - *Fix:* a session-wide autouse fixture that makes `launcher.spawn` / `spawn_detached` raise unless a test opts in.
4. **`status set <agent step> done` from an agent shell is refused on a step that is already done.**
   - The message is the misleading "an agent's work ends at ready-for-review".
   - It should be a no-op, under the "already clear is success" convention.
5. **A stray `/tmp/.dplanner` written by `test_move_plan`** after a hung run broke `tests/cli/test_commands.py`'s upward walk. A move whose `git init` fails can write the index above the intended root. The S25 agent found it and recorded a later note.
6. **Two scripts had been silently broken for weeks:** `render_briefing_size.py` and `render_signalling.py`. S7's new import smoke test found them, and they are now allow-listed on a ratchet.

## Test suite (flaky under load)

- `tests/modules/test_testing.py::test_double_clicking_a_row_names_the_rows_own_step` and `…_reveals_the_panel` **failed in 5 of 16 parallel runs** and always passed alone. They depend on focus, which is the pattern CLAUDE.md warns about.
- `test_dictation_module.py::test_try_it_records_transcribes_and_says_what_it_heard` and a `test_debug` strip-words test were also timing-flaky under load.

## Environment

- **`/tmp` is a RAM-backed tmpfs.**
  - It was 76% full: 3.5 GB of other Claude sessions' scratch plus 1.3 GB of pytest leftovers.
  - That starved memory, got the director's background checks reaped, and most likely killed a suite's xdist workers. The master then waited 7.5 hours.
- **Codex usage limits** were hit twice in one run, at roughly three reviews per hour of use.
