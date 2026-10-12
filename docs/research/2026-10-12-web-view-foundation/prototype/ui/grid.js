// <dp-grid>: a compact treegrid. The rows arrive flat and already ordered (the caller sorts
// and collapses); the grid draws them, moves focus, and keeps a selection — focus and
// selection apart, the way Gmail and Linear keep them, so arrowing through rows never
// reshapes anything and selecting does.
//
// The grid element is the one Tab stop (data-nav, so the shell's bare keys work on it);
// rows are pointed at with aria-activedescendant, never focused. It owns no truth: a gesture
// updates its own `selected`/`focusKey` at once so it feels instant, and emits the event so
// the caller can store it — or overwrite it.
//
//   dp-focus  { key }                   dp-select { keys: Set, via: "key" | "pointer" }
//   dp-toggle { key }  (expand/collapse) dp-open  { key }
//   dp-sort   { key, dir }              dp-context { key, event }
//
// Every row is in the DOM. Past ~500 rows this wants virtualising (fixed --row heights make
// that simple, keeping the focused row mounted); a plan this size does not.

import { DpElement } from "../engine/element.js";
import { html, repeat } from "../engine/template.js";
import { glyph } from "./glyph.js";
import { flash, still } from "./motion.js";
import { adopt, css } from "./style.js";

let grids = 0;

export class DpGrid extends DpElement {
  static shadow = false;
  static props = {
    columns: { type: Object, value: [] }, // [{ key, label, width, align, sortable, tree, render(row) }]
    rows: { type: Object, value: [] }, // [{ key, level, kind, expandable, expanded, cells }]
    selected: { type: Object, value: new Set() },
    focusKey: { type: Object, value: null },
    sort: { type: Object, value: null }, // { key, dir: "asc" | "desc" }
    changed: { type: Object, value: new Set() },
  };

  #id = `grid${++grids}`;
  #anchor = null;
  #widths = new Map(); // column key -> px, from a drag or an auto-fit
  #renderedSort = null;
  #before = null; // row key -> top, measured just before a sort lands
  #flashed = null;
  #scrolledTo = null;

