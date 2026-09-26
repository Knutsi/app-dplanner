/**
 * Delay steps: a wait until a day, or for n working days, that holds whatever requires it —
 * no work, no worker, no status of its own, and no part of any tally.
 */

import { type Day, fromYMD } from "../src/model/calendar.ts";
import { daysFor, type Delay, efficiencyOf, isMilestone, type Plan } from "../src/model/graph.ts";
import { ADOPTED } from "../src/model/options.ts";
import { landingIn, tally } from "../src/model/progress.ts";
import {
  chainTails,
  groups,
  landingOf,
  parallelFinish,
  phases,
  stretched,
} from "../src/model/simulate.ts";
import { forecastsOf } from "../src/sim/accuracy.ts";
import {
  delayId,
  delaysFromHash,
  delaysToHash,
  edited,
  NO_EDITS,
  worldDelays,
} from "../src/sim/edits.ts";
import { SAMPLE_START, samplePlan } from "../src/sim/sample.ts";
import { snapshotOf, type Timeline } from "../src/sim/timeline.ts";
import { DEFAULT_WORLD, run } from "../src/sim/world.ts";
import { assert, assertEquals, planOf, sep } from "./helpers.ts";

const WEDNESDAY = sep(9);

/** A takes a day; B waits on the delay W; nobody works on W. */
function waitingOn(delay: Delay, shape: Parameters<typeof planOf>[1] = {}): Plan {
  return planOf(["A", "W", "B"], {
    days: { A: 1, B: 1 },
    requires: { B: ["W"] },
    delays: { W: delay },
    ...shape,
  });
}

function landings(plan: Plan, today: Day): Day[] {
  const dated = phases(plan, daysFor, {
    humans: 1,
    agents: 1,
    start: sep(7),
    today,
    options: ADOPTED,
  });
  return ["A", "B"].map((id) => landingOf(dated[0], id));
}

Deno.test("a days delay holds what waits on it, and the worker it does not need works on", () => {
  const plan = planOf(["A", "W", "B", "C"], {
    days: { A: 1, B: 1, C: 2 },
    requires: { W: ["A"], B: ["W"] },
    delays: { W: { days: 3 } },
  });
  const run = parallelFinish(plan.steps, daysFor, 1, 1)!;
  assertEquals(
    ["A", "W", "C", "B"].map((id) => [run.starts.get(id), run.landings.get(id)]),
    [[0, 1], [1, 4], [1, 3], [4, 5]],
  );
});

Deno.test("an until delay lets what waits on it start on its day, and not before", () => {
  // Without it B would follow A on Tuesday; waiting until Wednesday, it lands Wednesday.
  assertEquals(landings(waitingOn({ until: WEDNESDAY }), sep(4)), [sep(7), WEDNESDAY]);
  assertEquals(landings(waitingOn({ until: sep(12) }), sep(4)), [sep(7), sep(14)], "a Saturday");
});

Deno.test("a delay whose day has passed costs nothing", () => {
  const plan = waitingOn({ until: WEDNESDAY }, { done: ["A"], since: { A: sep(7) } });
  // Thursday, with B not started: it resumes from Friday, with nothing left to wait for.
  assertEquals(landings(plan, sep(10))[1], sep(11));
});

Deno.test("a delay is no work: it changes no tally, and is never unsized", () => {
  const plain = planOf(["A", "B"], { days: { A: 1, B: 1 } });
  const delayed = waitingOn({ days: 2 });
  assertEquals(tally(delayed.steps), tally(plain.steps));
  assertEquals(delayed.steps.filter((step) => daysFor(step) === null && !step.estimateOff), []);
});

// -- in the world ------------------------------------------------------------------------------------

const MADE = fromYMD(2026, 10, 12);

