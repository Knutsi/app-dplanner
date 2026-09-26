/**
 * The plots under the calendar — `time_estimates/chart.py` in the window and
 * `cli/report/drawings.py` on the page — as one SVG of stacked plots on a locked date axis.
 *
 * A page picks the plots (Progress: status and scope; Volume: the two amounts; Milestone
 * shifts; All). Picking a milestone highlights, never hides: everything is drawn faded, then
 * the picked stretch again at full strength through a clip.
 */

import { axisTicks, type Day, formatDays, percent, shortDate } from "../../model/calendar.ts";
import {
  changeRuns,
  type Point,
  scopeWords,
  shareAt,
  standingWords,
  volumeScale,
} from "../../model/progress.ts";
import type { ChartData, Page, Segment } from "../../present.ts";
import {
  ATTENTION,
  BAD,
  clip,
  esc,
  GOOD,
  INK,
  n,
  PLAN,
  SECONDARY,
  SURFACE,
  textWidth,
} from "../markup.ts";

export type Kind = "status" | "scope" | "shift" | "volume" | "remaining";

export const PAGES: { page: Page; label: string }[] = [
  { page: "shift", label: "Milestone shifts" },
  { page: "progress", label: "Progress" },
  { page: "volume", label: "Volume" },
  { page: "all", label: "All" },
];

const PAGE_PLOTS: Record<Page, Kind[]> = {
  shift: ["shift"],
  progress: ["status", "scope"],
  volume: ["volume", "remaining"],
  all: ["status", "scope", "shift", "volume", "remaining"],
};

const PLOT_H = 120;
const SHIFT_ROW_H = 26;
const TITLE_H = 18;
const PLOT_GAP = 22;
const CHART_TOP = 6;
const CHART_BOTTOM = 26;
const GUTTER_MIN = 46;
const GUTTER_MAX = 150;
const GUTTER_PAD = 12;
const CHART_RIGHT = 16;
const TICK_ROOM = 64;
const PAD_DAYS = 1;
const LINE_W = 2;
const MARKER = 4;
const LANDING_MARK = 3.5;
const ARROW_HEAD = 5;
const FADE = 0.3;

export interface Panel {
  kind: Kind;
  top: number;
  height: number;
  scale: number; // What the top stands for: a share (1) or days.
}

export interface Geometry {
  first: Day;
  last: Day;
  left: number;
  right: number;
  panels: Panel[];
  x: (day: Day) => number;
  y: (panel: Panel, value: number) => number;
  day: (x: number) => Day;
}

const bottom = (panel: Panel) => panel.top + panel.height;

function milestones(data: ChartData): Segment[] {
  return data.segments.filter((segment) => segment.key);
}

function extent(data: ChartData): [Day, Day] {
  const days = [data.today, ...data.expected.map(([d]) => d), ...data.actual.map(([d]) => d)];
  days.push(
    ...data.baseline.map(([d]) => d),
    ...data.volume.map(([d]) => d),
    ...data.remaining.map(([d]) => d),
  );
  days.push(...data.marks.map(([d]) => d));
  for (const when of [data.finish, data.baselineFinish]) if (when !== null) days.push(when);
  for (const segment of data.segments) {
    for (const span of [segment.now, segment.then]) if (span) days.push(span[0], span[1]);
  }
  const [first, last] = [Math.min(...days) - PAD_DAYS, Math.max(...days) + PAD_DAYS];
  return [first, last > first ? last : first + 1];
}

export function geometry(data: ChartData, page: Page, width: number): Geometry {
  const rows = milestones(data).length;
  const scale = volumeScale(data.volume, data.remaining);
  const panels: Panel[] = [];
  let cursor = CHART_TOP + TITLE_H;
  for (const kind of PAGE_PLOTS[page]) {
    const height = kind === "shift" ? Math.max(1, rows) * SHIFT_ROW_H : PLOT_H;
    panels.push({
      kind,
      top: cursor,
      height,
      scale: kind === "volume" || kind === "remaining" ? scale : 1,
    });
    cursor += height + PLOT_GAP + TITLE_H;
  }
  const widest = Math.max(
    0,
    ...milestones(data).map((segment) => textWidth(clip(segment.label, 20))),
  );
  const left = Math.min(GUTTER_MAX, Math.max(GUTTER_MIN, widest + GUTTER_PAD));
  const right = width - CHART_RIGHT;
  const [first, last] = extent(data);
  const span = last - first;
  return {
    first,
    last,
    left,
    right,
    panels,
    x: (day) => left + ((day - first) / span) * (right - left),
    y: (panel, value) =>
      panel.top +
      (1 - Math.max(0, Math.min(1, panel.scale ? value / panel.scale : 0))) * panel.height,
    day: (x) => Math.round(first + ((x - left) / (right - left)) * span),
  };
}

