// The context: what the person is looking at, what has focus and what is selected, as URIs —
// the same scopes and scheme as DPlanner's framework/context.py, plus the one thing a web
// table adds: focus and selection are separate (Gmail, Linear). Focus is the row the arrows
// are on; the selection is an explicit set. A verb acts on the selection when there is one,
// else on the focused thing — so arrowing through a list never reshapes the toolbar, and
// selecting does.
//
// Each scope is replaced whole. Anything that depends on the context — a menu's enabled
// state, the toolbar's verbs, the palette's scope — is a computed over this one signal.

import { signal, computed } from "../engine/signals.js";

export const entityUri = (kind, id) => `app://entity/${kind}/${id}`;
export const activityUri = (kind, target) => `app://activity/${kind}${target ? `/${target}` : ""}`;

export function parseUri(uri) {
  const m = /^app:\/\/(entity|activity)\/([^/]+)(?:\/(.+))?$/.exec(uri ?? "");
  return m ? { scope: m[1], kind: m[2], id: m[3] ?? null } : null;
}

const EMPTY = Object.freeze({ activity: null, focus: null, selection: Object.freeze([]) });

export const context = signal(EMPTY);

// Set by the active view when it gains focus: its URI and the entity it shows.
export function setActivity(uri, entity = null) {
  context.value = { ...context.peek(), activity: { uri, entity }, focus: null, selection: [] };
}

export function setFocus(uri) {
  if (context.peek().focus !== uri) context.value = { ...context.peek(), focus: uri };
}

export function setSelection(uris) {
  const now = context.peek().selection;
  if (now.length === uris.length && now.every((u, i) => u === uris[i])) return;
  context.value = { ...context.peek(), selection: Object.freeze([...uris]) };
}

// What a verb acts on: the selection if there is one, else the focused entity — of `kind`.
export function targets(ctx, kind) {
  const pick = (uris) => uris.map(parseUri).filter((p) => p?.scope === "entity" && p.kind === kind).map((p) => p.id);
  const chosen = pick(ctx.selection);
  return chosen.length ? chosen : pick(ctx.focus ? [ctx.focus] : []);
}

export const selectionCount = computed(() => context.value.selection.length);
