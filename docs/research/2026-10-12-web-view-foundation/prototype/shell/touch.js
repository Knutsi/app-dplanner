// The touch frame: a separate UI, not the desktop squeezed. A stack of screens with a back
// button; the selection bar takes the app bar's place, as the desktop's takes the toolbar's;
// the bottom action bar is the toolbar's touch form and a sheet is the context menu's. Every
// verb still comes from the command registry, so the phone can never grow one the desktop lacks.
//
// It runs the same workspace, headless: the active tab is the root of the screen stack, so
// opening a project from the Projects tab lands here without a second way to navigate.
//
// Motion here says where you went: a pushed screen arrives from the right, a popped one from
// the left. Nothing else moves.

import { DpElement } from "../engine/element.js";
import { html, nothing } from "../engine/template.js";
import { signal, effect } from "../engine/signals.js";
import { adopt, css } from "../ui/style.js";
import { glyph } from "../ui/glyph.js";
import { still } from "../ui/motion.js";
import "../ui/sheet.js";
import { setSelection } from "./context.js";
import { contextGroups, selectionModel } from "./surfaces.js";
import { kindOf, panels, activeTab } from "./workspace.js";
import { running } from "./activity.js";

const TABS = [
  { id: "steps", label: "Steps", icon: "table" },
  { id: "projects", label: "Projects", icon: "project" },
  { id: "activity", label: "Activity", icon: "gauge" },
];

class TouchApp extends DpElement {
  static shadow = false;

  #stack = signal([]); // [{ kind, params, view }]
  #tab = signal("steps");
  #direction = "none";
  #root = null;

  connected() {
    this.stopFollowing = effect(() => {
      const tab = activeTab.value;
      if (!tab || tab === this.#root) return;
      this.#root = tab;
      this.#reset();
      this.#tab.value = "steps";
    });
  }

  disconnected() {
    this.stopFollowing?.();
  }

  #make(kind, params) {
    return { kind, params, view: kindOf({ kind }).touch(params, { open: (k, p) => this.push(k, p) }) };
  }

  #reset() {
    this.#stack.value = [this.#make(this.#root.kind, this.#root.params)];
  }

  push(kind, params) {
    this.#direction = "forward";
    this.#stack.value = [...this.#stack.peek(), this.#make(kind, params)];
  }

  pop() {
    this.#direction = "back";
    this.#stack.value = this.#stack.peek().slice(0, -1);
  }

  updated() {
    const screen = this.querySelector(".touch-screen");
    if (!screen || this.#direction === "none" || still()) return;
    const from = this.#direction === "forward" ? "24px" : "-24px";
    screen.animate([{ translate: `${from} 0`, opacity: 0.4 }, { translate: "0 0", opacity: 1 }], { duration: 220, easing: "cubic-bezier(0.2, 0, 0, 1)" });
    this.#direction = "none";
  }

  #header(top, depth, selection) {
    if (selection)
      return html`<header class="touch-bar selecting" aria-live="polite">
        <button class="touch-icon" aria-label="Clear selection" @click=${() => setSelection([])}>${glyph("close")}</button>
        <h1>${selection.count} selected</h1>
      </header>`;
    const title = this.#tab.value === "steps" ? top.view.title() : TABS.find((t) => t.id === this.#tab.value).label;
    return html`<header class="touch-bar">
      ${depth > 1 && this.#tab.value === "steps" ? html`<button class="touch-icon" aria-label="Back" @click=${() => this.pop()}>${glyph("chevron-left")}</button>` : html`<span class="touch-icon"></span>`}
      <h1>${title}</h1>
      ${running.value.length ? html`<span class="touch-busy" aria-label=${`${running.value.length} running`}></span>` : nothing}
    </header>`;
  }

  #actions(top, selection) {
    if (selection) return selection.items;
    if (this.#tab.value === "steps" && top.view.actionsFor) return contextGroups(top.view.actionsFor, { touch: true }).flat();
    return [];
  }

  render() {
    const stack = this.#stack.value;
    const top = stack.at(-1);
    if (!top) return nothing;
    const selection = selectionModel(() => setSelection([]), { touch: true });
    const actions = this.#actions(top, selection);
    const section = this.#tab.value;
    const body =
      section === "steps" ? top.view.element : section === "projects" ? panels.left.value?.render() : panels.bottom.value?.render();
    return html`
      ${this.#header(top, stack.length, selection)}
      <main class="touch-screen">${body}</main>
      ${actions.length ? html`<dp-actionbar .items=${actions}></dp-actionbar>` : nothing}
      <nav class="touch-tabs" aria-label="Sections">
        ${TABS.map(
          (t) => html`<button aria-current=${t.id === section ? "page" : "false"} @click=${() => {
            if (t.id === section && t.id === "steps") this.#reset();
            this.#tab.value = t.id;
          }}>${glyph(t.icon)}<span>${t.label}</span></button>`,
        )}
      </nav>
      <dp-sheet></dp-sheet>
    `;
  }
}
TouchApp.define("dp-touch-app");

adopt(css`
  dp-touch-app {
    display: grid;
    grid-template-rows: auto 1fr auto auto;
    height: 100dvh;
    background: var(--bg);
    font-size: 15px;
  }
  dp-touch-app .touch-bar {
    display: grid;
    grid-template-columns: 44px 1fr 44px;
    align-items: center;
    min-height: 52px;
    padding-top: env(safe-area-inset-top, 0px);
    border-bottom: var(--rule);
    background: var(--bg-raised);
    transition: background-color var(--dur-micro) linear;
  }
  dp-touch-app .touch-bar.selecting { background: var(--accent-wash); }
  dp-touch-app .touch-bar h1 {
    margin: 0;
    text-align: center;
    font: var(--title-weight) 16px / 1.2 var(--font-title);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  dp-touch-app .touch-icon {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border: 0;
    background: transparent;
    color: var(--fg);
  }
  dp-touch-app .touch-icon .glyph { width: 22px; height: 22px; }
  dp-touch-app .touch-busy {
    justify-self: center;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 2px solid var(--tone-busy);
    border-right-color: transparent;
    animation: frame-spin 0.9s linear infinite;
  }
  dp-touch-app .touch-screen { overflow: auto; overscroll-behavior: contain; min-height: 0; }
  dp-touch-app .touch-tabs {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    border-top: var(--rule);
    background: var(--bg-raised);
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  dp-touch-app .touch-tabs button {
    display: grid;
    justify-items: center;
    gap: 2px;
    min-height: 52px;
    padding: 6px 0;
    border: 0;
    background: transparent;
    color: var(--fg-3);
    font: 500 11px var(--font-ui);
  }
  dp-touch-app .touch-tabs button[aria-current="page"] { color: var(--accent); }
  dp-touch-app .touch-tabs .glyph { width: 22px; height: 22px; }
  dp-touch-app .library-nav a { padding: 12px 16px; }
  @keyframes frame-spin { to { rotate: 1turn; } }
`);
