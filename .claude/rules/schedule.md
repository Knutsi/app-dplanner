---
paths:
  - "src/dplanner/modules/{time_estimates,progression,step_order,estimation,step_wait}/**"
  - "src/dplanner/domain/{schedule,progression,ordering}.py"
  - "src/dplanner/theme/palettes.py"
  - "tests/modules/test_{time_estimates,time_progress,time_present,time_pace,progression_board,step_order,milestone_colors,estimation_bulk}.py"
  - "tests/domain/test_{schedule,progression,ordering}.py"
  - "tests/cli/test_time_matrix.py"
  - "scripts/render_boards.py"
---

# Schedule — order, progression, time estimates, progress and milestone colour

- **Progression is derived, never stored** — `domain/progression.py` is the graph's
  readiness with a `status_for(step)` handed in like `days_for`; the board, `dplanner
  progression show` and `--json` are three readers of one function, and the frontier is a
  per-step check, not `ordering.ready()`'s wave one. **The surface is named for the
  question and the derivation for the answer**: the tab, its menu entries and its index
  row say *Ready to start*, while the walk, the module id, the activity kind and the verb
  stay `progression`, because the frontier is one of the six partitions it computes and a
  renamed verb would move under every agent that has the skill. Its header is the percent
  and the bar — the two lines under the bar said the same counts in words and then again
  in estimated days, which the bar draws to scale; the terminal still prints both, where
  there is no bar to read. `ARCHITECTURE.md`'s *Progression is the status-aware frontier*
  has the partition rules and why each was a decision.
