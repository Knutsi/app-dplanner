/**
 * Track record — how good the forecasts were. Not a DPlanner view (yet): the question the
 * prototype exists to answer.
 *
 * A milestone trend chart: across, the day a forecast was recorded; up, the landing it gave.
 * A forecast that holds is flat. The diagonal is "today", so a milestone lands where its
 * line meets the diagonal — and its true landing is marked there, with a faint level across
 * the chart, so the gap between each forecast and the truth is read straight off the page.
 */

import { axisTicks, type Day, formatDate, shortDate } from "../../model/calendar.ts";
import { isMilestone, milestoneLabel, placed, type Plan } from "../../model/graph.ts";
import { milestoneColors, WHOLE_COLOR } from "../../model/palettes.ts";
import {
  actual,
  baseline,
  expected,
  landingIn,
  landingShift,
  type Snapshot,
  standing,
  standingWords,
} from "../../model/progress.ts";
import type { Recording, Timeline } from "../../sim/timeline.ts";
import { snapshotOf } from "../../sim/timeline.ts";
import type { ModelOptions } from "../../model/options.ts";
import { esc, h, INK, n, SECONDARY } from "../markup.ts";

interface Series {
  key: string | null;
  label: string;
  color: string;
  truth: Day | null; // When it really landed, if it had by today.
}

function seriesOf(plan: Plan, timeline: Timeline, today: Day): Series[] {
  const colors = milestoneColors(plan, plan.assumptions.palette);
  const found: Series[] = placed(plan).map((place) => place.step).filter(isMilestone).map(
    (step) => {
      const truth = timeline.finished.get(step.id) ?? null;
      return {
        key: step.id,
        label: milestoneLabel(step),
        color: colors.get(step.id)!,
        truth: truth !== null && truth <= today ? truth : null,
      };
    },
  );
  const everything = plan.steps.map((step) => timeline.finished.get(step.id) ?? null);
  const last = everything.every((day) => day !== null) ? Math.max(...(everything as Day[])) : null;
  found.push({
    key: null,
    label: "All work",
    color: WHOLE_COLOR,
    truth: last !== null && last <= today ? last : null,
  });
  return found;
}

/** Each record's forecast for one milestone: [record day, landing]. */
function forecasts(rows: readonly Snapshot[], key: string | null): [Day, Day][] {
  return rows.flatMap((row) => {
    const landing = landingIn(row, key);
    return landing === null || (key !== null && !row.stretches.some((s) => s.key === key))
      ? []
      : [[row.day, landing] as [Day, Day]];
  });
}

export function trackRecord(
  timeline: Timeline,
  recording: Recording,
  compared: Recording | null,
  options: ModelOptions,
  index: number,
): HTMLElement {
  const today = timeline.frames[index].day;
  const plan = timeline.frames[timeline.frames.length - 1].plan;
  const rows = recording.rows.filter((row) => row.day <= today);
  const others = compared?.rows.filter((row) => row.day <= today) ?? [];
  const series = seriesOf(plan, timeline, today);
  if (!rows.length) {
    return h(
      "div",
      { class: "track" },
      h(
        "p",
        { class: "note" },
        "Nothing recorded yet — scrub forward, or pick a recorder that runs on more days.",
      ),
    );
  }
  return h(
    "div",
    { class: "track" },
    h(
      "p",
      { class: "lede" },
      "Each line is one milestone's landing date, as the plan said it on each recorded day. A forecast that holds is flat; ",
      "where a line meets the diagonal, that day is the landing it promised. ◆ marks where the milestone really landed.",
      compared
        ? " Dashed lines are DPlanner as it is today; solid ones are the model the page runs, re-planned from today with any variants switched on."
        : "",
    ),
    h("div", { html: trendSvg(series, rows, others, today, timeline) }),
    errorTable(series, rows, others, today, Boolean(compared)),
    h("h3", {}, "What the Progress plot said each day"),
    h(
      "p",
      { class: "lede" },
      "The ahead/behind the Time tab printed beside today's dot, day by day — the only warning a reader gets that the plan is slipping.",
    ),
    h("div", { html: standingSvg(timeline, recording, options, index) }),
  );
}

