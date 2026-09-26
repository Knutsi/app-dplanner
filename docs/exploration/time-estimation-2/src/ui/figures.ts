/**
 * The explainer's figures, drawn by the prototype's own code from one small fixed example —
 * so a picture in the explainer cannot say something the Time tab would not.
 *
 * The example: one person, full focus, starting Monday 7 September. v1 is Design (1d) and
 * Build (2d); v2 is Polish (3d) and Docs (2d). The window is closed on Tuesday, so no record
 * is written that day. On Thursday a two-day step is added to v2. Today is Friday 11th.
 */

import { type Day, fromYMD, g, shortDate, weekdayName } from "../model/calendar.ts";
import type { Plan, Status, Step } from "../model/graph.ts";
import { FAITHFUL } from "../model/options.ts";
import { AT_START, LIVE, type Pick, pickWords, resolve, type Snapshot } from "../model/progress.ts";
import { type Page, present, type TimeView } from "../present.ts";
import { record, recordedBy, type Timeline } from "../sim/timeline.ts";
import { chartSvg } from "./v1/charts.ts";
import { esc, h, INK, n, SECONDARY } from "./markup.ts";

const MONDAY = fromYMD(2026, 9, 7);
const TODAY = MONDAY + 4;

function step(
  id: string,
  number: number,
  title: string,
  estimate: number,
  requires: string[],
  milestone: string | null = null,
): Step {
  return {
    id,
    number,
    title,
    requires,
    estimate: milestone ? null : estimate,
    estimateOff: milestone !== null,
    estimateHistory: [],
    status: "pending",
    milestone,
    agent: false,
    created: MONDAY - 3,
    start: null,
    color: null,
  };
}

function planOn(day: Day): Plan {
  const steps = [
    step("design", 1, "Design", 1, []),
    step("build", 2, "Build", 2, ["design"]),
    step("v1", 3, "Release 1", 0, ["build"], "v1"),
    step("polish", 4, "Polish", 3, ["v1"]),
    step("docs", 5, "Docs", 2, ["v1"]),
    step("v2", 6, "Release 2", 0, ["polish", "docs"], "v2"),
  ];
  if (day >= MONDAY + 3) {
    steps.splice(5, 0, { ...step("import", 7, "Fix the import", 2, ["v1"]), created: MONDAY + 3 });
    steps[6] = { ...steps[6], requires: [...steps[6].requires, "import"] };
  }
  const done: Record<string, Day> = { design: MONDAY, build: MONDAY + 2, v1: MONDAY + 2 };
  const status = (one: Step): Status =>
    done[one.id] !== undefined && done[one.id] <= day
      ? "done"
      : one.id === "polish" && day >= MONDAY + 3
      ? "in-progress"
      : "pending";
  return {
    id: "example",
    title: "Example",
    start: MONDAY,
    assumptions: { efficiency: 1, palette: "viridis", team: [1, 1] },
    steps: steps.map((one) => ({ ...one, status: status(one) })),
  };
}

function example(): { timeline: Timeline; view: (then: Pick, now?: Pick) => TimeView } {
  const days = [MONDAY, MONDAY + 1, MONDAY + 2, MONDAY + 3, TODAY];
  const timeline: Timeline = {
    title: "Example",
    frames: days.map((day) => ({ day, plan: planOn(day), events: [] })),
    begin: MONDAY,
    finished: new Map(),
    kind: "scenario",
  };
  // Tuesday the window stayed closed: the recorder is "daily" but Tuesday has no frame of its own.
  const recorded = record(
    { ...timeline, frames: timeline.frames.filter((frame) => frame.day !== MONDAY + 1) },
    {
      options: FAITHFUL,
      cadence: "daily",
      saved: [{ day: MONDAY, title: "Kickoff review", note: "" }],
      seed: 1,
    },
  );
  const upToToday = recordedBy(recorded, TODAY);
  return {
    timeline,
    view: (then, now = LIVE) =>
      present(planOn(TODAY), TODAY, upToToday, {
        picked: null,
        then,
        now,
        lens: "calendar",
        page: "progress",
        whatIf: {},
      }, FAITHFUL)!,
  };
}

function chart(view: TimeView, page: Page, holder: HTMLElement): void {
  const width = Math.max(480, Math.min(780, holder.clientWidth - 24));
  holder.innerHTML = chartSvg(view.chart, page, width, `figure-${page}`).svg;
}

