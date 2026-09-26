# Lessons learned, v1 to v4

Four passes at the Time tab, each reviewed and reworked. What each one taught, for the
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
- **Order the toolbar by use.** The frequent controls go on the left. The rare ones fold to
  the right: the budget, save, and colours.
- **Give each line style one meaning.** Once idle days were dotted, the dotted schedule
  could be misread as idle work, so it became dashed.

## Interaction

- **A redraw on the first click swallows `dblclick`.** Read the click event's `detail`
  count instead.
- **A popover must survive the re-render its own controls cause,** and close on any click
  outside it.
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
  and v3's pessimism happened to be closer. A pace factor learned from done work is the
  next experiment (ISSUES F5).

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
