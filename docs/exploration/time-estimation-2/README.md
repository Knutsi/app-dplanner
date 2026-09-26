# Time estimation, exploration 2

This directory rebuilds DPlanner's **Time Estimates** tab as a small HTML and TypeScript
page, and drives it with a simulated clock. You can play a plan through weeks of work, or
replay a real plan's git history, and watch the view move day by day. It exists to answer
two questions:

- **Is the model any good?** Do its forecasts hold as work actually happens?
- **Do the view and the reporting say what they mean?**

What it found is in [`ISSUES.md`](ISSUES.md). How comparisons over time work, in plain
words, is in [`explainer.html`](explainer.html). What each version taught is in
[`LESSONS.md`](LESSONS.md), and what must reach the Qt app is in
[`BACKPORT.md`](BACKPORT.md).

![v5's Work tab, day by day through the Scope creep scenario: the scope climbs above the
plan at start, work is done in steps with its quiet days dotted, and each milestone turns
to a ✓ as it lands](work.gif)

*v5's Work tab played through **Scope creep** (seed 1), axes locked to the whole run.*

## Open it

The page needs no build and no server to *look at*: open `index.html` in a browser. It
loads the committed `app.js`, and `local/plans.js` too if you have exported real plans.

Some browser tools refuse `file://` pages. For those, serve the directory:

```
python3 -m http.server 8765 --bind 127.0.0.1 -d docs/exploration/time-estimation-2
```

**The page is two parts.** The dark **debugger** on top is everything that exists only in
the prototype. The light **view** under it is the Time tab as DPlanner would show it on the
day the debugger is set to.

**The debugger's bar** stays pinned to the top of the window. It holds:

- *▾ Debugger*, which folds the rest away (or press `d`);
- play and step (← →);
- the day;
- the scrubber. The ticks under it are recorded days, saved snapshots (tall) and when each
  milestone *really* landed (coloured).

**The debugger's body** has three sections, each folding on its own, and the folds are
remembered in the browser:

- **Plan, scenario and model.**
  - *Plan:* the synthetic sample (pick a seed), or a replay of an exported real plan. You
    can also drop an export `.json` anywhere on the page.
  - *Scenario:* each one breaks *one* assumption the model makes, and says where to look.
    "By the book" breaks none; it is the control. *Adjust the world* exposes every
    parameter.
  - *Recorder runs:* which days DPlanner's recorder wrote a row. When replaying it also
    offers *as DPlanner recorded it*.
  - *Plan edits:* what DPlanner's canvas would do and this page has no canvas for. You can
    add a **Delay step** before any step that has not started, on the day shown: *until* a
    day, or *for* a number of working days. It goes in the address bar, and ✕ removes it.
    In a scenario the simulated team waits for it too.
  - *Model:* the page always runs **`resume`** (ISSUES.md F1, F5). The plan's own dates
    stand while what is done matches them. Otherwise the rest resumes from tomorrow, with
    work in flight credited for the days already spent. The rounding is fixed (I1, Q3).
    That is decided for the backport, so it has no switch. The parity tools alone run
    DPlanner exactly as it is today. v5's *Adjust for efficiency* is the reader's own
    switch, in the view (F6).
  - *Lock the Work plot's axes to the whole run* (v5): the date axis ends at the last
    landing and the scale holds the most work the run ever has, so scrubbing moves only
    the lines. It is how `work.gif` was recorded.
- **Track record.** Each milestone's forecast against the day it was made, with the real
  landing on the diagonal, and the forecast error at points along the way. DPlanner as it
  is today is drawn dashed beside the page's model. DPlanner has no such view; see
  ISSUES.md U2.
- **Records.** Exactly what `progress_history.json` holds, day by day, beside what happened
  that day. On a replay, each stored row also shows whether the port reproduces it.

What happened on the day sits between the sections. Track record and Records are computed
only while unfolded.

