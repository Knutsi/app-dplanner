/**
 * The Work tab: two plots on one locked date axis and **one scale in days**, so a height in
 * one is the same amount of work as the same height in the other.
 *
 * - **Scope** — how much work the plan held on each recorded day, against what the plan
 *   compared with held, the area between them shaded warm (more) or cool (less). Each day
 *   the scope changed carries one arrow right under the line: ▲ when that day added work in
 *   sum, ▼ when it took some away.
 * - **Work done** — what is done, and from today on what the plan's schedule, re-planned
 *   from today, will have done by each day. Each milestone is marked where it sits: a check
 *   on the done line the day it was done, or a dot on the schedule the day the plan lands it.
 */

import { axisTicks, type Day, formatDays, isWorkingDay, shortDate } from "../../model/calendar.ts";
import { isDelay } from "../../model/graph.ts";
import { landingOf, startDayOf } from "../../model/simulate.ts";
import { niceCeiling, type Point } from "../../model/progress.ts";
import type { Burnup, Jump, Scope } from "../../brief.ts";
import type { TimeView } from "../../present.ts";
import { glyphPath } from "../glyphs.ts";
import { esc, INK, n, PLAN, SECONDARY } from "../markup.ts";
import { CHECK_R, landedCheck } from "./marks.ts";

const LEFT = 52;
const RIGHT = 90;
const TOP = 30;
const PLOT_H = 150;
const GAP = 46;
const BOTTOM = 26;
const MARK = 8;

export interface ScopeMark {
  day: Day;
  direction: "up" | "down";
  steps: number;
  days: number;
}

/** One mark per day the scope changed, by the day's sum; a day that netted nothing has none. */
export function scopeMarks(jumps: readonly Jump[]): ScopeMark[] {
  const byDay = new Map<Day, Jump>();
  for (const jump of jumps) {
    const sum = byDay.get(jump.day);
    byDay.set(
      jump.day,
      sum ? { day: jump.day, steps: sum.steps + jump.steps, days: sum.days + jump.days } : jump,
    );
  }
  return [...byDay.values()].flatMap((jump) => {
    const sign = Math.abs(jump.days) > 1e-9 ? Math.sign(jump.days) : Math.sign(jump.steps);
    return sign ? [{ ...jump, direction: sign > 0 ? "up" as const : "down" as const }] : [];
  });
}

/** A step curve's value on a day: what the last point at or before it said. */
export function stepAt(points: readonly Point[], day: Day): number | null {
  let found: number | null = null;
  for (const [when, value] of points) {
    if (when > day) break;
    found = value;
  }
  return found;
}

/** A step curve from a day on: its value that day, then every later point. */
export function stepsFrom(points: readonly Point[], day: Day): Point[] {
  const at = stepAt(points, day);
  return [...(at === null ? [] : [[day, at] as Point]), ...points.filter(([when]) => when > day)];
}

/**
 * What v4 adds to the plots. A day's point on the axis is its end, so the day itself runs
 * from the point before to its own — which is where each of these draws it.
 * - `weekends`: a pale band on each day off, through both plots;
 * - `idle`: the done line dotted across a day on which no step changed status;
 * - `delays`: a hatched band over each wait still in the plan, named.
 */
export interface WorkMarks {
  weekends?: boolean;
  idle?: boolean;
  delays?: boolean;
}

/** Each Delay in the plan that still waits: its title and the days it covers. */
export function delaySpans(view: TimeView): { title: string; from: Day; to: Day }[] {
  return view.stretches.flatMap(({ phase }) =>
    phase.steps.filter(isDelay).flatMap((step) => {
      const [begins, ends] = [phase.starts.get(step.id), phase.landings.get(step.id)];
      if (begins === undefined || ends === undefined || ends - begins < 1e-9) return [];
      return [{
        title: step.title,
        from: startDayOf(phase, step.id),
        to: landingOf(phase, step.id),
      }];
    })
  );
}