export function chartHeight(g: Geometry): number {
  return bottom(g.panels[g.panels.length - 1]) + CHART_BOTTOM;
}

/** The whole chart: its SVG and the geometry the hover reads. */
export function chartSvg(
  data: ChartData,
  page: Page,
  width: number,
  id: string,
): { svg: string; geometry: Geometry } {
  const g = geometry(data, page, width);
  const height = chartHeight(g);
  const ticks = axisTicks(g.first, g.last, Math.floor((g.right - g.left) / TICK_ROOM));
  const out = [
    `<svg class="chart" viewBox="0 0 ${n(width)} ${n(height)}" width="${n(width)}" height="${
      n(height)
    }" font-size="11">`,
  ];
  const emphasised =
    data.segments.find((segment) => segment.key && segment.key === data.emphasis) ?? null;
  for (const [index, panel] of g.panels.entries()) {
    out.push(
      `<g class="plot plot-${panel.kind}">`,
      title(data, panel, g),
      grid(data, panel, g, ticks),
    );
    const body = panel.kind === "status"
      ? statusPlot(data, panel, g)
      : panel.kind === "scope"
      ? scopePlot(data, panel, g)
      : panel.kind === "shift"
      ? shiftPlot(data, panel, g, emphasised)
      : amountPlot(data, panel, g);
    if (emphasised && (panel.kind === "status" || panel.kind === "scope")) {
      const spans = [emphasised.now, ...(panel.kind === "scope" ? [emphasised.then] : [])].filter(
        (span): span is [Day, Day] => span !== null,
      );
      const clipId = `${id}-clip-${index}`;
      out.push(`<defs><clipPath id="${clipId}">`);
      for (const [from, to] of spans) {
        out.push(
          `<rect x="${n(g.x(from) - 2)}" y="${n(panel.top - 20)}" width="${
            n(g.x(to) - g.x(from) + 4)
          }" height="${n(panel.height + 40)}"/>`,
        );
      }
      out.push(`</clipPath></defs>`);
      out.push(`<g opacity="${FADE}">${body}</g><g clip-path="url(#${clipId})">${body}</g>`);
    } else {
      out.push(body);
    }
    out.push(`</g>`);
  }
  const [top, end] = [g.panels[0].top, bottom(g.panels[g.panels.length - 1])];
  for (const [when, name] of data.marks) {
    if (when < g.first || when > g.last) continue;
    const at = g.x(when);
    const room = g.right - at > textWidth(clip(name, 18)) + 8;
    out.push(
      `<g class="mark"><line x1="${n(at)}" x2="${n(at)}" y1="${n(top)}" y2="${
        n(end)
      }" style="stroke:${INK}" stroke-opacity="0.45" stroke-dasharray="4 3"/>` +
        `<text x="${n(room ? at + 4 : at - 4)}" y="${n(top + 10)}" text-anchor="${
          room ? "start" : "end"
        }" style="fill:${SECONDARY}">${esc(clip(name, 18))}</text>` +
        `<title>saved as ${esc(name)}</title></g>`,
    );
  }
  if (emphasised?.now) {
    const at = g.x(emphasised.now[1]);
    out.push(
      `<line x1="${n(at)}" x2="${n(at)}" y1="${n(top)}" y2="${
        n(end)
      }" stroke="${emphasised.color}" stroke-opacity="0.6"/>`,
    );
  }
  if (data.today >= g.first && data.today <= g.last) {
    const at = g.x(data.today);
    out.push(
      `<line class="today" x1="${n(at)}" x2="${n(at)}" y1="${n(top)}" y2="${
        n(end)
      }" style="stroke:${SECONDARY}"/>`,
    );
  }
  for (const [when, label] of ticks) {
    out.push(
      `<text class="axis" x="${n(g.x(when))}" y="${
        n(end + 15)
      }" text-anchor="middle" style="fill:${SECONDARY}">${esc(label)}</text>`,
    );
  }
  out.push(
    `<line class="hover" x1="0" x2="0" y1="${n(top)}" y2="${
      n(end)
    }" style="stroke:${INK}" stroke-opacity="0.5" visibility="hidden"/>`,
  );
  out.push("</svg>");
  return { svg: out.join(""), geometry: g };
}

