/**
 * Progress, snapshots and comparisons — `modules/time_estimates/progress.py`, plus
 * `share_at` and `change_runs` from `domain/schedule.py`.
 *
 * A Snapshot is one row of `progress_history`: the plan on one day, stretch by stretch, with
 * each stretch's tally, its dates and its landing knots. The curves are drawn from those rows
 * alone, never from the graph, which is why a comparison can only ever be as good as what
 * was recorded.
 */

import {
  type Day,
  formatDate,
  g,
  isoDay,
  nextWorkingDay,
  parseDay,
  percent,
  pyRound,
  workingDaysBetween,
} from "./calendar.ts";
import { cyclic, type DaysFor, daysFor, DONE, isDelay, type Plan, type Step } from "./graph.ts";
import type { ModelOptions } from "./options.ts";
import { landingOf, type Phase, phases, stretched } from "./simulate.ts";

export type Point = [Day, number];

export const ON_PLAN = 0.005;
export const SAME_SHARE = 0.002;

export interface Tally {
  steps: number;
  done: number;
  days: number; // Estimated days, unestimated steps counting nothing.
  doneDays: number;
  // Steps whose status changed on the snapshot's day — 0 in a row DPlanner wrote, which
  // does not know (BACKPORT.md).
  changed: number;
}

export const EMPTY_TALLY: Tally = { steps: 0, done: 0, days: 0.0, doneDays: 0.0, changed: 0 };

export function addTally(a: Tally, b: Tally): Tally {
  return {
    steps: a.steps + b.steps,
    done: a.done + b.done,
    days: a.days + b.days,
    doneDays: a.doneDays + b.doneDays,
    changed: a.changed + b.changed,
  };
}

/** `Tally.share`: done days over all days — null when there is nothing to be a share of. */
export function shareOf(tally: Tally): number | null {
  return tally.days ? tally.doneDays / tally.days : null;
}

export function remainingOf(tally: Tally): number {
  return tally.days - tally.doneDays;
}

export interface Landing {
  day: Day;
  steps: number;
  days: number;
}

export interface Stretch {
  key: string; // The milestone's step id; "" for the work after the last one.
  tally: Tally;
  start: Day;
  finish: Day | null;
  landings: Landing[];
}

export interface Snapshot {
  day: Day;
  stretches: Stretch[];
  title: string; // A saved snapshot's; "" on an automatic day.
  note: string;
}

/** `Snapshot.toward`: the tally through the stretch `key` closes — every stretch for null. */
export function toward(snapshot: Snapshot, key: string | null): Tally {
  let total = EMPTY_TALLY;
  for (const stretch of snapshot.stretches) {
    total = addTally(total, stretch.tally);
    if (stretch.key === key) return total;
  }
  return key === null ? total : EMPTY_TALLY;
}

export function has(snapshot: Snapshot, key: string | null): boolean {
  return key === null || snapshot.stretches.some((stretch) => stretch.key === key);
}

/** `Snapshot.landing`: the stretch's finish, or the last dated one for the whole. */
export function landingIn(snapshot: Snapshot, key: string | null): Day | null {
  if (key === null) {
    return [...snapshot.stretches].reverse().find((s) => s.finish !== null)?.finish ?? null;
  }
  return snapshot.stretches.find((s) => s.key === key)?.finish ?? null;
}

function sameStretch(a: Stretch, b: Stretch): boolean {
  return a.key === b.key && a.start === b.start && a.finish === b.finish &&
    a.tally.steps === b.tally.steps && a.tally.done === b.tally.done &&
    a.tally.days === b.tally.days && a.tally.doneDays === b.tally.doneDays &&
    a.tally.changed === b.tally.changed &&
    a.landings.length === b.landings.length &&
    a.landings.every((knot, index) => {
      const other = b.landings[index];
      return knot.day === other.day && knot.steps === other.steps && knot.days === other.days;
    });
}

/** `Snapshot.same_plan`: everything but the day. */
export function samePlan(a: Snapshot, b: Snapshot): boolean {
  return a.stretches.length === b.stretches.length &&
    a.stretches.every((stretch, index) => sameStretch(stretch, b.stretches[index]));
}

