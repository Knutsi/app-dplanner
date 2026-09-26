/**
 * The milestones as the page's navigation: a listbox, one row per scope, each with its
 * verdict, its landing and a small Gantt on one shared time axis. Picking a row (click, or
 * ↑/↓ while the list has focus) chooses what the detail below is about.
 *
 * The Gantt reads without a legend: the plan compared with is a ghost outline, the plan now
 * a bar, the work done fills it up to the day that work was due — so the gap to the today
 * line *is* the lag — and the lag itself extends the bar with ▶ glyphs to the landing at
 * today's pace. Milestone colour stays on the badge; bars are ink, status colour sits on the
 * verdict alone.
 */

import { axisTicks, type Day, shortDate } from "../../model/calendar.ts";
import type { Brief, Scope } from "../../brief.ts";
import type { TimeView } from "../../present.ts";
import { esc, h, INK, n, SECONDARY } from "../markup.ts";
import { verdictChip } from "./headline.ts";
import { alongSegment, glyphPath } from "../glyphs.ts";
import type { V2Handlers, V2State } from "./state.ts";
import { moveChip, moveParts } from "./words.ts";

const ROW_H = 26;
let refocus = false;

function extent(scopes: Scope[], today: Day): [Day, Day] {
  const days = [today];
  for (const scope of scopes) {
    for (const span of [scope.span, scope.thenSpan]) {
      if (span) days.push(span[0], ...(span[1] !== null ? [span[1]] : []));
    }
    for (const day of [scope.move.projected, scope.move.planned, scope.move.then]) {
      if (day !== null) days.push(day);
    }
  }
  return [Math.min(...days) - 1, Math.max(...days) + 3];
}

function ganttRow(scope: Scope, today: Day, first: Day, last: Day, width: number): string {
  const x = (day: Day) => ((day - first) / (last - first)) * width;
  const mid = ROW_H / 2;
  const out = [`<svg viewBox="0 0 ${n(width)} ${ROW_H}" width="${n(width)}" height="${ROW_H}">`];
  const thenSpan = scope.thenSpan;
  if (thenSpan && thenSpan[1] !== null) {
    out.push(
      `<rect x="${n(x(thenSpan[0]))}" y="${mid - 7}" width="${
        n(Math.max(2, x(thenSpan[1] + 1) - x(thenSpan[0])))
      }" height="14" rx="3" fill="none" style="stroke:${SECONDARY}" stroke-dasharray="3 2"><title>${
        esc(`then: ${shortDate(thenSpan[0], today)} → ${shortDate(thenSpan[1], today)}`)
      }</title></rect>`,
    );
  }
  const span = scope.span;
  const planned = scope.move.planned;
  if (span && planned !== null) {
    const [from, to] = [x(span[0]), x(planned + 1)];
    out.push(
      `<rect x="${n(from)}" y="${mid - 5}" width="${
        n(Math.max(2, to - from))
      }" height="10" rx="2" style="fill:${INK}" fill-opacity="0.16"><title>${
        esc(`planned ${shortDate(span[0], today)} → ${shortDate(planned, today)}`)
      }</title></rect>`,
    );
    const earned = scope.landedBy ?? scope.pace.earned;
    if (earned !== null && earned >= span[0]) {
      const end = x(Math.min(earned, planned) + 1);
      out.push(
        `<rect x="${n(from)}" y="${mid - 5}" width="${
          n(Math.max(1, end - from))
        }" height="10" rx="2" style="fill:${INK}" fill-opacity="0.5"><title>${
          esc(`the work done was due by ${shortDate(earned, today)}`)
        }</title></rect>`,
      );
    }
    const projected = scope.move.projected;
    if (projected !== null && projected > planned) {
      const [start, end] = [x(planned + 1), x(projected + 1)];
      out.push(
        `<rect x="${n(start)}" y="${mid - 5}" width="${
          n(end - start)
        }" height="10" rx="2" class="lag-fill"><title>${
          esc(`${scope.pace.lag} working days at today's pace`)
        }</title></rect>`,
      );
      for (const glyph of alongSegment(start, end, mid, 9)) {
        out.push(`<path d="${glyphPath({ ...glyph, size: 6 }, "right")}" class="lag-glyph"/>`);
      }
    }
  }
  if (scope.move.then !== null) {
    out.push(
      `<circle cx="${
        n(x(scope.move.then + 0.5))
      }" cy="${mid}" r="4" style="fill:var(--surface);stroke:${SECONDARY}" stroke-width="1.5"><title>${
        esc(`then it landed ${shortDate(scope.move.then, today)}`)
      }</title></circle>`,
    );
  }
  const lands = scope.landedBy ?? scope.move.projected;
  if (lands !== null) {
    out.push(`<circle cx="${n(x(lands + 0.5))}" cy="${mid}" r="3.5" style="fill:${INK}"/>`);
  }
  out.push(
    `<line x1="${n(x(today + 0.5))}" x2="${
      n(x(today + 0.5))
    }" y1="0" y2="${ROW_H}" class="today-line"/>`,
  );
  out.push("</svg>");
  return out.join("");
}

