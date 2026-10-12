// Marks: the small, repeated signs a table is made of — a status, an owner, an estimate, an
// age, a progress bar. Status is coded twice, by colour and by shape, so it reads in a glance,
// in greyscale and for someone who cannot tell the theme's red from its green: the two states
// that need a person (done, blocked) are the only filled ones.

import { html } from "../engine/template.js";
import { glyph } from "./glyph.js";
import { adopt, css } from "./style.js";

// DPlanner's glyph per status (modules/step_status/module.py).
export const STATUS_GLYPH = {
  pending: "step",
  "in-progress": "play",
  "ready-for-review": "eye",
  "ready-to-merge": "pull-request",
  done: "check",
  blocked: "stop",
};

const words = (status) => status.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase());

export function statusMark(status, label = words(status)) {
  return html`<span class="status-mark st-${status}" title=${label} role="img" aria-label=${label}>${glyph(STATUS_GLYPH[status] ?? "step")}</span>`;
}

const AGENTS = new Set(["claude", "codex", "opencode"]);

export function ownerChip(owner) {
  if (!owner) return html`<span class="mark-owner none">—</span>`;
  if (AGENTS.has(owner)) return html`<span class="mark-owner agent">${glyph("spark")}<span class="name">${owner}</span></span>`;
  return html`<span class="mark-owner"><i>${owner.slice(0, 2).toUpperCase()}</i><span class="name">${owner}</span></span>`;
}

export function estimate(days) {
  return days === null || days === undefined ? html`<span class="mark-num none">—</span>` : html`<span class="mark-num">${days} d</span>`;
}

const UNITS = [
  [7 * 86400000, "w"],
  [86400000, "d"],
  [3600000, "h"],
  [60000, "m"],
];

export function relativeTime(ms, now = Date.now()) {
  const age = Math.max(0, now - ms);
  for (const [size, unit] of UNITS) if (age >= size) return `${Math.floor(age / size)} ${unit}`;
  return "now";
}

export function progressBar(fraction) {
  const pct = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
  return html`<span class="mark-bar" role="progressbar" aria-valuenow=${pct} aria-valuemin="0" aria-valuemax="100"><i style="width: ${pct}%"></i></span>`;
}

adopt(css`
  .status-mark {
    display: inline-grid;
    place-items: center;
    width: calc(var(--icon) + 2px);
    height: calc(var(--icon) + 2px);
    flex: none;
    border-radius: 50%;
  }
  .status-mark .glyph { width: var(--icon); height: var(--icon); }
  .status-mark.st-pending { color: var(--st-pending); }
  .status-mark.st-in-progress { color: var(--st-progress); }
  .status-mark.st-ready-for-review { color: var(--st-review); }
  .status-mark.st-ready-to-merge { color: var(--st-merge); }
  .status-mark.st-blocked { color: var(--st-blocked); }
  .status-mark.st-blocked .glyph { fill: currentColor; }
  .status-mark.st-done { background: var(--st-done); color: var(--bg); }
  .status-mark.st-done .glyph { width: calc(var(--icon) - 4px); height: calc(var(--icon) - 4px); stroke-width: 3; }

  .mark-owner { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: var(--fg-2); }
  .mark-owner i {
    display: inline-grid;
    place-items: center;
    width: calc(var(--icon) + 2px);
    height: calc(var(--icon) + 2px);
    flex: none;
    border-radius: 50%;
    background: var(--bg-overlay);
    border: 1px solid var(--line-strong);
    font: 600 9px / 1 var(--font-ui);
    font-style: normal;
    color: var(--fg);
  }
  .mark-owner.agent .glyph { color: var(--accent); }
  .mark-owner .name { overflow: hidden; text-overflow: ellipsis; }
  .mark-owner.none, .mark-num.none { color: var(--fg-3); }

  .mark-num { font-variant-numeric: tabular-nums; white-space: nowrap; }

  .mark-bar {
    display: inline-block;
    width: 96px;
    max-width: 100%;
    flex: none;
    height: 4px;
    border-radius: 2px;
    background: var(--line);
    overflow: hidden;
  }
  .mark-bar i { display: block; height: 100%; background: var(--accent); border-radius: inherit; }
`);
