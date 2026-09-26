/**
 * The prototype's page: a dark debugger over a light view.
 *
 * The **view** is the Time tab as DPlanner would show it on the scrubbed day — nothing on it
 * exists only in the prototype. The **debugger** is everything that does: which plan and
 * scenario, the model variants and the recorder, the day scrubber, what happened that day,
 * the track record and the raw records. Its bar (the scrubber) stays pinned at the top; its
 * body folds away, section by section or whole (`d`), so the view can be read on its own.
 *
 * Three things are kept apart on purpose (timeline.ts has the why): the *timeline* is what
 * happened; the *recording* is what DPlanner wrote down about it, under the chosen recorder
 * cadence and model variants; the *view state* is how the tab is being looked at.
 */

import {
  type Day,
  formatDate,
  isoDay,
  parseDay,
  shortDate,
  weekdayName,
} from "./model/calendar.ts";
import { isMilestone, placed } from "./model/graph.ts";
import { FAITHFUL, type ModelOptions, VARIANTS } from "./model/options.ts";
import { milestoneColors } from "./model/palettes.ts";
import { AT_START, LIVE } from "./model/progress.ts";
import { type ExportFile, isExport } from "./data.ts";
import { present, type ViewState, type WhatIf } from "./present.ts";
import { type Parity, parity, replay } from "./sim/replay.ts";
import { SAMPLE_START, samplePlan } from "./sim/sample.ts";
import { SAVED_BY_DEFAULT, scenarioById, SCENARIOS } from "./sim/scenarios.ts";
import {
  type Cadence,
  CADENCES,
  record,
  recordedBy,
  type Recording,
  type SavedSpec,
  type Timeline,
} from "./sim/timeline.ts";
import { DEFAULT_WORLD, run, type WorldParams } from "./sim/world.ts";
import { renderFigures } from "./ui/figures.ts";
import { recordsView } from "./ui/records.ts";
import { h } from "./ui/markup.ts";
import { timeTab } from "./ui/timetab.ts";
import { trackRecord } from "./ui/track.ts";

interface App {
  source: string; // "sample", or an export's slug
  seed: number;
  scenario: string;
  world: WorldParams;
  cadence: Cadence;
  options: ModelOptions;
  frame: number;
  view: ViewState;
  saved: SavedSpec[]; // Saved by hand on this page.
  offset: number;
}

/** Which parts of the debugger are unfolded — a per-viewer convenience, kept in the browser. */
interface Folds {
  open: boolean; // The body under the bar.
  setup: boolean;
  track: boolean;
  records: boolean;
}

const FOLDS_KEY = "te2.debugger";

const exports = new Map<string, ExportFile>();
const app: App = {
  source: "sample",
  seed: 1,
  scenario: SCENARIOS[0].id,
  world: { ...DEFAULT_WORLD, ...SCENARIOS[0].world },
  cadence: "weekdays",
  options: { ...FAITHFUL },
  frame: -1,
  view: { picked: null, then: AT_START, now: LIVE, lens: "calendar", page: "progress", whatIf: {} },
  saved: [],
  offset: 0,
};
let folds: Folds = readFolds();

function readFolds(): Folds {
  const fallback = { open: true, setup: true, track: false, records: false };
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem(FOLDS_KEY) ?? "{}") };
  } catch {
    return fallback;
  }
}

function fold(patch: Partial<Folds>): void {
  folds = { ...folds, ...patch };
  try {
    localStorage.setItem(FOLDS_KEY, JSON.stringify(folds));
  } catch {
    // A private window or blocked storage: the folds just do not outlive the page.
  }
  body.hidden = !folds.open;
  toggle.textContent = folds.open ? "▾ Debugger" : "▸ Debugger";
  renderContent();
}

// -- what is derived, and cached while its inputs hold --------------------------------------------

let timelineKey = "";
let timeline: Timeline;
let replayed: Parity[] | null = null;
let recordingKey = "";
let recording: Recording;
let compared: Recording | null = null;

