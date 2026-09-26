/**
 * How good each model's forecasts are, scenario by scenario: error, movement and moves
 * (src/sim/accuracy.ts), summed over a handful of seeds. The table ISSUES.md and LESSONS.md
 * quote comes from here.
 *
 *   deno task accuracy               every scenario
 *   deno task accuracy by-the-book   one
 */

import { ADOPTED, FAITHFUL, type ModelOptions } from "../src/model/options.ts";
import { type Accuracy, combined, timelineAccuracy } from "../src/sim/accuracy.ts";
import { SAMPLE_START, samplePlan } from "../src/sim/sample.ts";
import { scenarioById, SCENARIOS } from "../src/sim/scenarios.ts";
import { DEFAULT_WORLD, run } from "../src/sim/world.ts";

const SEEDS = [1, 2, 3, 7, 11, 42];

const MODES: [string, ModelOptions][] = [
  ["DPlanner today", FAITHFUL],
  ["rounding fixed", { ...ADOPTED, replan: "off" }],
  ["v3: restart", { ...ADOPTED, replan: "restart" }],
  ["v4: resume", ADOPTED],
];

const picked = Deno.args.length ? Deno.args.map(scenarioById) : SCENARIOS;

const cell = (found: Accuracy) =>
  `${found.error.toFixed(1).padStart(5)} ${String(found.movement).padStart(4)} ${
    String(found.moves).padStart(4)
  }`;

console.log(
  "whole-plan landing, per mode: mean |error|, total movement, days moved (working days)",
);
console.log(`seeds ${SEEDS.join(", ")}\n`);
console.log(
  "scenario".padEnd(16) + MODES.map(([name]) => `| ${name.padEnd(15)}`).join(" "),
);
for (const scenario of picked) {
  const results = MODES.map(([, options]) =>
    SEEDS.map((seed) => {
      const timeline = run(
        samplePlan(seed),
        { ...DEFAULT_WORLD, ...scenario.world, seed },
        SAMPLE_START,
      );
      return timelineAccuracy(timeline, options);
    })
  );
  console.log(
    scenario.id.padEnd(16) +
      results.map((perSeed) => `| ${cell(combined(perSeed.map((one) => one.whole)))}`).join(" "),
  );
  console.log(
    "  milestones".padEnd(16) +
      results.map((perSeed) => `| ${cell(combined(perSeed.map((one) => one.milestones)))}`)
        .join(" "),
  );
}
