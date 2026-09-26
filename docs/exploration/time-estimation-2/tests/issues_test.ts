/**
 * The issues in ISSUES.md, pinned: each test holds the port to DPlanner's behaviour as it is
 * today, named by the issue's id. A model variant or a fix upstream that changes one of these
 * should flip exactly the test that names it — and then ISSUES.md should say so.
 */

import { workingDaysAfter } from "../src/model/calendar.ts";
import { daysFor } from "../src/model/graph.ts";
import { FAITHFUL } from "../src/model/options.ts";
import {
  actual,
  AT_START,
  expected,
  landingIn,
  resolve,
  shareOf,
  standing,
  take,
  toward,
} from "../src/model/progress.ts";
import { parallelFinish, phases, stretched, timeReport } from "../src/model/simulate.ts";
import { assert, assertEquals, MONDAY, planOf, sep } from "./helpers.ts";

const at = (today: number, start = MONDAY) => ({
  humans: 1,
  agents: 1,
  start,
  efficiency: 1.0,
  today,
});

Deno.test("F1: the forecast is the same whatever is done", () => {
  const shape = { chain: true, days: { A: 2, B: 2, C: 2 }, milestones: ["C"] };
  const none = take(planOf(["A", "B", "C"], shape), at(sep(30)))!;
  const all = take(planOf(["A", "B", "C"], { ...shape, done: ["A", "B", "C"] }), at(sep(30)))!;
  assertEquals(landingIn(none, "C"), landingIn(all, "C"));
  assert(landingIn(none, "C")! < sep(30), "and it happily dates the milestone in the past");
});

Deno.test("F2: an undated plan starts today, every day, and its plan at start is itself", () => {
  const plan = planOf(["A", "B"], { chain: true, days: { A: 2, B: 2 } });
  const [monday, tuesday] = [take(plan, at(MONDAY, MONDAY))!, take(plan, at(sep(8), sep(8)))!];
  assertEquals(landingIn(tuesday, null)! - landingIn(monday, null)!, 1);
  assert(resolve(AT_START, [tuesday], [], tuesday, sep(8)) === tuesday, "compared with itself");
});

Deno.test("F3: an unsized step costs nothing, and the banner cannot tell it from a milestone", () => {
  const plan = planOf(["A", "Unsized", "M"], { chain: true, days: { A: 2 }, milestones: ["M"] });
  plan.steps[2].estimateOff = true; // the milestone opted out, as every milestone template does
  const report = timeReport(plan, daysFor, { start: MONDAY, today: MONDAY, efficiency: 1 })!;
  assertEquals(report.unestimated, 2); // I2: "2 steps unestimated", one of them a milestone
  assertEquals(report.calendar[0].finish, sep(8)); // the unsized step ran as zero days
});

Deno.test("F4: in-progress and blocked read as not done, and delay nothing", () => {
  const shape = { chain: true, days: { A: 3, B: 3 } };
  const plan = planOf(["A", "B"], shape);
  const blocked = { ...plan, steps: plan.steps.map((s) => ({ ...s, status: "blocked" as const })) };
  const [a, b] = [take(plan, at(sep(20)))!, take(blocked, at(sep(20)))!];
  assertEquals(landingIn(a, null), landingIn(b, null));
  assertEquals(shareOf(toward(b, null)), 0);
});

Deno.test("P1: a step exactly on schedule reads as behind until it lands", () => {
  const plan = planOf(["Long"], { days: { Long: 5 } });
  const kickoff = take(plan, at(MONDAY))!;
  const working = {
    ...plan,
    steps: plan.steps.map((s) => ({ ...s, status: "in-progress" as const })),
  };
  const thirdDay = take(working, at(sep(9)))!;
  assertEquals(standing(expected(thirdDay, null), actual([kickoff], thirdDay, null), sep(9)), -0.5);
});

Deno.test("P2: a share is of its own day's total, so added scope lowers what landed", () => {
  const before = take(planOf(["A", "B"], { days: { A: 2, B: 2 }, done: ["A"] }), at(sep(9)))!;
  const after = take(
    planOf(["A", "B", "C", "D"], { days: { A: 2, B: 2, C: 2, D: 2 }, done: ["A"] }),
    at(sep(10)),
  )!;
  assertEquals(actual([before], after, null), [[sep(9), 0.5], [sep(10), 0.25]]);
});

Deno.test("Q2: work no milestone gathers runs last, even with nothing to wait for", () => {
  const plan = planOf(["A", "M", "X"], {
    days: { A: 1, M: 0, X: 1 },
    requires: { M: ["A"] },
    milestones: ["M"],
  });
  const [first, rest] = phases(plan, daysFor, {
    humans: 2,
    agents: 1,
    start: MONDAY,
    today: MONDAY,
  });
  assertEquals([first.finish, rest.start], [MONDAY, sep(8)]);
});

Deno.test("Q3: each stretch rounds up to a whole day before the next begins", () => {
  const plan = planOf(["A", "M1", "B", "M2"], {
    chain: true,
    days: { A: 0.5, M1: 0, B: 0.5, M2: 0 },
    milestones: ["M1", "M2"],
  });
  const faithful = phases(plan, daysFor, { humans: 1, agents: 1, start: MONDAY, today: MONDAY });
  const carried = phases(plan, daysFor, {
    humans: 1,
    agents: 1,
    start: MONDAY,
    today: MONDAY,
    options: { ...FAITHFUL, carry: true },
  });
  assertEquals(faithful[1].finish, sep(8)); // one day of work, two days on the calendar
  assertEquals(carried[1].finish, MONDAY);
});

Deno.test("I1: float noise and a bare ceil add a working day — here a whole weekend", () => {
  const titles = Array.from({ length: 15 }, (_, index) => `S${index}`);
  const plan = planOf(titles, { chain: true, days: Object.fromEntries(titles.map((t) => [t, 1])) });
  const run = parallelFinish(plan.steps, stretched(daysFor, 0.6), 1, 1)!;
  assertEquals(run.days, 25.000000000000004);
  const [faithful] = phases(plan, stretched(daysFor, 0.6), {
    humans: 1,
    agents: 1,
    start: MONDAY,
    today: MONDAY,
  });
  assertEquals(faithful.finish, workingDaysAfter(MONDAY, 26)); // Monday 12 Oct, not Friday 9 Oct
  const [guarded] = phases(plan, stretched(daysFor, 0.6), {
    humans: 1,
    agents: 1,
    start: MONDAY,
    today: MONDAY,
    options: { ...FAITHFUL, epsilon: true },
  });
  assertEquals(guarded.finish, workingDaysAfter(MONDAY, 25));
});

Deno.test("I3: a zero-day step waits for a free worker, and holds up what follows it", () => {
  // One person, busy four days on X. The check C costs nothing and is ready at once, but
  // waits for the person; D after it can only start when X is done.
  const plan = planOf(["X", "A", "C", "D"], {
    days: { X: 4, A: 0, C: 0, D: 1 },
    requires: { C: ["A"], D: ["C"] },
  });
  const run = parallelFinish(plan.steps, daysFor, 1, 1)!;
  assertEquals(run.landings.get("C"), 4);
  assertEquals(run.days, 5);
});

Deno.test("S1: agents cost no one's time — one person and four agents run five steps at once", () => {
  const plan = planOf(["H", "A1", "A2", "A3", "A4"], {
    days: { H: 2, A1: 2, A2: 2, A3: 2, A4: 2 },
    agents: ["A1", "A2", "A3", "A4"],
  });
  assertEquals(parallelFinish(plan.steps, daysFor, 1, 4)!.days, 2);
});
