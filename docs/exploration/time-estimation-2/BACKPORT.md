# Backporting v4 and v5 to the Qt app

This is what has to reach DPlanner once v4 and v5 are settled. Each item names:

- the prototype file that shows it working;
- the DPlanner file it lands in;
- what to watch for.

The prototype's model is a faithful port (`deno task parity` holds it to DPlanner's own
rows), so each model change below is a diff against code that already matches.

DPlanner paths are under `src/dplanner/` unless they start with a capital (the repo root).

## 1. The model: `resume`

**Where it goes.** `domain/schedule.py`: `phases` and `parallel_finish`. The prototype is
`src/model/simulate.ts` (`phases`, `holds`, `resumed`, `dated`), under `replan: "resume"`
in `src/model/options.ts`.

- [ ] **The plan holds while reality matches it.**
  - Simulate from the project's start, as today.
  - Keep those dates if, for every step:
    - it is done exactly when the plan has it landed by today, and on that very day where
      its `since` is known;
    - a step in progress or blocked did not start after its planned start day;
    - no step was planned to start before it was created.
  - By the book this always holds, and the forecast never moves (`tests/resume_test.ts`).
- [ ] **Otherwise, resume from the next working day after today.** A day's state is its end,
  and the recorder's last write of a day wins.
  - A stretch whose work is all done is dated by its steps' `since`, and holds nothing back.
    Today, finished stretches are re-dated from the start with the *current* budget, so a
    lower focus re-dates finished work (ISSUES F5, E3).
  - From the first unfinished stretch on:
    - done steps cost nothing;
    - a step **in progress keeps its worker** and goes first in `parallel_finish` (a new
      `running` set);
    - it costs its estimate less the working days since its `since`, counted from the middle
      of that day, and at least half a day;
    - everything else costs its estimate.
  - Work that ran before the focus last changed counts at the old focus (§2,
    `efficiencyWas`).
  - A resumed stretch *began* at its first fact: the earliest `since` of its done steps
    and of its steps in progress, not tomorrow (`Phase.began`). The calendar's band starts
    there.
  - `parallel_finish` also returns each step's start offset, which the *holds* check reads
    with the same "a day's end" rule as a landing.
- [ ] **The rounding fixes.**
  - Round a fractional day with a 1e-9 guard (ISSUES I1).
  - Carry part-days between stretches (Q3). A stretch that ends exactly as a day ends
    passes the rest of that day on, not the next morning.
- [ ] **The raw lens stays un-re-planned.** The staffing matrix's "project days" counts work,
  not dates.
- [ ] **Don't port the lag, or the projection "at today's pace".** Re-planned, the lag is
  always zero and the plan's own date carries the move (ISSUES F1, F5).

Accuracy to hold the port to: `deno task accuracy` (ISSUES F5 has the table). By the book
must read exactly the real landing on every day.

### The pace so far (v5, a toggle)

- [ ] **Measure it.** Over people's done steps with a known `started` and `since`: the
  days each was given (its estimate over the focus) against the working days it took, from
  the middle of the day it started to the middle of the day it was done. Divide the sums.
  - People only: the focus scales only people's steps, and agent steps are short enough
    that a day's rounding swamps them.
  - No floor on a step's time. A half-day floor read unbiased plans as 0.84–0.90 slow
    (ISSUES F6).
  - Null before five working days of work and three finished steps.
  - Prototype: `paceSoFar` in `src/model/simulate.ts`.
- [ ] **Apply it only under `resume`, once the plan no longer holds.** People's steps not
  yet done cost their days over the pace; a running step, its days over the pace less the
  days it has run. Agents' steps and delays are unchanged. A pace within a tenth of 1
  (`asPlanned`) changes nothing.
- [ ] **Off by default.** It helps where estimates are systematically short and costs a
  little where they are not, so the reader chooses (ISSUES F6 has the table).

## 2. Data (FORMAT.md)

