/**
 * What the Time tab shows, as data — `time_estimates/module.py`'s `_render`, `_entries` and
 * `_render_progress`, with no widgets. The page draws this; a test can read it.
 *
 * The what-ifs are the tab's controls (focus, team, palette, start, a milestone's begin
 * date). In DPlanner each is a stored write the next record carries; here they act on the
 * scrubbed day's live plan only, so the recorded past stays what the timeline recorded.
 */

import { type Day } from "./model/calendar.ts";
import {
  daysFor,
  DEFAULT_EFFICIENCY,
  efficiencyOf,
  milestoneLabel,
  type Plan,
  startOf,
  type Step,
  stepKey,
  teamOf,
} from "./model/graph.ts";
import type { ModelOptions } from "./model/options.ts";
import { milestoneColors, phaseColors, WHOLE_COLOR } from "./model/palettes.ts";
import {
  actual,
  expected,
  idle,
  landingIn,
  type Pick,
  pickWords,
  type Point,
  remaining,
  resolve,
  shiftWords,
  type Snapshot,
  snapshotFrom,
  spanOf,
  standing,
  type Tally,
  toward,
  volume,
} from "./model/progress.ts";
import {
  calendarDays,
  type Cell,
  cellAt,
  type Phase,
  pushed,
  type TimeReport,
  timeReport,
} from "./model/simulate.ts";
import type { Recording } from "./sim/timeline.ts";

export const ALL_KEY = "*";
export const ALL_LABEL = "All milestones";
export const WHOLE_LABEL = "All work";
export const REMAINDER_LABEL = "Remaining work";

export type Page = "shift" | "progress" | "volume" | "all";

export interface WhatIf {
  efficiency?: number;
  team?: [number, number];
  palette?: string;
  start?: Day;
  begins?: Record<string, Day | null>; // A milestone's own start, by step id.
}

export interface ViewState {
  picked: string | null; // A milestone's step id; null for the whole plan.
  then: Pick;
  now: Pick;
  lens: "calendar" | "project";
  page: Page;
  whatIf: WhatIf;
}

export interface Stretch {
  phase: Phase;
  key: string; // The milestone's id, "" for the remainder.
  label: string;
  color: string;
}

export interface Segment {
  key: string;
  label: string;
  color: string;
  now: [Day, Day] | null;
  then: [Day, Day] | null;
  words: string;
}

export interface ChartData {
  today: Day;
  expected: Point[];
  actual: Point[];
  baseline: Point[];
  basis: string; // The plan compared with, in words; "" when nothing was found.
  asOf: string; // The now side in words, when it is not the live plan.
  finish: Day | null;
  baselineFinish: Day | null;
  idle: [Day, Day][];
  segments: Segment[];
  emphasis: string | null;
  volume: Point[];
  remaining: Point[];
  marks: [Day, string][]; // Saved snapshots: their day and title.
  standing: number | null;
}

export interface Entry {
  key: string; // ALL_KEY, a milestone's id, or "" for the remainder.
  label: string;
  title: string;
  badge: string;
  color: string;
  asked: Day | null; // A date set by hand.
  begins: Day; // The day the sequence gives it.
  finish: Day | null;
  days: number;
  steps: number;
  pushed: Day | null;
  landed: Tally;
  setsProject: boolean;
}

export interface TimeView {
  today: Day;
  plan: Plan;
  report: TimeReport;
  team: [number, number];
  cell: Cell;
  stretches: Stretch[];
  entries: Entry[];
  unestimated: Step[];
  live: Snapshot;
  now: Snapshot;
  then: Snapshot | null;
  chart: ChartData;
  recording: Recording;
  start: Day;
}

export function applyWhatIf(plan: Plan, whatIf: WhatIf, today: Day): Plan {
  const begins = whatIf.begins ?? {};
  const stored = plan.assumptions.efficiency;
  // A what-if focus is a change from tomorrow on: the work in flight ran at the stored one.
  const changed = whatIf.efficiency !== undefined && whatIf.efficiency !== stored;
  return {
    ...plan,
    start: whatIf.start ?? plan.start,
    assumptions: {
      ...plan.assumptions,
      efficiency: whatIf.efficiency ?? stored,
      palette: whatIf.palette ?? plan.assumptions.palette,
      team: whatIf.team ?? plan.assumptions.team,
      ...(changed
        ? { efficiencyWas: { until: today + 1, efficiency: stored ?? DEFAULT_EFFICIENCY } }
        : {}),
    },
    steps: plan.steps.map((
      step,
    ) => (step.id in begins ? { ...step, start: begins[step.id] } : step)),
  };
}

