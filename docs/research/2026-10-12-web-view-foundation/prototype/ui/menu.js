// Menus: <dp-menu> (a popup list of items, one submenu level), <dp-menubar> and contextMenu().
//
// The keyboard contract is WAI-ARIA's menu and menubar patterns in full; the pointer gets the
// two things that make desktop menus pleasant — a short hover delay before a submenu opens, and
// aim protection, so a diagonal move toward an open submenu does not switch it on the way. A
// menu opened by a click grows out of its origin; opened from the keyboard it is simply there.

import { signal } from "../engine/signals.js";
import { DpElement } from "../engine/element.js";
import { html, nothing, render } from "../engine/template.js";
import { glyph } from "./glyph.js";
import { enter } from "./motion.js";
import { adopt, css } from "./style.js";
import { chordOf, kbd } from "./keys.js";

const SUBMENU_HOVER_MS = 100;
const AIM_PATIENCE_MS = 300;
const TYPEAHEAD_MS = 500;
const EDGE_PX = 4;
const OVERLAP_PX = 2;

// aria-keyshortcuts takes chords, not sequences ("g p" would read as two alternatives).
const ariaKeys = (binding) => (binding && !binding.includes(" ") ? binding.replace("Ctrl", "Control") : nothing);

export class DpMenu extends DpElement {
  static shadow = false;
  static props = { groups: { type: Object, value: [] } };

  parentMenu = null;
  owner = null; // an element whose clicks are not "outside" (the menubar that opened us)
  onEdge = null; // (direction) => void, for ArrowLeft/Right at a root menu (the menubar's)
  #items = [];
  #subIndex = signal(-1);
  #sub = null;
  #returnTo = null;
  #subTimer = 0;
  #aimTimer = 0;
  #lastPoint = null;
  #typed = "";
  #typedAt = 0;
  #wired = false;

