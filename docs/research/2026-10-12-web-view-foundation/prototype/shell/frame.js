// The desktop frame: menubar, toolbar, panes, side and bottom panels, the modeline, and the
// overlays (palette, which-key, cheat sheet). It owns layout only — every verb in it comes
// from the command registry through surfaces.js, every view from the workspace.
//
// Where the toolbar lives is the variant's call (--toolbar-place): under the menubar (Ledger),
// folded into the modeline as keyed verbs (Modeline), or floating over the work (Atelier).

import { DpElement } from "../engine/element.js";
import { html, repeat, nothing } from "../engine/template.js";
import { adopt, css } from "../ui/style.js";
import { glyph } from "../ui/glyph.js";
import { kbd } from "../ui/keys.js";
import { variant, toolbarPlace } from "../ui/look.js";
import { activeTheme } from "../ui/theme.js";
import "../ui/menu.js";
import "../ui/toolbar.js";
import "../ui/statusbar.js";
import "../ui/palette.js";
import "../ui/keyhelp.js";
import { tooltips } from "../ui/tooltip.js";
import { commands, MENUS } from "./commands.js";
import { context, parseUri, selectionCount } from "./context.js";
import { menubarModel, toolbarBands, selectionModel, paletteItems, keyItems, toItem } from "./surfaces.js";
import { mode, echo, pending, whichKeyOpen } from "./keyboard.js";
import { panes, activePaneId, activate, viewOf, kindOf, closeTab, pinTab, paneFocus, describe, clearSelection, panels, leftOpen, bottomOpen, overlays } from "./workspace.js";
import { running, unseen } from "./activity.js";

// Alt+M first: on Omarchy the desktop or the browser can take F10 before the page sees it.
const MENUBAR_KEYS = ["Alt+M", "F10"];
const TOOLBAR_BANDS = ["history", "navigate", "step", "status", "agent", "panes"];

let app = null;
const recent = []; // command ids, newest first, for the palette's empty query

// `only` narrows the palette to one family of commands ("theme."), for a menu item that means
// "choose one of many" — More Themes… — without a picker of its own.
function openPalette({ only = null, placeholder = null } = {}) {
  if (only) {
    const items = paletteItems(null).filter((item) => item.id.startsWith(only));
    return app.querySelector("dp-palette").open({ items, placeholder });
  }
  const ctx = context.peek();
  const kind = ctx.selection.length ? parseUri(ctx.selection[0])?.kind : ctx.focus ? parseUri(ctx.focus)?.kind : null;
  const scope = !kind ? null : ctx.selection.length > 1 ? `${ctx.selection.length} ${kind}s` : describe(kind, parseUri(ctx.selection[0] ?? ctx.focus).id);
  app.querySelector("dp-palette").open({
    items: scope ? paletteItems(kind, recent) : paletteItems(null, recent),
    scope,
    placeholder: scope ? `Do something with ${scope}…` : "Type a command…",
    onWiden: () => paletteItems(null, recent),
  });
}

function openCheatsheet() {
  const ctx = context.peek();
  const focusKind = parseUri(ctx.selection[0] ?? ctx.focus)?.kind;
  const all = keyItems();
  const sections = Object.keys(MENUS)
    .map((menu) => ({ title: menu, items: all.filter((item) => commands.get(item.id).menu === menu) }))
    .filter((s) => s.items.length);
  if (focusKind) sections.unshift({ title: `On this ${focusKind}`, items: all.filter((item) => commands.get(item.id).for === focusKind) });
  // The menubar's own keys are not commands, so they would never be listed: say them here.
  sections.push({
    title: "Menus",
    items: [
      { id: "menubar.focus", label: "Go to the menu bar (F10 too, where the desktop lets it through)", keys: MENUBAR_KEYS[0] },
      { id: "menubar.mnemonic", label: "Open a menu by its underlined letter (hold Alt to see them)", keys: "Alt+F" },
      { id: "menubar.context", label: "Open the context menu on the focused row", keys: "Shift+F10" },
    ],
  });
  const sheet = app.querySelector("dp-cheatsheet");
  sheet.sections = sections;
  sheet.open();
}

