/** What the page changes in the plan from a day on: re-budgets (and Delay steps). */

import { fromYMD } from "../src/model/calendar.ts";
import { ADOPTED } from "../src/model/options.ts";
import { landingIn, landingShift, samePlan } from "../src/model/progress.ts";
import {
  budgetOf,
  budgetsFromHash,
  budgetsToHash,
  edited,
  NO_EDITS,
  rebudget,
  worldBudgets,
} from "../src/sim/edits.ts";
import { SAMPLE_START, samplePlan } from "../src/sim/sample.ts";
import { record, snapshotOf } from "../src/sim/timeline.ts";
import { DEFAULT_WORLD, run } from "../src/sim/world.ts";
import { assert, assertEquals } from "./helpers.ts";
import { viewOf } from "./played.ts";

const DAY = fromYMD(2026, 10, 26);
const TWO = { humans: 2, agents: 2, efficiency: 0.5 };

function playedWith(edits = NO_EDITS) {
  return run(samplePlan(1), {
    ...DEFAULT_WORLD,
    seed: 1,
    unestimatedEffort: 0,
    budgets: worldBudgets(edits, SAMPLE_START),
  }, SAMPLE_START);
}

const withTwo = rebudget(NO_EDITS, DAY, TWO, { humans: 1, agents: 2, efficiency: 0.5 });

Deno.test("a re-budget changes the plan and the team from its day, and nothing before it", () => {
  const [plain, budgeted] = [playedWith(), playedWith(withTwo)];
  for (const frame of budgeted.frames) {
    const expected = frame.day < DAY ? budgetOf(samplePlan(1)) : TWO;
    assertEquals(budgetOf(frame.plan), expected, `${frame.day}`);
  }
  const before = (timeline: typeof plain) =>
    record(timeline, { options: ADOPTED, cadence: "weekdays", saved: [], seed: 1 }).rows
      .filter((row) => row.day < DAY);
  const [a, b] = [before(plain), before(budgeted)];
  assertEquals(a.length, b.length);
  a.forEach((row, index) => assert(samePlan(row, b[index]), `row ${row.day} changed`));
  // A second person really works from that day, so the plan and the world both land sooner.
  const on = (timeline: typeof plain) =>
    landingIn(snapshotOf(timeline.frames.find((f) => f.day === DAY)!.plan, DAY, ADOPTED)!, null)!;
  assert(on(budgeted) < on(plain), "the forecast moves on the day");
  const last = (timeline: typeof plain) => Math.max(...timeline.finished.values());
  assert(last(budgeted) < last(plain), "and the work really lands sooner");
});

Deno.test("a re-budget replaces that day's, and one that changes nothing is none", () => {
  const was = { humans: 1, agents: 2, efficiency: 0.5 };
  const twice = rebudget(withTwo, DAY, { ...TWO, efficiency: 0.6 }, was);
  assertEquals(twice.budgets, [{ day: DAY, ...TWO, efficiency: 0.6 }]);
  assertEquals(rebudget(twice, DAY, was, was).budgets, []);
  const later = rebudget(twice, DAY - 7, TWO, was);
  assertEquals(later.budgets.map((one) => one.day), [DAY - 7, DAY]);
});

Deno.test("re-budgets survive the address bar", () => {
  const edits = rebudget(withTwo, DAY + 7, { humans: 3, agents: 1, efficiency: 0.35 }, TWO);
  const text = budgetsToHash(edits.budgets);
  assertEquals(text, "2026-10-26:2+2@50;2026-11-02:3+1@35");
  assertEquals(budgetsFromHash(text), edits.budgets);
  assertEquals(budgetsFromHash("nonsense;2026-10-26:0+1@50"), []);
  assertEquals(budgetsFromHash("2026-10-26:2 2@50"), withTwo.budgets, "a typed + reads as a space");
});

Deno.test("a replay carries a re-budget on its frames from that day, and history stays", () => {
  const plain = playedWith();
  const budgeted = edited(plain, withTwo);
  budgeted.frames.forEach((frame, index) => {
    assertEquals(budgetOf(frame.plan), frame.day < DAY ? budgetOf(plain.frames[index].plan) : TWO);
    assertEquals(frame.plan.steps, plain.frames[index].plan.steps);
  });
});

Deno.test("work in flight when the focus changes is credited at the focus it ran at", () => {
  const cut = fromYMD(2026, 11, 2);
  const was = budgetOf(samplePlan(1));
  const tenth = rebudget(NO_EDITS, cut, { ...was, efficiency: 0.1 }, was);
  const timeline = playedWith(tenth);
  const plan = timeline.frames.find((frame) => frame.day === cut)!.plan;
  assertEquals(plan.assumptions.efficiencyWas, { until: cut, efficiency: 0.5 });
  // The half day nobody knows about a step's start, at 50%, is two and a half at 10%.
  const recording = record(timeline, { options: ADOPTED, cadence: "weekdays", saved: [], seed: 1 });
  const view = viewOf(plan, cut, recording); // As the page reads it.
  for (const said of [snapshotOf(plan, cut, ADOPTED)!, view.live]) {
    for (const stretch of said.stretches.filter((one) => one.key)) {
      const off = landingShift(timeline.finished.get(stretch.key)!, stretch.finish!);
      assert(Math.abs(off) <= 3, `${stretch.key} is ${off} working days off`);
    }
  }
});
