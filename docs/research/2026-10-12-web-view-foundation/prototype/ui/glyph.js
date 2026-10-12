// Glyphs: one <svg> sprite in the document, and every glyph a two-node <svg><use> clone of a
// cached template — cheap enough for a status glyph on each of ten thousand rows. The keys
// are DPlanner's (theme/glyphs), so a verb wears the same picture in the window and the web.

import { svg } from "../engine/template.js";
import { GLYPHS } from "./glyphs.js";
import { adopt, css } from "./style.js";

let mounted = false;

function mountSprite() {
  mounted = true;
  const symbols = Object.entries(GLYPHS)
    .map(([name, inner]) => `<symbol id="g-${name}" viewBox="0 0 24 24">${inner}</symbol>`)
    .join("");
  const host = document.createElement("div");
  host.hidden = true;
  host.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg">${symbols}</svg>`; // our own vendored files
  document.body.prepend(host);
}

export function glyph(name, label = null) {
  if (!mounted) mountSprite();
  return label
    ? svg`<svg class="glyph" role="img" aria-label=${label}><use href=${`#g-${name}`}></use></svg>`
    : svg`<svg class="glyph" aria-hidden="true"><use href=${`#g-${name}`}></use></svg>`;
}

export const hasGlyph = (name) => name in GLYPHS;

adopt(css`
  .glyph {
    width: var(--icon);
    height: var(--icon);
    flex: none;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    vertical-align: middle;
  }
`);
