/**
 * A real plan's git history as a timeline, and how the port's snapshots compare with the
 * rows DPlanner itself recorded on the same days.
 *
 * The plan on a day is the plan as its last commit that day left it; a day with no commit
 * keeps the day before's. The truth is the first day a step read `done` (and read it from
 * then on) — the nearest thing to a finish date a plan with no status timestamps has.
 */

import { type Day, isoDay, parseDay } from "../model/calendar.ts";
import { DONE, type Plan } from "../model/graph.ts";
import { readRows, rowJson, type Snapshot } from "../model/progress.ts";
import { type ExportFile, planFromJson } from "../data.ts";
import { type Frame, snapshotOf, type Timeline } from "./timeline.ts";

export function replay(file: ExportFile): Timeline {
  const byDay = new Map<Day, (typeof file.frames)[number]>();
  for (const frame of file.frames) {
    const day = parseDay(frame.day);
    if (day !== null) byDay.set(day, frame); // The last commit of the day wins.
  }
  const days = [...byDay.keys()].sort((a, b) => a - b);
  const frames: Frame[] = [];
  const finished = new Map<string, Day>();
  let before: Frame | null = null;
  for (let day = days[0]; day <= days[days.length - 1]; day += 1) {
    const found = byDay.get(day);
    if (!found) {
      frames.push({ ...before!, day, events: [] });
      continue;
    }
    const plan = dated(planFromJson(found.plan), before, day);
    const events = describe(before, plan.steps, found.commit);
    for (const step of plan.steps) {
      const was = before?.plan.steps.find((other) => other.id === step.id);
      if (step.status === DONE && was?.status !== DONE) finished.set(step.id, day);
      if (step.status !== DONE) finished.delete(step.id);
    }
    before = {
      day,
      plan,
      events,
      stored: { rows: readRows(found.history, "days"), saved: readRows(found.history, "saved") },
    };
    frames.push(before);
  }
  const first = frames[0].plan.start ?? frames[0].day;
  return { title: file.title, frames, begin: first, finished, kind: "replay" };
}

/**
 * Each step's `since` and `started` where the files do not say them: the first day of the
 * history on which it read its current status, and on which it was seen going from pending
 * to in progress. Before the first frame nothing is known, so what was already under way
 * then never has a start.
 */
function dated(plan: Plan, before: Frame | null, day: Day): Plan {
  if (!before) return plan;
  const old = new Map(before.plan.steps.map((step) => [step.id, step]));
  return {
    ...plan,
    steps: plan.steps.map((step) => {
      const was = old.get(step.id);
      const going = step.status === "in-progress" || step.status === "blocked";
      return {
        ...step,
        since: step.since ?? (was && was.status === step.status ? was.since : day),
        started: step.started ?? was?.started ??
          (going && was?.status === "pending" ? day : null),
      };
    }),
  };
}

function describe(before: Frame | null, steps: Frame["plan"]["steps"], commit: string): string[] {
  const events = [
    commit === "worktree" ? "uncommitted changes on disk" : `commit ${commit.slice(0, 7)}`,
  ];
  if (!before) return events;
  const old = new Map(before.plan.steps.map((step) => [step.id, step]));
  for (const step of steps) {
    const was = old.get(step.id);
    if (!was) events.push(`S${step.number} ${step.title} added`);
    else if (was.status !== step.status) {
      events.push(`S${step.number} ${was.status} → ${step.status}`);
    } else if (was.estimate !== step.estimate) {
      events.push(`S${step.number} re-estimated ${was.estimate ?? "–"} → ${step.estimate ?? "–"}`);
    }
  }
  const now = new Set(steps.map((step) => step.id));
  for (const step of before.plan.steps) {
    if (!now.has(step.id)) events.push(`S${step.number} removed`);
  }
  return events;
}

export interface Parity {
  day: Day;
  same: boolean;
  differences: string[];
}

/**
 * The port's snapshot of each replayed day beside the row DPlanner stored for that day.
 * Only a day that has both says anything; and the code changed over those weeks, so a
 * difference is a lead to follow, not a verdict on the port.
 */
export function parity(timeline: Timeline): Parity[] {
  const found: Parity[] = [];
  for (const frame of timeline.frames) {
    const stored = frame.stored?.rows.find((row) => row.day === frame.day);
    if (!stored || !frame.events.length) continue;
    const mine = snapshotOf(frame.plan, frame.day);
    if (!mine) continue;
    // Field by field, what DPlanner stores — never what only the port records (`changed`).
    const apart = differences(stored, mine);
    found.push({ day: frame.day, same: !apart.length, differences: apart });
  }
  return found;
}

function differences(stored: Snapshot, mine: Snapshot): string[] {
  const [a, b] = [
    rowJson(stored).stretches as Record<string, unknown>[],
    rowJson(mine).stretches as Record<string, unknown>[],
  ];
  const found: string[] = [];
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    const [x, y] = [a[index], b[index]];
    if (!x || !y) {
      found.push(`stretch ${index + 1}: ${x ? "only DPlanner has it" : "only the port has it"}`);
      continue;
    }
    for (const field of ["milestone", "steps", "done", "days", "done_days", "start", "finish"]) {
      if (JSON.stringify(x[field]) !== JSON.stringify(y[field])) {
        found.push(
          `stretch ${index + 1} ${field}: DPlanner ${JSON.stringify(x[field])}, port ${
            JSON.stringify(y[field])
          }`,
        );
      }
    }
    if (JSON.stringify(x.landings) !== JSON.stringify(y.landings)) {
      found.push(`stretch ${index + 1}: landing knots differ`);
    }
  }
  return found;
}

export function parityWords(results: Parity[]): string {
  if (!results.length) return "no day has both a stored row and a commit to compare";
  const same = results.filter((one) => one.same).length;
  return `${same} of ${results.length} recorded days match DPlanner's own row` +
    (same < results.length
      ? ` (differs on ${
        results.filter((one) => !one.same).map((one) => isoDay(one.day)).join(", ")
      })`
      : "");
}
