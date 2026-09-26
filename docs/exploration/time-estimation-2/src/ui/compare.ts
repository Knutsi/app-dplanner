/**
 * "Compared with": which recorded plan a redesigned view measures the plan now against —
 * shared by v2 and v3. Beside the picks DPlanner has (the plan at start, a saved snapshot,
 * a day), it offers the plan **a week ago**, the anchor of a weekly review, relative to
 * whichever day is today. There is no "now" side: now is the debugger's day.
 */

import { type Day, isoDay, parseDay, shortDate } from "../model/calendar.ts";
import { type Pick, pickWords } from "../model/progress.ts";
import type { TimeView } from "../present.ts";
import { h } from "./markup.ts";

export type ComparePick = Pick | { kind: "week" };

export function resolvePick(pick: ComparePick, today: Day): Pick {
  return pick.kind === "week" ? { kind: "day", day: today - 7 } : pick;
}

/** What the plan compared with is called in a sentence: short, and never a guess. */
export function basisName(pick: ComparePick, view: TimeView): string {
  if (pick.kind === "start") return "the plan at start";
  if (pick.kind === "week") return "the plan a week ago";
  if (pick.kind === "saved") return pick.title;
  if (pick.kind === "now") return "the plan now";
  return `the plan at ${shortDate(pick.day, view.now.day)}`;
}

export function comparePicker(
  view: TimeView,
  pick: ComparePick,
  picked: (pick: ComparePick) => void,
): HTMLElement {
  const select = h("select", {
    title: pickWords(resolvePick(pick, view.now.day), view.then, view.now.day) ||
      "Nothing recorded to compare with yet",
    onchange: (event: Event) => {
      const value = (event.target as HTMLSelectElement).value;
      if (value === "start") picked({ kind: "start" });
      else if (value === "week") picked({ kind: "week" });
      else if (value === "day") picked({ kind: "day", day: view.now.day - 14 });
      else picked({ kind: "saved", title: value.slice(6) });
    },
  });
  select.append(
    h("option", { value: "start", selected: pick.kind === "start" }, "the plan at start"),
  );
  select.append(
    h("option", { value: "week", selected: pick.kind === "week" }, "the plan a week ago"),
  );
  for (const row of view.recording.saved) {
    select.append(h("option", {
      value: `saved:${row.title}`,
      selected: pick.kind === "saved" && pick.title.toLowerCase() === row.title.toLowerCase(),
      title: row.note,
    }, `${row.title} · ${shortDate(row.day, view.now.day)}`));
  }
  select.append(h("option", { value: "day", selected: pick.kind === "day" }, "a day…"));
  const day = pick.kind === "day"
    ? h("input", {
      type: "date",
      value: isoDay(pick.day),
      onchange: (event: Event) => {
        const when = parseDay((event.target as HTMLInputElement).value);
        if (when !== null) picked({ kind: "day", day: when });
      },
    })
    : null;
  const found = view.then && view.then.day !== view.now.day
    ? h("span", { class: "recorded" }, `recorded ${shortDate(view.then.day, view.now.day)}`)
    : h("span", { class: "recorded missing" }, "nothing recorded before today");
  return h("label", { class: "compare" }, "Compared with ", select, day, found);
}