/** Which record each kind of pick lands on, over the week's records. */
function picksSvg(rows: Snapshot[], saved: Snapshot[], live: Snapshot): string {
  // Three columns: what was picked, the week, and the words the headings print.
  const [width, left, right, top, row] = [940, 250, 580, 34, 30];
  const first = MONDAY - 4;
  const x = (day: Day) => left + ((day - first) / (TODAY - first)) * (right - left);
  const picks: [string, Pick, Day][] = [
    ["Plan at start", AT_START, MONDAY],
    ["Day… 8 September", { kind: "day", day: MONDAY + 1 }, MONDAY + 1],
    ["Plan at start, if the start were 3 Sep", AT_START, MONDAY - 4],
    ["Kickoff review", { kind: "saved", title: "Kickoff review" }, MONDAY],
    ["Now", LIVE, TODAY],
  ];
  const height = top + picks.length * row + 36;
  const out = [
    `<svg class="chart" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-size="12">`,
  ];
  for (let day = first; day <= TODAY; day += 1) {
    out.push(
      `<text x="${n(x(day))}" y="12" text-anchor="middle" style="fill:${SECONDARY}">${
        weekdayName(day).slice(0, 2)
      } ${shortDate(day, TODAY).split(" ")[0]}</text>`,
    );
    const has = rows.some((one) => one.day === day) || day === TODAY;
    out.push(
      `<circle cx="${n(x(day))}" cy="24" r="${has ? 5 : 3}" style="fill:${
        has ? INK : "none"
      };stroke:${SECONDARY}"><title>${
        has ? (day === TODAY ? "today: the live plan" : "a record") : "no record"
      }</title></circle>`,
    );
  }
  picks.forEach(([label, pick, asked], index) => {
    const y = top + (index + 1) * row;
    const found = resolve(pick, rows, saved, live, pick.kind === "start" ? asked : MONDAY);
    const words = pickWords(pick, found, TODAY) || "nothing to compare with";
    out.push(
      `<text x="0" y="${y}" dominant-baseline="central" style="fill:${INK}">${esc(label)}</text>`,
    );
    out.push(`<circle cx="${n(x(asked))}" cy="${y}" r="3" style="fill:none;stroke:${INK}"/>`);
    if (found) {
      out.push(
        `<line x1="${n(x(asked))}" x2="${
          n(x(found.day))
        }" y1="${y}" y2="${y}" style="stroke:${INK}" stroke-width="1.5"/>`,
      );
      out.push(`<circle cx="${n(x(found.day))}" cy="${y}" r="5" style="fill:${INK}"/>`);
    }
    out.push(
      `<text x="${right + 24}" y="${y}" dominant-baseline="central" style="fill:${SECONDARY}">${
        esc(`→ ${words}`)
      }</text>`,
    );
  });
  out.push(
    `<text x="${left}" y="${
      height - 6
    }" style="fill:${SECONDARY}">○ the day asked for · ● the record that answers · Tuesday has no record: the window was closed</text>`,
  );
  out.push("</svg>");
  return out.join("");
}

function recordTable(row: Snapshot, plan: Plan): HTMLElement {
  const label = (key: string) =>
    plan.steps.find((one) => one.id === key)?.milestone ?? "after the last milestone";
  return h(
    "table",
    {},
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        ...["Stretch", "Steps", "Done", "Days", "Done days", "Starts", "Lands", "What lands when"]
          .map((name) => h("th", {}, name)),
      ),
    ),
    h(
      "tbody",
      {},
      ...row.stretches.map((stretch) =>
        h(
          "tr",
          {},
          h("td", {}, label(stretch.key)),
          h("td", { class: "number" }, String(stretch.tally.steps)),
          h("td", { class: "number" }, String(stretch.tally.done)),
          h("td", { class: "number" }, `${g(stretch.tally.days)}d`),
          h("td", { class: "number" }, `${g(stretch.tally.doneDays)}d`),
          h("td", {}, shortDate(stretch.start, TODAY)),
          h("td", {}, stretch.finish !== null ? shortDate(stretch.finish, TODAY) : "—"),
          h(
            "td",
            {},
            stretch.landings.map((knot) => `${shortDate(knot.day, TODAY)}: ${g(knot.days)}d`).join(
              " · ",
            ),
          ),
        )
      ),
    ),
  );
}

/** The one-plan-doubled example: 50 % both days, twice the work. */
function doubledTable(): HTMLElement {
  return h(
    "table",
    {},
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        ...["Day", "Estimated days in the plan", "Done", "Progress (share)", "Still to do"].map((
          name,
        ) => h("th", {}, name)),
      ),
    ),
    h(
      "tbody",
      {},
      h(
        "tr",
        {},
        h("td", {}, "Monday"),
        h("td", { class: "number" }, "10d"),
        h("td", { class: "number" }, "5d"),
        h("td", { class: "number" }, "50%"),
        h("td", { class: "number" }, "5d"),
      ),
      h(
        "tr",
        {},
        h("td", {}, "Tuesday, after 10 days of work were added"),
        h("td", { class: "number" }, "20d"),
        h("td", { class: "number" }, "10d"),
        h("td", { class: "number" }, "50%"),
        h("td", { class: "number" }, "10d"),
      ),
    ),
  );
}

export function renderFigures(): void {
  const { timeline, view } = example();
  const atStart = view(AT_START);
  const rows = atStart.recording.rows;
  const fill = (name: string, make: (holder: HTMLElement) => void) => {
    for (const holder of document.querySelectorAll<HTMLElement>(`[data-figure="${name}"]`)) {
      make(holder);
    }
  };
  fill("record", (holder) => {
    const thursday = rows.find((one) => one.day === MONDAY + 3)!;
    holder.replaceChildren(recordTable(thursday, timeline.frames[3].plan));
  });
  fill(
    "picks",
    (holder) => (holder.innerHTML = picksSvg(rows, atStart.recording.saved, atStart.live)),
  );
  fill("progress", (holder) => chart(atStart, "progress", holder));
  fill("shift", (holder) => chart(atStart, "shift", holder));
  fill("volume", (holder) => chart(atStart, "volume", holder));
  fill("doubled", (holder) => holder.replaceChildren(doubledTable()));
  fill("words", (holder) => {
    const shifts = atStart.chart.segments.filter((one) => one.key).map((one) => one.words);
    holder.replaceChildren(
      h(
        "ul",
        {},
        h(
          "li",
          {},
          `Scope change heading: “${
            atStart.chart.basis
              ? `Scope change — versus ${atStart.chart.basis}`
              : "nothing to compare with"
          }”`,
        ),
        ...shifts.map((text) => h("li", {}, text)),
      ),
    );
  });
  fill(
    "recorded-days",
    (
      holder,
    ) => (holder.textContent = rows.map((one) =>
      `${weekdayName(one.day).slice(0, 3)} ${shortDate(one.day, TODAY)}`
    ).join(", ")),
  );
}
