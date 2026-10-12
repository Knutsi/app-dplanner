// The command palette: every verb by name, each row teaching its key. It opens scoped to what
// is selected (a chip before the query); Backspace on an empty query drops the chip and widens
// to everything. It opens and closes without animation — it is used too often to wait for.

import { DpElement } from "../engine/element.js";
import { html, nothing, repeat } from "../engine/template.js";
import { glyph } from "./glyph.js";
import { kbd } from "./keys.js";
import { adopt, css } from "./style.js";

const BOUNDARY = /[\s\-_/▸.:,()…]/;

// A small fuzzy scorer: every query character must appear in order; word starts and runs of
// consecutive characters score high, gaps cost a little. Returns null for no match.
export function fuzzy(query, text) {
  const q = query.toLowerCase().replace(/\s+/g, "");
  if (!q) return { score: 0, positions: [] };
  const t = text.toLowerCase();
  const isStart = (i) => i === 0 || BOUNDARY.test(text[i - 1]) || (/[A-Z]/.test(text[i]) && /[a-z]/.test(text[i - 1]));

  const attempt = (preferStarts) => {
    const positions = [];
    let from = 0;
    for (const ch of q) {
      let found = -1;
      if (preferStarts) {
        for (let i = from; i < t.length; i++) {
          if (t[i] === ch && (isStart(i) || i === positions.at(-1) + 1)) {
            found = i;
            break;
          }
        }
      }
      if (found < 0) found = t.indexOf(ch, from);
      if (found < 0) return null;
      positions.push(found);
      from = found + 1;
    }
    return positions;
  };

  const score = (positions) =>
    positions.reduce((sum, p, i) => {
      let s = sum + 1;
      if (isStart(p)) s += 8;
      if (i && p === positions[i - 1] + 1) s += 5;
      if (i) s -= Math.min(p - positions[i - 1] - 1, 10) * 0.2;
      return s;
    }, positions[0] === 0 ? 10 : 0);

  let best = null;
  for (const positions of [attempt(true), attempt(false)]) {
    if (!positions) continue;
    const s = score(positions);
    if (!best || s > best.score) best = { score: s, positions };
  }
  return best;
}

// Text with the matched characters wrapped in <mark>, run by run.
function marked(text, positions, offset) {
  const out = [];
  let run = "";
  let inMark = false;
  for (let i = 0; i < text.length; i++) {
    const hit = positions.has(i + offset);
    if (hit !== inMark && run) {
      out.push(inMark ? html`<mark>${run}</mark>` : run);
      run = "";
    }
    inMark = hit;
    run += text[i];
  }
  if (run) out.push(inMark ? html`<mark>${run}</mark>` : run);
  return out;
}

let counter = 0;

export class Palette extends DpElement {
  static shadow = false;
  static props = {
    items: { type: Object, value: [] },
    scope: { type: Object, value: null },
    query: { type: String, value: "" },
    active: { type: Number, value: 0 },
    placeholder: { type: String, value: "Type a command" },
  };
  #id = `dp-palette-${++counter}`;
  #back = null;
  #onWiden = null;

  get dialog() {
    return this.querySelector("dialog");
  }

  get input() {
    return this.querySelector("input");
  }

  open({ items, scope = null, placeholder = "Type a command", onWiden = null }) {
    this.#back = document.activeElement;
    this.#onWiden = onWiden;
    this.items = items;
    this.scope = scope;
    this.placeholder = placeholder;
    this.query = "";
    this.active = 0;
    this.input.value = "";
    if (!this.dialog.open) this.dialog.showModal();
    this.input.focus();
  }

  close() {
    if (this.dialog.open) this.dialog.close();
  }

  // The items as shown: in given order with no query, else by score, ties by given order.
  get matches() {
    const query = this.query.trim();
    if (!query) return this.items.map((item) => ({ item, positions: new Set() }));
    const found = [];
    this.items.forEach((item, index) => {
      const m = fuzzy(query, `${item.label} ${item.detail ?? ""}`);
      if (m) found.push({ item, index, score: m.score, positions: new Set(m.positions) });
    });
    return found.sort((a, b) => b.score - a.score || a.index - b.index);
  }

