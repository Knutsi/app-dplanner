/**
 * The parity fixture for the Qt backport: each scenario played out, day by day, as the
 * events DPlanner would store — and the forecast the page's model made on each day.
 *
 *   deno task export-parity <out.json>
 *
 * The backport replays the events into a real library and holds its model to the same
 * forecasts (`tests/modules/test_time_parity.py` in the app). Only what DPlanner stores
 * travels: a step's title, number, requires, estimate, whether its estimate is off, its
 * milestone label, agent flag, created day, a milestone's start date, and its status with
 * the two days a status remembers; the project's start and its assumptions. The world
 * itself stays here — the app's simulator is checked loosely, the model exactly.
 */

import { type Day, isoDay, isWorkingDay } from "../src/model/calendar.ts";
import type { Plan, Step } from "../src/model/graph.ts";
import { ADOPTED } from "../src/model/options.ts";
import { SAMPLE_START, samplePlan } from "../src/sim/sample.ts";
import { SCENARIOS } from "../src/sim/scenarios.ts";
import { snapshotOf } from "../src/sim/timeline.ts";
import { DEFAULT_WORLD, run } from "../src/sim/world.ts";

const SEEDS = [1, 2, 3];

const iso = (
  day: Day | null | undefined,
) => (day === null || day === undefined ? null : isoDay(day));

function stepJson(step: Step) {
  return {
    id: step.id,
    number: step.number,
    title: step.title,
    requires: step.requires,
    estimate: step.estimate,
    off: step.estimateOff,
    milestone: step.milestone,
    agent: step.agent,
    created: iso(step.created),
    start: iso(step.start),
    status: step.status,
    since: iso(step.since),
    started: iso(step.started),
  };
}

function planJson(plan: Plan) {
  const was = plan.assumptions.efficiencyWas;
  return {
    start: iso(plan.start),
    efficiency: plan.assumptions.efficiency,
    team: plan.assumptions.team,
    efficiencyWas: was ? { until: isoDay(was.until), efficiency: was.efficiency } : null,
  };
}

const out = Deno.args[0];
if (!out) throw new Error("usage: deno task export-parity <out.json>");
const scenarios = [];
for (const scenario of SCENARIOS) {
  for (const seed of SEEDS) {
    const timeline = run(
      samplePlan(seed),
      { ...DEFAULT_WORLD, ...scenario.world, seed },
      SAMPLE_START,
    );
    const end = Math.max(...timeline.finished.values());
    let before = new Map<string, string>();
    let planBefore = "";
    let orderBefore = "";
    const days = [];
    for (const frame of timeline.frames) {
      const steps = frame.plan.steps.map(stepJson);
      const changed = steps.filter((step) => before.get(step.id) !== JSON.stringify(step));
      before = new Map(steps.map((step) => [step.id, JSON.stringify(step)]));
      const plan = planJson(frame.plan);
      const planChanged = JSON.stringify(plan) !== planBefore;
      planBefore = JSON.stringify(plan);
      const order = frame.plan.steps.map((step) => step.id);
      const orderChanged = JSON.stringify(order) !== orderBefore;
      orderBefore = JSON.stringify(order);
      const dated = frame.day >= timeline.begin && frame.day <= end && isWorkingDay(frame.day);
      const said = dated ? snapshotOf(frame.plan, frame.day, ADOPTED) : null;
      days.push({
        day: isoDay(frame.day),
        ...(planChanged ? { plan } : {}),
        ...(changed.length ? { steps: changed } : {}),
        ...(orderChanged ? { order } : {}),
        ...(said
          ? {
            forecast: said.stretches.map((stretch) => ({
              key: stretch.key,
              start: iso(stretch.start),
              finish: iso(stretch.finish),
              landings: stretch.landings.map((knot) => [isoDay(knot.day), knot.steps, knot.days]),
            })),
          }
          : {}),
      });
    }
    scenarios.push({ scenario: scenario.id, seed, days });
  }
}
const generated = {
  generator: "docs/exploration/time-estimation-2/tools/export_parity.ts on agent/time-estimation-2",
  model: "ADOPTED: epsilon, carry, replan resume",
  scenarios,
};
const text = JSON.stringify(generated);
if (out.endsWith(".gz")) {
  // Deterministic bytes for a committed fixture: the stream sets no name and no time.
  const packed = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  await Deno.writeFile(out, new Uint8Array(await new Response(packed).arrayBuffer()));
} else {
  await Deno.writeTextFile(out, text);
}
console.log(`${scenarios.length} runs written to ${out}`);
