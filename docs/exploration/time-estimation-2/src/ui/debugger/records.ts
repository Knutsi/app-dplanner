/**
 * Records — exactly what DPlanner keeps in `progress_history.json`, day by day, beside what
 * happened that day. Every comparison on the Time tab is drawn from these rows and nothing
 * else, so a day with no row is a day the plots interpolate across.
 */

import { type Day, formatDays, isoDay, shortDate, weekdayName } from "../../model/calendar.ts";
import { isMilestone, milestoneLabel, placed } from "../../model/graph.ts";
import { rowJson, type Snapshot } from "../../model/progress.ts";
import { type Parity, parityWords } from "../../sim/replay.ts";
import type { Recording, Timeline } from "../../sim/timeline.ts";
import { h } from "../markup.ts";

function stretchText(row: Snapshot, key: string, today: Day): string {
  const stretch = row.stretches.find((one) => one.key === key);
  if (!stretch) return "";
  const { steps, done, days, doneDays } = stretch.tally;
  const finish = stretch.finish !== null ? shortDate(stretch.finish, today) : "undated";
  return `${done}/${steps} steps · ${formatDays(doneDays) || "0d"} of ${
    formatDays(days) || "0d"
  } · ${shortDate(stretch.start, today)} → ${finish}`;
}

export function recordsView(
  timeline: Timeline,
  recording: Recording,
  index: number,
  parity: Parity[] | null,
): HTMLElement {
  const today = timeline.frames[index].day;
  const plan = timeline.frames[timeline.frames.length - 1].plan;
  const keys: [string, string][] = [
    ...placed(plan).map((place) => place.step).filter(isMilestone).map((step) =>
      [step.id, milestoneLabel(step)] as [string, string]
    ),
  ];
  const rows = recording.rows.filter((row) => row.day <= today);
  if (rows.some((row) => row.stretches.some((stretch) => !stretch.key))) {
    keys.push(["", "Remaining work"]);
  }
  const byDay = new Map(rows.map((row) => [row.day, row]));
  const table = h(
    "table",
    { class: "records" },
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", {}, "Day"),
        h("th", {}, "What happened"),
        ...keys.map(([, label]) => h("th", {}, label)),
      ),
    ),
  );
  const body = h("tbody");
  for (const frame of timeline.frames.slice(0, index + 1).reverse()) {
    const row = byDay.get(frame.day);
    const found = parity?.find((one) => one.day === frame.day);
    body.append(
      h(
        "tr",
        { class: row ? "" : "absent" },
        h(
          "td",
          { class: "day" },
          `${weekdayName(frame.day).slice(0, 3)} ${shortDate(frame.day, today)}`,
          found
            ? h("div", {
              class: `parity ${found.same ? "same" : "different"}`,
              title: found.differences.join("\n"),
            }, found.same ? "= DPlanner's row" : "≠ DPlanner's row")
            : null,
        ),
        h("td", { class: "events" }, frame.events.join("; ") || ""),
        ...(row ? keys.map(([key]) => h("td", { class: "cell" }, stretchText(row, key, today))) : [
          h(
            "td",
            { colspan: keys.length || 1, class: "absent" },
            "no row — the window was closed, or nothing had changed",
          ),
        ]),
      ),
    );
  }
  table.append(body);
  const latest = rows[rows.length - 1];
  return h(
    "div",
    { class: "records-tab" },
    h(
      "p",
      { class: "lede" },
      `${rows.length} automatic row${rows.length === 1 ? "" : "s"} and ${
        recording.saved.filter((row) => row.day <= today).length
      } saved snapshot(s) by ${shortDate(today, today)}. `,
      "A row is written on a day the recorder ran and the plan it would record differs from the last one; the last write of a day wins.",
      parity ? ` Replay: ${parityWords(parity)}.` : "",
    ),
    savedList(recording, today),
    table,
    latest
      ? h(
        "details",
        {},
        h(
          "summary",
          {},
          `The latest row as progress_history.json stores it (${isoDay(latest.day)})`,
        ),
        h("pre", {}, JSON.stringify(rowJson(latest), null, 2)),
      )
      : null,
  );
}

function savedList(recording: Recording, today: Day): HTMLElement | null {
  const saved = recording.saved.filter((row) => row.day <= today);
  if (!saved.length) return null;
  return h(
    "ul",
    { class: "saved" },
    ...saved.map((row) =>
      h(
        "li",
        {},
        h("b", {}, row.title),
        ` · ${shortDate(row.day, today)}`,
        row.note ? ` — ${row.note}` : "",
      )
    ),
  );
}