  #run(entry) {
    if (!entry || entry.item.disabled) return;
    this.close(); // focus goes back first, so the verb acts where the person was
    entry.item.run();
  }

  #keydown(e) {
    const matches = this.matches;
    const move = (delta) => {
      e.preventDefault();
      if (matches.length) this.active = (this.active + delta + matches.length) % matches.length;
    };
    if (e.key === "ArrowDown" || (e.ctrlKey && e.key === "n")) move(1);
    else if (e.key === "ArrowUp" || (e.ctrlKey && e.key === "p")) move(-1);
    else if (e.key === "Enter") {
      e.preventDefault();
      this.#run(matches[this.active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      this.close();
    } else if (e.key === "Backspace" && !this.input.value && this.scope) {
      e.preventDefault();
      this.scope = null;
      const wider = this.#onWiden?.();
      if (wider) this.items = wider;
      this.active = 0;
    }
  }

  updated() {
    this.querySelector('[role="option"][aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }

  render() {
    const matches = this.matches;
    const active = Math.min(this.active, Math.max(matches.length - 1, 0));
    const optionId = (i) => `${this.#id}-${i}`;
    return html`<dialog aria-label="Command palette" @close=${() => this.#back?.isConnected && this.#back.focus()}>
      <div class="query">
        ${glyph("find")}
        ${this.scope ? html`<span class="scope" title="Backspace widens to every command">${this.scope}</span>` : nothing}
        <input type="text" role="combobox" aria-expanded="true" aria-controls=${`${this.#id}-list`}
          aria-activedescendant=${matches.length ? optionId(active) : nothing}
          aria-autocomplete="list" autocomplete="off" spellcheck="false" placeholder=${this.placeholder}
          @input=${(e) => {
            this.query = e.target.value;
            this.active = 0;
          }}
          @keydown=${(e) => this.#keydown(e)} />
      </div>
      <div class="list" role="listbox" id=${`${this.#id}-list`} aria-label="Commands">
        ${matches.length
          ? repeat(matches, (m) => m.item.id, (m, i) => {
              const { item, positions } = m;
              const second = item.disabled && item.reason ? item.reason : item.detail;
              return html`<div class="row" role="option" id=${optionId(i)} aria-selected=${i === active ? "true" : "false"}
                aria-disabled=${item.disabled ? "true" : nothing}
                @pointermove=${() => this.active !== i && (this.active = i)}
                @click=${() => this.#run(m)}>
                <span class="icon">${item.icon ? glyph(item.icon) : nothing}</span>
                <span class="label">${marked(item.label, positions, 0)}</span>
                <span class="detail">${second ? (item.disabled ? second : marked(second, positions, item.label.length + 1)) : nothing}</span>
                ${kbd(item.keys)}
              </div>`;
            })
          : html`<p class="empty">No command matches “${this.query.trim()}”</p>`}
      </div>
    </dialog>`;
  }
}
Palette.define("dp-palette");

adopt(css`
  dp-palette dialog {
    width: min(640px, 92vw);
    margin: 20vh auto auto;
    padding: 0;
    color: var(--fg);
    background: var(--bg-overlay);
    border: none;
    border-radius: var(--radius-pop);
    box-shadow: var(--shadow);
    font: var(--fs) / var(--lh) var(--font-ui);
    overflow: hidden;
  }
  dp-palette dialog::backdrop { background: color-mix(in srgb, black 25%, transparent); }
  dp-palette .query {
    display: flex;
    align-items: center;
    gap: var(--gap);
    padding: 0 calc(var(--pad) * 1.5);
    border-bottom: var(--rule);
    color: var(--fg-3);
  }
  dp-palette .scope {
    flex: none;
    padding: 1px 8px;
    border-radius: var(--radius);
    background: var(--accent-wash);
    color: var(--accent);
    font-size: var(--fs-small);
    font-weight: 600;
    white-space: nowrap;
  }
  dp-palette input {
    flex: 1;
    min-width: 0;
    height: calc(var(--control) + 16px);
    border: none;
    background: transparent;
    color: var(--fg);
    font: inherit;
    font-size: calc(var(--fs) * 1.15);
  }
  dp-palette input::placeholder { color: var(--fg-3); }
  dp-palette input:focus-visible { outline: none; } /* the caret is the focus; the dialog frames it */
  dp-palette .list { max-height: min(420px, 52vh); overflow: auto; padding: 4px; }
  dp-palette .row {
    display: grid;
    grid-template-columns: var(--icon) auto 1fr auto;
    align-items: center;
    gap: 10px;
    min-height: calc(var(--row) + 6px);
    padding: 0 var(--pad);
    border-radius: var(--radius);
    cursor: default;
  }
  dp-palette .row[aria-selected="true"] { background: var(--sel-bg); color: var(--sel-fg); }
  dp-palette .row[aria-disabled="true"] { color: var(--fg-3); }
  dp-palette .row .icon { display: flex; color: var(--fg-2); }
  dp-palette .row .label { white-space: nowrap; }
  dp-palette .row .detail { color: var(--fg-3); font-size: var(--fs-small); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  dp-palette .row[aria-disabled="true"] .detail { font-style: italic; }
  dp-palette mark { background: none; color: var(--accent); font-weight: 600; }
  dp-palette .row[aria-selected="true"] mark { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
  dp-palette .empty { margin: 0; padding: calc(var(--pad) * 1.5); color: var(--fg-3); }
`);
