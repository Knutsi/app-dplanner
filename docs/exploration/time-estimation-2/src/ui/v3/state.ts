/**
 * v3's view state: which tab, which plan it is compared with, which milestone the Work tab
 * shows, and any what-if. Kept apart from v1's and v2's, so a pick in one never leaks into
 * another.
 */

import type { WhatIf } from "../../present.ts";
import type { ComparePick } from "../compare.ts";

export type V3Page = "milestones" | "work";

export interface V3State {
  page: V3Page;
  then: ComparePick;
  scope: string | null; // A milestone's step id; "" the work after the last one; null all work.
  whatIf: WhatIf;
}

export const V3_START: V3State = {
  page: "milestones",
  then: { kind: "start" },
  scope: null,
  whatIf: {},
};

export interface V3Handlers {
  state(patch: Partial<V3State>): void;
  save(title: string, note: string): string | null; // The refusal, or null when saved.
}