/** `landing_shift`: working days a landing moved, positive for later. */
export function landingShift(then: Day, now: Day): number {
  if (now >= then) return workingDaysBetween(then, now) - 1;
  return -(workingDaysBetween(now, then) - 1);
}

/** `span_of`: where the stretch `key` ran in a snapshot, or null. */
export function spanOf(snapshot: Snapshot | null, key: string): [Day, Day] | null {
  const found = snapshot?.stretches.find((stretch) => stretch.key === key);
  return found && found.finish !== null ? [found.start, found.finish] : null;
}

// -- words ---------------------------------------------------------------------------------------

/** `standing_words`: "on plan", "ahead 5%", "behind 12%". */
export function standingWords(standing: number | null): string {
  if (standing === null) return "";
  if (Math.abs(standing) < ON_PLAN) return "on plan";
  return `${standing > 0 ? "ahead" : "behind"} ${percent(Math.abs(standing))}`;
}

/** `shift_words`: a milestone's row in words, against the plan it is compared with. */
export function shiftWords(
  label: string,
  then: Day | null,
  now: Day | null,
  basis: string,
  today: Day,
): string {
  if (now === null) return `${label} — nothing estimated, so no date`;
  const said = `${label} lands ${formatDate(now, today)}`;
  if (!basis) return said;
  if (then === null) return `${said} — not in ${basis}`;
  const moved = landingShift(then, now);
  if (moved === 0) return `${said} — unchanged since ${basis}`;
  const size = Math.abs(moved);
  return `${said} — ${size} working day${size === 1 ? "" : "s"} ${
    moved > 0 ? "later" : "earlier"
  } ` +
    `than ${basis} said (${formatDate(then, today)})`;
}

/** `scope_words`: the scope plot's heading. */
export function scopeWords(basis: string): string {
  return basis ? `Scope change — versus ${basis}` : "Scope change — nothing to compare with";
}

// -- taking a snapshot -----------------------------------------------------------------------

export interface TakeArgs {
  humans: number;
  agents: number;
  start: Day;
  efficiency: number;
  today: Day;
  options?: ModelOptions;
}

/** `calendar_phases`: the stretches dated on the calendar, over stretched estimates. */
export function calendarPhases(plan: Plan, args: TakeArgs): Phase[] {
  return phases(plan, stretched(daysFor, args.efficiency), {
    humans: args.humans,
    agents: args.agents,
    start: args.start,
    today: args.today,
    options: args.options,
  });
}

/** `take`: the plan today. Null for a project with no steps, or one a loop keeps undated. */
export function take(plan: Plan, args: TakeArgs): Snapshot | null {
  if (!plan.steps.length || cyclic(plan).length) return null;
  return snapshotFrom(calendarPhases(plan, args), args.today);
}

/** A Snapshot from dated stretches — what the tab's own `snapshot()` builds from a cell. */
export function snapshotFrom(dated: Phase[], today: Day): Snapshot {
  return {
    day: today,
    stretches: dated.map((phase) => ({
      key: phase.milestone ? phase.milestone.id : "",
      tally: tally(phase.steps, daysFor, today),
      start: phase.began,
      finish: phase.finish,
      landings: landings(phase),
    })),
    title: "",
    note: "",
  };
}

/** `landings`: what the stretch lands on each date, weighted by the *raw* estimates. */
export function landings(phase: Phase, days: DaysFor = daysFor): Landing[] {
  const byDay = new Map<Day, Landing>();
  for (const step of phase.steps) {
    if (isDelay(step)) continue;
    const when = landingOf(phase, step.id);
    const found = byDay.get(when) ?? { day: when, steps: 0, days: 0.0 };
    byDay.set(when, { day: when, steps: found.steps + 1, days: found.days + (days(step) ?? 0.0) });
  }
  return [...byDay.keys()].sort((a, b) => a - b).map((when) => byDay.get(when)!);
}

/**
 * `tally`: what these steps amount to, and how much of it reads done — only "done" counts.
 * A Delay is no work, so it is no part of any tally. `today` counts the steps whose status
 * changed that day.
 */