function currentTimeline(): Timeline {
  const key = JSON.stringify([app.source, app.seed, app.world]);
  if (key !== timelineKey) {
    timelineKey = key;
    const file = exports.get(app.source);
    timeline = file
      ? replay(file)
      : run(samplePlan(app.seed), { ...app.world, seed: app.seed }, SAMPLE_START);
    replayed = file ? parity(timeline) : null;
    app.frame = file ? timeline.frames.length - 1 : Math.min(
      timeline.frames.length - 1,
      timeline.frames.findIndex((f) => f.day === timeline.begin) + 14,
    );
    app.offset = 0;
  }
  return timeline;
}

function savedSpecs(): SavedSpec[] {
  if (timeline.kind === "replay") return app.saved;
  return [
    ...SAVED_BY_DEFAULT.map((one) => ({
      day: timeline.begin + one.after,
      title: one.title,
      note: one.note,
    })),
    ...app.saved,
  ];
}

function currentRecording(): Recording {
  const key = JSON.stringify([timelineKey, app.options, app.cadence, app.saved]);
  if (key !== recordingKey) {
    recordingKey = key;
    const spec = {
      options: app.options,
      cadence: app.cadence,
      saved: savedSpecs(),
      seed: app.seed,
    };
    recording = record(timeline, spec);
    const variant = VARIANTS.some(({ key }) => app.options[key]);
    compared = variant && app.cadence !== "stored"
      ? record(timeline, { ...spec, options: FAITHFUL })
      : null;
  }
  return recording;
}

// -- the page ----------------------------------------------------------------------------------------

const root = document.getElementById("app")!;
let content: HTMLElement;
let body: HTMLElement;
let toggle: HTMLButtonElement;
let happened: HTMLElement;
let trackHost: HTMLElement;
let recordsHost: HTMLElement;
let viewTitle: HTMLElement;

function render(): void {
  currentTimeline();
  currentRecording();
  root.replaceChildren(debuggerBar(), debuggerBody(), viewFrame());
  renderContent();
  writeHash();
}

/** Everything that depends on the day: the view, and the debugger's day-bound parts. */
function renderContent(): void {
  const frame = timeline.frames[app.frame];
  const upToDay = recordedBy(recording, frame.day);
  content.replaceChildren(timeContent(frame.plan, frame.day, upToDay));
  viewTitle.textContent = `${frame.plan.title} — Time Estimates`;
  happened.replaceChildren(events(frame.events));
  // The two heavy readings run only while someone is looking at them.
  trackHost.replaceChildren(
    folds.open && folds.track
      ? trackRecord(timeline, recording, compared, app.options, app.frame)
      : "",
  );
  recordsHost.replaceChildren(
    folds.open && folds.records ? recordsView(timeline, recording, app.frame, replayed) : "",
  );
  updateBar();
}

function viewFrame(): HTMLElement {
  viewTitle = h("span", { class: "view-tab" });
  content = h("main");
  return h("section", { class: "view" }, h("div", { class: "view-tabs" }, viewTitle), content);
}

function timeContent(
  plan: Timeline["frames"][number]["plan"],
  day: Day,
  upToDay: Recording,
): HTMLElement {
  const view = present(plan, day, upToDay, app.view, app.options);
  if (!view) {
    return h(
      "div",
      { class: "empty" },
      "No steps yet — the staffing grid and the calendar date a plan once it has some.",
    );
  }
  return timeTab(view, app.view, {
    view: (patch) => {
      app.view = { ...app.view, ...patch };
      renderContent();
    },
    whatIf: (patch) => {
      app.view = {
        ...app.view,
        whatIf: patch === null ? {} : { ...app.view.whatIf, ...patch } as WhatIf,
      };
      renderContent();
    },
    save: (title, note) => {
      const named = title.trim();
      if (!named) return "A snapshot needs a title.";
      if (
        upToDay.saved.some((row) => row.title.toLowerCase() === named.toLowerCase()) ||
        app.saved.some((one) => one.title.toLowerCase() === named.toLowerCase())
      ) {
        return `A snapshot called “${named}” is already saved.`;
      }
      app.saved = [...app.saved, { day, title: named, note: note.trim() }];
      currentRecording();
      renderContent();
      return null;
    },
    offset: app.offset,
    page: (offset) => {
      app.offset = offset;
      renderContent();
    },
  });
}

