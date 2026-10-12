// Commands as each surface wants them. Every function here reads the registry and the
// context and returns ui/'s plain item shape — so the menubar, a context menu, the toolbar,
// the selection bar, the palette, the which-key panel and the touch bar can never disagree
// about what a verb is called, which key runs it, or why it is off.

import { commands, MENUS } from "./commands.js";
import { context, parseUri } from "./context.js";

export function toItem(spec, ctx, state = commands.state(spec, ctx)) {
  return {
    id: spec.id,
    label: state.label,
    icon: spec.icon ?? null,
    keys: spec.keys[0] ?? null,
    disabled: !state.enabled,
    reason: state.enabled ? null : state.reason,
    checked: state.checked,
    detail: spec.menu ? [spec.menu, spec.submenu].filter(Boolean).join(" ▸ ") : null,
    run: () => commands.run(spec.id, context.peek(), "pointer"),
    submenu: spec.items ? [spec.items(ctx).map((child) => ({ icon: null, keys: null, disabled: false, reason: null, ...child }))] : null,
  };
}

// The menubar: menus never come and go, and an item that does not apply is disabled, not hidden.
export function menuGroups(name) {
  const ctx = context.peek();
  return commands.menu(name, ctx).map((group) =>
    group.map((entry) =>
      entry.submenu
        ? { id: entry.submenu, label: entry.submenu, icon: null, keys: null, disabled: false, submenu: [entry.items.map(({ spec, state }) => toItem(spec, ctx, state))] }
        : toItem(entry.spec, ctx, entry.state),
    ),
  );
}

export const menubarModel = () => Object.keys(MENUS).map((name) => ({ name, groups: () => menuGroups(name) }));

// Plain verbs stay as they are; verbs that share a submenu title gather under one item.
function gather(specs, ctx) {
  const out = [];
  const subs = new Map();
  for (const [spec, state] of specs) {
    const item = toItem(spec, ctx, state);
    if (!spec.submenu) out.push(item);
    else if (subs.has(spec.submenu)) subs.get(spec.submenu).push(item);
    else {
      const children = [item];
      subs.set(spec.submenu, children);
      out.push({ id: spec.submenu, label: spec.submenu, icon: spec.icon ?? null, keys: null, disabled: false, reason: null, checked: null, submenu: [children] });
    }
  }
  return out;
}

const withState = (specs, ctx) => specs.map((spec) => [spec, commands.state(spec, ctx)]);

// A context menu: the complete verb list for what was clicked, in the menubar's group order,
// with what does not apply *hidden* — the menu is about this thing, not about everything.
// `touch` drops verbs that have no meaning without a pointer and keyboard (spec.touch === false).
export function contextGroups(kind, { touch = false } = {}) {
  const ctx = context.peek();
  const groups = [];
  for (const [menu, names] of Object.entries(MENUS))
    for (const group of names) {
      const specs = commands
        .all()
        .filter((s) => s.for === kind && s.menu === menu && s.group === group && !(touch && s.touch === false))
        .sort((a, b) => a.order - b.order);
      const items = gather(withState(specs, ctx).filter(([, state]) => state.visible && state.enabled), ctx);
      if (items.length) groups.push(items);
    }
  return groups;
}

// The toolbar: commands that name a band, in band order, always visible, dimmed when off.
export function toolbarBands(order) {
  const ctx = context.value; // read tracked: the toolbar re-renders when the context moves
  return order
    .map((name) => ({
      name,
      items: gather(
        withState(
          commands
            .all()
            .filter((s) => s.toolbar === name)
            .sort((a, b) => a.order - b.order),
          ctx,
        ),
        ctx,
      ),
    }))
    .filter((band) => band.items.length);
}

// The selection bar: the bulk verbs for the kind that is selected.
export function selectionModel(clear, { touch = false } = {}) {
  const ctx = context.value;
  if (!ctx.selection.length) return null;
  const kinds = new Set(ctx.selection.map((u) => parseUri(u)?.kind));
  const kind = kinds.size === 1 ? [...kinds][0] : "item";
  return {
    count: ctx.selection.length,
    noun: kind,
    items: gather(
      withState(
        commands
          .all()
          .filter((s) => s.bulk && s.for === kind && !(touch && s.touch === false))
          .sort((a, b) => a.order - b.order),
        ctx,
      ).filter(([, state]) => state.visible && state.enabled),
      ctx,
    ),
    clear,
  };
}

// The palette: everything runnable, the selection's own verbs first, recents before both.
export function paletteItems(scopeKind, recent = []) {
  const ctx = context.peek();
  const all = commands
    .all()
    .filter((s) => s.palette && !s.items)
    .filter((s) => !scopeKind || s.for === scopeKind)
    .map((spec) => [spec, commands.state(spec, ctx)])
    .filter(([, state]) => state.visible)
    .map(([spec, state]) => toItem(spec, ctx, state));
  const rank = (item) => (recent.includes(item.id) ? 0 - (recent.length - recent.indexOf(item.id)) : 1);
  return all.sort((a, b) => rank(a) - rank(b));
}

// Keys for the which-key panel and the cheat sheet.
export function keyItems(prefix = null) {
  const ctx = context.peek();
  return commands
    .all()
    .flatMap((spec) => spec.keys.map((keys) => ({ spec, keys })))
    .filter(({ keys }) => (prefix ? keys.startsWith(`${prefix} `) : true))
    .map(({ spec, keys }) => ({ ...toItem(spec, ctx), keys }));
}