export function tally(steps: readonly Step[], days: DaysFor = daysFor, today?: Day): Tally {
  let total = EMPTY_TALLY;
  for (const step of steps) {
    if (isDelay(step)) continue;
    const cost = days(step) ?? 0.0;
    const landed = step.status === DONE;
    total = addTally(total, {
      steps: 1,
      done: landed ? 1 : 0,
      days: cost,
      doneDays: landed ? cost : 0.0,
      changed: today !== undefined && step.since === today ? 1 : 0,
    });
  }
  return total;
}

// -- the curves ------------------------------------------------------------------------------

/** `_through`: the stretches up to and including the one `key` closes — all of them for null. */
export function through(snapshot: Snapshot, key: string | null): Stretch[] {
  const chosen: Stretch[] = [];
  for (const stretch of snapshot.stretches) {
    chosen.push(stretch);
    if (stretch.key === key) break;
  }
  return chosen;
}

/** `marks`: where each milestone through `key` was expected to land. */
export function marks(snapshot: Snapshot, key: string | null): [Day, string][] {
  return through(snapshot, key)
    .filter((stretch) => stretch.key && stretch.finish !== null)
    .map((stretch) => [stretch.finish!, stretch.key]);
}

/** `idle`: the spans a milestone's own later start leaves empty. */
export function idle(snapshot: Snapshot, key: string | null): [Day, Day][] {
  const chosen = through(snapshot, key);
  const spans: [Day, Day][] = [];
  for (let index = 1; index < chosen.length; index += 1) {
    const [previous, following] = [chosen[index - 1], chosen[index]];
    if (previous.finish === null) continue;
    if (following.start > nextWorkingDay(previous.finish + 1)) {
      spans.push([previous.finish, following.start]);
    }
  }
  return spans;
}

/** `expected`: the share of estimated days the plan promised landed by each date. */
export function expected(snapshot: Snapshot, key: string | null): Point[] {
  if (!has(snapshot, key)) return [];
  const chosen = through(snapshot, key);
  const whole = chosen.reduce(
    (sum, stretch) => stretch.landings.reduce((inner, knot) => inner + knot.days, sum),
    0,
  );
  if (!whole) return [];
  const landed = new Map<Day, number>();
  for (const stretch of chosen) {
    for (const knot of stretch.landings) {
      landed.set(knot.day, (landed.get(knot.day) ?? 0.0) + knot.days);
    }
  }
  const resumes = new Set(idle(snapshot, key).map(([, start]) => start));
  const points: Point[] = [[chosen[0].start, 0.0]];
  let running = 0.0;
  const days = [...new Set([...landed.keys(), ...resumes])].sort((a, b) => a - b);
  for (const when of days) {
    if (resumes.has(when)) points.push([when, points[points.length - 1][1]]);
    const add = landed.get(when);
    if (add !== undefined) {
      running += add;
      points.push([when, Math.min(running / whole, 1.0)]);
    }
  }
  return points;
}

/** `until`: the recorded days through `now`'s own, then `now`. */
export function until(history: readonly Snapshot[], now: Snapshot | null): Snapshot[] {
  const rows = history.filter((row) => now === null || row.day <= now.day);
  return now === null ? rows : [...rows, now];
}

/** `actual`: where progress stood on every recorded day that knew the scope, then now. */
export function actual(
  history: readonly Snapshot[],
  now: Snapshot | null,
  key: string | null,
): Point[] {
  const points: Point[] = [];
  for (const row of until(history, now)) {
    if (!has(row, key)) continue;
    const share = shareOf(toward(row, key));
    if (share === null) continue;
    if (points.length && points[points.length - 1][0] === row.day) {
      points[points.length - 1] = [row.day, share];
    } else {
      points.push([row.day, share]);
    }
  }
  return points;
}

/**
 * `baseline`: the last row on or before the basis, else the earliest — but that fallback
 * never lets today's own record stand in.
 */
export function baseline(
  history: readonly Snapshot[],
  basis: Day,
  today: Day | null = null,
): Snapshot | null {
  const before = history.filter((row) => row.day <= basis);
  if (before.length) return before[before.length - 1];
  const first = history[0] ?? null;
  if (first === null || (today !== null && first.day >= today)) return null;
  return first;
}

// -- the delta -------------------------------------------------------------------------------

export interface Delta {
  steps: number;
  days: number;
  finishThen: Day | null;
  finishNow: Day | null;
}