  connected() {
    if (this.#wired) return;
    this.#wired = true;
    this.setAttribute("role", "menu");
    this.tabIndex = -1;
    this.popover = "manual";
    this.addEventListener("keydown", (e) => this.#onKey(e));
    this.addEventListener("click", (e) => this.#onClick(e));
    this.addEventListener("pointermove", (e) => this.#onMove(e));
    this.addEventListener("pointerleave", () => this.#onLeave());
    this.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  get isOpen() {
    return this.matches(":popover-open");
  }

  render() {
    const items = [];
    const open = this.#subIndex.value;
    const rows = this.groups.map(
      (group, g) => html`${g ? html`<div class="sep" role="separator"></div>` : nothing}${group.map((item) => {
        const i = items.push(item) - 1;
        const why = item.disabled && item.reason ? item.reason : nothing;
        return html`<div
          class="item"
          role=${item.checked == null ? "menuitem" : "menuitemcheckbox"}
          tabindex="-1"
          data-index=${i}
          aria-disabled=${item.disabled ? "true" : nothing}
          aria-checked=${item.checked == null ? nothing : String(Boolean(item.checked))}
          aria-haspopup=${item.submenu ? "menu" : nothing}
          aria-expanded=${item.submenu ? String(open === i) : nothing}
          ?data-open=${open === i}
          data-tip=${why}
          aria-description=${why}
          aria-keyshortcuts=${ariaKeys(item.keys)}
        >
          <span class=${item.icon ? "ico own" : "ico"}>${item.icon ? glyph(item.icon) : item.checked ? glyph("check") : nothing}</span>
          <span class="label">${item.label}</span>
          <span class="keys">${item.keys ? kbd(item.keys, { plain: true }) : nothing}</span>
          <span class="chev">${item.submenu ? glyph("chevron-right") : nothing}</span>
        </div>`;
      })}`,
    );
    this.#items = items;
    return html`${rows}`;
  }

  // at: { x, y } (a point) or { anchor, side: "below" | "right" }.
  // focus: "first" | "last" | "menu" (the menu itself; arrows then start at the top).
  open(at, { via = "pointer", focus = via === "key" ? "first" : "menu", returnTo = document.activeElement } = {}) {
    const switching = this.isOpen;
    this.#closeSub();
    this.#returnTo = returnTo;
    if (!this.isConnected) document.body.append(this);
    // A menu must be measurable the moment it opens, so render now rather than next microtask.
    render(this.render(), this, { host: this });
    if (!switching) this.showPopover();
    const origin = this.#place(at);
    if (!switching) enter(this, { origin, via });
    if (focus === "first") this.#focusItem(this.#step(-1, 1));
    else if (focus === "last") this.#focusItem(this.#step(this.#items.length, -1));
    else this.focus({ preventScroll: true });
    if (!this.parentMenu && !switching) this.#listenOutside(true);
  }

  // reason: "escape" | "activate" | "outside" | "tab" | "close"
  close(reason = "close") {
    if (!this.isOpen) return;
    this.#closeSub();
    clearTimeout(this.#subTimer);
    clearTimeout(this.#aimTimer);
    const hadFocus = this.contains(document.activeElement) || document.activeElement === this;
    this.hidePopover();
    if (!this.parentMenu) this.#listenOutside(false);
    if (hadFocus && reason !== "outside") this.#returnTo?.focus?.({ preventScroll: true });
    this.emit("dp-close", { reason }, { bubbles: false });
  }

  #root() {
    let menu = this;
    while (menu.parentMenu) menu = menu.parentMenu;
    return menu;
  }

  #contains(node) {
    for (let menu = this; menu; menu = menu.#sub?.isOpen ? menu.#sub : null) if (menu.contains(node)) return true;
    return false;
  }

  #outside = (e) => {
    if (this.#contains(e.target) || this.owner?.contains(e.target)) return;
    this.close("outside");
  };
  #resized = () => this.close("outside");

  #listenOutside(on) {
    const method = on ? "addEventListener" : "removeEventListener";
    document[method]("pointerdown", this.#outside, true);
    window[method]("resize", this.#resized);
  }

  #place(at) {
    const w = this.offsetWidth;
    const h = this.offsetHeight;
    let x;
    let y;
    let ox = "left";
    let oy = "top";
    if (at.anchor) {
      const r = at.anchor.getBoundingClientRect();
      if (at.side === "right") {
        // A submenu sits against its parent menu's edge, not its row's, overlapping it by a hair.
        const parent = at.anchor.closest("dp-menu")?.getBoundingClientRect() ?? r;
        x = parent.right - OVERLAP_PX;
        y = r.top - parseFloat(getComputedStyle(this).paddingTop);
        if (x + w > innerWidth - EDGE_PX) [x, ox] = [parent.left - w + OVERLAP_PX, "right"];
      } else {
        [x, y] = [r.left, r.bottom];
        if (y + h > innerHeight - EDGE_PX && r.top - h >= EDGE_PX) [y, oy] = [r.top - h, "bottom"];
      }
    } else {
      [x, y] = [at.x, at.y];
      if (x + w > innerWidth - EDGE_PX) [x, ox] = [at.x - w, "right"];
      if (y + h > innerHeight - EDGE_PX) [y, oy] = [at.y - h, "bottom"];
    }
    this.style.left = `${Math.max(EDGE_PX, Math.min(x, innerWidth - w - EDGE_PX))}px`;
    this.style.top = `${Math.max(EDGE_PX, Math.min(y, innerHeight - h - EDGE_PX))}px`;
    return `${oy} ${ox}`;
  }

  #rows() {
    return this.querySelectorAll(":scope > .item");
  }

  #activeIndex() {
    const row = document.activeElement?.closest?.(".item");
    return row && this.contains(row) ? Number(row.dataset.index) : -1;
  }

  #focusItem(i) {
    this.#rows()[i]?.focus({ preventScroll: false });
  }

  // The next index from `from` in `direction`, wrapping. Disabled items stay reachable (APG):
  // a person can land on one and read why it is off.
  #step(from, direction) {
    const n = this.#items.length;
    if (!n) return -1;
    return (((from + direction) % n) + n) % n;
  }

  #onKey(e) {
    const i = this.#activeIndex();
    const item = this.#items[i];
    let handled = true;
    switch (e.key) {
      case "ArrowDown":
        this.#focusItem(this.#step(i < 0 ? -1 : i, 1));
        break;
      case "ArrowUp":
        this.#focusItem(this.#step(i < 0 ? this.#items.length : i, -1));
        break;
      case "Home":
        this.#focusItem(0);
        break;
      case "End":
        this.#focusItem(this.#items.length - 1);
        break;
      case "ArrowRight":
        if (item?.submenu && !item.disabled) this.#openSub(i, "key");
        else this.#root().onEdge?.(1);
        break;
      case "ArrowLeft":
        if (this.parentMenu) this.parentMenu.#subClosedByKey();
        else this.onEdge?.(-1);
        break;
      case "Escape":
        if (this.parentMenu) this.parentMenu.#subClosedByKey();
        else this.close("escape");
        break;
      case "Enter":
      case " ":
        if (item) this.#activate(i, "key");
        break;
      case "Tab":
        this.#root().close("tab");
        handled = false; // focus goes back where it came from, and Tab moves on from there
        break;
      default:
        handled = this.#typeahead(e, i);
    }
    if (handled) {
      e.preventDefault();
      e.stopPropagation();
    }
  }

  #typeahead(e, from) {
    if (e.key.length !== 1 || e.ctrlKey || e.metaKey || e.altKey) return false;
    const now = performance.now();
    this.#typed = now - this.#typedAt < TYPEAHEAD_MS ? this.#typed + e.key.toLowerCase() : e.key.toLowerCase();
    this.#typedAt = now;
    const n = this.#items.length;
    const start = this.#typed.length > 1 ? Math.max(from, 0) : from + 1;
    for (let k = 0; k < n; k++) {
      const j = (start + k) % n;
      if (this.#items[j].label.toLowerCase().startsWith(this.#typed)) {
        this.#focusItem(j);
        break;
      }
    }
    return true;
  }

  #onClick(e) {
    const row = e.target.closest(".item");
    if (row) this.#activate(Number(row.dataset.index), "pointer");
  }

