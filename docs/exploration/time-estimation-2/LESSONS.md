# Lessons learned, v1 to v5

Five passes at the Time tab, each reviewed and reworked. What each one taught, for the
backport (BACKPORT.md) and for the next exploration.

## The view

- **v1, today's tab.**
  - The landing date sat in a table's first row.
  - The staffing grid held the prime spot.
  - The plots were separate places to cross-reference.
- **v2 led with the answer, but said too much.**
  - It had cards, sentences, verdict pills and explainers.
  - It laid a texture of arrows over every changed area, and the arrows ended up "placed
    all over the place".
  - A professional reader wants the numbers and a picture they already know. The words
    belong in tooltips.
- **v3: key figures only, and two tabs instead of cards.**
  - The familiar shift view beat a new timeline.
  - Two plots on one locked date axis and one scale beat an overlaid burn-up.
  - One arrow per day the scope changed, right under the line, reads. A texture does not.
  - Shading between the scope and the baseline still helps, as a plain fill.
  - Milestones read best as marks on the work line: a ✓ where done.
- **v4: explain the line with marks, not words.**
  - Weekends are banded.
  - Days on which nothing changed are dotted.
  - A wait is a named, hatched band.
  - The budget sits beside the dates it moves, not in a grid.
- **v5: the past is a place to go, and the calendar a page to read.**
  - History needed nothing new. Every derivation already read "the plan shown", so a
    recorded day is just another pick, and the writers grey out.
  - Six months in two rows beat a single row of six: tall cells can carry a milestone's
    name on the day it lands.
- **A scale must fit what it holds.** 1-2-5 steps drew 10.2 weeks in a 20-week plot, half
  of it empty. Finer steps with a little headroom fixed that. For a recording, the axes are
  locked to the whole run, so only the lines move.
- **Text whose length changes must not decide a layout.** The debugger's day line wrapped
  on long dates, and the whole page jumped while scrubbing. It now has a fixed basis and
  an ellipsis.
- **Order the toolbar by use.** The frequent controls go on the left. The rare ones fold to
  the right: the budget, save, and colours.
- **Give each line style one meaning.** Once idle days were dotted, the dotted schedule
  could be misread as idle work, so it became dashed.

## Interaction

- **A redraw on the first click swallows `dblclick`.** Read the click event's `detail`
  count instead.
- **A popover must survive the re-render its own controls cause,** and close on any click
  outside it. A slider inside one must too: the view follows it on `input` redrawn *around*
  it, since a range input taken out of the document mid-drag drops the drag; on `change`
  the whole view is redrawn and the slider takes its focus back.
- **Name a control for what the reader wants, and label it with their number.** "Pace so
  far · 77%" became "Adjust for efficiency · 38%": the focus measured reads beside the
  Budget's planned 50%, where a pace was a ratio of ratios.
- **A greyed toggle is never shown pressed.** *Adjust for efficiency* stays on across
  days, but it looks pressed only while the dates actually run at it.
- **A `+` typed into the address bar arrives as a space.** Links the page writes encode it;
  links people type do not.
- **Hidden windows starve `requestAnimationFrame`, and background tabs throttle timers to
  about a second.**
  - Draw after mount with `queueMicrotask`.
  - Time a render directly: 5 ms. A timer-paced loop showed 954 ms.

## The model

- **A projection layered on a plan that never learns is a workaround.** v2's lag and
  "at today's pace" made the missing date visible; re-planning made it true, and the lag
  went to zero.
- **Adopt a change on its numbers, not its intent.**
  - v3 made `restart` the default while ISSUES already said it saw-toothed.
  - The first thing a reader saw was *+5d* by the book.
  - `deno task accuracy` now puts every mode side by side, and v4 was adopted on it.
- **A day's state is its end.** The re-plan starts on the next working day. Starting at the
  beginning of today read a day early when a step landed, and a day late over a weekend.
- **What is done is a fact.** Finished stretches were re-simulated from the start with
  today's budget, so a lower focus pushed the future behind work finished weeks before.
- **A forecast should stand still while things go to plan.** "The plan holds" made By the
  book exact on every day. Movement is information only when it is rare.
- **Every "holds" rule had a loophole, and a series found it, not a single day.**
  - Done late still looks consistent once *everything* is done: Optimistic read ± 0d at its
    end. The fix: done on the planned day.
  - A step or delay added later was planned into the past. The fix: nothing starts before
    it existed.
- **Past budgets are unnecessary, with one exception.** Work in flight across a change of
  focus ran at the old one. Credited at the new one, a cut to 10% read February for a
  December landing.
- **`resume` trusts the estimates of unfinished work.** Where every estimate is low it lags,
  and v3's pessimism happened to be closer. v5's *Adjust for efficiency* learns from done
  work (ISSUES F6).
- **A ratio against the plan's schedule is too jumpy to steer by.** The first pace
  estimator compared work done with work planned done. It needed no new data, and every
  long step landing late flipped it: ten times the movement, for almost no gain.
- **A bias that helps is still a bias.** A half-day floor on each step's time read every
  plan as slow. That flattered the slow scenarios and moved the dates of plans that were
  fine. Measure the estimator on an unbiased run first: it must read 1.
- **A fix that helps some plans and costs others is the reader's choice.** The pace cuts
  Optimistic's error by a third and costs up to half a day elsewhere, so it is a toggle,
  off by default. The label carries the number, so the reader judges the pace before the
  dates.

## Data

- **One missing fact carried three features.**
  - DPlanner stores no status timestamp.
  - `since`, the day the status last changed, credits work in flight, dates a done
    milestone exactly, and finds the days nothing changed.
- **Records count only `done`, and only the GUI and `progress record` write them.**
  - Starting a step is invisible.
  - A day of agent work driven from the CLI can leave no row at all.
- **A wait is not work.** "Testing starts Wednesday" needed its own step type. A milestone's
  start date could not hold one branch, and an estimate would have counted it as work.
- **`since` is not enough for a pace.** A done step's `since` is the day it was done, and
  the day it began is gone. `started` is the second stamp, written once.

## Process

- **Simulate before claiming.**
  - The saw-tooth's causes came from scrubbing the page a day at a time and reading the DOM.
  - The claims about the budget came from running it at 10% focus.
- **Hold the model to a movement number.** By the book must read 0.0 · 0 · 0 on every seed,
  and it is a test (`tests/resume_test.ts`).
- **Test through the path the page uses.**
  - A test on `snapshotOf` passed while `present()` dropped the new `efficiencyWas`.
  - The test now reads the view too.
- **Parity compares only what DPlanner stores.** A new field the port records, `changed`,
  briefly broke parity until the comparison went field by field.
- **Write the lesson where the next change will meet it.** v2's "what the model variants
  taught" was right about `restart`, and was read too late. BACKPORT.md is the list the Qt
  work starts from.