**The view comes in five designs.** Switch between them in the debugger's bar (*v1 ·
today* / *v2* / *v3* / *v4* / *v5 · latest*). All read the same plan on the same day, and
the choice is remembered; v5 is the default.

- **v1** is a wireframe of today's tab: the strip, the staffing grid, the milestones, the
  calendar, and the plot pages.
- **v2** is the first redesign, built around what a professional reader comes to the tab to
  learn. Top to bottom, it answers:
  1. When does it land, really?
  2. Did that move, and why — did the plan change, or are we slower?
  3. Which milestone needs a look?
  4. How is the scope moving?
  5. What if the team were different?
- **v3** is v2 pared down after review: key figures, a toolbar and two tabs, with the words
  moved into tooltips.
- **v4** is v3 with the **Budget** in place of the what-ifs. Its Work tab marks weekends,
  the days nothing changed, and the waits of Delay steps.
- **v5** is v4 with the **Calendar** back as a third tab, **History** to look back at any
  recorded day, and **Adjust for efficiency** to re-estimate what is left at the focus work
  has actually had.

In v1 to v3, focus, team, palette, start and a milestone's begin date are *what-ifs* on the
day's live plan. In v4 the Budget is not a what-if: a choice is saved at once, and applies
from the day shown on. Every design reads the page's model, so v1 is today's tab *layout*
over a plan that resumes from tomorrow.

### v5, part by part

v5 is v4, with these additions:

- **Calendar**, a third tab: six months in two rows of three, each stretch a band in its
  milestone's colour, each milestone's name on the day it lands, and each Delay's wait
  hatched. ◂ ▸ page a month at a time.
- **History**, in the toolbar: a slider over every day the recorder wrote, with ◂ ▸ steps
  and *back to today* (or ✕).
  - The view follows the slider as it moves. On a day before today, the key figures, the
    plots and the calendar show the tab as it read that day, from the records alone.
  - Unsized steps and Delay steps are left out, since no record holds them.
  - Everything that writes is greyed until you are back to today: the Budget, *Adjust for
    efficiency*, *Save snapshot…* and ⋯ (colours).
- **Adjust for efficiency**, in the toolbar: re-estimates what is left at the focus
  people's finished steps actually had, each step's estimate against the working days it
  took. The label carries the focus measured ("Adjust for efficiency · 38%"), beside the
  Budget's planned 50%. The tooltip says it in estimates ("taking 1.3× their estimates").
  - It is greyed until there are five working days of work and three finished steps.
  - A focus within a tenth of the planned one leaves the dates alone.
  - It applies only once the plan no longer holds, so By the book never moves.
  - It is off by default. On Optimistic estimates it cuts the forecast's error by a
    third; on plans whose estimates are right, it costs up to half a day of error and
    moves the date more. A blocked step's stall reads as slowness (ISSUES.md F6).
- **No *Showing***: the Work tab always shows all the work. A click on a milestone still
  picks it, fading the others in Milestones and the Calendar.
- **The debugger's bar** keeps its size whatever the day's words: they cut off with an
  ellipsis before they wrap, so the page never jumps while scrubbing.

### v4, part by part

v4 is v3's layout, part for part, with these changes:

- **Budget** replaces *What if…* in the toolbar.
  - People [1][2][3] and Agents [1][2][3][4] as buttons; Agents only when the plan has agent
    steps.
  - Focus from 10% to 100%.
  - A click applies at once, from the day shown on; earlier days keep theirs. It goes in the
    address bar (`budget=`).
  - In a scenario the simulated team changes with it, so you see what a real re-budget does.
- **Work**, both plots:
  - a pale band on each weekend;
  - a hatched, named band over each Delay's wait.
- **Work done:**
  - the done line is dotted across each day on which no step changed status;
  - the plan's schedule is dashed, so the two never mix.
- **Milestones:** a row's tooltip names the delays its stretch waits on.

