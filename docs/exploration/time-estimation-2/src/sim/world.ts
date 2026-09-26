/**
 * Reality, simulated: a team works a plan day by day, and things happen to the plan.
 *
 * The executor is deliberately the model's own scheduler run against the *true* effort of
 * each step: the same two pools, the same "longest remaining chain first" priority, the
 * same milestones-in-sequence rule, with time continuous inside a working day. So when the
 * true effort equals the estimate and nothing happens to the plan ("By the book"), whatever
 * gap opens between the forecast and what happens is the model's own doing — rounding, say
 * — and every other scenario breaks exactly one assumption on top of that.
 *
 * Nothing here reads the model's options or the recorder: this is what happened, not what
 * DPlanner wrote down about it (timeline.ts).
 */

import {
  type Day,
  isWorkingDay,
  nextWorkingDay,
  workingDaysAfter,
  workingDaysBetween,
} from "../model/calendar.ts";
import {
  daysFor,
  type Delay,
  DONE,
  efficiencyOf,
  isDelay,
  type Plan,
  type Step,
  stepKey,
  teamOf,
} from "../model/graph.ts";
import { chainTails, groups, stretched } from "../model/simulate.ts";
import { choose, lognormal, type Rng, rng, seedOf } from "./rng.ts";
import { delayId, insertDelay } from "./edits.ts";
import type { Frame, Timeline } from "./timeline.ts";

export interface WorldParams {
  seed: number;
  humanBias: number; // True effort ÷ estimate for human steps, on average.
  agentBias: number;
  noise: number; // Lognormal σ of each step's own luck.
  unestimatedEffort: number; // True days of a step nobody sized.
  focus: number | null; // The focus people really give; null = what the plan assumes.
  agentLoad: number; // Share of a person's day each running agent step takes.
  scopePerWeek: number; // New steps per week, into the stretch being worked.
  reestimateEvery: number; // Working days between re-estimates; 0 = never.
  reestimateFactor: number;
  budgets: BudgetChange[]; // The plan re-budgeted, and the team with it.
  delays: DelayChange[]; // Delay steps added to the plan, which the team then waits for.
  block: { after: number; days: number } | null; // `days` in working days
  workAhead: boolean; // Idle people start the next milestone's ready work.
  dated: boolean; // The plan has a start date stored.
  lead: number; // Days shown before work begins.
  tail: number; // Days shown after the last step lands.
  maxDays: number;
}

export const DEFAULT_WORLD: WorldParams = {
  seed: 7,
  humanBias: 1,
  agentBias: 1,
  noise: 0,
  unestimatedEffort: 1,
  focus: null,
  agentLoad: 0,
  scopePerWeek: 0,
  reestimateEvery: 0,
  reestimateFactor: 1.5,
  budgets: [],
  delays: [],
  block: null,
  workAhead: false,
  dated: true,
  lead: 3,
  tail: 5,
  maxDays: 400,
};

/** A re-budget: from `after` days since work began, this team and (if given) this focus. */
export interface BudgetChange {
  after: number;
  humans: number;
  agents: number;
  efficiency?: number;
}

/** A Delay step added `after` days since work began, before the step `before`. */
export interface DelayChange {
  after: number;
  before: string;
  delay: Delay;
}

const EPSILON = 1e-9;

export function run(start: Plan, params: WorldParams, begin: Day): Timeline {
  const world = new World(start, params, begin);
  return world.play();
}

class World {
  private steps: Step[];
  private plan: Plan;
  private readonly effort = new Map<string, number>();
  private readonly progress = new Map<string, number>();
  private readonly blockedUntil = new Map<string, Day>();
  private readonly finished = new Map<string, Day>();
  // A Delay is a timer, never a worker: when it ends, in working days since work began.
  private readonly waits = new Map<string, number>();
  private readonly over = new Set<string>();
  private humans: (string | null)[];
  private agents: (string | null)[];
  private readonly random: Rng;
  private events: string[] = [];
  private today: Day;

  constructor(start: Plan, private readonly params: WorldParams, private readonly begin: Day) {
    this.steps = start.steps.map((step) => ({ ...step, status: "pending" }));
    this.plan = { ...start, start: params.dated ? begin : null };
    this.today = begin;
    const [humans, agents] = teamOf(start);
    this.humans = Array(humans).fill(null);
    this.agents = Array(agents).fill(null);
    this.random = rng(seedOf(params.seed, "events"));
    // Reality is fixed before anyone re-estimates: a new estimate is learning, not a change.
    for (const step of this.steps) this.effortOf(step);
  }

