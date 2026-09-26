# Time estimation, exploration 2

This directory rebuilds DPlanner's **Time Estimates** tab as a small HTML and TypeScript
page, and drives it with a simulated clock. You can play a plan through weeks of work, or
replay a real plan's git history, and watch the view move day by day. It exists to answer
two questions:

- **Is the model any good?** Do its forecasts hold as work actually happens?
- **Do the view and the reporting say what they mean?**

What it found is in [`ISSUES.md`](ISSUES.md). How comparisons over time work, in plain
words, is in [`explainer.html`](explainer.html).

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
  - *Model variants:* proposed fixes, off by default. With all of them off, the page
    computes exactly what DPlanner computes today.
- **Track record.** Each milestone's forecast against the day it was made, with the real
  landing on the diagonal, and the forecast error at points along the way. DPlanner has no
  such view; see ISSUES.md U2.
- **Records.** Exactly what `progress_history.json` holds, day by day, beside what happened
  that day. On a replay, each stored row also shows whether the port reproduces it.

What happened on the day sits between the sections. Track record and Records are computed
only while unfolded.

**The view** is a wireframe of today's tab: the strip, the staffing grid, the milestones,
the calendar, and the plot pages.

- Focus, team, palette, start and a milestone's begin date are *what-ifs* on the day's
  live plan.
- The recorded past stays as it was recorded.

The address bar keeps the plan, scenario, day and variants, so a link opens the page where
you left it:

- `day=end` goes to the last day;
- `tab=track` or `tab=records` unfolds that section.

## Build, check, test

Everything uses [Deno](https://deno.com) 2.x. There are no packages, no lockfile and no
`node_modules`.

```
deno task check     # strict type-check of src/, tools/ and tests/
deno task test      # the ported DPlanner tests, the simulation, the issues
deno task build     # bundle src/main.ts into app.js (commit it: the page loads it)
deno task dev       # the same, rebuilding on every save
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
explainer.html          how comparisons over time work; its figures are drawn by app.js
ISSUES.md               the issues, each with its evidence and a direction
src/model/              the faithful port — no DOM, and `today` is always passed in
  calendar.ts             days as integers, working days, how dates and days are worded
  graph.ts                Plan and Step, the predicates DPlanner wires, placed/cone/cyclic
  simulate.ts             parallel_finish, phases, stretched, the 3×4 matrix
  progress.ts             snapshots, curves, baseline/resolve, recording, volume, words
  palettes.ts             the colour maps and the milestone deal
  options.ts              the model variants (every flag off = DPlanner today)
src/sim/                time travel
  world.ts                reality: a team working the plan with true effort, and events
  scenarios.ts            the presets, each breaking one assumption
  timeline.ts             frames, and the recorder that writes rows over them
  replay.ts               an exported git history as frames; parity with stored rows
  sample.ts, rng.ts       the synthetic plan, and seeded luck
src/present.ts          what the Time tab shows, as data
src/ui/                 the page's parts: the tab, calendar, plots, track record, records
src/data.ts             the export format
tools/                  export_plan.ts, parity.ts, compare_matrix.ts
tests/                  model_test (DPlanner's own cases), sim_test, issues_test
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

- **A model change** is a flag in `src/model/options.ts`, threaded where it bites
  (`phases` holds all three variants today). It then appears in the page and in Track
  record's comparison by itself. If it fixes an issue, flip that issue's test in
  `tests/issues_test.ts` and say so in ISSUES.md.
- **A new scenario** is an entry in `src/sim/scenarios.ts`: the world parameters, the one
  assumption it breaks, and where to look. Check the "look" sentence against the numbers
  before trusting it; several first guesses were wrong.
- **A view change** starts in `src/present.ts`, the data, then `src/ui/`. The plots are a
  port of `cli/report/drawings.py`, so a change that belongs upstream can be carried back.
