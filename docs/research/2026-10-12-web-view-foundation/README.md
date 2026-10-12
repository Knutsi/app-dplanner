# The web view's foundation: our own reactive engine, and a design system

> **Status: research, 12 October 2026.** Two related questions asked by Knut before the web view
> (the "reporting outside one machine" piece of the [timeline note](../2026-10-11-timeline-and-scope.md))
> is built: (a) is the engine behind Lit small enough to own rather than depend on, and (b) what
> should DPlanner's web design system be. Like the other notes here it is a snapshot.
> **[report.html](report.html)** is the readable front, with the screenshots; this file and
> `notes/` are the durable source.

## Verdicts

**(a) Own the engine.** The part of Lit we need — tagged templates compiled once into a cached
`<template>`, parts that write only what changed, a keyed list, a batched element — is ~350 lines
of idea. Our prototype engine is **about 1,020 lines with comments, 5.5 KB gzipped**, with signals
built in (Lit plus its signals add-on: 11.5 KB; lit-html alone, without signals: 4.1 KB). It **matches Lit 3.3.0 on updates, selection and
swaps, and trails it by 10–25 % on bulk creation** (10,000 rows: 260 ms against 221 ms) —
measured with the js-framework-benchmark operations, median of three run orders. Its 37 tests
include one per defect an independent review found (an XSS hole, leaked computeds, lost focus on
moves, …), and building the app on it found two more engine bugs the tests now hold. The case is
not size but **maintenance**: Lit 3.3.1–3.3.3 ship a `repeat` that leaks DOM ([lit/lit#5298](https://github.com/lit/lit/issues/5298),
reproduced here), and the native replacements (TC39 Signals at Stage 1, DOM Parts) are years out.

**(b) One command registry, three variants, a separate touch UI.** Every surface — menubar,
context menu, toolbar, selection bar, palette, which-key, `?` sheet, touch action bar — is a view
of one registry of commands evaluated against a context of URIs, as DPlanner's `ActionSpec` and
`framework/context.py` already work. Three design variants (*Ledger*, *Modeline*, *Atelier*) are
token sets over one component set; Omarchy's `colors.toml` is the theme format and "Automatic"
follows the desktop live. **Recommendation: Ledger as the default**, Atelier for the read-only
report audience, Modeline for terminal people — each costs ~30 lines.

**Would a WASM core be faster?** No: in every heavy operation JavaScript is only 20–35 % of the
time; the rest is the browser building DOM, styling and laying out, which WASM cannot touch without
crossing back into JS. WASM (or a Worker) could pay for bulk work — decoding a large dataset,
search indexing, graph layout — which fits the backend-for-frontend idea below.

## What is here

```
notes/
  lit-engine.md            Lit from source, comparables, platform status, our engine vs Lit, the six defects
  interaction-patterns.md  menus, context menus, toolbars, palette, keyboard and modes, grids, touch,
                           motion, icons, feedback, multitasking — with 51 rules (R1–R51)
  design-system.md         the system as rules with reasons, variants, keyboard model, edge cases
prototype/                 runs from source, no build step (open via tools/serve.mjs)
  engine/                  signals.js, template.js, element.js
  ui/                      tokens, themes, glyphs and the components (ui/README.md: contracts)
  shell/                   context (URIs), commands, keyboard router, surfaces, workspace (panes),
                           activity, frame.js (desktop) and touch.js (touch)
  data/                    the plan store, filled in bulk; sample data
  features/                appshell, steps, projects, activity — never import each other
  app.js, desktop.html, mobile.html   the composition root
  tests/                   engine, grid, menus, overlays, layers; bench.html; lit-probe.html
tools/                     run.mjs, scenes.mjs (screenshots), serve.mjs, build-demo.mjs,
                           import-assets.mjs — dev-time only; `npm install` here first
evidence/                  benchmark runs (three orders) and their summary
shots/                     every screenshot in the report
```

## Running it

```bash
cd docs/research/2026-10-12-web-view-foundation/tools && npm install
node serve.mjs                         # open the printed address; the theme follows Omarchy's
node run.mjs tests/engine.test.html --wait     # also grid.html, menus.html, overlays.html
node ../prototype/tests/layers.test.mjs
node scenes.mjs                        # 21 scripted scenes → ../shots/, fails on any console error
node run.mjs "tests/bench.html?order=lit,fine,ours" --wait
```

## Findings worth keeping

1. **Lit 3.3.1–3.3.3 `repeat` leaks one comment node per removed row.** A replace-and-clear of 1,000
   rows left 2,000 comments behind each cycle, and our first benchmark slowed from 300 ms to 1.4 s
   per round before we saw why. 3.3.0 is clean.
2. **A parent that sets a child's reactive property must not read it back.** Comparing against the
   child's current value subscribed the parent to its own child: an infinite render loop that froze
   the page with no error. Parts now compare with what they last committed (Lit does the same).
3. **A render-loop guard pays for itself.** The base element throws, naming the element, after 200
   renders without the page yielding. It caught finding 2 on the first run.
4. **Focus versus selection is the whole toolbar story.** With them apart (Gmail, Linear), arrowing
   never reshapes the chrome, selecting turns the toolbar into the selection bar, and every verb has
   one target rule: the selection if any, else the focused thing.
5. **"Normal mode" needs no mode switch.** Single keys act only on a focused navigable surface,
   which is both Vim's speed and WCAG 2.1.4's exception; the modeline names the mode and its exit.
6. **Status colours should come from the theme.** Fixed tints clash with Omarchy palettes; the
   theme's own ANSI hues mixed toward its text colour read well in the five themes photographed
   (retro-82, tokyo-night, catppuccin-latte, gruvbox, rose-pine) — not yet checked across all 22.
7. **The touch UI can share everything but the frame.** Same commands, context, store and workspace
   (run headless); only `shell/touch.js` differs — and a verb that means nothing on touch says so.
8. **Class names collide in light DOM.** A component's `.bar` clipped the menubar to 96 px: every class
   is now scoped under its element or prefixed (`.mark-*`), as `ui/README.md` requires.

## Constraints from the conversation, and where they landed

| Asked for | Where |
|---|---|
| Standard web components + a small reactivity layer, no dependency, no fork | `prototype/engine/` — ideas from Lit (BSD-3) and preact-signals (MIT), no code |
| Components we make ourselves | `prototype/ui/` — 0 runtime packages (checked by `tests/layers.test.mjs`) |
| Menus, right-click, toolbars, compact tables | menubar + APG keyboard contract, context menus (right-click, Shift+F10), banded toolbar, 24 px treegrid |
| Context as URIs reshaping menus and toolbar | `shell/context.js`, `shell/surfaces.js` |
| The selection toolbar: count, actions, clear | `<dp-toolbar>`'s selection bar; on touch, the app bar and action bar |
| Touch, as a separate UI if needed | `shell/touch.js` + `mobile.html` |
| Not busy, learnable, visual | keys shown everywhere, the modeline echo, glyph + colour + shape status |
| Keyboard-driven, self-teaching, a safe normal mode | `shell/keyboard.js`; `notes/design-system.md` §5 |
| Animation that communicates, never adorns or slows | `ui/motion.js`; `notes/design-system.md` §7 |
| Omarchy themes, switchable, auto-detected | `ui/theme.js`, `/api/theme` in `tools/server.mjs` |
| More than one thing at once | panes, follow, peek, preview tabs, the Activity panel |
| Low entropy over time | layers enforced by a test, one registry, one item shape, contracts in `ui/README.md` |
| Later: a backend-for-frontend that pre-renders and sends big datasets | `data/store.js` is filled by one bulk `load()`; no component fetches |

## Next, if this goes ahead

- **Scope check first:** the timeline note says the web view is *read-only*. The design system
  supports verbs; the first version should register only reading ones (open, peek, copy link,
  filter) and leave status changes to DPlanner and the CLI.
- Port the engine out of the prototype with the line budget in `notes/lit-engine.md` §6, adding
  `selector()` and a dev-mode marker for class-field shadowing.
- A data loader: `dplanner report` already assembles the plan for the static site; make it emit the
  store's snapshot shape, and later serve it (and `/api/theme`) from a local `dplanner serve`.
- Adopting server-rendered HTML (S5 in the sample plan) — the hydration question for the
  backend-for-frontend.
- Virtualise the grid past ~500 rows; a screen-reader pass; Safari and Firefox runs.
