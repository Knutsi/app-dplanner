/**
 * The burn-up: one scope's own work in days over the recorded days — how much there is, how
 * much is done, what the plan's own schedule promised, and where it lands at today's pace.
 *
 * Scope change is drawn where it happens: the area between the scope line and the scope the
 * plan compared with had is filled, and filled with ▲ where work was added and ▼ where it
 * was taken away. Up on the chart, up on the arrow and *more work* are one direction — v1's
 * share plot drew added scope as a line going down.
 */

import { axisTicks, type Day, formatDays, shortDate } from "../../model/calendar.ts";
import { niceCeiling } from "../../model/progress.ts";
import type { Burnup, Scope } from "../../brief.ts";
import type { TimeView } from "../../present.ts";
import { esc, INK, n, PLAN, SECONDARY, textWidth } from "../markup.ts";
import { type Direction, glyphPath, placeGlyphs, type Rect } from "../glyphs.ts";

const HEIGHT = 250;
const LEFT = 48;
const RIGHT = 96;
const TOP = 30;
const BOTTOM = 24;

/** A step curve's path: each value holds until the next point, the last until `end`. */
function stepPath(
  points: readonly [Day, number][],
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

export function burnupSvg(
  data: Burnup,
  scope: Scope,
  view: TimeView,
  width: number,
  basis: string,
): string {
  const today = view.today;
  const days = [today, ...data.scope.map(([day]) => day), ...data.promised.map(([day]) => day)];
  for (
    const day of [
      scope.move.projected,
      scope.move.planned,
      scope.move.then,
      scope.span?.[0] ?? null,
    ]
  ) {
    if (day !== null) days.push(day);
  }
  const [first, last] = [Math.min(...days) - 1, Math.max(...days) + 2];
  const values = [
    ...data.scope.map(([, v]) => v),
    ...data.promised.map(([, v]) => v),
    data.baseline ?? 0,
    1,
  ];
  const top = niceCeiling(Math.max(...values));
  const plotW = width - LEFT - RIGHT;
  const x = (day: Day) => LEFT + ((day - first) / (last - first)) * plotW;
  const y = (value: number) => TOP + (1 - value / top) * (HEIGHT - TOP - BOTTOM);
  const out = [
    `<svg class="chart" viewBox="0 0 ${n(width)} ${HEIGHT}" width="${
      n(width)
    }" height="${HEIGHT}" font-size="11">`,
  ];

  // The grid: days of work up the side, dates along the bottom.
  for (const share of [0, 0.5, 1]) {
    out.push(
      `<line x1="${LEFT}" x2="${n(LEFT + plotW)}" y1="${n(y(top * share))}" y2="${
        n(y(top * share))
      }" style="stroke:${INK}" stroke-opacity="0.12"/>`,
    );
    out.push(
      `<text x="${LEFT - 8}" y="${
        n(y(top * share))
      }" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${
        formatDays(top * share) || "0d"
      }</text>`,
    );
  }
  for (const [when, label] of axisTicks(first, last, Math.max(1, Math.floor(plotW / 70)))) {
    out.push(
      `<line x1="${n(x(when))}" x2="${n(x(when))}" y1="${TOP}" y2="${
        HEIGHT - BOTTOM
      }" style="stroke:${INK}" stroke-opacity="0.08"/>`,
    );
    out.push(
      `<text x="${n(x(when))}" y="${HEIGHT - 8}" text-anchor="middle" style="fill:${SECONDARY}">${
        esc(label)
      }</text>`,
    );
  }

  // Scope added or removed since the plan compared with: areas, then their arrows.
  const since = view.then?.day ?? null;
  if (data.baseline !== null && since !== null) {
    const areas: Record<Direction, Rect[]> = { up: [], down: [], left: [], right: [] };
    data.scope.forEach(([day, value], index) => {
      const next = index + 1 < data.scope.length ? data.scope[index + 1][0] : today;
      const from = Math.max(day, since);
      if (next <= from || Math.abs(value - data.baseline!) < 1e-9) return;
      const [left, right] = [x(from), x(next)];
      const [upper, lower] = [
        y(Math.max(value, data.baseline!)),
        y(Math.min(value, data.baseline!)),
      ];
      areas[value > data.baseline! ? "up" : "down"].push({
        x: left,
        y: upper,
        width: right - left,
        height: lower - upper,
      });
    });
    for (const direction of ["up", "down"] as const) {
      for (const rect of areas[direction]) {
        out.push(
          `<rect x="${n(rect.x)}" y="${n(rect.y)}" width="${n(rect.width)}" height="${
            n(rect.height)
          }" class="scope-${direction}-fill"/>`,
        );
      }
      for (const glyph of placeGlyphs(areas[direction])) {
        out.push(`<path d="${glyphPath(glyph, direction)}" class="scope-${direction}-glyph"/>`);
      }
    }
    const at = y(data.baseline);
    out.push(
      `<line x1="${n(x(since))}" x2="${n(LEFT + plotW)}" y1="${n(at)}" y2="${
        n(at)
      }" style="stroke:${SECONDARY}" stroke-dasharray="5 4"/>`,
    );
    out.push(
      `<text x="${n(LEFT + plotW + 6)}" y="${
        n(at)
      }" dominant-baseline="central" style="fill:${SECONDARY}">${
        esc(`${formatDays(data.baseline) || "0d"} then`)
      }</text>`,
    );
  }

  // Done: an area, because what is done is the one thing that is certain.
  const end = today;
  if (data.done.length) {
    const line = stepPath(data.done, x, y, end);
    out.push(
      `<path d="${line} V${n(y(0))} H${
        n(x(data.done[0][0]))
      } Z" style="fill:${INK}" fill-opacity="0.1"/>`,
    );
    out.push(`<path d="${line}" fill="none" style="stroke:${INK}" stroke-width="2"/>`);
  }
  // The plan's own schedule for this work: what it promised done by each day.
  if (data.promised.length > 1) {
    out.push(
      `<path d="${
        stepPath(data.promised, x, y, data.promised[data.promised.length - 1][0])
      }" fill="none" style="stroke:${SECONDARY}" stroke-width="1.5" stroke-dasharray="1 3" stroke-linecap="round"/>`,
    );
  }
  // Scope: how much work there is, as recorded.
  if (data.scope.length) {
    out.push(
      `<path d="${
        stepPath(data.scope, x, y, end)
      }" fill="none" stroke="${PLAN}" stroke-width="2.5"/>`,
    );
    const [, now] = data.scope[data.scope.length - 1];
    out.push(
      `<text x="${n(LEFT + plotW + 6)}" y="${
        n(y(now) - (data.baseline !== null && Math.abs(y(now) - y(data.baseline)) < 12 ? 10 : 0))
      }" dominant-baseline="central" fill="${PLAN}" font-weight="600">${
        esc(`${formatDays(now) || "0d"} now`)
      }</text>`,
    );
  }
  // Where it lands: the plan compared with (hollow), the plan now, and today's pace.
  const scopeNow = data.scope.length ? data.scope[data.scope.length - 1][1] : 0;
  const doneNow = data.done.length ? data.done[data.done.length - 1][1] : 0;
  const lands = scope.move.projected;
  if (lands !== null && scope.landedBy === null) {
    out.push(
      `<line x1="${n(x(today))}" y1="${n(y(doneNow))}" x2="${n(x(lands))}" y2="${
        n(y(scopeNow))
      }" class="projection"/>`,
    );
    out.push(
      `<circle cx="${n(x(lands))}" cy="${n(y(scopeNow))}" r="5" class="projected"><title>${
        esc(`lands ~${shortDate(lands, today)} at today's pace`)
      }</title></circle>`,
    );
    const label = `~${shortDate(lands, today)}`;
    out.push(
      `<text x="${n(Math.min(x(lands) + 8, LEFT + plotW + RIGHT - textWidth(label) - 4))}" y="${
        n(y(scopeNow) + 16)
      }" font-weight="600" style="fill:${INK}">${esc(label)}</text>`,
    );
  }
  if (scope.move.planned !== null && scope.move.planned !== lands && scope.landedBy === null) {
    const at = x(scope.move.planned);
    out.push(
      `<line x1="${n(at)}" x2="${n(at)}" y1="${n(y(scopeNow) - 6)}" y2="${
        n(y(scopeNow) + 6)
      }" style="stroke:${INK}" stroke-width="2"><title>${
        esc(`the plan itself says ${shortDate(scope.move.planned, today)}`)
      }</title></line>`,
    );
  }
  if (scope.move.then !== null && data.baseline !== null) {
    out.push(
      `<circle cx="${n(x(scope.move.then))}" cy="${
        n(y(data.baseline))
      }" r="4.5" style="fill:var(--surface);stroke:${SECONDARY}" stroke-width="1.5"><title>${
        esc(`${basis} landed it ${shortDate(scope.move.then, today)}`)
      }</title></circle>`,
    );
  }

  // Today, saved snapshots, and what each scope jump was.
  for (const row of view.recording.saved) {
    if (row.day < first || row.day > last) continue;
    out.push(
      `<line x1="${n(x(row.day))}" x2="${n(x(row.day))}" y1="${TOP}" y2="${
        HEIGHT - BOTTOM
      }" style="stroke:${INK}" stroke-opacity="0.4" stroke-dasharray="4 3"><title>${
        esc(`saved: ${row.title}`)
      }</title></line>`,
    );
  }
  out.push(
    `<line x1="${n(x(today))}" x2="${n(x(today))}" y1="${TOP - 6}" y2="${
      HEIGHT - BOTTOM
    }" class="today-line"/>`,
  );
  out.push(
    `<text x="${n(x(today))}" y="${
      TOP - 10
    }" text-anchor="middle" font-weight="600" style="fill:${INK}">today</text>`,
  );
  for (const jump of data.jumps) {
    const words = `${jump.steps >= 0 ? "+" : "−"}${Math.abs(jump.steps)} step${
      Math.abs(jump.steps) === 1 ? "" : "s"
    }, ${jump.days >= 0 ? "+" : "−"}${formatDays(Math.abs(jump.days)) || "0d"} on ${
      shortDate(jump.day, today)
    }`;
    out.push(
      `<rect x="${n(x(jump.day) - 5)}" y="${TOP}" width="10" height="${
        HEIGHT - TOP - BOTTOM
      }" fill="transparent"><title>${esc(words)}</title></rect>`,
    );
  }
  out.push("</svg>");
  return out.join("");
}

