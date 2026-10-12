// The command registry: every verb exists once, here, and every surface is a view of it — the
// menubar, a context menu, the toolbar, the selection bar, the palette, the which-key panel,
// the cheat sheet, the touch action bar. DPlanner's ActionSpec, in the browser. A feature
// never builds a button that runs code; it registers a command and says where it shows.
//
//   id        "step.rename"
//   label     "Rename…"            "…" when the verb asks for more before it acts
//   icon      a glyph key          "edit"
//   menu      "Step"               and group, from MENUS below; order ranks within the group
//   submenu   "Status"             items sharing a submenu title gather under it
//   keys      ["F2", "r"]          the first is the one shown; chords work everywhere, bare keys
//                                  and sequences ("g p") only on a navigable surface
//   for       "step"               the kind of entity it acts on (scopes palette + context menu)
//   toolbar   "edit"               the toolbar band it sits in, if any
//   bulk      true                 offered in the selection bar
//   state(ctx) → { visible, enabled, reason, label, checked }   all optional
//   run(ctx, { source }) → an undo function, or nothing
//   items(ctx) → [{ id, label, checked, run }]   a submenu filled when it opens (themes)

import { signal } from "../engine/signals.js";

export const MENUS = {
  File: ["project", "export", "window"],
  Edit: ["history", "clipboard", "select"],
  View: ["palette", "panes", "look", "theme"],
  Go: ["navigate", "history"],
  Step: ["edit", "status", "link", "agent"],
  Help: ["keys", "about"],
};

const DEFAULT_STATE = { visible: true, enabled: true, reason: null, label: null, checked: null };

export class Commands {
  #specs = new Map();
  #listeners = new Set();
  history = signal([]); // undo functions with labels, newest last
  future = signal([]);

  register(spec) {
    if (this.#specs.has(spec.id)) throw new Error(`command ${spec.id} registered twice`);
    if (spec.menu && !MENUS[spec.menu]?.includes(spec.group)) throw new Error(`${spec.id}: no group ${spec.menu} ▸ ${spec.group}`);
    this.#specs.set(spec.id, { order: 50, keys: [], palette: true, ...spec });
  }

  get(id) {
    return this.#specs.get(id);
  }

  all() {
    return [...this.#specs.values()];
  }

  state(spec, ctx) {
    const s = { ...DEFAULT_STATE, ...(spec.state?.(ctx) ?? {}) };
    s.label ??= spec.label;
    return s;
  }

  // Runs a command if the context allows it; a refusal is returned, never thrown, so the
  // caller can say why where the person is looking (the modeline, for a key).
  run(id, ctx, source = "pointer") {
    const spec = this.#specs.get(id);
    if (!spec) return { ran: false, reason: `No command ${id}` };
    const state = this.state(spec, ctx);
    if (!state.visible || !state.enabled) return { ran: false, spec, reason: state.reason ?? `${state.label} is not available here` };
    const undo = spec.run(ctx, { source });
    if (typeof undo === "function") {
      this.history.value = [...this.history.peek(), { label: state.label, undo, redo: () => spec.run(ctx, { source: "redo" }) }];
      this.future.value = [];
    }
    for (const listener of this.#listeners) listener({ spec, state, source });
    return { ran: true, spec };
  }

  undo() {
    const last = this.history.peek().at(-1);
    if (!last) return null;
    this.history.value = this.history.peek().slice(0, -1);
    last.undo();
    this.future.value = [...this.future.peek(), last];
    return last.label;
  }

  redo() {
    const next = this.future.peek().at(-1);
    if (!next) return null;
    this.future.value = this.future.peek().slice(0, -1);
    const undo = next.redo();
    this.history.value = [...this.history.peek(), { ...next, undo: undo ?? next.undo }];
    return next.label;
  }

  // Every surface that wants to echo or teach ("you ran Rename — the key is F2") listens here.
  onRun(listener) {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  // The menubar's model: menus → groups → items (and submenus), visible-ness resolved.
  menu(name, ctx) {
    const groups = [];
    for (const group of MENUS[name]) {
      const specs = this.all()
        .filter((s) => s.menu === name && s.group === group)
        .sort((a, b) => a.order - b.order);
      const items = [];
      const submenus = new Map();
      for (const spec of specs) {
        const state = this.state(spec, ctx);
        if (!state.visible) continue;
        const item = { spec, state };
        if (!spec.submenu) items.push(item);
        else {
          if (!submenus.has(spec.submenu)) items.push({ submenu: spec.submenu, items: submenus.set(spec.submenu, []).get(spec.submenu) });
          submenus.get(spec.submenu).push(item);
        }
      }
      if (items.length) groups.push(items);
    }
    return groups;
  }
}

export const commands = new Commands();
