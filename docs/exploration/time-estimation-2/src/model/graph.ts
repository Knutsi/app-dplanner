/**
 * The plan as the time model sees it, and the walks over its graph — `domain/ordering.py`
 * and `domain/scope.py`'s `cone`.
 *
 * DPlanner hands its derivations functions (`days_for`, `is_agent`, `status_for`…) wired by
 * the composition root from each module's aspect. This prototype has no aspects, so a `Step`
 * carries exactly the facts those functions read, and the functions below are the wiring.
 * `tools/export_plan.ts` says which file each field comes from.
 */

import type { Day } from "./calendar.ts";

export type Status = "pending" | "in-progress" | "done" | "blocked";
export const DONE: Status = "done";

export interface Step {
  id: string;
  number: number; // "S12" is its key.
  title: string;
  requires: string[]; // The steps this one waits on.
  estimate: number | null; // estimation.days; null when nobody sized it.
  estimateOff: boolean; // estimation {"off": true}: milestone, feature and check steps.
  // estimation.history: the value that stood when each day of a change began.
  estimateHistory: [Day, number][];
  status: Status;
  milestone: string | null; // step_milestone.label
  agent: boolean; // step_agent_instruction on, or its .md present.
  created: Day | null;
  start: Day | null; // time_estimates.start on a milestone: when its stretch begins.
  color: string | null; // time_estimates.color on a milestone.
  // The day its status last changed — a fact DPlanner does not store yet (BACKPORT.md).
  since: Day | null;
  started: Day | null; // The day it first went in progress: what the pace so far is read from.
  delay: Delay | null; // A Delay step: a wait, with no work and no status of its own.
}

/** What a Delay step waits for: a day its dependents may start on, or n working days. */
export type Delay = { until: Day } | { days: number };

export interface Assumptions {
  efficiency: number | null; // The focus factor; 0.5 when absent.
  palette: string | null;
  team: [number, number] | null; // [people, agents]; [1, 1] when absent.
  // The focus before it last changed, and the day the new one began: work in flight across
  // the change ran at the old one (BACKPORT.md).
  efficiencyWas?: { until: Day; efficiency: number } | null;
}

export interface Plan {
  id: string;
  title: string;
  start: Day | null; // estimation.start on the project; today when absent.
  assumptions: Assumptions;
  steps: Step[]; // Project order.
}

export const DEFAULT_EFFICIENCY = 0.5;
export const DEFAULT_TEAM: [number, number] = [1, 1];
export const HUMANS = [1, 2, 3];
export const AGENTS = [1, 2, 3, 4];

// -- the predicates the composition root wires -------------------------------------------------

export type DaysFor = (step: Step) => number | null;
export type StepTest = (step: Step) => boolean;

/** `estimation/aspect.py`'s `read`: None for an absent, unreadable *or opted-out* entry. */
export const daysFor: DaysFor = (step) => (step.estimateOff ? null : step.estimate);
export const isAgent: StepTest = (step) => step.agent;
export const isMilestone: StepTest = (step) => Boolean(step.milestone);
export const isDelay: StepTest = (step) => step.delay !== null;
/**
 * A step that carries no work by design — a milestone, feature or check step, estimate off.
 * Its own status is no fact about the schedule: people rarely mark a milestone step done on
 * the day its work lands, so a model that waited for the mark would slide it every day.
 */
export const isMarker: StepTest = (step) => step.estimateOff && !isDelay(step);
export const statusFor = (step: Step): Status => step.status;
export const startFor = (step: Step): Day | null => step.start;

export function efficiencyOf(plan: Plan): number {
  return plan.assumptions.efficiency ?? DEFAULT_EFFICIENCY;
}

export function teamOf(plan: Plan): [number, number] {
  return plan.assumptions.team ?? DEFAULT_TEAM;
}

/** `estimation/schedule.py`'s `start_of`: the stored start, or today. */
export function startOf(plan: Plan, today: Day): Day {
  return plan.start ?? today;
}

export function stepKey(step: Step): string {
  return `S${step.number}`;
}

export function milestoneLabel(step: Step): string {
  return step.milestone || step.title;
}

// -- ordering.py -------------------------------------------------------------------------------

function idsOf(steps: readonly Step[]): Set<string> {
  return new Set(steps.map((step) => step.id));
}

export function byId(plan: Plan): Map<string, Step> {
  return new Map(plan.steps.map((step) => [step.id, step]));
}

/** `depths`: how many `requires` edges deep each step is. */
export function depths(plan: Plan): Map<string, number> {
  const known = new Map<string, number>();
  const index = byId(plan);
  const depthOf = (id: string, seen: Set<string>): number => {
    const found = known.get(id);
    if (found !== undefined) return found;
    if (seen.has(id)) return 0;
    const resolved = (index.get(id)?.requires ?? []).filter((target) => index.has(target));
    const next = new Set(seen).add(id);
    const depth = resolved.length
      ? 1 + Math.max(...resolved.map((target) => depthOf(target, next)))
      : 0;
    known.set(id, depth);
    return depth;
  };
  for (const step of plan.steps) depthOf(step.id, new Set());
  return known;
}

/** `cyclic`: the steps on or behind a loop a hand-edited file carries — Kahn's peeling. */
export function cyclic(plan: Plan): Step[] {
  const ids = idsOf(plan.steps);
  const pending = new Map(
    plan.steps.map((step) => [step.id, new Set(step.requires.filter((t) => ids.has(t)))]),
  );
  let shed = true;
  while (shed) {
    shed = false;
    for (const [id, waiting] of [...pending]) {
      if (!waiting.size) {
        pending.delete(id);
        for (const others of pending.values()) others.delete(id);
        shed = true;
      }
    }
  }
  return plan.steps.filter((step) => pending.has(step.id));
}

/** `waves`: the steps grouped by depth, project order inside each. */
export function waves(plan: Plan): Step[][] {
  if (!plan.steps.length) return [];
  const byDepth = depths(plan);
  const grouped: Step[][] = Array.from(
    { length: Math.max(0, ...byDepth.values()) + 1 },
    () => [],
  );
  for (const step of plan.steps) grouped[byDepth.get(step.id) ?? 0].push(step);
  return grouped;
}

export interface Placed {
  index: number; // 1-based topological index.
  wave: number; // 1-based.
  step: Step;
}

/** `placed`: every step in order with its index and wave — the order milestones run in. */
export function placed(plan: Plan): Placed[] {
  const result: Placed[] = [];
  waves(plan).forEach((wave, number) => {
    for (const step of wave) result.push({ index: result.length + 1, wave: number + 1, step });
  });
  return result;
}

// -- scope.py ----------------------------------------------------------------------------------

export interface Cone {
  steps: Step[]; // Excludes the origin and the boundaries; project order.
  boundaries: Step[];
}

/** `cone`: the steps behind `stepId`, never walking through one `stopsAt` claims. */
export function cone(plan: Plan, stepId: string, stopsAt?: StepTest): Cone {
  const index = byId(plan);
  const reached = new Set<string>();
  const stopped = new Set<string>();
  const visit = (current: string): void => {
    for (const targetId of index.get(current)?.requires ?? []) {
      const target = index.get(targetId);
      if (!target || reached.has(targetId) || stopped.has(targetId)) continue;
      if (stopsAt && stopsAt(target)) {
        stopped.add(targetId);
        continue;
      }
      reached.add(targetId);
      visit(targetId);
    }
  };
  visit(stepId);
  return {
    steps: plan.steps.filter((step) => reached.has(step.id)),
    boundaries: plan.steps.filter((step) => stopped.has(step.id)),
  };
}
