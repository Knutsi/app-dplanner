# Interaction patterns for DPlanner's web design system

Research notes, 2026-10-12. Sections 1–12 plus a combined rule list. Sources inline. **[V]** = a
number checked against the source on 2026-10-12; unmarked numbers are long-standing platform
values from memory and worth a second look before they are frozen into tokens (especially the
Carbon row heights and the Material 3 and Fluent 2 duration scales).

## Summary

1. **One command registry, many surfaces.** Menubar, context menu, toolbar, palette, cheat-sheet and touch sheets all render the *same* commands, each with an `enabled(ctx)` / `visible(ctx)` predicate evaluated against a context built from the focused/selected URI (VS Code `when` clauses, JetBrains `AnAction.update()`, Eclipse `enabledWhen`).
2. **Stable places, changing contents.** Top-level menus never appear or vanish; menubar items *disable* (with a reason). Context menus *hide* what does not apply (Apple HIG). Contextual toolbar groups appear in a reserved slot at the end, never shifting the permanent ones.
3. **The shortcut is printed everywhere the command is**: menus, tooltips, palette rows, the `?` sheet. That is the teaching device; Superhuman and Linear rely on it, and it costs nothing.
4. **Normal mode is "focus is on a navigable surface"**, not a global state. Single-key verbs work only while a grid/canvas has focus (this is exactly WCAG 2.1.4's "active only on focus" exception), any text field turns them off, Escape always walks one level out, and a status-bar chip shows the mode and any pending prefix.
5. **Prefix keys (`g`, leader) show a which-key popup after ~400 ms**, but the pending state is shown in the status bar immediately and never times out silently.
6. **Menus via keyboard and the palette open with no animation.** Motion is reserved for *where did it go* (FLIP/View Transitions), *what changed* (a one-shot highlight), and *where it came from* (scale from trigger), at 100–250 ms, always interruptible, gone under `prefers-reduced-motion`.
7. **Compact grid: 24 px rows (28 px "comfortable"), treegrid with row focus.** Focus (the current item) and selection (an explicit set, `x`/Ctrl/Shift) are separate, as in Gmail and Linear; a non-empty selection swaps the toolbar in place for a `× N selected · actions` bar.
8. **Touch gets a different UI, not a squeezed one.** Figma, Linear and GitHub all ship a narrower *companion* on mobile; share the command registry and the model, not the layout. Detect per interaction (`pointerType`), not only by media query.
9. **Icons: one set, one grid, one stroke.** DPlanner already vendors Tabler (MIT, 24 px grid, stroke 2, ≈1.33 px at 16 px); keep it the only set, draw domain glyphs on its grid; status always coded by colour *and* shape.
10. **Feedback is inline first.** Busy states appear after 300 ms and last at least 500 ms. Toasts are only for results the user can't see; undo goes through the undo stack (Ctrl+Z) and the toast just advertises it. Background work runs in an Activity panel.
11. **Parallel work = live panes over one model.** Split panes, Space-peek, pop-outs (Document PiP where supported), a navigation history wired to the browser, and a URL for every view. In a browser tab the browser owns Ctrl+W/T/Tab, so the app needs its own tab keys.

---

## 1. Menubar and menus

*Summary: implement the APG menubar contract exactly; use a triangle-aim heuristic rather than
open/close delays for submenus; print shortcuts right-aligned in every item; keep top-level menus
fixed and disable (not hide) items whose context is missing.*

**Keyboard/ARIA contract** ([APG Menubar](https://www.w3.org/WAI/ARIA/apg/patterns/menubar/)) [V]:
- Roles: `menubar` > `menuitem` (with `aria-haspopup="menu"` + `aria-expanded`) > `menu` > `menuitem` / `menuitemcheckbox` / `menuitemradio` (`aria-checked`), `separator`. Label containers with `aria-label(ledby)`.
- Menubar is one Tab stop (roving tabindex or `aria-activedescendant`); Tab/Shift+Tab leave it and close everything.
- Left/Right move across the menubar; with a menu open, Right/Left move to the adjacent top-level menu *and keep it open*. Down/Enter/Space opens and focuses the first item; Up may open on the last.
- In a menu: Up/Down move (wrapping is optional), Home/End, Right opens a submenu, Left/Escape close one level and return focus to the parent item. Type-ahead: a printable character moves to the next item starting with it.
- **Disabled items stay focusable but cannot be activated** — so screen reader and keyboard users still discover them. Use `aria-disabled="true"`, never the `disabled` attribute (which also kills hover, so a "why" tooltip cannot show).

**Getting into the menubar from the keyboard.** On the desktop `Alt`/`F10` focuses the menubar and `Alt+letter` opens a menu via its underlined mnemonic. In a browser those keys belong to the browser (Alt+F opens Chrome's menu, F10 focuses it). Google Docs' solution is the exemplar: `Alt+/` (search the menus) and `Alt+Shift+F` for File in non-Chrome browsers. Recommendation: one non-conflicting chord focuses the menubar (e.g. `Alt+Shift+M`, or `F10` only when the installed app owns it), and show mnemonic underlines only while that chord's modifier is held — Windows has hidden underlines until Alt is pressed since Windows 2000. Mnemonics *inside an open menu* are free to use: there, plain letters are type-ahead anyway.

**Submenu hover intent.** Delays make menus feel broken; aim detection removes them. Amazon's trick: while the cursor moves inside the triangle from its position to the submenu's near corners, do not switch rows ([Kamens, "Breaking down Amazon's mega dropdown"](https://bjk5.com/post/44698559168/breaking-down-amazons-mega-dropdown)) [V]. jQuery-menu-aim's numbers: re-check after **300 ms**, **75 px** tolerance ([source](https://github.com/kamens/jQuery-menu-aim)) [V]. Without aim detection, Windows' `MenuShowDelay` default is 400 ms. Recommended: open a submenu after **~100 ms hover**, keep the current one while inside the triangle, fall back to switching after **300 ms** of no movement. Keyboard-opened submenus open instantly.

**Shortcuts in menus are the primary teacher.** Right-aligned, secondary text colour, platform glyphs (⌘⇧ on macOS, `Ctrl+Shift+` elsewhere). Sequences shown as `G then I` (Linear, GitHub). Ellipsis (`Rename…`) means "asks for more input before acting" (Apple, Microsoft convention).

**Disabled vs hidden.** Apple: in menubar menus, disable unavailable items so people learn what exists; in context menus, "Hide unavailable menu items, don't dim them" ([Apple HIG, context menus](https://developer.apple.com/design/human-interface-guidelines/context-menus)) [V]. Never hide or reorder a *top-level* menu on selection change — muscle memory is spatial. Items whose availability depends on selection stay at the same index; only their enabled state and, at most, their label noun change ("Delete Step" / "Delete 3 Steps").

**Disabled reasons.** A dimmed item with no explanation is a dead end. Show the reason in the item's tooltip and in the palette ("Needs a selected step"). The predicate returns `{enabled: false, reason}` rather than a bare boolean (see §7).

**Pitfalls:** opening menus on hover of the menubar before any click (only after one menu is open does hover switch menus — every desktop OS); animating menus that the keyboard opened; submenus deeper than one level; menus that re-render and lose the focused item when the context updates under them (freeze the context while a menu is open).

*Exemplars:* macOS menubar (Help ▸ search highlights the item in place); Google Docs `Alt+/`.

## 2. Context menus

*Summary: the context menu is the complete verb list for the thing under the pointer, ordered
primary → edit → organise → destructive, one submenu level at most. Open with right-click,
Shift+F10 and the Menu key, and a 450 ms long-press on touch, where it becomes a bottom sheet.*

- **Triggers.** `contextmenu` event (right-click; on Windows the Menu key and Shift+F10 also fire it, but handle `keydown` Shift+F10 / `ContextMenu` explicitly so it is uniform across OSes and anchors at the *focused element*, not the pointer). Same `role="menu"` contract as §1; focus the first item; Escape returns focus to the invoker.
- **Long-press.** iOS `UILongPressGestureRecognizer` defaults to 0.5 s; Android's `DEFAULT_LONG_PRESS_TIMEOUT` is **400 ms** (formerly 500) ([AOSP ViewConfiguration](https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/view/ViewConfiguration.java)) [V]. On the web: Android Chrome fires `contextmenu` on long-press, iOS Safari does not — implement a pointer timer (**450 ms**, cancel on >8–10 px movement or on scroll), set `-webkit-touch-callout: none` and `user-select: none` on the target, and give haptic/visual feedback at trigger.
- **What goes in it vs the toolbar.** Toolbar: the few most frequent verbs, visible. Context menu: *every* verb that applies to the target, including the toolbar ones (the user right-clicks to ask "what can I do with this?"). Microsoft's rule is the other direction: never put a command *only* in a context menu — it must be reachable from the menubar or palette too.
- **Ordering.** Default/primary action first (bold on Windows), then open/navigate, then create/edit, clipboard group (Cut/Copy/Paste/Duplicate), organise (move, link, status), then copy-link/URI and Properties, destructive last behind a separator. Keep the order identical for every object type so the position of "Delete" is learned once.
- **Depth.** One level of submenu maximum; a submenu with fewer than ~3 items should be inlined; one with more than ~12 should be a dialog or palette scope. Context menus show shortcuts too.
- **Multi-selection.** The menu acts on the selection if the right-clicked item is in it; right-clicking outside the selection first selects that item (Explorer, Finder, VS Code).

*Exemplars:* VS Code explorer (groups by `navigation`, `1_modification`, `9_cutcopypaste`, destructive last; `when` clauses hide inapplicable items); Finder.

## 3. Toolbars

*Summary: one Tab stop, arrows inside (APG); icon-only buttons with a tooltip carrying label and
shortcut; overflow into a "⋯" menu from the end; contextual groups appear in a reserved slot at
the end with a visible divider.*

- **Contract** ([APG Toolbar](https://www.w3.org/WAI/ARIA/apg/patterns/toolbar/)) [V]: `role="toolbar"` with a label; roving tabindex; Left/Right (or Up/Down for `aria-orientation="vertical"`), optional wrap, Home/End; remember the last-focused control. Use only for ≥3 controls. Avoid controls that need the same arrow keys; if unavoidable, one such control, last.
- **Icon-only + tooltip.** Every icon button has `aria-label`, and a tooltip showing the label and the shortcut (`Run agent  R`). Tooltips must meet WCAG 1.4.13 (dismissable with Escape, hoverable, persistent) and must also show on keyboard focus.
- **Tooltip timing.** Radix defaults: **700 ms** open delay, **300 ms** "skip delay" window in which the next tooltip opens instantly ([Radix Tooltip](https://www.radix-ui.com/primitives/docs/components/tooltip)) [V]. Win32 tooltips: initial = double-click time (500 ms), reshow 100 ms, autopop 5 s. Recommended for a dense pro tool: **500 ms initial, 0 ms while warm, warm window 400 ms**; no fade-in longer than 100 ms; on keyboard focus show after the same delay.
- **Overflow.** Measure with a `ResizeObserver`; move items from the *end* (lowest priority, not last-added) into a trailing "More" menu-button; overflowed items keep their shortcuts in the menu. Never wrap a toolbar to two lines and never scroll it horizontally.
- **Contextual groups.** Office's contextual ribbon tabs (Picture Format appears, coloured, at the end, when a picture is selected) are the exemplar: the permanent groups never move; the item-specific group appears after a divider at a fixed slot, labelled with the item kind ("Step"), and leaves without animation sliding the others.
- **Pitfalls:** toggle buttons without `aria-pressed`; tooltips that cover the next button (place below); hiding disabled toolbar buttons (which shifts positions — dim them instead).

*Exemplars:* VS Code editor title bar actions; Figma's contextual property toolbar.

### 3a. The selection bar (toolbar becomes "× 3 selected · actions")

*Summary: the best tools swap the collection's toolbar, in place and at the same height, for a
bar that reads "× N selected" followed by the actions that apply to all of them. It appears on
explicit selection, not on mere focus; Escape or × clears it.*

How the leaders do it:
- **Material contextual action bar.** "A top app bar can transform into a contextual action bar" for selected items; anatomy: a **close (×) button in place of the navigation icon, a contextual title (the count), contextual actions, optional overflow**; it stays "until an action is taken or it is dismissed" ([M2 top app bar](https://m2.material.io/components/app-bars-top)) [V]. Android's `ActionMode` overlays the normal bar — same place, different colour.
- **Google Photos / Drive.** The top bar (Photos) or the filter/toolbar row above the file list (Drive) turns into `× N selected` with the item actions on the right — the × at the far left exactly where the eye starts. Replaced in place; nothing below moves.
- **Gmail.** The toolbar above the list keeps its master checkbox but swaps refresh/more for Archive, Report, Delete, Mark, Snooze, Move, Label. Select-all across pages: the header checkbox selects only the visible page (50), then a banner offers "All 50 conversations on this page are selected. **Select all conversations that match this search**", which then confirms the larger count ([Mailmeteor guide](https://mailmeteor.com/blog/how-to-select-all-in-gmail)) [V]. Keyboard: `j/k` move the cursor, `x` selects — focus and selection are separate.
- **GitHub issue/PR list.** The list's header row (counts and filter dropdowns) is replaced by "N selected" plus bulk dropdowns (Mark as, Label, Assign, Projects, Milestone) — the bar *is* the column header, so it never covers a row.
- **Linear.** A floating bar centred at the bottom of the list ("N selected", the bulk actions, ×) rises when the first issue is selected with `x`; Escape clears. It overlays rather than replaces, so the view header (filters, display) stays usable while selecting.
- **iOS edit mode.** An explicit **Select** button enters the mode; rows grow selection circles; the navigation bar title becomes "N Selected" with **Select All** and **Done**; actions sit in a bottom toolbar. The mode is explicit because a tap otherwise opens.

**Recommendation for DPlanner:**
- **Focus is the current item; selection is an explicit set** (Gmail/Linear). Arrow keys, `j/k` and a plain click move the *focus*, which drives the context (detail panel, contextual toolbar group, single-item verbs). `x`/Space, Ctrl/⌘+click, Shift+click, or a row checkbox add to the *selection*. Commands act on the selection if it is non-empty, else on the focused item. Without this split the toolbar would flip to a selection bar on every arrow press.
- **Desktop: replace in place.** When the selection becomes non-empty, the view's toolbar is replaced by the selection bar *in the same slot and at the same height*: `[×] 3 steps selected · [Status ▾] [Move ▾] [Run agent] … [⋯]`, × first (Material/Photos/Drive position). No layout shift, no occlusion of rows. The count names the kind ("3 steps").
- **Touch: a bottom bar** (iOS edit mode / Linear's floating bar position), because the thumb is there and the top is far.
- **Select-all.** Ctrl/⌘+A selects all *rows matching the current filter*; if some matching rows are not shown (collapsed subtrees, a paged source), the bar says so and offers the widening explicitly, Gmail-style: "All 40 visible selected · Select all 312 matching". Never select hidden items silently — a bulk delete over things the user cannot see is the worst failure here.
- **Clearing.** Escape (when focus is in the list or the bar), the × button, clicking empty space, or completing a bulk action that removes the items. After a non-destructive bulk action keep the selection (the user often applies a second action).
- **Keyboard/ARIA.** The bar is a `role="toolbar"` labelled "Selection actions"; it appears without taking focus; the count is announced through a polite live region ("3 steps selected"); when it disappears while focused, focus returns to the list's focused row. Its actions carry the same shortcuts as the context menu, which already act on the selection.
- **Animation.** Gmail and GitHub swap instantly; Material crossfades and recolours the bar. Use a **100 ms crossfade, no movement, keyboard-initiated swaps instant**; the count changes without animation. The bar's background shifts to a selection tint so the mode change registers peripherally.

## 4. Command palette

*Summary: Ctrl/Cmd+K (plus Ctrl+Shift+P as an alias), opens instantly, fuzzy-matched, recents
first, every row shows its shortcut, and it is scoped to the current selection — the selection is
shown as a chip at the top and Backspace on an empty query removes it.*

- **Matching.** Subsequence fuzzy match scored by: contiguous runs, word-start/camelCase hits, prefix of the label, then recency/frequency boost. Highlight matched characters. Match aliases/synonyms ("remove" → Delete) and the menu path ("Edit ▸ Delete").
- **Recents.** Empty query shows *recently used* first (VS Code), then the commands applicable to the selection. Store per-user usage counts locally.
- **Self-teaching.** The shortcut sits right-aligned on every row: Superhuman's help centre describes its Cmd+K as the way shortcuts are learned — "watch the letter that appears on the right" ([Superhuman help](https://help.superhuman.com/hc/en-us/articles/45191759067411-Speed-Up-With-Shortcuts)). VS Code's prefixes (`>` commands, `@` symbols, `:` line, `?` lists the prefixes) make the palette teach its own grammar.
- **Scoping / "actions on the selected thing".** Linear's Cmd+K acts on the selected issues and shows them at the top; Raycast's Cmd+K opens an *action panel* for the selected result (Enter = primary, Cmd+Enter = secondary). Recommended: palette opens with a context chip (`Step 4: Write tests ✕`) built from the selection URI; commands that apply rank first; Backspace on the empty query removes the chip and widens to global commands; a sub-palette (e.g. "Set status ▸") is a second page in the same box, not a new dialog.
- **Inapplicable commands.** Hide them by default (VS Code filters palette entries by `when`); if the query is an exact label match, show the row dimmed with its reason instead of "No results".
- **ARIA:** `role="combobox"` input with `aria-controls` a `role="listbox"`, `aria-activedescendant` for the highlighted option; focus never leaves the input. Up/Down/Enter, Escape closes (or pops a page), Tab may complete.
- **Pitfalls:** animation on open (Kowalski: Raycast opens hundreds of times a day with no animation — "the optimal experience" ([You Don't Need Animations](https://emilkowal.ski/ui/you-dont-need-animations)) [V]); results reordering under the cursor as async results arrive (append only, or freeze after the first 150 ms).

## 5. Keyboard-first and self-teaching; modes

*Summary: a discoverability ladder (menus → tooltips → palette → `?` sheet → which-key → hold-
modifier overlay) gets users from mouse to keys. A "normal mode" is safe when it is bound to focus
on a navigable surface, shown in a persistent indicator, exited by Escape and by entering any text
field, and can be turned off (WCAG 2.1.4).*

**The ladder**, cheapest to richest:
1. Shortcut printed in menus and context menus.
2. Shortcut in tooltips.
3. Shortcut on every palette row (Superhuman, Linear).
4. `?` opens a searchable cheat-sheet overlay grouped by area, showing *the shortcuts valid in the current context first* (GitHub, Gmail, Linear all use `?`).
5. Prefix popups (which-key): after typing `g`, a small panel lists the continuations.
6. **Hold-the-modifier overlay.** iPadOS shows the app's command list while ⌘ is held; ExposeHK (Malacria et al., CHI 2013) showed that revealing hotkeys on the toolbar while a modifier is held raised hotkey adoption substantially. Office KeyTips (press Alt, letters appear on every ribbon control) and Vimium's `f` link hints are the same idea for *every* visible control. Recommended: holding Ctrl/⌘ for **≥600 ms** with no other key draws shortcut badges on the visible toolbar buttons and focused surface.
7. **Nudges** ("you did that with the mouse 3 times — the key is D"). Evidence is mixed: Grossman, Dragicevic & Balakrishnan, "Strategies for accelerating on-line learning of hotkeys" (CHI 2007) found feedback after a mouse selection (especially audio) and making the menu path costlier increased hotkey use; JetBrains' *Key Promoter X* plugin does exactly this and is popular, but in-product it irritates when frequent. Recommended: off by default, opt-in from the `?` sheet; when on, at most one nudge per command per day, shown in the status bar (not a toast), never interrupting.

**Sequences.** GitHub (`g c`, `g i`) and Gmail (`g i`) use two-key "go to" sequences; Linear `G then I`. Vim's `timeoutlen` default is 1000 ms; Emacs which-key shows its popup after **1.0 s** idle, folke's which-key.nvim after **200 ms** ([emacs-which-key](https://github.com/justbur/emacs-which-key), [which-key.nvim](https://github.com/folke/which-key.nvim)) [V]. Kakoune/Helix show their info box as soon as a prefix is pressed. Recommended: the status bar shows `g…` **immediately**; the popup appears after **400 ms**; the pending state lasts until the next key, Escape, or a focus change — **no silent timeout**, because an invisible timeout is itself a hidden mode.

**Modes: the evidence.** NN/g: mode errors happen when "the user forgets what the current mode is" ([Modes in User Interfaces](https://www.nngroup.com/articles/modes/)) [V]. Raskin (*The Humane Interface*, 2000) defines a mode by two conditions — the state is *not the locus of attention* and the same gesture gives different results — and recommends quasimodes (spring-loaded modes held by a key), which NN/g calls "a major exception to the rule that modes cause usability problems" ([Spring-Loaded Modes](https://www.nngroup.com/articles/spring-loaded-modes/)) [V]. The fix for Raskin's first condition is to put the mode *in* the locus of attention: the focus ring and the caret, not only a status bar.

**WCAG 2.1.4 Character Key Shortcuts** ([Understanding 2.1.4](https://www.w3.org/WAI/WCAG22/Understanding/character-key-shortcuts.html)) [V]: a shortcut made only of letter/number/punctuation/symbol keys must be able to be turned off, remapped to include a modifier, or be active only when its component has focus. Sequences count. The reason is speech input: dictated words become keystrokes. GitHub's answer is a "Character keys" toggle in Accessibility settings ([GitHub Docs](https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-user-account-settings/managing-accessibility-settings)) [V].

**Recommended design for DPlanner's normal mode:**
- **Normal mode = keyboard focus is on a navigable surface** (graph canvas, step grid, project list) — that is the "active only on focus" exception, so it is compliant by construction. Single-key verbs are registered *on the surface*, not on `document`.
- **Insert/edit mode = focus is in an editable element** (`input`, `textarea`, `select`, `[contenteditable]`, or anything with `role=textbox/combobox`). The key handler checks `event.target` and also ignores `event.isComposing` / keyCode 229 (IME). Entering a field needs no command — clicking or pressing `Enter`/`F2`/`e` on the item enters it.
- **Escape ladder:** in a field, Escape cancels the edit and returns focus to its item (normal mode); in normal mode, Escape closes the innermost popover → clears a pending prefix → clears multi-selection → moves focus to the surface's parent. Escape never navigates away or discards data silently.
- **Indicator, in two places:** a status-bar chip on the far left (`NAV` / `EDIT` / `g…`), coloured per mode (Helix colours its `NOR/INS/SEL` statusline segment with `color-modes`; Vim prints `-- INSERT --`); *and* a distinct focus treatment — a 2 px accent ring on the focused item in normal mode, a text caret in edit mode — because the focused item is where the user is looking.
- **Settings:** a "Single-key shortcuts" toggle (default on), remapping via the same registry, and Ctrl/⌘ chord equivalents for the most important single-key verbs so turning them off loses little.
- **Layout-aware matching:** match letters and symbols by `event.key`, not `event.code` — `?` and `/` need Shift on a Norwegian keyboard. Never bind `Ctrl+Alt+letter` (AltGr on Windows emits Ctrl+Alt), and never shadow the browser's own chords (Ctrl+W/T/N/L/Tab).
- **Quasimodes for transient tools:** hold Space to pan, hold Alt to show link handles — release ends the mode.

## 6. Compact tables, grids, tree-tables

*Summary: use a plain `table` when cells are read-only and there is no arrow navigation; use
`grid`/`treegrid` with row focus for the step list. 24 px compact rows, tabular numerals right-
aligned, sticky header, focus separate from selection (Gmail/Linear), actions on the focused or
selected row.*

- **Table vs grid.** `role="grid"` makes the widget one Tab stop with arrow-key cell/row navigation ([APG Grid](https://www.w3.org/WAI/ARIA/apg/patterns/grid/)); use it only when the user operates within it. Steps form hierarchies, so **`treegrid` with row focus** ([APG Treegrid](https://www.w3.org/WAI/ARIA/apg/patterns/treegrid/)) [V]: Right expands a collapsed row (or moves to first child), Left collapses (or moves to parent), Up/Down rows, Home/End, Ctrl+Home/End, Enter = default action. Roles: `treegrid` > `row` (`aria-level`, `aria-expanded` on parents, `aria-setsize`/`aria-posinset` when virtualised, `aria-selected`) > `gridcell`/`rowheader`/`columnheader`. `aria-multiselectable="true"`. `aria-rowindex`/`aria-rowcount` when rows are virtualised.
- **Graphs aren't trees.** A step with several prerequisites appears once under its primary parent; the other edges are shown as a link glyph in a column, not as duplicated subtrees (duplicate rows break selection identity).
- **Row height.** IBM Carbon data table sizes: xs **24**, sm **32**, md 40, lg **48** (default), xl 64 ([Carbon data table](https://carbondesignsystem.com/components/data-table/style/)). Excel's default row is 15 pt = 20 px at 96 dpi; VS Code's lists use 22 px rows. Recommended: **compact 24 px, comfortable 28 px**, 13 px text, 16 px icons, 8 px horizontal cell padding. On touch, 44 px (§8).
- **Selection model.** Two conventions exist: Explorer/Finder/VS Code, where focus and selection move together (click selects, arrows select), and Gmail/Linear, where a cursor (focus) moves freely and selection is an explicit set. Because the toolbar turns into a selection bar (§3a), use the **Gmail/Linear split**: click, Up/Down and `j/k` move the focus (the current item); Ctrl/⌘+click toggles, Shift+click selects anchor→target, Ctrl/⌘+Shift+click adds a range, Shift+Up/Down extend from the focused row, Space or `x` toggles the focused row; Ctrl/⌘+A selects all matching; Escape clears. Focus (ring) and selection (fill + checkbox) look different.
- **Inline actions.** Hover-revealed buttons are invisible to touch and keyboard users and make rows jump. Show row actions **on the focused/selected row** (and keep a hover affordance as a convenience only); the full set is in the context menu.
- **Sticky header** (`position: sticky; top: 0`), with a 1 px divider that appears only once scrolled.
- **Column resize:** an 8 px hit area over a 1 px divider, `col-resize` cursor, double-click auto-fits (Excel), minimum ~48 px. Keyboard: resize via the column header's menu.
- **Sorting:** `aria-sort="ascending|descending"` on exactly one `columnheader` (others omit it); a small ▲/▼ glyph after the label; click cycles asc → desc (→ none only if there is a natural order to return to). Shift+click for secondary sort is optional.
- **Numbers:** `font-variant-numeric: tabular-nums`, right-aligned, header aligned like its content, units in the header not the cells. Dates in a fixed format.
- **Truncation:** end-ellipsis for titles, **middle** ellipsis for paths/URIs/branch names (Finder); a tooltip only when actually truncated; the full text is always in the detail panel.
- **Virtualisation:** cheap below ~200 rows; measure, but plan to virtualise above ~500 rows or ~5 000 cells. Keep fixed row heights so the math is trivial, overscan ~10 rows, and keep the focused row mounted even when scrolled away.

*Exemplars:* VS Code's explorer tree (type-ahead filter, `aria-level`), Linear's issue list (`j/k`, `x`, Shift-extend), Excel.

## 7. Selection → context → commands

*Summary: every pro tool converges on the same architecture — commands declared once with
predicates over a context object; surfaces evaluate them when the context changes. Make the
predicate return a reason, not a boolean.*

- **VS Code:** context keys (`editorFocus`, `listFocus`, `resourceExtname`, custom ones via `setContext`) and `when` expressions with `&& || ! == =~ in`; menus and keybindings filter by `when`, commands also have `enablement`. *Developer: Inspect Context Keys* shows the live context ([when clause contexts](https://code.visualstudio.com/api/references/when-clause-contexts)) [V].
- **JetBrains:** `AnAction.update(AnActionEvent)` reads the `DataContext` (the selected element, project, editor) and sets `presentation.isEnabled/isVisible`; it is called often, so it must be fast, and `getActionUpdateThread()` chooses background or UI thread.
- **macOS:** the responder chain finds the first object that implements the action (focus decides which object answers Copy); `validateMenuItem:`/`NSMenuItemValidation` enables items just before a menu opens.
- **Eclipse:** commands (abstract), handlers (implementations) with core expressions `activeWhen`/`enabledWhen` over variables such as `selection` and `activePart`.

**For DPlanner:** the context is `{focusSurface, focused: URI, selection: URI[], kind, …facts}` derived from `dplanner://project/x/step/y`. A command is `{id, label, icon, keys, group, when(ctx) → visible, enabled(ctx) → true | {reason}}`. Recompute menubar/toolbar on context change (debounced to one frame); menus re-evaluate on open (the macOS approach — cheap and always fresh); the palette evaluates lazily per row. Freeze the context while a menu or palette is open. Communicate disabled reasons in the menu tooltip, the palette row, and when the user presses the shortcut anyway (a brief status-bar message: "Run agent needs a step selected") — a pressed shortcut that does nothing silently is the worst case.

## 8. Touch and mobile

*Summary: the leaders ship a different, narrower mobile UI — share the command registry, the
model and the icons, not the layout. Touch targets 44 px; bottom sheets replace context menus,
a bottom action bar replaces the toolbar; detect input per interaction.*

- **Evidence for two UIs.** Figma's mobile app views, comments and mirrors; design editing is not supported ([Figma help](https://help.figma.com/hc/en-us/articles/1500007537281-Guide-to-the-Figma-mobile-app)) [V]. Linear Mobile is native Swift/Kotlin, "purpose-designed for 'away from keyboard' workflows" — inbox, triage, quick capture ([linear.app/mobile](https://linear.app/mobile)) [V]. GitHub Mobile centres on notifications and reviews. Notion is the counter-example — one block editor everywhere — and its dense pages are the weakest part of its mobile experience. Conclusion consistent with the owner's preference: **adaptive** (a different component tree) rather than **responsive** for the planner; the mobile UI does review/triage/status/agent supervision, not graph editing.
- **Targets.** Apple 44×44 pt, Material 48×48 dp; WCAG 2.5.8 (AA) minimum 24×24 CSS px or 24 px spacing circles ([Understanding 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)) [V]. The desktop's 24 px rows meet 2.5.8 only if the row is the target; small icon buttons inside need the spacing exception. Touch UI: 44 px minimum.
- **Context menu → bottom sheet** (Material 3 bottom sheet; iOS sheets with detents): opened by long-press or a "⋯" button, same command list and order, large rows with icons, drag handle, swipe-down or backdrop tap to dismiss.
- **Toolbar → bottom action bar** of ≤5 actions, with "More" opening the sheet; selection mode turns it into a contextual bar ("3 selected · Status · Move · ⋯").
- **Swipe actions** (iOS Mail, Gmail, Linear inbox): leading = non-destructive (done/snooze), trailing = destructive; partial swipe reveals, full swipe commits, always undoable. Never the only route to an action.
- **Detection.** Media queries `(hover: hover) and (pointer: fine)` for the primary input, `(any-pointer: coarse)` for "a touchscreen exists". Choose the *UI* at startup from the primary input and viewport (and let the user switch), but adapt *per interaction* with `PointerEvent.pointerType` — a touch on a touch-laptop gets a bigger hit-slop and a long-press menu; an iPad with keyboard and trackpad reports `pointer: fine` and should get shortcuts.

## 9. Motion

*Summary: motion explains change — where it went, what changed, where it came from — at
100–250 ms, ease-out on entry, never blocking input, and never on things done hundreds of times a
day. Reduced motion replaces movement with an instant change or a short fade.*

**Numbers.**
- NN/g: most UI animations should last **100–500 ms** ([Animation duration](https://www.nngroup.com/articles/animation-duration/)) [V].
- Fluent/WinUI: `ControlFasterAnimationDuration` **83 ms**, `ControlFastAnimationDuration` **167 ms**, `ControlNormalAnimationDuration` **250 ms**; entry easing `cubic-bezier(0,0,0,1)`, exit `cubic-bezier(1,0,1,1)` ([Timing and easing](https://learn.microsoft.com/en-us/windows/apps/design/motion/timing-and-easing)) [V]. Fluent 2 web tokens: ultraFast 50, faster 100, fast 150, normal 200, gentle 250, slow 300, slower 400, ultraSlow 500 ms; `curveEasyEase` `(0.33,0,0.67,1)`.
- Material 3: durations short1–4 = 50/100/150/200 ms, medium1–4 = 250–400 ms; easing *standard* `(0.2,0,0,1)`, *standard decelerate* `(0,0,0,1)`, *standard accelerate* `(0.3,0,1,1)`, *emphasized decelerate* `(0.05,0.7,0.1,1)` [V], *emphasized accelerate* `(0.3,0,0.8,0.15)` ([M3 easing and duration](https://m3.material.io/styles/motion/easing-and-duration/tokens-specs)).
- Exits are faster than entries (≈ 2/3 the duration), ease-in/accelerate.

**Rules from practitioners.**
- Kowalski: decide by frequency — actions done 100+ times a day (palette, shortcuts, core navigation) get **no** animation; keyboard-initiated actions should never be animated ([You Don't Need Animations](https://emilkowal.ski/ui/you-dont-need-animations)) [V]. His Sonner/Vaul work shows the craft for the rest: interruptible CSS transitions rather than keyframes, origin-aware scaling, no `scale(0)` entries (start at ~0.95).
- Apple, *Designing Fluid Interfaces* (WWDC 2018): animations must be interruptible and redirectable; respond to input immediately; the interface must never wait for an animation to finish.
- Val Head (*Designing Interface Animation*) and Rachel Nabors (*Animation at Work*): animation must have a job — orientation, feedback, relationship, attention.

**Never block input.** Commit the state change first, animate the representation; the next key acts on the new state even mid-animation. Key-repeat (holding `j`) must not animate per step — scroll/focus jumps instantly. Menus/palettes opened from the keyboard appear in ≤1 frame; pointer-opened popovers may fade/scale in ≤100 ms and close instantly on selection (keep a ~100 ms "blink" on the chosen item only if it confirms what was picked).

**Uses:**
- *Where did it go* — FLIP ([Paul Lewis, 2015](https://aerotwist.com/blog/flip-your-animations/)) or the View Transitions API (`document.startViewTransition`, same-document; Chromium, Safari 18+, recent Firefox) for reorder, move between groups, expand/collapse: 150–200 ms.
- *What changed* — a one-shot background highlight on a changed row/card from another writer (agent, CLI, other window): accent at ~20% opacity fading out over ~1 s, no movement. This is the most valuable motion for DPlanner, where agents change the plan behind the user.
- *Grouping* — staggered reveal only for first appearance of a small set: ≤ 30 ms per item, ≤ 6 items staggered, total ≤ 300 ms; never on refresh.
- *Causality* — popovers/sheets scale from their trigger (`transform-origin` at the anchor), 0.97→1, 120 ms.
- *State changes* — toggles, checkmarks, status colour: 100–150 ms.

**Reduced motion.** Under `@media (prefers-reduced-motion: reduce)` replace transforms with an instant change or an opacity fade ≤ 100 ms; keep the "what changed" highlight (it's colour, not motion) but shorten it. Provide an in-app override.

## 10. Icons

*Summary: pick one open set drawn for the size you use, keep one stroke and one grid, label icons
the first time (menus) and use icon-only only where the same icon is always labelled elsewhere;
code status by colour and shape together. DPlanner already vendors Tabler; keep it.*

| Set | Licence | Grid / style | Notes for 16 px |
|---|---|---|---|
| **Tabler** (DPlanner's set) | MIT | 24 px, stroke 2 (adjustable) | ~5,000+, very consistent; stroke 2 renders ≈1.33 px at 16 px |
| Lucide | ISC | 24 px, 2 px stroke, round | ~1,600 icons; `absoluteStrokeWidth` keeps 1–1.5 px at 16 |
| Phosphor | MIT | 256 grid, 6 weights (thin…fill, duotone) | weights give a free filled/selected state |
| Material Symbols | Apache 2.0 | variable font: weight, fill, grade, optical size 20–48 | optical size 20 is the smallest; font delivery |
| Codicons (VS Code) | CC BY 4.0 (code MIT) [V] | **16 px native** | drawn for 16, ~550 dev-tool glyphs; attribution needed |
| Remix Icon | Remix Icon License v1.0 (was Apache 2.0) [V] | 24 px, line + fill | no standalone resale, not as logos; check fit |

Sources: [Codicons repo](https://github.com/microsoft/vscode-codicons), [Remix licence notice](https://github.com/Remix-Design/RemixIcon/issues/1069), project sites for the rest.

- **DPlanner's situation.** Tabler is already vendored as SVG — 87 glyphs keyed by DPlanner's own semantic names — so the web view uses the same files and the same semantic keys; no second set. Tabler is drawn on a 24 px grid with stroke 2, which renders at about **1.33 px at 16 px**: slightly soft on 1× screens, crisp at 2×. Keep stroke 2 (the set's design weight) rather than thinning it per size, and render at exactly 16 px in menus/toolbars/rows, 20 px in touch bars, 24 px on mobile — whole-pixel sizes only, never fractional scaling.
- Domain concepts with no Tabler glyph (step, edge, aspect kinds, agent states) are drawn on the same 24 px grid with stroke 2, round caps and joins, and added under a semantic name — never borrowed from another set.
- NN/g: universally understood icons are few (home, print, search); "a text label must be present alongside an icon"; the **5-second rule** — if you can't think of an icon in 5 s, use a word ([Icon usability](https://www.nngroup.com/articles/icon-usability/)) [V]. In a pro tool icon-only is acceptable when the same icon sits *next to its label* in the menu and palette, so it is learned there, and the tooltip carries the label.
- **Status coding:** never colour alone (WCAG 1.4.1). Pair hue with shape: e.g. empty circle = not started, half circle = in progress, filled circle with check = done, triangle = blocked, dashed circle = waiting (Linear's status icons are the exemplar — shape progresses with state). Reserve red for error/destructive, and keep ≤ 6–7 status hues.

## 11. Notifications and feedback

*Summary: put feedback where the user is looking (inline, on the object); toasts only for things
off-screen or asynchronous; undo is the undo stack, toasts just advertise it; delay busy states so
fast operations show nothing.*

- **Response-time thresholds** (Nielsen): 0.1 s feels instant — no indicator; 1 s keeps flow — show a subtle inline cue; 10 s is the attention limit — show progress with an estimate and allow cancel. NN/g: spinners for ~2–10 s, determinate progress bars for longer ([Progress indicators](https://www.nngroup.com/articles/progress-indicators/)).
- **Delayed + minimum busy states:** show a busy indicator only after **300 ms**, and once shown keep it **≥ 500 ms**, so nothing flickers. Show it *on the thing that is busy* (a row's status cell, a button's icon) — not a page-wide spinner. Keep the UI interactive; disable only what would conflict.
- **Skeletons** only for the first load of a layout whose shape is known; never for refreshes (keep stale content, mark it, update in place with the "what changed" highlight).
- **Toasts:** Material snackbars without action auto-dismiss after 4–10 s; with an action they should stay until acted on or dismissed ([M3 Snackbar](https://m3.material.io/components/snackbar/guidelines)). Sonner defaults to 4 s and pauses on hover and while the tab is hidden. Recommended: bottom-left (out of the way of the right-side panels), max 3 stacked, **6 s** with an Undo action, pausing on hover/focus and while the window is blurred; `role="status"` / `aria-live="polite"`, never stealing focus; label the undo with its shortcut ("Undo  Ctrl+Z"). Because DPlanner has a single undo stack, **Ctrl+Z works after the toast is gone** — the toast teaches it; it is not the only route (which also sidesteps WCAG 2.2.1 timing concerns).
- **Errors** are inline and persistent next to their cause; a toast for an error is only a pointer to it.
- **Background changes** (agent runs, CLI writes, another window): a status-bar counter / notice bar, plus the row highlight — not a toast per event.

## 12. Doing more than one thing at once

*Summary: tabs are the coarse tool; the finer ones are split panes over one shared model, peek
without navigating, pop-out windows, drill-down columns, an activity centre for background work,
a navigation history, and a URL for every view. The rule that holds them together: every pane is
a view of the same live model, so nothing is ever stale, and exactly one pane is visibly active.*

**Tabs.** VS Code: Ctrl+Tab cycles editors "in most-recently-used order" within the group, through a switcher held open while Ctrl is down; Ctrl+PageUp/PageDown is positional; single-click opens a *preview* tab (italic) that the next single-click replaces, double-click or an edit pins it ([VS Code user interface](https://code.visualstudio.com/docs/getstarted/userinterface)) [V]. Ctrl+Shift+T reopens closed editors; `workbench.editor.limit` caps open editors. Firefox offers the same MRU-vs-positional choice as a setting. Preview tabs are the answer to "too many tabs": browsing does not accumulate.

**The browser owns the tab keys.** In an ordinary browser tab, Ctrl+W, Ctrl+T, Ctrl+N, Ctrl+Tab, Ctrl+Shift+T and Ctrl+PageUp/Down go to the browser and mostly cannot be intercepted; only an installed PWA window (and then not all of them) gets them. vscode.dev therefore binds alternative chords for its own editors. DPlanner needs a second set for in-app tabs: e.g. **Alt+W** close, **Alt+Shift+T** reopen, **Alt+[ / Alt+]** previous/next positional, **Alt+`** MRU switcher (Alt+letter collides with the browsers' own menu letters F, E, V, S, B, T, H — avoid those unshifted), with the native chords bound additionally when running as an installed app.

**Split / tiled panes.** VS Code editor groups (Ctrl+\ split, Ctrl+1/2/3 focus group n [V]); JetBrains *Split Vertically/Horizontally* opening the same file twice with separate carets; Excel's *View ▸ New Window* (same workbook, two windows, independent scroll and selection, edits shared); tmux/tiling WMs (prefix + direction to move focus, the active pane's border coloured). The common rule: **the data is shared and live, the viewport and focus are per pane.** Recommended: Ctrl/⌘+\ splits the active view (same object, new pane); Ctrl/⌘+1…4 focuses pane n; Ctrl/⌘+Alt+arrows moves focus between panes; the active pane has an accent top border and the only "live" focus ring, others dim their selection fill.

**Linked vs independent selection.** Default **independent** (VS Code, Excel). Offer **linking as an explicit, visible toggle** on a pane: "follow selection" (a link icon in the pane header), like JetBrains' *Autoscroll from Source* / VS Code's `explorer.autoReveal` and the outline's "Follow cursor". A follower pane shows *what* it follows ("Following: Graph"). Master–detail pairs (list → detail panel) are linked by construction and need no toggle.

**Peek / preview without navigating.** VS Code *Peek Definition* (Alt+F12) embeds an editor inline, Escape closes it. Linear: Space opens peek on the focused issue, Space again closes, *holding* Space peeks only while held, Up/Down move through items with the preview following, Escape closes ([Linear Peek](https://linear.app/docs/peek)) [V] — a spring-loaded mode (§5) done right. macOS Quick Look and PowerToys Peek use Space too. Hover cards (GitHub's user/issue hovercards) are the pointer-only version: show after ~500 ms, hoverable, never the only route. Recommended: **Space toggles peek, hold-Space peeks transiently, arrows keep moving the focus, Enter opens for real, Escape closes**; the peek is read-mostly and opens in the side panel, not a modal.

**Pinned, detached and popped-out.** A panel can be pinned (stays when the context changes — the "follow selection" toggle off) or popped out. `window.open` gives a real window on every desktop browser; keep it in sync through the shared model (same-origin `BroadcastChannel` or a `SharedWorker`), never by copying state into it. The **Document Picture-in-Picture API** gives an always-on-top window holding arbitrary DOM: Chrome/Edge **116+**, Firefox desktop **151+**, **not Safari, not mobile** ([caniuse](https://caniuse.com/mdn-api_documentpictureinpicture), [Firefox 151](https://www.phoronix.com/news/Firefox-151)) [V]. It suits exactly one DPlanner use: a small always-on-top agent/progress monitor while the user works in another app. Feature-detect `documentPictureInPicture` and fall back to `window.open`.

**Stacked / Miller-column drill-down.** Finder's column view: each selection opens the next column to the right, the path stays visible, Left/Right move between levels. Good for project → step → aspect, and the natural touch pattern (a navigation stack with breadcrumbs, one column at a time). On desktop show at most 3 columns, then collapse the oldest into a breadcrumb.

**Background tasks and the activity centre.** VS Code reports long work in three places — the status bar (window progress), a notification with a progress bar and Cancel, or the view that owns it ([`window.withProgress` locations](https://code.visualstudio.com/api/references/vscode-api#ProgressLocation)); JetBrains shows a status-bar progress bar with a "show all background tasks" popup and lets a modal progress be *sent to background*; Figma shows export progress in a toast. Recommended: a status-bar activity item (spinner + count while anything runs) opening an **Activity panel** listing running and recently finished tasks, each with progress, elapsed time, Cancel, and *Open result*. Progress is also shown on the object (the step's row/card). Completion: a status-bar badge always; a toast only for tasks the user started and that took > 10 s; an OS notification only if the window is unfocused and the user opted in.

**History.** VS Code: Go Back / Forward (Alt+Left/Right on Windows, Ctrl+−/Ctrl+Shift+− on macOS) over *navigation locations*, coalescing small moves. Recommended: a back/forward stack of **navigations** (opening a view, a project, a step's detail, drilling down) — not of every selection change — wired to the browser history with `pushState` for navigations and `replaceState` for selection, so the browser's own Back button and Alt+Left/⌘[ work.

**URL-addressable state.** Every view and every object has a URL derived from its `dplanner://` URI (`/project/x/step/y?view=graph`); every navigational element is a real `<a href>` so middle-click and Ctrl/⌘+click open it in a new browser tab and Copy Link works. Selection may go in the URL (`#sel=…`, via `replaceState`) so a shared link restores it; transient UI (open menus, peek) does not.

**Pitfalls.** *Too many tabs*: preview tabs, a cap with least-recently-used eviction of unpinned tabs, and the MRU switcher. *A lost focused pane*: one active-pane indicator, focus remembered per pane, Ctrl/⌘+1…n always works, and closing the active pane focuses the neighbour, never `body`. *A stale view of the same object*: every pane, peek and pop-out subscribes to the one model; an edit in one shows in all with the "what changed" highlight (§9); two panes editing the same field is resolved by the undo stack, not a dialog. *Pop-outs orphaned* when the main window closes: close them with it.

---

## Recommended rules for our system

**Commands and context**
1. Every action is one registered command `{id, label, icon, keys, group, order, when, enabled}`; menubar, context menu, toolbar, palette, `?` sheet and touch sheets are views of that registry. No surface defines an action inline.
2. The context is derived from focus + selection URIs; `enabled(ctx)` returns `true` or `{reason}`. A disabled command always has a human reason, shown in its tooltip, its palette row, and the status bar when its shortcut is pressed.
3. Freeze the context while a menu, context menu or palette is open; re-evaluate menus on open.

**Menus**
4. Implement the APG menubar/menu keyboard contract in full, including type-ahead and focusable `aria-disabled` items.
5. Top-level menus never appear, disappear or reorder. Selection-dependent items keep their position and *disable*; only their noun/count may change.
6. Context menus *hide* inapplicable items and are the complete verb list for their target, in a fixed group order: primary · open · edit · clipboard · organise · copy link/URI · destructive (last, after a separator).
7. At most one submenu level. Submenus open after 100 ms hover with triangle-aim protection (switch rows only after 300 ms without progress toward the submenu); instantly from the keyboard.
8. Every menu item shows its shortcut, right-aligned, in platform notation; sequences read `G then I`. `…` marks items that ask for more input.
9. Context menus open on right-click, Shift+F10 and the Menu key (anchored at the focused element), and on a 450 ms touch long-press cancelled by >8 px movement.

**Toolbars and tooltips**
10. Toolbars follow APG: one Tab stop, arrow keys, remembered focus, ≥3 controls.
11. Icon-only buttons have `aria-label` and a tooltip "Label  Shortcut", shown on hover *and* focus after 500 ms, instantly within 400 ms of the previous tooltip; Escape dismisses; hoverable (WCAG 1.4.13).
12. Disabled toolbar buttons dim, never vanish. Overflow collapses from the end into a "More" menu; toolbars never wrap or scroll.
13. Tools for the *focused* item appear as one contextual group in a reserved slot at the end, after a divider, labelled by its kind; permanent groups never move.
13a. A non-empty explicit *selection* replaces the view's toolbar, in the same slot and at the same height, with a selection bar: `× N <kind>s selected · actions · ⋯`, × first. Touch puts it at the bottom.
13b. The selection bar clears on Escape, ×, a click on empty space, or a bulk action that removes the items; it stays after non-destructive actions. It never takes focus; the count is announced politely; if it vanishes while focused, focus returns to the list.
13c. Ctrl/⌘+A selects what the filter matches and is visible; when more match than are shown, the bar offers "Select all N matching" explicitly. Hidden items are never selected silently.
13d. The toolbar ↔ selection-bar swap is a 100 ms crossfade with a tint change and no movement; instant when keyboard-initiated.

**Palette and keyboard**
14. Ctrl/⌘+K opens the palette (Ctrl+Shift+P as alias) in ≤ 1 frame with no animation; empty query shows recents then commands applicable to the selection.
15. The palette opens scoped to the selection, shown as a removable chip; Backspace on an empty query widens to global. Every row shows its shortcut; matches are highlighted.
16. `?` opens a searchable shortcut sheet, current-context shortcuts first.
17. Holding Ctrl/⌘ alone for 600 ms overlays shortcut badges on visible controls.
18. Match keys by `event.key` (layout-aware); never bind Ctrl+Alt+letter (AltGr) or browser-reserved chords (Ctrl+W/T/N/L/Tab, F5, F11/F12).
19. Mouse-to-key nudges are opt-in, appear in the status bar, at most once per command per day.

**Normal mode**
20. Single-key verbs are bound to a focused navigable surface (grid, canvas, list), never to `document` — WCAG 2.1.4's "active only on focus".
21. Focus in any editable element (or IME composition) disables single-key verbs automatically; no command is needed to "enter insert mode".
22. Escape always moves exactly one level outward: cancel edit → close popover → clear pending prefix → clear multi-selection → focus parent. Escape never discards data without undo.
23. The mode is shown twice: a status-bar chip (`NAV` / `EDIT` / `g…`, colour per mode) and the focus treatment on the object itself (2 px accent ring vs text caret).
24. A prefix key shows `g…` in the status bar immediately and a which-key panel after 400 ms; it waits for the next key, Escape, or focus change — no invisible timeout.
25. A setting turns single-key shortcuts off; the most important ones also have a Ctrl/⌘ chord.

**Grids**
26. Read-only tabular data is a `table`; the step list is a `treegrid` with row focus, `aria-level`, `aria-expanded`, `aria-selected`, `aria-multiselectable`, and `aria-rowindex`/`aria-rowcount` when virtualised.
27. Row height 24 px compact / 28 px comfortable / 44 px touch; 13 px text; 16 px icons; 8 px cell padding.
28. Focus is the current item, selection an explicit set (Gmail/Linear). Click, Up/Down and `j/k` move focus; Ctrl/⌘+click toggles, Shift+click selects a range from the anchor, Shift+Up/Down extend, Space or `x` toggles, Escape clears. Commands act on the selection if non-empty, else on the focused item. Focus ring and selection fill look different.
29. Row actions appear on the focused/selected row, not only on hover; all of them are also in the context menu.
30. Numbers use tabular numerals, right-aligned with their header; paths/URIs truncate in the middle, titles at the end, with a tooltip only when truncated.
31. Sticky header; one `aria-sort` column with ▲/▼; 8 px resize hit area, double-click to auto-fit. Virtualise beyond ~500 rows with fixed row heights, keeping the focused row mounted.

**Motion**
32. Durations: 100 ms micro (toggles, hover, tooltip fade), 150 ms small (popover in, highlight start), 200–250 ms layout (move/reorder/expand); exits ≈ 2/3 of entry. Nothing exceeds 300 ms except the 1 s "changed" highlight fade.
33. Easing tokens: enter `cubic-bezier(0,0,0,1)`, exit `cubic-bezier(0.3,0,1,1)`, move `cubic-bezier(0.2,0,0,1)`.
34. Animation never gates input: state commits first, animations are interruptible, key-repeat never animates, and anything done many times a day (palette, keyboard-opened menus, navigation, selection) does not animate at all.
35. Motion is only used to show where something went (FLIP/View Transitions), what changed (one-shot highlight, especially for changes made by agents or other writers), where something came from (scale 0.97→1 from its trigger), or a state change. Stagger ≤ 6 items, ≤ 30 ms apart.
36. `prefers-reduced-motion: reduce` turns movement into instant changes or ≤ 100 ms fades; an in-app setting can force it.

**Icons and colour**
37. One icon set: Tabler (MIT), vendored as SVG and keyed by DPlanner's own semantic names; new domain glyphs are drawn on its 24 px grid with stroke 2. Render at whole-pixel sizes — 16 px in menus, toolbars and rows (stroke ≈ 1.33 px), 20 px on touch bars, 24 px on mobile. No mixing of sets.
38. Icon-only only where the same icon appears labelled in a menu or palette; otherwise icon + label.
39. Status is coded by colour *and* shape; red is reserved for errors and destructive actions; ≤ 7 status hues.

**Feedback**
40. No indicator under 300 ms; once shown, a busy state lasts ≥ 500 ms and sits on the busy object. Skeletons only for first load. Toasts are for off-screen/async results only: bottom-left, ≤ 3, 6 s with Undo, pause on hover/focus/blur, `aria-live="polite"`, never focus-stealing; Undo is always also Ctrl+Z.

**Touch**
41. Touch gets its own adaptive UI (review, triage, status, agent supervision) built from the same command registry: bottom action bar (≤ 5) for the toolbar, bottom sheet for the context menu, swipe actions as shortcuts only, 44 px targets. Choose the UI from the primary pointer and viewport, allow switching, and adapt hit-slop per `pointerType`.

**More than one thing at once**
42. Every pane, peek and pop-out is a live view of the one model — never a copy — so no view is ever stale; a change made elsewhere shows with the "what changed" highlight.
43. Panes share data and keep their own viewport, focus and selection. Linking is an explicit per-pane "follow selection" toggle that names what it follows.
44. Exactly one pane is active, marked by an accent border; focus is remembered per pane; closing the active pane focuses its neighbour, never `body`.
45. Keys: Ctrl/⌘+\ split; Ctrl/⌘+1…4 focus pane n; Ctrl/⌘+Alt+arrows move between panes; in-app tabs use Alt+W close, Alt+Shift+T reopen, Alt+[ / Alt+] positional, Alt+` MRU switcher held open while Alt is down — plus the native Ctrl+W/Ctrl+Tab/Ctrl+Shift+T when running as an installed app.
46. Single-click opens a preview tab that the next single-click replaces; a double-click or an edit pins it. Unpinned tabs beyond a cap are evicted least-recently-used.
47. Space toggles peek on the focused item, holding Space peeks only while held, arrows keep moving with the peek following, Enter opens, Escape closes. Hover cards appear after 500 ms and are never the only route.
48. Long work reports on the object itself and in a status-bar activity item that opens an Activity panel (progress, elapsed, Cancel, Open result). Completion: badge always; toast only if the user started it and it took > 10 s; OS notification only if unfocused and opted in.
49. Back/Forward walks navigations, not selection changes, and is the browser history (`pushState` for navigation, `replaceState` for selection), so Alt+Left / ⌘[ and the browser's Back button agree.
50. Every view and object has a URL derived from its `dplanner://` URI, and every navigational element is a real link, so Ctrl/⌘/middle-click opens it in a new browser tab.
51. Pop-outs use `window.open`; the always-on-top agent monitor uses Document Picture-in-Picture where `documentPictureInPicture` exists (Chromium 116+, Firefox 151+; not Safari or mobile) and falls back to `window.open`. Pop-outs close with their main window.
