// A component keeps its CSS beside its code, in one css`` sheet, and adopts it into the
// document once. Components render into light DOM (see ui/README.md): the page's tokens,
// variants and themes reach every one of them with no ::part plumbing.

export { css } from "../engine/template.js";

const adopted = new Set();

export function adopt(...sheets) {
  for (const sheet of sheets) {
    if (adopted.has(sheet)) continue;
    adopted.add(sheet);
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  }
}
