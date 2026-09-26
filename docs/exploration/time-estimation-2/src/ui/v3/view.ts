/**
 * The Time tab, v3: a line of key figures, a toolbar, and two tabs — **Milestones** (the
 * shift view: where each one lands against the plan compared with) and **Work** (the scope
 * and the work done, on one scale). No sentences: the words live in the tooltips.
 */

import { type Day, formatDate, g, percent } from "../../model/calendar.ts";
import { stepKey } from "../../model/graph.ts";
import { shareOf } from "../../model/progress.ts";
import { type Brief, brief, burnup, type Reach, type Scope } from "../../brief.ts";
import { lookingBack, type TimeView } from "../../present.ts";
import { basisName } from "../compare.ts";
import { h } from "../markup.ts";
import { shiftsSvg } from "./shifts.ts";
import type { V3Handlers, V3State } from "./state.ts";
import { toolbar } from "./toolbar.ts";
import { stepAt, stepsFrom, type WorkMarks, workSvg } from "./work.ts";

export function v3View(view: TimeView, state: V3State, on: V3Handlers): HTMLElement {
  return tabbedView(
    view,
    state,
    (found) => toolbar(view, found, state, on),
    (found) =>
      state.page === "milestones"
        ? milestonesPage(found, view, state, on)
        : workPage(found, view, state),
  );
}

/**
 * Key figures, a toolbar and a tab's page — v3's layout, which v4 and v5 keep with their own
 * toolbar and pages.
 */
export function tabbedView(
  view: TimeView,
  state: V3State,
  bar: (found: Brief) => HTMLElement,
  page: (found: Brief) => HTMLElement,
): HTMLElement {
  if (view.report.cycle.length) {
    const names = view.report.cycle.map((step) => step.title || "an untitled step").join(", ");
    return h(
      "div",
      { class: "v3" },
      h(
        "div",
        { class: "banner error" },
        `These steps wait on each other, so nothing can be dated: ${names}.`,
      ),
    );
  }
  const found = brief(view);
  const basis = basisName(state.then, view);
  return h(
    "div",
    { class: "v3" },
    keyFigures(found, view, basis),
    bar(found),
    page(found),
  );
}

/** The answer in numbers — each figure's meaning in its tooltip, none in words on the page. */
function keyFigures(found: Brief, view: TimeView, basis: string): HTMLElement {
  const whole = found.whole;
  const today = view.now.day;
  const figures: (HTMLElement | null)[] = [];
  if (whole.landedBy !== null) {
    figures.push(
      h(
        "span",
        { class: "figure lead", title: "All the work is done" },
        `✓ ${formatDate(whole.landedBy, today)}`,
      ),
    );
  } else if (whole.move.planned !== null) {
    figures.push(h("span", {
      class: "figure lead",
      title: "Where the plan lands, re-planned from today",
    }, formatDate(whole.move.planned, today)));
  }
  const moved = whole.move.plan;
  if (moved !== null) {
    figures.push(h("span", {
      class: `figure move tone-${moved > 0 ? "later" : moved < 0 ? "earlier" : "ok"}`,
      title: `Working days the landing moved against ${basis}`,
    }, moved === 0 ? "± 0d" : `${moved > 0 ? "▶ +" : "◀ −"}${Math.abs(moved)}d`));
  }
  const share = shareOf(whole.own);
  if (share !== null) {
    figures.push(
      h("span", {
        class: "figure",
        title: `${g(whole.own.doneDays)} of ${g(whole.own.days)} days of work done`,
      }, `${percent(share)} done`),
    );
  }
  const unsized = lookingBack(view) ? [] : view.unestimated.filter((step) => !step.estimateOff);
  if (unsized.length) {
    figures.push(h("span", {
      class: "figure tone-later",
      title: `No estimate, so counted as 0 days:\n${
        unsized.map((step) => `${stepKey(step)} ${step.title}`).join("\n")
      }`,
    }, `⚠ ${unsized.length} unsized`));
  }
  if (lookingBack(view)) {
    figures.push(h("span", {
      class: "figure as-of",
      title: "The tab as it was recorded on that day — History ▸ back to today",
    }, `as recorded ${formatDate(today, view.today)}`));
  }
  return h("div", { class: "v3-figures" }, ...figures);
}

// -- Milestones -----------------------------------------------------------------------------------

/**
 * `drill`: a double-click opens the milestone's own work (v3, v4; v5's Work shows it all).
 * `reach`: the least the date axis holds (v5, so History moves only the rows).
 */
