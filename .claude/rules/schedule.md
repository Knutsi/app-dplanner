---
paths:
  - "{src/dplanner,tests}/modules/{schedule,status_board,step_order,estimation,step_wait}/**"
  - "src/dplanner/domain/ordering.py"
  - "src/dplanner/planning/{schedule,progression,status,estimate,dates}.py"
  - "src/dplanner/cli/report/axis.py"
  - "src/dplanner/theme/palettes.py"
  - "tests/domain/test_ordering.py"
  - "tests/planning/test_{schedule,progression,status,dates}.py"
  - "tests/cli/test_{time_matrix,progression_verbs}.py"
  - "scripts/render_boards.py"
---

# Schedule — order, progression, time estimates, progress and milestone colour

- **Progression is derived, never stored** — `planning/progression.py` is the graph's
  readiness with a `status_for(step)` handed in (a wait's status depends on the day); the
  Step statuses tab, the Control Centre, `dplanner progression show` and `--json` read one
  function, and the
  frontier is a per-step check, not `ordering.ready()`'s wave one. **Ready for review and
  ready to merge are on the board and not done**: each is a partition of its own
  (`review`, `merge`), one move away for the lookahead, out of the percent — and a plain
  `requires` is fulfilled by `done` alone, so nothing starts on work nobody accepted.
  **An auto-progress link is fulfilled from review on** (`auto_progresses`, handed in beside
  `status_for`): `progression.outstanding()` is the one answer the frontier, the lookahead
  and Run Agent's gate read, so a step that collects its sources is Ready to start once they
  are under review (`graph-model.md`).
  **Some of Ready to start is due, and an agent waiting on a person is on the board.**
  `progression.due` is the part of the frontier nobody decides to launch — an agent step,
  pending, no run, a prerequisite fulfilled *through* an auto-progress link — read with the
  review turns by `agent_launch/due.py`'s `due_now`, marked `due` by `progression show`, and launched by
  a window (`agents.md`). `asks_person` (the agent-run aspect's reading: `plan-for-review`,
  `needs-input`, or a plan-mode launch that has said nothing since) splits running work
  into `asking`, the **Waits for you** group under Blocked on both boards and in
  `progression show`; the report keeps the default, since it publishes the plan.
  **Ready for review is a person's turn**: `progression.taken` — a step waiting on it across
  an auto-progress link, worked by an agent (`is_agent`, handed in beside `asks_person`),
  neither blocked nor done — splits work an agent takes on into `taken`, off both boards
  like running work and *Taken by an agent* in `progression show`, so the boards' *Ready for
  review* is exactly what the canvas pulses for (`canvas.md`).
  **Every partition a person acts on is ranked by `unlocks`** (the map covers every step
  of work not done), ties in project order. **The surface is named for the question and
  the derivation for the answer**: the tab, its menu entries and its index row say *Step
  statuses* — the title adds how many rows need a person — and the package is `status_board`,
  while the walk, the module id, the activity kind and the verb stay `progression`, because the groups are some of the
  partitions it computes and a renamed verb would move under every agent that has the
  skill. **The tab is a table of what needs a person**, never lanes: Blocked, Ready to
  merge, Ready for review, Ready to start, then Waiting (temporary, until a tab of what is
  going on exists); running work is not listed, the header's percent and bar are gone, a
  `Segmented` picks one group, and the strip seats the registry verbs the root names
  (`StripVerb`: Run Agent with its profiles, Ready to Merge, Done) over the ticked rows —
  a check column, whose box is the selection — and every row ends in a ⋮ rendering the
  Step menu's `agent`, `open` and `surfaces` bands (`ROW_MENU`), which picks its row
  alone first. **The Control Centre is every project's Step statuses as one board**
  (`ControlCentreActivity`, a singleton: the index's row after Home, and Go ▸ `home`):
  each project is walked on its own and the board is `progression.merge` of the walks — `across()` in the
  terminal — re-ranked by `unlocks`, ties going library order then the project's own; rows
  name their project (the Project column stands down on one project's tab) and a
  *Projects* `FilterButton` narrows by re-merging, never re-walking. The two tabs are
  siblings on `StatusBoard`, never one class with a scope, because `follow_project_tabs`
  closes a project's tab with its project; both re-run on `clock.day_changed`, so a step
  behind a dated wait joins Ready the morning it may start. `dplanner progression show
  --all [PROJECT …]` is its terminal half — positionals, since `--project` is every verb's
  own option — with each row's `project` and `agent` in the text and the JSON alike.
  `ARCHITECTURE.md`'s *Progression is the status-aware frontier* has the partition rules
  and why each was a decision.
- **The order says what order, and how much — never when.** The Order tab is the index,
  the step, its wave and its estimate, under one line of volume (`planning/schedule.py`'s
  `volume_words`: *62 days over 24 steps, 2 unestimated*, the sentence `order show`,
  `estimate rollup` and the Estimates tab's strip all print). It ran a serial calendar
  once — accumulated days, days since the last milestone, a landing date per row, from a
  start date set on that page — and nobody schedules that way: `schedule` simulates
  two pools of workers and owns the start date, so the columns and the bar are gone and
  **wave 1 is called *Wave 1***, the words *Ready to start* now naming a group of the
  Step statuses tab alone.
  The CSV export and the published report keep the day counts and the dates, because a
  spreadsheet is opened to sort and sum.
- **Staffing what-ifs are derived; only the assumptions are stored.** `dplanner schedule
  matrix` and the Time tab are one derivation — `planning/schedule.py`'s `phases` over
  `parallel_finish`, a deterministic two-pool greedy simulation (longest remaining chain
  first, ties by project order) reading the estimate (`planning/estimate.py`) and handed
  `is_agent` and `is_milestone` as functions. The matrix prints the grid of teams; **the tab runs one staffing, the stored
  one** (`Readers.snapshot`, the recorder's own call) — trying another team is choosing it.
  **Milestones run in sequence**: each stretch is a
  milestone's `ordering.cone` truncated at the milestones before it, simulated on its own
  (`parallel_finish`'s `among`) from where the previous one lands — with what is left of
  that day — or from a date of its own, when it has one and that is later; an earlier
  date is *pushed* and reported, never silently overlapped. Calendar time is the same
  walk over another `days_for` (`schedule/assumptions.py`'s `stretched`), so the
  planning tier never learns what an efficiency is — the one kind of caller `days_for`
  survives for, with the simulator's world and a test's fakes. Five assumptions reach disk, all under the id `time_estimates`: the focus
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
  the calendar fades the other stretches. **A calendar day two stretches are both worked
  is a stripe of each**, and a landing fills its day with every milestone landing on it.
  A cycle a hand-edited file smuggled in is named by `ordering.cyclic()` and the tab says
  so instead of drawing a calendar over a broken walk. `ARCHITECTURE.md`'s *Time estimates: two
  worker pools, one greedy simulation* has the reasoning.
- **The plan re-dates itself from what has happened, and facts beat the sequence.**
  `phases` handed `ScheduleFacts` — `schedule/assumptions.py`'s `schedule_facts`: the
  stored statuses and their `since`, which steps are markers (estimate off), and work in
  flight credited at the focus it ran at — keeps the plan's own dates while every step is
  done exactly when they land it, and otherwise resumes the rest from tomorrow: done steps
  dated by their `since`, work in flight first and credited, a stretch whose work is done
  dated by it whatever its markers say, the whole landing with its **latest** stretch.
  **Work already started in a stretch not reached yet runs now**, keeping its worker from
  tomorrow beside the stretch being worked and done where it belongs the day it lands, and
  **a marker takes no worker** — both measured with the simulator's parallel scenarios
  (`ARCHITECTURE.md`'s *Milestones worked in parallel*, which also has the candidates
  rejected and why).
  **Review and merge are work in flight, dated from when it started** — one fold,
  `planning/status.py`'s `in_flight` / `work_since`, which every time surface reads by
  default: `in_flight` answers in progress for both, and `work_since` their `started`,
  because moving to review stamps `since` today and the model credits in-flight work from it — the raw day re-costed the
  step at its whole estimate the moment an agent finished. `status.read_since` keeps the
  raw day for what a recorded day counts as a change. `test_time_simulation.py` pins both.
  **Adjust for Efficiency** is the tab's opt-in exception: people's remaining work at the
  pace so far (`schedule.pace_so_far` — finished steps' stretched days over the working
  days they took, each half day shared among people's steps open in it; five working days
  and three steps first, a tenth either way is the plan's, ¼–4×), handed in as
  `resume_days` = `stretched` at the measured focus, so it moves only a
  plan that no longer holds. A per-user preference (`user_config`), off by default, that
  reaches the page alone — never the recorder, a saved snapshot or the report.
  **Every surface that dates the plan hands the facts in** — the tab, the recorder,
  `schedule matrix`, `progress show|record` and the report — reading a day still going
  (`day_over` False: a step due today has until tonight); only the parity harness and the
  simulator read days that are over. **The model is the prototype's to the day**:
  `tests/modules/schedule/test_time_parity.py` replays its scenarios through the real aspect writers
  (`simulation/frames.py`) and compares every forecast, so a model change that moves one
  of them is made in the prototype first, its fixture regenerated, then here; one that
  moves none — milestones worked in parallel, which its scenarios never play, and *Adjust
  for Efficiency*'s pace, which the file does not compare — is measured with
  `scripts/time_accuracy.py` over all fifteen. A stretch's `start` is where its
  remaining work begins and `began` when its work first began — a view shows `began`.
  `ARCHITECTURE.md`'s *The plan re-dates itself from what has happened* has the reasoning.
- **A wait is a step that holds, and no work.** `modules/step_wait/` marks a step
  `{"until": …}` — what requires it may start on that day — or `{"days": n}` working days
  from when it is reached (`planning/wait.py`'s `Wait`, which every walk reads by
  default; the simulator hands in its own `wait_of`). `parallel_finish` releases a wait without a worker; `phases` ends an
  `until` wait at its day's first moment and, re-dated, credits a `days` wait with the days
  it has already waited; `_holds` asks a wait only when it was made. **No tally counts
  one** — `snapshot_of`, `time_report`'s effort and the unsized count leave it out. A step,
  never a kind of node, so it works unchanged in cones, ordering, cycles and copy and paste.
  Its model is the prototype's Delay, to the day (`test_schedule.py`'s waits), and so is
  the simulator's world (`test_time_waits.py`). **Elsewhere a wait is done when it is over
  and no work at all**: the Step statuses tab, its verb and report and the Run Agent gate read
  `schedule.wait_status` — done once what it waits on is done and its day has come or its
  days are waited, `Waiting` until then — so what follows it is ready that day; the root's
  one `_counts_as_work` keeps it off every row and out of every volume (`schedule.volume`:
  the Step statuses tab, the Estimates tab, `estimate rollup`, `schedule show`, `order show`, the Order
  tab) and lint; the Status verbs, the Agent and Test toggles and Run Agent refuse one,
  saying why (`aspect_toggle`'s `refusal`). **A wait looks like one**: `W` for its key's
  letter, the clock in its key block in the attention amber — nobody works a wait, and it
  says so whatever its date — and how long it holds for its stat; the Work page hatches
  its days through both plots and names it, the calendar hatches them, a milestone's words
  name the waits in its stretch, and the report draws them as pale bands — all from
  `Snapshot.waits`, the plan's waits as it dates them now, never recorded, so History shows
  none. *Insert Wait Before* (`W` on the canvas) puts a wait of a day in front of a step —
  it takes what the step waited on — as one undo, born through the graph editor's
  `create_step`.
  `ARCHITECTURE.md`'s *A wait is a step that holds* has the reasoning.
- **The simulator is the prototype's, to the frame, and Debug ▸ Time Simulation shows it in
  the real tab.** `schedule/simulation/` is Qt-free: `world.py` plays a scenario,
  `replay.py` writes each day through the owners' writers (`frames.Writers`, every one
  a `planning/` writer) and records it as the recorder would, and `test_time_simulation.py`
  holds the world to the prototype's exported frames — port a change to the world there
  first, like one to the model. `simulator_activity.py` embeds `TimeEstimatesActivity` built from
  the root's own `time_deps` recipe over a scratch library, undo stack, context, clock and
  debounce service — never `dataclasses.replace` over the window's deps — and scrubs by
  `replay.restore`, never by rebuilding the tab; the embedded tab's writers are greyed
  (`set_read_only`, the simulator writes that plan) and *Hold the Axes Still* hands it the
  whole run's rows to hold (`hold_reach`). Three scenarios are this simulator's own —
  *Two tracks*, *Multitasking*, *Late marking*, milestones worked in parallel, which the
  prototype never played (a `SampleShape` of two `tracks`, a world's `juggle` and
  `mark_late`). `scripts/time_accuracy.py` is the number to quote for a model change,
  printed as recorded and with *Adjust for Efficiency* on. `ARCHITECTURE.md`'s *The Time
  tab has a simulator* has the reasoning.
- **Progress is derived; the past is a list of snapshots, and a comparison is two of
  them.** How far a milestone has come — by estimated days, everything through its
  stretch; the count of steps is tallied and worded, never the share — is
  `schedule/progress.py` over the statuses (`status.in_flight` by default),
  and the plan's expected curve is the simulation's own per-step landings
  (`planning/schedule.py`'s `ParallelFinish.landings`, carried on each `Phase`). The one
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
  (`shift_chart.py`) is a row per milestone — the landing then hollow, now filled, a check
  once done, an arrow between, each mark dated (`row_dates`'s rule) and a hairline to the
  axis. *Work* (`work_chart.py`) is two plots on **one scale in days**
  (`Presented.scale`): the scope against the plan compared with, warm where it holds more
  and cool where less, a ▲ or ▼ each day it changed (`scope_marks`, by the day's sum);
  and the work done, **dotted, paler, across a day no step changed status** (`Burnup.active`),
  beside the plan's schedule from the day shown on, each milestone marked where it ends —
  **milestones landing on one day share the mark**, a wedge each, and the name.
  Weekends are pale bands through both. **Both surfaces draw the same page**: the report's
  `Chart` of `Plot`s (`shift`, `scope`, `done`) and `Stretch`es is `present.py`'s output
  said as plain data (`schedule/report.py`), drawn by `cli/report/drawings.py`.
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
  one answer.** `schedule.py`'s `milestone_colors(library, project)` is the
  deal — `ordering.placed`'s sequence, a milestone's own chosen colour over its dealt
  shade — walked once per project and handed down by the composition root as a typed
  callback, so no module learns where a colour map is stored. Ten surfaces
  read it: the canvas card, its badge and its tag medallion, the order table's row wash
  and **key badge**, the Step statuses tab's key badge, the Tests tab's grouping heading,
  the Docs tab's medallion, the coverage lane, the Milestone tab's swatch, the calendar's
  bands and the report's graph. `theme/tones.py`'s `toned(name, hex)` is the one place a
  shade takes a tone's alphas — never re-derive them — and the maps live in
  **`theme/palettes.py`** (Qt-free, hex strings) because three consumers need them and
  modules never import each other. **The map is the project's, never the user's**: a
  report site exported by any of a project's people should paint its milestones alike. *View ▸ Milestone Colours* is therefore a **second presenter** of
  the choice the Time tab's picker and `dplanner schedule palette` already write — a
  sibling of Theme, never inside it, and greyed with its reason when no project is open.
  `ARCHITECTURE.md`'s *Colour is a place on one map* has the reasoning.