class DpApp extends DpElement {
  static shadow = false;

  connected() {
    app = this;
    overlays.palette = openPalette;
    overlays.cheatsheet = openCheatsheet;
    tooltips();
    commands.onRun(({ spec }) => {
      recent.splice(0, recent.length, spec.id, ...recent.filter((id) => id !== spec.id).slice(0, 7));
    });
  }

  render() {
    variant.value; // re-render on a variant change: placement is the variant's
    const place = toolbarPlace();
    const bands = toolbarBands(TOOLBAR_BANDS);
    const selection = selectionModel(() => clearSelection());
    const toolbar = html`<dp-toolbar placement=${place === "modeline" ? "inline" : place} .bands=${bands} .selection=${selection}></dp-toolbar>`;
    return html`
      <div class="frame-menubar">
        <dp-menubar .menus=${menubarModel()} .focusKeys=${MENUBAR_KEYS}></dp-menubar>
        <div class="frame-keyhint" aria-hidden="true">${kbd(MENUBAR_KEYS[0])}<span>menus</span>${kbd("Ctrl+K")}<span>commands</span>${kbd("?")}<span>keys</span></div>
      </div>
      ${place === "top" ? html`<div class="frame-toolbar">${toolbar}</div>` : nothing}
      <div class="frame-body">
        ${leftOpen.value && panels.left.value ? html`<aside class="frame-left" aria-label=${panels.left.value.title}>${panels.left.value.render()}</aside>` : nothing}
        <div class="frame-centre">
          <div class="frame-panes">${repeat(panes.value, (p) => p.id, (pane) => this.pane(pane))}</div>
          ${place === "float" ? html`<div class="frame-float">${toolbar}</div>` : nothing}
          ${bottomOpen.value && panels.bottom.value ? html`<section class="frame-bottom" aria-label=${panels.bottom.value.title}>${panels.bottom.value.render()}</section>` : nothing}
        </div>
      </div>
      <dp-statusbar
        ?verbs=${place === "modeline"}
        .verbs=${place === "modeline" ? this.modelineVerbs(bands, selection) : []}
        .mode=${mode.value}
        .echo=${echo.value}
        .crumbs=${this.crumbs()}
        .right=${this.statusRight()}
      ></dp-statusbar>
      <dp-palette></dp-palette>
      <dp-whichkey ?hidden=${!whichKeyOpen.value} .prefix=${pending.value} .items=${whichKeyOpen.value ? keyItems(pending.value) : []}></dp-whichkey>
      <dp-cheatsheet></dp-cheatsheet>
    `;
  }

  pane(pane) {
    const active = pane.id === activePaneId.value;
    const tab = pane.tabs[pane.active];
    const view = tab ? viewOf(tab) : null;
    const target = pane.follow ? paneFocus.value.get(pane.follow) ?? null : undefined;
    return html`
      <section class="pane" data-pane=${pane.id} ?data-active=${active && panes.value.length > 1} @focusin=${() => !active && activate(pane.id)} @pointerdown=${() => !active && activate(pane.id)}>
        <div class="pane-tabs" role="tablist">
          ${pane.tabs.map(
            (t, i) => html`<button
              role="tab"
              class=${`pane-tab${t.preview ? " preview" : ""}`}
              aria-selected=${i === pane.active ? "true" : "false"}
              tabindex="-1"
              @click=${() => activate(pane.id, i)}
              @dblclick=${() => pinTab(pane.id, i)}
              @auxclick=${(e) => e.button === 1 && closeTab(pane.id, i)}
            >${glyph(kindOf(t).icon)}<span>${kindOf(t).title(t.params)}</span>${t.preview && i === pane.active && active && pane.tabs.length > 1
              ? html`<span class="pane-tab-esc" data-tip="A preview: Escape puts it away">${kbd("Escape")}</span>`
              : nothing}<span class="pane-tab-close" @click=${(e) => (e.stopPropagation(), closeTab(pane.id, i))}>${glyph("close", "Close tab")}</span></button>`,
          )}
          <span class="pane-tabs-fill"></span>
          ${pane.follow ? html`<span class="pane-follow" data-tip="This pane shows what the other pane has focused">${glyph("link")} follows ${panes.value.findIndex((p) => p.id === pane.follow) === 0 ? "left" : "the other"} pane</span>` : nothing}
        </div>
        <div class="pane-body">${view ? view.render({ paneId: pane.id, active, follow: target }) : nothing}</div>
      </section>
    `;
  }

