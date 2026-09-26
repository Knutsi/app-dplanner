/**
 * What v2 tells a reader first, as data: for the whole plan and for each milestone, when it
 * will land at today's pace, how that moved against the plan it is compared with and why,
 * and a verdict — from nothing DPlanner does not already store (the plan now, and the
 * `progress_history` rows).
 *
 * Two derived numbers carry it, both measured without interpolation and in days of work:
 *
 * - **Lag** — the plan now promises each step's work done by its landing day (the landing
 *   knots, a step function). The first knot whose work is not yet done is what is *due*; if
 *   its day has passed, the plan is that many working days behind itself. A step in flight
 *   on schedule is never "behind" (ISSUES.md P1), and scope changes cannot flatter or
 *   darken a share (P2), because nothing here is a share.
 * - **Projected landing** — the plan's own landing moved on by the lag: the date the rest
 *   lands if it goes to plan from here. DPlanner's date never moves when work runs late
 *   (F1); this one does.
 *
 * Dates, lag and verdicts read *through* a milestone — everything up to and including it —
 * because milestones run in sequence and each inherits the delay of those before it. What a
 * milestone is made of (the burn-up, the change list) reads its *own* stretch, so its own
 * scope stays legible.
 */

import { addWorkingDays, type Day, nextWorkingDay } from "./model/calendar.ts";
import type { Plan, Step } from "./model/graph.ts";
import { WHOLE_COLOR } from "./model/palettes.ts";
import {
  changesSince,
  EMPTY_TALLY,
  has,
  landingIn,
  landingShift,
  type Snapshot,
  type Stretch,
  type Tally,
  through,
  toward,
  until,
} from "./model/progress.ts";
import type { TimeView } from "./present.ts";

const EPSILON = 1e-9;

/** How far a projected landing may move before it is called later or earlier: working days. */
export const NOTICEABLE = 2;

export type VerdictKind =
  | "landed"
  | "overdue"
  | "later"
  | "earlier"
  | "on-track"
  | "no-baseline"
  | "new";

export interface Pace {
  done: number; // Days of work done, through the scope.
  promised: number; // Days the plan now promised done by today — a step, never interpolated.
  short: number; // promised − done, when positive.
  earned: Day | null; // The day the plan now had the done work due by.
  due: Day | null; // The earliest planned landing whose work is not yet done.
  lag: number; // Working days `due` has been overdue; 0 when nothing due is undone.
}

export interface Move {
  then: Day | null; // Where the plan compared with landed the scope.
  planned: Day | null; // Where the plan now lands it.
  projected: Day | null; // Where it lands at today's pace.
  plan: number | null; // Working days the plan itself moved: planned against then.
  pace: number; // Working days today's pace adds: the lag.
  total: number | null; // projected against then.
}

export interface Scope {
  key: string | null; // null for all work; "" for the work after the last milestone.
  label: string;
  title: string;
  badge: string;
  color: string;
  own: Tally; // The stretch's own work now (everything, for all work).
  thenOwn: Tally | null; // The same in the plan compared with.
  span: [Day, Day | null] | null; // The own stretch now: start, planned landing.
  thenSpan: [Day, Day | null] | null;
  pace: Pace;
  move: Move;
  verdict: VerdictKind;
  landedBy: Day | null; // The first recorded day it read done.
}

export interface Brief {
  today: Day;
  compared: boolean; // Whether there is an earlier plan to compare with at all.
  whole: Scope;
  milestones: Scope[]; // In sequence; includes the work after the last milestone.
  attention: Attention | null; // The one milestone most in need of a look, if any.
}

export interface Attention {
  scope: Scope;
  kind: "overdue" | "origin"; // Overdue, or where most of the move is added.
  days: number; // For an origin: working days its own stretch adds to the move.
  plan: number; // …of which from changes to the plan,
  pace: number; // …and from today's pace.
}

// -- pace --------------------------------------------------------------------------------------

/** The days a snapshot's stretches promise done by each landing day, cumulative. */
export function promisedCurve(stretches: readonly Stretch[]): [Day, number][] {
  const byDay = new Map<Day, number>();
  for (const stretch of stretches) {
    for (const knot of stretch.landings) {
      byDay.set(knot.day, (byDay.get(knot.day) ?? 0) + knot.days);
    }
  }
  let running = 0;
  return [...byDay.keys()].sort((a, b) => a - b).map((day) => [day, running += byDay.get(day)!]);
}

export function paceOf(live: Snapshot, key: string | null, today: Day): Pace {
  const knots = promisedCurve(through(live, key));
  const done = toward(live, key).doneDays;
  let earned: Day | null = null;
  let due: Day | null = null;
  let promised = 0;
  for (const [day, cumulative] of knots) {
    if (day <= today) promised = cumulative;
    if (due === null && cumulative <= done + EPSILON) earned = day;
    else if (due === null) due = day;
  }
  return {
    done,
    promised,
    short: Math.max(0, promised - done),
    earned,
    due,
    // Work still undone can be done today at the soonest, or on Monday if today is a weekend.
    lag: due !== null && due < today ? landingShift(due, nextWorkingDay(today)) : 0,
  };
}