// -- the parts of a plot --------------------------------------------------------------------------

function title(data: ChartData, panel: Panel, g: Geometry): string {
  const y = panel.top - TITLE_H / 2;
  const name = panel.kind === "status"
    ? (data.asOf ? `Progress — as of ${data.asOf}` : "Progress")
    : panel.kind === "scope"
    ? scopeWords(data.basis)
    : panel.kind === "shift"
    ? "Milestones"
    : panel.kind === "volume"
    ? "Scope volume"
    : "Remaining work";
  const out = [
    `<text class="plot-title" x="${n(g.left)}" y="${
      n(y)
    }" dominant-baseline="central" font-size="12" font-weight="600" style="fill:${INK}">${
      esc(name)
    }</text>`,
  ];
  const keys = legend(data, panel);
  const width = keys.reduce((sum, [label]) => sum + 24 + textWidth(label) + 18, 0);
  if (keys.length && width <= g.right - g.left - textWidth(name, 12) - 24) {
    let cursor = g.right - width + 18;
    for (const [label, mark] of keys) {
      out.push(
        `<g class="legend">${mark(cursor, y)}<text x="${n(cursor + 24)}" y="${
          n(y)
        }" dominant-baseline="central" style="fill:${SECONDARY}">${esc(label)}</text></g>`,
      );
      cursor += 24 + textWidth(label) + 18;
    }
  }
  return out.join("");
}

type Mark = (x: number, y: number) => string;

function legend(data: ChartData, panel: Panel): [string, Mark][] {
  const line = (color: string, opacity = 1, dash = ""): Mark => (x, y) =>
    `<line x1="${n(x)}" x2="${n(x + 18)}" y1="${n(y)}" y2="${
      n(y)
    }" style="stroke:${color}" stroke-opacity="${opacity}" stroke-width="2"${
      dash ? ` stroke-dasharray="${dash}"` : ""
    }/>`;
  const patch = (color: string): Mark => (x, y) =>
    `<rect x="${n(x)}" y="${
      n(y - 5)
    }" width="18" height="10" rx="2" fill="${color}" fill-opacity="0.3"/>`;
  const dot = (fill: string, ring: string): Mark => (x, y) =>
    `<circle cx="${n(x + 9)}" cy="${
      n(y)
    }" r="4" style="fill:${fill};stroke:${ring}" stroke-width="1.5"/>`;
  if (panel.kind === "status") {
    return [
      ["Plan", line(PLAN)],
      ["Actual", line(INK)],
      ...(data.idle.length ? [["No work planned", line(PLAN, 1, "0.1 4")] as [string, Mark]] : []),
    ];
  }
  if (panel.kind === "scope") {
    return [
      ...(data.baseline.length ? [["Plan then", line(PLAN, 0.6, "6 4")] as [string, Mark]] : []),
      ["Plan now", line(PLAN)],
      ["Pulled in", patch(ATTENTION)],
      ["Slipped", patch(BAD)],
    ];
  }
  if (panel.kind === "shift") {
    const compared = data.segments.some((segment) => segment.then !== null);
    return compared ? [["Then", dot(SURFACE, SECONDARY)], ["Now", dot(SECONDARY, SECONDARY)]] : [];
  }
  if (panel.kind === "volume") return [["Estimated days", line(PLAN)]];
  return [["Total", line(PLAN, 0.55, "6 4")], ["Remaining", line(PLAN)]];
}