export function shiftOf(moved: Delta): number | null {
  if (moved.finishThen === null || moved.finishNow === null) return null;
  return landingShift(moved.finishThen, moved.finishNow);
}

export function delta(then: Snapshot, now: Snapshot, key: string | null): Delta | null {
  if (!has(then, key) || !has(now, key)) return null;
  const [was, is] = [toward(then, key), toward(now, key)];
  return {
    steps: is.steps - was.steps,
    days: is.days - was.days,
    finishThen: landingIn(then, key),
    finishNow: landingIn(now, key),
  };
}

/** `delta_words`: "since 7 September: +1 step, +5d, lands 5 working days later (was …)". */
export function deltaWords(moved: Delta, since: Day, today: Day): string {
  const when = formatDate(since, today);
  const shift = shiftOf(moved);
  if (!moved.steps && !moved.days && !shift) return `unchanged since ${when}`;
  const parts: string[] = [];
  if (moved.steps) {
    parts.push(
      `${moved.steps > 0 ? "+" : ""}${moved.steps} step${Math.abs(moved.steps) !== 1 ? "s" : ""}`,
    );
  }
  if (moved.days) parts.push(`${moved.days > 0 ? "+" : ""}${g(moved.days)}d`);
  if (shift) {
    const size = Math.abs(shift);
    parts.push(
      `lands ${size} working day${size !== 1 ? "s" : ""} ${shift > 0 ? "later" : "earlier"}` +
        (moved.finishThen !== null ? ` (was ${formatDate(moved.finishThen, today)})` : ""),
    );
  } else if (moved.finishThen === null && moved.finishNow !== null) {
    parts.push(`now lands ${formatDate(moved.finishNow, today)}`);
  } else if (moved.finishNow === null && moved.finishThen !== null) {
    parts.push("no longer dated");
  }
  return `since ${when}: ${parts.join(", ")}`;
}

export interface Changes {
  added: [Step, number | null][];
  estimates: [Step, Day, number, number | null][]; // step, day, from, to
  since: Day;
}

/**
 * `changes_since`: steps born after `since`, and estimates changed after it — one row per
 * step, from the day it first changed. A step with no `created` stamp is never "added".
 */
export function changesSince(steps: readonly Step[], since: Day): Changes {
  const added: Changes["added"] = [];
  const estimates: Changes["estimates"] = [];
  for (const step of steps) {
    if (step.created !== null && step.created > since) {
      added.push([step, daysFor(step)]);
      continue;
    }
    const later = step.estimateHistory.filter(([when]) => when > since);
    if (later.length) estimates.push([step, later[0][0], later[0][1], daysFor(step)]);
  }
  return { added, estimates, since };
}

// -- recording -------------------------------------------------------------------------------

/** `recorded`: the history with today recorded — null when nothing new would be written. */
export function recorded(history: readonly Snapshot[], taken: Snapshot): Snapshot[] | null {
  const now = { ...taken, title: "", note: "" };
  const rows = [...history];
  const last = rows[rows.length - 1];
  if (last && last.day === now.day) {
    if (samePlan(last, now)) return null;
    rows[rows.length - 1] = now;
    return rows;
  }
  if (last && samePlan(last, now)) return null;
  rows.push(now);
  return rows;
}

export function findSaved(saved: readonly Snapshot[], title: string): Snapshot | null {
  const wanted = title.trim().toLowerCase();
  return saved.find((row) => row.title.toLowerCase() === wanted) ?? null;
}

/** `saved_with`: refused when the title is empty or already taken. */
export function savedWith(
  saved: readonly Snapshot[],
  now: Snapshot,
  title: string,
  note = "",
): Snapshot[] {
  const named = title.trim();
  if (!named) throw new Error("a saved snapshot needs a title");
  if (findSaved(saved, named)) throw new Error(`a snapshot called "${named}" is already saved`);
  return [...saved, { ...now, title: named, note: note.trim() }];
}

// -- which plan a comparison reads -------------------------------------------------------------

export type Pick =
  | { kind: "start" }
  | { kind: "now" }
  | { kind: "saved"; title: string }
  | { kind: "day"; day: Day };

export const AT_START: Pick = { kind: "start" };
export const LIVE: Pick = { kind: "now" };