/** By the book, with the step M2's longest chain starts from made to wait, on MADE. */
function delayedWorld(delay: Delay | null): { timeline: Timeline; held: string } {
  const plan = samplePlan(1);
  const [[m1], [, members]] = groups(plan);
  const tails = chainTails(members, stretched(daysFor, efficiencyOf(plan)));
  const held = members.filter((step) => step.requires.includes(m1!.id))
    .sort((a, b) => tails.get(b.id)! - tails.get(a.id)!)[0].id;
  const edits = delay ? { ...NO_EDITS, delays: [{ day: MADE, before: held, delay }] } : NO_EDITS;
  const timeline = run(plan, {
    ...DEFAULT_WORLD,
    seed: 1,
    unestimatedEffort: 0,
    delays: worldDelays(edits, SAMPLE_START),
  }, SAMPLE_START);
  return { timeline, held };
}

function exactFrom(timeline: Timeline, day: Day, within: number) {
  const plan = timeline.frames[timeline.frames.length - 1].plan;
  for (const step of plan.steps.filter(isMilestone)) {
    const truth = timeline.finished.get(step.id)!;
    for (const [when, said] of forecastsOf(timeline, ADOPTED, step.id, truth)) {
      if (when < day) continue;
      const off = Math.abs(said - truth);
      assert(off <= within, `${step.milestone} on ${when}: said ${said}, landed ${truth}`);
    }
  }
}

Deno.test("the team waits for a delay: the held step starts no earlier than it allows", () => {
  const until = fromYMD(2026, 11, 4);
  const { timeline, held } = delayedWorld({ until });
  const started =
    timeline.frames.find((frame) =>
      frame.plan.steps.find((step) => step.id === held)!.status !== "pending"
    )!.day;
  // It is picked up the moment the wait ends: as the day before Wednesday ends.
  assertEquals(started, fromYMD(2026, 11, 3));
  const w = timeline.frames.at(-1)!.plan.steps.find((step) => step.delay !== null)!;
  assertEquals([w.id, w.created, w.requires.length > 0], [
    delayId({ day: MADE, before: held, delay: { until } }),
    MADE,
    true,
  ]);
});

Deno.test("by the book with a delay until Wednesday, every forecast from that day is exact", () => {
  const { timeline } = delayedWorld({ until: fromYMD(2026, 11, 4) });
  exactFrom(timeline, MADE, 0);
});

Deno.test("by the book with a delay of days, the forecast from that day is within a day", () => {
  const { timeline } = delayedWorld({ days: 4 });
  exactFrom(timeline, MADE, 1);
});

Deno.test("'what if testing starts Wednesday?': the milestones behind it move, to the day", () => {
  const plain = delayedWorld(null).timeline;
  const { timeline } = delayedWorld({ until: fromYMD(2026, 11, 4) });
  const on = (one: Timeline) => one.frames.find((frame) => frame.day === MADE)!.plan;
  const m2 = on(plain).steps.filter(isMilestone)[1].id;
  const before = landingIn(snapshotOf(on(plain), MADE, ADOPTED)!, m2)!;
  const after = landingIn(snapshotOf(on(timeline), MADE, ADOPTED)!, m2)!;
  assert(after > before, "M2 moves out");
  assertEquals(after, timeline.finished.get(m2), "to the day it really lands");
});

Deno.test("a replay carries a delay from its day on; delays survive the address bar", () => {
  const plain = delayedWorld(null);
  const edit = { day: MADE, before: plain.held, delay: { days: 3 } };
  const withDelay = edited(plain.timeline, { ...NO_EDITS, delays: [edit] });
  withDelay.frames.forEach((frame, index) => {
    const requires = (plan: Plan) => plan.steps.find((step) => step.id === plain.held)!.requires;
    const was = requires(plain.timeline.frames[index].plan);
    assertEquals(requires(frame.plan), frame.day < MADE ? was : [delayId(edit)]);
    assertEquals(frame.plan.steps.some((step) => step.delay !== null), frame.day >= MADE);
  });
  const edits = [edit, { day: MADE + 1, before: "s9", delay: { until: WEDNESDAY } }];
  const text = delaysToHash(edits);
  assertEquals(text, `2026-10-12:${plain.held}:days:3;2026-10-13:s9:until:2026-09-09`);
  assertEquals(delaysFromHash(text), edits);
});
