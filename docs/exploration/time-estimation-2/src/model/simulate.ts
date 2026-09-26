/**
 * The simulation — `domain/schedule.py`'s `parallel_finish`, `phases` and `critical_path`,
 * and `time_estimates/schedule.py`'s `stretched`, `cell_for` and `time_report`.
 *
 * Floats and rounding are kept exactly as Python has them (JavaScript numbers are the same
 * IEEE doubles, summed in the same order), so the faithful port reproduces DPlanner's
 * answers to the day — including the day float noise sometimes adds. options.ts holds the
 * variants that change that.
 */

import { type Day, nextWorkingDay, workingDaysAfter, workingDaysBetween } from "./calendar.ts";
import {
  AGENTS,
  cone,
  cyclic,
  type DaysFor,
  DONE,
  HUMANS,
  isAgent,
  isMilestone,
  placed,
  type Plan,
  startFor,
  type Step,
} from "./graph.ts";
import { FAITHFUL, GUARD, guardOf, type ModelOptions } from "./options.ts";

export interface ParallelFinish {
  days: number; // Simulated makespan in working days.
  unestimated: number; // Steps that ran as zero days.
  landings: Map<string, number>; // The working day each step finished on, from the start.
  tails: Map<string, number>; // Each step's longest remaining chain, itself included.
}

/**
 * `parallel_finish`: greedy list scheduling over two pools. A free slot takes the ready step
 * with the longest remaining chain, ties by position in `steps`. An edge to a step outside
 * `steps` counts as met. Null only when there is nothing to run.
 */
export function parallelFinish(
  steps: readonly Step[],
  daysFor: DaysFor,
  humans: number,
  agents: number,
): ParallelFinish | null {
  if (humans < 1 || agents < 1) throw new Error("a pool with work in it needs at least one worker");
  if (!steps.length) return null;
  const order = new Map(steps.map((step, index) => [step.id, index]));
  const days = new Map(steps.map((step) => [step.id, daysFor(step)]));
  const waiting = new Map<string, Set<string>>();
  const dependents = new Map<string, string[]>(steps.map((step) => [step.id, []]));
  for (const step of steps) {
    const requires = new Set(step.requires.filter((target) => order.has(target)));
    waiting.set(step.id, requires);
    for (const target of requires) dependents.get(target)!.push(step.id);
  }
  const tails = tailsOf(steps, days, dependents);

  const free = new Map<boolean, number>([[true, agents], [false, humans]]);
  const pool = new Map(steps.map((step) => [step.id, isAgent(step)]));
  const ready = new Map<boolean, string[]>([[true, []], [false, []]]);
  for (const step of steps) {
    if (!waiting.get(step.id)!.size) ready.get(pool.get(step.id)!)!.push(step.id);
  }
  let running: [number, string][] = [];
  const landings = new Map<string, number>();
  let now = 0.0;
  let remaining = steps.length;
  const priority = (a: string, b: string) =>
    tails.get(b)! - tails.get(a)! || order.get(a)! - order.get(b)!;
  while (remaining) {
    // Python walks `ready.items()` in insertion order: the agent lane (True), then humans.
    for (const lane of [true, false]) {
      const queue = ready.get(lane)!;
      while (queue.length && free.get(lane)!) {
        queue.sort(priority);
        const id = queue.shift()!;
        free.set(lane, free.get(lane)! - 1);
        running.push([now + (days.get(id) ?? 0.0), id]);
      }
    }
    if (!running.length) break; // A loop a hand-edited file carries.
    now = Math.min(...running.map(([finish]) => finish));
    const landed = running.filter(([finish]) => finish <= now);
    running = running.filter(([finish]) => finish > now);
    for (const [finish, id] of landed) {
      landings.set(id, finish);
      free.set(pool.get(id)!, free.get(pool.get(id)!)! + 1);
      remaining -= 1;
      for (const after of dependents.get(id)!) {
        const left = waiting.get(after)!;
        left.delete(id);
        if (!left.size) ready.get(pool.get(after)!)!.push(after);
      }
    }
  }
  return {
    days: now,
    unestimated: [...days.values()].filter((value) => value === null).length,
    landings,
    tails,
  };
}

/** The priority `parallel_finish` schedules `steps` by: each one's longest remaining chain. */
export function chainTails(steps: readonly Step[], daysFor: DaysFor): Map<string, number> {
  const order = new Set(steps.map((step) => step.id));
  const dependents = new Map<string, string[]>(steps.map((step) => [step.id, []]));
  for (const step of steps) {
    for (const target of new Set(step.requires)) {
      if (order.has(target)) dependents.get(target)!.push(step.id);
    }
  }
  return tailsOf(steps, new Map(steps.map((step) => [step.id, daysFor(step)])), dependents);
}

