/** The world, the recorder and replay — held to what the design says they are. */

import { isWorkingDay } from "../src/model/calendar.ts";
import { DONE, isMilestone } from "../src/model/graph.ts";
import { FAITHFUL, type ModelOptions } from "../src/model/options.ts";
import { landingIn } from "../src/model/progress.ts";
import { type ExportFile, planToJson } from "../src/data.ts";
import { replay } from "../src/sim/replay.ts";
import { SAMPLE_START, samplePlan } from "../src/sim/sample.ts";
import { SCENARIOS } from "../src/sim/scenarios.ts";
import { record, snapshotOf, type Timeline } from "../src/sim/timeline.ts";
import { DEFAULT_WORLD, run, type WorldParams } from "../src/sim/world.ts";
import { assert, assertEquals } from "./helpers.ts";

/** An unsized step costs nothing here, as the model counts it, unless a test says otherwise. */
function world(params: Partial<WorldParams> = {}, seed = 7): Timeline {
  return run(
    samplePlan(seed),
    { ...DEFAULT_WORLD, seed, unestimatedEffort: 0, ...params },
    SAMPLE_START,
  );
}

/** Each milestone's forecast on the first day of work, and the day it really landed. */
function forecastAndTruth(timeline: Timeline, options: ModelOptions): [number, number][] {
  const first = timeline.frames.find((frame) => frame.day === timeline.begin)!;
  const plan = timeline.frames[timeline.frames.length - 1].plan;
  const said = snapshotOf(first.plan, first.day, options)!;
  return plan.steps.filter(isMilestone).map((
    step,
  ) => [landingIn(said, step.id)!, timeline.finished.get(step.id)!]);
}

Deno.test("by the book, with the rounding fixed, the first day's forecast is what happens", () => {
  for (const seed of [1, 2, 3, 7, 11, 42]) {
    const timeline = world({}, seed);
    for (
      const [said, happened] of forecastAndTruth(timeline, {
        epsilon: true,
        carry: true,
        replan: "off",
        pace: false,
      })
    ) {
      assertEquals(said, happened, `seed ${seed}`);
    }
  }
});

Deno.test("by the book, DPlanner's own forecast is never early and is sometimes late", () => {
  let late = 0;
  for (const seed of [1, 2, 3, 7, 11, 42]) {
    for (const [said, happened] of forecastAndTruth(world({}, seed), FAITHFUL)) {
      assert(said >= happened, `seed ${seed}: forecast ${said} before the landing ${happened}`);
      if (said > happened) late += 1;
    }
  }
  assert(late > 0, "per-stretch rounding should cost at least one milestone a day somewhere");
});

Deno.test("the world is the same every time for one seed, and every step finishes", () => {
  const [a, b] = [world({ noise: 0.3, scopePerWeek: 2 }), world({ noise: 0.3, scopePerWeek: 2 })];
  assertEquals([...a.finished], [...b.finished]);
  const last = a.frames[a.frames.length - 1].plan;
  assert(last.steps.every((step) => step.status === DONE));
  assertEquals(a.finished.size, last.steps.length);
});

Deno.test("scope creep adds stamped steps that the working milestone waits on", () => {
  const timeline = world({ scopePerWeek: 5 });
  const last = timeline.frames[timeline.frames.length - 1].plan;
  const added = last.steps.filter((step) => step.id.startsWith("added-"));
  assert(added.length > 0);
  for (const step of added) {
    assert(step.created !== null && step.created >= SAMPLE_START);
    assert(
      last.steps.some((other) => other.requires.includes(step.id)),
      `${step.id} gathered by nothing`,
    );
  }
});

Deno.test("a re-estimate remembers the value it replaced, and reality does not move", () => {
  const plain = world({ humanBias: 1.5 });
  const learning = world({ humanBias: 1.5, reestimateEvery: 3, reestimateFactor: 1.5 });
  const last = learning.frames[learning.frames.length - 1].plan;
  assert(last.steps.some((step) => step.estimateHistory.length > 0));
  // The team works in the same order on the same true effort, so the same steps finish.
  assertEquals(learning.finished.size, plain.finished.size);
});

Deno.test("the recorder writes on the days it ran, and only when something changed", () => {
  const timeline = world({ humanBias: 1.2 });
  const recording = record(timeline, {
    options: FAITHFUL,
    cadence: "weekdays",
    saved: [],
    seed: 1,
  });
  assert(recording.rows.length > 5);
  assert(recording.rows.every((row) => isWorkingDay(row.day)));
  const days = recording.rows.map((row) => row.day);
  assertEquals(new Set(days).size, days.length);
  const saved = record(timeline, {
    options: FAITHFUL,
    cadence: "twice-weekly",
    saved: [{ day: SAMPLE_START, title: "Kickoff review", note: "" }, {
      day: SAMPLE_START + 1,
      title: "kickoff review",
      note: "",
    }],
    seed: 1,
  }).saved;
  assertEquals(saved.map((row) => row.title), ["Kickoff review"]);
});

Deno.test("an undated plan's forecast slides with the day it is read on", () => {
  const timeline = world({ dated: false });
  const [a, b] = [timeline.frames[5], timeline.frames[6]];
  const [said, later] = [snapshotOf(a.plan, a.day)!, snapshotOf(b.plan, b.day)!];
  assert(landingIn(later, null)! > landingIn(said, null)!);
});

Deno.test("every scenario plays to the end", () => {
  for (const scenario of SCENARIOS) {
    const timeline = world(scenario.world);
    const last = timeline.frames[timeline.frames.length - 1].plan;
    assert(last.steps.every((step) => step.status === DONE), scenario.id);
  }
});

Deno.test("a replayed history dates a step's finish by the first day it read done", () => {
  const plan = samplePlan(3);
  const frame = (day: string, done: string[], commit: string) => ({
    day,
    commit,
    time: `${day}T12:00:00+02:00`,
    plan: planToJson({
      ...plan,
      steps: plan.steps.map((step) => ({
        ...step,
        status: done.includes(step.id) ? "done" as const : "pending" as const,
      })),
    }),
    history: null,
  });
  const file: ExportFile = {
    format: "te2-export/1",
    title: "t",
    slug: "t",
    source: { repo: "", dir: "", exported: "" },
    frames: [
      frame("2026-10-05", [], "a"),
      frame("2026-10-07", ["s1"], "b"),
      frame("2026-10-07", ["s1", "s2"], "c"),
      frame("2026-10-09", ["s2"], "d"),
    ],
  };
  const timeline = replay(file);
  assertEquals(timeline.frames.length, 5); // 5th to 9th, the 6th and 8th carried over
  assertEquals(timeline.frames[1].events, []);
  assertEquals([...timeline.finished], [["s2", SAMPLE_START + 2]]); // s1 was undone on the 9th
});

Deno.test("the world stamps every status change with its day, and nothing else", () => {
  const timeline = world({ block: { after: 10, days: 3 } });
  let before = timeline.frames[0];
  for (const frame of timeline.frames.slice(1)) {
    for (const step of frame.plan.steps) {
      const was = before.plan.steps.find((one) => one.id === step.id);
      if (!was) continue;
      if (was.status !== step.status) assertEquals(step.since, frame.day, step.id);
      else assertEquals(step.since, was.since, step.id);
    }
    before = frame;
  }
  const last = timeline.frames[timeline.frames.length - 1].plan;
  for (const step of last.steps) {
    assertEquals(step.since, timeline.finished.get(step.id), `${step.id} done on its day`);
  }
});