function grid(data: ChartData, panel: Panel, g: Geometry, ticks: [Day, string][]): string {
  const out: string[] = [];
  if (panel.kind === "shift") {
    const rows = milestones(data);
    if (!rows.length) {
      out.push(
        `<text x="${n(g.left)}" y="${
          n(panel.top + SHIFT_ROW_H / 2)
        }" dominant-baseline="central" style="fill:${SECONDARY}">No milestones yet</text>`,
      );
    }
    rows.forEach((_, index) => {
      const row = panel.top + (index + 0.5) * SHIFT_ROW_H;
      out.push(
        `<line x1="${n(g.left)}" x2="${n(g.right)}" y1="${n(row)}" y2="${
          n(row)
        }" style="stroke:${INK}" stroke-opacity="0.1"/>`,
      );
    });
  } else {
    for (const share of [0, 0.25, 0.5, 0.75, 1]) {
      const at = g.y(panel, share * panel.scale);
      out.push(
        `<line x1="${n(g.left)}" x2="${n(g.right)}" y1="${n(at)}" y2="${
          n(at)
        }" style="stroke:${INK}" stroke-opacity="0.12"/>`,
      );
      if (share === 0 || share === 0.5 || share === 1) {
        const label = panel.scale === 1 ? percent(share) : formatDays(share * panel.scale);
        out.push(
          `<text x="${n(g.left - 8)}" y="${
            n(at)
          }" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${label}</text>`,
        );
      }
    }
  }
  for (const [when] of ticks) {
    out.push(
      `<line x1="${n(g.x(when))}" x2="${n(g.x(when))}" y1="${n(panel.top)}" y2="${
        n(bottom(panel))
      }" style="stroke:${INK}" stroke-opacity="0.12"/>`,
    );
  }
  return out.join("");
}

function polyline(
  points: readonly Point[],
  panel: Panel,
  g: Geometry,
  color: string,
  extra = "",
): string {
  const coords = points.map(([when, value]) => `${n(g.x(when))},${n(g.y(panel, value))}`).join(" ");
  return `<polyline points="${coords}" fill="none" style="stroke:${color}" stroke-width="${LINE_W}" stroke-linejoin="round" stroke-linecap="round"${extra}/>`;
}

function marker(x: number, y: number, fill: string, ring: string): string {
  return `<circle cx="${n(x)}" cy="${
    n(y)
  }" r="${MARKER}" style="fill:${fill};stroke:${ring}" stroke-width="2"/>`;
}

/** `_slice`: a line between two days, its ends interpolated onto it. */
function slice(points: readonly Point[], since: Day, until: Day): Point[] {
  if (until <= since) return [];
  const cut: Point[] = points.filter(([when]) => since < when && when < until);
  const [head, tail] = [shareAt(points, since), shareAt(points, until)];
  if (head !== null) cut.unshift([since, head]);
  if (tail !== null) cut.push([until, tail]);
  return cut;
}

/** `_plan_line`: the plan in each stretch's shade, dotted across a span it leaves empty. */
function planLine(data: ChartData, points: readonly Point[], panel: Panel, g: Geometry): string {
  const runs = data.segments.filter((segment) => segment.now !== null);
  if (!runs.length) return polyline(points, panel, g, PLAN);
  const out: string[] = [];
  let previous: Day | null = null;
  for (const segment of runs) {
    const [start, finish] = segment.now!;
    const cut = slice(points, previous ?? start, finish);
    if (cut.length >= 2) out.push(polyline(cut, panel, g, segment.color));
    previous = finish;
  }
  for (const [since, until] of data.idle) {
    const level = shareAt(points, since);
    if (level === null) continue;
    const y = g.y(panel, level);
    out.push(
      `<line x1="${n(g.x(since))}" x2="${n(g.x(until))}" y1="${n(y)}" y2="${
        n(y)
      }" style="stroke:${SURFACE}" stroke-width="${LINE_W + 1}"/>` +
        `<line x1="${n(g.x(since))}" x2="${n(g.x(until))}" y1="${n(y)}" y2="${
          n(y)
        }" style="stroke:${PLAN}" stroke-width="${LINE_W}" stroke-dasharray="0.1 4" stroke-linecap="round"/>`,
    );
  }
  return out.join("");
}

