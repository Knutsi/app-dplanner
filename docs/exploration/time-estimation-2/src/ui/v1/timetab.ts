/**
 * The Time tab, as a wireframe of today's layout (`time_estimates/module.py`): a strip of
 * controls over a split — what you set on the left (the staffing grid, the milestones), what
 * it answers on the right (the banner, the months, the plots).
 */

import {
  formatDate,
  formatDays,
  g,
  isoDay,
  parseDay,
  percent,
  shortDate,
} from "../../model/calendar.ts";
import { AGENTS, DEFAULT_EFFICIENCY, HUMANS, stepKey } from "../../model/graph.ts";
import { paletteById, PALETTES } from "../../model/palettes.ts";
import { type Pick, pickWords, shareOf, shortPickWords } from "../../model/progress.ts";
import { cellAt } from "../../model/simulate.ts";
import { ALL_KEY, type Page, type TimeView, type ViewState, type WhatIf } from "../../present.ts";
import { monthsView } from "./calendar.ts";
import { chartSvg, PAGES, readout } from "./charts.ts";
import { h } from "../markup.ts";

export interface TimeTabHandlers {
  view(patch: Partial<ViewState>): void;
  whatIf(patch: Partial<WhatIf> | null): void; // null clears every what-if.
  save(title: string, note: string): string | null; // The refusal, or null when saved.
  offset: number;
  page(offset: number): void;
}

export function timeTab(view: TimeView, state: ViewState, on: TimeTabHandlers): HTMLElement {
  if (view.report.cycle.length) {
    const names = view.report.cycle.map((step) => step.title || "an untitled step").join(", ");
    return h(
      "div",
      { class: "time" },
      toolbar(view, state, on),
      h(
        "div",
        { class: "banner error" },
        `● These steps wait on each other, so nothing can be dated: ${names}. Unlink one to time the plan.`,
      ),
    );
  }
  const left = h(
    "div",
    { class: "left" },
    staffing(view, state.lens, (team) => on.whatIf({ team })),
    milestoneTable(view, state, on),
  );
  const right = h(
    "div",
    { class: "right" },
    banner(view),
    pager(on),
    monthsView(view, state.picked, on.offset, (day) => on.whatIf({ start: day })),
    plots(view, state, on),
  );
  return h(
    "div",
    { class: "time" },
    toolbar(view, state, on),
    h("div", { class: "split" }, left, right),
  );
}

// -- the strip -----------------------------------------------------------------------------------

function toolbar(view: TimeView, state: ViewState, on: TimeTabHandlers): HTMLElement {
  const efficiency = Math.round((view.plan.assumptions.efficiency ?? DEFAULT_EFFICIENCY) * 100);
  const focus = h("select", {
    title: "Human focus: how much of a person's working day this project gets",
    onchange: (event: Event) =>
      on.whatIf({ efficiency: Number((event.target as HTMLSelectElement).value) / 100 }),
  });
  for (let value = 10; value <= 100; value += 5) {
    focus.append(
      h("option", { value: String(value), selected: value === efficiency }, `${value}% focus`),
    );
  }
  const palette = h("select", {
    title: "Milestone colours: the project's map",
    onchange: (event: Event) => on.whatIf({ palette: (event.target as HTMLSelectElement).value }),
  });
  for (const found of PALETTES) {
    palette.append(
      h("option", {
        value: found.id,
        selected: found.id === paletteById(view.plan.assumptions.palette).id,
      }, found.name),
    );
  }
  const stops = paletteById(view.plan.assumptions.palette).stops;
  const swatch = h("span", {
    class: "swatch",
    style: `background: linear-gradient(90deg, ${stops.join(", ")})`,
  });
  const lens = h(
    "span",
    { class: "segmented" },
    h("button", {
      class: state.lens === "calendar" ? "on" : "",
      onclick: () => on.view({ lens: "calendar" }),
    }, "Calendar days"),
    h("button", {
      class: state.lens === "project" ? "on" : "",
      onclick: () => on.view({ lens: "project" }),
    }, "Project days"),
  );
  const whatIfs = describeWhatIf(state.whatIf, view);
  return h(
    "div",
    { class: "strip" },
    saveButton(view, on.save),
    h("span", { class: "divider" }),
    focus,
    lens,
    swatch,
    palette,
    h("span", { class: "divider" }),
    h("span", { class: "label" }, "Compare"),
    picker(view, state.then, "then", (pick) => on.view({ then: pick })),
    h("span", { class: "label" }, "with"),
    picker(view, state.now, "now", (pick) => on.view({ now: pick })),
    whatIfs
      ? h(
        "span",
        {
          class: "what-if",
          title:
            "These act on this day's live plan only; the recorded history keeps what was stored.",
        },
        `what-if: ${whatIfs}`,
        h("button", { class: "link", onclick: () => on.whatIf(null) }, "reset"),
      )
      : null,
  );
}

