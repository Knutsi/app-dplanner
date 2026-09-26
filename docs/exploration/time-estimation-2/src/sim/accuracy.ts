/**
 * How good a model's forecasts are over a played timeline, as numbers: the question the
 * saw-tooth in v3 raised ("the date jumps around, even by the book") made measurable.
 *
 * Every working day from the day work began to the day a milestone really landed, the plan
 * as it stood that evening is dated under the model, and its forecast is set against the
 * truth. Three numbers per series, all in working days:
 *
 * - **error**: the mean distance between the forecast and the real landing;
 * - **movement**: how far the forecast travelled in total, day to day;
 * - **moves**: on how many days it moved at all.
 *
 * A forecast that is right and still scores zero on all three.
 */

import { type Day, isWorkingDay } from "../model/calendar.ts";
import { isMilestone } from "../model/graph.ts";
import type { ModelOptions } from "../model/options.ts";
import { landingIn, landingShift } from "../model/progress.ts";
import { snapshotOf, type Timeline } from "./timeline.ts";

export interface Accuracy {
  error: number;
  movement: number;
  moves: number;
  samples: number;
}

export const NO_ACCURACY: Accuracy = { error: 0, movement: 0, moves: 0, samples: 0 };

/** A series' forecast on each working day until its real landing: [day, landing]. */
export function forecastsOf(
  timeline: Timeline,
  options: ModelOptions,
  key: string | null,
  truth: Day,
): [Day, Day][] {
  return timeline.frames.flatMap((frame) => {
    if (frame.day < timeline.begin || frame.day > truth || !isWorkingDay(frame.day)) return [];
    const said = snapshotOf(frame.plan, frame.day, options);
    const landing = said ? landingIn(said, key) : null;
    return landing === null ? [] : [[frame.day, landing] as [Day, Day]];
  });
}

export function accuracyOf(line: readonly [Day, Day][], truth: Day): Accuracy {
  let [error, movement, moves] = [0, 0, 0];
  line.forEach(([, landing], index) => {
    error += Math.abs(landingShift(truth, landing));
    if (index === 0) return;
    const moved = Math.abs(landingShift(line[index - 1][1], landing));
    movement += moved;
    if (moved) moves += 1;
  });
  return { error: line.length ? error / line.length : 0, movement, moves, samples: line.length };
}

/** Sums several series, the error weighted by how many days each was forecast. */
export function combined(parts: readonly Accuracy[]): Accuracy {
  const samples = parts.reduce((sum, part) => sum + part.samples, 0);
  return {
    error: samples ? parts.reduce((sum, part) => sum + part.error * part.samples, 0) / samples : 0,
    movement: parts.reduce((sum, part) => sum + part.movement, 0),
    moves: parts.reduce((sum, part) => sum + part.moves, 0),
    samples,
  };
}

/** The whole plan's landing and every milestone's, over one timeline. */
export function timelineAccuracy(
  timeline: Timeline,
  options: ModelOptions,
): { whole: Accuracy; milestones: Accuracy } {
  const last = timeline.frames[timeline.frames.length - 1].plan;
  const truths = last.steps.map((step) => timeline.finished.get(step.id) ?? null);
  const milestones = last.steps.filter(isMilestone).flatMap((step) => {
    const truth = timeline.finished.get(step.id);
    return truth === undefined
      ? []
      : [accuracyOf(forecastsOf(timeline, options, step.id, truth), truth)];
  });
  const whole = truths.every((day) => day !== null)
    ? (() => {
      const truth = Math.max(...(truths as Day[]));
      return accuracyOf(forecastsOf(timeline, options, null, truth), truth);
    })()
    : NO_ACCURACY;
  return { whole, milestones: combined(milestones) };
}