  play(): Timeline {
    const frames: Frame[] = [];
    let workday = 0;
    let doneOn: Day | null = null;
    for (
      let day = this.begin - this.params.lead;
      day - this.begin <= this.params.maxDays;
      day += 1
    ) {
      this.events = [];
      this.today = day;
      if (day >= this.begin) {
        this.scheduled(day - this.begin, day);
        if (isWorkingDay(day)) {
          workday += 1;
          if (workday > 1) this.changePlan(day, workday);
          this.work(day);
        }
      }
      frames.push({ day, plan: { ...this.plan, steps: [...this.steps] }, events: this.events });
      if (doneOn === null && this.steps.every((step) => isDelay(step) || step.status === DONE)) {
        doneOn = day;
      }
      if (doneOn !== null && day >= doneOn + this.params.tail) break;
    }
    return {
      title: this.plan.title,
      frames,
      begin: this.begin,
      finished: new Map(this.finished),
      kind: "scenario",
    };
  }

  // -- the plan changing under the team ----------------------------------------------------------

  /** A change to a step; one to its status is stamped with the day, as DPlanner would. */
  private update(id: string, patch: Partial<Step>): Step {
    const index = this.steps.findIndex((step) => step.id === id);
    const was = this.steps[index];
    const moved = patch.status !== undefined && patch.status !== was.status;
    const begins = patch.status === "in-progress" && was.started === null;
    this.steps[index] = {
      ...was,
      ...patch,
      ...(moved ? { since: this.today } : {}),
      ...(begins ? { started: this.today } : {}),
    };
    return this.steps[index];
  }

  private scheduled(offset: number, day: Day): void {
    for (const change of this.params.budgets.filter((one) => one.after === offset)) {
      const [was, efficiency] = [
        efficiencyOf(this.plan),
        change.efficiency ?? efficiencyOf(this.plan),
      ];
      this.plan = {
        ...this.plan,
        assumptions: {
          ...this.plan.assumptions,
          team: [change.humans, change.agents],
          efficiency,
          ...(efficiency !== was ? { efficiencyWas: { until: day, efficiency: was } } : {}),
        },
      };
      this.humans = resized(this.humans, change.humans);
      this.agents = resized(this.agents, change.agents);
      this.events.push(
        `the team becomes ${change.humans} ${
          change.humans === 1 ? "person" : "people"
        } + ${change.agents} agent${change.agents === 1 ? "" : "s"}${
          change.efficiency !== undefined ? ` at ${Math.round(change.efficiency * 100)}% focus` : ""
        }`,
      );
    }
    for (const change of this.params.delays.filter((one) => one.after === offset)) {
      const edit = { day, before: change.before, delay: change.delay };
      this.steps = insertDelay(this.steps, edit);
      const added = this.steps.find((step) => step.id === delayId(edit));
      if (added) this.events.push(`${stepKey(added)} ${added.title} added`);
    }
    const block = this.params.block;
    if (block && offset === block.after) {
      const tails = this.tails();
      const running = [...this.humans, ...this.agents].filter((id): id is string => id !== null);
      const critical = running.sort((a, b) => (tails.get(b) ?? 0) - (tails.get(a) ?? 0))[0];
      if (critical) {
        this.release(critical);
        this.blockedUntil.set(critical, workingDaysAfter(day, block.days + 1));
        const step = this.update(critical, { status: "blocked" });
        this.events.push(
          `${stepKey(step)} ${step.title} is blocked for ${block.days} working days`,
        );
      }
    }
    for (const [id, until] of this.blockedUntil) {
      if (until <= day) {
        this.blockedUntil.delete(id);
        const step = this.update(id, { status: this.progress.get(id) ? "in-progress" : "pending" });
        this.events.push(`${stepKey(step)} is unblocked`);
      }
    }
  }