/** `tail_of`: each step's own days plus the longest chain of steps waiting on it. */
function tailsOf(
  steps: readonly Step[],
  days: Map<string, number | null>,
  dependents: Map<string, string[]>,
): Map<string, number> {
  const tails = new Map<string, number>();
  const tailOf = (id: string, seen: Set<string>): number => {
    const known = tails.get(id);
    if (known !== undefined) return known;
    if (seen.has(id)) return 0.0;
    const next = new Set(seen).add(id);
    const ahead = Math.max(0.0, ...dependents.get(id)!.map((after) => tailOf(after, next)));
    const tail = (days.get(id) ?? 0.0) + ahead;
    tails.set(id, tail);
    return tail;
  };
  for (const step of steps) tailOf(step.id, new Set());
  return tails;
}

export interface Phase {
  milestone: Step | null;
  steps: Step[]; // Project order.
  days: number; // Makespan of this stretch alone, in working days.
  start: Day;
  finish: Day | null;
  asked: Day | null;
  unestimated: number;
  landings: Map<string, number>;
  lead: number; // Part of the start day already used — always 0 unless `carry` is on.
  guard: number;
}

/** `Phase.landing_of`: the date a step lands on; the stretch's start for a weightless one. */
export function landingOf(phase: Phase, id: string): Day {
  const offset = phase.landings.get(id) ?? 0.0;
  return offset > 0 ? workingDaysAfter(phase.start, phase.lead + offset, phase.guard) : phase.start;
}

/** `Phase.pushed`: the date asked for could not be kept. */
export function pushed(phase: Phase): boolean {
  return phase.asked !== null && phase.start > nextWorkingDay(phase.asked);
}

/** `Phase.calendar_days`: whole working days from its start to its landing, both counted. */
export function calendarDays(phase: Phase): number {
  return phase.finish !== null ? workingDaysBetween(phase.start, phase.finish) : 0;
}

/** The stretches' membership, before any dating: a milestone's cone truncated at earlier ones. */
export function groups(plan: Plan): [Step | null, Step[]][] {
  const milestones = placed(plan).map((place) => place.step).filter(isMilestone);
  const taken = new Set<string>();
  const found: [Step | null, Step[]][] = [];
  for (const closing of milestones) {
    const reached = cone(plan, closing.id, isMilestone).steps;
    const own = new Set(reached.map((step) => step.id).filter((id) => !taken.has(id)));
    own.add(closing.id);
    for (const id of own) taken.add(id);
    found.push([closing, plan.steps.filter((step) => own.has(step.id))]);
  }
  const rest = plan.steps.filter((step) => !taken.has(step.id));
  if (rest.length) found.push([null, rest]);
  return found;
}

export interface PhaseArgs {
  humans: number;
  agents: number;
  start: Day;
  today: Day;
  options?: ModelOptions;
}

/**
 * `phases`: the milestones in sequence, each stretch simulated on its own and dated from the
 * working day after the previous one lands — or from its own later start date.
 */
export function phases(plan: Plan, daysFor: DaysFor, args: PhaseArgs): Phase[] {
  const options = args.options ?? FAITHFUL;
  const guard = guardOf(options);
  const result: Phase[] = [];
  let when = args.start; // The earliest the next stretch may begin.
  let lead = 0.0; // With `carry`: how much of `when` the previous stretch already used.
  let replanned = false;
  for (const [index, [milestone, steps]] of groups(plan).entries()) {
    let costs = daysFor;
    if (options.replan && !replanned && steps.some((step) => step.status !== DONE)) {
      // The first stretch with work left: done work costs nothing, and it cannot begin
      // before today. Every later stretch follows it as usual.
      replanned = true;
      if (args.today > when) [when, lead] = [args.today, 0.0];
    }
    if (options.replan && replanned) {
      costs = (step) => {
        const days = daysFor(step);
        return days !== null && step.status === DONE ? 0.0 : days;
      };
    }
    const asked = milestone ? startFor(milestone) : null;
    let begins = asked !== null && (index === 0 || asked >= when) ? asked : when;
    let used = begins === when ? lead : 0.0;
    if (nextWorkingDay(begins) !== begins) used = 0.0;
    begins = nextWorkingDay(begins);
    const run = parallelFinish(steps, costs, args.humans, args.agents)!;
    const finish = run.days > 0 ? workingDaysAfter(begins, used + run.days, guard) : null;
    result.push({
      milestone,
      steps,
      days: run.days,
      start: begins,
      finish,
      asked,
      unestimated: run.unestimated,
      landings: run.landings,
      lead: used,
      guard,
    });
    if (finish === null) {
      [when, lead] = [begins, used];
    } else if (options.carry) {
      const total = used + run.days;
      const part = total - Math.floor(total + GUARD);
      [when, lead] = part > GUARD ? [finish, part] : [nextWorkingDay(finish + 1), 0.0];
    } else {
      [when, lead] = [nextWorkingDay(finish + 1), 0.0];
    }
  }
  return result;
}

/** `stretched`: human steps' days divided by the focus factor; agent steps untouched. */
export function stretched(daysFor: DaysFor, efficiency: number): DaysFor {
  return (step) => {
    const days = daysFor(step);
    if (days === null || isAgent(step)) return days;
    return days / efficiency;
  };
}

export interface CriticalPath {
  days: number;
  steps: Step[];
  unestimated: number;
}

