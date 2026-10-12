// Key notation. A binding is written once, canonically — "Ctrl+K", "Shift+Alt+ArrowUp", a bare
// "x", or a sequence "g p" — and shown in the platform's own spelling wherever it appears:
// menus, tooltips, the palette, the which-key panel, the cheat sheet and the modeline echo.

import { html, nothing } from "../engine/template.js";

export const MAC = /Mac|iPhone|iPad/.test(navigator.platform ?? navigator.userAgent);

const MODIFIERS = ["Ctrl", "Alt", "Shift", "Meta"];
const NAMES = { " ": "Space", Esc: "Escape", Del: "Delete", Up: "ArrowUp", Down: "ArrowDown", Left: "ArrowLeft", Right: "ArrowRight" };

// A KeyboardEvent as a canonical chord. Printable keys with no Ctrl/Alt/Meta keep their case
// and drop Shift ("X", "?"), so a Shift+x binding is written "X" — what the keycap shows.
export function chordOf(event) {
  let key = NAMES[event.key] ?? event.key;
  if (["Control", "Alt", "Shift", "Meta", "AltGraph"].includes(key)) return null;
  const command = event.ctrlKey || event.altKey || event.metaKey;
  const printable = key.length === 1;
  if (printable && command) key = key.toUpperCase();
  const mods = [];
  // ⌘ is the command key on a Mac, and the bindings say Ctrl: one table serves both.
  if (event.ctrlKey || (MAC && event.metaKey)) mods.push("Ctrl");
  if (event.altKey) mods.push("Alt");
  if (event.shiftKey && (!printable || command)) mods.push("Shift");
  if (event.metaKey && !MAC) mods.push("Meta");
  return [...mods, key].join("+");
}

export const isChord = (binding) => MODIFIERS.some((m) => binding.startsWith(`${m}+`));

const GLYPH = { ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→", Enter: "↵", Escape: "Esc", Backspace: "⌫", Delete: "Del", Space: "Space", Tab: "Tab" };
const MAC_MOD = { Ctrl: "⌘", Alt: "⌥", Shift: "⇧", Meta: "⌃" };

// "Ctrl+Shift+P" → ["Ctrl", "Shift", "P"] (or ["⌘", "⇧", "P"]); a sequence → one list per step.
// A bare letter keeps its case, as Vim writes it: "x" is x, "X" is shown ⇧X.
function cap(part, bare) {
  if (MAC && MAC_MOD[part]) return MAC_MOD[part];
  if (GLYPH[part]) return GLYPH[part];
  if (bare && /^[A-Z]$/.test(part)) return `⇧${part}`;
  return part;
}

export function keycaps(binding) {
  return binding.split(" ").map((step) => {
    const parts = step.split(/\+(?!$)/);
    return parts.map((part) => cap(part, parts.length === 1));
  });
}

// Plain text, for tooltips and aria-keyshortcuts: "Ctrl+K", "G then P".
export function keyText(binding) {
  return keycaps(binding)
    .map((caps) => caps.join(MAC ? "" : "+"))
    .join(" then ");
}

export const isEditable = (el) =>
  !!el && (el.isContentEditable || (el.tagName === "INPUT" && !["checkbox", "radio", "button", "range"].includes(el.type)) || el.tagName === "TEXTAREA" || el.tagName === "SELECT");

// The one way a key is drawn: a cap per key ("Ctrl" "K", or "g" then "p"), or — in a menu row,
// where caps would be noise — the plain words, right-aligned like a native menu's shortcuts.
export function kbd(binding, { plain = false } = {}) {
  if (!binding) return nothing;
  if (plain) return html`<span class="kbd plain" aria-hidden="true">${keyText(binding)}</span>`;
  return html`<span class="kbd" aria-label=${keyText(binding)}>${keycaps(binding).map(
    (step, i) => html`${i ? html`<span class="then">then</span>` : nothing}${step.map((c) => html`<kbd>${c}</kbd>`)}`,
  )}</span>`;
}
