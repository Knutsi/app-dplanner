// The look: which design variant and how much motion — per-viewer preferences, kept in the
// browser and written onto <html> where tokens.css reads them.

import { signal, effect } from "../engine/signals.js";

export const VARIANTS = [
  { id: "ledger", label: "Ledger", note: "classic workbench: menubar, toolbar, hairline grid" },
  { id: "modeline", label: "Modeline", note: "keyboard first: mono, verbs in the modeline" },
  { id: "atelier", label: "Atelier", note: "calm and layered: floating toolbar, serif titles" },
];

function stored(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function keep(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* kept for this visit only */
  }
}

const fromUrl = new URLSearchParams(location.search);
export const variant = signal(fromUrl.get("variant") ?? stored("dp.variant", "ledger"));
export const reducedMotion = signal(stored("dp.motion", "full") === "reduced");

effect(() => {
  document.documentElement.dataset.variant = variant.value;
  keep("dp.variant", variant.value);
});
effect(() => {
  if (reducedMotion.value) document.documentElement.dataset.motion = "reduced";
  else delete document.documentElement.dataset.motion;
  keep("dp.motion", reducedMotion.value ? "reduced" : "full");
});

// Where the toolbar lives in this variant: the shell asks, the variant's tokens answer.
export const toolbarPlace = () => getComputedStyle(document.documentElement).getPropertyValue("--toolbar-place").trim() || "top";