/** `critical_path`: the longest days-weighted chain, ties to the earliest in project order. */
export function criticalPath(plan: Plan, daysFor: DaysFor): CriticalPath | null {
  if (!plan.steps.length) return null;
  const order = new Map(plan.steps.map((step, index) => [step.id, index]));
  const index = new Map(plan.steps.map((step) => [step.id, step]));
  const finishes = new Map<string, number>();
  const towards = new Map<string, string | null>();
  const finishOf = (id: string, seen: Set<string>): number => {
    const known = finishes.get(id);
    if (known !== undefined) return known;
    if (seen.has(id)) return 0.0;
    const step = index.get(id)!;
    const own = daysFor(step) ?? 0.0;
    const resolved = step.requires
      .filter((target) => order.has(target))
      .sort((a, b) => order.get(a)! - order.get(b)!);
    let best: string | null = null;
    let upstream = 0.0;
    const next = new Set(seen).add(id);
    for (const target of resolved) {
      const candidate = finishOf(target, next);
      if (candidate > upstream) [upstream, best] = [candidate, target];
    }
    finishes.set(id, own + upstream);
    towards.set(id, best);
    return own + upstream;
  };
  for (const step of plan.steps) finishOf(step.id, new Set());
  let last = plan.steps[0];
  for (const step of plan.steps) {
    if (finishes.get(step.id)! > finishes.get(last.id)!) last = step;
  }
  const chain: Step[] = [];
  for (let at: string | null = last.id; at !== null; at = towards.get(at) ?? null) {
    chain.push(index.get(at)!);
  }
  chain.reverse();
  return {
    days: finishes.get(last.id)!,
    steps: chain,
    unestimated: chain.filter((step) => daysFor(step) === null).length,
  };
}

// -- the staffing matrix ------------------------------------------------------------------------

export interface Cell {
  humans: number;
  agents: number;
  days: number;
  finish: Day | null;
  phases: Phase[];
}

export interface TimeReport {
  start: Day;
  efficiency: number;
  humanDays: number;
  agentDays: number;
  unestimated: number;
  hasAgentSteps: boolean;
  floor: number;
  calendarFloor: number;
  parallel: Cell[];
  calendar: Cell[];
  cycle: Step[];
}

export interface ReportArgs {
  start: Day;
  today: Day;
  efficiency: number;
  options?: ModelOptions;
}

/** `cell_for`: one staffing, both lenses — project days and calendar days. */
export function cellFor(
  plan: Plan,
  daysFor: DaysFor,
  humans: number,
  agents: number,
  args: ReportArgs,
): [Cell, Cell] {
  const common = { humans, agents, start: args.start, today: args.today, options: args.options };
  const raw = phases(plan, daysFor, common);
  const slow = phases(plan, stretched(daysFor, args.efficiency), common);
  const landing = [...slow].reverse().find((phase) => phase.finish !== null)?.finish ?? null;
  return [
    {
      humans,
      agents,
      days: raw.reduce((sum, phase) => sum + phase.days, 0),
      finish: null,
      phases: raw,
    },
    {
      humans,
      agents,
      days: landing !== null ? workingDaysBetween(slow[0].start, landing) : 0.0,
      finish: landing,
      phases: slow,
    },
  ];
}

/** `time_report`: the whole matrix over HUMANS × AGENTS. Null for a project with no steps. */
export function timeReport(plan: Plan, daysFor: DaysFor, args: ReportArgs): TimeReport | null {
  if (!plan.steps.length) return null;
  let humanDays = 0;
  let agentDays = 0;
  for (const step of plan.steps) {
    if (isAgent(step)) agentDays += daysFor(step) ?? 0.0;
    else humanDays += daysFor(step) ?? 0.0;
  }
  const hasAgentSteps = plan.steps.some(isAgent);
  const loop = cyclic(plan);
  const base = {
    start: args.start,
    efficiency: args.efficiency,
    humanDays,
    agentDays,
    hasAgentSteps,
  };
  if (loop.length) {
    return {
      ...base,
      unestimated: plan.steps.filter((step) => daysFor(step) === null).length,
      floor: 0,
      calendarFloor: 0,
      parallel: [],
      calendar: [],
      cycle: loop,
    };
  }
  const path = criticalPath(plan, daysFor);
  const calendarPath = criticalPath(plan, stretched(daysFor, args.efficiency));
  const parallel: Cell[] = [];
  const calendar: Cell[] = [];
  for (const humans of HUMANS) {
    for (const agents of AGENTS) {
      const [raw, slow] = cellFor(plan, daysFor, humans, agents, args);
      parallel.push(raw);
      calendar.push(slow);
    }
  }
  return {
    ...base,
    start: calendar[0].phases[0].start,
    unestimated: calendar[0].phases.reduce((sum, phase) => sum + phase.unestimated, 0),
    floor: path ? path.days : 0,
    calendarFloor: calendarPath ? Math.ceil(calendarPath.days - 1e-9) : 0,
    parallel,
    calendar,
    cycle: [],
  };
}

export function cellAt(cells: Cell[], humans: number, agents: number): Cell | undefined {
  return cells.find((cell) => cell.humans === humans && cell.agents === agents);
}