/** `resolve`: the record a pick names — null when nothing recorded answers it. */
export function resolve(
  pick: Pick,
  history: readonly Snapshot[],
  saved: readonly Snapshot[],
  live: Snapshot | null,
  start: Day,
): Snapshot | null {
  if (pick.kind === "now") return live;
  if (pick.kind === "saved") return findSaved(saved, pick.title);
  const when = pick.kind === "start" ? start : pick.day;
  return baseline(history, when, live !== null ? live.day : null);
}

/** `pick_words`: the pick named, and the record that stood in for it. */
export function pickWords(pick: Pick, found: Snapshot | null, today: Day): string {
  if (pick.kind === "now") return "now";
  if (pick.kind === "saved") {
    return found ? `${pick.title} (${formatDate(found.day, today)})` : "";
  }
  const when = pick.kind === "day" ? pick.day : null;
  const asked = when !== null ? `the plan at ${formatDate(when, today)}` : "the plan at start";
  if (found === null) return "";
  if (when !== null && found.day === when) return asked;
  return `${asked}, recorded ${formatDate(found.day, today)}`;
}

/** `short_pick_words`: what a picker's face says. */
export function shortPickWords(pick: Pick, today: Day): string {
  if (pick.kind === "now") return "Now";
  if (pick.kind === "start") return "Plan at start";
  if (pick.kind === "saved") return pick.title;
  return formatDate(pick.day, today);
}

// -- volume ----------------------------------------------------------------------------------

function stepCurve(rows: readonly Snapshot[], valueOf: (reached: Tally) => number): Point[] {
  const points: Point[] = [];
  for (const row of rows) {
    const value = valueOf(toward(row, null));
    const last = points[points.length - 1];
    if (last && last[0] === row.day) {
      points[points.length - 1] = [row.day, value];
      continue;
    }
    if (last) points.push([row.day, last[1]]);
    points.push([row.day, value]);
  }
  return points;
}

/** `volume`: the total of estimated days on each recorded day, as a step curve. */
export function volume(history: readonly Snapshot[], now: Snapshot | null): Point[] {
  return stepCurve(until(history, now), (reached) => reached.days);
}

/** `remaining`: the same less what had landed. */
export function remaining(history: readonly Snapshot[], now: Snapshot | null): Point[] {
  return stepCurve(until(history, now), remainingOf);
}

/** `nice_ceiling`: 1, 2 or 5 (or `steps`) times a power of ten at or above `value`; at least 1. */
export function niceCeiling(value: number, steps: readonly number[] = [1, 2, 5, 10]): number {
  if (value <= 1.0) return 1.0;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const step of steps) {
    if (step * magnitude >= value) return step * magnitude;
  }
  return 10 * magnitude;
}

export function volumeScale(total: readonly Point[], left: readonly Point[]): number {
  return niceCeiling(Math.max(0.0, ...[...total, ...left].map(([, value]) => value)));
}

// -- reading two lines together ---------------------------------------------------------------

/** `share_at`: a line's value on `when`, interpolated in calendar days, flat past its ends. */
export function shareAt(points: readonly Point[], when: Day): number | null {
  if (!points.length) return null;
  if (when <= points[0][0]) {
    return when === points[0][0] || points.length === 1 ? points[0][1] : null;
  }
  for (let index = 1; index < points.length; index += 1) {
    const [[left, low], [right, high]] = [points[index - 1], points[index]];
    if (left <= when && when <= right) {
      const span = right - left;
      const share = span ? (when - left) / span : 1.0;
      return low + (high - low) * share;
    }
  }
  return points[points.length - 1][1];
}

export type Sample = [Day, number, number]; // The day, the plan's share, the base's share.

/** `change_runs`: two lines cut into runs of one sign, closed where they cross. */
export function changeRuns(
  plan: readonly Point[],
  base: readonly Point[],
  same = SAME_SHARE,
): [number, Sample[]][] {
  const days = [...new Set([...plan.map(([d]) => d), ...base.map(([d]) => d)])].sort((a, b) =>
    a - b
  );
  const samples: Sample[] = [];
  for (const when of days) {
    const [above, below] = [shareAt(plan, when), shareAt(base, when)];
    if (above !== null && below !== null) samples.push([when, above, below]);
  }
  const runs: [number, Sample[]][] = [];
  for (const sample of samples) {
    const [, above, below] = sample;
    const sign = Math.abs(above - below) <= same ? 0 : above > below ? 1 : -1;
    const last = runs[runs.length - 1];
    if (last && last[0] === sign) {
      last[1].push(sample);
    } else if (last) {
      const crossing = crossingOf(last[1][last[1].length - 1], sample);
      last[1].push(crossing);
      runs.push([sign, [crossing, sample]]);
    } else {
      runs.push([sign, [sample]]);
    }
  }
  return runs.filter(([, run]) => run.length >= 2);
}