function statusPlot(data: ChartData, panel: Panel, g: Geometry): string {
  const out: string[] = [];
  if (data.expected.length) {
    out.push(planLine(data, data.expected, panel, g));
    let reached = -Infinity;
    for (const segment of milestones(data)) {
      const share = segment.now ? shareAt(data.expected, segment.now[1]) : null;
      if (!segment.now || share === null) continue;
      const [at, level] = [g.x(segment.now[1]), g.y(panel, share)];
      out.push(
        `<circle cx="${n(at)}" cy="${n(level)}" r="${LANDING_MARK}" fill="${segment.color}"/>`,
      );
      const name = clip(segment.label, 16);
      if (at - textWidth(name) - 6 < reached) continue;
      out.push(
        `<text x="${n(at - 6)}" y="${
          n(Math.max(panel.top + 6, level - 12))
        }" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${
          esc(name)
        }</text>`,
      );
      reached = at - 6;
    }
    const [when, share] = data.expected[data.expected.length - 1];
    const last = data.segments.filter((segment) => segment.now).pop()?.color ?? PLAN;
    out.push(marker(g.x(when), g.y(panel, share), last, SURFACE));
  }
  if (data.actual.length) {
    out.push(polyline(data.actual, panel, g, INK));
    const [when, share] = data.actual[data.actual.length - 1];
    out.push(marker(g.x(when), g.y(panel, share), INK, SURFACE));
    const words = standingWords(data.standing);
    if (words) {
      const flipped = g.x(when) + 8 + textWidth(words) > g.right;
      out.push(
        `<text class="standing" x="${n(g.x(when) + (flipped ? -8 : 8))}" y="${
          n(g.y(panel, share))
        }" dominant-baseline="central" text-anchor="${
          flipped ? "end" : "start"
        }" style="fill:${INK}" font-weight="600">${esc(words)}</text>`,
      );
    }
  }
  return out.join("");
}

function scopePlot(data: ChartData, panel: Panel, g: Geometry): string {
  const out: string[] = [];
  if (data.expected.length && data.baseline.length) {
    for (const [sign, run] of changeRuns(data.expected, data.baseline)) {
      if (sign === 0) {
        const line = run.map(([when, high]) => `${n(g.x(when))},${n(g.y(panel, high))}`).join(" ");
        out.push(
          `<polyline points="${line}" fill="none" stroke="${GOOD}" stroke-width="${
            LINE_W + 1
          }" stroke-opacity="0.8" stroke-linecap="round"/>`,
        );
        continue;
      }
      const ring = [
        ...run.map(([when, high]) => `${n(g.x(when))},${n(g.y(panel, high))}`),
        ...[...run].reverse().map(([when, , low]) => `${n(g.x(when))},${n(g.y(panel, low))}`),
      ];
      out.push(
        `<polygon points="${ring.join(" ")}" fill="${
          sign > 0 ? ATTENTION : BAD
        }" fill-opacity="0.25"/>`,
      );
    }
  }
  if (data.expected.length) {
    out.push(planLine(data, data.expected, panel, g));
    const [when, share] = data.expected[data.expected.length - 1];
    out.push(marker(g.x(when), g.y(panel, share), PLAN, SURFACE));
  }
  if (data.baseline.length) {
    // The plan then over the plan now, paler and dashed: unchanged reads as two lines in one place.
    out.push(
      polyline(data.baseline, panel, g, "#3f5f9f", ` stroke-dasharray="6 4" stroke-opacity="0.75"`),
    );
    const [when, share] = data.baseline[data.baseline.length - 1];
    out.push(marker(g.x(when), g.y(panel, share), SURFACE, PLAN));
  }
  return out.join("");
}

function shiftPlot(data: ChartData, panel: Panel, g: Geometry, emphasised: Segment | null): string {
  const out: string[] = [];
  milestones(data).forEach((segment, index) => {
    const row = panel.top + (index + 0.5) * SHIFT_ROW_H;
    const faded = emphasised && emphasised !== segment ? ` opacity="${FADE}"` : "";
    out.push(`<g class="shift"${faded}><title>${esc(segment.words)}</title>`);
    const [then, now] = [segment.then?.[1] ?? null, segment.now?.[1] ?? null];
    if (now !== null) {
      out.push(
        `<line x1="${n(g.x(now))}" x2="${n(g.x(now))}" y1="${n(row)}" y2="${
          n(bottom(panel))
        }" stroke="${segment.color}" stroke-opacity="0.35"/>`,
      );
    }
    out.push(
      `<text x="${n(g.left - 8)}" y="${
        n(row)
      }" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${
        esc(clip(segment.label, 20))
      }</text>`,
    );
    if (then !== null && now !== null && then !== now) {
      out.push(arrow(g.x(then), g.x(now), row, segment.color));
    }
    if (then !== null) {
      out.push(
        `<circle cx="${n(g.x(then))}" cy="${n(row)}" r="${
          MARKER + (then === now ? 1.5 : 0)
        }" style="fill:${SURFACE}" stroke="${segment.color}" stroke-width="1.5"/>`,
      );
    }
    if (now !== null) {
      out.push(
        `<circle cx="${n(g.x(now))}" cy="${n(row)}" r="${LANDING_MARK}" fill="${segment.color}"/>`,
      );
    }
    for (const [text, at] of rowDates(then, now, data.today, g)) {
      out.push(
        `<text x="${n(at)}" y="${n(row)}" dominant-baseline="central" style="fill:${SECONDARY}">${
          esc(text)
        }</text>`,
      );
    }
    out.push(`</g>`);
  });
  return out.join("");
}

