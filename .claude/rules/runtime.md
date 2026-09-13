---
paths:
  - "src/dplanner/app.py"
  - "src/dplanner/core/telemetry.py"
  - "src/dplanner/cli/telemetry.py"
  - "src/dplanner/framework/{debounce,diagnostics,session,builder,services,llm,llm_service,tasks,task_runner,gc_policy}.py"
  - "src/dplanner/modules/{llm,llm_anthropic,llm_openai,taskcenter}/**"
  - "tests/conftest.py"
  - "tests/core/test_telemetry.py"
  - "tests/framework/test_{debounce,diagnostics,session,builder,llm_service,task_runner,gc_policy}.py"
  - "tests/cli/test_telemetry_verbs.py"
  - "tests/test_measure_scaling.py"
  - "scripts/{measure_scaling,synthetic_library}.py"
---

# Runtime — telemetry, diagnostics, discarding a build and LLM calls

- **Every action, command and slow slot is a span, and the journal is how you find out
  why.** `core/telemetry.py` is one process-wide journal, like `logging`: `ActionRegistry.run`
  (every presenter's one path — the menu bar's QAction goes through it too), `UndoService`'s
  push/undo/redo, `TaskService.finish`, autosave's flush, the disk poll, the session's
  open/reload/refresh, each CLI run and each `Debounced` run are spans; `Signal.emit` times
  every slot and journals one over `SLOW_MS` (20 ms) by `Class.method (file:line)`, nested
  under the action or command it ran inside. Failures arrive through logging — `install()`
  puts a handler on the root logger, so every `logger.exception` is a `failure` span with its
  traceback — which is also why **the test suite fails on a slot that raised**
  (`tests/conftest.py`; mark a test that means to with `raises_in_a_slot`). *Debug ▸
  Telemetry* and `dplanner telemetry show --slow 50` / `--failures` are the two readers of
  the one file under `config_dir()/telemetry/` (`FORMAT.md`). Measure with it before
  guessing: `uv run python scripts/measure_scaling.py` builds the application over
  `scripts/synthetic_library.py`'s library at several sizes, runs every gesture the window
  has — edit bursts, a click, the details dialog, a tab open, a paint, the poll, a full
  collection — and prints what each view paid, by size; `synthetic_library.py --out DIR`
  leaves the same library where a window can open it. `ARCHITECTURE.md`'s *How the
  application scales* has the numbers, and they are the ones to quote before changing a
  delay.
  **A module opens a span of its own where the action's cannot answer.** `agent.launch`
  is the example: one per shell, carrying that briefing's `prompt_chars`, because a single
  gesture launches a shell per chosen step and three sizes can never be one detail key on
  the parent. And a verb body could not add detail to the enclosing action span in any
  case — `recent()` and `open_spans()` hand out **copies** on purpose
  (`tests/core/test_telemetry.py`), so reaching into what is open is not a thing the
  journal offers. Open a child span; never add an accessor for the live one.
- **A hang is sampled and a crash leaves a stack.** `framework/diagnostics.py`, started from
  `app.main` and nowhere deeper: a 100 ms heartbeat, and a daemon thread that samples the
  GUI thread's stack when the beat is 250 ms late and opens a `stall` span saying what it
  interrupted ("stall 1.2 s during action steps.delete"); `sys.excepthook`,
  `threading.excepthook` and Qt's message handler chained into `failure` spans;
  `faulthandler` on `crash.log` beside the journal; a `session` start and end record, so a
  session without an end is visible afterwards. Never start any of it from the builder — a
  test build has no event loop, and pytest owns the hooks while a test runs.
- **Discarding a build is `discard_build()`, and closing the window is not enough.** Qt keeps
  a closed `QWidget` in `topLevelWidgets()`, so without `deleteLater()` the whole build —
  services, model, every module — stays reachable forever. Nobody notices in the application;
  the test suite builds one per test, and the omission made it quadratic and cost it 80% of
  its running time. Never hand-roll the close sequence: a reload and a test both call that
  one function. Anything that discards Qt objects with **no event loop to follow** must
  dispatch the deferred deletes itself (`sendPostedEvents(None, DeferredDelete)` — never
  `processEvents`, which skips them); `AppSession.close()` is the only place that does.
  `ARCHITECTURE.md`'s *Closing a window is not discarding it* has the measurements.
- **An LLM call is a task, and the service is GUI-bound.** `framework/llm_service.py`'s
  `complete()` is blocking network I/O, so it runs in a `TaskRunner` body and the answer
  comes back on the owner's own Qt signal — the runner has no result seam. Every call is
  already in its ring buffer, so nothing logs one. An AI-gated control is **disabled, never
  hidden**, carrying `status().message`, and re-asks on `config_changed`. The service reads
  its provider through QSettings and its key through the keychain, so **`cli/` cannot call
  it** — the agent loop above is the headless answer. `ARCHITECTURE.md`'s *An LLM call is a
  task* has the rest.

**A settle is deterministic, and the suite never reads the shell it runs in.**
`DebounceService.flush_all` runs pending rebuilds in registration order and re-runs
whatever a flush made pending, because a `WeakSet`'s order moved with every allocation in
the process and a rebuild that triggers another (the progress recorder writing after a
change, which the Time tab hears) was settled before or after it by chance — a Time tab
test passed on one commit and failed on the next for a change that never touched it. And
`tests/conftest.py` scrubs `DPLANNER_PROJECT`: Run Agent's wrapper exports it into an
agent's shell, and an agent running the suite handed every CLI test the wrong project.