- **The order says what order, and how much — never when.** The Order tab is the index,
  the step, its wave and its estimate, under one line of volume (`domain/schedule.py`'s
  `volume_words`: *62 days over 24 steps, 2 unestimated*, the sentence `order show`,
  `estimate rollup` and the Estimates tab's strip all print). It ran a serial calendar
  once — accumulated days, days since the last milestone, a landing date per row, from a
  start date set on that page — and nobody schedules that way: `time_estimates` simulates
  two pools of workers and owns the start date, so the columns and the bar are gone and
  **wave 1 is called *Wave 1***, the words *Ready to start* now naming the board alone.
  The CSV export and the published report keep the day counts and the dates, because a
  spreadsheet is opened to sort and sum.
- **Staffing what-ifs are derived; only the assumptions are stored.** `dplanner schedule
  matrix` and the Time tab are one derivation — `domain/schedule.py`'s `phases` over
  `parallel_finish`, a deterministic two-pool greedy simulation (longest remaining chain
  first, ties by project order) handed `days_for`, `is_agent` and `is_milestone` as
  functions. The matrix prints the grid of teams; **the tab runs one staffing, the stored
  one** (`Readers.snapshot`, the recorder's own call) — trying another team is choosing it.
  **Milestones run in sequence**: each stretch is a
  milestone's `scope.cone` truncated at the milestones before it, simulated on its own
  (`parallel_finish`'s `among`) from where the previous one lands — with what is left of
  that day — or from a date of its own, when it has one and that is later; an earlier
  date is *pushed* and reported, never silently overlapped. Calendar time is the same
  walk over a wrapped
  `days_for` (`time_estimates/schedule.py`'s `stretched`), so the domain never learns what
  an efficiency is. Five assumptions reach disk, all under `time_estimates`: the focus
  factor, the colour map and the **team** the calendar is dated for on the project node
  (one `Assumptions` record, `schedule.py`'s `read_assumptions`/`write_project` — a
  control changing one carries the others as stored), and a milestone's start date and
  colour on its step — written by the tab's **Budget** (`budget.py`: people, agents and
  focus in one popover, one undoable *Set Budget* writing only what the pick changed, from
  today on), its ⋯ palette, the milestone's own **Schedule** block on its Details tab
  (`section.py`, `shown_for` milestones — a milestone's assumptions are edited where the
  milestone is) and `dplanner schedule focus` / `schedule palette` / `schedule team` /
  `schedule milestone` alike. **Milestones are shades of one map, dealt by place in the
  sequence** (`theme/palettes.py`'s `PALETTES` and `shades`), never a list of hues. **Four
  figures lead the tab** (`activity.py`) — where the plan lands (✓ and the day once done),
  how far that moved in working days against the plan compared with, how much is done by
  estimated days, and how many steps nobody sized, a click opening the Estimates tab on
  them through `TimeEstimatesDeps.estimate_missing` — over one `Toolbar`: the pages (a
  `Segmented`: *Milestones*, *Work*, *Calendar*), *Compared with*, the Budget, *Save
  Snapshot…*, ⋯ and Export. A pick on the Milestones page **highlights, never hides**:
  the calendar fades the other stretches. A cycle a
  hand-edited file smuggled in is named by `ordering.cyclic()` and the tab says so instead
  of drawing a calendar over a broken walk. `ARCHITECTURE.md`'s *Time estimates: two
  worker pools, one greedy simulation* has the reasoning.
- **The plan re-dates itself from what has happened, and facts beat the sequence.**
  `phases` handed `ScheduleFacts` — `time_estimates/schedule.py`'s `schedule_facts`: the
  stored statuses and their `since`, which steps are markers (estimate off), and work in
  flight credited at the focus it ran at — keeps the plan's own dates while every step is
  done exactly when they land it, and otherwise resumes the rest from tomorrow: done steps
  dated by their `since`, work in flight first and credited, a stretch whose work is done
  dated by it whatever its markers say, the whole landing with its **latest** stretch.
  **Adjust for Efficiency** is the tab's opt-in exception: people's remaining work at the
  pace so far (`schedule.pace_so_far` — finished steps' stretched days over the working
  days they took; five working days and three steps first, a tenth either way is the plan's,
  ¼–4×), handed in as `resume_days` = `stretched` at the measured focus, so it moves only a
  plan that no longer holds. A per-user preference (`user_config`), off by default, that
  reaches the page alone — never the recorder, a saved snapshot or the report.
  **Every surface that dates the plan hands the facts in** — the tab, the recorder,
  `schedule matrix`, `progress show|record` and the report — reading a day still going
  (`day_over` False: a step due today has until tonight); only the parity harness and the
  simulator read days that are over. **The model is the prototype's to the day**:
  `tests/modules/test_time_parity.py` replays its scenarios through the real aspect writers
  (`simulation/frames.py`) and compares every forecast, so a model change is made in the
  prototype first, its fixture regenerated, then here. A stretch's `start` is where its
  remaining work begins and `began` when its work first began — a view shows `began`.
  `ARCHITECTURE.md`'s *The plan re-dates itself from what has happened* has the reasoning.
- **A wait is a step that holds, and no work.** `modules/step_wait/` marks a step
  `{"until": …}` — what requires it may start on that day — or `{"days": n}` working days
  from when it is reached; the root hands the time module `wait_of`, the domain's `Wait`,
  beside `days_for`. `parallel_finish` releases a wait without a worker; `phases` ends an
  `until` wait at its day's first moment and, re-dated, credits a `days` wait with the days
  it has already waited; `_holds` asks a wait only when it was made. **No tally counts
  one** — `snapshot_of`, `time_report`'s effort and the unsized count leave it out. A step,
  never a kind of node, so it works unchanged in cones, ordering, cycles and copy and paste.
  Its model is the prototype's Delay, to the day (`test_schedule.py`'s waits), and so is
  the simulator's world (`test_time_waits.py`). **Elsewhere a wait is done when it is over
  and no work at all**: the board, its verb and report and the Run Agent gate read
  `schedule.wait_status` — done once what it waits on is done and its day has come or its
  days are waited, `WAITING` until then — so what follows it is ready that day; the root's
  one `_counts_as_work` keeps it off every lane and out of every volume (`schedule.volume`:
  the board, the Estimates tab, `estimate rollup`, `schedule show`, `order show`, the Order
  tab) and lint; the Status verbs, the Agent and Test toggles and Run Agent refuse one,
  saying why (`aspect_toggle`'s `refusal`).
  `ARCHITECTURE.md`'s *A wait is a step that holds* has the reasoning.
- **The simulator is the prototype's, to the frame, and Debug ▸ Time Simulation shows it in
  the real tab.** `time_estimates/simulation/` is Qt-free: `world.py` plays a scenario,
  `replay.py` writes each day through the owners' writers the root hands in
  (`_time_writers`) and records it as the recorder would, and `test_time_simulation.py`
  holds the world to the prototype's exported frames — port a change to the world there
  first, like one to the model. `debugger.py` embeds `TimeEstimatesActivity` built from
  the root's own `time_deps` recipe over a scratch library, undo stack, context, clock and
  debounce service — never `dataclasses.replace` over the window's deps — and scrubs by
  `replay.restore`, never by rebuilding the tab; the embedded tab's writers are greyed
  (`set_read_only`, the simulator writes that plan) and *Hold the Axes Still* hands it the
  whole run's rows to hold (`hold_reach`). `scripts/time_accuracy.py` is the number
  to quote for a model change. `ARCHITECTURE.md`'s *The Time tab has a simulator* has the
  reasoning.
- **Progress is derived; the past is a list of snapshots, and a comparison is two of
  them.** How far a milestone has come — by estimated days, everything through its
  stretch; the count of steps is tallied and worded, never the share — is
  `time_estimates/progress.py` over the statuses (`status_for`, handed in like `days_for`),
  and the plan's expected curve is the simulation's own per-step landings
  (`domain/schedule.py`'s `ParallelFinish.landings`, carried on each `Phase`). The one
  thing that cannot be derived is the past: a `Snapshot` — one row per stretch, steps,
  done, days, done days, start, landing, and the **landing knots** the curve is drawn
  through — is written under a second module id, `progress_history` (format 3), in two
  lists. **Automatic** days, **only on a day something in the plan changed** (a step or
  an estimate added or removed, a link, a status, a milestone dated) **or a status was
  set** — each stretch counting the steps whose status changed that day (`changed`, from
  the status aspect's `since`), so a day of work is told from a quiet one when nothing
  landed, while a day that only differs from yesterday by that count is not written —
  last-wins within the day, by `recorder.py` after every settled change in the window, by
  `dplanner status set`/`clear` (the root's `_recording_status`, since an agent reports
  with no window open) and by `dplanner progress record` from the terminal — directly,
  with its own origin, off the undo stack
  (the PR refresher's rule — Ctrl+Z undoes the status, not the record). And **saved**
  snapshots, taken on purpose under a title and a note — *Save snapshot…* in the tab's
  strip (`snapshots.py`), `dplanner progress save|list|remove` — a decision, so pushed
  through the undo stack, never replaced by a later change and carried along by every
  automatic write. **The page compares the plan now with a plan then, picked in the
  strip** (`Pick`, `resolve`, `pick_words`): the plan at the project's start unless the
  plan a week ago, a saved snapshot or a day is chosen, resolved as the last record on or
  before the day (the earliest row for a project older than its history, but **never
  today's own record** — not even for a plan whose start is still to come — which is the
  plan now and no comparison at all; a snapshot saved earlier today is one). **Which plan
  is compared with is named, record included** — *the plan at start, recorded 9 Sep*,
  *Kickoff review (1 Nov)* — worded once (`pick_words`) for the picker's tooltip, the
  report's chart heading and `progress show`; a saved snapshot's day is a dashed hairline
  through every plot. **What a page draws is one `Presented`** (`present.py`, Qt-free,
  the prototype's `present.ts`): the figures, each milestone's landing then and now, and
  the work over the recorded days (`Burnup`), with **the axes holding the reach of every
  record** (`reach_of`) so moving between days moves only the lines. *Milestones*
  (`shift_view.py`) is a row per milestone — the landing then hollow, now filled, a check
  once done, an arrow between, each mark dated (`row_dates`'s rule) and a hairline to the
  axis. *Work* (`work_view.py`) is two plots on **one scale in days**
  (`Presented.scale`): the scope against the plan compared with, warm where it holds more
  and cool where less, a ▲ or ▼ each day it changed (`scope_marks`, by the day's sum);
  and the work done, **dotted across a day no step changed status** (`Burnup.active`),
  beside the plan's schedule from the day shown on, each milestone marked where it ends.
  Weekends are pale bands through both. **Both surfaces draw the same page**: the report's
  `Chart` of `Plot`s (`shift`, `scope`, `done`) and `Stretch`es is `present.py`'s output
  said as plain data (`time_estimates/report.py`), drawn by `cli/report/drawings.py`.
  **History** (`history.py`) is the now side: a slider over the recorded days and today,
  followed as it moves (a 0 ms `Debounced`), reading an earlier day's record in the live
  plan's place with the axes held for the live plan too; **while it looks back every writer
  is greyed, saying why** (`writers_refusal` — the Budget, ⋯, *Save Snapshot…*, a calendar
  click), and a host greys them for a reason of its own through `set_read_only`.
  **A change re-runs the page after a quiet spell, and the strip's indicator turns until
  it has** — the debounce is the coalescing, and a worker thread is not the answer (*A
  view refresh is coalesced*). The delta in words (`delta`, `delta_words`) and
  `changes_since` — the steps born and the estimates changed after the baseline's
  recorded day, from the step's `created` stamp and the estimate aspect's own history
  (`estimation`'s `read_history`; every `write` carries the value it replaced, one row
  per day, format 2; `dplanner estimate show` reads it back) — are the terminal's prose;
  the page says it with the plots. `ARCHITECTURE.md`'s *Progress against the plan* has
  the reasoning.
- **Today is the clock's, never the machine's.** Whatever dates a plan reads the day from
  `core/clock.py`'s `Clock` — `TimeEstimatesDeps.clock` and the reporting module's in the
  window (`services.clock`), `CliContext.clock` in a verb — and `format_date`/`short_date`
  are handed the same day, since whether a label prints its year is a question about
  today. A report is built *for* a day (`build(today=…)`), and every `ReportSource` is
  handed it. `day_changed` re-runs the tab and the recorder, so a window open overnight
  moves on. **A test pins it**: `services.clock.pin(…)` in the window, the `clock` fixture in
  a CLI test — never an assertion against `date.today()`. `ARCHITECTURE.md`'s *Today is
  handed in* has the reasoning.
- **A milestone's colour is its place in the project's map, and every surface reads the
  one answer.** `schedule.py`'s `milestone_colors(library, project, is_milestone)` is the
  deal — `ordering.placed`'s sequence, a milestone's own chosen colour over its dealt
  shade — walked once per project by the composition root's `_milestone_colors` and handed
  down as a typed callback, so no module learns where a colour map is stored. Ten surfaces
  read it: the canvas card, its badge and its tag medallion, the order table's row wash
  and **key badge**, the Ready-to-start board's card, the Tests tab's grouping heading, the
  Docs tab's medallion, the coverage lane, the Milestone tab's swatch, the calendar's
  bands and the report's graph. `theme/tones.py`'s `toned(name, hex)` is the one place a
  shade takes a tone's alphas — never re-derive them — and the maps live in
  **`theme/palettes.py`** (Qt-free, hex strings) because three consumers need them and
  modules never import each other. **The map is the project's, never the user's**: the
  window commits `reports/` on every Save, so a per-user map would churn the published
  report per committer. *View ▸ Milestone Colours* is therefore a **second presenter** of
  the choice the Time tab's picker and `dplanner schedule palette` already write — a
  sibling of Theme, never inside it, and greyed with its reason when no project is open.
  `ARCHITECTURE.md`'s *Colour is a place on one map* has the reasoning.