The dates hold still while the plan does. By the book reads the same date every day until
it lands, and a Delay or a re-budget moves the dates only from its own day on (ISSUES.md
F5 has the numbers).

### v3, part by part

- **Key figures**, one line: the landing date (`✓` once everything is done), how many
  working days it moved against the plan compared with (▶ +13d), the share done, and a
  warning count of unsized steps.
- **The toolbar**, in the order the controls are reached for. The tabs come first, then
  *Compared with* and, on the Work tab, *Showing* (all work or one milestone; not in
  v5). On the right, folded away: *What if…* (team and focus, tinted with a one-click ✕ while set),
  *Save snapshot…*, and ⋯ for the colour map.
- **Milestones** is v1's shift view, restored. Each row shows where the plan compared with
  landed a milestone (a ring) and where the plan now lands it (a dot), with an arrow between
  them. A milestone that is done ends in a ✓ circle on the day it was recorded done. Click a
  row to pick it; double-click to open its work.
- **Work** is two plots on one locked date axis and one scale in days.
  - **Scope**: the scope's step line over the scope compared with (dashed). The area between
    them is shaded warm where work was added and cool where it was taken away. One ▲ or ▼
    sits under the line on each day the scope changed, by the day's sum.
  - **Work done**: the done area up to today, and from today on the plan's schedule. Each
    milestone is marked where it sits: a ✓ on the done line the day it was done, or a dot on
    the schedule the day the plan lands it.

  **There is no projection "at today's pace".** Re-planned from today, nothing undone is
  ever late: late work moves the plan's own dates. The Milestones arrows and the Work
  schedule show that move directly.

### v2, part by part

- **The headline.** The landing date *at today's pace*, and what the plan itself says.
  - A verdict (✓ Landed, ⚠ Overdue, ▶ Later, ◀ Earlier, ● On track) with one sentence
    that splits a move into *changes to the plan* and *today's pace*.
  - Where work stands against the plan's own schedule.
  - The one milestone that needs a look: an overdue one, or the one whose own work added
    most of the move.
  - *Compared with* offers the plan at start, **the plan a week ago**, a saved snapshot or
    any day. There is no "now" picker: now is the debugger's day.
- **Milestones** is the navigation: click a row, or use ↑/↓ while the list has focus, and
  the detail below follows. Each row has a small Gantt on one shared axis:
  - the plan compared with is a ghost outline, the plan now a bar;
  - the work done fills the bar up to the day that work was due, so the gap to the
    today line *is* the lag;
  - the lag extends the bar with ▶ arrows.
- **The detail** of the picked scope:
  - A burn-up in days of work: scope, done, the plan's own schedule, and the projection to
    the landing at today's pace. The area between the scope and the scope compared with
    carries ▲ where work was added and ▼ where it was taken away.
  - Beside it, what changed: steps added and re-estimated, by name; steps removed or
    moved, by count; and a note when dates moved without any change in scope.
- **What if…** and **Calendar** are folded at the bottom.

**The arrow grammar.** Vertical arrows (▲▼) only ever mean scope; horizontal ones (◀▶) only
ever mean time. Colour is never the only channel: every verdict has a glyph and a word, and
every scope area has arrows.

**Two numbers v2 derives** (`src/brief.ts`, pure and tested) come from nothing DPlanner does
not already store. Both were built over DPlanner as it is today. Re-planned from today,
the lag is always zero and the projected landing *is* the plan's date, so v2 now reads
them as nothing to report; its tests pin them on the faithful model.

- **Lag** is how many working days the earliest undone work is overdue. It uses the plan's
  landing knots as steps, never a line drawn between them, so a step in flight on schedule
  is never "behind". It counts to today, or to Monday on a weekend, so work still undone
  never lands in the past.
- **The projected landing** is the plan's landing moved on by the lag.

Dates, lag and verdicts count everything up to a milestone, since milestones run in
sequence. The burn-up and the change list show the milestone's own work.

