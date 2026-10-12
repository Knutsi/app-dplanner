// The workspace: views, tabs and panes — doing more than one thing at once.
//
// A *view* is a kind a feature registers ("steps", "step", "activity"). A *tab* is a view with
// its parameters. A *pane* holds tabs and shows one. Every pane is a live view of the one
// store, never a copy, so two panes on the same project can never disagree; each keeps its own
// focus, selection and scroll. A pane can *follow* another: its view then shows whatever the
// other pane has focused — read one thing while working on another.
//
// Exactly one pane is active (accent edge). The context is always the active pane's: switching
// panes republishes its focus and selection, so menus and toolbar follow you across.

import { signal, computed, batch } from "../engine/signals.js";
import { context, setActivity, setFocus, setSelection } from "./context.js";

const kinds = new Map(); // kind -> { title(params), icon, uri(params), create(params, tab) }
const describers = new Map(); // entity kind -> (id) => label

export function registerView(kind, spec) {
  if (kinds.has(kind)) throw new Error(`view ${kind} registered twice`);
  kinds.set(kind, spec);
}

// How the status bar, the palette chip and a tab name an entity: "S12 Step table as a treegrid".
export function registerDescriber(kind, describe) {
  describers.set(kind, describe);
}
export function describe(kind, id) {
  return describers.get(kind)?.(id) ?? `${kind} ${id}`;
}

let nextId = 1;
export const panes = signal([]); // [{ id, tabs: [{ id, kind, params, preview }], active, follow }]
export const activePaneId = signal(null);
export const paneFocus = signal(new Map()); // pane id -> the focused entity URI in that pane

const instances = new Map(); // tab id -> the live view object, kept across tab switches

export function viewOf(tab) {
  if (!instances.has(tab.id)) instances.set(tab.id, kinds.get(tab.kind).create(tab.params, tab));
  return instances.get(tab.id);
}
export const kindOf = (tab) => kinds.get(tab.kind);
export const activePane = computed(() => panes.value.find((p) => p.id === activePaneId.value) ?? null);
export const activeTab = computed(() => {
  const pane = activePane.value;
  return pane ? pane.tabs[pane.active] ?? null : null;
});
export const activeView = () => (activeTab.peek() ? viewOf(activeTab.peek()) : null);

function replacePane(id, change) {
  panes.value = panes.peek().map((p) => (p.id === id ? change(p) : p));
}

// Opens a view. A preview tab (single click) is replaced by the next preview; pinning it (a
// double click, or any edit) keeps it — so browsing does not leave a trail of tabs.
export function openTab(kind, params, { paneId = activePaneId.peek(), preview = false } = {}) {
  const pane = panes.peek().find((p) => p.id === paneId);
  const same = pane.tabs.findIndex((t) => t.kind === kind && JSON.stringify(t.params) === JSON.stringify(params));
  if (same >= 0) return activate(paneId, same);
  const tab = { id: nextId++, kind, params, preview };
  replacePane(paneId, (p) => {
    const at = preview ? p.tabs.findIndex((t) => t.preview) : -1;
    if (at >= 0) instances.delete(p.tabs[at].id);
    const tabs = at >= 0 ? p.tabs.with(at, tab) : [...p.tabs, tab];
    return { ...p, tabs, active: at >= 0 ? at : tabs.length - 1 };
  });
  activate(paneId, panes.peek().find((p) => p.id === paneId).active);
}

export function pinTab(paneId, index) {
  replacePane(paneId, (p) => ({ ...p, tabs: p.tabs.map((t, i) => (i === index ? { ...t, preview: false } : t)) }));
}

const closed = []; // for Reopen Closed Tab

export function closeTab(paneId = activePaneId.peek(), index = panes.peek().find((p) => p.id === paneId)?.active) {
  const pane = panes.peek().find((p) => p.id === paneId);
  if (!pane || !pane.tabs[index]) return;
  closed.push({ kind: pane.tabs[index].kind, params: pane.tabs[index].params });
  instances.delete(pane.tabs[index].id);
  const tabs = pane.tabs.filter((_, i) => i !== index);
  if (!tabs.length && panes.peek().length > 1) return closePane(paneId);
  replacePane(paneId, (p) => ({ ...p, tabs, active: Math.min(p.active, tabs.length - 1) }));
  activate(paneId, Math.min(index, tabs.length - 1));
}

export function reopenTab() {
  const last = closed.pop();
  if (last) openTab(last.kind, last.params);
  return !!last;
}

export function activate(paneId, index = null) {
  batch(() => {
    if (index !== null) replacePane(paneId, (p) => ({ ...p, active: index }));
    activePaneId.value = paneId;
    const tab = activeTab.peek();
    if (!tab) return;
    setActivity(kinds.get(tab.kind).uri(tab.params));
    viewOf(tab).publish?.(); // the context is the active pane's focus and selection
  });
}

// Ctrl+\ — a second pane on the same view, live on the same data. With `follow`, the new pane
// shows the detail of whatever the first pane has focused.
export function split({ kind = null, params = null, follow = false } = {}) {
  const from = activePane.peek();
  const source = from?.tabs[from.active];
  const tab = { id: nextId++, kind: kind ?? source.kind, params: params ?? source.params, preview: false };
  const pane = { id: nextId++, tabs: [tab], active: 0, follow: follow ? from.id : null };
  panes.value = [...panes.peek(), pane];
  activate(pane.id, 0);
  queueMicrotask(() => viewOf(tab).focus?.()); // the keyboard goes where the new pane is
  return pane.id;
}

export function closePane(paneId = activePaneId.peek()) {
  if (panes.peek().length < 2) return;
  const index = panes.peek().findIndex((p) => p.id === paneId);
  for (const tab of panes.peek()[index].tabs) instances.delete(tab.id);
  panes.value = panes.peek().filter((p) => p.id !== paneId).map((p) => (p.follow === paneId ? { ...p, follow: null } : p));
  const neighbour = panes.peek()[Math.max(0, index - 1)];
  activate(neighbour.id); // closing the active pane focuses its neighbour, never <body>
}

export function toggleFollow(paneId = activePaneId.peek()) {
  const others = panes.peek().filter((p) => p.id !== paneId);
  if (!others.length) return;
  replacePane(paneId, (p) => ({ ...p, follow: p.follow ? null : others[0].id }));
}

// A view reports its focus and selection here; the context only hears it from the active pane.
export function report(paneId, { focus, selection }) {
  if (focus !== undefined) {
    const next = new Map(paneFocus.peek());
    next.set(paneId, focus);
    paneFocus.value = next;
  }
  if (paneId !== activePaneId.peek()) return;
  if (focus !== undefined) setFocus(focus);
  if (selection !== undefined) setSelection(selection);
}

export function clearSelection() {
  activeView()?.clearSelection?.();
  if (context.peek().selection.length) setSelection([]);
}

// Panels beside the panes (a feature fills an area; the frame decides how to show it), and the
// overlays a frame provides — the desktop's palette and cheat sheet, the touch frame's sheets.
export const panels = { left: signal(null), bottom: signal(null) }; // { title, render() }
export const leftOpen = signal(true);
export const bottomOpen = signal(false);
export const setPanel = (area, panel) => (panels[area].value = panel);
export const overlays = { palette: () => {}, cheatsheet: () => {} };

export function startWorkspace(kind, params) {
  const tab = { id: nextId++, kind, params, preview: false };
  const pane = { id: nextId++, tabs: [tab], active: 0, follow: null };
  panes.value = [pane];
  activate(pane.id, 0);
}
