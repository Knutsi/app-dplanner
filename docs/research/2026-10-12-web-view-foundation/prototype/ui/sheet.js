// Touch: the bottom sheet is the context menu's touch form, and the action bar is the
// toolbar's. Same groups, same items as the desktop surfaces — only the shape changes, so the
// touch UI never grows a verb the desktop lacks. Rows are 44 px; the sheet slides up because
// that says where it lives, and a swipe down puts it back.

import { DpElement } from "../engine/element.js";
import { html, nothing } from "../engine/template.js";
import { glyph } from "./glyph.js";
import { still } from "./motion.js";
import { adopt, css } from "./style.js";

const DISMISS_PX = 60;
const DISMISS_SPEED = 0.5; // px per ms
const token = (name) => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
const easing = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "ease";

export class Sheet extends DpElement {
  static shadow = false;
  static props = { groups: { type: Object, value: [] }, heading: { type: String, value: null } };
  #drag = null;
  #draggedAt = 0; // a drag that ends over a row is not a tap on it

  get dialog() {
    return this.querySelector("dialog");
  }

  open(groups, { title = null } = {}) {
    this.groups = groups;
    this.heading = title;
    this.dialog.showModal();
    if (!still()) this.dialog.animate([{ translate: "0 100%" }, { translate: "0 0" }], { duration: token("--dur-layout"), easing: easing("--ease-enter") });
  }

  close(from = 0) {
    if (!this.dialog.open) return;
    const time = token("--dur-layout") * (2 / 3);
    if (still() || !time) return this.dialog.close();
    this.dialog
      .animate([{ translate: `0 ${from}px` }, { translate: "0 100%" }], { duration: time, easing: easing("--ease-exit"), fill: "forwards" })
      .finished.then((a) => {
        this.dialog.close();
        a.cancel();
      });
  }

  #activate(item) {
    if (item.disabled || performance.now() - this.#draggedAt < 80) return;
    this.close(); // the verb runs at once; the sheet leaves behind it
    item.run();
  }

  // Swipe down from the grabber or header, or anywhere once the list is scrolled to the top.
  #down = (e) => {
    const body = this.querySelector(".body");
    if (!e.target.closest(".top") && body.scrollTop > 0) return;
    this.#drag = { y: e.clientY, t: performance.now(), dy: 0, id: e.pointerId };
  };
  #move = (e) => {
    if (!this.#drag || e.pointerId !== this.#drag.id) return;
    this.#drag.dy = Math.max(0, e.clientY - this.#drag.y);
    if (this.#drag.dy > 4) this.dialog.style.translate = `0 ${this.#drag.dy}px`;
  };
  #up = () => {
    const drag = this.#drag;
    this.#drag = null;
    if (!drag || drag.dy <= 4) return;
    this.#draggedAt = performance.now();
    const speed = drag.dy / (performance.now() - drag.t);
    this.dialog.style.translate = "";
    if (drag.dy > DISMISS_PX || speed > DISMISS_SPEED) this.close(drag.dy);
    else if (!still()) this.dialog.animate([{ translate: `0 ${drag.dy}px` }, { translate: "0 0" }], { duration: token("--dur-small"), easing: easing("--ease-move") });
  };

  render() {
    return html`<dialog aria-label=${this.heading ?? "Actions"}
      @click=${(e) => e.target === this.dialog && this.close()}
      @keydown=${(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          this.close();
        }
      }}
      @pointerdown=${this.#down} @pointermove=${this.#move} @pointerup=${this.#up} @pointercancel=${this.#up}>
      <div class="frame" tabindex="-1" autofocus>
        <div class="top"><span class="grabber" aria-hidden="true"></span>${this.heading ? html`<h2>${this.heading}</h2>` : nothing}</div>
        <div class="body">
          ${this.groups.map(
            (group) => html`<div class="group" role="menu">${group.map(
              (item) => html`<button type="button" role="menuitem" class="row" aria-disabled=${item.disabled ? "true" : nothing}
                @click=${() => this.#activate(item)}>
                <span class="icon">${item.icon ? glyph(item.icon) : nothing}</span>
                <span class="label">${item.label}${item.disabled && item.reason ? html`<small>${item.reason}</small>` : nothing}</span>
              </button>`,
            )}</div>`,
          )}
        </div>
        <button type="button" class="cancel" @click=${() => this.close()}>Cancel</button>
      </div>
    </dialog>`;
  }
}
Sheet.define("dp-sheet");