**v1's Scope change plot is not about scope.** It compares two *schedules*: the share of
work each plan promised landed by each date. More scope makes its line go down, and a new
team paints it amber. v2's ▲▼ areas are scope, in days.

The address bar keeps the plan, scenario, day, variants and design, so a link opens the
page where you left it:

- `day=end` goes to the last day;
- `tab=track` or `tab=records` unfolds that section;
- `ui=v1` to `ui=v5` picks the design, and `scope=<step id>` the milestone it shows;
- `page=milestones` or `page=work` picks the tab in v3 to v5, and `page=calendar` in v5;
- `asof=2026-11-02` is the recorded day v5's History shows;
- `adjust=on` adjusts v5's dates for the efficiency so far;
- `axes=run` locks the Work plot's axes to the whole run;
- `budget=2026-11-02:2+1@60` holds re-budgets: the day, people + agents, and focus;
- `delay=2026-10-12:s14:until:2026-11-04` (or `…:days:3`) holds Delay steps: the day made,
  the step held, and the wait.

## Build, check, test

Everything uses [Deno](https://deno.com) 2.x. There are no packages, no lockfile and no
`node_modules`.

```
deno task check     # strict type-check of src/, tools/ and tests/
deno task test      # the ported DPlanner tests, the simulation, the issues
deno task build     # bundle src/main.ts into app.js (commit it: the page loads it)
deno task dev       # the same, rebuilding on every save
deno task accuracy  # each model's forecasts against the truth, scenario by scenario
```

`app.js` is generated. Rebuild it after editing `src/`, and commit it with the change, so
the page opens for someone without Deno.

## Real plans

```
deno task export <plan-repo> <project-dir> [--worktree]
deno task export ~/Code/app-dplanner-planning dplanner --worktree
```

**What the exporter reads.**

- It reads every commit that touched the project directory, using git's plumbing only
  (`log`, `ls-tree`, one `cat-file --batch`). It never checks anything out and never runs
  `dplanner`: every verb migrates and flushes the files it opens.
- `--worktree` adds the uncommitted files as a last frame.

**What it writes.**

- `local/<slug>.json`.
- A rewritten `local/plans.js`, which the page picks up.

`local/` is gitignored. A plan may belong to a client, and this repository is public.

**Two checks hold the port to DPlanner on real data:**

```
deno task parity local/dplanner.json
# the port's snapshot against every row DPlanner stored on the same day

dplanner schedule matrix <project> --json --library <a COPY of the library> > matrix.json
deno task compare-matrix local/<slug>.json matrix.json
# the port's staffing matrix against the real one, field by field
```

On 2026-09-26 both agreed exactly:

- 8 of 8 recorded days, across four plans;
- the full matrix for two plans.

## Where things are

```
index.html, app.css     the page, and its wireframe styling (DESIGN.md's tokens)
work.gif                v5's Work tab played through Scope creep, for this README
explainer.html          how comparisons over time work; its figures are drawn by app.js
ISSUES.md               the issues, each with its evidence and a direction
LESSONS.md              what each version taught, v1 to v5
BACKPORT.md             the checklist for the Qt app
src/model/              the faithful port — no DOM, and `today` is always passed in
  calendar.ts             days as integers, working days, how dates and days are worded
  graph.ts                Plan and Step (with `since`, `started` and Delay steps), the
                          predicates DPlanner wires, placed/cone/cyclic
  simulate.ts             parallel_finish, phases (and `resume`: holds, resumed; the pace
                          so far), stretched, the 3×4 matrix
  progress.ts             snapshots, curves, baseline/resolve, recording, volume, words
  palettes.ts             the colour maps and the milestone deal
  options.ts              the model: FAITHFUL (DPlanner today), ADOPTED (the page's:
                          `resume` and the rounding fixes), and the variants still on trial
src/sim/                time travel
  world.ts                reality: a team working the plan with true effort, and events
  scenarios.ts            the presets, each breaking one assumption
  timeline.ts             frames, and the recorder that writes rows over them
  replay.ts               an exported git history as frames; parity with stored rows
  edits.ts                what the page changes in the plan from a day on: re-budgets and
                          Delay steps, for the world, a replay and the address bar
  accuracy.ts             a model's forecasts against the truth: error, movement, moves
  sample.ts, rng.ts       the synthetic plan, and seeded luck
src/present.ts          what the Time tab shows, as data (every design starts here)
src/brief.ts            what v2 to v5 derive: lag, projected landing, the move split,
                        verdicts, the burn-up series and its active days
src/ui/v1/              today's tab: timetab.ts, calendar.ts, charts.ts
src/ui/v2/              the first redesign: view.ts, headline, milestones, burnup, changes,
                        words (how it says things), state
src/ui/v3/              the second: view.ts (key figures and the tabs), toolbar, shifts
                        (Milestones), work (Work, and v4's marks), marks (the ✓), state
src/ui/v4/              the third: view.ts (v3's layout, v4's toolbar), budget (the Budget)
src/ui/v5/              the fourth: view.ts (v4 and the Calendar tab), history (History),
                        efficiency (Adjust for efficiency)
src/ui/compare.ts       the Compared with picker v2 to v5 share
src/ui/glyphs.ts        the ▲▼◀▶ arrows v2 to v5 share
src/ui/debugger/        the debugger's readings: track.ts, records.ts
src/ui/markup.ts        building HTML and SVG; figures.ts draws the explainer's figures
src/data.ts             the export format
tools/                  export_plan.ts, parity.ts, compare_matrix.ts, accuracy.ts
tests/                  model_test (DPlanner's own cases), sim_test, issues_test,
                        brief_test and glyphs_test (v2), v3_test, resume_test (the model),
                        edits_test (the Budget), delay_test, v4_test, v5_test (History,
                        the locked axes), pace_test; played.ts plays a scenario for them
```

**How an export maps to DPlanner's files.** `tools/export_plan.ts`'s header has the full
table. In short:

| DPlanner file | What it gives |
|---|---|
| `project.dproj` | Step order and title |
| `modules/estimation.json` | The start |
| `modules/time_estimates.json` | Focus, palette, team |
| `modules/progress_history.json` | Kept whole |

Each step contributes:

| Step file | What it gives |
|---|---|
| `step.json` | Id, number, title, `requires`, `created` |
| `estimation.json` | Days, opted out, history |
| `step_status.json` | Status |
| `step_milestone.json` | The milestone label |
| `step_agent_instruction.json` / `.md` | Agent work |
| `time_estimates.json` | A milestone's own start and colour |

## Evolving it

- **A model change** is an option in `src/model/options.ts`, threaded where it bites
  (`phases` holds all three today). As a variant it appears in the page and in Track
  record's comparison by itself.
  - **Decide on it with `deno task accuracy`**, not its intent. Add the mode to the tool's
    list, and adopt it only if By the book stays at 0.0 · 0 · 0 and the other scenarios do
    not move more (LESSONS.md, *The model*).
  - Once decided, move it into `ADOPTED` and out of `VARIANTS`, as the rounding fixes and
    `resume` were.
  - A change that helps some scenarios and costs others is not adopted. At most it is the
    reader's choice, as *Adjust for efficiency* is (ISSUES.md F6).
  - If it fixes an issue, flip that issue's test in `tests/issues_test.ts`, say so in
    ISSUES.md, and add it to BACKPORT.md.
- **A new scenario** is an entry in `src/sim/scenarios.ts`: the world parameters, the one
  assumption it breaks, and where to look. Check the "look" sentence against the numbers
  before trusting it; several first guesses were wrong.
- **A view change** starts in `src/present.ts`, the data, then `src/ui/`. The plots are a
  port of `cli/report/drawings.py`, so a change that belongs upstream can be carried back.
