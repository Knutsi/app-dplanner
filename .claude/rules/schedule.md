---
paths:
  - "src/dplanner/modules/{time_estimates,progression,step_order,estimation}/**"
  - "src/dplanner/domain/{schedule,progression,ordering}.py"
  - "src/dplanner/theme/palettes.py"
  - "tests/modules/test_{time_estimates,time_progress,progress_chart,progression_board,step_order,milestone_colors,estimation_bulk}.py"
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
- **Staffing what-ifs are derived; only the assumptions are stored.** The time estimates
  tab and `dplanner schedule matrix` are one derivation — `domain/schedule.py`'s
  `phases` over `parallel_finish`, a deterministic two-pool greedy simulation (longest
  remaining chain first, ties by project order) handed `days_for`, `is_agent` and
  `is_milestone` as functions. **Milestones run in sequence**: each stretch is a
  milestone's `scope.cone` truncated at the milestones before it, simulated on its own
  (`parallel_finish`'s `among`) from the working day after the previous one lands — or
  from a date of its own, when it has one and that is later; an earlier date is *pushed*
  and reported, never silently overlapped. Calendar time is the same walk over a wrapped
  `days_for` (`time_estimates/schedule.py`'s `stretched`), so the domain never learns what
  an efficiency is. Five assumptions reach disk, all under `time_estimates`: the focus
  factor, the colour map and the **team** the calendar is dated for on the project node
  (one `Assumptions` record, `schedule.py`'s `read_assumptions`/`write_project` — a
  control changing one carries the others as stored), and a milestone's start date and
  colour on its step — written by the tab's controls (a matrix tile click *is* the
  team) and `dplanner schedule focus` / `schedule palette` / `schedule team` / `schedule
  milestone` alike. **Milestones are shades of one map, dealt by place in the
  sequence** (`theme/palettes.py`'s `PALETTES` and `shades`), never a list of hues. Under the
  staffing grid, **Milestones** is one table (`milestones.py`'s `MilestoneTable`): a row
  per stretch, led by *All milestones*, the whole plan — when it begins (the day the
  sequence gives it, quieter than a day of its own, which is typed in the cell), where it
  lands, its days and how much of it has landed. Picking a row **highlights, never hides**: the calendar and every plot keep the
  whole project and fade what is outside the picked stretch. *Save Snapshot…*, Export, the
  picked milestone's colour and *Begin When the Previous Lands*, then the focus factor, the
  calendar-or-project-days lens, the palette and the two plans compared sit in one
  `Toolbar` over the page, and a banner over the answer counts
  the steps running as zero, with *Estimate missing* opening the Estimates tab on them
  through `TimeEstimatesDeps.estimate_missing`. A cycle a
  hand-edited file smuggled in is named by `ordering.cyclic()` and the tab says so instead
  of drawing a calendar over a broken walk. `ARCHITECTURE.md`'s *Time estimates: two
  worker pools, one greedy simulation* has the reasoning.
- **Progress is derived; the past is a list of snapshots, and a comparison is two of
  them.** How far a milestone has come — by estimated days, everything through its
  stretch; the count of steps is tallied and worded, never the share — is
  `time_estimates/progress.py` over the statuses (`status_for`, handed in like `days_for`),
  and the plan's expected curve is the simulation's own per-step landings
  (`domain/schedule.py`'s `ParallelFinish.landings`, carried on each `Phase`). The one
  thing that cannot be derived is the past: a `Snapshot` — one row per stretch, steps,
  done, days, done days, start, landing, and the **landing knots** the curve is drawn
  through — is written under a second module id, `progress_history` (format 2), in two
  lists. **Automatic** days, **only on a day something in the plan changed** (a step or
  an estimate added or removed, a link, a status, a milestone dated), last-wins within
  the day, by `recorder.py` after every settled change in the window and by `dplanner
  progress record` from the terminal — directly, with its own origin, off the undo stack
  (the PR refresher's rule — Ctrl+Z undoes the status, not the record). And **saved**
  snapshots, taken on purpose under a title and a note — *Save snapshot…* in the tab's
  strip (`snapshots.py`), `dplanner progress save|list|remove` — a decision, so pushed
  through the undo stack, never replaced by a later change and carried along by every
  automatic write. **The plots compare a then with a now, and both are picked in the
  strip** (`Pick`, `resolve`, `pick_words`): the then side is the plan at the project's
  start unless a saved snapshot or a day is chosen, resolved as the last record on or
  before the day (the earliest row for a project older than its history, but **never
  today's own record**, which is the plan now and no comparison at all); the now side is
  the live plan unless a saved snapshot or a day is chosen, and read as of one the
  curves stop at its day. **Every heading names the plan it is compared with, record
  included** — *Scope change — versus the plan at start, recorded 9 Sep*, *versus
  Kickoff review (1 Nov)*, *Progress — as of Review 2 (1 Dec)* — worded once
  (`pick_words`, `scope_words`, `shift_words`) for the picker's tooltip, the window and
  the report, so which two plans are compared is never a guess; a saved snapshot's day
  is a hairline through every plot with its title. **The plots are read a page at a
  time** (`chart.py`'s `PAGES`, toggles over them): *Milestone shifts* (a row each: the
  landing then hollow, the landing now filled, an arrow between), *Progress* (the plan
  now in each stretch's shade against what landed in ink, with *ahead 5 %* / *behind
  12 %* beside today's dot; and *Scope change* — the plan then dashed **over** the plan
  now, opaque and paler — so a plan unchanged since reads as two lines in one place —
  and **the area between them filled by direction**: the attention amber where the plan
  now promises more by a date than it did, the bad red where it promises less, the good
  green as a line where the two agree) and *Volume* (`progress.volume` and `remaining`:
  the total of estimated days the plan came to on each recorded day as a step curve,
  and the same less what had landed, on one scale in days — `volume_scale`, shared
  with the report); *⤢* opens `ChartDialog` with every page at once, the same widget fed
  the same record, so both redraw together. Every page shares one locked time axis —
  the date marks (days, Mondays or month firsts, `axis_ticks`) as hairlines through
  every plot, the labels printed once under the last, the edges the earliest and
  latest date any plot has to show. A span a milestone's own start date leaves empty is
  flat and dotted (`progress.idle`, the same one `progress show` prints). **Both
  surfaces draw the same plots** — `time_estimates/chart.py` in the window, `cli/report/`'s
  `Chart` of `Plot`s and `Stretch`es on the page and the PDF — so what they share is
  `domain/schedule.py`: `share_at` reads a line at a date and `change_runs` cuts two
  plans into the runs the fill is coloured by, and `progress.py` words `standing_words`
  and `shift_words` once. **Every milestone's landing is marked and named on the
  progress line** — a name elided, and dropped rather than squeezed when its neighbour's
  reaches that far — **a milestone row dates both its marks and drops a hairline to the
  axis** (`row_dates`, the same fit rule, both surfaces), a page's plots grow with the
  window to a ceiling of twice their floor (bounds set from the data, never from a
  resize), and their names are set bold. **A change re-runs the page after a quiet
  spell, and the strip says *Recalculating…* until it has** — the debounce is the
  coalescing, and a worker thread is not the answer (*A view refresh is coalesced*). The
  delta in words (`delta`, `delta_words`) and `changes_since` — the steps born and the
  estimates changed after the baseline's recorded day, from the step's `created` stamp
  and the estimate aspect's own history (`estimation`'s `read_history`; every `write`
  carries the value it replaced, one row per day, format 2; `dplanner estimate show`
  reads it back) — are the terminal's and the report's prose; the charts say it with
  the plots. `ARCHITECTURE.md`'s *Progress against the plan* has the reasoning.
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