function axis(first: Day, last: Day, today: Day, width: number): string {
  const x = (day: Day) => ((day - first) / (last - first)) * width;
  const out = [`<svg viewBox="0 0 ${n(width)} 18" width="${n(width)}" height="18">`];
  for (const [when, label] of axisTicks(first, last, Math.max(1, Math.floor(width / 64)))) {
    // "today" is the label that matters; a date that would touch it gives way.
    if (Math.abs(x(when) - x(today)) < 34) continue;
    out.push(
      `<text x="${
        n(x(when + 0.5))
      }" y="12" text-anchor="middle" style="fill:${SECONDARY}" font-size="11">${esc(label)}</text>`,
    );
  }
  out.push(
    `<text x="${
      n(x(today + 0.5))
    }" y="12" text-anchor="middle" font-size="11" font-weight="600" style="fill:${INK}">today</text>`,
  );
  out.push("</svg>");
  return out.join("");
}

export function timeline(
  view: TimeView,
  found: Brief,
  state: V2State,
  on: V2Handlers,
  basis: string,
): HTMLElement {
  const scopes = [found.whole, ...found.milestones];
  const [first, last] = extent(scopes, view.today);
  const choose = (scope: Scope) => on.state({ scope: scope.key });
  const selected = scopes.find((scope) => scope.key === state.scope) ?? found.whole;
  const holders: [Scope, HTMLElement][] = [];
  const axisHolder = h("div", { class: "gantt axis" });
  const rows = scopes.map((scope) => {
    const holder = h("div", { class: "gantt" });
    holders.push([scope, holder]);
    const chip = moveChip(scope.move.total);
    const lands = scope.landedBy !== null
      ? h("span", {}, `done by ${shortDate(scope.landedBy, view.today)}`)
      : scope.move.projected !== null
      ? h(
        "span",
        {},
        h(
          "b",
          {},
          `${scope.move.projected !== scope.move.planned ? "~" : ""}${
            shortDate(scope.move.projected, view.today)
          }`,
        ),
        scope.move.projected !== scope.move.planned
          ? h("span", { class: "planned" }, ` plan ${shortDate(scope.move.planned!, view.today)}`)
          : null,
      )
      : h("span", { class: "planned" }, "nothing estimated");
    return h(
      "div",
      {
        class: `row${scope === selected ? " selected" : ""}${scope.key === null ? " whole" : ""}`,
        role: "option",
        "aria-selected": String(scope === selected),
        onclick: () => choose(scope),
      },
      h(
        "span",
        { class: "name" },
        scope.badge
          ? h("span", { class: "badge", style: `background:${scope.color}` }, scope.badge)
          : null,
        h("span", {}, scope.label),
        scope.title ? h("span", { class: "subtitle" }, scope.title) : null,
      ),
      verdictChip(scope),
      h("span", { class: "lands" }, lands),
      h("span", {
        class: `move tone-${chip.tone}`,
        title: scope.move.total !== null
          ? moveParts(scope.move) || "no change"
          : "nothing to compare with",
      }, chip.text),
      holder,
    );
  });
  const list = h(
    "div",
    {
      class: "timeline",
      role: "listbox",
      tabindex: "0",
      "aria-label": "Milestones — ↑ and ↓ move between them",
      onkeydown: (event: KeyboardEvent) => {
        if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
        event.preventDefault();
        const index = scopes.indexOf(selected) + (event.key === "ArrowDown" ? 1 : -1);
        if (index < 0 || index >= scopes.length) return;
        refocus = true;
        choose(scopes[index]);
      },
    },
    h(
      "div",
      { class: "row head" },
      h("span", {}, "Milestone"),
      h("span", {}, "Status"),
      h("span", {}, "Lands"),
      h("span", { title: `against ${basis}` }, "Moved"),
      axisHolder,
    ),
    ...rows,
  );
  // After the caller has put this on the page — the width is read from where it landed.
  queueMicrotask(() => {
    const width = Math.max(160, axisHolder.clientWidth);
    axisHolder.innerHTML = axis(first, last, view.today, width);
    for (const [scope, holder] of holders) {
      holder.innerHTML = ganttRow(scope, view.today, first, last, width);
    }
    if (refocus) {
      refocus = false;
      list.focus();
    }
  });
  return h("section", { class: "v2-section" }, h("h2", {}, "Milestones"), list);
}
