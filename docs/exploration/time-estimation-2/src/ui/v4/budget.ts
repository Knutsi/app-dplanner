/**
 * v4's Budget: who works on the plan and how much of their day, set from the day shown on and
 * saved as it is chosen. The days before keep the budget they had — the model re-plans only
 * forward, so nothing about them needs remembering.
 */

import { formatDate } from "../../model/calendar.ts";
import { AGENTS, HUMANS } from "../../model/graph.ts";
import type { TimeView } from "../../present.ts";
import { type Budget, budgetOf } from "../../sim/edits.ts";
import { h } from "../markup.ts";
import { popover } from "../v3/toolbar.ts";

function counts(
  label: string,
  values: number[],
  current: number,
  pick: (value: number) => void,
): HTMLElement {
  return h(
    "div",
    { class: "budget-row" },
    h("span", { class: "budget-label" }, label),
    h(
      "span",
      { class: "segmented", role: "group", "aria-label": label },
      ...values.map((value) =>
        h(
          "button",
          { class: value === current ? "on" : "", onclick: () => pick(value) },
          String(value),
        )
      ),
    ),
  );
}

export function budgetMenu(view: TimeView, apply: (budget: Budget) => void): HTMLElement {
  const now = budgetOf(view.plan);
  const percent = Math.round(now.efficiency * 100);
  const agents = view.report.hasAgentSteps;
  const focus = h("select", {
    onchange: (event: Event) =>
      apply({ ...now, efficiency: Number((event.target as HTMLSelectElement).value) / 100 }),
  });
  for (let value = 10; value <= 100; value += 5) {
    focus.append(h("option", { value: String(value), selected: value === percent }, `${value}%`));
  }
  const people = `${now.humans} ${now.humans === 1 ? "person" : "people"}`;
  const summary = h(
    "summary",
    {
      title:
        `${people}${agents ? ` and ${now.agents} agent${now.agents === 1 ? "" : "s"}` : ""}, ` +
        `at ${percent}% focus — a change applies from this day on`,
    },
    "Budget ",
    h(
      "span",
      { class: "budget-now" },
      agents ? `${now.humans}p/${now.agents}a · ${percent}%` : `${now.humans}p · ${percent}%`,
    ),
  );
  const panel = h(
    "div",
    { class: "menu-panel budget-panel" },
    counts("People", HUMANS, now.humans, (humans) => apply({ ...now, humans })),
    agents
      ? counts("Agents", AGENTS, now.agents, (count) => apply({ ...now, agents: count }))
      : null,
    h("div", { class: "budget-row" }, h("span", { class: "budget-label" }, "Focus"), focus),
    h(
      "div",
      { class: "budget-note" },
      `From ${formatDate(view.today, view.today)} on; the days before keep theirs.`,
    ),
  );
  return popover("budget", summary, panel);
}
