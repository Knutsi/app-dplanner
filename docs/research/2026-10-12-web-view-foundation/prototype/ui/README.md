# ui/ — the design system

The components, tokens, themes and glyphs. **Nothing in `ui/` knows DPlanner**: no steps, no
commands registry, no store. A component takes plain data and calls plain callbacks, so it can be
shown on a test page, tested alone, and reused by a feature that did not exist when it was
written. What a menu item *does* is the shell's business (`shell/commands.js`); how it *looks and
behaves* is this folder's.

## Layers (enforced by `tests/layers.test.mjs`)

```
engine/   signals.js template.js element.js        imports nothing
ui/       tokens.css base.css + one file per component   imports engine/ only
shell/    context commands keyboard surfaces workspace activity, frame.js (desktop) touch.js   imports engine/, ui/
data/     store.js (bulk-loaded plan) sample.js    imports engine/ only
features/<name>/                                    imports engine/, ui/, shell/, data/ — never another feature
app.js, desktop.html, mobile.html                   the composition root: the only place features meet
```

## Conventions

- **One component, one file**, its CSS beside its code in a `css```` sheet adopted with
  `adopt()` from `style.js`. Element names are `dp-*`; classes inside a component are scoped
  under its element name (`dp-menu .item`), so two components never fight over a class.
- **Light DOM.** Components render into themselves (`static shadow = false`). Variants and themes
  are page-wide concerns, a table must take part in find-in-page and text selection, and light
  DOM lets one token change reach everything. Shadow DOM stays available for a leaf widget that
  truly needs isolation.
- **Colours, sizes, radii, fonts and durations come from tokens** (`tokens.css`). A literal is a bug.
- **Data in, callbacks out.** Properties take plain objects; a component reports with
  `this.emit("dp-…", detail)` or calls a function it was handed. It never imports the shell.
- **Motion follows `motion.js`'s rules**: state commits first, animation never gates input, and a
  surface opened from the keyboard opens without animation.

## The shared item shape

Menus, toolbars, the selection bar, the palette, the which-key panel and the touch action bar all
take the same item, which the shell builds from a command:

```js
{
  id: "step.rename",
  label: "Rename…",
  icon: "edit",               // a glyph key, or null
  keys: "F2",                 // the binding shown, canonical notation (keys.js), or null
  disabled: false,
  reason: null,               // why it is disabled — shown in tooltip, palette row, menu
  checked: null,              // true/false for toggles, null for plain verbs
  run: () => {},              // called on activation
  submenu: null,              // or groups: [[item, …], …] for one nested level
  detail: null,               // palette only: a second line ("Step ▸ Status")
}
```

A **groups** value is an array of arrays of items; separators fall between groups.

## Components

| Element / export | File | Takes | Says |
|---|---|---|---|
| `kbd(binding, { plain })`, `keyText`, `chordOf` | `keys.js` | canonical bindings ("Ctrl+K", "g p") | keycaps, or plain words in menus |
| `glyph(name, label?)` | `glyph.js` | a DPlanner glyph key | an `<svg><use>` from one sprite |
| `statusMark`, `ownerChip`, `estimate`, `relativeTime`, `progressBar` | `marks.js` | a status word, an owner, numbers | small marks coded by colour *and* shape |
| `enter`, `flip`, `flash`, `swap`, `still` | `motion.js` | elements | motion that carries information, never gates input |
| `themeChoice`, `activeTheme`, `startThemes` | `theme.js` | Omarchy colors.toml objects | `--om-*` on `<html>`, followed live from `/api/theme` |
| `variant`, `reducedMotion` | `look.js` | per-viewer preferences | `data-variant`, `data-motion` on `<html>` |
| `<dp-menu>` | `menu.js` | `.groups`; `open({ x, y } \| { anchor, side }, { via, focus, returnTo })` | `dp-close` `{ reason }` |
| `<dp-menubar>` | `menu.js` | `.menus = [{ name, groups: () => groups }]` (computed on open) | — |
| `contextMenu(event, groups)` | `menu.js` | a pointer or key event | — |
| `<dp-toolbar>` | `toolbar.js` | `.bands = [{ name, items }]`, `.selection = { count, noun, items, clear } \| null`, `placement` top/float/inline, `.via` | — |
| `tooltips()` | `tooltip.js` | installs the one tooltip for every `[data-tip]` (+ `data-tip-keys`) | — |
| `<dp-grid>` | `grid.js` | `.columns`, `.rows`, `.selected`, `.focusKey`, `.sort`, `.changed` | `dp-focus`, `dp-select`, `dp-toggle`, `dp-open`, `dp-sort`, `dp-context` |
| `<dp-palette>` | `palette.js` | `open({ items, scope, placeholder, onWiden })` | — |
| `<dp-whichkey>`, `<dp-cheatsheet>` | `keyhelp.js` | `.prefix` + `.items` / `.sections`, `open()` | — |
| `<dp-statusbar>` | `statusbar.js` | `.mode`, `.echo`, `.crumbs`, `.right`, `verbs` + `.verbs` | — |
| `toast(message, { undo, tone, duration })` | `toast.js` | a message, an optional undo | — |
| `<dp-sheet>`, `<dp-actionbar>` | `sheet.js` | groups / items, for touch; a submenu item opens a sheet | — |

Items in palettes and sheets need a unique `id` (rows are keyed by it). A command that means
nothing on touch (Peek, Open — a tap opens) says `touch: false` and the touch surfaces drop it.