  connected() {
    if (this.hasAttribute("role")) return;
    this.setAttribute("role", "treegrid");
    this.setAttribute("aria-multiselectable", "true");
    this.setAttribute("tabindex", "0");
    this.setAttribute("data-nav", "");
    this.addEventListener("keydown", (e) => this.#key(e));
    this.addEventListener("mousedown", (e) => this.#press(e));
    this.addEventListener("dblclick", (e) => this.#double(e));
    this.addEventListener("contextmenu", (e) => this.#context(e));
    // Arriving with nothing focused lands on the first row, so the first j is not wasted.
    this.addEventListener("focus", () => {
      if (this.focusKey === null && this.rows.length) this.#focus(this.rows[0].key);
    });
  }

  rowId(key) {
    return `${this.#id}-${key}`;
  }

  rowElement(key) {
    return this.querySelector(`[data-key="${CSS.escape(String(key))}"]`);
  }

  render() {
    const { columns, rows, selected, focusKey, sort } = this;
    // A new sort is about to move rows: note where they are now, play them home after.
    const sortKey = sort ? `${sort.key}:${sort.dir}` : null;
    if (this.#renderedSort !== null && sortKey !== this.#renderedSort && !still()) {
      this.#before = new Map([...this.querySelectorAll(".row")].map((el) => [el.dataset.key, el.getBoundingClientRect().top]));
    }
    this.#renderedSort = sortKey;

    this.style.setProperty("--cols", columns.map((c) => (this.#widths.has(c.key) ? `${this.#widths.get(c.key)}px` : c.width ?? "1fr")).join(" "));
    if (focusKey !== null && rows.some((r) => r.key === focusKey)) this.setAttribute("aria-activedescendant", this.rowId(focusKey));
    else this.removeAttribute("aria-activedescendant");
    this.setAttribute("aria-rowcount", String(rows.length + 1));

    const tree = columns.find((c) => c.tree) ?? columns[0];
    return html`
      <div class="head" role="row" aria-rowindex="1">
        ${columns.map((c) => this.#header(c, sort))}
      </div>
      ${repeat(rows, (r) => r.key, (row, i) => this.#row(row, i, columns, tree, selected.has(row.key), row.key === focusKey))}
    `;
  }

  #header(column, sort) {
    const dir = sort?.key === column.key ? sort.dir : null;
    const aria = dir === "asc" ? "ascending" : dir === "desc" ? "descending" : column.sortable ? "none" : null;
    return html`<div class="cell ${column.align === "end" ? "end" : ""} ${column.sortable ? "sortable" : ""}" role="columnheader" aria-sort=${aria} data-col=${column.key}>
      <span class="trunc">${column.label}</span>${dir ? html`<span class="arrow" aria-hidden="true">${dir === "asc" ? "▲" : "▼"}</span>` : null}
      <span class="grip" data-grip=${column.key} aria-hidden="true"></span>
    </div>`;
  }

  #row(row, index, columns, tree, isSelected, isFocused) {
    const cls = `row ${row.kind === "group" ? "group" : ""} ${isFocused ? "focus" : ""}`;
    return html`<div class=${cls} role="row" id=${this.rowId(row.key)} data-key=${row.key} aria-rowindex=${index + 2}
        aria-level=${row.level ?? 1} aria-expanded=${row.expandable ? String(!!row.expanded) : null} aria-selected=${String(isSelected)}>
      ${columns.map((c) => (c === tree ? this.#treeCell(row, c) : html`<div class="cell ${c.align === "end" ? "end" : ""}" role="gridcell"><span class="trunc">${c.render(row)}</span></div>`))}
    </div>`;
  }

  #treeCell(row, column) {
    const indent = `padding-inline-start: calc(var(--pad) + ${((row.level ?? 1) - 1) * 12}px)`;
    return html`<div class="cell tree" role="gridcell" style=${indent}>
      ${row.expandable ? html`<span class="twist ${row.expanded ? "open" : ""}" data-twist="">${glyph("chevron-right")}</span>` : html`<span class="twist none"></span>`}
      <span class="trunc">${column.render(row)}</span>
    </div>`;
  }

  updated() {
    // Rows a sort moved travel from where they were. This is motion.js's flip() split in two:
    // the "before" is measured in render(), because the change is the render itself.
    if (this.#before) {
      const before = this.#before;
      this.#before = null;
      const time = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--dur-layout")) || 0;
      for (const el of this.querySelectorAll(".row")) {
        const old = before.get(el.dataset.key);
        if (old === undefined) continue;
        const dy = old - el.getBoundingClientRect().top;
        if (!dy) continue;
        el.getAnimations().forEach((a) => a.cancel());
        el.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: time, easing: "cubic-bezier(0.2, 0, 0, 1)" });
      }
    }
    // What someone else changed washes once.
    if (this.changed !== this.#flashed) {
      this.#flashed = this.changed;
      for (const key of this.changed) {
        const el = this.rowElement(key);
        if (el) flash(el);
      }
    }
    const focused = this.focusKey !== this.#scrolledTo && this.rowElement(this.focusKey);
    if (focused) {
      this.#scrolledTo = this.focusKey;
      focused.scrollIntoView({ block: "nearest" });
    }
    // A title only where the text is cut — a tooltip that repeats what is visible is noise.
    for (const el of this.querySelectorAll(".row .trunc")) {
      if (el.scrollWidth > el.clientWidth) el.title = el.textContent.trim();
      else if (el.title) el.removeAttribute("title");
    }
  }

  // ------------------------------------------------------------ gestures

  #focus(key) {
    if (key === null || key === undefined) return;
    this.focusKey = key;
    this.emit("dp-focus", { key });
  }

  #select(keys, via) {
    this.selected = keys;
    this.emit("dp-select", { keys, via });
  }

