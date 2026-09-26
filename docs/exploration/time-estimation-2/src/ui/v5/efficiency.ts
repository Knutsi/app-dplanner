/**
 * v5's *Adjust for efficiency*: a toggle that re-estimates what is left at the efficiency
 * people's finished steps actually ran at — each step's estimate against the working days it
 * took (`paceSoFar`, the ratio to the planned focus). Greyed until there is enough to go on,
 * and while History looks back; the label carries the efficiency measured, beside the
 * Budget's planned one.
 */

import { efficiencyOf } from "../../model/graph.ts";
import { asPlanned, PACE_AFTER, PACE_STEPS } from "../../model/simulate.ts";
import type { TimeView } from "../../present.ts";
import { h } from "../markup.ts";

const pct = (share: number) => `${Math.round(share * 100)}%`;

export function efficiencyToggle(
  view: TimeView,
  on: boolean,
  toggle: (adjust: boolean) => void,
  off?: string,
): HTMLElement {
  const { pace } = view;
  const planned = efficiencyOf(view.plan);
  const measured = pace === null ? null : planned * pace;
  const title = off ??
    (pace === null || measured === null
      ? `Adjusting for efficiency needs ${PACE_AFTER} working days of work and ${PACE_STEPS} ` +
        "finished steps"
      : asPlanned(pace)
      ? `Finished steps ran at about the planned focus (${pct(measured)} against ` +
        `${pct(planned)}): adjusting leaves the dates as they are`
      : `Finished steps ran at ${pct(measured)} focus against the ${pct(planned)} planned, ` +
        `taking ${(1 / pace).toFixed(1)}× their estimates: adjust what is left to it`);
  // Pressed only while the dates run at it: kept on, a toggle waits out a day too early.
  const applied = on && !off && pace !== null;
  return h(
    "button",
    {
      class: `efficiency-toggle${applied ? " on" : ""}`,
      disabled: Boolean(off) || pace === null,
      title,
      "aria-pressed": String(applied),
      onclick: () => toggle(!on),
    },
    measured === null || off ? "Adjust for efficiency" : `Adjust for efficiency · ${pct(measured)}`,
  );
}