  private changePlan(day: Day, workday: number): void {
    const current = this.currentStretch();
    if (!current) return;
    const [milestone, members] = current;
    if (this.params.scopePerWeek && this.random() < this.params.scopePerWeek / 5) {
      const agent = this.random() < 0.7;
      const id = `added-${this.steps.length + 1}`;
      const work = members.filter((step) => step !== milestone);
      const after = work.length ? choose(this.random, work) : null;
      const step: Step = {
        id,
        number: Math.max(...this.steps.map((one) => one.number)) + 1,
        title: `Added: ${choose(this.random, ["handle", "support", "fix", "cover"])} ${
          choose(this.random, [
            "an edge case",
            "a second format",
            "the empty state",
            "an old import",
            "a review comment",
          ])
        }`,
        requires: after ? [after.id] : [],
        estimate: agent ? choose(this.random, [0.25, 0.5, 1]) : choose(this.random, [1, 2, 3]),
        estimateOff: false,
        estimateHistory: [],
        status: "pending",
        milestone: null,
        agent,
        created: day,
        start: null,
        color: null,
        since: null,
        started: null,
        delay: null,
      };
      this.steps.push(step);
      this.effortOf(step);
      if (milestone) this.update(milestone.id, { requires: [...milestone.requires, id] });
      this.events.push(`${stepKey(step)} added (${step.estimate}d, ${agent ? "agent" : "human"})`);
    }
    if (this.params.reestimateEvery && workday % this.params.reestimateEvery === 0) {
      const waiting = members
        .filter((step) => step.status === "pending" && daysFor(step))
        .sort((a, b) => daysFor(b)! - daysFor(a)!)
        .slice(0, 3);
      for (const step of waiting) {
        const was = step.estimate!;
        const estimate = Math.max(
          0.25,
          Math.round((was * this.params.reestimateFactor) / 0.25) * 0.25,
        );
        if (estimate === was) continue;
        const history = step.estimateHistory.some(([when]) => when === day)
          ? step.estimateHistory
          : [...step.estimateHistory, [day, was] as [Day, number]];
        this.update(step.id, { estimate, estimateHistory: history });
        this.events.push(`${stepKey(step)} re-estimated ${was}d → ${estimate}d`);
      }
    }
  }

  // -- the team working --------------------------------------------------------------------------

  private effortOf(step: Step): number {
    const known = this.effort.get(step.id);
    if (known !== undefined) return known;
    const days = daysFor(step) ?? (step.estimateOff ? 0 : this.params.unestimatedEffort);
    const bias = step.agent ? this.params.agentBias : this.params.humanBias;
    const luck = lognormal(rng(seedOf(this.params.seed, step.id)), this.params.noise);
    const effort = days * bias * luck;
    this.effort.set(step.id, effort);
    return effort;
  }

  private tails(): Map<string, number> {
    const plan = { ...this.plan, steps: this.steps };
    const calendar = stretched(daysFor, efficiencyOf(plan));
    const found = new Map<string, number>();
    for (const [, members] of groups(plan)) {
      for (const [id, tail] of chainTails(members, calendar)) found.set(id, tail);
    }
    return found;
  }

  private currentStretch(): [Step | null, Step[]] | undefined {
    return groups({ ...this.plan, steps: this.steps }).find(([, members]) =>
      members.some((step) => !isDelay(step) && step.status !== DONE)
    );
  }

  private release(id: string): void {
    this.humans = this.humans.map((held) => (held === id ? null : held));
    this.agents = this.agents.map((held) => (held === id ? null : held));
  }

