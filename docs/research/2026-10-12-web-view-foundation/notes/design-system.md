# The design system: what it is, the rules, and why

> A snapshot from 12 October 2026. The prototype in `../prototype/` is the system in code; this note
> is the system in words, and `interaction-patterns.md` is the research it rests on (its rule
> numbers are cited as **R1**–**R51**).

## Summary

- **One command registry, every surface a view of it.** The menubar, a context menu, the toolbar,
  the selection bar, the palette, the which-key panel, the `?` sheet and the touch action bar are
  all built from the same registered commands (`shell/commands.js`) — DPlanner's `ActionSpec`, in
  the browser. A feature never builds a button that runs code.
- **The context is URIs** (`app://entity/step/S12`, the scheme `framework/context.py` uses), in
  three scopes plus one the web adds: focus is kept apart from selection. Arrowing through a table
  never reshapes anything; selecting does — the toolbar becomes the selection bar.
- **Keyboard first without Vim's trap.** "Normal mode" is not entered: it is wherever focus is on
  a navigable surface and not in a text field. The modeline always names the mode and the way out;
  Escape steps exactly one level outward.
- **Three variants, one component set:** *Ledger* (classic workbench), *Modeline* (terminal-native,
  keyboard first) and *Atelier* (calm, layered). A variant is ~30 lines of tokens plus a toolbar
  placement — not a fork of the components.
- **Omarchy themes are the theme format.** Any `colors.toml` drives every colour through
  `color-mix()`; "Automatic" follows the desktop live (`/api/theme`) or, served from CI, the
  browser's light/dark preference.
- **Motion carries information only**: where something went, what changed under you, where a
  surface came from. Nothing done hundreds of times a day animates; nothing ever waits for an
  animation.
- **Touch is a separate UI** on the same commands, context and store — a screen stack, long-press
  to select, a bottom action bar and sheets — not the desktop squeezed.

## 1. Principles

1. **Learnable, not explained.** No explainer text in the chrome. The system teaches by showing the
   key wherever a verb appears (menu, tooltip, palette, modeline echo), and by naming every mode's
   way out. A person may have to learn something; they never have to guess.
2. **The visual cortex first.** Status is coded by colour *and* shape (only the two states that
   need a person — done and blocked — are filled). Glyphs are DPlanner's Tabler set under its own
   keys, so a verb wears the same picture in the window and the web.
3. **Position is meaning.** Top-level menus never come and go (R5); toolbar bands never move; the
   selection bar takes the toolbar's slot at the toolbar's height. What changes is *in place*.
4. **Dense, aligned, quiet.** 24 px rows (Ledger), tabular numerals right-aligned, one accent
   used sparingly, hairlines over boxes, one primary per surface.
5. **The surfaces cannot drift.** Whatever the desktop can do, touch can do, because both read the
   one registry — the rule DPlanner's CLI and GUI already live by.

## 2. Variants

| | Ledger | Modeline | Atelier |
|---|---|---|---|
| For | daily work at a desk — the default | keyboard power users, Omarchy natives | readers: reviews, stakeholders, the report site |
| Type | Inter / system sans 13 px | JetBrains Mono 12.5 px everywhere | sans 13.5 px, step titles in the prose serif (EB Garamond stack) |
| Rows | 24 px, hairline grid | 22 px, no grid lines | 30 px, no grid lines |
| Shape | radius 4 / 6 | square, hard offset shadow | radius 7 / 10, soft lift |
| Toolbar | a strip under the menubar | none: the verbs live in the modeline with their keys | a floating pill over the work |

**Recommendation: ship Ledger as the default and keep the other two.** They cost ~30 lines of
tokens each and no component code, and they answer different readers: Atelier suits the
read-only report site's audience (people outside development, per the 2026-10-11 timeline note),
Modeline the person who lives in a terminal. Shape changes that a token cannot express — where the
toolbar sits — are one switch in the frame (`--toolbar-place`).

## 3. Tokens

Three layers, and a component reads only the last (`ui/tokens.css`):

1. **`--om-*`** — a theme's raw colours, exactly the keys of an Omarchy `colors.toml`.
2. **Roles** — `--bg`, `--bg-sunken/raised/overlay`, `--line(-strong)`, `--fg`, `--fg-2/3`,
   `--accent(-hover/-wash)`, `--sel-bg/fg`, `--st-*` (status), `--tone-*`, `--changed` —
   derived with `color-mix()` using the same ramps as DPlanner's `theme/omarchy.py`.
3. **Variant** — type, sizes, shape, density and toolbar placement.