  crumbs() {
    const ctx = context.value;
    const crumbs = [];
    const activity = parseUri(ctx.activity?.uri);
    if (activity) crumbs.push({ label: activity.id ? describe(activity.kind === "steps" ? "project" : activity.kind, activity.id) : activity.kind, uri: ctx.activity.uri });
    const focus = parseUri(ctx.focus);
    if (focus) crumbs.push({ label: describe(focus.kind, focus.id), uri: ctx.focus });
    return crumbs;
  }

  statusRight() {
    const items = [];
    const count = selectionCount.value;
    if (count) items.push(html`<span class="status-count">${count} selected</span>`);
    const busy = running.value;
    const finished = unseen.value;
    if (busy.length || finished) {
      const item = toItem(commands.get("activity.toggle"), context.peek());
      items.push(html`<button class="status-activity" data-tip=${item.label} data-tip-keys=${item.keys} @click=${item.run}>
        ${busy.length ? html`<span class="status-spinner" aria-hidden="true"></span>${busy[0].label}${busy.length > 1 ? ` +${busy.length - 1}` : ""}` : html`${glyph("check")} ${finished} finished`}
      </button>`);
    }
    const theme = activeTheme.value;
    items.push(html`<span class="status-theme" data-tip=${theme.source === "desktop" ? "Following the desktop's Omarchy theme" : theme.source === "browser" ? "Following the browser's light or dark preference" : "Chosen in View ▸ Theme"}>${glyph("palette")} ${theme.name}</span>`);
    return items;
  }

  modelineVerbs(bands, selection) {
    const items = selection ? selection.items : bands.flatMap((b) => b.items);
    return items.filter((item) => item.keys && !item.disabled).slice(0, 7);
  }
}
DpApp.define("dp-app");

