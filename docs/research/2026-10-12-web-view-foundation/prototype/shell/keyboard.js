// The keyboard router: Vim's speed without Vim's trap.
//
// "Normal mode" is not a mode you enter — it is where you are whenever focus is on a navigable
// surface (anything marked data-nav: the step table, a list) and not in a text field. There,
// bare keys and sequences act ("r" renames, "g p" goes to projects). Focus a field and you are
// typing (EDIT), with nothing to remember: the keys are letters again. The modeline always
// says which, and always names the way out. Escape steps exactly one level outward — pending
// prefix, transient mode, selection, field — and never loses work.
//
// Chords (Ctrl+K, F2) work everywhere except the few a text field owns while you type in it.
// Overlays (menus, palette, sheets) handle their own keys first and preventDefault; the router
// only sees what they leave.

import { signal, computed } from "../engine/signals.js";
import { chordOf, isChord, isEditable } from "../ui/keys.js";
import { context } from "./context.js";
import { clearSelection } from "./workspace.js";

const FIELD_CHORDS = new Set(["Ctrl+A", "Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Ctrl+Y", "Ctrl+Shift+Z", "Ctrl+ArrowLeft", "Ctrl+ArrowRight", "Ctrl+Backspace", "Ctrl+Delete", "Home", "End", "Delete", "Backspace"]);
const WHICH_KEY_MS = 400;
const SHOW_KEYS_MS = 600;
const ECHO_MS = 2200;

export const singleKeys = signal(true); // WCAG 2.1.4: a person can turn bare-key verbs off
export const pending = signal(null); // a sequence prefix being typed: "g"
export const whichKeyOpen = signal(false);
export const transient = signal(null); // { label, exits, onKey(chord) → handled }
export const echo = signal(null); // { keys, label, refused } — the modeline's last word
const focusKind = signal("none"); // nav | edit | none

export const mode = computed(() => {
  if (transient.value) return { name: transient.value.label, exits: transient.value.exits, tone: "transient" };
  if (pending.value) return { name: `${pending.value}…`, exits: "Esc cancels", tone: "pending" };
  if (focusKind.value === "edit") return { name: "EDIT", exits: "Esc leaves the field", tone: "edit" };
  if (focusKind.value === "nav" && singleKeys.value) return { name: "NAV", exits: null, tone: "nav" };
  return { name: "—", exits: null, tone: "none" };
});

let echoTimer = 0;
export function say(entry) {
  clearTimeout(echoTimer);
  echo.value = entry;
  echoTimer = setTimeout(() => (echo.value = null), entry.refused ? ECHO_MS * 1.5 : ECHO_MS);
}

export function enterTransient(state) {
  transient.value = state;
}
export function exitTransient() {
  transient.peek()?.onExit?.();
  transient.value = null;
}

export function installKeyboard(commands) {
  let whichTimer = 0;
  let showTimer = 0;
  let lastSurface = null;

  const bindings = () => {
    const map = new Map();
    for (const spec of commands.all()) for (const key of spec.keys) map.set(key, spec);
    return map;
  };
  const prefixes = (map, prefix) => [...map.keys()].some((k) => k.startsWith(`${prefix} `));

  const setPending = (value) => {
    clearTimeout(whichTimer);
    pending.value = value;
    whichKeyOpen.value = false;
    if (value) whichTimer = setTimeout(() => (whichKeyOpen.value = true), WHICH_KEY_MS);
  };

  const run = (spec, keys) => {
    const result = commands.run(spec.id, context.peek(), "key");
    if (!result.ran) say({ keys, label: spec.label, refused: result.reason });
  };

  // Escape, one level at a time.
  const escape = () => {
    if (pending.peek()) return setPending(null), true;
    if (transient.peek()) return exitTransient(), true;
    if (isEditable(document.activeElement)) {
      (lastSurface?.isConnected ? lastSurface : document.querySelector("[data-nav]"))?.focus();
      return true;
    }
    if (context.peek().selection.length) return clearSelection(), true;
    return false;
  };

  document.addEventListener("focusin", (e) => {
    const target = e.composedPath()[0];
    if (isEditable(target)) focusKind.value = "edit";
    else if (target.closest?.("[data-nav]")) {
      focusKind.value = "nav";
      lastSurface = target.closest("[data-nav]");
    } else focusKind.value = "none";
  });

  window.addEventListener("keydown", (e) => {
    // Hold Ctrl (⌘) alone and the chords appear on the controls that have them.
    clearTimeout(showTimer);
    if (e.key === "Control" || e.key === "Meta") showTimer = setTimeout(() => (document.documentElement.dataset.showkeys = ""), SHOW_KEYS_MS);
    else delete document.documentElement.dataset.showkeys;

    if (e.defaultPrevented || e.isComposing) return;
    const chord = chordOf(e);
    if (!chord) return;
    const editing = isEditable(e.composedPath()[0]);
    const onSurface = !editing && !!e.composedPath()[0].closest?.("[data-nav]");

    if (transient.peek() && chord !== "Escape" && transient.peek().onKey?.(chord)) return e.preventDefault();
    if (chord === "Escape") {
      if (escape()) e.preventDefault();
      return;
    }

    const map = bindings();
    if (pending.peek()) {
      e.preventDefault();
      const sequence = `${pending.peek()} ${chord}`;
      if (map.has(sequence)) {
        setPending(null);
        return run(map.get(sequence), sequence);
      }
      if (prefixes(map, sequence)) return setPending(sequence);
      setPending(null);
      return say({ keys: sequence, label: null, refused: `${sequence} does nothing here — ? lists the keys` });
    }

    const bare = !isChord(chord) && !/^F\d+$/.test(chord) && chord !== "Delete";
    if (bare && (!onSurface || !singleKeys.peek())) return;
    if (!bare && editing && FIELD_CHORDS.has(chord)) return;
    if (map.has(chord)) {
      e.preventDefault();
      return run(map.get(chord), chord);
    }
    if (bare && prefixes(map, chord)) {
      e.preventDefault();
      setPending(chord);
    }
  });

  window.addEventListener("keyup", () => {
    clearTimeout(showTimer);
    delete document.documentElement.dataset.showkeys;
  });
  window.addEventListener("blur", () => delete document.documentElement.dataset.showkeys);

  // The echo: whatever ran, however it ran, the modeline shows its name and its key. A
  // keyboard user gets confirmation; a mouse user learns the key without being lectured.
  commands.onRun(({ spec, state, source }) => say({ keys: spec.keys[0] ?? null, label: state.label, source }));
}