Motion tokens are shared: `--dur-micro` 100 ms, `--dur-small` 150 ms, `--dur-layout` 220 ms,
`--dur-changed` 1.2 s; `--ease-enter` `cubic-bezier(0,0,0,1)`, `--ease-exit`
`cubic-bezier(0.3,0,1,1)`, `--ease-move` `cubic-bezier(0.2,0,0,1)` (R32–R33).

**One deliberate difference from the Qt app:** status colours come from the theme's own ANSI hues
(mixed 10–30 % toward the text colour so a dim blue still reads), where the Qt app uses fixed
tints. In an Omarchy theme the fixed tints clash; the theme's own green and red do not.

## 4. Context and commands

- A command: `{ id, label, icon, menu, group, submenu, order, keys, for, toolbar, bulk, touch,
  state(ctx) → { visible, enabled, reason, label, checked }, run(ctx) → undo }`.
- `state` returns a *reason* when it says no; the reason shows in the tooltip, the palette row, the
  menu item's description and the modeline when the key is pressed (R2). "Select or focus a step
  first", not a silent grey.
- **Menubar items disable; context-menu items hide** (R5–R6). The menubar is a map of everything
  the app can do; a context menu is about the thing under the pointer.
- **The target rule:** a verb acts on the selection if there is one, else on the focused entity
  (`targets(ctx, kind)`), and its label says so: "Copy 3 Links", "Run Agents on 2 Steps".
- **The selection bar** (the pattern from your other application): a non-empty selection replaces
  the toolbar in its slot — `× · N steps selected · bulk verbs` — with verbs that share a submenu
  gathered under one button (Status ▸, Assign To ▸). It clears on ×, Escape, or an empty
  selection, and the swap is a 100 ms crossfade, instant from the keyboard (R13a–d).
- Menus compute their items when they open, so a context change while a menu is open cannot
  reshape it under the pointer (R3).

## 5. The keyboard model

| Mode | When | Shown as | Way out |
|---|---|---|---|
| NAV | focus on a `data-nav` surface (the table, a list) | accent chip | — (home) |
| EDIT | focus in a text field | busy-blue chip | "Esc leaves the field" |
| `g…` | a prefix typed | amber chip; which-key after 400 ms | "Esc cancels" — never a silent timeout |
| transient (e.g. MOVE) | a verb that needs more input | accent-filled chip | named by the verb |

- **Chords** (Ctrl+K, F2, Ctrl+\\) work everywhere except the few a text field owns.
- **Bare keys and sequences** (`x`, `s d`, `g p`) only act on a focused navigable surface — WCAG
  2.1.4's "active only on focus" — and View ▸ Single-Key Shortcuts turns them off (R20–R25).
- **Escape** steps one level out: prefix → transient mode → field → selection → preview tab.
- **The menubar's keys are shown, not assumed:** a quiet strip at the menubar's right end reads
  `Alt M menus · Ctrl K commands · ? keys`, and the `?` sheet lists the menu keys too. Alt+M is
  first because on Omarchy the desktop or the browser can take F10 before the page sees it; F10
  still works where it gets through, and Alt + a menu's underlined letter opens that menu.
- **Self-teaching:** the modeline echoes every command with its key however it ran — a mouse user
  who clicks Peek sees "Peek · Space". Holding Ctrl for 600 ms puts chord badges on the toolbar.
  `?` opens the sheet, with the focused thing's own verbs first.
- **Bindings in the prototype:** `j/k` move, `x` select, Space peek, Enter open, `s` + `n i r m d b`
  status, `a` + `c x k` assign, `y` copy link, `R` run agent, `g p` projects, `g a` activity,
  Alt+M menu bar, Ctrl+K palette, Ctrl+\\ split, Ctrl+Shift+\\ split following focus, Ctrl+J activity, Alt+W close tab.

## 6. Doing more than one thing at once

- **Panes are live views of one store, never copies** — two panes on one project cannot disagree.
  Each keeps its own focus, selection and scroll; the context is always the active pane's (R42–R44).
- **Follow:** a pane can follow another's focus — read a step's detail on the right while you work
  through the table on the left (Ctrl+Shift+\\).
- **Peek** (Space) shows the focused step beside the table and follows the arrows (R47).
- **Preview tabs:** a single click (or Enter in the table) opens a tab that the next one replaces; a
  double click pins it (R46). Escape puts a preview away — the last rung of the Escape ladder — and
  the active preview wears a small `Esc` keycap beside its ×, so the way out is on the tab itself.
- **Background work** (Run Agent) reports on the object (its status changes) and in a status-bar
  item that opens the Activity panel; a toast only when you started it and it ran long enough
  that you will have moved on (R48). When the agent writes its result, the row washes once in
  every pane that shows it — the "what changed" highlight is how another writer's change is seen.

## 7. Motion