- [ ] **`step_status.json` gains `since`**, the day the status last changed.
  - Today it is `{"status": …}` with no timestamp (`modules/step_status/aspect.py`).
  - Stamp `since` in the aspect's write whenever the value changes, so `status set`, the GUI
    and `record_started()` all get it for free. Undo restores it with the before-image.
  - It needs a format bump.
  - Prototype: `Step.since`; the world stamps it in `src/sim/world.ts` `update`, and replays
    derive it in `src/sim/replay.ts` `dated`.
- [ ] **…and `started`**, the day it first went in progress, for the pace so far (v5).
  - Stamp it in the same write, only when the status becomes in progress and `started` is
    unset. A step reopened keeps its first start.
  - A replay derives it only from a pending → in-progress change it saw. A step already
    under way at the first commit has no start, and counts toward no pace.
- [ ] **Progress rows gain `changed`**: per stretch, how many steps' `since` is the row's day.
  - `tally()` counts only done steps today (`modules/time_estimates/progress.py`).
  - With `changed`, a row is written on every day a status changed.
  - Write it only when non-zero, as the prototype's `rowJson` does, so old readers see
    nothing new.
- [ ] **Say who records.** The recorder runs in the GUI and in `progress record`, never in
  `status set`. Decide whether status verbs from the CLI (agents) should record too.
  Otherwise a day of CLI-only work has no row.
- [ ] **`time_estimates.json` gains `efficiency_was: {"until": day, "efficiency": f}`.**
  - It is the focus before the last change, and the day the new one began.
  - Every other past budget is unneeded: forecasts look forward, and each past day's
    forecast is frozen in its row.
  - Prototype: `Assumptions.efficiencyWas`, set in `src/sim/world.ts` and
    `src/sim/edits.ts`, and read in `resumed`'s `worked`. It is tested in
    `tests/edits_test.ts`.

## 3. The Delay step

A step that is a wait, not work.

- **"Until" a day:** what requires it may start on that day, or the next working day if that
  one is off.
- **"For n working days":** counted from when everything it requires is done, or from when
  it was made, if later.

It answers "what does the plan look like if I start testing Wednesday?" (ISSUES, last
section).

- [ ] **Storage.** Either a node kind, or a step whose only entry is `delay: {"until": …}` /
  `{"days": n}`; pick the house pattern.
  - It has no estimate (treat it as opted out, so it is never "unsized"), no status, and no
    agent flag.
  - Prototype: `Step.delay`, `isDelay`, in `src/model/graph.ts`.
- [ ] **Scheduling** (`parallel_finish`, `phases`).
  - A ready delay takes no worker.
  - A `days` delay adds *n* to what waits on it, including its predecessors' tails.
  - An `until` delay ends at the first moment of its day, reckoned from the stretch's start
    and lead, and at once if that day has passed.
  - Under `resume`:
    - a `days` delay is credited with the days it has waited;
    - the *holds* check skips delays, but a `days` delay made after its wait would have
      begun does not hold.
  - Prototype: `parallelFinish`'s `waits`, `dated`, and `resumed`'s `waited`.
  - Tests: `tests/delay_test.ts`, including the Wednesday example, exact to the day.
- [ ] **Tallies.** A delay is in no tally (steps, done, days), no landing knot, and no
  unsized count. It never moves "% done" (`tally`, `landings`).
- [ ] **Verbs.**
  - A Step-menu action and a canvas gesture: insert a delay before the selected step.
  - A CLI verb: `dplanner step delay <step> --until DATE | --days N`, or similar.
  - The prototype's insertion takes over the held step's `requires`, and the step then
    requires the delay (`src/sim/edits.ts` `insertDelay`).
- [ ] **Consider:** a milestone's own start date (`time_estimates.start` on a milestone step)
  is a special case of an `until` delay before the whole stretch. It may migrate.

## 4. The Budget

- [ ] **The Time tab's team matrix and focus spinbox become a toolbar popover.**
  - People [1][2][3] and Agents [1][2][3][4] as segmented buttons; Agents only when the plan
    has agent steps.
  - Focus as a preset list, 10–100% in steps of 5.
  - It writes `time_estimates.json` as today, at once: no Save, no confirmation.
  - Prototype: `src/ui/v4/budget.ts`, with v3's popover (open across re-renders, closed
    by any click outside).
