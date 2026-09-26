/**
 * The port held to DPlanner's own tests: each case here is one from
 * tests/domain/test_schedule.py or tests/modules/test_time_progress.py, same numbers.
 */

import {
  axisTicks,
  formatDate,
  formatDays,
  fromYMD,
  nextWorkingDay,
  volumeWords,
  weekday,
  workingDaysAfter,
  workingDaysBetween,
} from "../src/model/calendar.ts";
import { cyclic, daysFor, type Plan } from "../src/model/graph.ts";
import { paletteById, shades } from "../src/model/palettes.ts";
import {
  actual,
  AT_START,
  baseline,
  changeRuns,
  delta,
  deltaWords,
  expected,
  idle,
  LIVE,
  marks,
  niceCeiling,
  pickWords,
  recorded,
  remaining,
  resolve,
  savedWith,
  scopeWords,
  shareAt,
  shiftOf,
  shiftWords,
  type Snapshot,
  take,
  toward,
  volume,
} from "../src/model/progress.ts";
import {
  calendarDays,
  criticalPath,
  landingOf,
  parallelFinish,
  phases,
  pushed,
} from "../src/model/simulate.ts";
import {
  assert,
  assertClose,
  assertEquals,
  assertThrows,
  CHAIN,
  DAYS,
  MONDAY,
  planOf,
  SATURDAY,
  sep,
} from "./helpers.ts";

// -- the calendar ----------------------------------------------------------------------------

Deno.test("a weekend start rolls forward to the Monday", () => {
  assertEquals(nextWorkingDay(SATURDAY), sep(14));
  assertEquals(nextWorkingDay(MONDAY), MONDAY);
  assertEquals(weekday(MONDAY), 0);
});

Deno.test("five days from a Monday finishes on the Friday; a sixth lands on the Monday", () => {
  assertEquals(workingDaysAfter(MONDAY, 5), sep(11));
  assertEquals(workingDaysAfter(MONDAY, 6), sep(14));
  assertEquals(workingDaysAfter(MONDAY, 0.5), MONDAY);
});

Deno.test("a landing counts working days across every weekend from any start", () => {
  for (let offset = 0; offset < 14; offset += 1) {
    const start = MONDAY + offset;
    for (const days of [0.5, 1, 2, 4.5, 5, 6, 7, 11, 23, 64, 250]) {
      const landing = workingDaysAfter(start, days);
      assert(weekday(landing) < 5);
      assertEquals(
        workingDaysBetween(nextWorkingDay(start), landing),
        Math.max(1, Math.ceil(days)),
      );
    }
  }
});

Deno.test("dates and day counts are worded as DPlanner words them", () => {
  assertEquals(formatDate(sep(23), sep(1)), "23 September");
  assertEquals(formatDate(fromYMD(2027, 2, 14), sep(1)), "14 Feb '27");
  assertEquals(formatDays(3), "3d");
  assertEquals(formatDays(12), "2.4w");
  assertEquals(formatDays(11.25), "2.2w"); // Python's round: 2.25 is a tie, to the even 2.2
  assertEquals(volumeWords(12, 7, 1), "12 days over 7 steps, 1 unestimated");
  assertEquals(volumeWords(1, 1, 0), "1 day over 1 step");
});

Deno.test("the axis marks days, else Mondays, else month firsts", () => {
  assertEquals(axisTicks(sep(7), sep(9), 10).map(([, label]) => label), [
    "7 Sep",
    "8 Sep",
    "9 Sep",
  ]);
  assertEquals(axisTicks(sep(1), sep(30), 6).map(([, label]) => label), [
    "7 Sep",
    "14 Sep",
    "21 Sep",
    "28 Sep",
  ]);
  assertEquals(
    axisTicks(sep(1), fromYMD(2027, 2, 1), 6).map(([, label]) => label),
    ["Sep", "Oct", "Nov", "Dec", "Jan '27", "Feb"],
  );
});

// -- staffing between the brackets -------------------------------------------------------------

function diamond(days: Record<string, number>): Plan {
  return planOf(CHAIN, { days, requires: { B: ["A"], C: ["A"], D: ["B", "C"] } });
}

