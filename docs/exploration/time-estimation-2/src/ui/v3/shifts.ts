/**
 * The Milestones tab: v1's milestone shift view, restored and given the room of a tab.
 *
 * One row per milestone: where the plan compared with landed it (a hollow ring), where the
 * plan now lands it (a dot), an arrow between, the dates beside them and a line dropped to
 * the axis. One addition: a milestone that is done ends in a circle with a check, on the
 * day it was first recorded done.
 */

import { axisTicks, type Day, shortDate } from "../../model/calendar.ts";
import type { Brief, Scope } from "../../brief.ts";
import type { TimeView } from "../../present.ts";
import { clip, esc, INK, n, SECONDARY, textWidth } from "../markup.ts";
import { CHECK_R, landedCheck } from "./marks.ts";

const ROW_H = 34;
const LEFT = 230;
const RIGHT = 80;
const TOP = 28;
const BOTTOM = 26;
const DOT = 4.5;

export interface ShiftRow {
  key: string;
  top: number;
  bottom: number;
}

export interface Shifts {
  svg: string;
  rows: ShiftRow[];
}

function arrow(from: number, to: number, y: number, color: string): string {
  const way = to >= from ? 1 : -1;
  const tip = to - way * (DOT + 2);
  if (Math.abs(tip - from) < 6) return "";
  return `<line x1="${n(from + way * (DOT + 1))}" x2="${n(tip)}" y1="${n(y)}" y2="${
    n(y)
  }" stroke="${color}" stroke-width="1.5" stroke-opacity="0.85"/>` +
    `<path d="M${n(tip)},${n(y)} L${n(tip - way * 6)},${n(y - 3.5)} L${n(tip - way * 6)},${
      n(y + 3.5)
    } Z" fill="${color}" fill-opacity="0.85"/>`;
}

function words(scope: Scope, today: Day): string {
  const parts = [`${scope.badge} ${scope.label}${scope.title ? ` — ${scope.title}` : ""}`];
  if (scope.move.then !== null) parts.push(`then: ${shortDate(scope.move.then, today)}`);
  if (scope.landedBy !== null) parts.push(`done by ${shortDate(scope.landedBy, today)}`);
  else if (scope.move.planned !== null) {
    parts.push(`plan now: ${shortDate(scope.move.planned, today)}`);
  }
  return parts.join("\n");
}

