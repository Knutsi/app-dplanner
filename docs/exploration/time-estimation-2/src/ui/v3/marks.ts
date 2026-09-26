/** The marks v3's two tabs share. */

import { n } from "../markup.ts";

export const CHECK_R = 8;

/** A circle with a check, in the milestone's colour: this milestone is done. */
export function landedCheck(x: number, y: number, color: string): string {
  return `<circle cx="${n(x)}" cy="${n(y)}" r="${CHECK_R}" fill="${color}" class="landed-check"/>` +
    `<path d="M${n(x - 3.8)},${n(y + 0.2)} L${n(x - 1)},${n(y + 3)} L${n(x + 4)},${
      n(y - 3)
    }" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
}