// -- the debugger's body -----------------------------------------------------------------------------

/** A foldable part of the debugger, its fold remembered. */
function section(key: "setup" | "track" | "records", name: string, ...inner: HTMLElement[]) {
  const details = h(
    "details",
    { class: "debug-section", open: folds[key] },
    h("summary", {}, name),
    ...inner,
  );
  details.addEventListener("toggle", () => {
    if (details.open !== folds[key]) fold({ [key]: details.open });
  });
  return details;
}

function debuggerBody(): HTMLElement {
  happened = h("div", { class: "happened" });
  trackHost = h("div");
  recordsHost = h("div");
  body = h(
    "section",
    { class: "debug debug-body", hidden: !folds.open },
    section("setup", "Plan, scenario and model", ...setupRows()),
    happened,
    section("track", "Track record — how good the forecasts were", trackHost),
    section("records", "Records — what progress_history.json holds", recordsHost),
  );
  return body;
}

function setupRows(): HTMLElement[] {
  const file = exports.get(app.source);
  const source = h(
    "select",
    {
      onchange: (event: Event) => {
        app.source = (event.target as HTMLSelectElement).value;
        app.cadence = exports.has(app.source)
          ? "stored"
          : scenarioById(app.scenario).cadence ?? "weekdays";
        app.saved = [];
        app.view = { ...app.view, whatIf: {}, picked: null, then: AT_START, now: LIVE };
        render();
      },
    },
    h("option", { value: "sample", selected: !file }, "Synthetic sample plan"),
    ...[...exports.values()].map((one) =>
      h(
        "option",
        { value: one.slug, selected: one.slug === app.source },
        `Replay: ${one.title} (${one.slug}, ${one.frames.length} commits)`,
      )
    ),
  );
  const open = h("input", {
    type: "file",
    accept: ".json",
    onchange: async (event: Event) => {
      const chosen = (event.target as HTMLInputElement).files?.[0];
      if (chosen) adopt(JSON.parse(await chosen.text()));
    },
  });
  const rows: HTMLElement[] = [
    h(
      "div",
      { class: "row" },
      h("label", {}, "Plan ", source),
      file ? null : h(
        "label",
        {},
        "seed ",
        h("input", {
          type: "number",
          value: String(app.seed),
          class: "short",
          onchange: (event: Event) => {
            app.seed = Number((event.target as HTMLInputElement).value) || 1;
            app.saved = [];
            render();
          },
        }),
      ),
      h(
        "label",
        {
          class: "open",
          title: "An export written by tools/export_plan.ts — or drop one anywhere on the page",
        },
        "open an export… ",
        open,
      ),
    ),
  ];
  if (!file) rows.push(scenarioRow());
  rows.push(modelRow(Boolean(file)));
  return rows;
}