export function milestonesPage(
  found: Brief,
  view: TimeView,
  state: V3State,
  on: V3Handlers,
  { drill = true, reach }: { drill?: boolean; reach?: Reach } = {},
): HTMLElement {
  const holder = h("div", { class: "shifts-holder" });
  // After the caller has put this on the page — the width is read from where it landed.
  queueMicrotask(() => {
    const width = Math.max(560, holder.clientWidth);
    const { svg, rows } = shiftsSvg(found, view, state.scope, width, reach);
    holder.innerHTML = svg;
    const element = holder.querySelector("svg")!;
    const rowAt = (event: MouseEvent) => {
      const box = element.getBoundingClientRect();
      const y = (event.clientY - box.top) * (element.viewBox.baseVal.height / box.height);
      return rows.find((row) => row.top <= y && y < row.bottom) ?? null;
    };
    // The first click redraws this chart, so a double-click never lands twice on one element
    // and `dblclick` never fires; the second click's count still says what it was.
    element.addEventListener("click", (event) => {
      const row = rowAt(event);
      if (event.detail >= 2) {
        if (row && drill) on.state({ scope: row.key, page: "work" });
      } else {
        on.state({ scope: row && row.key !== state.scope ? row.key : null });
      }
    });
  });
  const key = h(
    "div",
    { class: "v3-key" },
    h("span", {}, h("span", { class: "k-then" }), "then"),
    h("span", {}, h("span", { class: "k-now" }), "plan now"),
    h("span", {}, h("span", { class: "k-done" }, "✓"), "done"),
    h(
      "span",
      { class: "hint" },
      drill
        ? "click a milestone to pick it · double-click to see its work"
        : "click a milestone to pick it",
    ),
  );
  return h("section", { class: "v3-page" }, holder, key);
}

// -- Work -----------------------------------------------------------------------------------------

export function workPage(
  found: Brief,
  view: TimeView,
  state: V3State,
  marks: WorkMarks = {},
): HTMLElement {
  const scopes: Scope[] = [found.whole, ...found.milestones];
  const scope = scopes.find((one) => one.key === state.scope) ?? found.whole;
  const series = burnup(view, scope.key, found.compared);
  // Re-planned from today, the schedule before today holds only finished work's old dates.
  const data = { ...series, promised: stepsFrom(series.promised, view.now.day) };
  const named = found.milestones.filter((one) => one.key);
  const marked = scope.key !== null ? [scope] : named.length ? named : [scope];
  const holder = h("div", { class: "work-holder" });
  const tip = h("div", { class: "tooltip", hidden: true });
  queueMicrotask(() => {
    const { svg, geometry } = workSvg(
      data,
      marked,
      view,
      Math.max(560, holder.clientWidth),
      found.compared,
      marks,
    );
    holder.innerHTML = svg;
    holder.append(tip);
    const element = holder.querySelector("svg")!;
    const line = element.querySelector(".hover") as SVGLineElement;
    element.addEventListener("mousemove", (event) => {
      const box = element.getBoundingClientRect();
      const scale = element.viewBox.baseVal.width / box.width;
      const px = (event.clientX - box.left) * scale;
      if (px < geometry.left || px > geometry.right) {
        tip.hidden = true;
        line.setAttribute("visibility", "hidden");
        return;
      }
      const day: Day = geometry.day(px);
      line.setAttribute("x1", String(geometry.x(day)));
      line.setAttribute("x2", String(geometry.x(day)));
      line.setAttribute("visibility", "visible");
      const read = (
        label: string,
        value: number | null,
      ) => (value === null ? null : h("div", {}, `${label}: ${g(Math.round(value * 4) / 4)}d`));
      const lines = [
        day <= view.now.day ? read("scope", stepAt(data.scope, day)) : null,
        day <= view.now.day ? read("done", stepAt(data.done, day)) : null,
        read("the plan's schedule", stepAt(data.promised, day)),
      ].filter((one): one is HTMLDivElement => one !== null);
      tip.replaceChildren(h("b", {}, formatDate(day, view.now.day)), ...lines);
      tip.hidden = false;
      tip.style.left = `${Math.min((event.clientX - box.left) + 14, box.width - 200)}px`;
      tip.style.top = `${event.clientY - box.top + 14}px`;
    });
    element.addEventListener("mouseleave", () => {
      tip.hidden = true;
      line.setAttribute("visibility", "hidden");
    });
  });
  return h("section", { class: "v3-page" }, holder);
}
