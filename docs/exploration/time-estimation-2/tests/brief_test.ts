/**
 * v2's derived answers — lag, projection, the move split, verdicts, burn-up, changes. Lag is
 * a reading of DPlanner as it is today (`FAITHFUL`); re-planned from today, as the page runs,
 * nothing undone is ever late, and the last test pins that.
 */

import { type Day, fromYMD } from "../src/model/calendar.ts";
import { ADOPTED, FAITHFUL } from "../src/model/options.ts";
import { changesSince, take } from "../src/model/progress.ts";
import { brief, burnup, changes, paceOf } from "../src/brief.ts";
import { assert, assertEquals, MONDAY, planOf, sep } from "./helpers.ts";
import { played, viewOf } from "./played.ts";

const at = (today: Day) => ({ humans: 1, agents: 1, start: MONDAY, efficiency: 1.0, today });

Deno.test("lag counts the working days the earliest undone work is overdue — a step, never a slope", () => {
  const shape = { chain: true, days: { A: 2, B: 3 } };
  // A lands Tue 8, B Fri 11.
  const aDone = take(planOf(["A", "B"], { ...shape, done: ["A"] }), at(sep(9)))!;
  assertEquals(paceOf(aDone, null, sep(9)), {
    done: 2,
    promised: 2,
    short: 0,
    earned: sep(8),
    due: sep(11),
    lag: 0,
  });
  const nothing = take(planOf(["A", "B"], shape), at(sep(9)))!;
  assertEquals(paceOf(nothing, null, sep(9)).lag, 1);
  // B in flight on Thursday, exactly on schedule: no lag, although a line drawn between the
  // knots would already stand at 4 of 5 days.
  assertEquals(paceOf(aDone, null, sep(10)).lag, 0);
  assertEquals(paceOf(nothing, null, sep(14)).lag, 4); // A was due Tue 8: Wed, Thu, Fri, Mon
});

Deno.test("on a weekend, work that is overdue lands on Monday at the earliest, never in the past", () => {
  const nothing = take(planOf(["A", "B"], { chain: true, days: { A: 2, B: 3 } }), at(sep(12)))!;
  // A was due Tue 8; on Saturday 12 the soonest it can be done is Monday 14.
  assertEquals(paceOf(nothing, null, sep(12)).lag, paceOf(nothing, null, sep(14)).lag);
});

Deno.test("by the book, nothing is ever late: lag is zero and no verdict says otherwise", () => {
  const { timeline, viewOn } = played("by-the-book", FAITHFUL);
  for (const frame of timeline.frames.filter((one) => one.day >= timeline.begin)) {
    const found = brief(viewOn(frame.day));
    for (const scope of [found.whole, ...found.milestones]) {
      assertEquals(scope.pace.lag, 0, `${scope.label} on day ${frame.day - timeline.begin}`);
      assert(!["overdue", "later"].includes(scope.verdict), `${scope.label}: ${scope.verdict}`);
    }
  }
});

Deno.test("optimistic estimates: M2 is overdue on 20 November, and its projection is not", () => {
  const found = brief(played("optimistic", FAITHFUL).viewOn(fromYMD(2026, 11, 20)));
  const m2 = found.milestones.find((scope) => scope.label === "M2")!;
  assertEquals(m2.verdict, "overdue");
  assert(m2.pace.lag >= 3, `lag ${m2.pace.lag}`);
  assert(m2.move.projected! > fromYMD(2026, 11, 20));
  assertEquals([found.attention?.kind, found.attention?.scope], ["overdue", m2]);
  assert(
    found.whole.move.pace > 0 && found.whole.move.plan === 0,
    "the plan did not change; the pace did",
  );
});

Deno.test("someone joins: the dates move, the scope does not, and the list says so", () => {
  const view = played("joiner", FAITHFUL).viewOn(fromYMD(2026, 11, 2));
  const whole = brief(view).whole;
  assert(whole.move.plan! < 0, "the plan now lands earlier");
  const listed = changes(view, whole)!;
  assertEquals([listed.steps, listed.days, listed.unexplained], [0, 0, true]);
});