// -- one scope -----------------------------------------------------------------------------------

function ownTally(snapshot: Snapshot, key: string | null): Tally | null {
  if (key === null) return toward(snapshot, null);
  return snapshot.stretches.find((stretch) => stretch.key === key)?.tally ?? null;
}

function ownSpan(snapshot: Snapshot, key: string | null): [Day, Day | null] | null {
  if (!snapshot.stretches.length) return null;
  if (key === null) return [snapshot.stretches[0].start, landingIn(snapshot, null)];
  const stretch = snapshot.stretches.find((one) => one.key === key);
  return stretch ? [stretch.start, stretch.finish] : null;
}

function landedBy(rows: readonly Snapshot[], live: Snapshot, key: string | null): Day | null {
  const landed = (row: Snapshot) => {
    const reached = toward(row, key);
    return has(row, key) && reached.steps > 0 && reached.done === reached.steps;
  };
  if (!landed(live)) return null;
  return until(rows, live).find(landed)?.day ?? live.day;
}

function verdictOf(
  scope: Omit<Scope, "verdict">,
  compared: boolean,
  then: Snapshot | null,
  today: Day,
): VerdictKind {
  if (scope.landedBy !== null) return "landed";
  if (scope.move.planned !== null && scope.move.planned < today) return "overdue";
  if (!compared) return "no-baseline";
  if (then && !has(then, scope.key)) return "new";
  const total = scope.move.total;
  if (total !== null && total >= NOTICEABLE) return "later";
  if (total !== null && total <= -NOTICEABLE) return "earlier";
  return "on-track";
}

function scopeOf(
  view: TimeView,
  key: string | null,
  labels: { label: string; title: string; badge: string; color: string },
  compared: boolean,
): Scope {
  // The day shown: today, or a day in the history — everything reads the plan as it stood.
  const { now, then } = view;
  const today = now.day;
  const pace = paceOf(now, key, today);
  const planned = landingIn(now, key);
  const landed = landedBy(view.recording.rows, now, key);
  const projected = landed !== null || planned === null ? null : addWorkingDays(planned, pace.lag);
  const was = compared && then ? landingIn(then, key) : null;
  const move: Move = {
    then: was,
    planned,
    projected,
    plan: was !== null && planned !== null ? landingShift(was, planned) : null,
    pace: pace.lag,
    total: was !== null && projected !== null ? landingShift(was, projected) : null,
  };
  const partial = {
    key,
    ...labels,
    own: ownTally(now, key) ?? EMPTY_TALLY,
    thenOwn: compared && then ? ownTally(then, key) : null,
    span: ownSpan(now, key),
    thenSpan: compared && then ? ownSpan(then, key) : null,
    pace,
    move,
    landedBy: landed,
  };
  return { ...partial, verdict: verdictOf(partial, compared, then, today) };
}

/**
 * Which milestone most needs a look. An overdue one first — the earliest. Otherwise the one
 * whose *own* stretch adds the most to the move: every later milestone inherits the delay of
 * those before it, so pointing at the last one says nothing, while the stretch where the
 * working days were added is where somebody can act.
 */
function attentionOf(milestones: Scope[]): Attention | null {
  const overdue = milestones.filter((scope) => scope.verdict === "overdue")
    .sort((a, b) => a.move.planned! - b.move.planned!);
  if (overdue.length) return { scope: overdue[0], kind: "overdue", days: 0, plan: 0, pace: 0 };
  let best: Attention | null = null;
  let before: Move = { then: null, planned: null, projected: null, plan: 0, pace: 0, total: 0 };
  for (const scope of milestones) {
    const move = scope.move;
    if (move.total === null) continue;
    const days = move.total - (before.total ?? 0);
    if (days >= NOTICEABLE && (!best || days > best.days)) {
      best = {
        scope,
        kind: "origin",
        days,
        plan: (move.plan ?? 0) - (before.plan ?? 0),
        pace: move.pace - before.pace,
      };
    }
    before = move;
  }
  return best;
}

export function brief(view: TimeView): Brief {
  const compared = view.then !== null && view.then.day !== view.now.day;
  const whole = scopeOf(
    view,
    null,
    { label: "All work", title: "", badge: "", color: WHOLE_COLOR },
    compared,
  );
  const milestones = view.stretches.map(({ phase, key, label, color }) =>
    scopeOf(view, key, {
      label,
      title: phase.milestone && phase.milestone.title !== label ? phase.milestone.title : "",
      badge: phase.milestone ? `S${phase.milestone.number}` : "",
      color,
    }, compared)
  );
  return {
    today: view.now.day,
    compared,
    whole,
    milestones,
    attention: attentionOf(milestones),
  };
}