function describeWhatIf(whatIf: WhatIf, view: TimeView): string {
  const parts: string[] = [];
  if (whatIf.efficiency !== undefined) parts.push(`focus ${percent(whatIf.efficiency)}`);
  if (whatIf.team) parts.push(`team ${whatIf.team[0]}+${whatIf.team[1]}`);
  if (whatIf.palette) parts.push(`colours ${paletteById(whatIf.palette).name}`);
  if (whatIf.start !== undefined) parts.push(`start ${shortDate(whatIf.start, view.today)}`);
  const begins = Object.keys(whatIf.begins ?? {}).length;
  if (begins) parts.push(`${begins} milestone date${begins === 1 ? "" : "s"}`);
  return parts.join(", ");
}

/** *Save snapshot…*: keep the plan as it stands today under a title. */
export function saveButton(
  view: TimeView,
  save: (title: string, note: string) => string | null,
): HTMLElement {
  const title = h("input", {
    type: "text",
    placeholder: `What we thought on ${formatDate(view.today, view.today)}`,
  });
  const note = h("textarea", {
    rows: 3,
    placeholder: "What the occasion was, for whoever compares against it",
  });
  const refusal = h("div", { class: "refusal" });
  const panel = h(
    "div",
    { class: "popover", hidden: true },
    h("div", { class: "caption" }, "Title"),
    title,
    refusal,
    h("div", { class: "caption" }, "Note"),
    note,
    h(
      "div",
      { class: "footer" },
      h("button", { onclick: () => (panel.hidden = true) }, "Cancel"),
      h("button", {
        class: "primary",
        onclick: () => {
          const refused = save(title.value, note.value);
          refusal.textContent = refused ?? "";
        },
      }, "Save"),
    ),
  );
  return h(
    "span",
    { class: "anchor" },
    h("button", {
      title: "Save Snapshot… — keep the plan as it stands today under a title",
      onclick: () => (panel.hidden = !panel.hidden),
    }, "📷 Save snapshot…"),
    panel,
  );
}

/** `SnapshotPicker`: the side's default, every saved snapshot, and any day. */
function picker(
  view: TimeView,
  pick: Pick,
  side: "then" | "now",
  chosen: (pick: Pick) => void,
): HTMLElement {
  const saved = view.recording.saved;
  const select = h("select", {
    title: side === "then"
      ? pickWords(pick, view.then, view.now.day) || "Nothing recorded to compare with yet"
      : pickWords(pick, view.now, view.live.day) || "the plan now",
    onchange: (event: Event) => {
      const value = (event.target as HTMLSelectElement).value;
      if (value === "default") chosen(side === "then" ? { kind: "start" } : { kind: "now" });
      else if (value === "day") {
        chosen({ kind: "day", day: pick.kind === "day" ? pick.day : view.today - 7 });
      } else chosen({ kind: "saved", title: value.slice(6) });
    },
  });
  select.append(
    h(
      "option",
      { value: "default", selected: pick.kind === "start" || pick.kind === "now" },
      side === "then" ? "Plan at start" : "Now",
    ),
  );
  for (const row of saved) {
    select.append(
      h("option", {
        value: `saved:${row.title}`,
        selected: pick.kind === "saved" && pick.title.toLowerCase() === row.title.toLowerCase(),
        title: row.note,
      }, `${row.title} · ${shortDate(row.day, view.today)}`),
    );
  }
  select.append(
    h(
      "option",
      { value: "day", selected: pick.kind === "day" },
      pick.kind === "day" ? shortPickWords(pick, view.today) : "Day…",
    ),
  );
  if (pick.kind !== "day") return select;
  const day = h("input", {
    type: "date",
    value: isoDay(pick.day),
    onchange: (event: Event) => {
      const when = parseDay((event.target as HTMLInputElement).value);
      if (when !== null) chosen({ kind: "day", day: when });
    },
  });
  return h("span", { class: "picker" }, select, day);
}

