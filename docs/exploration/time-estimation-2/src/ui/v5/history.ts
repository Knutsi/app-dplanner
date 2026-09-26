/**
 * v5's History: the tab as it was recorded on an earlier day.
 *
 * A slider runs over the days the recorder wrote a row, and today. On a recorded day the view
 * reads that day's record — its dates, its scope, what was done — as today it reads the live
 * plan; nothing on the page can write while it looks back. It needs nothing DPlanner does not
 * already store (`progress_history`).
 */

import { type Day, formatDate, shortDate } from "../../model/calendar.ts";
import { lookingBack, type TimeView } from "../../present.ts";
import { h } from "../markup.ts";
import type { V3Handlers } from "../v3/state.ts";
import { popover } from "../v3/toolbar.ts";

// The page is redrawn on every step; the slider being stepped with the keys keeps the focus.
let stepping = false;

export function historyMenu(
  view: TimeView,
  on: V3Handlers,
  recorded: readonly Day[],
): HTMLElement[] {
  const today = view.today;
  const days = [...new Set(recorded.filter((day) => day < today)), today].sort((a, b) => a - b);
  const shown = view.now.day;
  const at = Math.max(0, days.findLastIndex((day) => day <= shown));
  const show = (index: number) => {
    const day = days[Math.max(0, Math.min(days.length - 1, index))];
    on.state({ asOf: day === today ? null : day });
  };
  const said = (day: Day) => day === today ? "today" : `as recorded ${formatDate(day, today)}`;
  const label = h("span", { class: "history-day" }, said(days[at]));
  const slider = h("input", {
    type: "range",
    min: "0",
    max: String(days.length - 1),
    step: "1",
    value: String(at),
    "aria-label": "The day shown",
    oninput: () => (label.textContent = said(days[Number(slider.value)])),
    onchange: () => {
      stepping = true;
      show(Number(slider.value));
    },
  });
  if (stepping) {
    stepping = false;
    queueMicrotask(() => slider.focus());
  }
  const back = lookingBack(view);
  const step = (by: number, words: string, glyph: string) =>
    h("button", {
      title: words,
      disabled: at + by < 0 || at + by >= days.length,
      onclick: () => show(at + by),
    }, glyph);
  const panel = h(
    "div",
    { class: "menu-panel history-panel" },
    h(
      "div",
      { class: "history-row" },
      step(-1, "The record before", "◂"),
      slider,
      step(1, "The record after", "▸"),
    ),
    h(
      "div",
      { class: "history-row" },
      label,
      back
        ? h("button", { class: "link", onclick: () => show(days.length - 1) }, "back to today")
        : null,
    ),
    h(
      "div",
      { class: "budget-note" },
      days.length > 1
        ? `${days.length - 1} recorded day${days.length === 2 ? "" : "s"}, from ${
          shortDate(days[0], today)
        }. Looking back, the page reads each day's record; nothing is written.`
        : "Nothing recorded before today yet.",
    ),
  );
  const menu = popover(
    "history",
    h("summary", {
      title: back
        ? `Showing the tab as recorded ${formatDate(shown, today)}; nothing can be changed`
        : "Look back at the tab as it was recorded on an earlier day",
    }, back ? `History · ${shortDate(shown, today)}` : "History"),
    panel,
    back ? " active" : "",
  );
  return back
    ? [
      menu,
      h("button", {
        class: "clear-active",
        title: "Back to today",
        onclick: () => show(days.length - 1),
      }, "✕"),
    ]
    : [menu];
}