function crossingOf(left: Sample, right: Sample): Sample {
  const [[dayA, aboveA, belowA], [dayB, aboveB, belowB]] = [left, right];
  const [gapA, gapB] = [aboveA - belowA, aboveB - belowB];
  const total = gapA - gapB;
  const share = !total ? 0.5 : Math.max(0.0, Math.min(1.0, gapA / total));
  return [
    dayA + pyRound((dayB - dayA) * share, 0),
    aboveA + (aboveB - aboveA) * share,
    belowA + (belowB - belowA) * share,
  ];
}

/** `_standing`: actual against plan today, as a share — positive ahead. */
export function standing(
  plan: readonly Point[],
  landed: readonly Point[],
  today: Day,
): number | null {
  const [promised, reached] = [shareAt(plan, today), shareAt(landed, today)];
  return promised === null || reached === null ? null : reached - promised;
}

// -- the history on disk -----------------------------------------------------------------------

type Json = Record<string, unknown>;

function count(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) ? value : 0;
}

function amount(value: unknown): number {
  return typeof value === "number" ? value : 0.0;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function stretchFrom(row: Json): Stretch | null {
  const start = typeof row.start === "string" ? parseDay(row.start) : null;
  if (start === null) return null;
  const finish = typeof row.finish === "string" ? parseDay(row.finish) : null;
  const knots = Array.isArray(row.landings) ? row.landings : [];
  return {
    key: typeof row.milestone === "string" ? row.milestone : "",
    tally: {
      steps: count(row.steps),
      done: count(row.done),
      days: amount(row.days),
      doneDays: amount(row.done_days),
      changed: count(row.changed),
    },
    start,
    finish,
    landings: knots.flatMap((knot: Json) => {
      const when = typeof knot?.date === "string" ? parseDay(knot.date) : null;
      return when === null
        ? []
        : [{ day: when, steps: count(knot.steps), days: amount(knot.days) }];
    }),
  };
}

/** `_rows`: one list of `progress_history` read as snapshots, unreadable rows skipped. */
export function readRows(entry: unknown, key: "days" | "saved"): Snapshot[] {
  const raw = (entry as Json | null)?.[key];
  if (!Array.isArray(raw)) return [];
  const rows: Snapshot[] = [];
  for (const row of raw as Json[]) {
    if (typeof row !== "object" || row === null || typeof row.day !== "string") continue;
    const day = parseDay(row.day);
    if (day === null || !Array.isArray(row.stretches)) continue;
    const parsed = (row.stretches as Json[]).filter((s) => typeof s === "object" && s).map(
      stretchFrom,
    );
    if (parsed.some((stretch) => stretch === null)) continue;
    const snapshot = {
      day,
      stretches: parsed as Stretch[],
      title: text(row.title),
      note: text(row.note),
    };
    if (key === "saved" && !snapshot.title) continue;
    rows.push(snapshot);
  }
  return rows;
}

/** `_row`: a snapshot as the file stores it. */
export function rowJson(row: Snapshot): Json {
  return {
    day: isoDay(row.day),
    stretches: row.stretches.map((s) => ({
      ...(s.key ? { milestone: s.key } : {}),
      steps: s.tally.steps,
      done: s.tally.done,
      days: s.tally.days,
      done_days: s.tally.doneDays,
      ...(s.tally.changed ? { changed: s.tally.changed } : {}),
      start: isoDay(s.start),
      ...(s.finish !== null ? { finish: isoDay(s.finish) } : {}),
      ...(s.landings.length
        ? {
          landings: s.landings.map((k) => ({ date: isoDay(k.day), steps: k.steps, days: k.days })),
        }
        : {}),
    })),
  };
}