/** The key under the chart — every mark it draws, named once. */
export function burnupKey(basis: string, compared: boolean): string {
  const up = glyphPath({ x: 9, y: 8, size: 7 }, "up");
  const down = glyphPath({ x: 9, y: 8, size: 7 }, "down");
  const items = [
    `<span><svg width="18" height="14"><line x1="1" x2="17" y1="7" y2="7" stroke="${PLAN}" stroke-width="2.5"/></svg>scope</span>`,
    `<span><svg width="18" height="14"><rect x="1" y="3" width="16" height="9" style="fill:${INK}" fill-opacity="0.18"/><line x1="1" x2="17" y1="3" y2="3" style="stroke:${INK}" stroke-width="2"/></svg>done</span>`,
    `<span><svg width="18" height="14"><line x1="1" x2="17" y1="7" y2="7" style="stroke:${SECONDARY}" stroke-width="1.5" stroke-dasharray="1 3" stroke-linecap="round"/></svg>the plan's schedule</span>`,
    `<span><svg width="18" height="14"><line x1="1" x2="17" y1="7" y2="7" class="projection"/></svg>at today's pace</span>`,
  ];
  if (compared) {
    items.push(
      `<span><svg width="18" height="14"><line x1="1" x2="17" y1="7" y2="7" style="stroke:${SECONDARY}" stroke-dasharray="5 4"/></svg>scope in ${
        esc(basis)
      }</span>`,
      `<span><svg width="18" height="16"><rect x="0" y="0" width="18" height="16" class="scope-up-fill"/><path d="${up}" class="scope-up-glyph"/></svg>work added</span>`,
      `<span><svg width="18" height="16"><rect x="0" y="0" width="18" height="16" class="scope-down-fill"/><path d="${down}" class="scope-down-glyph"/></svg>work taken away</span>`,
    );
  }
  return items.join("");
}
