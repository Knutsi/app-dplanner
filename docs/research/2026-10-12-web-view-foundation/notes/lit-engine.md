# The engine behind Lit, and the slice of it we should own

*Research notes, 2026-10-12. Question: can DPlanner's read-mostly web view run on standard Web
Components plus a small reactivity layer of our own, built by taking the ideas from Lit
(and its peers) rather than forking or depending on Lit?*

## Summary

1. **Yes, the pattern is small.** You can rebuild Lit's core idea (tagged template, then a cached `<template>` with markers, then a clone, then parts that write only changed values) in about 350 lines. Our prototype does it in 618 (`prototype/engine/template.js`), and a second, independent prototype written for these notes took 339 code lines.
2. **Lit is big for reasons we don't share.** The core `lit-html.ts` is 2,304 source lines, about 1,100 of them code, and about 630 once dev mode is stripped. Much of that weight is dev-mode diagnostics, a sanitizer hook, ShadyDOM/polyfill seams, SSR/hydration hooks, MathML, and a public directive class system with connect/disconnect bookkeeping.
3. **Sizes:** lit-html with `repeat` is ≈ 9.5 KB minified, 4.1 KB gzipped. A full `lit` with `repeat` is ≈ 18 KB / 7 KB, and adding `@lit-labs/signals` brings it to 22–32 KB / 8–11.5 KB. A good signal core is about 1.7–2 KB gzipped (preact, alien-signals). Our prototype engine comes to 4.7 KB gzipped in all.
4. **What carries the complexity:** the HTML-position scanner, the raw-text elements, attribute case-folding and de-duplication, keyed list moves, and the lifetime of subscriptions when DOM leaves or moves. The last two are where both Lit and our prototype have live bugs today (see §1.6 and §5).
5. **Lit 3.3.1–3.3.3 `repeat` leaks one end-marker comment per removed item** (lit/lit#5298, fix PR #5299 open). This is a concrete argument for owning about 100 lines rather than pinning a dependency.
6. **The platform now covers much of what libraries used to supply.** Constructable stylesheets, `:state()`, popover, anchor positioning, `<dialog>`, invoker commands, `@starting-style` and `@scope` all ship across Chrome, Firefox and Safari. A positioning library, a dialog/focus-trap library and a CSS-in-JS layer are all unnecessary.
7. **Native templating and signals are not coming soon.** TC39 Signals is still at Stage 1, last presented in June 2024. DOM Parts is a Chromium prototype that has been "in development" since 2023, and the WCCG chose in March 2025 not to pursue it alone. Fagnani's DOM Templating API is an unreviewed draft from November–December 2025. Design so we can swap them in later, but don't wait for them.
8. **Recommendation: tagged templates plus parts as the structure, with a signal core underneath.** Each component re-renders as one batched effect, and a signal placed directly in a hole is the opt-in fine-grained path for hot spots. This is exactly the shape of our prototype. Benchmarks show that fine-grained-everything buys sub-millisecond updates we don't need, at about twice the memory and slower first render.
9. **Build:** `html` / `svg` / `render` / `repeat` / `nothing`, `signal` / `computed` / `effect` / `batch` / `untracked`, and `css` plus a base element: about 700–900 lines with tests in the same order of size. **Skip:** the directive class API, AsyncDirective, `noChange`, static templates, SSR/hydration, MathML, `cache` / `until` / `guard` / `asyncAppend`, `classMap` / `styleMap`, decorators and controllers.
10. **Before the prototype becomes the engine,** fix six concrete defects found here: the `raw` check against XSS, SVG `<title>`, computed unlinking, disposal on disconnect, focus lost on keyed moves, and error-safe commits. §5 has the details.

---

## 0. Method and sources

*Everything here comes from the published packages and the Lit monorepo source, measured on this
machine. Platform support comes from `web-features` and MDN `browser-compat-data`, not from blogs.
The reboot wiped the first scratch install; the numbers below come from that session's log, and
the probes of our prototype were re-run in `~/.cache/dplanner-lit-research/`.*

- **Packages, from npm on 2026-10-12:**
  - Lit family: `lit` 3.3.3, `lit-html` 3.3.3, `@lit/reactive-element` 2.1.2, `lit-element` 4.2.2, `@lit-labs/signals` 0.3.0, `@lit/context` 1.1.6, `@lit/task` 1.0.3 (all BSD-3-Clause).
  - Template libraries: `uhtml` 5.0.9 (MIT), `lighterhtml` 4.2.0 (ISC), `hyperhtml` 2.34.2 (ISC), `htm` 3.1.1 (Apache-2.0), `preact` 11.0.1 (MIT), `@arrow-js/core` 1.0.6 (MIT).
  - Signal libraries: `@preact/signals-core` 1.14.4 (MIT), `alien-signals` 2.0.8 (MIT), `signal-polyfill` 0.2.2 (Apache-2.0), `@vue/reactivity` (MIT).
  - Frameworks and compilers: `@microsoft/fast-element` 3.1.0 (MIT), `petite-vue` 0.4.1 (MIT), `alpinejs` 3.17.4 (MIT), `solid-js` 1.9.17 (MIT), `@stencil/core` 4.45.2 (MIT).
- **Lit TypeScript source:** a sparse clone of `github.com/lit/lit` at `01dbc6673cdc` (main, 2026-09-14). The npm packages ship compiled JS without `sourcesContent`. File references below are `packages/<pkg>/src/<file>.ts:<line>` at that commit.
- **Sizes:** `esbuild 0.28.2 --bundle --minify --format=esm --platform=browser --conditions=production` over a one-line entry that imports the named symbols and assigns them to `window`, so they survive tree-shaking. Then `gzip -9` and `brotli -q 11`.
- **Platform data:** `web-features` 3.42.0 (Baseline status) and `@mdn/browser-compat-data` 8.1.5 (per-browser versions).
- **Browser runs:** Chromium 152 headless through `playwright-core` 1.64.

## 1. Lit, from source

*Lit is three layers. **lit-html** turns a tagged template into a cached `<template>` and a list of "parts" that write individual DOM positions. **ReactiveElement** turns property writes into one microtask-batched update. **LitElement** glues the two together. The essential mechanism is a few hundred lines. The rest is diagnostics, extensibility (directives), and environments we don't have (SSR, polyfills).*

### 1.1 Sizes and line counts

Here is what is in each core file:

| File (lit main @ 01dbc66) | source lines | code lines (comments stripped) | code, `DEV_MODE=false` + DCE |
|---|---:|---:|---:|
| lit-html/src/lit-html.ts | 2,304 | 1,101 | ≈ 634 |
| lit-html/src/directive.ts | 144 | 60 | |
| lit-html/src/directive-helpers.ts | 253 | 84 | |
| lit-html/src/async-directive.ts | 388 | 165 | |
| lit-html/src/directives/repeat.ts | 488 | 153 | |
| lit-html/src/static.ts | 194 | | |
| reactive-element/src/reactive-element.ts | 1,755 | 1,108 | |
| reactive-element/src/css-tag.ts | 206 | 103 | |
| reactive-element/src/reactive-controller.ts | 85 | | |
| lit-element/src/lit-element.ts | 298 | 133 | |
| labs/signals/src/lib/{signal-watcher,watch,html-tag}.ts | 327 + 103 + 47 | | |
| context/src/lib/** (7 files) | ≈ 800 | | |
| task/src/task.ts | 459 | | |

Directive source lines: `live` 104, `ref` 163, `class-map` 129, `style-map` 146, `when` 48, `cache` 126, `until` 150, `keyed` 57, `guard` 100. `lit-html.ts` refers to `DEV_MODE` 21 times and `debugLogEvent` 35 times.

Code lines were counted as the non-blank lines of `esbuild --loader=ts` output. The DCE column is the same count after `DEV_MODE` is flipped to `false` and run through `--minify-syntax`.

Bundle sizes, measured as described in §0:

| Bundle | min | gzip -9 | brotli |
|---|---:|---:|---:|
| lit-html: `html, render, svg, nothing, noChange` | 7,145 | 3,198 | 2,878 |
| lit-html + `repeat` | 9,437 | 4,109 | 3,703 |
| `@lit/reactive-element` (`ReactiveElement, css`) | 7,501 | 2,940 | 2,595 |
| `lit` (`LitElement, html, css, render`) | 15,445 | 5,984 | 5,392 |
| `lit` + `repeat` | 17,750 | 6,896 | 6,207 |
| `lit` + repeat, classMap, styleMap, live, ref, until, cache, when | 23,962 | 8,800 | 7,966 |
| `lit/async-directive` alone (pulls lit-html) | 8,549 | 3,718 | 3,354 |
| `@lit-labs/signals` (`SignalWatcher, watch, html, signal, computed`; includes signal-polyfill and lit) | 21,597 | 7,870 | 7,023 |
| `@lit/context` (`createContext, ContextProvider, ContextConsumer`) | 3,253 | 1,067 | 923 |
| `@lit/task` (`Task`) | 8,913 | 3,393 | 3,043 |

The main session measured slightly different import sets with the same tool:

- lit-html 3.3.0 (`html + render + svg + nothing + repeat`): 9.5 KB min, 4.1 KB gz.
- lit 3.3.3 (`LitElement, html, css, repeat`): 18.1 KB / 7.0 KB.
- lit plus `@lit-labs/signals`: 32.3 KB / 11.5 KB.

The gap from my 21.6 KB comes from the import set: theirs adds `LitElement`, `css` and `repeat` beside the signals entry points, and so carries both the element and the template layers. Both figures are honest for what they import. The figure that matters is that **signals-on-Lit costs 8–11.5 KB gz.**

### 1.2 The template pipeline, step by step

1. **The tag returns a description, nothing more.**
   - `html` is `tag(HTML_RESULT)` and returns `{_$litType$: 1, strings, values}` (lit-html.ts:560–601). `svg` and `mathml` use types 2 and 3.
   - No DOM work happens yet.
   - The `_$litType$` key is deliberately left unminified so separately built copies of Lit interoperate (§1.5).

2. **The strings array is the cache key.**
   - A JavaScript engine hands the *same frozen `TemplateStringsArray` object* to every evaluation of one call site.
   - So `templateCache = new WeakMap<TemplateStringsArray, Template>()` (lit-html.ts:689) and `_$getTemplate` (≈1675) prepare each call site once.
   - Consequences:
     - Two textually identical literals at different call sites are different templates.
     - Template identity is the call site, so a ternary choosing between two `html` literals swaps whole instances.

3. **Scanning the strings to place markers (`getTemplateHtml`, lit-html.ts:799–953).**
   - It runs a five-state scanner using sticky regexes: `textEndRegex`, `commentEndRegex`, `comment2EndRegex`, `tagEndRegex`, and the single- and double-quoted attribute-end regexes. A sixth regex is built per raw-text element (lines 399–449).
   - At the end of each string it knows whether the next hole is in text, in an attribute value, or bare inside a tag:
     - **Text position:** it appends `<?lit$NNNN$>`. That is processing-instruction syntax, which the HTML parser turns into a *comment* whose data is `?lit$NNNN$` (lines 350–357). The marker is randomised per load (`Math.random()`), so author text cannot collide with it.
     - **Attribute value:** it rewrites the attribute name to `name$lit$` (the `boundAttributeSuffix`), keeps the value with markers spliced in, and records the *original-case* name in `attrNames`. The parser lowercases attribute names, which would turn `.textContent` into `.textcontent` (lines 808–811, 937–946).
     - **Bare in a tag** (element binding): it appends `lit$NNNN$` plus an index, so the attribute name is unique.
   - Edge handling:
     - It inserts a space before a following `/>` (line 933).
     - It throws in dev mode for a hole in a tag name (lines 857–866).

4. **One parse.**
   - `Template.createElement` sets `template.innerHTML` (≈1120).
   - The string is passed through a Trusted Types policy named `lit-html` (lines 264–268). This is safe because it contains only author literals plus markers.
   - SVG and MathML results are wrapped in `<svg>` / `<math>` for the parse and then unwrapped (lines 981–984).

5. **Walking the template once to record parts (Template constructor, lit-html.ts:958–1110).**
   - A shared `TreeWalker` with `SHOW_ELEMENT | SHOW_COMMENT` (filter 129) visits nodes in document order.
   - It records each part as `{type, index: nodeIndex, name, strings, ctor}`.
   - For `$lit$`-suffixed attributes, it chooses the part class from the recorded name's prefix: `.` gives PropertyPart, `?` gives BooleanAttributePart, `@` gives EventPart, and anything else gives AttributePart. Then it removes the attribute.
   - Raw-text elements (`script | style | textarea | title`) have their text split on the marker into text nodes plus marker comments, because comments are not parsed inside raw text (≈1044–1066).
   - Comments that contain a marker produce an inert `COMMENT_PART`.

6. **Instantiating (`TemplateInstance._clone`, lit-html.ts:1193–1270).**
   - `document.importNode(template.content, true)` clones the content.
   - The same walker steps to each recorded `index` and constructs the live part objects.
   - Construction is a single forward walk with no `querySelector`.

7. **Updating (`TemplateInstance._update`).**
   - Each part receives its value.
   - A multi-hole attribute consumes `strings.length - 1` values.

8. **Committing only what changed:**
   - **`ChildPart._$setValue`** (lit-html.ts:1339 onward) resolves directives first, then dispatches on the value:
     - A primitive is written into the existing Text node's `.data` when the previous value was also a primitive. It is compared against the *committed JS value*, not the DOM.
     - A TemplateResult goes to `_commitTemplateResult`: if it has the same `Template` as the committed instance it calls `_update(values)`, otherwise it clones a new instance and replaces the old.
     - A Node is inserted.
     - An iterable goes to `_commitIterable`, which reuses item ChildParts *by position* and trims the extras.
     - Anything else becomes text.
     - `nothing`, `null`, `undefined` and `''` clear the part.
   - **`AttributePart`** (≈1807): a single-hole attribute compares against its committed value. A multi-hole attribute concatenates statics with values. `nothing` removes the attribute. `null` and `undefined` become `''`.
   - **`PropertyPart`** sets `el[name]`, with `nothing` becoming `undefined`.
   - **`BooleanAttributePart`** calls `toggleAttribute`.
   - **`EventPart`** registers *the part itself* as the listener (`handleEvent`), so changing the handler is just a field write. It re-registers only when the `capture`, `once` or `passive` options carried on the listener object change. It calls the handler with `this` set to `options.host`.
   - **`ElementPart`** exists only to host directives such as `ref`.
   - The sentinels:
     - `noChange` (`Symbol.for('lit-noChange')`) tells a part to skip the write.
     - `nothing` (`Symbol.for('lit-nothing')`) means "remove". They exist so that `undefined`, `null` and `''` can mean "empty string" in attributes while still giving directives a way to say "skip" and "remove".

9. **`render(value, container)`** stores the root ChildPart on the container as `container._$litPart$` and calls `_$setValue`. A second render into the same container diffs against it.

### 1.3 Directives

- **The plain directive.** A directive is a class; `directive(Class)` returns a factory whose result is `{_$litDirective$: Class, values}`.
  - `resolveDirective` (lit-html.ts:1137–1182) keeps one directive *instance* per part, or per attribute slot. It replaces the instance when the class changes and calls `render()` or `update(part, values)`, which may return `noChange`.
- **AsyncDirective** (async-directive.ts, 388 lines) adds `setValue()` for out-of-band commits and `disconnected()` / `reconnected()` callbacks. Supporting these means every part and instance carries `_$parent`, `_$disconnectableChildren` and `_$notifyConnectionChanged`.
  - The connection state must be propagated down whenever DOM is cleared, moved between parents, or the root is `setConnected(false)` (lines 136–275).
  - This bookkeeping is the most intricate code in Lit, and it is entirely about subscriptions that must stop when DOM is no longer shown.
- **`repeat`** (repeat.ts, 488 lines; 153 code lines) is the classic keyed head/tail algorithm with lazily built key-to-index maps (lines 120–420, with a long worked example in the comments):
  - It checks head-head and tail-tail matches.
  - Keys that are gone are removed.
  - Otherwise it looks the new head up in the old map and moves it.
  - It adds the remaining new items and removes the remaining old ones.
  - It does not compute an LIS. The common edits (append, remove one, swap) are O(1) moves plus O(n) comparisons.
- **The other directives:**
  - `live` compares against the live DOM value instead of the last committed value, for inputs the user edits.
  - `ref` gives an element to a callback or a `Ref`.
  - `classMap` and `styleMap` do incremental per-key class and style updates.
  - `when` and `choose` are sugar.
  - `cache` keeps detached DOM per template to swap back cheaply.
  - `until` and `asyncReplace` / `asyncAppend` render promises and async iterables.
  - `guard` memoises on dependencies.
  - `keyed` forces a re-create.
  - `unsafeHTML` / `unsafeSVG` are the explicit escape hatch.

### 1.4 ReactiveElement and LitElement

- **Reactive properties.** `static properties` or decorators lead to `createProperty`, which installs an accessor on the prototype (reactive-element.ts:699–790). The setter calls `requestUpdate(name, old)`.
  - Options: `attribute` (name, or `false`), `type`, `converter` (`fromAttribute` / `toAttribute`, with `defaultConverter` at line 354 handling String, Number, Boolean, Object and Array via JSON), `reflect`, `hasChanged` (default `notEqual`, which is "different and not both NaN"), `state`, `noAccessor`, and since 2.1 `useDefault`.
  - Reflection guards against re-entry with `__reflectingProperty` (lines 1184–1258).
  - `observedAttributes` is derived during `finalize()`.
  - Values set on an instance *before* upgrade are saved and re-applied (`__instanceProperties`).
- **Batching.** `requestUpdate` records changed properties in a `Map`. If no update is pending, it sets `__updatePromise = __enqueueUpdate()` (lines 1282–1325).
  - `__enqueueUpdate` is `async`, and it `await`s the previous update promise. That `await` *is* the microtask batching: every synchronous write before it resolves lands in the same update (lines 1370–1390).
  - It then calls `scheduleUpdate()`, which you can override to return a Promise and so plug in a scheduler. That calls `performUpdate()`:
    1. On the first run, create the render root.
    2. Call `shouldUpdate(changed)`.
    3. Call `willUpdate(changed)`.
    4. Call each controller's `hostUpdate()`.
    5. Call `update(changed)`, where LitElement calls `render()` and lit-html `render()`, and reflects attributes.
    6. Call `_$didUpdate`: each controller's `hostUpdated()`, then `firstUpdated` (first run only), then `updated`.
  - `updateComplete` resolves after the update, and again if the update queued another.
- **Controllers** are plain objects that a host calls at `hostConnected`, `hostDisconnected`, `hostUpdate` and `hostUpdated`. `@lit/context` and `@lit/task` are both built from them.
- **Styles.** The `css` tag produces a `CSSResult`. Interpolation is allowed only of other `CSSResult`s or numbers, enforced by a construction token (css-tag.ts:38–72).
  - `finalizeStyles` flattens and dedups them.
  - `adoptStyles` sets `shadowRoot.adoptedStyleSheets`, falling back to `<style>` elements carrying the `litNonce` (css-tag.ts:171–191).
  - The default render root is `attachShadow({mode: 'open'})` with `static shadowRootOptions`.
- **LitElement** (298 lines) adds `render()`, `renderOptions.host = this` (so `@event` handlers get `this`), and `renderBefore` for styles. Through `setConnected` it also notifies AsyncDirectives when the element connects or disconnects.
- **@lit-labs/signals** adds `SignalWatcher(Base)`:
  - It overrides `performUpdate` to run inside a `Signal.Computed`, with a `Signal.subtle.Watcher` per element. Any signal read during render then schedules `requestUpdate`.
  - It adds the `watch(signal)` AsyncDirective, which commits one part when the signal changes, with no element re-render (watch.ts: a per-part Computed watched by the host's Watcher or by a hostless microtask watcher).
  - The `html` it exports auto-wraps signals in `watch`.
  - It is built on `signal-polyfill`, so it pays about 3.2 KB gz for the proposal's API surface.

### 1.5 The security model

- **Values never reach the parser.** The only string ever assigned to `innerHTML` is built from the template's *static* strings plus markers.
  - Values are written as Text node `.data`, attribute values via `setAttribute`, properties, or listeners.
  - So `${'<img onerror=…>'}` is inert text.
  - The remaining sinks are deliberate: `.innerHTML=${…}` property bindings, `unsafeHTML`, `href="javascript:…"`, and `<style>`/`<script>` content. Lit refuses the last of these when a sanitizer is installed (lit-html.ts, `_commitNode`).
- **The strings array must be a real template object.** `trustFromTemplateString` (lit-html.ts:754–785) throws unless `strings` is an array with an own `raw` property, so `html(['<img onerror=…>'])` called as a function is refused.
  - The comment points at `Array.isTemplateObject` as the eventual native check, which was a TC39 proposal.
- **The result brand.** `_$litType$` is a plain string key, not a Symbol, so results built by different Lit copies or by the SSR compiler interoperate.
  - The cost is that a JSON-decoded `{"_$litType$":1,"strings":…}` *looks* like a result. The `raw` check above is what stops it: JSON cannot produce an array with an own `raw`.
  - A compiled result (`_$litType$` is an object `{h, parts}`) is trusted through `trustFromTemplateString(type.h, …)`.
- **Trusted Types:** a `lit-html` policy whose `createHTML` is the identity, justified by the construction above. There is also an extra-security hook, `setSanitizer` / `createSanitizer`, for attribute, property and text sinks (`ENABLE_EXTRA_SECURITY_HOOKS`).
- **Dev-mode checks:**
  - throws on bindings in tag names and on expressions inside `<template>`;
  - warns on expressions inside `<textarea>`;
  - throws on duplicate attribute bindings (detected when fewer attributes come back than were recorded, lit-html.ts:1087–1105);
  - warns when `${this}` is rendered inside itself (≈1485);
  - throws on a ChildPart whose markers were ejected by external `innerHTML`;
  - throws when class fields shadow reactive accessors (reactive-element.ts:1453–1470);
  - warns when several versions of Lit are loaded;
  - warns when `requestUpdate` is called with an Event as the property name.

### 1.6 What is essential, what carries the complexity, and the traps

**Essential** (about 300–400 lines in any reimplementation):

- the call-site cache;
- the marker scanner;
- the one-time parse and walk;
- clone plus part construction;
- ChildPart (text, nested template, node, iterable) and attribute / property / boolean / event parts;
- a keyed list;
- `render()`.

**Where the complexity actually lives:**

| Concern | Why it is hard | Need it? |
|---|---|---|
| Attribute-position parsing | HTML tokenising without a parser: quotes, `>` inside quoted values, unquoted values, `/>`, comments, `</{` "bogus comments" | yes — but only the subset `html` literals need |
| Case-folding and dedup | parser lowercases names and drops repeated attributes; must record names from the strings, not the DOM | yes (or avoid: strip bound attributes entirely, see §5) |
| Raw-text elements | `<script>/<style>/<textarea>/<title>` contain no comments; `<textarea>` text sets only its *default* value | refuse holes there; bind `.value` |
| SVG / MathML | parse context; `svg`` fragments wrapped/unwrapped; `title` is raw text in HTML but *not* in SVG | SVG yes, MathML no |
| Sentinels `nothing`/`noChange` | let directives skip or remove, and let `''`/null differ in attributes | `nothing` optional; `noChange` no |
| Directive class system + AsyncDirective | public extension API with per-part instances and a connected-tree | no — signals in holes replace the use cases |
| Keyed `repeat` | minimal moves; correct cleanup | yes (≈60–100 lines) |
| Dev-mode warnings | ~35 log points, ~20 checks | a handful of throws at compile time, cheap |
| SSR / hydration (`private-ssr-support.ts`, `@lit-labs/ssr-client`, compiled templates) | | no |
| ShadyDOM / polyfill support, `wrap()` | | no |

**Traps a re-implementation will hit:**

- Attribute *names* must come from the strings, because the DOM lowercases them.
- Duplicate attributes in one tag silently drop a binding.
- A hole in a tag name is impossible.
- A hole in `<textarea>` text renders once and never updates once the user has typed. Use `.value`.
- `<style>` and `<script>` holes are injection sinks.
- In table context the parser foster-parents *text*, but comments are inserted where they stand. So markers must be comments, never text.
- A `<template>`'s contents are parsed in "template contents" mode, so a root `<tr>` or `<td>` survives.
- External code calling `innerHTML`, `textContent` or `replaceChildren` on a rendered container ejects the markers.
- Iterables without keys reuse rows by *position*, so focus and input state jump between rows.
- Moving a focused element with `insertBefore` blurs it.
- A class field `count = 0` in a subclass shadows the prototype accessor (because of `useDefineForClassFields`).
- Properties set before upgrade live on the instance.
- `Symbol.for` brands are forgeable by any code in the realm. Module-private Symbols and `instanceof` are not.

**A live upstream bug, the strongest single argument for owning this code.** In lit-html 3.3.1 through 3.3.3, `removePart` became `part._$clear(); part._$startNode.remove();` (lit/lit PR #4975, April 2025), which leaves `_$endNode` behind.

- Every removed `repeat` item therefore leaves an empty comment.
- The main session reproduced it on 3.3.3: replacing 3 rows with 3 new keys left 13 nodes in the tbody instead of 10, and the DOM grew by 2,000 comments per replace-then-clear cycle of 1,000 rows. 3.3.0 is clean.
- This session saw the same independently. After 5 create/clear cycles of 4,000 rows a container held 20,001 nodes. Clears slowed from 35 ms to 375 ms in a plain `<div>`. In a 5,000-row, 6-column table the 7th clear took about 3 s against about 25 ms for our engine.
- Reports: lit/lit#5010 (2025-06) and #5298 (2026-04), both open. The fix is PR #5299 (2026-04), unmerged in 3.3.3.

## 2. Comparables

*Every peer is one of three models. Tagged templates plus parts (Lit, uhtml, FAST, Arrow) need no build step. Templates compiled to a VDOM (htm + Preact) or to direct DOM (Solid, Stencil) need either a diff or a compiler. DOM-walking directive interpreters (petite-vue, Alpine) evaluate attribute strings with `new Function`. For "standard Web Components, no build step, CSP-friendly", only the first model fits, and all its members converge on the same design we prototyped.*

| Library (version, licence) | Model | min / gz (measured) | Notes |
|---|---|---:|---|
| lit-html 3.3.3 + repeat (BSD-3) | tagged template → `<template>` + parts | 9.4 / 4.1 KB | the reference |
| uhtml 5.0.9 (MIT) | tagged template, **own HTML parser**, path-addressed holes; signals via a fork of alien-signals | 15.0 / 6.4 KB (`html, svg, render`; signals live in the same entry) | v5 (2025-08) is a rewrite: JSX-like `<${Component}/>`, self-closing tags, `key` attribute, `<!--◦-->` holes, `<!--<>-->` persistent fragments; 1,693 source lines |
| lighterhtml 4.2.0 (ISC) | tagged template + `domdiff` | 11.7 / 5.2 KB | last release 2021; superseded by uhtml |
| hyperHTML 2.34.2 (ISC) | tagged template + wires | 18.9 / 8.0 KB | last release 2022; legacy |
| htm 3.1.1 (Apache-2.0) | tagged template → `h()` calls (parses once per call site) | 1.2 / 0.7 KB | needs a VDOM; last release 2022 |
| Preact 11.0.1 (MIT) | VDOM | 10.7 / 4.6 KB; htm+preact 11.9 / 5.2 KB | diffing every render; components are functions |
| @preact/signals-core 1.14.4 (MIT) | push-pull signals, linked-list graph, versions | 4.6 / 1.7 KB (main session: 5.3 / 1.95) | 1,138 source lines TS; the best reference implementation |
| alien-signals 2.0.8 (MIT) | push-pull signals, very fast | 4.1 / 1.6 KB | ~500 lines; Vue 3.6 adopted its algorithm |
| signal-polyfill 0.2.2 (Apache-2.0) | the TC39 proposal API | 9.4 / 3.2 KB | last commit 2025-02; "do not rely on stability" |
| @vue/reactivity (MIT) | proxies + effects | 13.7 / 5.2 KB | |
| Arrow.js @arrow-js/core 1.0.6 (MIT) | tagged template; **a function in a hole is a reactive binding**; `reactive()` proxies | 18.2 / 7.4 KB | grew well past its "~2 KB" origins (components, hydration); 2,890 source lines |
| FAST element 3.1.0 (MIT) | tagged template whose holes are arrow functions `${x => x.name}` bound to observables; behaviours | 56.0 / 17.2 KB | heavy; decorators; Microsoft's design system base |
| Solid 1.9.17 (MIT) via dom-expressions | **compiled** JSX → `template()` clones + fine-grained `effect`s; no diff | `solid-js/web` core 11.0 / 4.4 KB; `solid-js/html` tagged-template runtime 30.8 / 11.6 KB | the speed comes from the Babel compiler; the no-build `html` variant parses at runtime and is bigger and slower — does not fit "no build step" |
| Stencil 4.45.2 (MIT) | compiler → custom elements + small VDOM | n/a (output depends on build) | a compiler and dev server; opposite of "no build" |
| petite-vue 0.4.1 (MIT) | walks existing DOM, `v-` directives, `@vue/reactivity` | 16.6 / 7.2 KB | evaluates expressions with `new Function` → needs `'unsafe-eval'`; unmaintained since 2022-01 |
| Alpine 3.17.4 (MIT) | walks existing DOM, `x-` attributes | 55.9 / 19.9 KB | `new Function` (a separate CSP build exists, with a restricted expression language) |

The design notes worth borrowing:

- **uhtml 5's path-addressed holes.** It records each hole as a child-index path into its parsed tree, rather than walking with a TreeWalker. Its persistent fragments solve "a hole holding several nodes". Neither is needed if every hole owns a start/end comment pair.
- **Preact signals and alien-signals.** Their doubly-linked dependency nodes, plus "unsubscribe a computed when its last subscriber leaves", are what keep per-row computeds cheap. That is the gap in our `signals.js` (§5).
- **Solid's `createSelector`.** It makes "is this row selected?" O(1) per change instead of O(rows). A 10-line helper is worth having.
- **FAST and Arrow** show that "functions or signals in holes" is a known, workable model.

### 2.1 Standards status, late 2026

- **TC39 Signals is at Stage 1.** It sits in `tc39/proposals/stage-1-proposals.md`. It was last presented in 2024-06 ("algorithms for signals") after Stage 1 in 2024-04.
  - The `tc39/proposal-signals` repository's last commit is 2025-08-11, and `signal-polyfill`'s is 2025-02-13.
  - No engine ships it.
  - The champions' README itself estimates native availability as "at least 2–3 years" out and plans multiple production implementations before Stage 2.
  - Sources: github.com/tc39/proposals, github.com/tc39/proposal-signals.
- **DOM Parts:** blink-dev "Intent to Prototype" (Mason Freed, 2023-06-08). chromestatus feature 5199708301033472 says "In development", last updated 2023-06-08.
  - A parser prototype exists behind a flag.
  - In the WCCG meeting of 2025-03-26, benchmarks showed it winning some cases and losing others by 10–20%. The group concluded *not* to pursue DOM Parts standalone and to look at template instantiation instead. Apple wants to revive its 2017 Template Instantiation proposal.
  - Sources: groups.google.com/a/chromium.org/g/blink-dev/c/wIADRnljZDA, w3.org/2025/03/26-webcomponents-minutes.html.
- **DOM Templating API** (Justin Fagnani, WICG/webcomponents#1069, opened 2024-08-16). Its explainer, last updated 2025-11-07 and marked "not ready for review", proposes `DOMTemplate.html` / `svg` / `mathml`, `Element.prototype.render()`, and part classes that mirror Lit's: ChildPart, Single- and MultiAttributePart, PropertyPart, EventPart, BooleanAttributePart, ElementPart and CommentPart. It builds on DOM Parts and speculative TC39 signals.
  - No vendor has committed to it.
  - Takeaway: if this ever ships, it will have **Lit's exact part model**. Mirroring that vocabulary (`.prop`, `?bool`, `@event`, ChildPart) keeps a future swap cheap.
  - Sources: github.com/WICG/webcomponents/issues/1069, github.com/justinfagnani/dom-templating-api-proposal.
- **Nothing native removes the need for our engine in 2026–2027.**

## 3. Platform facts we will rely on

*All the building blocks of a custom-element app are Baseline today. The newer UI primitives
(popover, anchor positioning, invoker commands, `@starting-style`, `@scope`, view transitions)
reached all three engines in 2024–2026, and they retire whole categories of library code. A few
items are still Chromium-only: `interestfor`, `interpolate-size`, element-scoped view transitions,
`dialog closedby` in Safari, and customizable `<select>` in Firefox. Treat those as enhancements.*

Source: `web-features` 3.42.0 (`status.baseline`) and `@mdn/browser-compat-data` 8.1.5. In the
table, "high" means widely available (2.5 years since the last engine shipped) and "low" means newly available.

| Feature | Chrome | Firefox | Safari | Baseline | Replaces |
|---|---|---|---|---|---|
| Autonomous custom elements | 54 | 63 | 10.1 | high | — |
| Customized built-ins (`is=`) | 67 | 63 | **no** | not Baseline | don't use |
| Shadow DOM | 53 | 63 | 10 | high | |
| Declarative shadow DOM (`<template shadowrootmode>`) | 111 | 123 | 16.4 | high (2026-08) | server-rendered components without JS |
| Constructable stylesheets / `adoptedStyleSheets` | 73 | 101 | 16.4 | high | `<style>` per instance; Lit's `adoptStyles` fallback |
| `ElementInternals` / form-associated custom elements | 77 | 93 (FACE 98) | 16.4 | high | hidden-input hacks |
| `ElementInternals.states` + `:state()` | 90 / `:state()` 125 | 126 | 17.4 | — (all ship) | reflecting state to classes/attributes for styling |
| `ElementInternals.role` / ARIA reflection | 103 | 119 | 16.4 | | `role` attribute on host |
| `popover` attribute, `:popover-open` | 114 | 125 | 17 | low (2025-01) | z-index stacking, light-dismiss, top layer code |
| `popover="hint"` | 151 | 153 | no | no | |
| CSS anchor positioning (`anchor-name`, `position-area`, `@position-try`, `anchor()`) | 125–129 | 147 | 26 | core ships everywhere; web-features still lists the whole group as not Baseline because of late sub-features (`position-anchor` revised in 151/27) | Floating UI / Popper |
| `<dialog>` | 37 | 98 | 15.4 | high | modal libraries, focus traps |
| `dialog.requestClose()` | 134 | 139 | 18.4 | low | |
| `<dialog closedby>` | 134 | 141 | preview | no | light-dismiss code |
| `inert` | 102 | 112 | 15.5 | high | focus-trap libraries |
| Same-document View Transitions (`startViewTransition`, `view-transition-name`) | 111 | 144 | 18 | low (2025-10) | FLIP animation code |
| `view-transition-class` | 125 | 144 | 18.2 | | |
| Element-scoped `element.startViewTransition` | 147 | no | no | no | |
| `@starting-style` / `transition-behavior: allow-discrete` | 117 | 129 | 17.5 / 17.4 | low (2024-08) | JS enter/exit animation for popovers/dialogs |
| `interpolate-size` / `calc-size()` | 129 | no | no | no | measuring heights for accordions |
| `@scope` | 118 (feature 143) | 146 | 26.4 | low (2026-03) | BEM / CSS-module naming in light DOM |
| CSS nesting | 120 | 117 | 17.2 | high (2026-06) | preprocessor |
| `light-dark()` | 123 | 120 | 17.5 | low | theme switching code |
| `color-mix()` | 111 | 113 | 16.2 | high | colour helpers |
| Relative colour syntax | 125 | 128 | 18 | low | colour helpers |
| `contrast-color()` | 147 | 146 | 26 | | |
| `@property` (registered custom properties) | 85 | 128 | 16.4 | low | animating custom properties |
| `:has()` | 105 | 121 | 15.4 | high (2026-06) | parent-state classes |
| Container size queries | 105 | 110 | 16 | high | ResizeObserver layout code |
| Container style queries | 111 | 151 | 18 | low (2026-05) | |
| `scrollend` event | 114 | 109 | 26.2 | low (2025-12) | scroll debounce timers |
| Invoker commands (`commandfor`/`command`) | 135 | 144 | 26.2 | low (2025-12) | click handlers to open dialogs/popovers |
| Interest invokers (`interestfor`) | 142 | no | no | no | hover-card JS (enhancement only) |
| Customizable `<select>` (`appearance: base-select`) | 135 | 149 behind flag | 27 | no | custom listbox widgets (enhancement only) |
| `AccentColor` / `AccentColorText` system colours | 149 | 103 | 16.5 | | matching the OS accent |
| `accent-color` property | 93 | 92 | 26.2 | | |
| Trusted Types | 83 | 148 | 26 | low (2026-02) | — lets us enforce "no `innerHTML` sinks" by CSP |
| `Element.setHTML` (Sanitizer API) | 146 | 148 | no | | DOMPurify, for rendering step prose/Markdown HTML |
| `Document.parseHTMLUnsafe` | 124 | 128 | 26 | | |
| `Element.moveBefore` (state-preserving move) | 133 | 144 | **no** | | keeps focus/transitions when keyed rows move (see §5) |
| `content-visibility` | 85 | 125 | 18 | | virtual scrolling for long tables (keeps DOM for find-in-page and a11y) |
| `field-sizing` | 123 | 152 | 26.2 | | auto-growing textareas |
| `ariaActiveDescendantElement` (element reflection) | 135 | 136 | 16.4 | | id plumbing across shadow roots for keyboard grids |
| Scoped custom element registries | 146 | preview | 26 | no | |
| `ShadowRoot.referenceTarget` | 152 | flag | flag | no | cross-shadow ARIA |

**Library code these features remove:**

- **Positioning:** popover + anchor positioning + `@position-try` replace Floating UI or Popper entirely.
- **Dialogs and focus:** `<dialog>` + `inert` + `requestClose` replace a modal / focus-trap library.
- **Wiring:** invoker commands remove click-to-open wiring.
- **Animation:** `@starting-style` + `allow-discrete` + view transitions replace enter/exit animation helpers and FLIP code.
- **Styling:** `adoptedStyleSheets` + `@scope` + nesting + `light-dark()` + relative colours replace any CSS-in-JS or theming runtime.
- **Component state:** `:state()` replaces state-reflection boilerplate.
- **Long tables:** `content-visibility: auto` plus `contain-intrinsic-size` on row groups handles long tables without a virtualiser, which matters for keyboard navigation and find-in-page.
- **Prose rendering:** `setHTML` is a native sanitizer for user Markdown (Chrome and Firefox; Safari needs a fallback).

## 4. Tagged templates + parts vs signals bound directly to DOM

*Both are cheap enough for a few thousand rows. At that size the DOM and layout dominate creation
time whichever engine runs it. Fine-grained binding wins only on pinpoint updates we don't need,
and costs about twice the memory and slower first render. Coarse per-component re-rendering
over immutable snapshots is simpler and matches how DPlanner's data arrives.*

**Benchmarks:**

- **This session:** 5,000 rows × 6 cells, Chromium 152 headless, each operation timed through to a forced layout, medians of 3 page loads × 7–21 runs.
- **The main session** (`evidence/bench-run4-script-split.json`): 1,000 and 10,000 rows, total and script-only.

| op | Lit 3.3.3 | template-only (coarse re-render) | signals-per-cell (fine) |
|---|---:|---:|---:|
| create 5,000 rows | 240–250 ms | 228–338 ms | 240–423 ms |
| update every 10th row | 26–30 | 36–42 | 25–33 |
| select one row (class on one `<tr>`) | 2.0 | 2.7 (after caching the last text) | 0.9 |
| swap two rows | 20–22 | 20 (with LIS) / **214 without** | 32 |
| no-op re-render | 0.8–1.0 | 1.9 (9 ms before caching the last text value) | 0 |
| JS heap after create | 20 MB | 13–20 MB | **45 MB** |

The main session's script-only figures at 1,000 rows agree:

- Update every 10th row: ours 2.4 ms, fine 0.43, Lit 0.46.
- Select a row: 1.9 / 0.08 / 0.19 ms.
- Create 10,000 rows: 57 / 69 / 55 ms of script, against 229 / 274 / 270 ms in total. Layout and paint are about 75% of creation.

**Reading the numbers:**

- Every update path is well under a 16 ms frame at 5,000 rows. Creation is dominated by the browser, so `content-visibility` matters more than the engine.
- Fine-grained binding is the clear winner only on single-cell updates (0.1–1 ms against 2–3 ms) and the clear loser on memory and creation. It pays one effect per bound cell, about 2.5 KB each in a Map/Set-based implementation; linked-list engines like preact and alien-signals are several times leaner.
- **For DPlanner the data model decides it.** Data arrives from the Python side as project and step snapshots (CLI JSON / a server push). Re-rendering a component from a fresh immutable snapshot with keyed rows is natural. Fine-grained binding would need normalising every snapshot into per-field signals, which is a store layer of its own.
- Keyboard focus and selection are local UI state that changes often. That is where a signal in a hole (`class=${rowSelected}`) pays off.

**Recommendation: tagged templates + parts as the structure, signals as the state.**

- Each component renders inside one effect, coalesced to a microtask.
- Holes compare values, so a re-render touches only changed DOM.
- A signal passed *as a value* into a hole subscribes that one part. This is the opt-in fine-grained path for hot spots: selection, focus ring, live agent-run status, clocks.
- This is Lit + `@lit-labs/signals` semantics without the directive and AsyncDirective machinery. Our prototype already has this shape.
- Use a `createSelector`-style helper for "which row is selected", so a selection change touches two rows, not all of them.

## 5. Our prototype engine compared with Lit, point by point

*`prototype/engine/` (signals.js 196, template.js 618, element.js 112; 926 lines, 4.7 KB gz in all)
implements Lit's essential pipeline faithfully, makes three good departures (signals native in holes,
no directive classes, LIS keyed moves without Lit's marker leak), and has six defects I reproduced in
Chromium that must be fixed before it carries the web view. None of them needs more than about 30 lines.*

Probes were run against the files as they are now (`~/.cache/dplanner-lit-research/probe*.html`, Chromium 152).

### 5.1 Same as Lit

- **The call-site cache.** `cache = new WeakMap()` keyed by `strings`, with `prepare` and `compile` running once per call site.
- **One HTML string per template**, built by a char-level tokenizer, parsed once into `<template>`, with SVG wrapped and unwrapped.
- **A TreeWalker (`SHOW_ELEMENT | SHOW_COMMENT`)** records node indices at compile time and replays them over `importNode` clones.
- **The same part vocabulary:**
  - child;
  - attribute, including multi-hole interpolation with statics;
  - `?bool`;
  - `.prop`;
  - `@event`, with the part as `handleEvent` and `this` set to the host;
  - an element hole handing over the element, standing in for `ref`.
- **ChildPart covers** text, nested template (same template means update, otherwise replace), Node, iterable (positional), and `nothing` / `null` / `undefined` / `false` (clear).
- **Values never parse.** Text goes through Text nodes and attributes through `setAttribute`.
- **Raw-text holes are refused**, with the remedy "bind .value", and a hole in a tag name throws.
- **Base element:**
  - declared props with String/Number/Boolean attribute converters and reflection;
  - pre-upgrade instance properties adopted;
  - `adoptedStyleSheets` from a cached `css` tag;
  - a microtask-coalesced render;
  - an `updateComplete` promise.

### 5.2 Different from Lit, and better for us

1. **Signals are native in holes.** `Part.set` checks `isSignal(value)` and subscribes that part alone.
   - This replaces `@lit-labs/signals`' `watch` directive, the `SignalWatcher` mixin, the polyfill (3.2 KB) and AsyncDirective. The 8–11.5 KB gz of signals-on-Lit becomes part of 4.7 KB.
2. **There is no directive class system and no `noChange`.**
   - `ref` is an element hole.
   - `classMap` and `styleMap` become a `class=${string}` or a `.className` / `style` binding plus `?attr` and `:state()`.
   - `until` and `asyncReplace` become a signal set by the promise.
   - `cache`, `guard` and `keyed` are not needed.
   - The only extension point is "a value that is a signal", which keeps the engine closed and small.
3. **Bound attributes are cut out of the emitted HTML** and the element gets one `dp$` marker attribute.
   - Lit renames the attribute instead. Cutting it out removes the case-folding problem and the duplicate-attribute class of bugs outright, with no dev-mode count check needed.
4. **Child holes clone a start/end comment pair** (`<!----><!--dp$-->`), so a hole needs no `createComment` at instance time.
5. **The keyed `repeat` keeps the longest increasing run of old positions in place and moves only the rest.**
   - A swap moves two rows. Without the LIS, a naive backward walk took 214 ms for a 5,000-row swap.
   - It throws on duplicate keys, where Lit silently misbehaves.
   - It removes *both* markers of a removed row, so it does **not** have Lit 3.3.x's leak.
6. **`PropertyPart` compares against the element's live property.** This is Lit's `live()` behaviour by default, which is right for inputs the user edits.

### 5.3 What it skips, rightly

- MathML;
- static/`literal` templates;
- SSR/hydration and compiled templates;
- ShadyDOM `wrap()`;
- the Trusted Types policy and sanitizer hooks (add the policy only if we adopt a TT-enforcing CSP; about 5 lines);
- event listener options (`capture`, `passive`, `once`);
- `shouldUpdate`, `willUpdate` and controllers (signals and computeds cover them);
- `@lit/context` (pass signals down, or add a 30-line context-request event if needed);
- `@lit/task` (a signal plus an AbortController);
- the dev-mode warning catalogue.

### 5.4 Defects found (each reproduced)

1. **A missing `raw` check lets XSS through.** `render(html(['<img src=x onerror="window.PWNED=1">']), el)` executed the handler (probe: `img=true pwned=true`).
   - Lit refuses any `strings` without an own `raw` (§1.5). It matters the moment any code path builds a `strings` array from data.
   - Fix (one line in `compile`): `if (!Array.isArray(strings) || !Object.hasOwn(strings, "raw")) throw …`.
2. **SVG `<title>` holes are refused.** `RAW_TEXT` treats `title` as raw text even inside `svg`, so ``svg`<rect><title>${tip}</title></rect>` `` throws "cannot sit inside <title>: bind .value instead".
   - SVG `<title>` is the standard hover tooltip for a graph or Gantt drawing, so we will hit this.
   - Fix: apply `RAW_TEXT` only when not inside `<svg>`/`<math>`, tracking the depth of foreign content, or at least when compiling an `svg` literal.
3. **Computeds never unlink, so per-row computeds leak.**
   - After rendering 5 rows with `class=${computed(() => sel.value === r.id ? "sel" : "")}` and then removing all rows, `sel.subs.size` is still 5.
   - A Computed subscribes to its sources and never leaves when its own subscribers go. Every selection change keeps visiting every computed ever created, and none of them can be collected.
   - Fix (about 10 lines, as in preact-signals): when `subs` becomes empty after a `delete`, a Computed drops its own deps and resets to `"never"`. Apply this in `run` cleanup and in `Effect.dispose`.
4. **Disconnecting an element does not dispose its part tree.** `disconnectedCallback` disposes only the outer render effect.
   - A signal bound in a hole keeps updating the detached shadow DOM. Probe: after `el.remove()` and a write, the hole read `b` and the signal still had 1 subscriber.
   - This is exactly the job Lit's AsyncDirective connection bookkeeping does. Our minimal answer is ownership without reconnection:
     - on disconnect, dispose the root part's tree (`part.dispose()` recursing as `clear` does) and drop the root;
     - on connect, render afresh.
   - Moves inside a list should not trigger this at all: use `moveBefore` (next point) and implement `connectedMoveCallback() {}` so a moved element is not torn down.
5. **A keyed move loses focus.** `moveBefore` in template.js uses `ref.before(...nodes)`, which is remove plus insert.
   - Probe: focusing the first row's button and rotating the list left `document.activeElement` = `BODY`. A row on the kept LIS run did keep focus.
   - The code comment on `repeat` ("rows keep … focus, and running transitions") is therefore only true for rows that stay.
   - For a keyboard-driven table that re-sorts while the user is on a row, this is a real bug.
   - Fix: when `"moveBefore" in Element.prototype` (Chrome 133+, Firefox 144+), move with `parent.moveBefore(node, ref)`; in Chromium 152 the probe confirmed focus is kept. Elsewhere (Safari), remember `document.activeElement` if it is inside the moved range and refocus after the move.
6. **Commits are not error-safe.**
   - Rendering into a container whose children were replaced from outside threw `Cannot read properties of null (reading 'remove')`.
   - The next render threw `… reading 'prepared'`, because `clear()` had died halfway and left `kind = "template"` with `instance = null`.
   - Lit gives a clear dev error ("This ChildPart has no parentNode") instead.
   - Fix: check `this.end.parentNode` at the top of `commit` and throw a clear error. In `#template` and `#repeat`, set state only after the DOM work succeeds, or reset `kind` in a `finally`.

### 5.5 Smaller things worth doing

- **`#text` reads `this.start.nextSibling.data` from the DOM on every update.** Keep the last committed value and compare in JS, as Lit does. In my own prototype this one change took a 5,000-row no-op re-render from 9 ms to 1.9 ms. Ours measures 3.2 ms for 5,000×4 cells; the main session's script-only "update every 10th" is 2.4 ms against Lit's 0.46.
- **`#repeat` builds `oldIndex` (a Map over every part) and runs the LIS on every call.** Lit's head/tail skip makes the common edits (append, remove one) nearly free. The main session measured remove-one at 1.7 ms of script against Lit's 0.3. Add prefix and suffix skipping before the LIS (about 15 lines), then run the LIS only on the middle.
- **`AttributePart.set` tears down and recreates its effect on every parent render**, even when the same signal is passed again. `Part.set` has an identity check; add one here.
- **Signals:**
  - there is no cycle detection (a computed reading itself overflows the stack);
  - an exception in one effect during the drain leaves later effects queued until the next batch, so wrap each `flush()` and `reportError`;
  - un-batched writes run effects synchronously, which is fine, but say so in the API docs.
- **`MARK = "dp$"` is fixed.** An author comment `<!--dp$-->` or an attribute named `dp$` would be misread. Lit randomises its marker per load; a per-load suffix costs nothing.
- **Event options:** `passive` matters for wheel and touch handlers on a scrolling table. Accept `{handleEvent, passive}` objects as Lit does, or document `addEventListener` in `connected()`.
- **Class fields shadowing props** (`count = 0` in a subclass) silently break reactivity. Lit throws in dev mode; a cheap check in `DpElement`'s constructor (`Object.hasOwn(this, name)` after `super()` cannot see subclass fields, so check in `connectedCallback`) would catch it.
- **A selection helper:** `selector(sourceSignal)` returns `isSelected(key)` as a signal per key, so one change notifies two rows (Solid's `createSelector`, about 15 lines).

### 5.6 Judgement

- **The prototype is the right engine.** It has the right size, the right model, and departures from Lit that suit DPlanner.
- **What separates it from production is lifetime discipline, not features:**
  - items 3–5 of §5.4 (unlinking, disposal on disconnect, state-preserving moves);
  - the two correctness fixes, items 1–2;
  - error-safety, item 6.
  - These are exactly the areas where Lit spends its complexity (AsyncDirective, `repeat`), and where Lit itself currently has a bug.
- With the fixes, the engine stays under about 1,000 lines. It needs a test per defect above, added to `prototype/tests/engine.test.js`.

## 6. Verdict and the proposed minimal engine

*Build it. Pick Lit's architecture (call-site cache, markers, parts, keyed repeat, microtask-batched
element) and preact-signals' reactive core. Write both ourselves, and borrow no code.*

**API surface:**

```js
// template.js
html`…`, svg`…`               // → TemplateResult (class instance; instanceof-checked; strings must have own `raw`)
render(value, container, {host}) → root part   // part.dispose() to tear down
repeat(items, key, template)  // keyed, LIS moves, moveBefore when available
nothing                       // optional alias of null in child/attr holes
css`…`                        // → cached CSSStyleSheet
// holes: text | ${tpl} | ${node} | ${iterable} | ${signal}   attr=${v}  ?bool=${v}  .prop=${v}  @event=${fn}  <el ${el => …}>

// signals.js
signal(v, {equals}), computed(fn, {equals}), effect(fn, {schedule}) → dispose,
batch(fn), untracked(fn), isSignal(v), selector(signal) → key => boolean signal

// element.js
class DpElement extends HTMLElement {
  static props = { name: { type, value, attribute, reflect } };
  static styles = [sheet]; static shadow = true;
  render(); connected(); disconnected(); updated(); emit(type, detail); updateComplete;
}
```

**Line budget**, as code lines without comments:

| Piece | Lines |
|---|---:|
| Tokenizer and compile | ≈ 200 |
| Parts | ≈ 200 |
| `repeat` with prefix/suffix and LIS | ≈ 100 |
| Signals with unlinking | ≈ 180 |
| Element | ≈ 110 |
| Selector and small helpers | ≈ 30 |
| **Total** | **≈ 800–850** |

Tests are of the same order.

**Skip:**

- the directive and AsyncDirective API;
- `noChange`;
- static templates;
- MathML;
- SSR/hydration;
- polyfills and ShadyDOM;
- decorators;
- controllers, context and task as libraries;
- `classMap` / `styleMap` / `cache` / `until` / `guard` / `asyncAppend` / `live`, because the defaults cover `live` and the rest map onto signals or CSS.

**Borrow as ideas, with credit in a file header as our prototype already does:**

- from Lit (BSD-3-Clause), the template and part design;
- from preact-signals (MIT) and alien-signals (MIT), the push-pull versioned graph and unlink-on-last-subscriber;
- from Solid (MIT), `createSelector`;
- from ivi/Inferno-style list diffing, LIS.

Reimplementing ideas carries no licence obligation. If any *code* were ever copied from Lit, BSD-3 requires keeping its copyright notice and licence text. `signal-polyfill` is Apache-2.0 and carries a patent grant; the others carry none.

**Do not:**

- depend on `lit` (pinned or not): §1.6's open regression shows the cost of tracking upstream in exactly the 100 lines we would want to control;
- use a DOM-walking interpreter (`new Function`, CSP);
- adopt a compiler (Solid, Stencil), which breaks "no build step".

**Keep the door open.** Use Lit's and the DOM Templating proposal's vocabulary (`.prop`, `?bool`, `@event`, ChildPart, `render(value, container)`). If `DOMTemplate.html` or TC39 Signals ever ship, `template.js` and `signals.js` become thin adapters.
