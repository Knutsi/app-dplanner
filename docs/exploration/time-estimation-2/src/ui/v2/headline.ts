/**
 * The headline: the answer first. When it lands at today's pace, what the plan itself says,
 * how that moved against the plan compared with and why, and the one thing that needs a look.
 */

import { g, isoDay, parseDay, percent, shortDate } from "../../model/calendar.ts";
import { pickWords, shareOf } from "../../model/progress.ts";
import type { Brief, Scope } from "../../brief.ts";
import type { TimeView } from "../../present.ts";
import { h } from "../markup.ts";
import { resolvePick, type V2Handlers, type V2Pick, type V2State } from "./state.ts";
import { longDate, moveSentence, paceSentence, VERDICTS, workingDays } from "./words.ts";

/** What the plan compared with is called in a sentence: short, and never a guess. */
export function basisName(pick: V2Pick, view: TimeView): string {
  if (pick.kind === "start") return "the plan at start";
  if (pick.kind === "week") return "the plan a week ago";
  if (pick.kind === "saved") return pick.title;
  if (pick.kind === "now") return "the plan now";
  return `the plan at ${shortDate(pick.day, view.today)}`;
}

export function verdictChip(scope: Scope): HTMLElement {
  const verdict = VERDICTS[scope.verdict];
  return h(
    "span",
    { class: `verdict tone-${verdict.tone}` },
    h("span", { class: "glyph" }, verdict.glyph),
    verdict.word,
  );
}

function comparePicker(view: TimeView, state: V2State, on: V2Handlers): HTMLElement {
  const pick = state.then;
  const select = h("select", {
    title: pickWords(resolvePick(pick, view.today), view.then, view.today) ||
      "Nothing recorded to compare with yet",
    onchange: (event: Event) => {
      const value = (event.target as HTMLSelectElement).value;
      if (value === "start") on.state({ then: { kind: "start" } });
      else if (value === "week") on.state({ then: { kind: "week" } });
      else if (value === "day") on.state({ then: { kind: "day", day: view.today - 14 } });
      else on.state({ then: { kind: "saved", title: value.slice(6) } });
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
    }, `${row.title} · ${shortDate(row.day, view.today)}`));
  }
  select.append(h("option", { value: "day", selected: pick.kind === "day" }, "a day…"));
  const day = pick.kind === "day"
    ? h("input", {
      type: "date",
      value: isoDay(pick.day),
      onchange: (event: Event) => {
        const when = parseDay((event.target as HTMLInputElement).value);
        if (when !== null) on.state({ then: { kind: "day", day: when } });
      },
    })
    : null;
  const found = view.then && view.then.day !== view.today
    ? h("span", { class: "recorded" }, `recorded ${shortDate(view.then.day, view.today)}`)
    : h("span", { class: "recorded missing" }, "nothing recorded before today");
  return h("label", { class: "compare" }, "Compared with ", select, day, found);
}

export function headline(
  view: TimeView,
  found: Brief,
  state: V2State,
  on: V2Handlers,
): HTMLElement {
  const whole = found.whole;
  const basis = basisName(state.then, view);
  const share = shareOf(whole.own);
  const done = `${share === null ? "—" : percent(share)} of the work done (${
    g(whole.own.doneDays)
  } of ${g(whole.own.days)} days)`;
  let answer: HTMLElement;
  if (whole.landedBy !== null) {
    answer = h(
      "div",
      { class: "answer" },
      h("span", { class: "lead" }, "Landed"),
      h("strong", {}, `recorded done by ${longDate(whole.landedBy, view.today)}`),
    );
  } else if (whole.move.projected !== null) {
    const moved = whole.move.projected !== whole.move.planned;
    answer = h(
      "div",
      { class: "answer" },
      h("span", { class: "lead" }, "Lands"),
      h("strong", {}, `${moved ? "~" : ""}${longDate(whole.move.projected, view.today)}`),
      h("span", { class: "qualifier" }, moved ? "at today's pace" : "on schedule"),
    );
  } else {
    answer = h(
      "div",
      { class: "answer" },
      h("span", { class: "lead" }, "Nothing estimated to land"),
    );
  }
  const planned = whole.move.planned !== null && whole.move.projected !== whole.move.planned
    ? `The plan itself says ${longDate(whole.move.planned, view.today)} · `
    : "";
  const verdictLine = h(
    "div",
    { class: "verdict-line" },
    verdictChip(whole),
    h(
      "span",
      {},
      whole.verdict === "no-baseline"
        ? "Nothing recorded before today to compare with — pick a saved snapshot or a day."
        : moveSentence(whole, basis, view.today),
    ),
    " ",
    h(
      "span",
      { class: "pace" },
      whole.landedBy === null ? paceSentence(whole.pace, view.today) : "",
    ),
  );
  return h(
    "header",
    { class: "v2-head" },
    h("div", { class: "v2-controls" }, comparePicker(view, state, on), whatIfChip(state, on)),
    answer,
    h("div", { class: "sub" }, planned + done),
    verdictLine,
    attentionLine(found, view, on),
  );
}

/** The one milestone to look at: an overdue one, or where most of the move was added. */
function attentionLine(found: Brief, view: TimeView, on: V2Handlers): HTMLElement | null {
  const attention = found.attention;
  if (!attention) return null;
  const { scope } = attention;
  const name = `${scope.badge ? scope.badge + " " : ""}${scope.label}`;
  const words = attention.kind === "overdue"
    ? `${name} is overdue — planned ${shortDate(scope.move.planned!, view.today)}, not done; ~${
      shortDate(scope.move.projected ?? view.today, view.today)
    } at today's pace.`
    : `Most of the move is added in ${name}'s own work: +${workingDays(attention.days)}` +
      ` (${
        [
          attention.plan
            ? `${attention.plan > 0 ? "+" : "−"}${
              Math.abs(attention.plan)
            } from changes to the plan`
            : "",
          attention.pace ? `+${attention.pace} from today's pace` : "",
        ].filter(Boolean).join(", ")
      }).`;
  const tone = attention.kind === "overdue" ? "overdue" : "later";
  return h(
    "div",
    {
      class: `attention tone-border-${tone}`,
      role: "button",
      tabindex: "0",
      title: `Show ${name}`,
      onclick: () => on.state({ scope: scope.key }),
      onkeydown: (event: KeyboardEvent) => {
        if (event.key === "Enter") on.state({ scope: scope.key });
      },
    },
    h("span", { class: `glyph tone-${tone}` }, attention.kind === "overdue" ? "⚠" : "▶"),
    ` ${words}`,
  );
}

function whatIfChip(state: V2State, on: V2Handlers): HTMLElement | null {
  if (!Object.keys(state.whatIf).length) return null;
  return h(
    "span",
    { class: "what-if" },
    "what-if active",
    h("button", { class: "link", onclick: () => on.state({ whatIf: {} }) }, "reset"),
  );
}