- [ ] **Forward only follows from `resume`**; nothing else is needed but `efficiency_was` (§2).

## 5. The view (v4)

The layout is `src/ui/v4/view.ts` over v3's parts (`src/ui/v3/`).

- [ ] **Key figures only.** The landing date (✓ once done), the move against the plan
  compared with, % done, and unsized steps. The words live in tooltips.
- [ ] **The toolbar**, in the order it is used: Milestones | Work tabs, *Compared with*,
  *Showing* (Work), then on the right Budget, *Save snapshot…* and ⋯ (colours).
- [ ] **Milestones:** v1's shift view (then ring → now dot, with an arrow). A done milestone
  ends in a ✓ circle on its `since` day, and a tooltip names the delays its stretch waits on.
- [ ] **Work:** two plots on one locked date axis and one scale in days.
  - **Scope:** a step line against the baseline, shaded warm or cool between them, and one
    ▲ or ▼ under the line per day the scope changed, by the day's sum.
  - **Work done:**
    - the done area and line, dotted across days no status changed;
    - the plan's schedule, dashed, from today on;
    - each milestone marked: ✓ on the done line, or a dot on the schedule.
  - **Both plots:**
    - weekend bands;
    - a hatched, named band over each delay's wait.
  - Prototype: `src/ui/v3/work.ts` with `WorkMarks`.
- [ ] **Where a day sits:** a day's point on the axis is its *end*, so day *d* spans from the
  point before to its own. Weekends, idle segments and delay bands all follow this.
- [ ] **The Work plot's scale** steps 1, 1.5, 2, 3, 4, 5, 7.5, 10 times a power of ten, with
  5% headroom. With 1-2-5 alone, 10.2 weeks drew in a 20-week plot, half of each plot
  empty (`niceCeiling`'s `steps`).

## 5b. The view (v5)

The layout is `src/ui/v5/view.ts` over v4's.

- [ ] **Calendar**, a third tab (`src/ui/v1/calendar.ts` with `MonthsOptions`).
  - Six months in two rows of three, cells tall enough to name what lands.
  - A milestone's name on the day it lands, white on its colour in either theme, as the
    ✓ is.
  - A Delay's wait hatched.
- [ ] **History**, a toolbar popover (`src/ui/v5/history.ts`).
  - A slider over the recorded days and today, ◂ ▸ steps, and *back to today*.
  - On a day before today the view reads that day's record, and only what had been
    recorded by then: `present()`'s `now` pick is `{kind: "day"}`, and every derivation
    reads `view.now`. `tests/v5_test.ts` proves it equals what the tab showed that day.
  - Unsized steps and Delay steps are left out: no record holds them.
  - The view follows the slider as it moves. The prototype redraws everything but the
    slider's own ancestors (`redrawAround` in `src/main.ts`): a range input taken out of the
    document mid-drag loses the drag. In Qt, a slider's `valueChanged` does the same with
    the tab's `Debounced` at 0 ms.
  - Everything that writes is greyed while looking back, each saying why: the Budget,
    *Adjust for efficiency*, *Save snapshot…* and ⋯ (colours).
- [ ] **No *Showing*.** v5's Work tab always shows all the work; a click on a milestone only
  picks it, and a double-click does not drill in.
- [ ] **Adjust for efficiency**, a toolbar toggle (`src/ui/v5/efficiency.ts`).
  - The label carries the focus measured, the planned focus times the pace ("Adjust for
    efficiency · 38%"), to read beside the Budget's 50%. The tooltip says it in estimates
    ("taking 1.3× their estimates").
  - Greyed, and never shown pressed, before there is a pace and while History looks back.
  - Kept on across days; it waits out a day too early rather than switching itself off.

## 6. Not ported

- The lag, the projection "at today's pace", verdict chips and the v2 change list.
- The staffing matrix as a grid; the Budget replaces it.
- The debugger (Track record, Records, scenarios, *Plan edits*, the axis lock). These are
  the prototype's tools. Track record is worth proposing separately (ISSUES U2).
