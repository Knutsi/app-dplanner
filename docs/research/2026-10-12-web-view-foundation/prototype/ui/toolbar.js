// The toolbar, and the selection bar that takes its place.
//
// A toolbar is bands of glyph verbs; each verb's words live in its tooltip with its key, and a
// band that does not fit folds whole into "⋯ More" — the strip never wraps or scrolls, so
// nothing moves under a hand that knows where it is. When the person selects things, the same
// slot at the same height becomes the selection bar: × to clear, how many are selected, and
// what can be done to all of them, labelled because bulk verbs are rarer than everyday ones.
// The swap is a crossfade with no movement, and instant when the keyboard caused it.

import { DpElement } from "../engine/element.js";
import { html, nothing } from "../engine/template.js";
import { glyph } from "./glyph.js";
import { isChord, keyText } from "./keys.js";
import { swap } from "./motion.js";
import { adopt, css } from "./style.js";
import "./menu.js";

export class DpToolbar extends DpElement {
  static shadow = false;
  static props = {
    bands: { type: Object, value: [] },
    selection: { type: Object, value: null }, // { count, noun, items, clear } | null
    placement: { type: String, value: "top", reflect: true }, // top | float | inline
    label: { type: String, value: "Tools" },
  };

  via = "pointer"; // set by the caller before `selection` when the keyboard caused the change
  #fold = 0; // how many units, from the end, live in the More menu
  #current = null; // the id of the button that holds the toolbar's one Tab stop
  #mode = null;
  #focusInside = false;
  #more = null;
  #resize = null;

  connected() {
    if (this.#resize) return;
    this.#more = document.createElement("dp-menu");
    this.#resize = new ResizeObserver(() => this.#measure());
    this.#resize.observe(this);
    this.addEventListener("focusin", (e) => {
      this.#focusInside = true;
      const id = e.target.closest?.("[data-roving]")?.dataset.id;
      if (id) this.#current = id;
      this.#syncTabStops();
    });
    this.addEventListener("focusout", (e) => {
      if (e.relatedTarget && !this.contains(e.relatedTarget)) this.#focusInside = false;
    });
  }

  render() {
    const selection = this.selection?.count > 0 ? this.selection : null;
    const live = selection ? `${selection.count} ${noun(selection)} selected` : "";
    return html`<div class="strip" role="toolbar" aria-label=${selection ? "Selection" : this.label} ?data-selection=${!!selection} @keydown=${this.#onKey}>
        ${selection ? this.#selectionBar(selection) : this.bands.map((band) => this.#band(band))}
        <button class="tb more" type="button" data-roving data-id="more" hidden aria-label="More" data-tip="More" aria-haspopup="menu" @click=${this.#openMore}>
          ${glyph("options")}
        </button>
      </div>
      <span class="visually-hidden" aria-live="polite">${live}</span>`;
  }

  #band(band) {
    return html`<div class="band" data-unit role="group" aria-label=${band.name}>${band.items.map((item) => this.#button(item, false))}</div>`;
  }

  #selectionBar(selection) {
    return html`<button class="tb clear" type="button" data-roving data-id="clear" data-fixed aria-label="Clear selection" data-tip="Clear selection" data-tip-keys="Escape" @click=${() => selection.clear()}>
        ${glyph("close")}
      </button>
      <span class="count" data-fixed><b class="n">${selection.count}</b> ${noun(selection)} selected</span>
      <span class="divider" data-fixed></span>
      ${selection.items.map((item) => html`<span class="unit" data-unit>${this.#button(item, true)}</span>`)}`;
  }