adopt(css`
  dp-app {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto 1fr auto;
    height: 100%;
    background: var(--bg);
  }
  dp-app > .frame-menubar { grid-row: 1; display: flex; align-items: center; min-width: 0; }
  dp-app .frame-menubar dp-menubar { flex: 1; min-width: 0; }
  /* The three doors into the keyboard, where the eye looks for menus. Quiet, and gone when tight. */
  dp-app .frame-keyhint {
    display: flex;
    align-items: center;
    gap: 5px;
    padding-inline: 10px;
    color: var(--fg-3);
    font-size: var(--fs-small);
    white-space: nowrap;
    opacity: 0.8;
  }
  dp-app .frame-keyhint .kbd { font-size: 10px; }
  dp-app .frame-keyhint span + .kbd { margin-left: 8px; }
  @media (max-width: 900px) { dp-app .frame-keyhint { display: none; } }
  dp-app > .frame-toolbar { grid-row: 2; }
  dp-app .frame-toolbar {
    border-bottom: var(--rule);
    background: var(--bg-raised);
  }
  dp-app .frame-body {
    display: flex;
    min-height: 0;
    grid-row: 3;
  }
  dp-app .frame-left {
    width: 220px;
    flex: none;
    overflow: auto;
    border-right: var(--rule);
    background: var(--bg-sunken);
  }
  dp-app .frame-centre {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    position: relative;
  }
  dp-app .frame-panes {
    flex: 1;
    min-height: 0;
    display: flex;
  }
  dp-app .frame-bottom {
    height: 34%;
    min-height: 140px;
    border-top: var(--rule);
    overflow: auto;
    background: var(--bg-sunken);
    animation: frame-rise var(--dur-small) var(--ease-enter);
  }
  @keyframes frame-rise { from { translate: 0 12px; opacity: 0.6; } }
  dp-app .frame-float {
    position: absolute;
    left: 50%;
    bottom: 16px;
    translate: -50% 0;
    z-index: 5;
    max-width: calc(100% - 32px);
  }
  dp-app dp-statusbar { grid-row: 4; }

  dp-app .pane {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    border-top: 2px solid transparent;
    transition: border-color var(--dur-micro) linear;
  }
  dp-app .pane + .pane { border-left: var(--rule); }
  dp-app .pane[data-active] { border-top-color: var(--accent); }
  dp-app .pane-tabs {
    display: flex;
    align-items: stretch;
    height: calc(var(--control) + 4px);
    border-bottom: var(--rule);
    background: var(--bg-sunken);
    overflow: hidden;
  }
  dp-app .pane-tab {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 240px;
    padding: 0 6px 0 10px;
    border: 0;
    border-right: var(--rule);
    background: transparent;
    color: var(--fg-2);
    font: inherit;
    white-space: nowrap;
  }
  dp-app .pane-tab span:first-of-type { overflow: hidden; text-overflow: ellipsis; }
  dp-app .pane-tab.preview span:first-of-type { font-style: italic; }
  dp-app .pane-tab[aria-selected="true"] {
    background: var(--bg);
    color: var(--fg);
    box-shadow: inset 0 -1px 0 var(--bg);
  }
  /* The hint sits where the eye already goes to close a tab: Escape does the same to a preview. */
  dp-app .pane-tab-esc .kbd { font-size: 10px; opacity: 0.75; }
  dp-app .pane-tab-esc .kbd kbd { padding: 0 3px; min-width: 0; }
  dp-app .pane-tab-close { display: inline-flex; opacity: 0; border-radius: var(--radius); }
  dp-app .pane-tab:hover .pane-tab-close, dp-app .pane-tab[aria-selected="true"] .pane-tab-close { opacity: 0.7; }
  dp-app .pane-tab-close:hover { opacity: 1; background: var(--bg-hover); }
  dp-app .pane-tab-close .glyph { width: 13px; height: 13px; }
  dp-app .pane-tabs-fill { flex: 1; }
  dp-app .pane-follow {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 0 10px;
    color: var(--accent);
    font-size: var(--fs-small);
  }
  dp-app .pane-body { flex: 1; min-height: 0; display: flex; position: relative; }

  dp-app .status-activity {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    padding: 0 6px;
    border-radius: var(--radius);
  }
  dp-app .status-activity:hover { background: var(--bg-hover); }
  dp-app .status-spinner {
    width: 11px;
    height: 11px;
    border-radius: 50%;
    border: 2px solid var(--tone-busy);
    border-right-color: transparent;
    animation: frame-spin 0.9s linear infinite;
  }
  @keyframes frame-spin { to { rotate: 1turn; } }
  dp-app .status-theme { display: inline-flex; align-items: center; gap: 4px; color: var(--fg-3); }
  dp-app .status-count { color: var(--accent); }

  :root[data-variant="atelier"] dp-app .frame-left { background: var(--bg); }
  :root[data-variant="atelier"] dp-app .pane-tabs { background: var(--bg); }
  :root[data-variant="atelier"] dp-app .pane-tab { border-right: 0; border-radius: var(--radius) var(--radius) 0 0; }
  :root[data-variant="modeline"] dp-app .pane-tab { text-transform: lowercase; }
  /* Room to scroll the last rows out from under the floating toolbar. */
  :root[data-variant="atelier"] dp-app .pane-body dp-grid { padding-bottom: 72px; }
`);
