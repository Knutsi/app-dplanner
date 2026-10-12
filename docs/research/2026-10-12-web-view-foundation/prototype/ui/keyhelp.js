// Key help: the keycap view every surface uses, the which-key panel a prefix opens, and the
// "?" cheat sheet. Together with the modeline's echo they are how the keys teach themselves —
// nobody reads a manual; the next key is shown at the moment it is wanted.

import { DpElement } from "../engine/element.js";
import { html, nothing, repeat } from "../engine/template.js";
import { kbd, keycaps, keyText } from "./keys.js";
import { adopt, css } from "./style.js";

// ---------------------------------------------------------------- which-key

// Shown by the shell 400 ms after a prefix key: what each next key does from here. It never
// takes focus — the keys keep going to the router — and it waits; there is no timeout.
export class WhichKey extends DpElement {
  static shadow = false;
  static props = { prefix: { type: String, value: null }, items: { type: Object, value: [] } };

  render() {
    if (!this.prefix || !this.items.length) return nothing;
    const depth = this.prefix.split(" ").length;
    const entries = this.items.map((item) => {
      const rest = item.keys.split(" ").slice(depth);
      return { item, next: rest[0], deeper: rest.length > 1 };
    });
    return html`<div class="panel" role="dialog" aria-label=${`Keys after ${keyText(this.prefix)}`}>
      <header>${kbd(this.prefix)}<span class="dots">…</span><span class="hint">Esc cancels</span></header>
      <ul>
        ${entries.map(
          ({ item, next, deeper }) => html`<li aria-disabled=${item.disabled ? "true" : nothing} title=${item.reason ?? nothing}>
            <kbd class="next">${keycaps(next)[0].join("+")}${deeper ? html`<span class="more">…</span>` : nothing}</kbd><span class="label">${item.label}</span>
          </li>`,
        )}
      </ul>
    </div>`;
  }
}
WhichKey.define("dp-whichkey");

// ---------------------------------------------------------------- cheat sheet

export class CheatSheet extends DpElement {
  static shadow = false;
  static props = { sections: { type: Object, value: [] }, filter: { type: String, value: "" } };
  #back = null;

  get dialog() {
    return this.querySelector("dialog");
  }

  open() {
    this.#back = document.activeElement;
    this.filter = "";
    const input = this.querySelector("input");
    if (input) input.value = "";
    this.dialog.showModal();
    input?.focus();
  }

  close() {
    if (this.dialog.open) this.dialog.close();
  }

  #restore = () => {
    if (this.#back?.isConnected) this.#back.focus();
    this.#back = null;
  };

  #keydown = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      this.close();
    }
  };

  render() {
    const needle = this.filter.trim().toLowerCase();
    const matches = (item) => !needle || item.label.toLowerCase().includes(needle) || keyText(item.keys ?? "").toLowerCase().includes(needle);
    const sections = this.sections.map((s) => ({ ...s, items: s.items.filter((i) => i.keys && matches(i)) })).filter((s) => s.items.length);
    return html`<dialog aria-label="Keyboard shortcuts" @close=${this.#restore} @keydown=${this.#keydown}>
      <header>
        <input type="search" placeholder="Filter keys" aria-label="Filter keys" autocomplete="off" spellcheck="false"
          @input=${(e) => (this.filter = e.target.value)} />
        <span class="hint">${kbd("Escape")} closes</span>
      </header>
      <div class="sections">
        ${sections.length
          ? repeat(sections, (s) => s.title, (s) => html`<section>
              <h3>${s.title}</h3>
              <ul>${s.items.map((i) => html`<li aria-disabled=${i.disabled ? "true" : nothing}>${kbd(i.keys)}<span>${i.label}</span></li>`)}</ul>
            </section>`)
          : html`<p class="empty">No key matches “${this.filter}”</p>`}
      </div>
    </dialog>`;
  }
}
CheatSheet.define("dp-cheatsheet");

adopt(css`
  dp-whichkey .panel {
    position: fixed;
    left: 50%;
    bottom: calc(var(--menubar) + 10px);
    translate: -50% 0;
    z-index: 40;
    min-width: 280px;
    max-width: min(720px, 92vw);
    padding: var(--pad) calc(var(--pad) * 1.5);
    background: var(--bg-overlay);
    border-radius: var(--radius-pop);
    box-shadow: var(--shadow);
    animation: dp-whichkey-in var(--dur-micro) linear;
  }
  @keyframes dp-whichkey-in { from { opacity: 0; } }
  dp-whichkey header { display: flex; align-items: center; gap: 6px; padding-bottom: 6px; border-bottom: var(--rule); margin-bottom: 6px; }
  dp-whichkey .dots { color: var(--fg-3); }
  dp-whichkey .hint { margin-left: auto; color: var(--fg-3); font-size: var(--fs-small); }
  dp-whichkey ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 2px 18px; }
  dp-whichkey li { display: flex; align-items: center; gap: 10px; min-height: var(--row); }
  dp-whichkey li[aria-disabled="true"] { color: var(--fg-3); }
  dp-whichkey .next .more { color: var(--fg-3); font-weight: 400; }
  dp-whichkey .next {
    min-width: 1.7em;
    text-align: center;
    font: 700 calc(var(--fs) * 1.15) / 1.2 var(--font-mono);
    color: var(--accent);
  }

  dp-cheatsheet dialog {
    width: min(920px, 94vw);
    max-height: 78vh;
    margin: 11vh auto auto;
    padding: 0;
    color: var(--fg);
    background: var(--bg-overlay);
    border: none;
    border-radius: var(--radius-pop);
    box-shadow: var(--shadow);
    font: var(--fs) / var(--lh) var(--font-ui);
    overflow: hidden;
  }
  dp-cheatsheet dialog[open] { display: flex; flex-direction: column; }
  dp-cheatsheet dialog::backdrop { background: color-mix(in srgb, black 35%, transparent); }
  dp-cheatsheet header { display: flex; align-items: center; gap: var(--gap); padding: var(--pad) calc(var(--pad) * 1.5); border-bottom: var(--rule); }
  dp-cheatsheet input {
    flex: 1;
    height: var(--control);
    border: none;
    background: transparent;
    color: var(--fg);
    font: inherit;
    font-size: calc(var(--fs) * 1.1);
  }
  dp-cheatsheet input::placeholder { color: var(--fg-3); }
  dp-cheatsheet input:focus-visible { outline: none; }
  dp-cheatsheet .hint { color: var(--fg-3); font-size: var(--fs-small); display: flex; gap: 4px; align-items: center; }
  dp-cheatsheet .sections { overflow: auto; padding: calc(var(--pad) * 1.5); columns: 3 250px; column-gap: calc(var(--gap) * 3); }
  dp-cheatsheet section { break-inside: avoid; margin-bottom: calc(var(--gap) * 2); }
  dp-cheatsheet h3 {
    margin: 0 0 4px;
    font-size: var(--fs-small);
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--fg-3);
  }
  /* One grid per section, so a long binding widens its column instead of running into the label. */
  dp-cheatsheet ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: max-content 1fr; column-gap: calc(var(--gap) * 1.5); }
  dp-cheatsheet li { display: contents; }
  dp-cheatsheet li > * { display: flex; align-items: center; min-height: var(--row); }
  dp-cheatsheet li[aria-disabled="true"] > span:last-child { color: var(--fg-3); }
  dp-cheatsheet .empty { color: var(--fg-3); margin: 0; }
`);