export interface WorkGeometry {
  first: Day;
  last: Day;
  left: number;
  right: number;
  top: number;
  bottom: number;
  x: (day: Day) => number;
  day: (x: number) => Day;
  scopeY: (value: number) => number;
  workY: (value: number) => number;
}

function stepPath(
  points: readonly Point[],
  x: (day: Day) => number,
  y: (value: number) => number,
  end: Day,
): string {
  if (!points.length) return "";
  let path = `M${n(x(points[0][0]))},${n(y(points[0][1]))}`;
  points.forEach((_, index) => {
    const next = index + 1 < points.length ? points[index + 1] : null;
    path += ` H${n(x(next ? next[0] : end))}`;
    if (next) path += ` V${n(y(next[1]))}`;
  });
  return path;
}

/**
 * The area between the scope and the baseline from the day compared with: warm where the plan
 * holds more work than it did, cool where it holds less. One rectangle per recorded level.
 */
export function scopeFills(
  points: readonly Point[],
  baseline: number,
  from: Day,
  to: Day,
  x: (day: Day) => number,
  y: (value: number) => number,
): string[] {
  return points.flatMap(([day, value], index) => {
    const [start, end] = [
      Math.max(day, from),
      index + 1 < points.length ? points[index + 1][0] : to,
    ];
    if (end <= start || Math.abs(value - baseline) < 1e-9) return [];
    const [top, bottom] = [y(Math.max(value, baseline)), y(Math.min(value, baseline))];
    return [
      `<rect x="${n(x(start))}" y="${n(top)}" width="${n(x(end) - x(start))}" height="${
        n(bottom - top)
      }" class="scope-${value > baseline ? "up" : "down"}-fill"/>`,
    ];
  });
}

type Key = [string, string]; // A small drawing, and its words.

function title(name: string, keys: Key[], y: number, right: number): string {
  const out = [
    `<text x="${LEFT}" y="${
      n(y)
    }" dominant-baseline="central" font-size="12" font-weight="600" style="fill:${INK}">${
      esc(name)
    }</text>`,
  ];
  let cursor = right;
  for (const [mark, words] of [...keys].reverse()) {
    cursor -= words.length * 6.2 + 4;
    out.push(
      `<text x="${n(cursor)}" y="${
        n(y)
      }" dominant-baseline="central" font-size="11" style="fill:${SECONDARY}">${esc(words)}</text>`,
    );
    cursor -= 22;
    out.push(`<g transform="translate(${n(cursor)},${n(y - 7)})">${mark}</g>`);
    cursor -= 12;
  }
  return out.join("");
}

