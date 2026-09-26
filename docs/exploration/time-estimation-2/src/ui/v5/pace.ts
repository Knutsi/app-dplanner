/**
 * v5's *Pace so far*: a toggle that re-estimates what is left at the pace finished steps went
 * — each step's estimate against the working days it took (`paceSoFar`). Greyed until there
 * is enough to go on, and while History looks back; the label carries the pace itself.
 */

import { asPlanned, PACE_AFTER, PACE_STEPS } from "../../model/simulate.ts";
import type { TimeView } from "../../present.ts";
import { h } from "../markup.ts";

const pct = (share: number) => `${Math.round(share * 100)}%`;

export function paceToggle(
  view: TimeView,
  on: boolean,
  toggle: (pace: boolean) => void,
  off?: string,
): HTMLElement {
  const { pace } = view;
  const title = off ??
    (pace === null
      ? `The pace so far needs ${PACE_AFTER} working days of work and ${PACE_STEPS} finished steps`
      : asPlanned(pace)
      ? `Finished steps took about their estimates (${pct(pace)} of the planned pace): ` +
        "the dates stay as planned"
      : `Re-estimate what is left at the pace so far: finished steps went at ${pct(pace)} ` +
        `of the planned pace, taking ${(1 / pace).toFixed(1)}× their estimates`);
  // Pressed only while the dates run at it: kept on, a toggle waits out a day too early.
  const applied = on && !off && pace !== null;
  return h("button", {
    class: `pace-toggle${applied ? " on" : ""}`,
    disabled: Boolean(off) || pace === null,
    title,
    "aria-pressed": String(applied),
    onclick: () => toggle(!on),
  }, pace === null || off ? "Pace so far" : `Pace so far · ${pct(pace)}`);
}
