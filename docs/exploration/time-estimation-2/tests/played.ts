/**
 * The Time tab's data as a view reads it: for a plan on a day, or a scenario played out —
 * under the model the page runs unless a test names another.
 */

import type { Day } from "../src/model/calendar.ts";
import type { Plan } from "../src/model/graph.ts";
import { ADOPTED, type ModelOptions } from "../src/model/options.ts";
import { AT_START } from "../src/model/progress.ts";
import { present, type TimeView } from "../src/present.ts";
import { SAMPLE_START, samplePlan } from "../src/sim/sample.ts";
import { scenarioById } from "../src/sim/scenarios.ts";
import { record, recordedBy, type Recording } from "../src/sim/timeline.ts";
import { DEFAULT_WORLD, run } from "../src/sim/world.ts";

/** The Time tab's data for a plan on a day, compared with the plan at start. */
export function viewOf(
  plan: Plan,
  day: Day,
  recording: Recording,
  options: ModelOptions = ADOPTED,
): TimeView {
  const state = {
    picked: null,
    then: AT_START,
    now: { kind: "now" as const },
    lens: "calendar" as const,
    page: "progress" as const,
    whatIf: {},
  };
  return present(plan, day, recordedBy(recording, day), state, options)!;
}

/** A scenario played on the sample plan (seed 1), read as the view reads it on a day. */
export function played(id: string, options: ModelOptions = ADOPTED) {
  const scenario = scenarioById(id);
  const timeline = run(
    samplePlan(1),
    { ...DEFAULT_WORLD, ...scenario.world, seed: 1 },
    SAMPLE_START,
  );
  const recording = record(timeline, {
    options,
    cadence: scenario.cadence ?? "weekdays",
    saved: [],
    seed: 1,
  });
  return {
    timeline,
    viewOn: (day: Day) =>
      viewOf(timeline.frames.find((one) => one.day === day)!.plan, day, recording, options),
  };
}