  private work(day: Day): void {
    const plan = { ...this.plan, steps: this.steps };
    const stretches = groups(plan);
    const stretchOf = new Map<string, number>();
    stretches.forEach(([, members], index) =>
      members.forEach((step) => stretchOf.set(step.id, index))
    );
    const opens = stretches.map(([milestone]) => milestone?.start ?? null);
    const tails = this.tails();
    const order = new Map(this.steps.map((step, index) => [step.id, index]));
    const done = (id: string) => this.find(id).status === DONE || this.over.has(id);
    const known = new Set(this.steps.map((step) => step.id));
    // Asked afresh at every moment: a milestone that lands at eleven opens the next one then.
    const current = () =>
      stretches.findIndex(([, members]) =>
        members.some((step) => !isDelay(step) && !done(step.id))
      );
    // Today's first moment, in working days since work began; a delay's clock runs on these.
    const base = workingDaysBetween(this.begin, day) - 1;
    const running = () => new Set([...this.humans, ...this.agents].filter((id) => id !== null));
    const focus = this.params.focus ?? efficiencyOf(plan);

    const eligible = (agent: boolean): Step | undefined => {
      const busy = running();
      const now = current();
      if (now < 0) return undefined;
      return this.steps
        .filter((step) => {
          const stretch = stretchOf.get(step.id)!;
          return !isDelay(step) && step.agent === agent && step.status !== DONE &&
            step.status !== "blocked" &&
            !busy.has(step.id) &&
            (this.params.workAhead || stretch === now) &&
            (opens[stretch] === null || opens[stretch]! <= day) &&
            step.requires.every((id) => !known.has(id) || done(id));
        })
        .sort((a, b) =>
          stretchOf.get(a.id)! - stretchOf.get(b.id)! ||
          tails.get(b.id)! - tails.get(a.id)! || order.get(a.id)! - order.get(b.id)!
        )[0];
    };
    const land = (id: string) => {
      this.release(id);
      this.finished.set(id, day);
      const step = this.update(id, { status: DONE });
      this.events.push(`${stepKey(step)} ${step.title} done`);
    };
    // A delay starts the moment all it requires is done and its stretch is being worked, and
    // ends after its days, or as its day begins. True when one ended, freeing what waits on it.
    const waitFor = (now: number): boolean => {
      let ended = false;
      const stretch = current();
      for (const step of this.steps) {
        if (!step.delay || this.over.has(step.id)) continue;
        if (!this.waits.has(step.id)) {
          const mine = stretchOf.get(step.id);
          if (mine === undefined || (!this.params.workAhead && mine !== stretch)) continue;
          if (!step.requires.every((id) => !known.has(id) || done(id))) continue;
          const delay = step.delay;
          const opens = "days" in delay
            ? now + delay.days
            : workingDaysBetween(this.begin, nextWorkingDay(delay.until)) - 1;
          this.waits.set(step.id, opens);
        }
        if (this.waits.get(step.id)! <= now + EPSILON) {
          this.over.add(step.id);
          this.finished.set(step.id, day);
          ended = true;
        }
      }
      return ended;
    };
    let time = 0;
    const assign = () => {
      for (;;) {
        let moved = waitFor(base + time);
        for (const [lane, agent] of [[this.agents, true], [this.humans, false]] as const) {
          for (let slot = 0; slot < lane.length; slot += 1) {
            if (lane[slot] !== null) continue;
            const step = eligible(agent);
            if (!step) break;
            moved = true;
            if (step.status === "pending") this.update(step.id, { status: "in-progress" });
            if (this.effortOf(step) - (this.progress.get(step.id) ?? 0) <= EPSILON) land(step.id);
            else lane[slot] = step.id;
          }
        }
        if (!moved) return;
      }
    };

    for (let guard = 0; guard < 10_000; guard += 1) {
      assign();
      const busyAgents = this.agents.filter((id) => id !== null).length;
      const human = Math.max(
        0.05,
        focus - (this.params.agentLoad * busyAgents) / Math.max(1, this.humans.length),
      );
      const busy: [string, number][] = [
        ...this.agents.filter((id): id is string => id !== null).map((id) =>
          [id, 1] as [string, number]
        ),
        ...this.humans.filter((id): id is string => id !== null).map((id) =>
          [id, human] as [string, number]
        ),
      ];
      // A delay ending today moves the clock on even when nobody is working.
      const ending = [...this.waits].filter(([id]) => !this.over.has(id)).map(([, end]) =>
        end - base - time
      ).filter((left) => left > EPSILON && left <= 1 - time + EPSILON);
      if ((!busy.length && !ending.length) || time >= 1 - EPSILON) return;
      const step = Math.min(
        1 - time,
        ...ending,
        ...busy.map(([id, rate]) =>
          (this.effortOf(this.find(id)) - (this.progress.get(id) ?? 0)) / rate
        ),
      );
      for (const [id, rate] of busy) {
        this.progress.set(id, (this.progress.get(id) ?? 0) + rate * step);
      }
      time += step;
      for (const [id] of busy) {
        if (this.effortOf(this.find(id)) - this.progress.get(id)! <= EPSILON) land(id);
      }
    }
  }

  private find(id: string): Step {
    return this.steps.find((step) => step.id === id)!;
  }
}

function resized(lane: (string | null)[], size: number): (string | null)[] {
  const kept = [...lane];
  while (kept.length > size) {
    const free = kept.indexOf(null);
    kept.splice(free >= 0 ? free : kept.length - 1, 1);
  }
  while (kept.length < size) kept.push(null);
  return kept;
}