function trendSvg(
  series: Series[],
  rows: readonly Snapshot[],
  others: readonly Snapshot[],
  today: Day,
  timeline: Timeline,
): string {
  const [width, height, left, right, top, bottom] = [1000, 380, 70, 60, 16, 30];
  const lines = series.map((one) => forecasts(rows, one.key));
  const shadows = series.map((one) => forecasts(others, one.key));
  const days = [timeline.frames[0].day, today];
  for (const line of [...lines, ...shadows]) {
    for (const [made, lands] of line) days.push(made, lands);
  }
  for (const one of series) if (one.truth !== null) days.push(one.truth);
  const [xFirst, xLast] = [Math.min(...days.slice(0, 2), ...rows.map((row) => row.day)), today + 1];
  const [yFirst, yLast] = [Math.min(...days) - 1, Math.max(...days) + 2];
  const x = (day: Day) =>
    left + ((day - xFirst) / Math.max(1, xLast - xFirst)) * (width - left - right);
  const y = (day: Day) =>
    top + (1 - (day - yFirst) / Math.max(1, yLast - yFirst)) * (height - top - bottom);
  const out = [
    `<svg class="chart" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-size="11">`,
  ];
  for (const [when, label] of axisTicks(xFirst, xLast, 10)) {
    out.push(
      `<line x1="${n(x(when))}" x2="${n(x(when))}" y1="${top}" y2="${
        height - bottom
      }" style="stroke:${INK}" stroke-opacity="0.1"/>`,
    );
    out.push(
      `<text x="${n(x(when))}" y="${
        height - bottom + 15
      }" text-anchor="middle" style="fill:${SECONDARY}">${esc(label)}</text>`,
    );
  }
  for (const [when, label] of axisTicks(yFirst, yLast, 8)) {
    out.push(
      `<line x1="${left}" x2="${width - right}" y1="${n(y(when))}" y2="${
        n(y(when))
      }" style="stroke:${INK}" stroke-opacity="0.1"/>`,
    );
    out.push(
      `<text x="${left - 8}" y="${
        n(y(when))
      }" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${
        esc(label)
      }</text>`,
    );
  }
  const low = Math.max(xFirst, yFirst);
  const high = Math.min(xLast, yLast);
  out.push(
    `<line x1="${n(x(low))}" y1="${n(y(low))}" x2="${n(x(high))}" y2="${
      n(y(high))
    }" style="stroke:${INK}" stroke-opacity="0.35" stroke-dasharray="2 3"><title>today: a forecast on this line is due that very day</title></line>`,
  );
  const step = (line: [Day, Day][], end: Day) =>
    line.flatMap(([made, lands], index) => {
      const until = index + 1 < line.length ? line[index + 1][0] : end;
      return [`${n(x(made))},${n(y(lands))}`, `${n(x(until))},${n(y(lands))}`];
    }).join(" ");
  const labelled: number[] = [];
  series.forEach((one, index) => {
    const end = one.truth !== null ? Math.min(one.truth, today) : today;
    // A record made on the landing day forecasts nothing: the milestone has landed.
    const before = ([made]: [Day, Day]) => (one.truth !== null ? made < end : made <= end);
    if (one.truth !== null) {
      out.push(
        `<line x1="${left}" x2="${n(x(one.truth))}" y1="${n(y(one.truth))}" y2="${
          n(y(one.truth))
        }" stroke="${one.color}" stroke-opacity="0.35" stroke-dasharray="1 3"/>`,
      );
    }
    if (shadows[index].length) {
      out.push(
        `<polyline points="${
          step(shadows[index].filter(before), end)
        }" fill="none" stroke="${one.color}" stroke-width="1.5" stroke-dasharray="5 4" stroke-opacity="0.8"/>`,
      );
    }
    const line = lines[index].filter(before);
    if (line.length) {
      out.push(
        `<polyline points="${step(line, end)}" fill="none" stroke="${one.color}" stroke-width="${
          one.key === null ? 1.5 : 2
        }"><title>${esc(one.label)}</title></polyline>`,
      );
      let at = y(line[line.length - 1][1]);
      while (labelled.some((taken) => Math.abs(taken - at) < 12)) at += 12;
      labelled.push(at);
      out.push(
        `<text x="${n(Math.min(x(end), width - right) + 4)}" y="${
          n(at)
        }" dominant-baseline="central" style="fill:${SECONDARY}">${esc(one.label)}</text>`,
      );
    }
    if (one.truth !== null) {
      const [cx, cy] = [x(one.truth), y(one.truth)];
      out.push(
        `<path d="M${n(cx)},${n(cy - 6)} L${n(cx + 6)},${n(cy)} L${n(cx)},${n(cy + 6)} L${
          n(cx - 6)
        },${n(cy)} Z" fill="${one.color}"><title>${esc(one.label)} really landed ${
          esc(formatDate(one.truth, today))
        }</title></path>`,
      );
    }
  });
  out.push(
    `<text x="${left}" y="${
      height - 4
    }" style="fill:${SECONDARY}">day the forecast was recorded →</text>`,
  );
  out.push(`<text x="10" y="${top + 4}" style="fill:${SECONDARY}">lands ↑</text>`);
  out.push("</svg>");
  return out.join("");
}