Deno.test("one worker meets the serial total and ample workers the path", () => {
  const plan = diamond({ A: 1, B: 2, C: 10, D: 1 });
  assertEquals(parallelFinish(plan.steps, daysFor, 1, 1)!.days, 14.0);
  assertEquals(parallelFinish(plan.steps, daysFor, 4, 1)!.days, 12.0);
  assertEquals(criticalPath(plan, daysFor)!.days, 12.0);
});

Deno.test("neither pool takes the other's work", () => {
  const plan = planOf(["H", "X", "Y", "Z"], {
    days: { H: 5, X: 1, Y: 1, Z: 1 },
    agents: ["X", "Y", "Z"],
  });
  assertEquals(parallelFinish(plan.steps, daysFor, 1, 1)!.days, 5.0);
  assertEquals(parallelFinish(plan.steps, daysFor, 1, 3)!.days, 5.0);
  assertEquals(parallelFinish(plan.steps, daysFor, 4, 1)!.days, 5.0);
});

Deno.test("a free slot takes the longest remaining chain first", () => {
  const plan = planOf(["A", "D", "C", "B"], {
    days: { A: 1, B: 5, C: 4, D: 2 },
    requires: { B: ["A"] },
  });
  assertEquals(parallelFinish(plan.steps, daysFor, 2, 1)!.days, 6.0);
});

Deno.test("unestimated steps cost nothing and are all counted", () => {
  const finish = parallelFinish(diamond({ A: 1, D: 1 }).steps, daysFor, 2, 1)!;
  assertEquals([finish.days, finish.unestimated], [2.0, 2]);
  const none = parallelFinish(planOf(CHAIN, { chain: true }).steps, daysFor, 1, 1)!;
  assertEquals([none.days, none.unestimated], [0.0, 4]);
});

Deno.test("quarter days sum exactly; an empty project has no makespan; an empty pool is refused", () => {
  const plan = planOf(["A", "B", "C"], { days: { A: 0.25, B: 0.75, C: 0.25 } });
  assertEquals(parallelFinish(plan.steps, daysFor, 1, 1)!.days, 1.25);
  assertEquals(parallelFinish([], daysFor, 1, 1), null);
  assertThrows(() => parallelFinish(plan.steps, daysFor, 0, 1));
  assertThrows(() => parallelFinish(plan.steps, daysFor, 1, 0));
});

Deno.test("the simulation says when each step lands", () => {
  const plan = planOf(CHAIN, { days: DAYS, chain: true });
  const run = parallelFinish(plan.steps, daysFor, 1, 1)!;
  assertEquals([...run.landings], [["A", 1], ["B", 3], ["C", 6], ["D", 10]]);
  const [only] = phases(plan, daysFor, { humans: 1, agents: 1, start: MONDAY, today: MONDAY });
  assertEquals(plan.steps.map((step) => landingOf(only, step.id)), [
    MONDAY,
    sep(9),
    sep(14),
    sep(18),
  ]);
  assertEquals(landingOf(only, "nobody"), MONDAY);
});

Deno.test("a subset simulation treats edges out of it as met", () => {
  const plan = planOf(CHAIN, { days: DAYS, chain: true });
  assertEquals(parallelFinish(plan.steps, daysFor, 1, 1)!.days, 10.0);
  assertEquals(parallelFinish(plan.steps.slice(2), daysFor, 1, 1)!.days, 7.0);
});

// -- the plan in stretches ---------------------------------------------------------------------

function stretches(milestones: string[], starts: Record<string, number> = {}, days = DAYS) {
  const plan = planOf(CHAIN, { days, chain: true, milestones, starts });
  return phases(plan, daysFor, { humans: 1, agents: 1, start: MONDAY, today: MONDAY });
}

Deno.test("without milestones the plan is one stretch from the start", () => {
  const [only] = stretches([]);
  assertEquals([only.milestone, only.days, only.start, only.finish], [null, 10.0, MONDAY, sep(18)]);
  assertEquals(calendarDays(only), 10);
});