function labelOf(phase: Phase, all: readonly Phase[]): string {
  if (phase.milestone) return milestoneLabel(phase.milestone);
  return all.every((other) => other.milestone === null) ? WHOLE_LABEL : REMAINDER_LABEL;
}

/** Null when there is nothing to date: no steps. A loop still returns, with `report.cycle`. */
export function present(
  stored: Plan,
  today: Day,
  recording: Recording,
  state: ViewState,
  options: ModelOptions,
): TimeView | null {
  const plan = applyWhatIf(stored, state.whatIf, today);
  const start = startOf(plan, today);
  const report = timeReport(plan, daysFor, {
    start,
    today,
    efficiency: efficiencyOf(plan),
    options,
  });
  if (!report) return null;
  const team = teamOf(plan);
  const cell = cellAt(report.calendar, ...team) ?? report.calendar[0];
  const colors = milestoneColors(plan, plan.assumptions.palette);
  const phases = cell?.phases ?? [];
  const shades = phaseColors(phases, colors);
  const stretches: Stretch[] = phases.map((phase, index) => ({
    phase,
    key: phase.milestone ? phase.milestone.id : "",
    label: labelOf(phase, phases),
    color: shades[index],
  }));
  const live = snapshotFrom(phases, today);
  const unestimated = plan.steps.filter((step) => daysFor(step) === null);
  const found = (pick: Pick) => resolve(pick, recording.rows, recording.saved, live, start);
  const now = found(state.now) ?? live;
  const then = found(state.then);
  const basis = pickWords(state.then, then, now.day);
  const asOf = state.now.kind === "now" ? "" : pickWords(state.now, now, live.day);
  const promised = expected(now, null);
  const landed = actual(recording.rows, now, null);
  const picked = stretches.some((one) => one.key && one.key === state.picked) ? state.picked : null;
  const chart: ChartData = {
    today: now.day,
    expected: promised,
    actual: landed,
    baseline: then ? expected(then, null) : [],
    basis,
    asOf,
    finish: landingIn(now, null),
    baselineFinish: then ? landingIn(then, null) : null,
    idle: idle(now, null),
    segments: stretches.map((one) => {
      const [was, is] = [spanOf(then, one.key), spanOf(now, one.key)];
      return {
        key: one.key,
        label: one.label,
        color: one.color,
        now: is,
        then: was,
        words: shiftWords(one.label, was?.[1] ?? null, is?.[1] ?? null, basis, today),
      };
    }),
    emphasis: picked,
    volume: volume(recording.rows, now),
    remaining: remaining(recording.rows, now),
    marks: recording.saved.map((row) => [row.day, row.title]),
    standing: standing(promised, landed, now.day),
  };
  return {
    today,
    plan,
    report,
    team,
    cell,
    stretches,
    entries: entries(stretches, live, cell, start),
    unestimated,
    live,
    now,
    then,
    chart,
    recording,
    start,
  };
}

/** `_entries`: the whole first when there is a milestone, then each stretch in sequence. */
function entries(stretches: Stretch[], live: Snapshot, cell: Cell, start: Day): Entry[] {
  const found: Entry[] = stretches.map(({ phase, key, label, color }) => ({
    key,
    label,
    title: phase.milestone && phase.milestone.title !== label ? phase.milestone.title : "",
    badge: phase.milestone ? stepKey(phase.milestone) : "",
    color,
    asked: phase.asked,
    begins: phase.start,
    finish: phase.finish,
    days: calendarDays(phase),
    steps: phase.steps.length,
    pushed: pushed(phase) ? phase.asked : null,
    landed: toward(live, phase.milestone ? phase.milestone.id : null),
    setsProject: false,
  }));
  if (found.some((entry) => entry.badge)) {
    found.unshift({
      key: ALL_KEY,
      label: ALL_LABEL,
      title: "",
      badge: "",
      color: WHOLE_COLOR,
      asked: start,
      begins: start,
      finish: cell.finish,
      days: cell.days,
      steps: stretches.reduce((sum, one) => sum + one.phase.steps.length, 0),
      pushed: null,
      landed: toward(live, null),
      setsProject: true,
    });
  } else if (found.length) {
    found[0] = { ...found[0], asked: start, begins: start, setsProject: true };
  }
  return found;
}
