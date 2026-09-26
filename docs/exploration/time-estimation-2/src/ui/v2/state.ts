/**
 * v2's own view state — kept apart from v1's, so a pick made in one never leaks into the
 * other. There is no "now" picker: now is the debugger's day.
 */

import type { WhatIf } from "../../present.ts";
import type { ComparePick } from "../compare.ts";

export interface V2State {
  then: ComparePick;
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
