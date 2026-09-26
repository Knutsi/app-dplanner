/**
 * v2's own view state — kept apart from v1's, so a pick made in one never leaks into the
 * other. There is no "now" picker: now is the debugger's day.
 */

import type { Day } from "../../model/calendar.ts";
import type { Pick } from "../../model/progress.ts";
import type { WhatIf } from "../../present.ts";

/** A pick, or "a week ago" — the anchor of a weekly review, relative to today. */
export type V2Pick = Pick | { kind: "week" };

export interface V2State {
  then: V2Pick;
  scope: string | null; // The selected milestone's step id; "" the work after the last; null all.
  whatIf: WhatIf;
  offset: number; // The calendar's month pager.
  folds: { whatif: boolean; calendar: boolean };
}

export const V2_START: V2State = {
  then: { kind: "start" },
  scope: null,
  whatIf: {},
  offset: 0,
  folds: { whatif: false, calendar: false },
};

export interface V2Handlers {
  state(patch: Partial<V2State>): void;
  save(title: string, note: string): string | null; // The refusal, or null when saved.
}

export function resolvePick(pick: V2Pick, today: Day): Pick {
  return pick.kind === "week" ? { kind: "day", day: today - 7 } : pick;
}
