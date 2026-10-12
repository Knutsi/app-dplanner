// Toasts: for results that land somewhere you are not looking — a background job finished, a
// bulk change went through and can be undone. Never for what is already visible, never more
// than three, never stealing focus. A timer pauses while you hover or focus the stack, and
// while the window is in the background, so a toast is never missed because you looked away.

import { DpElement } from "../engine/element.js";
import { html, nothing, repeat } from "../engine/template.js";
import { glyph } from "./glyph.js";
import { kbd } from "./keys.js";
import { still } from "./motion.js";
import { adopt, css } from "./style.js";

const MAX = 3;
const TONE_GLYPH = { ok: "check", error: "problem", warn: "problem", busy: "refresh", info: "info" };

class Toasts extends DpElement {
  static shadow = false;
  static props = { items: { type: Object, value: [] } };
  #paused = new Set(); // why the timers are paused: "pointer", "focus", "window"

  connected() {
    this.setAttribute("role", "status");
    this.setAttribute("aria-live", "polite");
    this.addEventListener("pointerenter", () => this.#pause("pointer"));
    this.addEventListener("pointerleave", () => this.#resume("pointer"));
    this.addEventListener("focusin", () => this.#pause("focus"));
    this.addEventListener("focusout", () => this.#resume("focus"));
    window.addEventListener("blur", () => this.#pause("window"));
    window.addEventListener("focus", () => this.#resume("window"));
  }

  add(entry) {
    const items = [...this.items, entry];
    for (const old of items.slice(0, Math.max(0, items.length - MAX))) this.dismiss(old, false);
    this.items = items.filter((t) => !t.gone);
    if (!this.#paused.size) this.#start(entry);
  }

  #start(entry) {
    entry.startedAt = performance.now();
    entry.timer = setTimeout(() => this.dismiss(entry), entry.remaining);
  }

  #pause(why) {
    const was = this.#paused.size;
    this.#paused.add(why);
    if (was) return;
    for (const t of this.items) {
      clearTimeout(t.timer);
      t.remaining -= performance.now() - t.startedAt;
    }
  }

  #resume(why) {
    if (!this.#paused.delete(why) || this.#paused.size) return;
    for (const t of this.items) this.#start(t);
  }

  // Removing the toast that held focus fires no focusout, so the pause it caused is released
  // here — otherwise one clicked Undo would freeze every later toast on screen.
  updated() {
    if (this.#paused.has("focus") && !this.contains(document.activeElement)) this.#resume("focus");
  }

  dismiss(entry, fade = true) {
    if (entry.gone) return;
    entry.gone = true;
    clearTimeout(entry.timer);
    const el = this.querySelector(`[data-toast="${entry.id}"]`);
    const remove = () => (this.items = this.items.filter((t) => t !== entry));
    const duration = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--dur-micro")) || 0;
    if (fade && el && !still() && duration) el.animate([{ opacity: 1 }, { opacity: 0 }], { duration, easing: "linear" }).finished.then(remove);
    else remove();
  }

  render() {
    return repeat(
      this.items,
      (t) => t.id,
      (t) => html`<div class="toast" data-toast=${t.id} data-tone=${t.tone ?? "info"}>
        ${t.tone && t.tone !== "info" ? html`<span class="tone">${glyph(TONE_GLYPH[t.tone] ?? "info")}</span>` : nothing}
        <span class="message">${t.message}</span>
        ${t.undo
          ? html`<button type="button" class="undo" @click=${() => {
              this.dismiss(t);
              t.undo();
            }}>Undo</button>${kbd("Ctrl+Z")}`
          : nothing}
        <button type="button" class="close" aria-label="Dismiss" @click=${() => this.dismiss(t)}>${glyph("close")}</button>
      </div>`,
    );
  }
}
Toasts.define("dp-toasts");

let ids = 0;

// Shows a toast; returns { dismiss }. `undo` adds an Undo button that dismisses and calls it.
export function toast(message, { undo = null, tone = "info", duration = 6000 } = {}) {
  let stack = document.querySelector("dp-toasts");
  if (!stack) stack = document.body.appendChild(document.createElement("dp-toasts"));
  const entry = { id: ++ids, message, undo, tone, remaining: duration, timer: 0, startedAt: 0, gone: false };
  stack.add(entry);
  return { dismiss: () => stack.dismiss(entry) };
}

adopt(css`
  dp-toasts {
    position: fixed;
    left: 12px;
    bottom: calc(var(--menubar) + 12px + env(safe-area-inset-bottom, 0px));
    z-index: 60;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: min(440px, calc(100vw - 24px));
  }
  dp-toasts .toast {
    display: flex;
    align-items: center;
    gap: var(--gap);
    min-height: calc(var(--control) + 10px);
    padding: 4px 4px 4px calc(var(--pad) * 1.5);
    background: var(--bg-overlay);
    color: var(--fg);
    border-radius: var(--radius-pop);
    box-shadow: var(--shadow);
    animation: dp-toast-in var(--dur-small) var(--ease-enter);
  }
  @keyframes dp-toast-in { from { opacity: 0; translate: 0 6px; } }
  dp-toasts .tone { display: flex; }
  dp-toasts [data-tone="ok"] .tone { color: var(--tone-ok); }
  dp-toasts [data-tone="error"] .tone { color: var(--tone-error); }
  dp-toasts [data-tone="warn"] .tone { color: var(--tone-warn); }
  dp-toasts [data-tone="busy"] .tone { color: var(--tone-busy); }
  dp-toasts .message { flex: 1; min-width: 0; }
  dp-toasts button {
    display: inline-flex;
    align-items: center;
    height: var(--control);
    border: none;
    border-radius: var(--radius);
    background: transparent;
    color: var(--fg-2);
    font: inherit;
  }
  dp-toasts .undo { padding: 0 8px; color: var(--accent); font-weight: 600; }
  dp-toasts .undo:hover, dp-toasts .close:hover { background: var(--bg-hover); }
  dp-toasts .close { width: var(--control); justify-content: center; --icon: 14px; }
  dp-toasts .kbd { margin-left: -4px; }
`);