function scenarioRow(): HTMLElement {
  const scenario = scenarioById(app.scenario);
  const select = h(
    "select",
    {
      onchange: (event: Event) => {
        const chosen = scenarioById((event.target as HTMLSelectElement).value);
        app.scenario = chosen.id;
        app.world = { ...DEFAULT_WORLD, ...chosen.world };
        app.cadence = chosen.cadence ?? "weekdays";
        app.saved = [];
        render();
      },
    },
    ...SCENARIOS.map((one) =>
      h("option", { value: one.id, selected: one.id === app.scenario }, one.name)
    ),
  );
  const number = (key: keyof WorldParams, label: string, step: number, hint: string) =>
    h(
      "label",
      { title: hint },
      `${label} `,
      h("input", {
        type: "number",
        class: "short",
        step: String(step),
        value: String(app.world[key] ?? ""),
        placeholder: "as stored",
        onchange: (event: Event) => {
          const raw = (event.target as HTMLInputElement).value;
          (app.world as unknown as Record<string, unknown>)[key] = raw === "" ? null : Number(raw);
          render();
        },
      }),
    );
  const flag = (key: "workAhead" | "dated", label: string) =>
    h(
      "label",
      {},
      h("input", {
        type: "checkbox",
        checked: app.world[key],
        onchange: (event: Event) => {
          app.world = { ...app.world, [key]: (event.target as HTMLInputElement).checked };
          render();
        },
      }),
      ` ${label}`,
    );
  const world = h(
    "details",
    { class: "world" },
    h("summary", {}, "Adjust the world"),
    h(
      "div",
      { class: "params" },
      number("humanBias", "human effort ×", 0.05, "True effort ÷ estimate for human steps"),
      number("agentBias", "agent effort ×", 0.05, "True effort ÷ estimate for agent steps"),
      number("noise", "noise σ", 0.05, "Each step's own luck: lognormal spread around the bias"),
      number(
        "unestimatedEffort",
        "unsized step days",
        0.25,
        "What a step nobody estimated really takes",
      ),
      number(
        "focus",
        "real focus",
        0.05,
        "The share of a day people really give; empty = what the plan assumes",
      ),
      number(
        "agentLoad",
        "supervision",
        0.05,
        "Share of a person's day each running agent step takes",
      ),
      number(
        "scopePerWeek",
        "steps added / week",
        0.5,
        "Scope creep into the milestone being worked",
      ),
      number("reestimateEvery", "re-estimate every (days)", 1, "0 = never"),
      number("reestimateFactor", "re-estimate ×", 0.05, "How much a re-estimate multiplies by"),
      flag("workAhead", "team works ahead"),
      flag("dated", "plan has a start date"),
    ),
  );
  return h(
    "div",
    { class: "row scenario" },
    h("label", {}, "Scenario ", select),
    h("span", { class: "breaks" }, h("b", {}, "Breaks: "), scenario.breaks),
    world,
    h("div", { class: "look" }, h("b", {}, "Look at: "), scenario.look),
  );
}

function modelRow(replaying: boolean): HTMLElement {
  const cadence = h(
    "select",
    {
      onchange: (event: Event) => {
        app.cadence = (event.target as HTMLSelectElement).value as Cadence;
        render();
      },
    },
    ...CADENCES.filter(({ key }) => replaying || key !== "stored").map(({ key, label }) =>
      h("option", { value: key, selected: key === app.cadence }, label)
    ),
  );
  return h(
    "div",
    { class: "row model" },
    h(
      "label",
      { title: "Which days the recorder ran — the window was open — and so wrote a row" },
      "Recorder runs ",
      cadence,
    ),
    h("span", { class: "label" }, "Model variants:"),
    ...VARIANTS.map(({ key, label, hint }) =>
      h(
        "label",
        { title: hint },
        h("input", {
          type: "checkbox",
          checked: app.options[key],
          disabled: app.cadence === "stored",
          onchange: (event: Event) => {
            app.options = { ...app.options, [key]: (event.target as HTMLInputElement).checked };
            render();
          },
        }),
        ` ${label}`,
      )
    ),
    app.cadence === "stored"
      ? h(
        "span",
        { class: "note" },
        "(the variants apply to what the prototype records, not to what DPlanner stored)",
      )
      : null,
  );
}

function events(lines: string[]): HTMLElement {
  return h(
    "div",
    { class: "events" },
    h("b", {}, "What happened today: "),
    lines.length ? lines.join(" · ") : "nothing",
  );
}

// -- the debugger's bar: the days --------------------------------------------------------------------

let slider: HTMLInputElement;
let label: HTMLElement;
let playing: number | null = null;

