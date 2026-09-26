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
  efficiencyOf,
  HUMANS,
  isAgent,
  isDelay,
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
  starts: Map<string, number>; // …and the one it started on.
  tails: Map<string, number>; // Each step's longest remaining chain, itself included.
}

/**
 * `parallel_finish`: greedy list scheduling over two pools. A free slot takes the ready step
 * with the longest remaining chain, ties by position in `steps`. An edge to a step outside
 * `steps` counts as met. Null only when there is nothing to run.
 *
 * `running` names work already in flight: it keeps the worker it has, so it goes first.
 *
 * A Delay step takes no worker: the moment it is ready it waits, and `waits` says until when.
 */
export function parallelFinish(
  steps: readonly Step[],
  daysFor: DaysFor,
  humans: number,
  agents: number,
  running: ReadonlySet<string> = new Set(),
  waits: Waits = plainWaits,
): ParallelFinish | null {
  if (humans < 1 || agents < 1) throw new Error("a pool with work in it needs at least one worker");
  if (!steps.length) return null;
  const order = new Map(steps.map((step, index) => [step.id, index]));
  const byId = new Map(steps.map((step) => [step.id, step]));
  const days = new Map(steps.map((step) => [step.id, costOf(step, daysFor)]));
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
  let busy: [number, string][] = [];
  const landings = new Map<string, number>();
  const starts = new Map<string, number>();
  let now = 0.0;
  const release = (id: string) => {
    const step = byId.get(id)!;
    if (isDelay(step)) {
      starts.set(id, now);
      busy.push([waits(step, now), id]);
    } else {
      ready.get(pool.get(id)!)!.push(id);
    }
  };
  for (const step of steps) {
    if (!waiting.get(step.id)!.size) release(step.id);
  }
  let remaining = steps.length;
  const priority = (a: string, b: string) =>
    Number(running.has(b)) - Number(running.has(a)) || tails.get(b)! - tails.get(a)! ||
    order.get(a)! - order.get(b)!;
  while (remaining) {
    // Python walks `ready.items()` in insertion order: the agent lane (True), then humans.
    for (const lane of [true, false]) {
      const queue = ready.get(lane)!;
      while (queue.length && free.get(lane)!) {
        queue.sort(priority);
        const id = queue.shift()!;
        free.set(lane, free.get(lane)! - 1);
        starts.set(id, now);
        busy.push([now + (days.get(id) ?? 0.0), id]);
      }
    }
    if (!busy.length) break; // A loop a hand-edited file carries.
    now = Math.min(...busy.map(([finish]) => finish));
    const landed = busy.filter(([finish]) => finish <= now);
    busy = busy.filter(([finish]) => finish > now);
    for (const [finish, id] of landed) {
      landings.set(id, finish);
      if (!isDelay(byId.get(id)!)) free.set(pool.get(id)!, free.get(pool.get(id)!)! + 1);
      remaining -= 1;
      for (const after of dependents.get(id)!) {
        const left = waiting.get(after)!;
        left.delete(id);
        if (!left.size) release(after);
      }
    }
  }
  return {
    days: now,
    unestimated: [...days.values()].filter((value) => value === null).length,
    landings,
    starts,
    tails,
  };
}

/** When a Delay made ready at `at` is over, in the same working days as the simulation. */
export type Waits = (step: Step, at: number) => number;

/** A Delay's own working days: a `days` delay's count; an `until` delay's ends by the calendar. */
export function waitDays(step: Step): number {
  return step.delay && "days" in step.delay ? step.delay.days : 0.0;
}

/** Without dates, an `until` delay is over at once; `phases` knows the dates, and does better. */
const plainWaits: Waits = (step, at) => at + waitDays(step);

/** What a step weighs in the simulation: its days, or a Delay's wait — never work. */
function costOf(step: Step, daysFor: DaysFor): number | null {
  return isDelay(step) ? waitDays(step) : daysFor(step);
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
  return tailsOf(steps, new Map(steps.map((step) => [step.id, costOf(step, daysFor)])), dependents);
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
  starts: Map<string, number>;
  lead: number; // Part of the start day already used — always 0 unless `carry` is on.
  guard: number;
  facts: Map<string, Day>; // Re-planned: the day each done step was done, which dates it.
  // When its work began: the first day any of it was done or started, or else its start. A
  // re-planned stretch is dated from tomorrow, but its work may have begun weeks before.
  began: Day;
}

