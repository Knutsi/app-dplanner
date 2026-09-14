---
paths:
  - "src/dplanner/app.py"
  - "src/dplanner/core/{telemetry,wav}.py"
  - "src/dplanner/cli/telemetry.py"
  - "src/dplanner/domain/dictation.py"
  - "src/dplanner/framework/{debounce,diagnostics,session,builder,services,llm,llm_service,tasks,task_runner,gc_policy,dictation,dictation_verb,recording,key_dialog}.py"
  - "src/dplanner/modules/{llm,anthropic,openai,dictation,dictation_whisper,taskcenter}/**"
  - "tests/conftest.py"
  - "tests/core/test_{telemetry,wav}.py"
  - "tests/domain/test_dictation.py"
  - "tests/framework/test_{debounce,diagnostics,session,builder,llm_service,task_runner,gc_policy,dictation_service,dictation_verb,recording,key_dialog}.py"
  - "tests/cli/test_telemetry_verbs.py"
  - "tests/modules/test_{dictation_module,dictation_whisper,openai_dictation}.py"
  - "tests/test_measure_scaling.py"
  - "scripts/{measure_scaling,synthetic_library,render_dictation}.py"
---

# Runtime — telemetry, diagnostics, discarding a build, LLM calls and dictation

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
- **Dictation is a provider, and capture is a peer process.** Every markdown strip carries
  a microphone (`framework/dictation_verb.py`, `Ctrl+Shift+D` on the editor), and what it
  runs on is a `DictationProvider` record from a module's Qt-free `dictation.py`
  (`domain/dictation.py` is the contract, the `AgentHarness` shape; `dictation_providers()`
  in the root is the tuple). **A provider is batch or live, derived never declared**: one
  with `transcribe` gets the WAV once the microphone is off and the transcript lands
  through `ProseEdit.insert_at_caret` as one sealed insert; one with `listen` is fed the
  samples as they come and its deltas land at a session cursor while the person speaks —
  the whole session **one undo step**, because the verb holds `UndoService.begin_gesture`
  open from the first word to the stop and nothing can be undone under it. The whisper
  commands (`modules/dictation_whisper/`) are batch; OpenAI's Realtime session
  (`modules/openai/dictation.py`) is live, on the key the vendor module already keeps.
  **PySide6-Essentials ships no QtMultimedia**, so the microphone is read by a recorder
  row — `pw-record`, `parecord`, `arecord`, `ffmpeg`, `sox` — streaming raw 16-bit mono
  samples to a `QProcess` on the GUI thread (`framework/recording.py`; *Automatic* is the
  first installed, the rate is the provider's, and the stop is one sequence everywhere:
  `q`, terminate, kill after a grace). `DictationService` (`framework/dictation.py`) is on
  the bundle, owns the **one** task runner (a closed tab must never strand a task) and
  memoises `status()` between `config_changed`s; `Dictation` is the one state machine the
  strip's verb and the settings page's *Try it* both run. A host that re-binds or tears
  down its editor calls `abandon_dictation()` first — a dictation belongs to the document
  it was started over. The verb is **greyed with its reason in its words**; the editor
  wears an accent edge (`dictating`) while the microphone is on; nothing meters the level
  — the clip's RMS is read once after a batch stop and silence is refused before a
  provider is paid. Settings ▸ Dictation is two preset fields (`modules/dictation/`), the
  checklist's two *Services* rows name `dictation.settings` as their mend, and a
  provider's `setup_action` (`openai.key`, the `ApiKeyDialog` wizard on
  `framework/key_dialog.py`) is the button beside its refusal. `ARCHITECTURE.md`'s
  *Dictation is a provider, and capture is a peer process* has the reasoning.

**A settle is deterministic, and the suite never reads the shell it runs in.**
`DebounceService.flush_all` runs pending rebuilds in registration order and re-runs
whatever a flush made pending, because a `WeakSet`'s order moved with every allocation in
the process and a rebuild that triggers another (the progress recorder writing after a
change, which the Time tab hears) was settled before or after it by chance — a Time tab
test passed on one commit and failed on the next for a change that never touched it. And
`tests/conftest.py` scrubs `DPLANNER_PROJECT`: Run Agent's wrapper exports it into an
agent's shell, and an agent running the suite handed every CLI test the wrong project.