Deno.test("milestones run in sequence, each from the day after the last", () => {
  const [first, second] = stretches(["B", "D"]);
  assertEquals(first.steps.map((s) => s.title), ["A", "B"]);
  assertEquals([first.start, first.finish], [MONDAY, sep(9)]);
  assertEquals(second.steps.map((s) => s.title), ["C", "D"]);
  assertEquals([second.start, second.finish], [sep(10), sep(18)]);
  assert(!pushed(first) && !pushed(second));
});

Deno.test("a dated milestone begins on its date; an earlier one is pushed and reported", () => {
  const [, kept] = stretches(["B", "D"], { D: sep(21) });
  assertEquals([kept.asked, kept.start, kept.finish, pushed(kept)], [
    sep(21),
    sep(21),
    sep(29),
    false,
  ]);
  const [, moved] = stretches(["B", "D"], { D: sep(8) });
  assertEquals([moved.asked, moved.start, pushed(moved)], [sep(8), sep(10), true]);
});

Deno.test("the first milestone may be dated before the project start", () => {
  assertEquals(stretches(["B", "D"], { B: sep(5) })[0].start, MONDAY);
  assertEquals(stretches(["B", "D"], { B: sep(1) })[0].start, sep(1));
});

Deno.test("work no milestone gathers runs last without one", () => {
  const [, rest] = stretches(["B"]);
  assertEquals([rest.milestone, rest.steps.map((s) => s.title), rest.start], [
    null,
    ["C", "D"],
    sep(10),
  ]);
});

Deno.test("a stretch with nothing estimated has no landing and costs no days", () => {
  const [first, second] = stretches(["B", "D"], {}, { C: 3.0, D: 4.0 } as typeof DAYS);
  assertEquals([first.finish, first.unestimated, calendarDays(first)], [null, 2, 0]);
  assertEquals(second.start, MONDAY);
});

Deno.test("a loop in a hand-edited file is named", () => {
  const plan = planOf(CHAIN, { chain: true, requires: { A: ["D"] } });
  assertEquals(cyclic(plan).map((step) => step.title), ["A", "B", "C", "D"]);
});

// -- progress ------------------------------------------------------------------------------------

function snapshot(
  finished: string[] = ["A", "B"],
  closing: string[] = ["B", "D"],
  today = sep(10),
  extra: Partial<Parameters<typeof planOf>[1]> = {},
): Snapshot {
  // A step added through `extra.days` waits on nothing, as `library.add_child` leaves it.
  const added = Object.keys(extra.days ?? {});
  const plan = planOf([...CHAIN, ...added], {
    ...extra,
    chain: true,
    days: { ...DAYS, ...extra.days },
    done: finished,
    milestones: closing,
    requires: { ...Object.fromEntries(added.map((title) => [title, []])), ...extra.requires },
  });
  return take(plan, { humans: 1, agents: 1, start: MONDAY, efficiency: 1.0, today })!;
}

Deno.test("a snapshot tallies each stretch in sequence, cumulative through a milestone", () => {
  const now = snapshot();
  const [v1, v2] = now.stretches;
  assertEquals([v1.key, v1.tally, v1.start, v1.finish], [
    "B",
    { steps: 2, done: 2, days: 3, doneDays: 3 },
    MONDAY,
    sep(9),
  ]);
  assertEquals([v2.key, v2.tally, v2.start, v2.finish], [
    "D",
    { steps: 2, done: 0, days: 7, doneDays: 0 },
    sep(10),
    sep(18),
  ]);
  assertEquals(toward(now, "D"), { steps: 4, done: 2, days: 10, doneDays: 3 });
  assertEquals(toward(now, "nobody"), { steps: 0, done: 0, days: 0, doneDays: 0 });
});

Deno.test("a stretch records what lands on each date, and the curve is the simulation's", () => {
  const now = snapshot();
  assertEquals(now.stretches[0].landings, [{ day: MONDAY, steps: 1, days: 1 }, {
    day: sep(9),
    steps: 1,
    days: 2,
  }]);
  assertEquals(expected(now, null), [[MONDAY, 0], [MONDAY, 0.1], [sep(9), 0.3], [sep(14), 0.6], [
    sep(18),
    1,
  ]]);
  assertEquals(expected(now, "B"), [[MONDAY, 0], [MONDAY, 1 / 3], [sep(9), 1]]);
  assertEquals(expected(now, "nobody"), []);
});

