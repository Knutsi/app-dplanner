/**
 * The Time tab, v5: v4 with the Calendar back as a third tab, and History in the toolbar —
 * the tab as it was recorded on an earlier day. Looking back, the page reads that day's
 * record, and the Budget and *Save snapshot…* grey out: the past cannot be changed.
 */

import type { Day } from "../../model/calendar.ts";
import type { Brief } from "../../brief.ts";
import { lookingBack, type TimeView } from "../../present.ts";
import { comparePicker } from "../compare.ts";
import { h } from "../markup.ts";
import { monthsView } from "../v1/calendar.ts";
import { saveButton } from "../v1/timetab.ts";
import type { V3Page, V3State } from "../v3/state.ts";
import { more, showing, TABS, tabs } from "../v3/toolbar.ts";
import { milestonesPage, tabbedView, workPage } from "../v3/view.ts";
import { delaySpans, type Reach } from "../v3/work.ts";
import { budgetMenu } from "../v4/budget.ts";
import { V4_MARKS, type V4Handlers } from "../v4/view.ts";
import { historyMenu } from "./history.ts";
import { paceToggle } from "./pace.ts";

const PAGES: [V3Page, string][] = [...TABS, ["calendar", "Calendar"]];
const PAST = "History shows a recorded day: back to today to change the plan";
const ASKED = "History shows the dates as they were recorded";

function toolbar(
  view: TimeView,
  found: Brief,
  state: V3State,
  on: V4Handlers,
  recorded: readonly Day[],
): HTMLElement {
  const off = lookingBack(view) ? PAST : undefined;
  return h(
    "div",
    { class: "v3-toolbar" },
    tabs(state, on, PAGES),
    h("span", { class: "divider" }),
    comparePicker(view, state.then, (then) => on.state({ then })),
    state.page === "work" ? showing(found, state, on) : null,
    h("span", { class: "spacer" }),
    ...historyMenu(view, on, recorded),
    budgetMenu(view, on.budget, off),
    paceToggle(view, state.pace, (pace) => on.state({ pace }), off && ASKED),
    saveButton(view, on.save, off),
    more(view, state, on),
  );
}

/** The months, each stretch a band in its milestone's colour, and each wait hatched. */
function calendarPage(view: TimeView, state: V3State, on: V4Handlers): HTMLElement {
  const waits = lookingBack(view) ? [] : delaySpans(view);
  const pager = h(
    "div",
    { class: "pager" },
    h(
      "button",
      { title: "A month earlier", onclick: () => on.state({ offset: state.offset - 1 }) },
      "◂",
    ),
    h(
      "button",
      { title: "A month later", onclick: () => on.state({ offset: state.offset + 1 }) },
      "▸",
    ),
    state.offset
      ? h("button", { class: "link", onclick: () => on.state({ offset: 0 }) }, "from the start")
      : null,
  );
  const key = h(
    "div",
    { class: "v3-key" },
    h("span", {}, h("span", { class: "k-lands" }), "lands"),
    h("span", {}, h("span", { class: "k-today" }), lookingBack(view) ? "the day shown" : "today"),
    waits.length ? h("span", {}, h("span", { class: "k-wait" }), "a wait") : null,
    h("span", { class: "hint" }, "weekends are pale: they are not counted"),
  );
  return h(
    "section",
    { class: "v3-page calendar-page" },
    pager,
    monthsView(view, state.scope, state.offset, { waits, months: 6, named: true }),
    key,
  );
}

export function v5View(
  view: TimeView,
  state: V3State,
  on: V4Handlers,
  recorded: readonly Day[],
  reach?: Reach,
): HTMLElement {
  // Weekends and idle days come from the records; the waits are the live plan's alone.
  const marks = { ...V4_MARKS, delays: !lookingBack(view), reach };
  return tabbedView(
    view,
    state,
    (found) => toolbar(view, found, state, on, recorded),
    (found) =>
      state.page === "milestones"
        ? milestonesPage(found, view, state, on)
        : state.page === "calendar"
        ? calendarPage(view, state, on)
        : workPage(found, view, state, marks),
  );
}