// The toolbar's touch form: up to five verbs; past that, four and a More that opens a sheet.
export class ActionBar extends DpElement {
  static shadow = false;
  static props = { items: { type: Object, value: [] } };

  // Overflow and submenus both become a sheet: the touch form of a menu.
  #sheet(groups, title) {
    let sheet = document.querySelector("dp-sheet");
    if (!sheet) sheet = document.body.appendChild(document.createElement("dp-sheet"));
    sheet.open(groups, { title });
  }

  #activate(item) {
    if (item.disabled) return;
    if (item.submenu) this.#sheet(item.submenu, item.label);
    else item.run();
  }

  render() {
    const items = this.items.length > 5 ? [...this.items.slice(0, 4), { id: "more", label: "More", icon: "options", submenu: [this.items.slice(4)] }] : this.items;
    return html`<nav class="bar" aria-label="Actions" style=${`--count: ${items.length}`}>${items.map(
      (item) => html`<button type="button" aria-disabled=${item.disabled ? "true" : nothing} title=${item.reason ?? nothing}
        @click=${() => this.#activate(item)}>
        ${item.icon ? glyph(item.icon) : nothing}<span>${item.label}</span>
      </button>`,
    )}</nav>`;
  }
}
ActionBar.define("dp-actionbar");

adopt(css`
  dp-sheet dialog {
    width: 100%;
    max-width: 640px;
    max-height: 86vh;
    margin: auto auto 0;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--fg);
    font: var(--fs) / var(--lh) var(--font-ui);
    overflow: visible;
    touch-action: none;
  }
  dp-sheet dialog::backdrop { background: color-mix(in srgb, black 40%, transparent); }
  dp-sheet .frame:focus { outline: none; } /* opened by touch: focus lands on the frame, not a row */
  dp-sheet .frame {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 86vh;
    padding: 0 8px calc(8px + env(safe-area-inset-bottom, 0px));
  }
  dp-sheet .top, dp-sheet .body {
    background: var(--bg-overlay);
    border-radius: calc(var(--radius-pop) + 4px);
  }
  dp-sheet .top {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 6px 12px 4px;
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
    margin-bottom: -8px;
  }
  dp-sheet .grabber { width: 36px; height: 5px; border-radius: 3px; background: var(--line-strong); margin-bottom: 6px; }
  dp-sheet h2 { margin: 0 0 4px; font-size: var(--fs-small); font-weight: 600; color: var(--fg-3); letter-spacing: 0.04em; text-transform: uppercase; }
  dp-sheet .body { overflow: auto; overscroll-behavior: contain; border-top-left-radius: 0; border-top-right-radius: 0; touch-action: pan-y; }
  dp-sheet .group + .group { border-top: 6px solid var(--bg-sunken); }
  dp-sheet .row, dp-sheet .cancel {
    display: flex;
    align-items: center;
    gap: 14px;
    width: 100%;
    min-height: 44px;
    padding: 0 16px;
    border: none;
    background: transparent;
    color: var(--fg);
    font: inherit;
    font-size: calc(var(--fs) * 1.1);
    text-align: left;
    --icon: 20px;
  }
  dp-sheet .row + .row { border-top: var(--rule); }
  dp-sheet .row:active { background: var(--bg-hover); }
  dp-sheet .row .icon { display: flex; color: var(--fg-2); width: 20px; }
  dp-sheet .row .label { display: flex; flex-direction: column; }
  dp-sheet .row small { color: var(--fg-3); font-size: var(--fs-small); }
  dp-sheet .row[aria-disabled="true"] { color: var(--fg-3); }
  dp-sheet .cancel { justify-content: center; font-weight: 600; color: var(--accent); flex: none; background: var(--bg-overlay); border-radius: calc(var(--radius-pop) + 4px); }

  dp-actionbar .bar {
    display: grid;
    grid-template-columns: repeat(var(--count), 1fr);
    padding-bottom: env(safe-area-inset-bottom, 0px);
    background: var(--bg-raised);
    border-top: var(--rule);
  }
  dp-actionbar button {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    min-height: 56px;
    border: none;
    background: transparent;
    color: var(--fg-2);
    font: inherit;
    font-size: var(--fs-small);
    --icon: 22px;
  }
  dp-actionbar button:active { background: var(--bg-hover); color: var(--fg); }
  dp-actionbar button[aria-disabled="true"] { color: var(--fg-3); }
`);