function debuggerBar(): HTMLElement {
  const last = timeline.frames.length - 1;
  slider = h("input", {
    type: "range",
    min: "0",
    max: String(last),
    value: String(app.frame),
    oninput: (event: Event) => go(Number((event.target as HTMLInputElement).value)),
  });
  label = h("span", { class: "today-label" });
  toggle = h("button", {
    class: "fold",
    title: "Fold the debugger away to read the view on its own (d)",
    onclick: () => fold({ open: !folds.open }),
  }, folds.open ? "▾ Debugger" : "▸ Debugger");
  const play = h("button", {
    title: "Play the days",
    onclick: () => {
      if (playing !== null) {
        clearInterval(playing);
        playing = null;
        play.textContent = "▶";
        return;
      }
      if (app.frame >= last) go(0);
      play.textContent = "❚❚";
      playing = setInterval(() => {
        if (app.frame >= last) {
          clearInterval(playing!);
          playing = null;
          play.textContent = "▶";
          return;
        }
        go(app.frame + 1);
      }, 220);
    },
  }, "▶");
  const scenario = exports.has(app.source)
    ? `replay of ${exports.get(app.source)!.title}`
    : `${scenarioById(app.scenario).name} · seed ${app.seed}`;
  return h(
    "div",
    { class: "debug debug-bar" },
    h(
      "div",
      { class: "controls" },
      toggle,
      h("button", { title: "First day", onclick: () => go(0) }, "⏮"),
      h("button", { title: "A day earlier (←)", onclick: () => go(app.frame - 1) }, "◂"),
      play,
      h("button", { title: "A day later (→)", onclick: () => go(app.frame + 1) }, "▸"),
      h("button", { title: "Last day", onclick: () => go(last) }, "⏭"),
      label,
      h("span", { class: "scenario-name" }, scenario),
      h(
        "nav",
        {},
        h("a", { href: "explainer.html" }, "Explainer"),
        h("a", { href: "ISSUES.md" }, "Issues"),
        h("a", { href: "README.md" }, "README"),
      ),
    ),
    h("div", { class: "track-strip" }, slider, h("div", { class: "ticks", html: ticks() })),
  );
}

/** Marks under the slider: recorded days, saved snapshots, real landings. */
function ticks(): string {
  const frames = timeline.frames;
  const at = (day: Day) => ((day - frames[0].day) / Math.max(1, frames.length - 1)) * 100;
  const out = [`<svg viewBox="0 0 100 14" preserveAspectRatio="none" width="100%" height="14">`];
  for (const row of recording.rows) {
    out.push(
      `<rect x="${
        at(row.day) - 0.1
      }" y="0" width="0.2" height="5" fill="var(--secondary)"><title>recorded ${
        isoDay(row.day)
      }</title></rect>`,
    );
  }
  for (const row of recording.saved) {
    out.push(
      `<rect x="${
        at(row.day) - 0.15
      }" y="0" width="0.3" height="14" fill="var(--ink)"><title>saved: ${row.title}</title></rect>`,
    );
  }
  const plan = frames[frames.length - 1].plan;
  const colors = milestoneColors(plan, plan.assumptions.palette);
  for (const step of placed(plan).map((place) => place.step).filter(isMilestone)) {
    const day = timeline.finished.get(step.id);
    if (day !== undefined) {
      out.push(
        `<rect x="${at(day) - 0.35}" y="7" width="0.7" height="7" fill="${
          colors.get(step.id)
        }"><title>${step.milestone} really landed ${isoDay(day)}</title></rect>`,
      );
    }
  }
  out.push("</svg>");
  return out.join("");
}

function updateBar(): void {
  const day = timeline.frames[app.frame].day;
  slider.value = String(app.frame);
  const worked = day - timeline.begin;
  label.textContent = `${weekdayName(day)} ${formatDate(day, day)} — ` +
    (worked >= 0
      ? `day ${worked + 1} since work began (${shortDate(timeline.begin, day)})`
      : `${-worked} day${worked === -1 ? "" : "s"} before work begins`) +
    ` · ${app.frame + 1} of ${timeline.frames.length}`;
}