Deno.test("the actual curve is every recorded day then today", () => {
  const earlier = snapshot([], undefined, sep(8));
  const then = snapshot(["A"], undefined, sep(9));
  const now = snapshot();
  assertEquals(actual([earlier, then], now, "D"), [[sep(8), 0.0], [sep(9), 0.1], [sep(10), 0.3]]);
  const before = snapshot([], ["B"], MONDAY);
  assertEquals(actual([before, then], now, "D")[0], [sep(9), 0.1]);
  const later = snapshot(["A", "B", "C"], undefined, sep(15));
  assertEquals(actual([earlier, then, later], now, "D"), [[sep(8), 0.0], [sep(9), 0.1], [
    sep(10),
    0.3,
  ]]);
});

Deno.test("the baseline is the last record on or before the basis, never today's own", () => {
  const first = snapshot([], undefined, MONDAY);
  const later = snapshot(["A"], undefined, sep(9));
  assert(baseline([first, later], sep(8)) === first);
  assert(baseline([first, later], sep(9)) === later);
  assert(baseline([first, later], sep(1)) === first);
  assert(baseline([], MONDAY) === null);
  assert(baseline([first, later], sep(1), sep(8)) === first);
  assert(baseline([later], sep(1), sep(9)) === null);
  assert(baseline([later], sep(1), sep(10)) === later);
});

Deno.test("a pick names which recorded plan a side of the comparison reads", () => {
  const first = snapshot([], undefined, MONDAY);
  const later = snapshot(["A"], undefined, sep(9));
  const live = snapshot();
  const kept = savedWith([], later, "Kickoff review", "what we thought");
  const found = (pick: Parameters<typeof resolve>[0], start = MONDAY) =>
    resolve(pick, [first, later], kept, live, start);
  assert(found(AT_START) === first);
  assert(found(AT_START, sep(1)) === first);
  assert(found(AT_START, sep(10)) === later);
  assert(found(LIVE) === live);
  assert(found({ kind: "day", day: sep(9) }) === later);
  assert(found({ kind: "day", day: sep(8) }) === first);
  assertEquals(found({ kind: "saved", title: "kickoff review" }), kept[0]);
  assert(found({ kind: "saved", title: "nobody" }) === null);
  assert(resolve(AT_START, [live], [], live, MONDAY) === null);
  const today = sep(10);
  assertEquals(pickWords(AT_START, first, today), "the plan at start, recorded 7 September");
  assertEquals(pickWords({ kind: "day", day: sep(9) }, later, today), "the plan at 9 September");
  assertEquals(
    pickWords({ kind: "day", day: sep(8) }, first, today),
    "the plan at 8 September, recorded 7 September",
  );
  assertEquals(
    pickWords({ kind: "saved", title: "Kickoff review" }, kept[0], today),
    "Kickoff review (9 September)",
  );
  assertEquals(pickWords(LIVE, live, today), "now");
  assertEquals(pickWords(AT_START, null, today), "");
});

Deno.test("the headings name the plan compared with", () => {
  assertEquals(scopeWords(""), "Scope change — nothing to compare with");
  const today = sep(10);
  assertEquals(
    shiftWords("v2", sep(18), sep(23), "Kickoff review", today),
    "v2 lands 23 September — 3 working days later than Kickoff review said (18 September)",
  );
  assertEquals(
    shiftWords("v2", null, sep(23), "Kickoff review", today),
    "v2 lands 23 September — not in Kickoff review",
  );
  assertEquals(shiftWords("v2", null, sep(23), "", today), "v2 lands 23 September");
});

Deno.test("the delta says what was added and how the landing moved", () => {
  const then = snapshot([], undefined, MONDAY);
  const now = snapshot(["A"], undefined, sep(10), {
    days: { E: 5.0 },
    requires: { D: ["C", "E"] },
  });
  const moved = delta(then, now, "D")!;
  assertEquals(moved, { steps: 1, days: 5.0, finishThen: sep(18), finishNow: sep(25) });
  assertEquals(shiftOf(moved), 5);
  assertEquals(
    deltaWords(moved, then.day, sep(10)),
    "since 7 September: +1 step, +5d, lands 5 working days later (was 18 September)",
  );
  assertEquals(
    deltaWords(delta(then, now, "B")!, then.day, sep(10)),
    "unchanged since 7 September",
  );
  assertEquals(delta(then, now, "nobody"), null);
});

