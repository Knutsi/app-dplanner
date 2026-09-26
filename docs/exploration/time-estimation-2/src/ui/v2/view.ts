/**
 * The Time tab, v2 — the answer first, the milestones as navigation, and the detail of the
 * one picked: its burn-up and what changed. The staffing what-if and the calendar are there,
 * folded, for when they are the question.
 *
 * It reads nothing v1 does not: the plan now and the recorded rows. What it adds is how they
 * are read (brief.ts) — and ISSUES.md says which of v1's problems that reading answers.
 */

import { isoDay, parseDay } from "../../model/calendar.ts";
import { DEFAULT_EFFICIENCY, stepKey } from "../../model/graph.ts";
import { brief, burnup, changes, type Scope } from "../../brief.ts";
import type { TimeView } from "../../present.ts";
import { h } from "../markup.ts";
import { monthsView } from "../v1/calendar.ts";
import { saveButton, staffing } from "../v1/timetab.ts";
import { burnupKey, burnupSvg } from "./burnup.ts";
import { changesPanel } from "./changes.ts";
import { basisName } from "../compare.ts";
import { headline, verdictChip } from "./headline.ts";
import { timeline } from "./milestones.ts";
import type { V2Handlers, V2State } from "./state.ts";
import { longDate } from "./words.ts";

export function v2View(view: TimeView, state: V2State, on: V2Handlers): HTMLElement {
  if (view.report.cycle.length) {
    const names = view.report.cycle.map((step) => step.title || "an untitled step").join(", ");
    return h(
      "div",
      { class: "v2" },
      h(
        "div",
        { class: "banner error" },
        `These steps wait on each other, so nothing can be dated: ${names}. Unlink one to time the plan.`,
      ),
    );
  }
  const found = brief(view);
  const basis = basisName(state.then, view);
  const scopes = [found.whole, ...found.milestones];
  const selected = scopes.find((scope) => scope.key === state.scope) ?? found.whole;
  const head = headline(view, found, state, on);
  head.querySelector(".v2-controls")?.append(saveButton(view, on.save));
  return h(
    "div",
    { class: "v2" },
    head,
    unsized(view),
    timeline(view, found, state, on, basis),
    detail(view, selected, found.compared, basis),
    whatIf(view, state, on),
    calendar(view, state, on),
  );
}

/** Steps nobody sized — the milestones and features that opt out are not counted (I2). */
function unsized(view: TimeView): HTMLElement | null {
  const steps = view.unestimated.filter((step) => !step.estimateOff);
  if (!steps.length) return null;
  return h(
    "div",
    { class: "unsized", title: steps.map((step) => `${stepKey(step)} ${step.title}`).join("\n") },
    `${steps.length} step${
      steps.length === 1 ? " has" : "s have"
    } no estimate and count as 0 days — every date here is that much early.`,
  );
}

function detail(view: TimeView, scope: Scope, compared: boolean, basis: string): HTMLElement {
  const data = burnup(view, scope.key, compared);
  const holder = h("div", { class: "burnup" });
  // After the caller has put this on the page — the width is read from where it landed.
  queueMicrotask(() => {
    holder.innerHTML = burnupSvg(data, scope, view, Math.max(420, holder.clientWidth), basis);
  });
  const own = scope.own;
  const title = scope.key === null
    ? "All work"
    : `${scope.badge ? scope.badge + " " : ""}${scope.label}${
      scope.title ? " — " + scope.title : ""
    }`;
  const lands = scope.landedBy !== null
    ? `recorded done by ${longDate(scope.landedBy, view.today)}`
    : scope.move.projected !== null
    ? `lands ${scope.move.projected !== scope.move.planned ? "~" : ""}${
      longDate(scope.move.projected, view.today)
    }`
    : "nothing estimated to land";
  return h(
    "section",
    { class: "v2-section detail" },
    h("h2", {}, title),
    h(
      "div",
      { class: "detail-sub" },
      verdictChip(scope),
      ` ${lands} · own work: ${own.done} of ${own.steps} steps, ${
        Math.round(own.doneDays * 4) / 4
      } of ${Math.round(own.days * 4) / 4} days done`,
      scope.key !== null
        ? h(
          "span",
          { class: "planned" },
          " · dates count everything before it; the chart shows its own work",
        )
        : null,
    ),
    h(
      "div",
      { class: "detail-grid" },
      h("div", {}, holder, h("div", { class: "chart-key", html: burnupKey(basis, compared) })),
      changesPanel(compared ? changes(view, scope) : null, scope, basis, view.today),
    ),
  );
}

function fold(
  title: string,
  open: boolean,
  toggled: (open: boolean) => void,
  ...inner: (HTMLElement | null)[]
): HTMLElement {
  const details = h("details", { class: "v2-fold", open }, h("summary", {}, title), ...inner);
  details.addEventListener("toggle", () => {
    if (details.open !== open) toggled(details.open);
  });
  return details;
}

function whatIf(view: TimeView, state: V2State, on: V2Handlers): HTMLElement {
  const efficiency = Math.round((view.plan.assumptions.efficiency ?? DEFAULT_EFFICIENCY) * 100);
  const focus = h("select", {
    onchange: (event: Event) =>
      on.state({
        whatIf: {
          ...state.whatIf,
          efficiency: Number((event.target as HTMLSelectElement).value) / 100,
        },
      }),
  });
  for (let value = 10; value <= 100; value += 5) {
    focus.append(
      h("option", { value: String(value), selected: value === efficiency }, `${value}%`),
    );
  }
  const start = h("input", {
    type: "date",
    value: isoDay(view.start),
    onchange: (event: Event) => {
      const when = parseDay((event.target as HTMLInputElement).value);
      if (when !== null) on.state({ whatIf: { ...state.whatIf, start: when } });
    },
  });
  return fold(
    "What if… the team, the focus or the start were different",
    state.folds.whatif,
    (open) => on.state({ folds: { ...state.folds, whatif: open } }),
    h(
      "p",
      { class: "planned" },
      "Every tile is how long the plan takes with that team; picking one re-dates everything above for this day only. Nothing is saved.",
    ),
    h(
      "div",
      { class: "row" },
      h("label", {}, "Focus ", focus),
      h("label", {}, "Start ", start),
      Object.keys(state.whatIf).length
        ? h("button", { class: "link", onclick: () => on.state({ whatIf: {} }) }, "reset")
        : null,
    ),
    staffing(view, "calendar", (team) => on.state({ whatIf: { ...state.whatIf, team } })),
  );
}

function calendar(view: TimeView, state: V2State, on: V2Handlers): HTMLElement {
  return fold(
    "Calendar",
    state.folds.calendar,
    (open) => on.state({ folds: { ...state.folds, calendar: open } }),
    state.folds.calendar
      ? h(
        "div",
        {},
        h(
          "div",
          { class: "pager" },
          h("button", {
            title: "A month earlier",
            onclick: () => on.state({ offset: state.offset - 1 }),
          }, "◂"),
          h("button", {
            title: "A month later",
            onclick: () => on.state({ offset: state.offset + 1 }),
          }, "▸"),
        ),
        monthsView(view, state.scope, state.offset, {
          onDay: (day) => on.state({ whatIf: { ...state.whatIf, start: day } }),
        }),
      )
      : null,
  );
}
