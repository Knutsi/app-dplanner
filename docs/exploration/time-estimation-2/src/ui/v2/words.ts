/**
 * How v2 says things: each verdict as a glyph, a word and a tone — never colour alone — and
 * the few sentences that put the numbers into words. Horizontal glyphs mean time (◀ earlier,
 * ▶ later); vertical ones are kept for scope (glyphs.ts).
 */

import { type Day, formatDate, g, shortDate, weekdayName } from "../../model/calendar.ts";
import type { Move, Pace, Scope, VerdictKind } from "../../brief.ts";

export const VERDICTS: Record<VerdictKind, { glyph: string; word: string; tone: string }> = {
  landed: { glyph: "✓", word: "Landed", tone: "landed" },
  overdue: { glyph: "⚠", word: "Overdue", tone: "overdue" },
  later: { glyph: "▶", word: "Later", tone: "later" },
  earlier: { glyph: "◀", word: "Earlier", tone: "earlier" },
  "on-track": { glyph: "●", word: "On track", tone: "ok" },
  "no-baseline": { glyph: "○", word: "Nothing to compare", tone: "none" },
  new: { glyph: "✚", word: "New", tone: "none" },
};

export function workingDays(count: number): string {
  const size = Math.abs(count);
  return `${size} working day${size === 1 ? "" : "s"}`;
}

export function longDate(day: Day, today: Day): string {
  return `${weekdayName(day).slice(0, 3)} ${formatDate(day, today)}`;
}

/** "+7d", "−3d", "±0" — a move as the chips print it, with its direction glyph. */
export function moveChip(total: number | null): { text: string; tone: string } {
  if (total === null) return { text: "", tone: "none" };
  if (total === 0) return { text: "= same day", tone: "ok" };
  return total > 0
    ? { text: `▶ +${total}d`, tone: "later" }
    : { text: `◀ −${-total}d`, tone: "earlier" };
}

/** Why a landing moved: the plan itself, and today's pace — each named only when it moved. */
export function moveParts(move: Move): string {
  const parts: string[] = [];
  if (move.plan) {
    parts.push(`${move.plan > 0 ? "+" : "−"}${Math.abs(move.plan)} from changes to the plan`);
  }
  if (move.pace) parts.push(`+${move.pace} from today's pace`);
  return parts.join(", ");
}

/** The movement against the plan compared with, in one sentence. */
export function moveSentence(scope: Scope, basis: string, today: Day): string {
  const { move } = scope;
  if (move.total === null || move.then === null) return "";
  const was = `${basis} (${shortDate(move.then, today)})`;
  if (Math.abs(move.total) <= 1) return `Within a day of ${was}.`;
  const direction = move.total > 0 ? "later" : "earlier";
  const why = moveParts(move);
  return `${workingDays(move.total)} ${direction} than ${was}${why ? ` — ${why}` : ""}.`;
}

/** Where the work stands against the plan's own schedule, in days of work. */
export function paceSentence(pace: Pace, today: Day): string {
  if (pace.lag === 0) return "The work is on the plan's own schedule.";
  return `Work due ${shortDate(pace.due!, today)} is not done yet: ${
    workingDays(pace.lag)
  } behind the plan's own schedule` +
    (pace.short > 0 ? ` (${g(Math.round(pace.short * 4) / 4)} days of work).` : ".");
}