// -- the burn-up: a scope's own work over the recorded days ----------------------------------------

export interface Jump {
  day: Day;
  steps: number;
  days: number;
}

export interface Burnup {
  scope: [Day, number][]; // Estimated days of the scope's own work, per record, then today.
  done: [Day, number][];
  baseline: number | null; // The scope's own days in the plan compared with.
  promised: [Day, number][]; // The plan now's promise for the same work, by landing day.
  jumps: Jump[]; // Every change in scope between two records.
  // The days some step changed status: the record says so, or — in a row DPlanner wrote,
  // which does not — its done count moved.
  active: Day[];
}

export function burnup(view: TimeView, key: string | null, compared: boolean): Burnup {
  const scope: [Day, number][] = [];
  const done: [Day, number][] = [];
  const jumps: Jump[] = [];
  const active = new Set<Day>();
  let before: Tally | null = null;
  for (const row of until(view.recording.rows, view.now)) {
    const own = ownTally(row, key);
    if (!own) continue;
    if (scope.length && scope[scope.length - 1][0] === row.day) {
      scope.pop();
      done.pop();
    }
    if (before && (own.steps !== before.steps || Math.abs(own.days - before.days) > EPSILON)) {
      jumps.push({ day: row.day, steps: own.steps - before.steps, days: own.days - before.days });
    }
    if (own.changed > 0 || (before && own.done !== before.done)) active.add(row.day);
    scope.push([row.day, own.days]);
    done.push([row.day, own.doneDays]);
    before = own;
  }
  const stretches = key === null
    ? view.now.stretches
    : view.now.stretches.filter((one) => one.key === key);
  const promised = promisedCurve(stretches);
  const start = stretches[0]?.start;
  const baseline = compared && view.then ? ownTally(view.then, key)?.days ?? null : null;
  return {
    scope,
    done,
    baseline,
    promised: start !== undefined ? [[start, 0], ...promised] : promised,
    jumps,
    active: [...active].sort((a, b) => a - b),
  };
}

/** How far the plots reach: the first day and the last on the date axis, and the most work. */
export interface Reach {
  from: Day;
  day: Day;
  days: number;
}

/**
 * The reach that holds every one of `snapshots` — each record up to today and the live plan,
 * or a whole run's records: from the first day any starts to the last any lands, and the most
 * work any holds. Drawn to it, moving between them moves only the lines. `snapshots` is never
 * empty.
 */
export function reachOf(snapshots: readonly Snapshot[]): Reach {
  const [starts, ends, work] = [[] as Day[], [] as Day[], [] as number[]];
  for (const one of snapshots) {
    starts.push(one.day, ...one.stretches.map((stretch) => stretch.start));
    ends.push(one.day, landingIn(one, null) ?? one.day);
    work.push(toward(one, null).days, ...promisedCurve(one.stretches).map(([, days]) => days));
  }
  return { from: Math.min(...starts), day: Math.max(...ends), days: Math.max(0, ...work) };
}

// -- what changed since the plan compared with ----------------------------------------------------

export interface ChangeList {
  since: Day;
  steps: number; // Own steps now less then.
  days: number;
  added: [Step, number | null][];
  estimates: [Step, Day, number, number | null][];
  unnamed: number; // Steps the record counts but cannot name: + moved in, − removed or moved out.
  moved: boolean; // The unnamed ones are probably moves between milestones.
  doneSteps: number;
  doneDays: number;
  unexplained: boolean; // Dates moved while the scope did not — team, focus or start.
}

function stepsOf(view: TimeView, plan: Plan, key: string | null): Step[] {
  if (key === null) return plan.steps;
  return view.stretches.find((one) => one.key === key)?.phase.steps ?? [];
}

export function changes(view: TimeView, scope: Scope): ChangeList | null {
  const then = view.then;
  if (!then || !scope.thenOwn) return null;
  const now = scope.own;
  const listed = changesSince(stepsOf(view, view.plan, scope.key), then.day);
  const unnamed = now.steps - scope.thenOwn.steps - listed.added.length;
  const whole = toward(view.now, null).steps - toward(then, null).steps -
    changesSince(view.plan.steps, then.day).added.length;
  const throughNow = toward(view.now, scope.key);
  const throughThen = toward(then, scope.key);
  return {
    since: then.day,
    steps: now.steps - scope.thenOwn.steps,
    days: now.days - scope.thenOwn.days,
    added: listed.added,
    estimates: listed.estimates,
    unnamed,
    moved: scope.key !== null && unnamed !== 0 && whole === 0,
    doneSteps: now.done - scope.thenOwn.done,
    doneDays: now.doneDays - scope.thenOwn.doneDays,
    unexplained: (scope.move.plan ?? 0) !== 0 && throughNow.steps === throughThen.steps &&
      Math.abs(throughNow.days - throughThen.days) < EPSILON,
  };
}