// -- the left: what you set ------------------------------------------------------------------------

/** The staffing matrix: humans by agents, each tile how long the plan takes with that team. */
export function staffing(
  view: TimeView,
  lens: ViewState["lens"],
  onTeam: (team: [number, number]) => void,
): HTMLElement {
  const cells = lens === "calendar" ? view.report.calendar : view.report.parallel;
  const agents = view.report.hasAgentSteps ? AGENTS : [1];
  const values = HUMANS.flatMap((humans) => agents.map((a) => cellAt(cells, humans, a)!.days));
  const [least, most] = [Math.min(...values), Math.max(...values)];
  const grid = h("div", {
    class: "staffing",
    style: `grid-template-columns: auto repeat(${agents.length}, 72px)`,
  });
  grid.append(h("span"));
  for (const a of agents) {
    grid.append(
      h(
        "span",
        { class: "head" },
        view.report.hasAgentSteps ? `${a} agent${a === 1 ? "" : "s"}` : "any agents",
      ),
    );
  }
  for (const humans of HUMANS) {
    grid.append(h("span", { class: "head row" }, `${humans} human${humans === 1 ? "" : "s"}`));
    for (const a of agents) {
      const cell = cellAt(cells, humans, a)!;
      const calendar = cellAt(view.report.calendar, humans, a)!;
      const parallel = cellAt(view.report.parallel, humans, a)!;
      const tint = most > least ? 18 + ((cell.days - least) / (most - least)) * 70 : 18;
      const chosen = view.team[0] === humans && (view.team[1] === a || !view.report.hasAgentSteps);
      grid.append(h("button", {
        class: `tile${chosen ? " chosen" : ""}`,
        style: `background: rgba(95, 135, 215, ${(tint / 255).toFixed(3)})`,
        title: [
          `${humans} ${humans === 1 ? "person" : "people"} + ${a} agent${a === 1 ? "" : "s"}`,
          `${formatDays(parallel.days)} of project time`,
          `${formatDays(calendar.days)} of calendar time at ${
            percent(view.report.efficiency)
          } focus`,
          calendar.finish !== null
            ? `lands ${formatDate(calendar.finish, view.today)}`
            : "nothing estimated to land",
        ].join("\n"),
        onclick: () => onTeam([humans, view.report.hasAgentSteps ? a : view.team[1]]),
      }, formatDays(cell.days)));
    }
  }
  return grid;
}

function milestoneTable(view: TimeView, state: ViewState, on: TimeTabHandlers): HTMLElement {
  const table = h(
    "table",
    { class: "milestones" },
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        ...["Milestone", "Begins", "Lands", "Days", "Landed"].map((name) => h("th", {}, name)),
      ),
    ),
  );
  const body = h("tbody");
  for (const entry of view.entries) {
    const picked = entry.key === ALL_KEY || entry.key === ""
      ? state.picked === null
      : state.picked === entry.key;
    const share = shareOf(entry.landed);
    const own = entry.setsProject ? view.plan.start !== null : entry.asked !== null;
    const begins = h("input", {
      type: "date",
      class: own ? "own" : "sequence",
      value: isoDay(entry.setsProject ? view.start : entry.asked ?? entry.begins),
      disabled: !entry.setsProject && !entry.badge,
      title: entry.setsProject
        ? "The project's start"
        : own
        ? "A date of its own"
        : "The day the sequence gives it",
      onclick: (event: Event) => event.stopPropagation(),
      onchange: (event: Event) => {
        const when = parseDay((event.target as HTMLInputElement).value);
        if (entry.setsProject && when !== null) on.whatIf({ start: when });
        else if (entry.badge) on.whatIf({ begins: { ...state.whatIf.begins, [entry.key]: when } });
      },
    });
    body.append(h(
      "tr",
      {
        class: `${picked ? "picked" : ""}${entry.key === ALL_KEY ? " whole" : ""}`,
        title:
          `${entry.label}\n${entry.steps} steps · lands ${
            entry.finish !== null ? formatDate(entry.finish, view.today) : "—"
          }` +
          (entry.pushed !== null
            ? `\nasked to begin ${
              formatDate(entry.pushed, view.today)
            }, but the previous milestone lands later`
            : ""),
        onclick: () => on.view({ picked: entry.badge ? entry.key : null }),
      },
      h(
        "td",
        {},
        h("span", { class: "badge", style: `background:${entry.color}` }, entry.badge || ""),
        h("span", {}, entry.label),
        entry.title ? h("div", { class: "subtitle" }, entry.title) : null,
      ),
      h("td", {}, begins),
      h(
        "td",
        {},
        `${entry.pushed !== null ? "⚠ " : ""}${
          entry.finish !== null ? formatDate(entry.finish, view.today) : "—"
        }`,
      ),
      h("td", { class: "number" }, formatDays(entry.days)),
      h("td", {
        class: "number",
        title: `${g(entry.landed.doneDays)}d of ${
          g(entry.landed.days)
        }d estimated · ${entry.landed.done} of ${entry.landed.steps} steps done`,
      }, share === null ? "—" : percent(share)),
    ));
  }
  table.append(body);
  const none = view.entries.every((entry) => !entry.badge);
  return h(
    "div",
    {},
    h("div", { class: "caption bold" }, "Milestones"),
    table,
    none ? h("div", { class: "note" }, "No milestones yet · Step ▸ Type ▸ Milestone") : null,
  );
}