Deno.test("recording writes only when the day says something new", () => {
  const first = snapshot([], undefined, MONDAY);
  assertEquals(recorded([], first), [first]);
  assertEquals(recorded([first], snapshot([], undefined, sep(8))), null);
  const later = snapshot(["A"], undefined, MONDAY);
  assertEquals(recorded([first], later), [later]);
  const nextDay = snapshot(["A", "B"], undefined, sep(8));
  assertEquals(recorded([first, later], nextDay), [first, later, nextDay]);
  assertEquals(recorded([first, later, nextDay], nextDay), null);
});

Deno.test("a milestone whose start is later opens a gap the plan holds flat", () => {
  const plan = planOf(CHAIN, {
    chain: true,
    days: DAYS,
    done: ["A", "B"],
    milestones: ["B", "D"],
    starts: { D: sep(21) },
  });
  const now = take(plan, { humans: 1, agents: 1, start: MONDAY, efficiency: 1.0, today: sep(10) })!;
  assertEquals(idle(now, null), [[sep(9), sep(21)]]);
  assertEquals(idle(now, "B"), []);
  assertEquals(marks(now, null).map(([, key]) => key), ["B", "D"]);
  const curve = expected(now, null);
  assert(
    curve.some(([d, s]) => d === sep(9) && s === 0.3) &&
      curve.some(([d, s]) => d === sep(21) && s === 0.3),
  );
  assertEquals(idle(snapshot(), null), []);
});

Deno.test("the volume is a step curve of each recorded day's total", () => {
  const first = snapshot([], undefined, MONDAY);
  const then = snapshot(["A"], undefined, sep(9));
  const now = snapshot(["A", "B"], undefined, sep(10), { days: { E: 5.0 } });
  assertEquals(volume([first, then], now), [
    [MONDAY, 10],
    [sep(9), 10],
    [sep(9), 10],
    [sep(10), 10],
    [sep(10), 15],
  ]);
  assertEquals(remaining([first, then], now), [[MONDAY, 10], [sep(9), 10], [sep(9), 9], [
    sep(10),
    9,
  ], [sep(10), 12]]);
  assertEquals(volume([], null), []);
  assertEquals([0, 1, 3, 12, 20, 41, 130].map(niceCeiling), [1, 1, 5, 20, 20, 50, 200]);
});

// -- reading two lines together --------------------------------------------------------------

Deno.test("a line is read at a date by interpolating between its corners", () => {
  const line: [number, number][] = [[sep(1), 0.0], [sep(11), 1.0]];
  assertEquals(shareAt(line, sep(1)), 0.0);
  assertClose(shareAt(line, sep(6))!, 0.5);
  assertEquals(shareAt(line, sep(30)), 1.0);
  assertEquals(shareAt(line, fromYMD(2026, 8, 20)), null);
  assertEquals(shareAt([], sep(1)), null);
  assertEquals(shareAt([[sep(1), 0.4]], fromYMD(2026, 8, 1)), 0.4);
});

Deno.test("two plans are cut into runs of one sign at the day they cross", () => {
  const runs = changeRuns([[sep(1), 0.0], [sep(11), 1.0]], [[sep(1), 0.4], [sep(11), 0.6]]);
  assertEquals(runs.map(([sign]) => sign), [-1, 1]);
  const [[, behind], [, ahead]] = runs;
  assertEquals(behind[behind.length - 1], ahead[0]);
  assert(sep(4) <= ahead[0][0] && ahead[0][0] <= sep(6));
  const line: [number, number][] = [[sep(1), 0.0], [sep(11), 1.0]];
  const [[sign, run]] = changeRuns(line, line);
  assertEquals([sign, run.length], [0, 2]);
  assertEquals(changeRuns(line, []), []);
});

Deno.test("shades are dealt evenly along the map, centred", () => {
  assertEquals(shades(paletteById("viridis"), 1), ["#26828e"]);
  assertEquals(shades(paletteById("nobody"), 2).length, 2);
});