/** `Phase.landing_of`: the date a step lands on; the stretch's start for a weightless one. */
export function landingOf(phase: Phase, id: string): Day {
  const fact = phase.facts.get(id);
  if (fact !== undefined) return fact;
  return dayAt(phase, phase.landings.get(id) ?? 0.0);
}

/**
 * The day a step starts on. Work that starts the moment a day ends starts on that day, as a
 * team picks up the next step when it finishes one — the same rule as a landing's.
 */
export function startDayOf(phase: Phase, id: string): Day {
  return phase.facts.get(id) ?? dayAt(phase, phase.starts.get(id) ?? 0.0);
}

function dayAt(phase: Phase, offset: number): Day {
  const at = phase.lead + offset;
  return at > 0 ? workingDaysAfter(phase.start, at, phase.guard) : phase.start;
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
 *
 * Under `resume` that is the plan while it holds — while everything it has done by today is
 * done, nothing more, and nothing in flight started late — and otherwise the rest of the
 * work re-planned from tomorrow (`resumed`).
 */
export function phases(plan: Plan, daysFor: DaysFor, args: PhaseArgs): Phase[] {
  const options = args.options ?? FAITHFUL;
  if (options.replan !== "resume") return scheduled(plan, daysFor, args, options);
  const planned = scheduled(plan, daysFor, args, options);
  if (holds(planned, args.today)) return planned;
  const pace = options.pace ? paceSoFar(plan, daysFor, args.start, args.today) : null;
  const costs = pace === null || asPlanned(pace) ? daysFor : paced(daysFor, pace);
  return resumed(plan, costs, args, options);
}

/** The evidence a pace needs: working days of work, and steps finished. */
export const PACE_AFTER = 5;
export const PACE_STEPS = 3;
/** A pace this close to the plan's is the plan's: step-sized noise, not a trend. */
const PACE_BAND = 0.1;

export function asPlanned(pace: number): boolean {
  return Math.abs(Math.log(pace)) < Math.log(1 + PACE_BAND);
}

/**
 * The pace so far: the days people's finished steps were given against the working days they
 * took, each from the middle of the day it started to the middle of the day it was done — 1
 * as planned, 0.5 at half the speed. It is the focus measured, so like the focus it is
 * people's alone: an agent's step runs at its estimate. Null before `PACE_AFTER` working days
 * of work and `PACE_STEPS` finished steps. A step blocked on the way counts its stall as
 * slowness.
 */
export function paceSoFar(plan: Plan, daysFor: DaysFor, start: Day, today: Day): number | null {
  if (today < start || workingDaysBetween(start, today) <= PACE_AFTER) return null;
  let [given, took, count] = [0.0, 0.0, 0];
  for (const step of plan.steps) {
    const days = daysFor(step);
    if (days === null || isDelay(step) || isAgent(step) || step.status !== DONE) continue;
    if (step.started === null || step.since === null) continue;
    given += days;
    took += workingDaysBetween(step.started, step.since) - 2 * HALF;
    count += 1;
  }
  return count < PACE_STEPS || took <= 0 ? null : Math.min(4, Math.max(0.25, given / took));
}

/** People's steps at `pace` — slower below 1. An agent's step and a Delay take what they take. */
function paced(daysFor: DaysFor, pace: number): DaysFor {
  return (step) => {
    const days = daysFor(step);
    return days === null || isDelay(step) || isAgent(step) ? days : days / pace;
  };
}

/** When the next stretch may begin, and how much of that day is already used. */
interface Clock {
  when: Day;
  lead: number;
}

function scheduled(plan: Plan, daysFor: DaysFor, args: PhaseArgs, options: ModelOptions): Phase[] {
  const result: Phase[] = [];
  let clock: Clock = { when: args.start, lead: 0.0 };
  let replanned = false;
  for (const [index, [milestone, steps]] of groups(plan).entries()) {
    let costs = daysFor;
    if (options.replan === "restart" && !replanned && steps.some((step) => step.status !== DONE)) {
      // The first stretch with work left: done work costs nothing, and it cannot begin
      // before today. Every later stretch follows it as usual.
      replanned = true;
      if (args.today > clock.when) clock = { when: args.today, lead: 0.0 };
    }
    if (options.replan === "restart" && replanned) {
      costs = (step) => {
        const days = daysFor(step);
        return days !== null && step.status === DONE ? 0.0 : days;
      };
    }
    const [phase, next] = dated(milestone, steps, steps, costs, clock, index === 0, args, options);
    result.push(phase);
    clock = next;
  }
  return result;
}

/**
 * Does reality still match the plan? Each step is done exactly when the plan has it landed
 * by today — on the very day, where that is known, or a plan finished late would hold again
 * once everything is done — nothing in flight started after the day the plan started it, and
 * nothing was planned to start before it existed: a step or a Delay added since. A step
 * nobody marked in progress says nothing about when it started, so it is not held against
 * the plan.
 */
function holds(planned: Phase[], today: Day): boolean {
  return planned.every((phase) =>
    phase.steps.every((step) => {
      if (step.created !== null && startDayOf(phase, step.id) < step.created) return false;
      if (isDelay(step)) return true;
      const lands = landingOf(phase, step.id);
      if ((step.status === DONE) !== (lands <= today)) return false;
      if (step.status === DONE && step.since !== null && step.since !== lands) return false;
      const started = step.status === "in-progress" || step.status === "blocked";
      return !started || step.since === null || step.since <= startDayOf(phase, step.id);
    })
  );
}

/** Half a working day: what is assumed spent on the day work started, and left of late work. */
const HALF = 0.5;

/**
 * The rest of the work from tomorrow. A stretch that is all done is dated by when it was done
 * and holds nothing back. From the first with work left, stretches follow one another from
 * the next working day: done steps are facts, work in flight keeps its worker and is credited
 * with the working days since it started (from the middle of that day; at least half a day
 * is left), a `days` Delay with the days it has already waited, and everything else costs
 * its estimate.
 */
function resumed(plan: Plan, daysFor: DaysFor, args: PhaseArgs, options: ModelOptions): Phase[] {
  const result: Phase[] = [];
  let clock: Clock | null = null;
  const spentSince = (day: Day | null) =>
    day === null || day > args.today ? 0.0 : workingDaysBetween(day, args.today) - HALF;
  // Work in flight, in the working days of today's focus: the days it ran before the focus
  // last changed count at the old one's pace.
  const was = plan.assumptions.efficiencyWas;
  const worked = (step: Step) => {
    const whole = spentSince(step.since);
    if (!was || isAgent(step) || step.since === null || was.until <= step.since) return whole;
    const after = was.until > args.today ? 0.0 : workingDaysBetween(was.until, args.today);
    return (whole - after) * (was.efficiency / efficiencyOf(plan)) + after;
  };
  const byId = new Map(plan.steps.map((step) => [step.id, step]));
  // A `days` delay made after what it waits on was done waited from the start of the day it
  // was made; otherwise from the day the last of that was done, part-way through it.
  const waited = (step: Step) => {
    const before = step.requires.map((id) => byId.get(id)).filter((one) => one !== undefined);
    if (before.some((one) => one.status !== DONE)) return 0.0;
    const done = before.map((one) => one.since).filter((day) => day !== null);
    const last = done.length ? Math.max(...done) : null;
    if (step.created !== null && (last === null || step.created > last)) {
      return step.created > args.today ? 0.0 : workingDaysBetween(step.created, args.today);
    }
    return spentSince(last);
  };
  for (const [milestone, steps] of groups(plan)) {
    const done = steps.filter((step) => step.status === DONE);
    const facts = new Map(done.map((step) => [step.id, step.since ?? args.today]));
    const left = steps.filter((step) => step.status !== DONE);
    if (!left.some((step) => !isDelay(step))) {
      result.push(finished(milestone, steps, facts, args.today, options));
      continue;
    }
    clock ??= { when: nextWorkingDay(args.today + 1), lead: 0.0 };
    const running = new Set(
      left.filter((step) => step.status === "in-progress").map((step) => step.id),
    );
    const costs: DaysFor = (step) => {
      const days = daysFor(step);
      return days === null || !running.has(step.id) ? days : Math.max(HALF, days - worked(step));
    };
    const [phase, next] = dated(milestone, steps, left, costs, clock, false, args, options, {
      running,
      facts,
      waited,
    });
    result.push(phase);
    clock = next;
  }
  return result;
}

/** A stretch whose work is all done: from the first day any of it was done to the last. */
function finished(
  milestone: Step | null,
  steps: Step[],
  facts: Map<string, Day>,
  today: Day,
  options: ModelOptions,
): Phase {
  const days = facts.size ? [...facts.values()] : [today];
  return {
    milestone,
    steps,
    days: 0.0,
    start: Math.min(...days),
    finish: Math.max(...days),
    asked: milestone ? startFor(milestone) : null,
    unestimated: 0,
    landings: new Map(),
    starts: new Map(),
    lead: 0.0,
    guard: guardOf(options),
    facts,
    began: Math.min(...days),
  };
}

/** What a re-planned stretch knows: work in flight, what is done, and how long a delay waited. */
interface Extra {
  running?: ReadonlySet<string>;
  facts?: Map<string, Day>;
  waited?: (step: Step) => number;
}

/** One stretch dated from `clock`, and the clock it leaves for the next. */
function dated(
  milestone: Step | null,
  steps: Step[],
  members: Step[],
  costs: DaysFor,
  clock: Clock,
  first: boolean,
  args: PhaseArgs,
  options: ModelOptions,
  extra: Extra = {},
): [Phase, Clock] {
  const guard = guardOf(options);
  const asked = milestone ? startFor(milestone) : null;
  let begins = asked !== null && (first || asked >= clock.when) ? asked : clock.when;
  let used = begins === clock.when ? clock.lead : 0.0;
  if (nextWorkingDay(begins) !== begins) used = 0.0;
  begins = nextWorkingDay(begins);
  const waits: Waits = (step, at) => {
    const delay = step.delay!;
    if ("days" in delay) return at + Math.max(0.0, delay.days - (extra.waited?.(step) ?? 0.0));
    // Its dependents may start on its day: that day's first moment, from where this began.
    const opens = nextWorkingDay(delay.until);
    const offset = opens <= begins ? 0.0 : workingDaysBetween(begins, opens) - 1 - used;
    return Math.max(at, offset);
  };
  const run = parallelFinish(members, costs, args.humans, args.agents, extra.running, waits)!;
  const finish = run.days > 0 ? workingDaysAfter(begins, used + run.days, guard) : null;
  const started = members.filter((step) => extra.running?.has(step.id)).map((step) => step.since);
  const known = [...(extra.facts?.values() ?? []), ...started].filter((day) => day !== null);
  const phase: Phase = {
    milestone,
    steps,
    days: run.days,
    start: begins,
    finish,
    asked,
    unestimated: run.unestimated,
    landings: run.landings,
    starts: run.starts,
    lead: used,
    guard,
    facts: extra.facts ?? new Map(),
    began: Math.min(begins, ...known),
  };
  if (finish === null) return [phase, { when: begins, lead: used }];
  if (!options.carry) return [phase, { when: nextWorkingDay(finish + 1), lead: 0.0 }];
  // Ending exactly as a day ends still ends on that day: what follows starts then, as a team
  // picks up the next step the moment it finishes one.
  const total = used + run.days;
  const part = total - Math.floor(total + GUARD);
  return [phase, { when: finish, lead: part > GUARD ? part : 1.0 }];
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
  // Project days count work, not dates, so what is done and under way does not re-plan them.
  const raw = phases(plan, daysFor, {
    ...common,
    options: { ...(args.options ?? FAITHFUL), replan: "off" },
  });
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