  #activate(i, via) {
    const item = this.#items[i];
    if (!item || item.disabled) return;
    if (item.submenu) return this.#openSub(i, via);
    this.#root().close("activate");
    item.run?.();
  }

  #openSub(i, via) {
    clearTimeout(this.#subTimer);
    const row = this.#rows()[i];
    if (!row) return;
    if (this.#subIndex.peek() === i && this.#sub?.isOpen) {
      if (via === "key") this.#sub.#focusItem(0);
      return;
    }
    this.#closeSub();
    if (!this.#sub) {
      this.#sub = document.createElement("dp-menu");
      this.#sub.parentMenu = this;
      this.#sub.addEventListener("dp-close", () => this.#subIndex.value === i && (this.#subIndex.value = -1));
    }
    this.#sub.groups = this.#items[i].submenu;
    this.#subIndex.value = i;
    this.#sub.open({ anchor: row, side: "right" }, { via, focus: via === "key" ? "first" : "menu", returnTo: row });
  }

  #closeSub() {
    clearTimeout(this.#subTimer);
    if (this.#sub?.isOpen) this.#sub.close("close");
    this.#subIndex.value = -1;
  }

  #subClosedByKey() {
    const i = this.#subIndex.peek();
    this.#closeSub();
    this.#focusItem(i);
  }

  // Aim protection: while a submenu is open and the pointer travels inside the triangle from
  // where it was to the submenu's near edge, it is heading there — don't switch rows under it.
  #aiming(from, to) {
    if (!from || !this.#sub?.isOpen) return false;
    const r = this.#sub.getBoundingClientRect();
    const edge = r.left >= this.getBoundingClientRect().right - 1 ? r.left : r.right;
    const a = from;
    const b = { x: edge, y: r.top };
    const c = { x: edge, y: r.bottom };
    const side = (p, q, s) => (q.x - p.x) * (s.y - p.y) - (q.y - p.y) * (s.x - p.x);
    const d1 = side(a, b, to);
    const d2 = side(b, c, to);
    const d3 = side(c, a, to);
    return !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0));
  }

  #onMove(e) {
    const point = { x: e.clientX, y: e.clientY };
    const from = this.#lastPoint;
    this.#lastPoint = point;
    const row = e.target.closest(".item");
    if (!row) return;
    const i = Number(row.dataset.index);
    if (i === this.#activeIndex() && !this.#aimTimer) return;
    clearTimeout(this.#aimTimer);
    this.#aimTimer = 0;
    if (this.#subIndex.peek() !== i && this.#aiming(from, point)) {
      this.#aimTimer = setTimeout(() => {
        this.#aimTimer = 0;
        this.#hover(i);
      }, AIM_PATIENCE_MS);
      return;
    }
    this.#hover(i);
  }

  #hover(i) {
    clearTimeout(this.#subTimer);
    this.#focusItem(i);
    if (this.#subIndex.peek() !== i) this.#closeSub();
    const item = this.#items[i];
    if (item?.submenu && !item.disabled) this.#subTimer = setTimeout(() => this.#openSub(i, "pointer"), SUBMENU_HOVER_MS);
  }

  #onLeave() {
    clearTimeout(this.#subTimer);
    this.#lastPoint = null;
    if (this.#subIndex.peek() < 0 && this.isOpen) this.focus({ preventScroll: true });
  }
}

DpMenu.define("dp-menu");

// The menubar. Top-level menus never appear, disappear or move; what is inside them is asked
// for (`groups()`) each time one opens, so a menu always reflects the selection of that moment.
export class DpMenubar extends DpElement {
  static shadow = false;
  // focusKeys: the chords that bring the keyboard to the bar. F10 is the platform convention,
  // but a desktop (Omarchy, Hyprland) or the browser may take it first, so the shell can add its
  // own; a focus key wins over a menu whose name starts with the same letter.
  static props = { menus: { type: Object, value: [] }, focusKeys: { type: Object, value: ["F10"] } };

  #open = signal(-1);
  #focus = signal(0);
  #menu = null;
  #before = null; // where focus was before the person came to the bar
  #wired = false;

  connected() {
    if (this.#wired) return;
    this.#wired = true;
    this.#menu = document.createElement("dp-menu");
    this.#menu.owner = this;
    this.#menu.onEdge = (direction) => this.#openAt(this.#wrap(this.#open.peek() + direction), "key", "first");
    this.#menu.addEventListener("dp-close", (e) => {
      const i = this.#open.peek();
      this.#open.value = -1;
      if (e.detail.reason === "escape") this.#tops()[i]?.focus();
      else if (e.detail.reason === "activate" && this.#before?.isConnected) this.#before.focus();
    });
    window.addEventListener("keydown", (e) => this.#onGlobalKey(e), true);
    window.addEventListener("keyup", (e) => e.key === "Alt" && this.removeAttribute("data-alt"));
    window.addEventListener("blur", () => this.removeAttribute("data-alt"));
  }

  render() {
    const open = this.#open.value;
    const focus = this.#focus.value;
    return html`<div class="bar" role="menubar" aria-label="Main menu" @keydown=${this.#onKey} @pointerdown=${this.#remember}>
      ${this.menus.map(
        (menu, i) => html`<div
          class="top"
          role="menuitem"
          aria-haspopup="menu"
          aria-expanded=${String(open === i)}
          tabindex=${i === focus ? "0" : "-1"}
          @click=${() => (this.#open.peek() === i ? this.#menu.close("close") : this.#openAt(i, "pointer", "menu"))}
          @pointerenter=${() => this.#open.peek() >= 0 && this.#open.peek() !== i && this.#openAt(i, "pointer", "menu")}
        ><span class="mn">${menu.name[0]}</span>${menu.name.slice(1)}</div>`,
      )}
    </div>`;
  }

  #tops() {
    return this.querySelectorAll(".top");
  }

  #wrap(i) {
    const n = this.menus.length;
    return ((i % n) + n) % n;
  }

  #remember() {
    const active = document.activeElement;
    if (active && !this.contains(active) && !this.#menu.contains(active) && active !== document.body) this.#before = active;
  }

  #openAt(i, via, focus) {
    const top = this.#tops()[i];
    if (!top) return;
    this.#focus.value = i;
    this.#open.value = i;
    this.#menu.groups = this.menus[i].groups();
    this.#menu.open({ anchor: top, side: "below" }, { via, focus, returnTo: this.#before ?? top });
  }

  #onKey(e) {
    const top = e.target.closest(".top");
    if (!top) return;
    const i = [...this.#tops()].indexOf(top);
    const go = (j) => {
      this.#focus.value = this.#wrap(j);
      this.#tops()[this.#focus.peek()].focus();
    };
    const keys = {
      ArrowRight: () => go(i + 1),
      ArrowLeft: () => go(i - 1),
      Home: () => go(0),
      End: () => go(this.menus.length - 1),
      ArrowDown: () => this.#openAt(i, "key", "first"),
      Enter: () => this.#openAt(i, "key", "first"),
      " ": () => this.#openAt(i, "key", "first"),
      ArrowUp: () => this.#openAt(i, "key", "last"),
      Escape: () => this.#before?.isConnected && this.#before.focus(),
    };
    if (!keys[e.key]) return;
    keys[e.key]();
    e.preventDefault();
    e.stopPropagation();
  }

  // Alt+letter opens a menu (its letter underlined while Alt is held); a focus key comes to the bar.
  #onGlobalKey(e) {
    if (e.key === "Alt") return this.setAttribute("data-alt", "");
    if (this.focusKeys.includes(chordOf(e))) {
      this.removeAttribute("data-alt");
      this.#remember();
      e.preventDefault();
      e.stopPropagation();
      return this.#tops()[this.#focus.peek()]?.focus();
    }
    if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const letter = e.code?.startsWith("Key") ? e.code.slice(3).toLowerCase() : e.key.toLowerCase();
    const i = this.menus.findIndex((menu) => menu.name[0].toLowerCase() === letter);
    if (i < 0) return;
    this.removeAttribute("data-alt");
    this.#remember();
    e.preventDefault();
    e.stopPropagation();
    this.#openAt(i, "key", "first");
  }
}

DpMenubar.define("dp-menubar");

let shared = null;

// Right-click opens at the pointer; Shift+F10 or the Menu key opens under the focused thing.
export function contextMenu(event, groups) {
  event.preventDefault();
  shared ??= document.createElement("dp-menu");
  shared.close("close");
  shared.groups = groups;
  const viaKey = event instanceof KeyboardEvent || event.pointerType === "";
  const at = viaKey ? { anchor: event.target, side: "below" } : { x: event.clientX, y: event.clientY };
  shared.open(at, { via: viaKey ? "key" : "pointer" });
  return shared;
}

adopt(css`
  dp-menu:popover-open {
    position: fixed;
    inset: auto;
    margin: 0;
    display: block;
    min-width: calc(var(--row) * 9);
    max-height: calc(100vh - var(--pad) * 2);
    overflow: auto;
    padding: calc(var(--pad) / 2) 0;
    border: 0;
    border-radius: var(--radius-pop);
    background: var(--bg-overlay);
    color: var(--fg);
    font: var(--fs) / var(--lh) var(--font-ui);
    box-shadow: var(--shadow);
  }
  dp-menu:focus-visible {
    outline: none;
  }
  dp-menu .item {
    display: grid;
    grid-template-columns: var(--icon) 1fr auto var(--icon);
    align-items: center;
    gap: var(--gap);
    height: var(--row);
    margin: 0 calc(var(--pad) / 2);
    padding: 0 calc(var(--pad) / 2) 0 var(--pad);
    border-radius: calc(var(--radius) * 0.75);
    white-space: nowrap;
    cursor: default;
    text-transform: var(--label-case);
  }
  dp-menu .item:focus,
  dp-menu .item[data-open] {
    background: var(--sel-bg);
    color: var(--sel-fg);
    outline: none;
  }
  dp-menu .item[aria-disabled="true"] {
    color: var(--fg-3);
  }
  dp-menu .item[aria-disabled="true"]:focus {
    background: var(--bg-hover);
    color: var(--fg-2);
  }
  /* A checked item that has a glyph of its own keeps it, lifted the way a pressed toolbar
     toggle is; only a glyphless item shows a tick — so "Done" (a tick) never reads as checked. */
  dp-menu .item[aria-checked="true"] .ico.own {
    background: var(--accent-wash);
    color: var(--accent);
    border-radius: var(--radius);
    box-shadow: 0 0 0 3px var(--accent-wash);
  }
  dp-menu .ico,
  dp-menu .chev {
    display: flex;
    color: var(--fg-2);
  }
  dp-menu .item:focus .ico,
  dp-menu .item[data-open] .ico,
  dp-menu .item:focus .chev {
    color: inherit;
  }
  dp-menu .keys {
    padding-left: calc(var(--gap) * 2);
    color: var(--fg-2);
    font-size: var(--fs-small);
    text-transform: none;
  }
  dp-menu .item:focus .keys {
    color: inherit;
    opacity: 0.75;
  }
  dp-menu .sep {
    height: 0;
    margin: calc(var(--pad) / 2) var(--pad);
    border-top: var(--rule);
  }

  dp-menubar {
    display: block;
  }
  dp-menubar .bar {
    display: flex;
    align-items: center;
    height: var(--menubar);
    padding: 0 calc(var(--pad) / 2);
    gap: calc(var(--gap) / 4);
    user-select: none;
  }
  dp-menubar .top {
    display: flex;
    align-items: center;
    height: calc(var(--menubar) - var(--pad) / 2);
    padding: 0 var(--pad);
    border-radius: var(--radius);
    color: var(--fg);
    cursor: default;
    text-transform: var(--label-case);
  }
  dp-menubar .top:hover,
  dp-menubar .top[aria-expanded="true"] {
    background: var(--bg-hover);
  }
  dp-menubar .top[aria-expanded="true"] {
    background: var(--sel-bg);
    color: var(--sel-fg);
  }
  dp-menubar[data-alt] .mn {
    text-decoration: underline;
    text-underline-offset: 0.2em;
  }
`);