export function workSvg(
  data: Burnup,
  marked: readonly Scope[],
  view: TimeView,
  width: number,
  compared: boolean,
  marks: WorkMarks = {},
): { svg: string; geometry: WorkGeometry } {
  const today = view.today;
  const days = [today, ...data.scope.map(([day]) => day), ...data.promised.map(([day]) => day)];
  for (const one of marked) {
    for (const day of [one.move.planned, one.landedBy]) if (day !== null) days.push(day);
  }
  const [first, last] = [Math.min(...days) - 1, Math.max(...days) + 2];
  const top = niceCeiling(
    Math.max(
      1,
      ...data.scope.map(([, v]) => v),
      ...data.promised.map(([, v]) => v),
      data.baseline ?? 0,
    ),
  );
  const right = width - RIGHT;
  const x = (day: Day) => LEFT + ((day - first) / (last - first)) * (right - LEFT);
  const scopeTop = TOP;
  const workTop = TOP + PLOT_H + GAP;
  const scopeY = (value: number) => scopeTop + (1 - value / top) * PLOT_H;
  const workY = (value: number) => workTop + (1 - value / top) * PLOT_H;
  const height = workTop + PLOT_H + BOTTOM;
  const out = [
    `<svg class="chart work" viewBox="0 0 ${n(width)} ${n(height)}" width="${n(width)}" height="${
      n(height)
    }" font-size="11">`,
  ];

  // One scale in days for both, one set of dates through both.
  for (const y of [scopeY, workY]) {
    for (const share of [0, 0.5, 1]) {
      out.push(
        `<line x1="${LEFT}" x2="${n(right)}" y1="${n(y(top * share))}" y2="${
          n(y(top * share))
        }" style="stroke:${INK}" stroke-opacity="${share ? 0.1 : 0.25}"/>`,
      );
      out.push(
        `<text x="${LEFT - 8}" y="${
          n(y(top * share))
        }" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${
          formatDays(top * share) || "0d"
        }</text>`,
      );
    }
  }
  for (
    const [when, label] of axisTicks(first, last, Math.max(1, Math.floor((right - LEFT) / 70)))
  ) {
    out.push(
      `<line x1="${n(x(when))}" x2="${n(x(when))}" y1="${scopeTop}" y2="${
        n(workTop + PLOT_H)
      }" style="stroke:${INK}" stroke-opacity="0.07"/>`,
    );
    if (Math.abs(x(when) - x(today)) < 34) continue;
    out.push(
      `<text x="${n(x(when))}" y="${
        n(height - 8)
      }" text-anchor="middle" style="fill:${SECONDARY}">${esc(label)}</text>`,
    );
  }

  const band = (from: number, to: number, fill: string, top: number, label?: string) => {
    const [a, b] = [Math.max(LEFT, from), Math.min(right, to)];
    if (b - a < 0.5) return;
    out.push(
      `<rect x="${n(a)}" y="${n(top)}" width="${n(b - a)}" height="${PLOT_H}" ${fill}>${
        label ? `<title>${esc(label)}</title>` : ""
      }</rect>`,
    );
  };
  if (marks.weekends) {
    for (let day = first + 1; day <= last; day += 1) {
      if (isWorkingDay(day)) continue;
      for (const top of [scopeTop, workTop]) band(x(day - 1), x(day), `class="weekend"`, top);
    }
  }
  if (marks.delays) {
    const spans = delaySpans(view);
    if (spans.length) {
      out.push(
        `<defs><pattern id="delay-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" class="delay-fill"/><line x1="0" y1="0" x2="0" y2="6" class="delay-line"/></pattern></defs>`,
      );
    }
    for (const span of spans) {
      for (const top of [scopeTop, workTop]) {
        band(x(span.from), x(span.to), `fill="url(#delay-hatch)" class="delay"`, top, span.title);
      }
      const at = Math.max(LEFT, x(span.from)) + 4;
      if (at < right - 20) {
        out.push(
          `<text x="${n(at)}" y="${n(workTop + 12)}" font-size="10" class="delay-label">${
            esc(span.title)
          }</text>`,
        );
      }
    }
  }

  // -- Scope ----------------------------------------------------------------------------------
  const up = glyphPath({ x: 9, y: 7, size: 8 }, "up");
  const down = glyphPath({ x: 9, y: 7, size: 8 }, "down");
  const scopeKeys: Key[] = [[
    `<line x1="0" x2="18" y1="7" y2="7" stroke="${PLAN}" stroke-width="2.5"/>`,
    "scope",
  ]];
  if (compared && data.baseline !== null) {
    scopeKeys.push([
      `<line x1="0" x2="18" y1="7" y2="7" style="stroke:${SECONDARY}" stroke-dasharray="5 4"/>`,
      "then",
    ]);
  }
  scopeKeys.push(
    [
      `<rect x="0" y="1" width="18" height="12" class="scope-up-fill"/><path d="${up}" class="scope-up-glyph"/>`,
      "added",
    ],
    [
      `<rect x="0" y="1" width="18" height="12" class="scope-down-fill"/><path d="${down}" class="scope-down-glyph"/>`,
      "removed",
    ],
  );
  out.push(title("Scope", scopeKeys, scopeTop - 16, right));
  const scopeNow = data.scope.length ? data.scope[data.scope.length - 1][1] : 0;
  if (compared && data.baseline !== null && view.then) {
    out.push(...scopeFills(data.scope, data.baseline, view.then.day, today, x, scopeY));
    const at = scopeY(data.baseline);
    out.push(
      `<line x1="${n(x(view.then.day))}" x2="${n(right)}" y1="${n(at)}" y2="${
        n(at)
      }" style="stroke:${SECONDARY}" stroke-dasharray="5 4"/>`,
    );
    const clash = Math.abs(at - scopeY(scopeNow)) < 13;
    out.push(
      `<text x="${n(right + 6)}" y="${
        n(at + (clash ? 7 : 0))
      }" dominant-baseline="central" style="fill:${SECONDARY}">${
        esc(`${formatDays(data.baseline) || "0d"} then`)
      }</text>`,
    );
  }
  if (data.scope.length) {
    out.push(
      `<path d="${
        stepPath(data.scope, x, scopeY, today)
      }" fill="none" stroke="${PLAN}" stroke-width="2.5"/>`,
    );
    const clash = data.baseline !== null && Math.abs(scopeY(data.baseline) - scopeY(scopeNow)) < 13;
    out.push(
      `<text x="${n(right + 6)}" y="${
        n(scopeY(scopeNow) - (clash ? 7 : 0))
      }" dominant-baseline="central" fill="${PLAN}" font-weight="600">${
        esc(`${formatDays(scopeNow) || "0d"} now`)
      }</text>`,
    );
  }
  for (const mark of scopeMarks(data.jumps)) {
    const level = stepAt(data.scope, mark.day) ?? 0;
    const glyph = { x: x(mark.day) + 6, y: scopeY(level) + MARK, size: MARK };
    const said = `${mark.steps >= 0 ? "+" : "−"}${Math.abs(mark.steps)} step${
      Math.abs(mark.steps) === 1 ? "" : "s"
    }, ${mark.days >= 0 ? "+" : "−"}${formatDays(Math.abs(mark.days)) || "0d"} on ${
      shortDate(mark.day, today)
    }`;
    out.push(
      `<path d="${
        glyphPath(glyph, mark.direction)
      }" class="scope-${mark.direction}-glyph scope-mark"><title>${esc(said)}</title></path>`,
    );
  }

  // -- Work done ------------------------------------------------------------------------------
  // With idle days dotted on the done line, the schedule is dashed, so the two never mix.
  const schedule = marks.idle
    ? `stroke-dasharray="5 3"`
    : `stroke-dasharray="1 3" stroke-linecap="round"`;
  const idle = `stroke-dasharray="0.5 4" stroke-linecap="round"`;
  out.push(title(
    "Work done",
    [
      [
        `<rect x="0" y="2" width="18" height="10" style="fill:${INK}" fill-opacity="0.15"/><line x1="0" x2="18" y1="2" y2="2" style="stroke:${INK}" stroke-width="2"/>`,
        "done",
      ],
      ...(marks.idle
        ? [[
          `<line x1="0" x2="18" y1="7" y2="7" style="stroke:${INK}" stroke-width="2" ${idle}/>`,
          "no status change",
        ] as Key]
        : []),
      [
        `<line x1="0" x2="18" y1="7" y2="7" style="stroke:${SECONDARY}" stroke-width="1.5" ${schedule}/>`,
        "the plan's schedule",
      ],
    ],
    workTop - 16,
    right,
  ));
  // The whole of the work, faint, so the done line has somewhere to climb to.
  out.push(
    `<line x1="${LEFT}" x2="${n(right)}" y1="${n(workY(scopeNow))}" y2="${
      n(workY(scopeNow))
    }" style="stroke:${PLAN}" stroke-opacity="0.35" stroke-dasharray="2 3"><title>${
      esc(`all of the work: ${formatDays(scopeNow) || "0d"}`)
    }</title></line>`,
  );
  if (data.promised.length > 1) {
    out.push(
      `<path d="${
        stepPath(data.promised, x, workY, data.promised[data.promised.length - 1][0])
      }" fill="none" style="stroke:${SECONDARY}" stroke-width="1.5" ${schedule}/>`,
    );
  }
  if (data.done.length) {
    const line = stepPath(data.done, x, workY, today);
    out.push(
      `<path d="${line} V${n(workY(0))} H${
        n(x(data.done[0][0]))
      } Z" style="fill:${INK}" fill-opacity="0.1"/>`,
    );
    if (!marks.idle) {
      out.push(`<path d="${line}" fill="none" style="stroke:${INK}" stroke-width="2"/>`);
    } else {
      // Solid across a day some step changed status, dotted across one none did.
      const active = new Set(data.active);
      const [solid, dotted]: string[][] = [[], []];
      let level = data.done[0][1];
      for (let day = data.done[0][0] + 1; day <= today; day += 1) {
        const y = workY(level);
        (active.has(day) ? solid : dotted).push(`M${n(x(day - 1))},${n(y)} H${n(x(day))}`);
        const next = stepAt(data.done, day) ?? level;
        if (next !== level) solid.push(`M${n(x(day))},${n(y)} V${n(workY(next))}`);
        level = next;
      }
      out.push(`<path d="${solid.join(" ")}" fill="none" style="stroke:${INK}" stroke-width="2"/>`);
      out.push(
        `<path d="${
          dotted.join(" ")
        }" fill="none" style="stroke:${INK}" stroke-width="2" ${idle} class="idle"/>`,
      );
    }
  }
  const labelled: [number, number][] = [];
  for (const one of marked) {
    const done = one.landedBy;
    const day = done ?? one.move.planned;
    if (day === null) continue;
    const [cx, cy] = [
      x(day),
      workY((done !== null ? stepAt(data.done, day) : stepAt(data.promised, day)) ?? 0),
    ];
    const said = `${one.badge} ${one.label}${one.title ? ` — ${one.title}` : ""}\n${
      done !== null ? "done by" : "the plan lands it"
    } ${shortDate(day, today)}`;
    out.push(`<g class="milestone-mark"><title>${esc(said)}</title>`);
    out.push(
      done !== null
        ? landedCheck(cx, cy, one.color)
        : `<circle cx="${n(cx)}" cy="${
          n(cy)
        }" r="5" fill="${one.color}" style="stroke:var(--surface)" stroke-width="1.5"/>`,
    );
    // A name that would sit on another's is left to the tooltip.
    const [lx, ly] = [cx, cy - (done !== null ? CHECK_R : 5) - 6];
    if (!labelled.some(([ax, ay]) => Math.abs(ax - lx) < 28 && Math.abs(ay - ly) < 14)) {
      labelled.push([lx, ly]);
      out.push(
        `<text x="${n(lx)}" y="${
          n(ly)
        }" text-anchor="middle" font-weight="600" style="fill:${INK}">${esc(one.label)}</text>`,
      );
    }
    out.push("</g>");
  }

  // Today and the saved snapshots, through both.
  for (const row of view.recording.saved) {
    if (row.day < first || row.day > last) continue;
    out.push(
      `<line x1="${n(x(row.day))}" x2="${n(x(row.day))}" y1="${scopeTop}" y2="${
        n(workTop + PLOT_H)
      }" style="stroke:${INK}" stroke-opacity="0.35" stroke-dasharray="4 3"><title>${
        esc(`saved: ${row.title}`)
      }</title></line>`,
    );
  }
  out.push(
    `<line x1="${n(x(today))}" x2="${n(x(today))}" y1="${scopeTop}" y2="${
      n(workTop + PLOT_H)
    }" class="today-line"/>`,
  );
  out.push(
    `<text x="${n(x(today))}" y="${
      n(height - 8)
    }" text-anchor="middle" font-weight="600" style="fill:${INK}">today</text>`,
  );
  out.push(
    `<line class="hover" x1="0" x2="0" y1="${scopeTop}" y2="${
      n(workTop + PLOT_H)
    }" style="stroke:${INK}" stroke-opacity="0.5" visibility="hidden"/>`,
  );
  out.push("</svg>");
  return {
    svg: out.join(""),
    geometry: {
      first,
      last,
      left: LEFT,
      right,
      top: scopeTop,
      bottom: workTop + PLOT_H,
      x,
      day: (px) => Math.round(first + ((px - LEFT) / (right - LEFT)) * (last - first)),
      scopeY,
      workY,
    },
  };
}