function errorTable(
  series: Series[],
  rows: readonly Snapshot[],
  others: readonly Snapshot[],
  today: Day,
  compared: boolean,
): HTMLElement {
  const table = h("table", { class: "errors" });
  table.append(
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        ...[
          "Milestone",
          "Really landed",
          "Said at the start",
          "at ¼ of the way",
          "at ½",
          "at ¾",
          "last before landing",
        ].map((name) => h("th", {}, name)),
      ),
    ),
  );
  const body = h("tbody");
  for (const one of series) {
    const cells = (source: readonly Snapshot[]) => {
      const line = forecasts(source, one.key);
      if (!line.length) return Array(5).fill("—");
      const said = (row: Snapshot | null) => (row ? landingIn(row, one.key) : null);
      const first = line[0][0];
      const truth = one.truth;
      const at = (share: number) => {
        if (truth === null) return null;
        return said(baseline(source, first + Math.round((truth - first) * share)));
      };
      const lastBefore = truth === null ? null : said(baseline(source, truth - 1));
      const picks = [line[0][1], at(0.25), at(0.5), at(0.75), lastBefore];
      return picks.map((forecast) => {
        if (forecast === null) return "—";
        if (truth === null) return shortDate(forecast, today);
        const shift = landingShift(forecast, truth);
        return `${shortDate(forecast, today)} (${
          shift === 0 ? "exact" : `${shift > 0 ? "+" : ""}${shift}d`
        })`;
      });
    };
    const mine = cells(rows);
    const theirs = compared ? cells(others) : null;
    body.append(
      h(
        "tr",
        {},
        h("td", {}, h("span", { class: "badge", style: `background:${one.color}` }), one.label),
        h("td", {}, one.truth !== null ? shortDate(one.truth, today) : "not yet"),
        ...mine.map((text, index) =>
          h(
            "td",
            { class: "number" },
            text,
            theirs ? h("div", { class: "subtitle" }, `today's model: ${theirs[index]}`) : null,
          )
        ),
      ),
    );
  }
  table.append(body);
  return h(
    "div",
    {},
    table,
    h(
      "p",
      { class: "note" },
      "(+3d) means it really landed three working days after that forecast; (−2d), two before it. ¼, ½ and ¾ are points between the first record and the real landing.",
    ),
  );
}

function standingSvg(
  timeline: Timeline,
  recording: Recording,
  options: ModelOptions,
  index: number,
): string {
  const [width, height, left, right, top, bottom] = [1000, 150, 70, 60, 12, 26];
  const points: [Day, number][] = [];
  for (const frame of timeline.frames.slice(0, index + 1)) {
    const live = snapshotOf(frame.plan, frame.day, options);
    if (!live) continue;
    const rows = recording.rows.filter((row) => row.day <= frame.day);
    const found = standing(expected(live, null), actual(rows, live, null), frame.day);
    if (found !== null) points.push([frame.day, found]);
  }
  if (!points.length) return `<p class="note">No reading yet.</p>`;
  const reach = Math.max(0.1, ...points.map(([, value]) => Math.abs(value)));
  const [first, last] = [points[0][0], Math.max(points[points.length - 1][0], points[0][0] + 1)];
  const x = (day: Day) => left + ((day - first) / (last - first)) * (width - left - right);
  const y = (value: number) => top + (1 - (value + reach) / (2 * reach)) * (height - top - bottom);
  const out = [
    `<svg class="chart" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-size="11">`,
  ];
  for (
    const [value, label] of [[reach, "ahead"], [0, "on plan"], [-reach, "behind"]] as [
      number,
      string,
    ][]
  ) {
    out.push(
      `<line x1="${left}" x2="${width - right}" y1="${n(y(value))}" y2="${
        n(y(value))
      }" style="stroke:${INK}" stroke-opacity="${value ? 0.1 : 0.35}"/>`,
    );
    out.push(
      `<text x="${left - 8}" y="${
        n(y(value))
      }" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${label}</text>`,
    );
  }
  for (const [when, label] of axisTicks(first, last, 10)) {
    out.push(
      `<text x="${n(x(when))}" y="${height - 8}" text-anchor="middle" style="fill:${SECONDARY}">${
        esc(label)
      }</text>`,
    );
  }
  out.push(
    `<polyline points="${
      points.map(([d, v]) => `${n(x(d))},${n(y(v))}`).join(" ")
    }" fill="none" style="stroke:${INK}" stroke-width="1.5"/>`,
  );
  for (const [day, value] of points) {
    out.push(
      `<circle cx="${n(x(day))}" cy="${n(y(value))}" r="2.5" style="fill:${INK}"><title>${
        esc(formatDate(day, day))
      }: ${esc(standingWords(value))}</title></circle>`,
    );
  }
  out.push("</svg>");
  return out.join("");
}