Allowed, each because it says something:

| Motion | Says | Duration |
|---|---|---|
| a menu/popover scaling out of its trigger (pointer only) | where it came from | 150 ms |
| rows travelling to their new places on sort (FLIP) | where they went | 220 ms |
| the changed wash on rows another writer touched | what changed under you | 1.2 s fade |
| toolbar ↔ selection-bar crossfade (pointer only) | the same slot changed role | 100 ms |
| the peek and the bottom panel rising | where it lives | 150 ms |
| a touch screen pushing in from the right / popping from the left | where you went | 220 ms |
| a theme change crossfading (View Transitions) | everything changed at once | browser default |

Never animated: keyboard-opened menus, the palette, selection, focus moves, key repeat. State
commits first; every animation is interruptible; `prefers-reduced-motion` and View ▸ Reduce Motion
zero the duration tokens.

## 8. Theming and Omarchy

- A theme is a `colors.toml` object; DPlanner's own Dark and Light are written in the same shape,
  and the 22 stock Omarchy themes are generated from `/usr/share/omarchy/themes`
  (`tools/import-assets.mjs`).
- **Automatic** follows, in order: what a local DPlanner serves at `/api/theme` (the Omarchy theme
  the desktop wears now, polled every 2 s with an ETag, so an unchanged theme costs a 304) — then
  the browser's light/dark preference. A page served from CI has no `/api/theme` and lands on the
  second with no configuration.
- A person can pick any theme (View ▸ Theme, or type "theme" in the palette); the choice is a
  per-viewer preference in `localStorage`.

## 9. Touch

A separate frame (`shell/touch.js`), chosen at load — not a breakpoint:

- a stack of screens with a back button; tabs for Steps, Projects, Activity;
- 56 px two-line rows; a tap opens; a **long press (450 ms, 8 px slop) starts selecting**, and from
  then on a tap toggles;
- the selection bar takes the app bar's place; the bulk verbs fill the **bottom action bar**
  (≤ 5, the rest under More); a verb with a submenu opens a **sheet** — the context menu's touch
  form;
- verbs that mean nothing on touch (Peek, Open) say `touch: false`.

**Choosing the frame:** `(pointer: coarse) and (hover: none)` with a narrow viewport → touch; a
link in each frame switches to the other, remembered per device. A touch laptop or an iPad with a
keyboard gets the desktop (R41).

## 10. Edge cases worked through

| Case | What happens |
|---|---|
| A render writes a signal it reads (an infinite microtask loop, a frozen page) | the base element counts renders per task and throws naming the element after 200 — found and fixed one real instance this way |
| A parent sets a child's reactive property in its render | the property part compares with its own last value and never reads the child, so the parent does not subscribe to its children (a real bug, now a test) |
| A row moves while focused (sort, another writer) | `moveBefore` keeps focus where the browser has it; elsewhere focus is restored after the move |
| Rows removed while their per-row computeds still watch the selection | computeds with no readers let go of their sources; disposal on disconnect |
| Markup in plan data (a step titled `<img onerror=…>`) | values are never parsed; a strings array that is not a template literal is refused |
| `/api/theme` absent (CI, another OS) or mid-swap (Omarchy replacing the directory) | absent → browser preference; a failed read keeps the current theme until the next poll |
| A dim ANSI hue on its own background | status colours are mixed toward the text colour; shape carries status too |
| IME composition, AltGr layouts, browser-reserved chords | composition is ignored; no Ctrl+Alt+letter bindings; tabs use Alt-based keys inside a browser |
| Focus lands nowhere (on `<body>`) | bare keys are off (mode "—"); arriving on the table focuses its first row |
| A click on an already-focused grid in an inactive pane | panes activate on pointer-down as well as focus-in (found in the prototype) |
| A clicked toast's Undo removes the focused button | the stack releases its focus pause after each render; otherwise every later toast froze (found in the prototype) |
| Another writer removes a selected step | the selection holds IDs; verbs resolve them through the store and skip what is gone (a selection-pruning pass is still to do, below) |
| Long press vs scroll on touch | movement over 8 px cancels the long press; `touch-action: pan-y` keeps scrolling native |
| 10,000 rows | ~250 ms to build either way (ours or Lit): virtualise past ~500 rows, keeping the focused row mounted |

## 11. Known gaps (prototype, not system)

- The touch sheet does not mark the current status as checked.
- The selection is not pruned when another writer deletes a selected step.
- No virtualisation; no column chooser; column widths are not persisted.
- No screen-reader pass yet — roles and labels are in place, but nobody has listened to them.
- Safari is untested; Firefox untested beyond what the standards promise.
- The touch frame is chosen by page (`mobile.html`), not yet by the detection rule above.
