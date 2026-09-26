/**
 * What the page changes in the plan, each from the day it is made: a re-budget (the Budget
 * control), and a Delay step inserted (the debugger's *Plan edits*).
 *
 * In DPlanner each is an ordinary write, made today, and the model re-plans from tomorrow —
 * so nothing needs to remember when it was made. The prototype keeps the day only because it
 * replays history when you scrub: a scenario's world makes the change on that day (the team
 * really changes, the team really waits), and a replay's frames carry it from that day on.
 */

import { type Day, isoDay, parseDay, shortDate, weekdayName } from "../model/calendar.ts";
import { type Delay, efficiencyOf, type Plan, type Step, teamOf } from "../model/graph.ts";
import type { Timeline } from "./timeline.ts";
import type { BudgetChange, DelayChange } from "./world.ts";

export interface Budget {
  humans: number;
  agents: number;
  efficiency: number;
}

export interface BudgetEdit extends Budget {
  day: Day;
}

/** A Delay step made on `day`, inserted before the step `before`: that step now waits on it. */
export interface DelayEdit {
  day: Day;
  before: string;
  delay: Delay;
}

export interface Edits {
  budgets: BudgetEdit[]; // By day, one per day.
  delays: DelayEdit[];
}

export const NO_EDITS: Edits = { budgets: [], delays: [] };

export function budgetOf(plan: Plan): Budget {
  const [humans, agents] = teamOf(plan);
  return { humans, agents, efficiency: efficiencyOf(plan) };
}

const sameBudget = (a: Budget, b: Budget) =>
  a.humans === b.humans && a.agents === b.agents && Math.abs(a.efficiency - b.efficiency) < 1e-9;

/**
 * Re-budget on `day`. It replaces any change already made that day; one that leaves the budget
 * as it stood the day before (`before`) is no change at all, and is dropped.
 */
export function rebudget(edits: Edits, day: Day, budget: Budget, before: Budget): Edits {
  const others = edits.budgets.filter((one) => one.day !== day);
  const budgets = sameBudget(budget, before) ? others : [...others, { day, ...budget }];
  return { ...edits, budgets: budgets.sort((a, b) => a.day - b.day) };
}

/** The re-budgets as a scenario's world takes them: in days since work began. */
export function worldBudgets(edits: Edits, begin: Day): BudgetChange[] {
  return edits.budgets.map(({ day, ...budget }) => ({ after: day - begin, ...budget }));
}

/** The delays as a scenario's world takes them: in days since work began. */
export function worldDelays(edits: Edits, begin: Day): DelayChange[] {
  return edits.delays.map(({ day, ...delay }) => ({ after: day - begin, ...delay }));
}

/** A replay with the edits made: each frame from an edit's day on carries it. */
export function edited(timeline: Timeline, edits: Edits): Timeline {
  if (!edits.budgets.length && !edits.delays.length) return timeline;
  return {
    ...timeline,
    frames: timeline.frames.map((frame) => {
      const made = edits.budgets.filter((one) => one.day <= frame.day);
      const budget = made.at(-1);
      const delays = edits.delays.filter((one) => one.day <= frame.day);
      if (!budget && !delays.length) return frame;
      // The focus before the last change of it, for the work in flight across that change.
      const before = [budgetOf(frame.plan), ...made].map((one) => one.efficiency);
      const changed = before.findLastIndex((focus, at) => at > 0 && focus !== before[at - 1]);
      const assumptions = budget
        ? {
          ...frame.plan.assumptions,
          team: [budget.humans, budget.agents] as [number, number],
          efficiency: budget.efficiency,
          ...(changed > 0
            ? { efficiencyWas: { until: made[changed - 1].day, efficiency: before[changed - 1] } }
            : {}),
        }
        : frame.plan.assumptions;
      const steps = delays.reduce((held, edit) => insertDelay(held, edit), frame.plan.steps);
      return { ...frame, plan: { ...frame.plan, assumptions, steps } };
    }),
  };
}

// -- Delay steps ---------------------------------------------------------------------------------

export function waitTitle(delay: Delay): string {
  if ("days" in delay) return `Wait ${delay.days} working day${delay.days === 1 ? "" : "s"}`;
  return `Wait until ${weekdayName(delay.until).slice(0, 3)} ${
    shortDate(delay.until, delay.until)
  }`;
}

/** The id a Delay edit gives its step: one per step held, per day. */
export const delayId = (edit: DelayEdit): string => `wait-${isoDay(edit.day)}-${edit.before}`;

/**
 * The plan with a Delay step inserted before `edit.before`: the delay takes over what that step
 * required, and the step now requires only the delay. A Delay has no estimate and no status.
 * A step already gone, or an edit already made, leaves the plan as it was.
 */
export function insertDelay(steps: readonly Step[], edit: DelayEdit): Step[] {
  const at = steps.findIndex((step) => step.id === edit.before);
  const id = delayId(edit);
  if (at < 0 || steps.some((step) => step.id === id)) return [...steps];
  const held = steps[at];
  const delay: Step = {
    id,
    number: Math.max(...steps.map((step) => step.number)) + 1,
    title: waitTitle(edit.delay),
    requires: held.requires,
    estimate: null,
    estimateOff: true,
    estimateHistory: [],
    status: "pending",
    milestone: null,
    agent: false,
    created: edit.day,
    start: null,
    color: null,
    since: null,
    delay: edit.delay,
  };
  return [...steps.slice(0, at), delay, { ...held, requires: [id] }, ...steps.slice(at + 1)];
}

// -- in the address bar --------------------------------------------------------------------------

/** `2026-11-02:2+1@60;…` — the day, people + agents, and focus in percent. */
export function budgetsToHash(budgets: readonly BudgetEdit[]): string {
  return budgets.map((one) =>
    `${isoDay(one.day)}:${one.humans}+${one.agents}@${Math.round(one.efficiency * 100)}`
  ).join(";");
}

/** `2026-10-12:s14:until:2026-10-21;2026-10-12:s9:days:3` — made on, before, and the wait. */
export function delaysToHash(delays: readonly DelayEdit[]): string {
  return delays.map((one) =>
    `${isoDay(one.day)}:${one.before}:${
      "days" in one.delay ? `days:${one.delay.days}` : `until:${isoDay(one.delay.until)}`
    }`
  ).join(";");
}

export function delaysFromHash(text: string | null): DelayEdit[] {
  return (text ?? "").split(";").flatMap((part): DelayEdit[] => {
    const found = part.match(/^(\d{4}-\d\d-\d\d):([^:;]+):(until|days):([\d.-]+)$/);
    const day = found ? parseDay(found[1]) : null;
    if (!found || day === null) return [];
    if (found[3] === "days") {
      const days = Number(found[4]);
      return days > 0 ? [{ day, before: found[2], delay: { days } }] : [];
    }
    const until = parseDay(found[4]);
    return until === null ? [] : [{ day, before: found[2], delay: { until } }];
  });
}

export function budgetsFromHash(text: string | null): BudgetEdit[] {
  return (text ?? "").split(";").flatMap((part) => {
    // A `+` typed into the address bar arrives as a space.
    const found = part.match(/^(\d{4}-\d\d-\d\d):(\d+)[+ ](\d+)@(\d+)$/);
    const day = found ? parseDay(found[1]) : null;
    if (!found || day === null) return [];
    const [humans, agents, percent] = found.slice(2).map(Number);
    return humans >= 1 && agents >= 1 && percent > 0
      ? [{ day, humans, agents, efficiency: percent / 100 }]
      : [];
  }).sort((a, b) => a.day - b.day);
}