Deno.test("scope creep: the burn-up's scope climbs above the baseline, and each jump is named", () => {
  const view = played("scope-creep", FAITHFUL).viewOn(fromYMD(2026, 11, 20));
  const whole = burnup(view, null, true);
  assert(whole.baseline !== null);
  assert(whole.scope[whole.scope.length - 1][1] > whole.baseline!);
  assert(whole.jumps.some((jump) => jump.steps > 0 && jump.days > 0));
  const listed = changes(view, brief(view).whole)!;
  assert(listed.added.length > 0 && listed.added.length === listed.steps);
});

Deno.test("an undated plan has nothing earlier to compare with, and says so instead of a verdict", () => {
  const found = brief(played("undated", FAITHFUL).viewOn(fromYMD(2026, 10, 20)));
  assertEquals(found.compared, false);
  const kinds = [found.whole, ...found.milestones].map((scope) => scope.verdict);
  assert(kinds.every((kind) => ["no-baseline", "landed", "overdue"].includes(kind)), kinds.join());
});

Deno.test("a milestone the plan compared with never had is new, not on track", () => {
  const shape = { chain: true, days: { A: 1, B: 1 }, start: MONDAY };
  const then = take(planOf(["A", "M1", "B"], { ...shape, milestones: ["M1"] }), at(MONDAY))!;
  const now = planOf(["A", "M1", "B", "M2"], { ...shape, milestones: ["M1", "M2"] });
  const found = brief(viewOf(now, sep(8), { rows: [then], saved: [] }, FAITHFUL));
  assertEquals(found.milestones.find((scope) => scope.label === "M2")?.verdict, "new");
});

Deno.test("changes_since names steps born after the baseline and estimates changed after it", () => {
  const plan = planOf(["A", "B", "E"], {
    created: { A: sep(1), B: sep(1), E: sep(10) },
    days: { A: 1, B: 2 },
  });
  plan.steps[0].estimateHistory = [[sep(12), 3]];
  plan.steps[1].estimateHistory = [[sep(2), 1]];
  const found = changesSince(plan.steps, MONDAY);
  assertEquals(found.added.map(([step, days]) => [step.title, days]), [["E", null]]);
  assertEquals(found.estimates.map(([step, day, was, now]) => [step.title, day, was, now]), [[
    "A",
    sep(12),
    3,
    1,
  ]]);
});

Deno.test("re-planned from today, no undone work is late: the lag is zero and the plan's date moves", () => {
  const today = fromYMD(2026, 11, 20);
  const faithful = brief(played("optimistic", FAITHFUL).viewOn(today));
  const found = brief(played("optimistic", ADOPTED).viewOn(today));
  for (const scope of found.milestones.filter((one) => one.key && one.landedBy === null)) {
    assertEquals(scope.pace.lag, 0, scope.label);
    assert(scope.move.planned! >= today, `${scope.label} lands before today`);
    assertEquals(scope.move.projected, scope.move.planned);
  }
  const m2 = (of: typeof found) => of.milestones.find((scope) => scope.label === "M2")!;
  assert(
    m2(faithful).move.planned! < today && m2(found).move.planned! > m2(faithful).move.planned!,
  );
});

Deno.test("the burn-up's active days are exactly the days some step changed status", () => {
  const today = fromYMD(2026, 11, 20);
  const { timeline, viewOn } = played("by-the-book", ADOPTED);
  const moved = timeline.frames.filter((frame, index) =>
    index > 0 && frame.day <= today &&
    frame.plan.steps.some((step) =>
      timeline.frames[index - 1].plan.steps.find((one) => one.id === step.id)?.status !==
        step.status
    )
  ).map((frame) => frame.day);
  assert(moved.length > 5);
  assertEquals(burnup(viewOn(today), null, true).active, moved);
});
