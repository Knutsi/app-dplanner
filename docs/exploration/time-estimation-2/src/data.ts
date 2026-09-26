/**
 * What crosses a file boundary: the export format `tools/export_plan.ts` writes and the page
 * reads, and a Plan as JSON (ISO dates) inside it.
 *
 * An export is a plan's history as its git commits recorded it: one frame per commit that
 * touched the project, each the plan as the model reads it plus `progress_history` exactly
 * as DPlanner had written it by then.
 */

import { type Day, isoDay, parseDay } from "./model/calendar.ts";
import type { Delay, Plan, Status, Step } from "./model/graph.ts";

export const EXPORT_FORMAT = "te2-export/1";

export interface ExportFrame {
  day: string; // The commit's own calendar day, in the committer's time zone.
  commit: string; // A hash, or "worktree" for uncommitted files.
  time: string;
  plan: PlanJson;
  history: unknown; // progress_history.json as stored, or null.
}

export interface ExportFile {
  format: typeof EXPORT_FORMAT;
  title: string;
  slug: string;
  source: { repo: string; dir: string; exported: string };
  frames: ExportFrame[];
}

export interface StepJson {
  id: string;
  number: number;
  title: string;
  requires: string[];
  estimate: number | null;
  estimateOff: boolean;
  estimateHistory: [string, number][];
  status: Status;
  milestone: string | null;
  agent: boolean;
  created: string | null;
  start: string | null;
  color: string | null;
  since?: string | null; // Absent from exports DPlanner's files cannot fill (BACKPORT.md).
  delay?: DelayJson | null;
}

type DelayJson = { until: string } | { days: number };

export interface PlanJson {
  id: string;
  title: string;
  start: string | null;
  assumptions: Plan["assumptions"];
  steps: StepJson[];
}

const dayOrNull = (value: string | null): Day | null => (value ? parseDay(value) : null);
const isoOrNull = (value: Day | null): string | null => (value !== null ? isoDay(value) : null);

function delayFromJson(json: DelayJson | null | undefined): Delay | null {
  if (!json) return null;
  if ("days" in json) return { days: json.days };
  const until = parseDay(json.until);
  return until === null ? null : { until };
}

const delayToJson = (delay: Delay | null): DelayJson | null =>
  delay === null ? null : "days" in delay ? { days: delay.days } : { until: isoDay(delay.until) };

export function planFromJson(json: PlanJson): Plan {
  return {
    ...json,
    start: dayOrNull(json.start),
    steps: json.steps.map((step): Step => ({
      ...step,
      estimateHistory: step.estimateHistory.flatMap(([day, days]) => {
        const when = parseDay(day);
        return when === null ? [] : [[when, days] as [Day, number]];
      }),
      created: dayOrNull(step.created),
      start: dayOrNull(step.start),
      since: dayOrNull(step.since ?? null),
      delay: delayFromJson(step.delay),
    })),
  };
}

export function planToJson(plan: Plan): PlanJson {
  return {
    ...plan,
    start: isoOrNull(plan.start),
    steps: plan.steps.map((step): StepJson => ({
      ...step,
      estimateHistory: step.estimateHistory.map(([day, days]) => [isoDay(day), days]),
      created: isoOrNull(step.created),
      start: isoOrNull(step.start),
      since: isoOrNull(step.since),
      delay: delayToJson(step.delay),
    })),
  };
}

export function isExport(value: unknown): value is ExportFile {
  return typeof value === "object" && value !== null &&
    (value as ExportFile).format === EXPORT_FORMAT && Array.isArray((value as ExportFile).frames);
}
