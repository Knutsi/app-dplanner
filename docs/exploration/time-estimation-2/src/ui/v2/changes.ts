/**
 * What changed since the plan compared with — the *why* beside the burn-up, for the selected
 * scope's own work. It names what the plan can name (steps born later, estimates changed),
 * counts what it cannot (removed or moved steps: a record keeps counts, not steps), and says
 * plainly when dates moved with no change in scope, since records do not keep the team,
 * focus or start date that would explain it.
 */

import { type Day, formatDays, g, shortDate } from "../../model/calendar.ts";
import { stepKey } from "../../model/graph.ts";
import type { ChangeList, Scope } from "../../brief.ts";
import { h } from "../markup.ts";
import { glyphPath } from "../glyphs.ts";
import { moveParts, workingDays } from "./words.ts";

const LISTED = 6;

function arrow(direction: "up" | "down"): SVGElement {
  const holder = h("span", { class: "inline-glyph" });
  holder.innerHTML = `<svg width="12" height="12"><path d="${
    glyphPath({ x: 6, y: 6, size: 8 }, direction)
  }" class="scope-${direction}-glyph"/></svg>`;
  return holder.firstElementChild as SVGElement;
}

function signed(value: number, unit = ""): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : "±"}${g(Math.abs(value))}${unit}`;
}

export function changesPanel(
  listed: ChangeList | null,
  scope: Scope,
  basis: string,
  today: Day,
): HTMLElement {
  if (!listed) {
    return h(
      "div",
      { class: "changes empty-note" },
      h("h3", {}, "What changed"),
      h(
        "p",
        {},
        "Nothing recorded before today to compare with. Pick a saved snapshot or a day under “Compared with”.",
      ),
    );
  }
  const items: (HTMLElement | null)[] = [];
  const scopeLine = listed.steps === 0 && Math.abs(listed.days) < 1e-9
    ? h("li", {}, "Scope unchanged.")
    : h(
      "li",
      { class: "scope-line" },
      listed.days >= 0 ? arrow("up") : arrow("down"),
      ` Scope ${
        signed(listed.steps, listed.steps === 1 || listed.steps === -1 ? " step" : " steps")
      }, ${signed(listed.days, "d")} of work.`,
    );
  items.push(scopeLine);
  if (scope.move.total !== null) {
    const why = moveParts(scope.move);
    items.push(
      h(
        "li",
        {},
        scope.move.total === 0
          ? "Lands the same day."
          : `Lands ${workingDays(scope.move.total)} ${scope.move.total > 0 ? "later" : "earlier"}${
            why ? ` — ${why}` : ""
          }.`,
      ),
    );
  }
  if (listed.unexplained) {
    items.push(
      h(
        "li",
        { class: "note-box" },
        "The dates moved with no change in scope: a different team, focus or start date. Records do not keep which.",
      ),
    );
  }
  if (listed.added.length) {
    items.push(
      h(
        "li",
        {},
        `Added (${listed.added.length}):`,
        h(
          "ul",
          {},
          ...listed.added.slice(0, LISTED).map(([step, days]) =>
            h(
              "li",
              {},
              h("span", { class: "key" }, stepKey(step)),
              ` ${step.title}`,
              h(
                "span",
                { class: "planned" },
                ` ${days !== null ? formatDays(days) : "unsized"}${
                  step.created !== null ? ` · ${shortDate(step.created, today)}` : ""
                }`,
              ),
            )
          ),
          listed.added.length > LISTED
            ? h("li", { class: "planned" }, `and ${listed.added.length - LISTED} more`)
            : null,
        ),
      ),
    );
  }
  if (listed.estimates.length) {
    items.push(
      h(
        "li",
        {},
        `Re-estimated (${listed.estimates.length}):`,
        h(
          "ul",
          {},
          ...listed.estimates.slice(0, LISTED).map(([step, day, was, now]) =>
            h(
              "li",
              {},
              h("span", { class: "key" }, stepKey(step)),
              ` ${step.title}`,
              h(
                "span",
                { class: "planned" },
                ` ${formatDays(was)} → ${now !== null ? formatDays(now) : "unsized"} · ${
                  shortDate(day, today)
                }`,
              ),
            )
          ),
          listed.estimates.length > LISTED
            ? h("li", { class: "planned" }, `and ${listed.estimates.length - LISTED} more`)
            : null,
        ),
      ),
    );
  }
  if (listed.unnamed) {
    items.push(
      h(
        "li",
        {},
        listed.unnamed > 0
          ? `${listed.unnamed} step${
            listed.unnamed === 1 ? "" : "s"
          } moved in from another milestone (not named).`
          : `${-listed.unnamed} step${listed.unnamed === -1 ? "" : "s"} ${
            listed.moved ? "moved to another milestone" : "removed or moved out"
          } (not named — records keep counts, not steps).`,
      ),
    );
  }
  items.push(
    h(
      "li",
      {},
      listed.doneSteps > 0
        ? `Done since: ${listed.doneSteps} step${listed.doneSteps === 1 ? "" : "s"}, ${
          formatDays(listed.doneDays) || "0d"
        } of work.`
        : listed.doneSteps < 0
        ? `${-listed.doneSteps} step${listed.doneSteps === -1 ? "" : "s"} reopened since: ${
          formatDays(-listed.doneDays) || "0d"
        } of work no longer counts as done.`
        : "Nothing done since.",
    ),
  );
  return h(
    "div",
    { class: "changes" },
    h("h3", {}, `What changed since ${basis} (${shortDate(listed.since, today)})`),
    h("ul", {}, ...items),
  );
}