export function shiftsSvg(
  found: Brief,
  view: TimeView,
  selected: string | null,
  width: number,
): Shifts {
  const today = view.today;
  const scopes = found.milestones.filter((scope) => scope.key);
  const days = [today];
  for (const scope of scopes) {
    for (const day of [scope.move.then, scope.move.planned, scope.landedBy]) {
      if (day !== null) days.push(day);
    }
  }
  for (const row of view.recording.saved) days.push(row.day);
  const [first, last] = [Math.min(...days) - 2, Math.max(...days) + 3];
  const plotW = width - LEFT - RIGHT;
  const x = (day: Day) => LEFT + ((day - first) / (last - first)) * plotW;
  const height = TOP + Math.max(1, scopes.length) * ROW_H + BOTTOM;
  const bottom = height - BOTTOM;
  const out = [
    `<svg class="chart shifts" viewBox="0 0 ${n(width)} ${n(height)}" width="${n(width)}" height="${
      n(height)
    }" font-size="12">`,
  ];
  const rows: ShiftRow[] = [];

  const ticks = axisTicks(first, last, Math.max(1, Math.floor(plotW / 70)));
  for (const [when, label] of ticks) {
    out.push(
      `<line x1="${n(x(when))}" x2="${n(x(when))}" y1="${TOP}" y2="${
        n(bottom)
      }" style="stroke:${INK}" stroke-opacity="0.08"/>`,
    );
    // "today" is the label that matters; a date that would touch it gives way.
    if (Math.abs(x(when) - x(today)) < 34) continue;
    out.push(
      `<text x="${n(x(when))}" y="${
        n(height - 8)
      }" text-anchor="middle" style="fill:${SECONDARY}" font-size="11">${esc(label)}</text>`,
    );
  }
  if (!scopes.length) {
    out.push(
      `<text x="${LEFT}" y="${
        TOP + ROW_H / 2
      }" dominant-baseline="central" style="fill:${SECONDARY}">No milestones yet</text>`,
    );
  }

  scopes.forEach((scope, index) => {
    const y = TOP + (index + 0.5) * ROW_H;
    rows.push({ key: scope.key!, top: y - ROW_H / 2, bottom: y + ROW_H / 2 });
    const faded = selected !== null && selected !== scope.key ? ` opacity="0.35"` : "";
    out.push(`<g class="shift-row"${faded}><title>${esc(words(scope, today))}</title>`);
    if (selected === scope.key) {
      out.push(
        `<rect x="0" y="${n(y - ROW_H / 2)}" width="${
          n(width)
        }" height="${ROW_H}" class="row-picked"/>`,
      );
    }
    out.push(
      `<line x1="${LEFT}" x2="${n(LEFT + plotW)}" y1="${n(y)}" y2="${
        n(y)
      }" style="stroke:${INK}" stroke-opacity="0.08"/>`,
    );
    // The name: the key badge in the milestone's colour, then its label and title.
    const badgeW = textWidth(scope.badge, 10) + 10;
    out.push(
      `<rect x="8" y="${n(y - 8)}" width="${n(badgeW)}" height="16" rx="4" fill="${scope.color}"/>`,
    );
    out.push(
      `<text x="${n(8 + badgeW / 2)}" y="${
        n(y)
      }" text-anchor="middle" dominant-baseline="central" fill="#fff" font-size="10" font-weight="600">${
        esc(scope.badge)
      }</text>`,
    );
    out.push(
      `<text x="${n(16 + badgeW)}" y="${
        n(y)
      }" dominant-baseline="central" style="fill:${INK}" font-weight="600">${
        esc(scope.label)
      }</text>`,
    );
    if (scope.title) {
      const room = Math.floor((LEFT - 24 - badgeW - textWidth(scope.label, 12) - 8) / (12 * 0.56));
      if (room > 4) {
        out.push(
          `<text x="${n(24 + badgeW + textWidth(scope.label, 12))}" y="${
            n(y)
          }" dominant-baseline="central" style="fill:${SECONDARY}">${
            esc(clip(scope.title, room))
          }</text>`,
        );
      }
    }

    const then = scope.move.then;
    const done = scope.landedBy;
    const end = done ?? scope.move.planned;
    if (end !== null) {
      out.push(
        `<line x1="${n(x(end))}" x2="${n(x(end))}" y1="${n(y)}" y2="${
          n(bottom)
        }" stroke="${scope.color}" stroke-opacity="0.3"/>`,
      );
    }
    if (then !== null && end !== null && then !== end) {
      out.push(arrow(x(then), x(end), y, scope.color));
    }
    if (then !== null) {
      out.push(
        `<circle cx="${n(x(then))}" cy="${n(y)}" r="${
          DOT + (then === end ? 2 : 0)
        }" style="fill:var(--surface)" stroke="${scope.color}" stroke-width="1.6"/>`,
      );
    }
    if (done !== null) out.push(landedCheck(x(done), y, scope.color));
    else if (end !== null) {
      out.push(`<circle cx="${n(x(end))}" cy="${n(y)}" r="${DOT}" fill="${scope.color}"/>`);
    }

    // Dates beside the marks: the outer end of each, left out rather than squeezed.
    const labels: [string, number, "start" | "end", string][] = [];
    if (end !== null) {
      const rightward = then === null || then <= end;
      const offset = (done !== null ? CHECK_R : DOT) + 6;
      labels.push([
        shortDate(end, today),
        rightward ? x(end) + offset : x(end) - offset,
        rightward ? "start" : "end",
        INK,
      ]);
    }
    if (then !== null && then !== end) {
      const leftward = end === null || then <= end;
      labels.push([
        shortDate(then, today),
        leftward ? x(then) - DOT - 6 : x(then) + DOT + 6,
        leftward ? "end" : "start",
        SECONDARY,
      ]);
    }
    const spans = labels.map(([text, at, anchor]) =>
      anchor === "start" ? [at, at + textWidth(text, 11)] : [at - textWidth(text, 11), at]
    );
    labels.forEach(([text, at, anchor, ink], position) => {
      const [left, right] = spans[position];
      const clash = position === 1 && spans[0] && left < spans[0][1] && spans[0][0] < right;
      if (clash || left < LEFT - 4 || right > width - 2) return;
      out.push(
        `<text x="${n(at)}" y="${
          n(y)
        }" text-anchor="${anchor}" dominant-baseline="central" font-size="11" style="fill:${ink}">${
          esc(text)
        }</text>`,
      );
    });
    out.push(`</g>`);
  });

  for (const row of view.recording.saved) {
    const at = x(row.day);
    out.push(
      `<line x1="${n(at)}" x2="${n(at)}" y1="${TOP - 4}" y2="${
        n(bottom)
      }" style="stroke:${INK}" stroke-opacity="0.4" stroke-dasharray="4 3"><title>${
        esc(`saved: ${row.title}`)
      }</title></line>`,
    );
    out.push(
      `<text x="${n(at + 4)}" y="${TOP - 8}" style="fill:${SECONDARY}" font-size="11">${
        esc(clip(row.title, 20))
      }</text>`,
    );
  }
  out.push(
    `<line x1="${n(x(today))}" x2="${n(x(today))}" y1="${TOP - 4}" y2="${
      n(bottom)
    }" class="today-line"/>`,
  );
  out.push(
    `<text x="${n(x(today))}" y="${
      n(height - 8)
    }" text-anchor="middle" font-size="11" font-weight="600" style="fill:${INK}" class="today-label">today</text>`,
  );
  out.push("</svg>");
  return { svg: out.join(""), rows };
}
