# Issues found in the time model and its reporting

This is what the prototype turned up while rebuilding the Time tab and running plans
through time. Before relying on any of it, the port itself was checked against DPlanner:

- **Recorded rows.** On every day a real plan has a stored `progress_history` row, the port's
  snapshot equals it, landing knots included. That is 8 of 8 days across four real plans
  (`deno task parity`).
- **The staffing matrix.** The port's matrix equals `dplanner schedule matrix --json` on
  two real plans: all 24 cells, the milestones and their colours, the floors and the effort
  (`deno task compare-matrix`).

So what follows is DPlanner's behaviour, not the port's.

**Evidence.** Each issue says how it was established:

| Tag | Meaning |
|---|---|
| **Python** | Run against DPlanner's own code; the output is quoted. |
| **CLI** | Seen in real `dplanner` output, on a copy of a real plan. |
| **Real plan** | Seen replaying a real plan's git history in the prototype. |
| **Scenario** | Seen in the simulation. The link opens the page at that scenario and day. |
| **Code** | Read in the source, not exercised. |

`tests/issues_test.ts` pins each behaviour under the issue's id, so a fix flips a named test.

| Id | Issue | Weight | Evidence |
|---|---|---|---|
| [F1](#f1) | The landing dates never learn from what has landed | high | Python, real plan, scenario |
| [P1](#p1) | "Behind" while exactly on time | high | Python, scenario |
| [U1](#u1) | A landing date in the past is shown like any other | high | scenario, real plan |
| [F2](#f2) | An undated plan slides every day and is compared with itself | medium | Python, scenario |
| [P2](#p2) | Shares are of each day's own total | medium | scenario |
| [R2](#r2) | Scope change counts a staffing change as scope | medium | scenario |
| [I2](#i2) | "Unestimated" counts opted-out milestones | medium | CLI, real plan |
| [F3](#f3) | An unsized step costs nothing | medium | scenario |
| [F4](#f4) | In progress and blocked are read as not done | medium | scenario |
| [S1](#s1) | Agents cost no one's time | medium | scenario |
| [R1](#r1) | Days with no record are drawn as straight lines | medium | scenario |
| [Q3](#q3) | Each stretch rounds up before the next begins | low–medium | scenario, sim test |
| [I1](#i1) | Float noise and a bare `ceil` add a working day | low–medium | Python |
| [Q2](#q2) | Work no milestone gathers runs last | low–medium | Python |
| [R3](#r3) | "Plan at start" is the start day's *last* state | low | explainer example |
| [R4](#r4) | The change list misses most changes, and unsizing forgets history | low | Python, code |
| [Q1](#q1) | Milestones strictly in sequence | low | scenario |
| [I3](#i3) | A zero-day step waits for a free worker | low | port |

Two findings about the *fixes* matter as much as the issues. See
[What the model variants taught](#what-the-model-variants-taught).

---

## The forecast

<a id="f1"></a>
### F1. The landing dates never learn from what has landed

**What.** Every day, the forecast re-simulates the *whole* plan from its start date. Done
steps are included and priced at their estimates.

- Status feeds the tallies, the "Landed" percentage and the actual line, and nothing else.
- A plan running late shows it only as a gap on the Progress plot.
- The landing dates, the calendar and Milestone shifts do not move unless an estimate, a
  link, the team or a start date changes.
- The model also has no record of *when* a step finished: status carries no timestamp, and a
  record keeps counts, not steps.

**Where.** `progress.py:268` `take` → `domain/schedule.py:365` `phases`: every stretch
simulated from `start`. `progress.py:351` `tally` is the only reader of status.

**Evidence.**

- **Python.** "lands 2026-09-14 with nothing done and with everything done, read on 30 Sep".
- **Scenario** [Optimistic estimates](index.html#source=sample&seed=1&scenario=optimistic&tab=track&day=end):
  human work really takes 1.5×.
  - Every forecast line in Track record is flat for the whole project.
  - M3 lands 20 working days after its forecast, and the forecast a week before it landed
    was still 20 days out.
  - On 20 November the Time tab reads *behind 31%*, while its milestone table says M2
    "lands 12 November". That is eight days in the past, with M2 at 71%.
- **Real plan.** On 26 September, DPlanner's own plan says #1 "lands 24 September". That is
  two days in the past, with #1 at 91%.

**Why it matters.** The number people read, the landing date, is the one number that
cannot go late.

**Direction.**

- Re-plan the remaining work from today: done steps cost nothing, and the first unfinished
  stretch starts no earlier than today. `replan` in `options.ts` is a first cut, and it is
  enough to show the forecasts converging (Track record, same scenario, variant on).
- Doing this properly needs two facts the model lacks:
  - **when a step became done** (a status timestamp);
  - **how much of an in-progress step is left.** Without it, a re-plan saw-tooths (see
    [below](#what-the-model-variants-taught)).

<a id="f2"></a>
### F2. An undated plan slides every day and is compared with itself

**What.** A project with no stored start "starts today" (`estimation/schedule.py:54`
`start_of`) on every day it is read. So:

- every landing moves one working day later each day;
- a row is recorded every day, because the plan is always "new";
- *Plan at start* resolves to today's own record. `baseline()` stops the *fallback* from
  returning today's row, but not the main rule. With the basis equal to today, the last row
  on or before the basis *is* today's row (`progress.py:459`).

**Evidence.**

- **Python.** "start = today, so the last record on or before the start is today's own row".
- **Scenario** [Undated project](index.html#source=sample&seed=1&scenario=undated&tab=track&day=end):
  - the forecast a week before each landing was up to 39 working days out;
  - halfway through, Progress reads *ahead 41%*.

**Direction.** Store the start on the first day a step turns in-progress or done. Or
refuse to compare, with the reason, until a start exists. ARCHITECTURE.md's "never today's
own record" intent covers this case too.

<a id="f3"></a>
### F3. An unsized step costs nothing

**What.** A step without an estimate runs as zero days everywhere. The banner says so
("counted as 0d"), and nothing else does.

**Evidence.**

- **Scenario** [Unsized steps](index.html#source=sample&seed=1&scenario=unsized&tab=track&day=end):
  unsized steps really take 2 days.
  - The milestones holding them land 2–3 working days late.
  - Progress reads about on plan.
- Pinned in `F3` together with [I2](#i2).

**Direction.** Price an unsized step at a stated default: the house convention's quarter
day, or the project's median step. Put that price in the banner ("2 steps unsized · priced
at 1d").

<a id="f4"></a>
### F4. In progress and blocked are read as not done

**What.**

- The simulation never reads status, and the tally counts only `done`.
- An in-progress step counts 0%.
- A blocked step delays nothing.

**Evidence.** **Scenario** [A blocked step](index.html#source=sample&seed=1&scenario=blocked&tab=time&day=2026-10-20):
the longest-running step is blocked for six working days.

- Progress falls behind, but the landings do not move.
- Every milestone lands 4–5 working days late.

**Direction.** Once the forecast re-plans from today ([F1](#f1)), treat a blocked step as
unable to start before it is unblocked, or at least report which milestones a blocked step
holds.

---

## The progress measure

<a id="p1"></a>
### P1. "Behind" while exactly on time

**What.** *Ahead/behind* is `share_at(expected, today) − share_at(actual, today)`
(`progress.py:930`). The two lines are not made the same way:

- The **expected** line is drawn straight between the days steps land (its knots).
- A step's days count as **done** only when it lands.

So while any multi-day step is under way on schedule, the plan line has already risen and
the actual line has not. The longer the steps, the bigger the false "behind", and it snaps
back at each landing.

**Evidence.**

- **Python.** "one 5-day step, on its third day exactly as planned: standing −50%".
- **Scenario** [By the book](index.html#source=sample&seed=1&scenario=by-the-book&tab=track&day=end):
  every step takes exactly its estimate.
  - Track record's second plot shows what the Time tab said each day. It reads *behind*
    on 36 of the run's 64 days, by up to 16%.
  - It reads *ahead* on 12 days. Those are [Q3](#q3)'s rounding, where reality beats the
    forecast.
- **Explainer example.** Friday reads *behind 12%* while Polish is on schedule.

**Why it matters.** It is the one warning the tab gives that a plan is slipping, and it
fires falsely on every plan with multi-day steps.

**Direction.** Compare like with like. Either:

- read the expected line as a *step function* of landings, counting a step at its landing
  exactly as the actual line does; or
- give an in-progress step partial credit on both lines.

The step function is one change in `expected` or `share_at` and needs no new data.

<a id="p2"></a>
### P2. Shares are of each day's own total

**What.** Each actual point is `done_days / days` *of that day's plan*.

- Added scope lowers the actual line, although nothing was undone. In the explainer example
  it drops on Thursday.
- Earlier points were measured against a smaller plan than the plan now they are drawn
  beside. Under scope creep the actual line runs *above* the plan now in places.
- The plan now absorbs whatever was added, so *ahead/behind* cannot see scope creep at all.

**Evidence.**

- **Scenario** [Scope creep](index.html#source=sample&seed=1&scenario=scope-creep&tab=time&day=2026-11-20):
  - on 20 November, three weeks of steps have been added and the tab reads *on plan*;
  - Scope change beneath it is red to the end;
  - switch to the *All* page to see Volume climb.
- Pinned in `P2`: [0.5 on the 9th, 0.25 on the 10th] after scope doubles.

**Direction.** Volume, in days, already answers what a share cannot. Consider plotting
actual *days landed* against the plan's days-by-date on one scale in days, which makes the
two lines comparable across scope changes. Or say in the heading that a share is of that
day's total.

---

## Recording and comparison

<a id="r1"></a>
### R1. Days with no record are drawn as straight lines

**What.** A row exists only on a day the recorder ran (the window was open, or `progress
record` was called) *and* the plan had changed. The actual line interpolates straight
across the gaps (`share_at`, calendar days).

**Evidence.** **Scenario** [Window rarely open](index.html#source=sample&seed=1&scenario=sparse&tab=records&day=2026-11-30):

- the Records tab greys the missing days;
- the actual line on the Time tab is straight segments.

**Real plan.** DPlanner's own plan has 4 rows over 15 days, and several commit days wrote
none.

**Direction.** Draw the actual line as steps between records (a record holds until the
next, as Volume already does). Or mark the records on the line so the reader can see the gaps.

<a id="r2"></a>
### R2. Scope change counts a staffing change as scope

**What.** A record freezes the dates its day's team and focus produced
(ARCHITECTURE.md: "a snapshot records the plan as simulated that day"). The Scope change
plot then compares the plan now with the plan then, and colours every difference as
pulled-in or slipped *scope*, whether it came from:

- scope;
- estimates;
- a new person;
- a different focus factor;
- a moved start date.

**Evidence.** **Scenario** [Someone joins](index.html#source=sample&seed=1&scenario=joiner&tab=time&day=2026-11-02):

- a second person and a third agent join on day 14 (19 October);
- against the plan at start, Scope change turns amber from mid-October to the end, though
  not one step or estimate changed;
- it turns amber *before* anyone joined, because the plan now re-dates the past with
  today's team ([F1](#f1)).

**Direction.** Store the team and focus on each record. Then either:

- say in the heading when the two plans were made for different teams; or
- split the delta into "because of scope" (the volume change) and "because of capacity".

<a id="r3"></a>
### R3. "Plan at start" is the start day's *last* state

**What.** The last write of a day wins (`progress.py:730` `recorded`). So the record that
stands for the start day already holds that day's work and changes.

**Evidence.** In the explainer's example week the actual line starts at 12%, because Design
was done on the Monday.

**Direction.** Minor. Either record the first write of the project's first day and keep
it, or have *Save snapshot* suggest itself at kickoff.

<a id="r4"></a>
### R4. The change list misses most changes, and unsizing forgets history

**What.** `changes_since` (`progress.py:557`), which is the terminal's and the report's
"what moved it", sees only two things:

- steps *born* after the baseline;
- estimates *changed* after it.

It does not see:

- removed steps;
- status changes (a revert included);
- relinks;
- team, focus or start changes.

Separately, setting an estimate back to none writes `{}` (`estimation/aspect.py:152`) and
drops the estimate's history with it.

**Evidence.** **Python.** "history [(2026-09-08, 2.0)] → [] (entry {})". The first half is
from reading the code.

**Direction.** Derive the change list by diffing two records' stretches, which are there
already, plus the graph. Keep the history when an estimate is cleared.

---

## Staffing

<a id="s1"></a>
### S1. Agents cost no one's time

**What.** Agent steps take an agent slot and are not stretched by focus. One person with
four agents runs four agent steps *and* a full-speed human step at once. That holds even
though the quarter-day convention assumes a person in the loop for each agent task
(ARCHITECTURE.md: "their human-in-the-loop cost is already inside the quarter-day estimate
convention").

**Evidence.** **Scenario** [Agents need supervision](index.html#source=sample&seed=1&scenario=supervision&tab=track&day=end):

- each running agent step takes a quarter of a person's day;
- M3 and M4 land 3–4 working days late;
- the forecast never sees it.

**Direction.** A per-project "supervision" share that each running agent step takes from
the human pool. It is one number, and the simulation already has the pools.

Also noted, deliberate and documented, and not counted as issues:

- the pools are strict;
- focus is the same for everyone;
- there are no holidays;
- a team always has at least one agent (`domain/schedule.py:253`).

---

## Sequencing and rounding

<a id="q3"></a>
### Q3. Each stretch rounds up to a whole day before the next begins

**What.** A stretch's finish is its fractional makespan rounded *up* to a working day. The
next stretch starts the working day *after* that (`domain/schedule.py:427`). A stretch that
ends a quarter of the way into a day costs the whole day, once per milestone. `schedule()`
rounds once, on the total, and `phases` does not.

**Evidence.**

- **Scenario** [By the book](index.html#source=sample&seed=1&scenario=by-the-book&tab=track&day=end):
  M2–M4 land 1–2 working days *before* their forecasts. Rounding shows on most seeds.
- `tests/sim_test.ts` proves that with `carry` and `epsilon` on, the first day's forecast
  is exactly what happens, for every milestone on six seeds.

**Direction.** Carry the part-day into the next stretch (`carry` in `options.ts`), and
round once, when a date is printed.

<a id="i1"></a>
### I1. Float noise and a bare `ceil` add a working day

**What.** Stretched estimates are floats summed in sequence. `working_days_after` then
applies a bare `ceil` (`domain/schedule.py:83`), so a sum that should be whole can overshoot
by 4e-15 and cost a day. A day that crosses a weekend costs three calendar days. Only the
calendar floor has an epsilon guard.

**Evidence.** **Python.** "15 one-day steps at 60% focus: makespan 25.000000000000004, lands
2026-10-12 instead of 2026-10-09". That is a Monday instead of the Friday.

**Direction.** `ceil(days − 1e-9)` (`epsilon` in `options.ts`), or count in integer
quarter-days.

<a id="q2"></a>
### Q2. Work no milestone gathers runs last

**What.** Steps no milestone reaches form a final stretch after the last milestone, even
when they wait on nothing (`domain/schedule.py:401`).

**Evidence.** **Python.** "X waits on nothing, 2 people, yet begins 2026-09-09 after M lands
2026-09-08".

**Direction.** Let unreached work fill idle slots from the start, or have lint name it,
since it is usually a missing link.

<a id="q1"></a>
### Q1. Milestones strictly in sequence

**What.** The model never lets the next milestone's work start early. Teams do.

**Evidence.** **Scenario** [Team works ahead](index.html#source=sample&seed=1&scenario=work-ahead&tab=track&day=end):
the effect is small, and not always an improvement. Someone busy on the next milestone is
not free when this one's next step becomes ready, so M3 lands a day *later*.

This is a documented choice. The finding is that it costs the forecast little.

<a id="i3"></a>
### I3. A zero-day step waits for a free worker

**What.** A milestone, feature or check step costs nothing but still takes a worker slot
(`domain/schedule.py:300`). A ready check step waits behind unrelated work, and whatever
follows it waits too.

**Evidence.** **Port.** Pinned in `I3`: the check lands at day 4, behind a 4-day step it
does not depend on.

**Direction.** Let zero-day steps land without a slot.

---

## Reporting and the view

<a id="u1"></a>
### U1. A landing date in the past is shown like any other

**What.**

- The milestone table, the calendar and Milestone shifts print a past landing date for an
  unfinished milestone with no mark.
- The Progress plot, beside them, says *behind 47%*.

So two halves of one tab disagree, and the table half is the one people quote.

**Evidence.**

- **Scenario** [Optimistic estimates, 20 Nov](index.html#source=sample&seed=1&scenario=optimistic&tab=time&day=2026-11-20):
  M2 "lands 12 November" at 71%, and the tab reads *behind 31%*.
- **Real plan.** On 26 September, DPlanner's own plan says #1 "lands 24 September" at
  91%, and the tab reads *ahead 34%*. Most of #1 was done on 12–13 September, before the
  plan's stored start of 14 September.

**Direction.** Mark a past landing on an unfinished milestone as *overdue*, in the table's
own ⚠ language. Better, fix [F1](#f1), and it cannot happen.

<a id="i2"></a>
### I2. "Unestimated" counts opted-out milestones

**What.** The banner's count is `report.unestimated` (`time_estimates/schedule.py:430`,
`module.py:831`). That counts every step whose days read as none, and milestone, feature
and check steps opt out of estimating by design. Lint gets this right
(`enabled(step) and read(step) is None`); the banner and `schedule matrix` do not.

**Evidence.**

- **CLI.** `dplanner schedule matrix DPlanner --json` on a copy of the real plan gives
  `"unestimated": 4`. Its 4 steps without days are its 4 milestones, and all work is
  estimated.
- **Real plan.** The prototype's banner says "4 steps unestimated — 4 of them opted out".

**Direction.** Count only steps whose estimate is enabled: one predicate, wired where
`days_for` is.

### U2. What the Track record shows that no DPlanner view does

The milestone trend chart plots each record's landing forecast against the day it was
recorded, with the real landing on the diagonal.

- It answered every question in this document faster than the Time tab did.
- It needs nothing new: it reads the rows already stored.
- It is the view to propose for the tab or the report: "how has our forecast moved, and
  how good was it?".
- *Ahead/behind* does not survive a re-planning forecast. With `replan` on, the line is
  re-anchored at today and reads ahead or on plan whatever happens.

The trend chart does survive, because it compares *forecasts*, not shares.

---

## What the v2 view answers, and what it still cannot

v2 (the page's *v2 · redesign*; README) changes how the stored data is *read*, not the model
or the data. That is enough to answer several of the issues above at the view level:

| Issue | How v2 answers it |
|---|---|
| **F1** dates never learn | The headline leads with the landing *at today's pace*: the plan's own landing moved on by the lag. The plan's own date stays beside it. |
| **U1** past dates shown plainly | A milestone whose planned landing has passed and is not done reads ⚠ Overdue, and heads the page. |
| **P1** "behind" while on time | Lag counts working days since the earliest undone work was due, reading the knots as steps. By the book it is zero on every day (`tests/brief_test.ts`). |
| **P2** shares of a moving total | Nothing in v2 is a share of a total: the burn-up is in days, and scope change is its own area, marked ▲ where work was added and ▼ where it was taken away. |
| **R2** staffing read as scope | A move is split into *changes to the plan* and *today's pace*. When dates moved with no change in scope, the change list says so and names the likely causes. |
| **I2** milestones counted as unestimated | Only steps somebody could size are counted in v2's "no estimate" line. |

**What it still cannot do**, because the data is not there:

- **Split a plan change into its causes.** Records keep neither the team, the focus nor the
  start date they were made with, so v2 can only say "no scope change, so something else".
  **Proposal: add `team`, `focus` and `start` to every `progress_history` row.** They are
  three small fields, and they would let the change list say which one moved the dates.
- **Name removed or moved steps.** Records keep counts, not steps.
- **Say when a milestone really landed.** It can only say "recorded done by <day>". The
  same missing fact limits re-planning ([F1](#f1)).

---

## What the model variants taught

- **`epsilon` and `carry` are pure wins.**
  - Together they make the first day's forecast exactly right when reality follows the
    estimates (`tests/sim_test.ts`).
  - They change nothing else.
- **`replan` fixes F1's worst symptom, and exposes the next missing fact.**
  - The forecasts climb toward the truth and meet it at landing.
  - Pricing an in-progress step at its full estimate makes the forecast *pessimistic*: it
    rises through a long step and drops when the step lands (a saw-tooth in Track record).
  - A stretch already finished falls back to its planned dates, because the model cannot
    know when it really finished.
  - A real fix needs a status timestamp and a remaining-effort estimate for work under way.
    The simplest would be elapsed working days against the estimate.
- **The scheduling core is sound.** With the rounding fixed and reality following the
  estimates, the greedy two-pool simulation predicts every milestone to the day.
  - The problems are not in how it schedules.
  - They are in what it reads (only done or not done), when it reads it (from the start,
    never from today), and how the view compares (shares against interpolated lines).
