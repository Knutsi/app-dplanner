/**
 * A timeline is reality, day by day; a recording is what DPlanner wrote down about it.
 *
 * Keeping the two apart is the point of the prototype. The world (world.ts) or a replayed
 * git history (replay.ts) says what the plan *was* on each day and when each step really
 * finished. The recorder here plays DPlanner's `recorder.py` over those days — on the days
 * the window was open, with whichever model variant is switched on — so the same reality
 * can be recorded two ways and the two forecasts compared against what actually happened.
 */

import { type Day, isWorkingDay, weekday } from "../model/calendar.ts";
import { efficiencyOf, type Plan, startOf, teamOf } from "../model/graph.ts";
import { FAITHFUL, type ModelOptions } from "../model/options.ts";
import { recorded, savedWith, type Snapshot, take } from "../model/progress.ts";
import { rng, seedOf } from "./rng.ts";

export interface Frame {
  day: Day;
  plan: Plan; // The plan as it stood at the end of the day.
  events: string[]; // What happened that day, in words.
  // What DPlanner had actually written by then — a replayed history only.
  stored?: { rows: Snapshot[]; saved: Snapshot[] };
}

export interface Timeline {
  title: string;
  frames: Frame[]; // One per calendar day, in order.
  begin: Day; // The day work began.
  finished: Map<string, Day>; // The day each step really finished — the truth.
  kind: "scenario" | "replay";
}

/** Which days the window was open, so the recorder ran. */
export type Cadence = "weekdays" | "daily" | "twice-weekly" | "sparse" | "stored";

export const CADENCES: { key: Cadence; label: string }[] = [
  { key: "weekdays", label: "every working day" },
  { key: "daily", label: "every day, weekends too" },
  { key: "twice-weekly", label: "Mondays and Thursdays" },
  { key: "sparse", label: "one day in three, at random" },
  { key: "stored", label: "as DPlanner recorded it" },
];

export interface SavedSpec {
  day: Day;
  title: string;
  note: string;
}

export interface RecordSpec {
  options: ModelOptions;
  cadence: Cadence;
  saved: SavedSpec[];
  seed: number;
}

export interface Recording {
  rows: Snapshot[]; // Every automatic row, one per day at most.
  saved: Snapshot[];
}

function recorderRan(cadence: Cadence, day: Day, seed: number): boolean {
  if (cadence === "daily") return true;
  if (cadence === "weekdays") return isWorkingDay(day);
  if (cadence === "twice-weekly") return weekday(day) === 0 || weekday(day) === 3;
  if (cadence === "sparse") {
    return isWorkingDay(day) && rng(seedOf(seed, `record-${day}`))() < 1 / 3;
  }
  return false;
}

/** The plan today as the recorder takes it: the stored team, focus and start. */
export function snapshotOf(
  plan: Plan,
  today: Day,
  options: ModelOptions = FAITHFUL,
): Snapshot | null {
  const [humans, agents] = teamOf(plan);
  return take(plan, {
    humans,
    agents,
    start: startOf(plan, today),
    efficiency: efficiencyOf(plan),
    today,
    options,
  });
}

/** `recorder.py` over a timeline: a row on each day it ran and something had changed. */
export function record(timeline: Timeline, spec: RecordSpec): Recording {
  if (spec.cadence === "stored") {
    const last = timeline.frames[timeline.frames.length - 1]?.stored;
    return { rows: last?.rows ?? [], saved: last?.saved ?? [] };
  }
  let rows: Snapshot[] = [];
  let saved: Snapshot[] = [];
  for (const frame of timeline.frames) {
    const wanted = spec.saved.filter((one) => one.day === frame.day);
    const ran = recorderRan(spec.cadence, frame.day, spec.seed);
    if (!ran && !wanted.length) continue;
    const taken = snapshotOf(frame.plan, frame.day, spec.options);
    if (!taken) continue;
    if (ran) rows = recorded(rows, taken) ?? rows;
    for (const one of wanted) {
      try {
        saved = savedWith(saved, taken, one.title, one.note);
      } catch {
        // A title taken twice keeps the first, as the Save Snapshot dialog would refuse it.
      }
    }
  }
  return { rows, saved };
}

/** What had been recorded by the end of `day` — every row is final once its day is over. */
export function recordedBy(recording: Recording, day: Day): Recording {
  return {
    rows: recording.rows.filter((row) => row.day <= day),
    saved: recording.saved.filter((row) => row.day <= day),
  };
}