  #button(item, labelled) {
    const tip = item.disabled && item.reason ? `${item.label} — ${item.reason}` : item.label;
    const keys = item.keys ?? null;
    return html`<button
      class=${labelled ? "tb labelled" : "tb"}
      type="button"
      data-roving
      data-id=${item.id}
      aria-label=${item.label}
      aria-pressed=${item.checked == null ? nothing : String(Boolean(item.checked))}
      aria-disabled=${item.disabled ? "true" : nothing}
      aria-haspopup=${item.submenu ? "menu" : nothing}
      data-tip=${labelled && !keys && !item.disabled ? nothing : tip}
      data-tip-keys=${keys ?? nothing}
      data-chord=${keys && isChord(keys) ? keyText(keys) : nothing}
      @click=${(e) => this.#activate(item, e.currentTarget, e.detail === 0 ? "key" : "pointer")}
    >${item.icon ? glyph(item.icon) : nothing}${labelled ? html`<span>${item.label}</span>` : nothing}</button>`;
  }

  #activate(item, button, via = "pointer") {
    if (item.disabled) return;
    if (item.submenu) {
      this.#more.groups = item.submenu;
      this.#more.open({ anchor: button, side: "below" }, { via, returnTo: button });
      return;
    }
    item.run?.();
  }

  #openMore(e) {
    const fold = this.#fold;
    const selection = this.selection?.count > 0 ? this.selection : null;
    const groups = selection
      ? [selection.items.slice(selection.items.length - fold)]
      : this.bands.slice(this.bands.length - fold).map((band) => band.items);
    this.#more.groups = groups;
    this.#more.open({ anchor: e.currentTarget, side: "below" }, { via: e.detail === 0 ? "key" : "pointer", returnTo: e.currentTarget });
  }

  updated() {
    const mode = this.selection?.count > 0 ? "selection" : "bands";
    if (this.#mode && mode !== this.#mode) {
      swap(this.querySelector(".strip"), { via: this.via });
      // The bar never takes focus, but it must not strand it: if the button that had focus is
      // gone, focus goes to the surface the selection was made on.
      if (this.#focusInside && !this.contains(document.activeElement)) {
        this.#focusInside = false;
        this.closest("[data-pane]")?.querySelector("[data-nav]")?.focus();
      }
    }
    this.#mode = mode;
    this.via = "pointer";
    this.#measure();
  }

  // Fold whole units from the end until the rest fits beside the More button. Measured with
  // everything shown, then hidden imperatively, so a fold costs no extra render.
  #measure() {
    const strip = this.querySelector(".strip");
    if (!strip) return;
    const units = [...strip.querySelectorAll("[data-unit]")];
    const more = strip.querySelector(".more");
    for (const unit of units) unit.hidden = false;
    more.hidden = false;
    const style = getComputedStyle(strip);
    const gap = parseFloat(style.columnGap) || 0;
    const fixed = [...strip.querySelectorAll("[data-fixed]")].reduce((w, el) => w + el.getBoundingClientRect().width + gap, 0);
    const room = strip.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - fixed;
    const widths = units.map((unit) => unit.getBoundingClientRect().width + gap);
    let total = widths.reduce((a, b) => a + b, 0);
    let fold = 0;
    if (this.placement !== "float" && total > room + 0.5) {
      total += more.getBoundingClientRect().width;
      while (fold < units.length && total > room + 0.5) total -= widths[units.length - 1 - fold++];
    }
    units.forEach((unit, i) => (unit.hidden = i >= units.length - fold));
    more.hidden = fold === 0;
    this.#fold = fold;
    this.#syncTabStops();
  }

  #reachable() {
    return [...this.querySelectorAll(".strip [data-roving]")].filter((b) => !b.hidden && !b.closest("[hidden]"));
  }

  #syncTabStops() {
    const buttons = this.#reachable();
    const holder = buttons.find((b) => b.dataset.id === this.#current) ?? buttons[0];
    for (const b of this.querySelectorAll(".strip [data-roving]")) b.tabIndex = b === holder ? 0 : -1;
  }

  #onKey(e) {
    const buttons = this.#reachable();
    const i = buttons.indexOf(e.target.closest?.("[data-roving]"));
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: buttons.length - 1 }[e.key];
    if (to === undefined || i < 0) return;
    e.preventDefault();
    e.stopPropagation();
    buttons[Math.max(0, Math.min(to, buttons.length - 1))].focus();
  }
}

const noun = ({ count, noun }) => (count === 1 ? noun : `${noun}s`);

DpToolbar.define("dp-toolbar");

adopt(css`
  dp-toolbar {
    display: block;
    min-width: 0;
  }
  dp-toolbar .strip {
    display: flex;
    align-items: center;
    gap: calc(var(--gap) / 4);
    height: calc(var(--control) + var(--pad));
    padding: 0 calc(var(--pad) / 2);
    overflow: hidden;
    white-space: nowrap;
    background: var(--bg);
    border-bottom: var(--rule);
  }
  dp-toolbar .band {
    display: flex;
    align-items: center;
    gap: calc(var(--gap) / 4);
  }
  dp-toolbar .band + .band::before,
  dp-toolbar .divider {
    content: "";
    align-self: stretch;
    margin: calc(var(--pad) / 2) calc(var(--gap) / 2);
    border-left: var(--rule);
  }
  dp-toolbar .tb {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: calc(var(--gap) * 0.75);
    flex: none;
    height: var(--control);
    min-width: var(--control);
    padding: 0;
    border: 0;
    border-radius: var(--radius);
    background: transparent;
    color: var(--fg-2);
    font: inherit;
    cursor: default;
    transition: background-color var(--dur-micro) linear, color var(--dur-micro) linear;
  }
  dp-toolbar .tb:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }
  dp-toolbar .tb[aria-pressed="true"] {
    background: var(--accent-wash);
    color: var(--accent);
  }
  dp-toolbar .tb[aria-disabled="true"],
  dp-toolbar .tb[aria-disabled="true"]:hover {
    background: transparent;
    color: var(--fg-3);
  }
  dp-toolbar .tb.labelled {
    padding: 0 var(--pad);
    color: var(--fg);
    text-transform: var(--label-case);
  }
  dp-toolbar .tb.labelled .glyph {
    color: var(--fg-2);
  }
  dp-toolbar .more {
    margin-inline-start: auto;
  }
  dp-toolbar .strip[data-selection] {
    background-image: linear-gradient(var(--accent-wash), var(--accent-wash));
  }
  dp-toolbar .count {
    padding: 0 var(--pad) 0 calc(var(--pad) / 2);
    color: var(--fg);
    text-transform: var(--label-case);
  }
  dp-toolbar .count .n {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }
  dp-toolbar .unit {
    display: flex;
  }

  dp-toolbar[placement="float"] {
    display: inline-block;
  }
  dp-toolbar[placement="float"] .strip {
    display: inline-flex;
    padding: 0 calc(var(--pad) / 2);
    border: 0;
    border-radius: var(--radius-pop);
    background-color: var(--bg-overlay);
    box-shadow: var(--shadow);
  }
  dp-toolbar[placement="inline"] .strip {
    height: auto;
    padding: 0;
    border: 0;
    background-color: transparent;
  }
`);