/** `_row_dates`: each mark's date beside it, outside the pair when there is room, never squeezed. */
function rowDates(then: Day | null, now: Day | null, today: Day, g: Geometry): [string, number][] {
  const found: [string, number][] = [];
  const spots: [Day, Day | null][] = now !== null ? [[now, then]] : [];
  if (then !== null && then !== now) spots.push([then, now]);
  for (const [when, other] of spots) {
    const text = shortDate(when, today);
    const width = textWidth(text);
    const mark = g.x(when);
    const away = other !== null && g.x(other) > mark ? -1 : 1;
    for (const way of [away, -away]) {
      const start = way > 0 ? mark + LANDING_MARK + 5 : mark - LANDING_MARK - 5 - width;
      if (start < g.left || start + width > g.right) continue;
      if (other !== null) {
        const keep = g.x(other);
        if (start < keep + LANDING_MARK + 5 && keep - LANDING_MARK - 5 < start + width) continue;
      }
      found.push([text, start]);
      break;
    }
  }
  return found;
}

function arrow(start: number, end: number, row: number, color: string): string {
  const way = end >= start ? 1 : -1;
  const tip = end - way * (LANDING_MARK + 1);
  const head = `M${n(tip)},${n(row)} L${n(tip - way * ARROW_HEAD)},${n(row - ARROW_HEAD * 0.55)} L${
    n(tip - way * ARROW_HEAD)
  },${n(row + ARROW_HEAD * 0.55)} Z`;
  return `<line x1="${n(start)}" x2="${n(tip)}" y1="${n(row)}" y2="${
    n(row)
  }" stroke="${color}" stroke-width="1.5" stroke-opacity="0.8"/><path d="${head}" fill="${color}" fill-opacity="0.8"/>`;
}

function amountPlot(data: ChartData, panel: Panel, g: Geometry): string {
  const out: string[] = [];
  const own = panel.kind === "volume" ? data.volume : data.remaining;
  if (panel.kind === "remaining" && data.volume.length) {
    out.push(
      polyline(data.volume, panel, g, PLAN, ` stroke-dasharray="6 4" stroke-opacity="0.55"`),
    );
  }
  if (own.length) {
    out.push(polyline(own, panel, g, PLAN));
    const [when, value] = own[own.length - 1];
    out.push(marker(g.x(when), g.y(panel, value), PLAN, SURFACE));
  }
  return out.join("");
}

// -- reading a chart under the pointer --------------------------------------------------------------

/** What the tooltip says at a day, for the plot under the pointer — `chart.py`'s tooltip. */
export function readout(data: ChartData, kind: Kind, day: Day): string[] {
  const at = (points: readonly Point[]) => shareAt(points, day);
  const share = (
    label: string,
    value: number | null,
  ) => (value === null ? [] : [`${label}: ${percent(value)} of days`]);
  const days = (
    label: string,
    value: number | null,
  ) => (value === null ? [] : [`${label}: ${formatDays(value)}`]);
  const saved = data.marks.filter(([when]) => when === day).map(([, name]) => `saved as ${name}`);
  if (kind === "status") {
    return [...share("plan now", at(data.expected)), ...share("actual", at(data.actual)), ...saved];
  }
  if (kind === "scope") {
    return [
      ...share("plan now", at(data.expected)),
      ...share(data.basis || "then", at(data.baseline)),
      ...saved,
    ];
  }
  if (kind === "shift") {
    return [...data.segments.filter((s) => s.key).map((s) => s.words), ...saved];
  }
  const total = at(data.volume);
  const left = at(data.remaining);
  return [
    ...days("scope", total),
    ...(left !== null && total !== null
      ? [`remaining: ${formatDays(left)} · done ${formatDays(total - left)}`]
      : []),
    ...saved,
  ];
}
