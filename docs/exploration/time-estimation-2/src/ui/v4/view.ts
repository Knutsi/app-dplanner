/**
 * The Time tab, v4: v3's layout over a model whose dates hold still while the plan does, with
 * the Budget in the toolbar in place of the what-ifs, and the Work tab marking weekends, the
 * days nothing changed, and the waits of Delay steps.
 */

import type { Brief } from "../../brief.ts";
import type { TimeView } from "../../present.ts";
import type { Budget } from "../../sim/edits.ts";
import { comparePicker } from "../compare.ts";
import { h } from "../markup.ts";
import { saveButton } from "../v1/timetab.ts";
import type { V3Handlers, V3State } from "../v3/state.ts";
import { more, showing, tabs } from "../v3/toolbar.ts";
import { tabbedView } from "../v3/view.ts";
import { budgetMenu } from "./budget.ts";

export interface V4Handlers extends V3Handlers {
  budget(budget: Budget): void; // From the day shown on, saved as it is chosen.
}

function toolbar(view: TimeView, found: Brief, state: V3State, on: V4Handlers): HTMLElement {
  return h(
    "div",
    { class: "v3-toolbar" },
    tabs(state, on),
    h("span", { class: "divider" }),
    comparePicker(view, state.then, (then) => on.state({ then })),
    state.page === "work" ? showing(found, state, on) : null,
    h("span", { class: "spacer" }),
    budgetMenu(view, on.budget),
    saveButton(view, on.save),
    more(view, state, on),
  );
}

export function v4View(view: TimeView, state: V3State, on: V4Handlers): HTMLElement {
  return tabbedView(view, state, on, (found) => toolbar(view, found, state, on), {
    weekends: true,
    idle: true,
    delays: true,
  });
}