  #selectable(row) {
    return row && row.kind !== "group";
  }

  #range(from, to) {
    const rows = this.rows;
    let a = rows.findIndex((r) => r.key === from);
    let b = rows.findIndex((r) => r.key === to);
    if (a < 0) a = b;
    if (a > b) [a, b] = [b, a];
    return new Set(rows.slice(a, b + 1).filter((r) => this.#selectable(r)).map((r) => r.key));
  }

  #move(delta, extend) {
    const rows = this.rows;
    if (!rows.length) return;
    const at = rows.findIndex((r) => r.key === this.focusKey);
    const next = rows[Math.max(0, Math.min(rows.length - 1, at < 0 ? 0 : at + delta))];
    if (extend) {
      this.#anchor ??= this.focusKey ?? next.key;
      this.#select(this.#range(this.#anchor, next.key), "key");
    } else this.#anchor = next.key;
    this.#focus(next.key);
  }

  #key(e) {
    if (e.defaultPrevented || e.target !== this || e.altKey) return;
    const command = e.ctrlKey || e.metaKey;
    const row = this.rows.find((r) => r.key === this.focusKey);
    let handled = true;
    if (command) {
      if (e.key.toLowerCase() === "a") this.#select(new Set(this.rows.filter((r) => this.#selectable(r)).map((r) => r.key)), "key");
      else handled = false;
    } else
      switch (e.key) {
        case "ArrowDown":
          this.#move(1, e.shiftKey);
          break;
        case "j":
          this.#move(1, false);
          break;
        case "ArrowUp":
          this.#move(-1, e.shiftKey);
          break;
        case "k":
          this.#move(-1, false);
          break;
        case "Home":
          this.#move(-Infinity, e.shiftKey);
          break;
        case "End":
          this.#move(Infinity, e.shiftKey);
          break;
        case "x": // Space is not ours: the shell binds it to Peek
          if (this.#selectable(row)) {
            const keys = new Set(this.selected);
            keys.has(row.key) ? keys.delete(row.key) : keys.add(row.key);
            this.#anchor = row.key;
            this.#select(keys, "key");
          } else handled = false;
          break;
        case "ArrowRight":
          if (row?.expandable && !row.expanded) this.emit("dp-toggle", { key: row.key });
          else if (row?.expandable) this.#move(1, false);
          else handled = false;
          break;
        case "ArrowLeft":
          if (row?.expandable && row.expanded) this.emit("dp-toggle", { key: row.key });
          else if ((row?.level ?? 1) > 1) {
            const at = this.rows.indexOf(row);
            const parent = this.rows.slice(0, at).reverse().find((r) => (r.level ?? 1) < row.level);
            if (parent) this.#focus(parent.key);
          } else handled = false;
          break;
        case "Enter":
          if (row) this.emit("dp-open", { key: row.key });
          else handled = false;
          break;
        case "ContextMenu":
          if (row) this.emit("dp-context", { key: row.key, event: e });
          else handled = false;
          break;
        case "F10":
          if (e.shiftKey && row) this.emit("dp-context", { key: row.key, event: e });
          else handled = false;
          break;
        default:
          handled = false;
      }
    if (handled) e.preventDefault();
  }

  #press(e) {
    if (e.button !== 0) return;
    const grip = e.target.closest("[data-grip]");
    if (grip) return this.#resize(e, grip.dataset.grip);
    const header = e.target.closest(".head [data-col]");
    if (header) return this.#sortBy(header.dataset.col);
    const el = e.target.closest(".row");
    if (!el) return;
    const row = this.rows.find((r) => String(r.key) === el.dataset.key);
    if (!row) return;
    if (e.target.closest("[data-twist]")) {
      e.preventDefault();
      this.focus();
      this.#focus(row.key);
      return this.emit("dp-toggle", { key: row.key });
    }
    if (e.shiftKey) e.preventDefault(); // a range, not a text selection
    if (e.shiftKey && this.#selectable(row)) this.#select(this.#range(this.#anchor ?? this.focusKey ?? row.key, row.key), "pointer");
    else if ((e.ctrlKey || e.metaKey) && this.#selectable(row)) {
      const keys = new Set(this.selected);
      keys.has(row.key) ? keys.delete(row.key) : keys.add(row.key);
      this.#anchor = row.key;
      this.#select(keys, "pointer");
    } else this.#anchor = row.key;
    this.#focus(row.key);
  }

  #double(e) {
    const grip = e.target.closest("[data-grip]");
    if (grip) return this.#autofit(grip.dataset.grip);
    const el = e.target.closest(".row");
    if (el && !e.target.closest("[data-twist]")) this.emit("dp-open", { key: this.rows.find((r) => String(r.key) === el.dataset.key)?.key });
  }

  #context(e) {
    const el = e.target.closest(".row");
    if (!el) return;
    const row = this.rows.find((r) => String(r.key) === el.dataset.key);
    if (!row) return;
    e.preventDefault();
    this.focus();
    if (this.#selectable(row) && !this.selected.has(row.key)) {
      this.#anchor = row.key;
      this.#select(new Set([row.key]), "pointer");
    }
    this.#focus(row.key);
    this.emit("dp-context", { key: row.key, event: e });
  }

  #sortBy(key) {
    const column = this.columns.find((c) => c.key === key);
    if (!column?.sortable) return;
    const dir = this.sort?.key === key && this.sort.dir === "asc" ? "desc" : "asc";
    this.sort = { key, dir };
    this.emit("dp-sort", { key, dir });
  }

  #resize(e, key) {
    e.preventDefault();
    const cell = this.querySelector(`.head [data-col="${CSS.escape(key)}"]`);
    const start = e.clientX;
    const width = cell.getBoundingClientRect().width;
    const move = (m) => {
      this.#widths.set(key, Math.max(32, Math.round(width + m.clientX - start)));
      this.style.setProperty("--cols", this.columns.map((c) => (this.#widths.has(c.key) ? `${this.#widths.get(c.key)}px` : c.width ?? "1fr")).join(" "));
    };
    const up = () => {
      removeEventListener("pointermove", move);
      removeEventListener("pointerup", up);
    };
    addEventListener("pointermove", move);
    addEventListener("pointerup", up);
  }

  #autofit(key) {
    const index = this.columns.findIndex((c) => c.key === key);
    let widest = 0;
    for (const row of this.querySelectorAll(".head, .row")) {
      const cell = row.children[index];
      const text = cell?.querySelector(".trunc");
      if (!text) continue;
      const pad = cell.getBoundingClientRect().width - text.getBoundingClientRect().width;
      widest = Math.max(widest, text.scrollWidth + pad + 2);
    }
    if (!widest) return;
    this.#widths.set(key, Math.ceil(widest));
    this.style.setProperty("--cols", this.columns.map((c) => (this.#widths.has(c.key) ? `${this.#widths.get(c.key)}px` : c.width ?? "1fr")).join(" "));
  }
}

DpGrid.define("dp-grid");

adopt(css`
  dp-grid {
    display: block;
    position: relative;
    overflow: auto;
    background: var(--bg);
    color: var(--fg);
    font-size: var(--fs);
    contain: content;
  }
  dp-grid:focus-visible { outline: none; }

  dp-grid .head,
  dp-grid .row {
    display: grid;
    grid-template-columns: var(--cols);
    min-width: max-content;
    min-height: var(--row);
  }

  dp-grid .head {
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--bg-sunken);
    border-bottom: 1px solid var(--line-strong);
    color: var(--fg-2);
    font-size: var(--fs-small);
    font-weight: 600;
    text-transform: var(--label-case);
    letter-spacing: 0.02em;
    user-select: none;
  }
  dp-grid .head .cell { position: relative; gap: 4px; }
  dp-grid .head .sortable:hover { color: var(--fg); }
  dp-grid .head .arrow { font-size: 8px; color: var(--accent); }
  dp-grid .grip {
    position: absolute;
    inset-block: 0;
    inset-inline-end: -4px;
    width: 8px;
    z-index: 1;
    cursor: col-resize;
  }
  dp-grid .grip:hover { background: linear-gradient(var(--line-strong), var(--line-strong)) center / 1px 60% no-repeat; }

  dp-grid .cell {
    display: flex;
    align-items: center;
    min-width: 0;
    padding: 0 var(--pad);
    overflow: hidden;
    white-space: nowrap;
  }
  dp-grid .cell.end { justify-content: flex-end; text-align: end; }
  dp-grid .trunc {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  dp-grid .cell .trunc { display: block; }
  dp-grid .cell .trunc:has(> .status-mark, > .mark-owner, > .mark-bar) { display: inline-flex; }

  dp-grid .row {
    border-bottom: calc(var(--grid-lines) * 1px) solid var(--line);
    scroll-margin-block-start: var(--row);
    cursor: default;
  }
  dp-grid .row:hover { background: var(--bg-hover); }
  dp-grid .row[aria-selected="true"] { background: var(--sel-bg); color: var(--sel-fg); }
  dp-grid .row[aria-selected="true"] .mark-owner,
  dp-grid .row[aria-selected="true"] .dim { color: inherit; }
  dp-grid .row.focus { box-shadow: inset 2px 0 0 var(--line-strong); }
  dp-grid:focus .row.focus { box-shadow: inset 0 0 0 2px var(--focus); }

  dp-grid .row.group {
    font-weight: 600;
    background: color-mix(in srgb, var(--bg-sunken) 60%, transparent);
    border-bottom: 1px solid var(--line);
  }
  dp-grid .row.group:hover { background: var(--bg-hover); }
  dp-grid .row.group .tree .trunc { font-family: var(--font-title); }

  dp-grid .tree { gap: 2px; }
  dp-grid .twist {
    display: inline-grid;
    place-items: center;
    width: 16px;
    height: 16px;
    flex: none;
    color: var(--fg-2);
    border-radius: var(--radius);
  }
  dp-grid .twist:not(.none):hover { background: var(--bg-hover); color: var(--fg); }
  dp-grid .twist .glyph { width: 12px; height: 12px; transition: rotate var(--dur-micro) var(--ease-move); }
  dp-grid .twist.open .glyph { rotate: 90deg; }

  dp-grid .dim { color: var(--fg-2); }
`);