function go(index: number): void {
  app.frame = Math.max(0, Math.min(timeline.frames.length - 1, index));
  renderContent();
  writeHash();
}

// -- loading, the address bar, the keyboard ---------------------------------------------------------

function adopt(value: unknown): void {
  if (!isExport(value)) {
    alertInPage("That file is not an export — tools/export_plan.ts writes one.");
    return;
  }
  exports.set(value.slug, value);
  app.source = value.slug;
  app.cadence = "stored";
  app.saved = [];
  render();
}

function alertInPage(message: string): void {
  root.prepend(h("div", { class: "banner error" }, message));
}

function writeHash(): void {
  try {
    const day = timeline.frames[app.frame].day;
    const state = new URLSearchParams({
      source: app.source,
      seed: String(app.seed),
      scenario: app.scenario,
      day: isoDay(day),
      cadence: app.cadence,
      variants: VARIANTS.filter(({ key }) => app.options[key]).map(({ key }) => key).join(","),
    });
    history.replaceState(null, "", `#${state}`);
  } catch {
    // A page opened from disk in some browsers refuses replaceState; the page works without it.
  }
}

function readHash(): void {
  const state = new URLSearchParams(location.hash.slice(1));
  const source = state.get("source");
  if (source && (source === "sample" || exports.has(source))) app.source = source;
  const seed = Number(state.get("seed"));
  if (seed) app.seed = seed;
  const scenario = state.get("scenario");
  if (scenario) {
    app.scenario = scenarioById(scenario).id;
    app.world = { ...DEFAULT_WORLD, ...scenarioById(scenario).world };
    app.cadence = scenarioById(scenario).cadence ?? "weekdays";
  }
  if (exports.has(app.source)) app.cadence = "stored";
  const cadence = state.get("cadence") as Cadence | null;
  if (cadence && CADENCES.some(({ key }) => key === cadence)) app.cadence = cadence;
  const variants = (state.get("variants") ?? "").split(",");
  app.options = { ...FAITHFUL };
  for (const { key } of VARIANTS) app.options[key] = variants.includes(key);
  // A link naming one of the debugger's readings opens it, as the tabs of the first cut did.
  const tab = state.get("tab");
  if (tab === "track" || tab === "records") folds = { ...folds, open: true, [tab]: true };
  currentTimeline();
  // A day, or "end" for the last one — a scenario's length depends on how it plays out.
  const asked = state.get("day");
  const day = parseDay(asked ?? "");
  const index = asked === "end"
    ? timeline.frames.length - 1
    : day !== null
    ? timeline.frames.findIndex((frame) => frame.day === day)
    : -1;
  if (index >= 0) app.frame = index;
}

function start(): void {
  const local = (globalThis as { TE2_LOCAL?: unknown[] }).TE2_LOCAL ?? [];
  for (const file of local) if (isExport(file)) exports.set(file.slug, file);
  readHash();
  render();
  // A link pasted into the address bar; the page's own writes use replaceState, which is silent.
  addEventListener("hashchange", () => {
    readHash();
    render();
  });
  document.addEventListener("keydown", (event) => {
    const target = event.target as HTMLElement;
    if (["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
    if (event.key === "ArrowLeft") go(app.frame - 1);
    if (event.key === "ArrowRight") go(app.frame + 1);
    if (event.key === "d" && !event.ctrlKey && !event.metaKey) fold({ open: !folds.open });
  });
  document.addEventListener("dragover", (event) => event.preventDefault());
  document.addEventListener("drop", async (event) => {
    event.preventDefault();
    const file = event.dataTransfer?.files[0];
    if (file) adopt(JSON.parse(await file.text()));
  });
  let resize: number | undefined;
  addEventListener("resize", () => {
    clearTimeout(resize);
    resize = setTimeout(renderContent, 150);
  });
}

if (document.body.dataset.page === "explainer") renderFigures();
else start();