// -- the right: what it answers -------------------------------------------------------------------

function banner(view: TimeView): HTMLElement | null {
  const count = view.report.unestimated;
  if (!count) return null;
  const opted = view.unestimated.filter((step) => step.estimateOff).length;
  return h(
    "div",
    { class: "banner" },
    h("span", { class: "dot" }, "●"),
    ` ${count} step${count === 1 ? "" : "s"} unestimated · counted as 0d`,
    h("span", {
      class: "names",
      title: view.unestimated.map((step) =>
        `${stepKey(step)} ${step.title}${
          step.estimateOff ? " (opted out: milestone, feature or check)" : ""
        }`
      ).join("\n"),
    }, opted ? ` — ${opted} of them opted out of estimating` : " — which?"),
  );
}

function pager(on: TimeTabHandlers): HTMLElement {
  return h(
    "div",
    { class: "pager" },
    h("button", { title: "A month earlier", onclick: () => on.page(on.offset - 1) }, "◂"),
    h("button", { title: "A month later", onclick: () => on.page(on.offset + 1) }, "▸"),
    on.offset
      ? h("button", { class: "link", onclick: () => on.page(0) }, "back to the start")
      : null,
  );
}

let charts = 0;

function plots(view: TimeView, state: ViewState, on: TimeTabHandlers): HTMLElement {
  const holder = h("div", { class: "chart-holder" });
  const tip = h("div", { class: "tooltip", hidden: true });
  const draw = () => {
    const width = Math.max(420, holder.clientWidth || 640);
    const id = `chart${(charts += 1)}`;
    const { svg, geometry } = chartSvg(view.chart, state.page, width, id);
    holder.innerHTML = svg;
    holder.append(tip);
    const element = holder.querySelector("svg")!;
    const line = element.querySelector(".hover") as SVGLineElement;
    element.addEventListener("mousemove", (event) => {
      const box = element.getBoundingClientRect();
      const [x, y] = [event.clientX - box.left, event.clientY - box.top];
      const panel = geometry.panels.find((one) =>
        y >= one.top - 18 && y <= one.top + one.height + 10
      );
      if (!panel || x < geometry.left || x > geometry.right) {
        tip.hidden = true;
        line.setAttribute("visibility", "hidden");
        return;
      }
      const day = geometry.day(x);
      line.setAttribute("x1", String(geometry.x(day)));
      line.setAttribute("x2", String(geometry.x(day)));
      line.setAttribute("visibility", "visible");
      const lines = readout(view.chart, panel.kind, day);
      tip.replaceChildren(
        h("b", {}, formatDate(day, view.today)),
        ...lines.map((text) => h("div", {}, text)),
      );
      tip.hidden = false;
      tip.style.left = `${Math.min(x + 14, box.width - 260)}px`;
      tip.style.top = `${y + 14}px`;
    });
    element.addEventListener("mouseleave", () => {
      tip.hidden = true;
      line.setAttribute("visibility", "hidden");
    });
  };
  // After the caller has put this on the page — the width is read from where it landed.
  queueMicrotask(draw);
  const pages = h(
    "div",
    { class: "segmented pages" },
    ...PAGES.map(({ page, label }) =>
      h("button", {
        class: state.page === page ? "on" : "",
        onclick: () => on.view({ page: page as Page }),
      }, label)
    ),
  );
  return h("div", { class: "plots" }, pages, holder);
}
