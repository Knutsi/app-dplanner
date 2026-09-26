/**
 * v3's toolbar, in order of how often each control is reached for: the tabs, what the plan
 * is compared with, which milestone the Work tab shows; then, on the right and folded away,
 * the what-ifs (team and focus, tinted with a one-click ✕ while one is set), *Save
 * snapshot…*, and behind ⋯ the colour map.
 */

import { formatDays } from "../../model/calendar.ts";
import { AGENTS, DEFAULT_EFFICIENCY, HUMANS } from "../../model/graph.ts";
import { paletteById, PALETTES } from "../../model/palettes.ts";
import { cellAt } from "../../model/simulate.ts";
import type { Brief } from "../../brief.ts";
import type { TimeView } from "../../present.ts";
import { comparePicker } from "../compare.ts";
import { h } from "../markup.ts";
import { saveButton } from "../v1/timetab.ts";
import type { V3Handlers, V3Page, V3State } from "./state.ts";

export const TABS: [V3Page, string][] = [["milestones", "Milestones"], ["work", "Work"]];

export function tabs(
  state: V3State,
  on: V3Handlers,
  pages: [V3Page, string][] = TABS,
): HTMLElement {
  return h(
    "span",
    { class: "v3-tabs", role: "tablist" },
    ...pages.map(([page, name]) =>
      h("button", {
        role: "tab",
        "aria-selected": String(state.page === page),
        class: state.page === page ? "on" : "",
        onclick: () => on.state({ page }),
      }, name)
    ),
  );
}

export function showing(found: Brief, state: V3State, on: V3Handlers): HTMLElement {
  const select = h("select", {
    title: "Which work the plots show: everything, or one milestone's own",
    onchange: (event: Event) => {
      const value = (event.target as HTMLSelectElement).value;
      on.state({ scope: value === "*" ? null : value });
    },
  });
  select.append(h("option", { value: "*", selected: state.scope === null }, "All work"));
  for (const scope of found.milestones) {
    select.append(
      h(
        "option",
        { value: scope.key ?? "", selected: state.scope === scope.key },
        scope.badge ? `${scope.badge} ${scope.label}` : scope.label,
      ),
    );
  }
  return h("label", { class: "showing" }, "Showing ", select);
}

function team(view: TimeView, state: V3State, on: V3Handlers): HTMLElement {
  const agents = view.report.hasAgentSteps ? AGENTS : [1];
  const select = h("select", {
    title: "What if the team were different — how long the plan takes with each",
    onchange: (event: Event) => {
      const [people, bots] = (event.target as HTMLSelectElement).value.split("+").map(Number);
      on.state({ whatIf: { ...state.whatIf, team: [people, bots] } });
    },
  });
  for (const people of HUMANS) {
    for (const bots of agents) {
      const cell = cellAt(view.report.calendar, people, bots)!;
      const chosen = view.team[0] === people &&
        (view.team[1] === bots || !view.report.hasAgentSteps);
      select.append(
        h(
          "option",
          { value: `${people}+${bots}`, selected: chosen },
          `${people} ${people === 1 ? "person" : "people"}${
            view.report.hasAgentSteps ? ` + ${bots} agent${bots === 1 ? "" : "s"}` : ""
          } · ${formatDays(cell.days)}`,
        ),
      );
    }
  }
  return select;
}

function focus(view: TimeView, state: V3State, on: V3Handlers): HTMLElement {
  const current = Math.round((view.plan.assumptions.efficiency ?? DEFAULT_EFFICIENCY) * 100);
  const select = h("select", {
    title: "What if people gave this project a different share of their day",
    onchange: (event: Event) =>
      on.state({
        whatIf: {
          ...state.whatIf,
          efficiency: Number((event.target as HTMLSelectElement).value) / 100,
        },
      }),
  });
  for (let value = 10; value <= 100; value += 5) {
    select.append(
      h("option", { value: String(value), selected: value === current }, `${value}% focus`),
    );
  }
  return select;
}

/**
 * A popover that stays open across the re-render its own controls cause — picking a team
 * redraws the page, and the picker should still be there to try the next one.
 */
const opened = new Set<string>();

// Anywhere else on the page closes it, as a menu does.
document.addEventListener("pointerdown", (event) => {
  for (const menu of document.querySelectorAll<HTMLDetailsElement>("details.popover-menu[open]")) {
    if (!menu.contains(event.target as Node)) menu.open = false;
  }
});

export function popover(
  name: string,
  summary: HTMLElement,
  panel: HTMLElement,
  tone = "",
): HTMLElement {
  const details = h(
    "details",
    { class: `popover-menu ${name}${tone}`, open: opened.has(name) },
    summary,
    panel,
  );
  details.addEventListener("toggle", () => {
    if (details.open) opened.add(name);
    else opened.delete(name);
  });
  return details;
}

/** The what-ifs change the schedule; the colour map does not, so it is not one of them. */
function whatIfActive(state: V3State): boolean {
  const { team, efficiency, start, begins } = state.whatIf;
  return team !== undefined || efficiency !== undefined || start !== undefined ||
    begins !== undefined;
}

function whatIf(view: TimeView, state: V3State, on: V3Handlers): HTMLElement[] {
  const active = whatIfActive(state);
  const clear = () => {
    const { palette } = state.whatIf;
    on.state({ whatIf: palette === undefined ? {} : { palette } });
  };
  const menu = popover(
    "what-if",
    h("summary", {
      title: active
        ? "A what-if is active: the dates are this team's and focus, and nothing is saved"
        : "What if the team, or its focus, were different",
    }, "What if…"),
    h(
      "div",
      { class: "menu-panel" },
      h("label", {}, "Team ", team(view, state, on)),
      h("label", {}, "Focus ", focus(view, state, on)),
    ),
    active ? " active" : "",
  );
  return active
    ? [
      menu,
      h(
        "button",
        { class: "clear-what-if", title: "Back to the plan as it is", onclick: clear },
        "✕",
      ),
    ]
    : [menu];
}

export function more(view: TimeView, state: V3State, on: V3Handlers): HTMLElement {
  const palette = h("select", {
    onchange: (event: Event) =>
      on.state({ whatIf: { ...state.whatIf, palette: (event.target as HTMLSelectElement).value } }),
  });
  for (const found of PALETTES) {
    palette.append(
      h("option", {
        value: found.id,
        selected: found.id === paletteById(view.plan.assumptions.palette).id,
      }, found.name),
    );
  }
  return popover(
    "more",
    h("summary", { title: "More" }, "⋯"),
    h("div", { class: "menu-panel" }, h("label", {}, "Milestone colours ", palette)),
  );
}

export function toolbar(view: TimeView, found: Brief, state: V3State, on: V3Handlers): HTMLElement {
  return h(
    "div",
    { class: "v3-toolbar" },
    tabs(state, on),
    h("span", { class: "divider" }),
    comparePicker(view, state.then, (then) => on.state({ then })),
    state.page === "work" ? showing(found, state, on) : null,
    h("span", { class: "spacer" }),
    ...whatIf(view, state, on),
    saveButton(view, on.save),
    more(view, state, on),
  );
}
