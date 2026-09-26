/**
 * The colour maps milestones are shaded from — `theme/palettes.py` — and the one deal every
 * surface reads, `time_estimates/schedule.py`'s `milestone_colors` and `phase_colors`.
 */

import { pyRound } from "./calendar.ts";
import { isMilestone, placed, type Plan } from "./graph.ts";
import type { Phase } from "./simulate.ts";

export interface Palette {
  id: string;
  name: string;
  stops: string[];
}

export const PALETTES: Palette[] = [
  {
    id: "viridis",
    name: "Viridis",
    stops: ["#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58"],
  },
  {
    id: "mako",
    name: "Mako",
    stops: ["#2f1c4f", "#3b3f7c", "#3b5f92", "#3c7da0", "#47a1ad", "#6dc1ae"],
  },
  {
    id: "crest",
    name: "Crest",
    stops: ["#2a4e7d", "#2d5f8c", "#37739c", "#3f87a3", "#4b9ba2", "#5fae9d", "#7fbf98"],
  },
  {
    id: "plasma",
    name: "Plasma",
    stops: ["#46039f", "#7201a8", "#9c179e", "#bd3786", "#d8576b", "#ed7953", "#fb9f3a"],
  },
  {
    id: "magma",
    name: "Magma",
    stops: ["#3b0f70", "#641a80", "#8c2981", "#b73779", "#de4968", "#f7705c", "#fe9f6d"],
  },
  {
    id: "inferno",
    name: "Inferno",
    stops: ["#420a68", "#781c6d", "#a52c60", "#cf4446", "#ed6925", "#fb9b06"],
  },
  {
    id: "rocket",
    name: "Rocket",
    stops: ["#2c1439", "#5b1a4c", "#8a1f55", "#b7284e", "#dc4b3b", "#f07a3a", "#f8a952"],
  },
  {
    id: "flare",
    name: "Flare",
    stops: ["#5d3444", "#77384f", "#913c56", "#a94057", "#be4a54", "#cf5b4f", "#da6f52", "#e79a6d"],
  },
  {
    id: "cividis",
    name: "Cividis",
    stops: ["#123570", "#3b496c", "#575d6d", "#707173", "#8a8678", "#a59c74", "#c3b369"],
  },
];

export const WHOLE_COLOR = "#5f87d7";
export const REMAINDER_COLOR = "#8b8f96";

export function paletteById(id: string | null): Palette {
  return PALETTES.find((found) => found.id === id) ?? PALETTES[0];
}

function mix(low: string, high: string, share: number): string {
  let out = "#";
  for (const offset of [1, 3, 5]) {
    const [start, end] = [
      parseInt(low.slice(offset, offset + 2), 16),
      parseInt(high.slice(offset, offset + 2), 16),
    ];
    out += pyRound(start + (end - start) * share, 0).toString(16).padStart(2, "0");
  }
  return out;
}

export function shade(found: Palette, position: number): string {
  const stops = found.stops;
  const place = Math.min(Math.max(position, 0.0), 1.0) * (stops.length - 1);
  const index = Math.min(Math.floor(place), stops.length - 2);
  return mix(stops[index], stops[index + 1], place - index);
}

/** `shades`: `count` shades dealt evenly along the map, centred. */
export function shades(found: Palette, count: number): string[] {
  return Array.from({ length: count }, (_, index) => shade(found, (index + 0.5) / count));
}

/** `milestone_colors`: a milestone's own colour, else its place in the sequence. */
export function milestoneColors(plan: Plan, paletteId: string | null): Map<string, string> {
  const ordered = placed(plan).map((place) => place.step).filter(isMilestone);
  if (!ordered.length) return new Map();
  const dealt = shades(paletteById(paletteId), ordered.length);
  return new Map(ordered.map((step, index) => [step.id, step.color ?? dealt[index]]));
}

/** `phase_colors`: one colour per stretch; the work after the last milestone is neutral. */
export function phaseColors(stretches: readonly Phase[], colors: Map<string, string>): string[] {
  return stretches.map((phase, index) =>
    phase.milestone
      ? colors.get(phase.milestone.id) ?? WHOLE_COLOR
      : index
      ? REMAINDER_COLOR
      : WHOLE_COLOR
  );
}

/** A hex colour at an alpha, for SVG and CSS. */
export function alpha(hex: string, opacity: number): string {
  const [r, g, b] = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}
