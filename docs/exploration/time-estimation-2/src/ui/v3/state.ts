/**
 * The tabbed designs' view state (v3, and v4 and v5 after it): which tab, which plan it is
 * compared with, which milestone the Work tab shows, and any what-if; v5 adds the calendar's
 * month, the day History looks back to, and whether what is left is adjusted for efficiency. Each design keeps its own copy, so a pick in one
 * never leaks into another.
 */

import type { Day } from "../../model/calendar.ts";
import type { WhatIf } from "../../present.ts";
import type { ComparePick } from "../compare.ts";

export type V3Page = "milestones" | "work" | "calendar";

export interface V3State {
  page: V3Page;
  then: ComparePick;
  scope: string | null; // A milestone's step id; "" the work after the last one; null all work.
  whatIf: WhatIf;
  offset: number; // The calendar's month pager.
  asOf: Day | null; // The recorded day History shows; null for today.
  adjust: boolean; // What is left adjusted for the efficiency so far (ModelOptions.pace).
}

export const V3_START: V3State = {
  page: "milestones",
  then: { kind: "start" },
  scope: null,
  whatIf: {},
  offset: 0,
  asOf: null,
  adjust: false,
};

export interface V3Handlers {
  state(patch: Partial<V3State>): void;
  save(title: string, note: string): string | null; // The refusal, or null when saved.
}
