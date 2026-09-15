---
paths:
  - "src/dplanner/menus.py"
  - "src/dplanner/framework/{action_registry,action_menu,menubar,toolbar,palette,picker,list_rows,panels,tabs,main_window,window,dialog,table,row_well,widgets,signalling,notices,index_panel,theme_service,user_config,zoom}.py"
  - "src/dplanner/theme/**"
  - "src/dplanner/modules/{appshell,appearance,theme_omarchy,theme_system,reopen_tabs,settings,debug}/**"
  - "src/dplanner/modules/project_editor/canvas_toolbar.py"
  - "tests/test_theme.py"
  - "tests/framework/test_{action_menu,actions,menubar,toolbar,palette,picker,list_rows,panels,tabs,dialog,table,row_well,widgets,signalling,notices,index_panel,theme_service}.py"
  - "tests/modules/test_{appshell,appearance,theme_providers,reopen_tabs,debug}.py"
  - "scripts/{vendor_tabler_icons,import_omarchy_themes,render_design_example,render_about,render_icon,render_signalling}.py"
---

# Shell — seams, panes, primitives, menus, toolbars, glyphs and themes

- **Two surfaces meet at a seam, and the seam belongs to the splitter.** A 1 px `$BORDER`
  hairline inside a 7 px handle, from one `QSplitter::handle` rule that reaches every splitter
  the application builds — between two tab groups, between a panel area and the tabs, between
  two panels stacked in one area. A panel area therefore draws no border of its own: a surface
  that draws its own edge where a seam already falls gets two lines a pixel apart. **The two
  orientations are built differently on purpose** — Qt gives a horizontal handle the box model
  and fills a vertical one's whole rect, so the rule that centres a line in the first renders a
  7 px slab in the second, and nothing says so. `tests/test_theme.py` renders both rather than
  reading them. `ARCHITECTURE.md`'s *A seam belongs to the splitter* has the reasoning.
- **A primitive names its parts; a dialog is never added to a selector list.** The frame
  sets `#DialogBody` and `#DialogFooter`, the table `#Table`, and the one accent rule is
  `QPushButton#PrimaryButton` — type-prefixed and **last of the button rules in
  `theme.qss` on purpose**: a descendant rule such as `#Dialog QPushButton` outranks a
  bare `#PrimaryButton` whatever the order, and the type-prefixed one ties it and wins by
  position, which is how the file once grew an allow-list of dialog names. Every `#Name`
  the stylesheet styles must be a literal some widget sets (`tests/test_theme.py`). A
  table's row height is computed from the font and set on the vertical header, never a
  pixel token; an empty page swaps through `EmptyState.stands_in_for`; a refused primary
  is `refuse(reason)` — disabled, its name kept, the reason in the footer's status slot.
  **A dialog on screen never resizes itself**: its size is set once, before it shows, and
  a wizard's pages share it (`modules/projects/open_dialog.py`).
  **A settings page owns no outer margin**: `settings_page()` builds it, `block()` stacks
  its captioned fields, and the dialog insets it from its seam and scrolls it. **What a
  gesture came to after its dialog closed is a `notice()`**, never a `QMessageBox`; a state
  the dialog can still show goes in its own status slot. **A verb in a dialog's body is
  `quiet()`** — the footer's look through a property rule, never `#DialogBody QPushButton`,
  which would outrank every id-only button rule inside a body — and a `GlyphButton`, quiet
  already, when its glyph must follow the theme. `ARCHITECTURE.md`'s *A primitive carries
  the rule* has the reasoning.
- **A roster has three shapes, and each is a primitive.** A `Table` when a reader compares
  across rows — and a value set in the row is the column's `editor` or its `chips`, painted
  and hit-tested by the table, never a widget planted in a cell with `setCellWidget`. A
  `RichList` when there is one column of things. A `RowWell` when every row carries verbs of
  its own and has to outlive a refresh (the task and Agents browsers). A strip control that
  comes and goes is `Toolbar.set_shown`, never `hide()`, which the next reflow undoes.
  `ARCHITECTURE.md`'s *A roster has three shapes* has the reasoning.
- **A pane is marked only while there is another pane.** The accent edge on the group you are
  in appears when the window splits and goes when it stops being split — the same condition
  that installs `_ActiveGroupWatcher`, because it is the same fact. It lives on a one-widget
  `_Pane` frame, never on the `QTabWidget`: `documentMode` paints no pane frame for QSS to
  reach, a widget's children paint over anything it draws itself, and QSS on the `QTabBar`
  would replace the native rendering the dimmed titles rely on. `_drop_group` clears the mark
  itself — `_announce` short-circuits on exactly the case that needs it.
- **Where the user left off is remembered by key, per library.** Which index folders are
  open and which tabs the window had are written to the per-user store under
  `library_scope(library path)` — `framework/user_config.py`'s `get_scoped`, never the
  project directory, which is one person's window and not the plan. Both restore by **node
  id**: a remembered id that names nothing restores nothing, so a library that changed
  underneath comes back with *fewer* folders and tabs rather than wrong ones — no version
  stamp, no migration, the check is the lookup. The tree's folders are the index panel's own
  bookkeeping; tabs are `modules/reopen_tabs/`, which must be listed after every module that
  registers an activity factory and carries the *Settings ▸ Startup* switch.
  `ARCHITECTURE.md`'s *Where the user left off is remembered by key* has the reasoning,
  including why the write happens on every change rather than at close.
- **A single click in the index opens a preview tab** (`tabs.open(..., preview=True)`): at
  most one preview exists, the next preview replaces it, and a deliberate act — activation,
  or moving the tab — pins it. A preview-open of anything already open is a plain focus.
  `ARCHITECTURE.md`'s *A click is a glance* has the rules and why no timer is involved.
- **View is the window; Graph is the canvas.** The graph editor's own verbs are a
  top-level **Graph** menu — `arrange` (Sort, Layout, Divide), `regions`, `look` (Frame,
  Mark, Snap to Grid, Background — the band the strip's *Options* face renders whole) and
  `panels` (what stands beside the canvas inside the tab) — not a group inside View, which
  is about panels *around the tabs*, tabs, theme and zoom. What is *about a step* stays on Step even though it runs on the canvas:
  Connect, Link, Unlink, Isolate, Redirect and Lasso, which is also what keeps them on the
  canvas's right-click (it renders the Step menu). `ARCHITECTURE.md`'s *View is the window;
  Graph is the canvas* has the reasoning.
- **A palette row says where the verb lives.** The command palette renders the two-line
  row (`framework/list_rows.py`): the label, its **menu path** (`Graph ▸ Divide`) under it,
  the shortcut at the right and the spec's glyph at the left — because a submenu entry's
  label is written for its submenu and *Vertical* alone is a riddle. The path is
  searchable, and a match on the label always outranks one that needed it.
  `ARCHITECTURE.md`'s *The command palette says where a verb lives* has the reasoning.
- **A strip of verbs is glyphs in named bands, and a band folds whole.** The canvas strip
  is `framework/toolbar.py`'s `Toolbar`, cut into bands by `add_group(label)` —
  *Go · Step · Link · Arrange · History · Options* in `canvas_toolbar.py`'s `GROUPS` —
  because nineteen glyphs in a row are nineteen riddles and six named bands are a thing to
  learn once. **The glyph is the spec's**: every verb on the strip carries `ActionSpec.icon`
  and the module keeps no icon table, so adding a button is adding a string to `GROUPS`.
  A canvas can always be dragged narrower than its own strip, and what no longer fits leaves
  **a whole band at a time** into the `…` menu, as glyph *and* words with a rule where each
  band begins — never Qt's `»`, which pops the hidden buttons up as glyphs again. **A band's
  buttons are squares** (`CONTROL_HEIGHT` each way; a *dense* strip that is not banded stays
  narrow, because the aspect bar wants ten toggles in a 360 px dock). A control that is not a
  verb goes in the band it is *about*, as a widget — the layout picker names the arrangement,
  so it sits at the end of Arrange and hides rather than folding. **A checked verb's glyph
  takes `$ON_ACCENT`** (the palette's `BrightText`, which is what carries the theme's
  `on_accent`), which is what retired the worded switches. Debug ▸ Design Example Toolbars is
  every one of these shapes on one page.
- **A family of verbs is one toolbar button and its arrow; a band of the menus is one
  face.** `CanvasToolbar.MENUS` names the `(menu, submenu)` a button drops down — Sort,
  Divide, Redirect — so the strip carries a family in one seat and the dropdown is the
  child menu itself, rebuilt on every open, never a copy; add a verb to the submenu and the
  button offers it having touched nothing. **The arrow is a target of its own**: `ARROW_W`
  wide with a hairline parting it from the button half, and `ARROW_ROOM` of padding so the
  words step aside — a styled subcontrol is outside Qt's size hint, so widening the arrow
  without the padding paints it over the last letter. A control with **no verb under it**
  is `add_menu_face` instead — the *Options* face renders the Graph menu's `look` band
  through `fill_menu`'s `group` filter and wears the layout picker's look, because a
  hairline down its middle would say two halves do different things.
- **What DPlanner is built on is asked of the installation, never written down.**
  Help ▸ *About DPlanner…* (`modules/appshell/about.py`) is a `DialogFrame` over a `Table`:
  the list of components and what each *does here* is written — no package's metadata can
  say that — and every version and licence beside it comes from the installed
  distribution's own metadata, asked in the order the answers got vaguer
  (`License-Expression`, then `License`, then the trove classifiers). A hand-kept licence
  table drifts, and the one thing an acknowledgement must not do is claim the wrong
  licence. A component this build does not have says so in its row rather than being
  dropped. `ARCHITECTURE.md`'s *An acknowledgement is asked, not written* has the
  reasoning.
- **Find is a picker, and landing on a step is centring on it.** `framework/picker.py`
  is the one fuzzy picker — a field over `PickerRow`s, the label outranking whatever else a
  row answers to (`also`: a verb's menu path, a step's key), and `landmark` saying which
  rows a long list opens on before anything is typed. The command palette is that picker
  over the registry; `steps.find` (Ctrl+F, `/` on the canvas, Step ▸ navigate beside *Reveal in
  Graph*) is it over a project's steps, opening on the milestones and features.
  `GraphView.centre_on_step` is what a pick lands with, and `select_step` calls it, so
  `steps.reveal` centres from every view that reaches a step. Never zoom on a find — Frame
  is the verb that changes how much of the graph is in view.
- **A submenu is one child menu per title, and a group change draws the rule *inside* it.**
  Both presenters agree (`framework/menubar.py`, `framework/action_menu.py`), so two groups
  can feed one submenu — what a test *is* and what it *did* — and a group that only feeds an
  existing child menu costs the menu itself no line. Several submenus therefore sit in one
  group as a band (Step's `classify` holds Type, Status and Test), and since a child menu
  sits at its first entry's `order`, siblings in one group claim bands of it — the one place
  `order` says more than "rank inside this group", written down in `menus.py`.
  `ARCHITECTURE.md`'s *A submenu is one child menu per title* has the reasoning. **A child
  menu whose entries are data carries a `fill` instead of specs** — `DataMenuSpec`, placed
  by the same table, cleared and refilled every time it opens (Tools ▸ Agent List is the
  example; a fixed verb inside one renders through `append_action`). `ARCHITECTURE.md`'s
  *A child menu of data is rebuilt when it opens* has the reasoning.
- **The glyphs are Tabler's SVGs, vendored — a glyph key is ours, the picture is theirs.**
  `theme/glyphs/` holds the fifty-odd this application uses (MIT; the notice is beside
  them and Help ▸ About names the set and its version), fetched by
  `scripts/vendor_tabler_icons.py`, which is also where what each glyph *means* here is
  written. Adding one is a line there and running it again; changing icon sets is changing
  that file's right-hand column. Qt's SVG renderer knows no `currentColor`, so the ink is
  substituted into the source and the colour's **alpha becomes the painter's opacity** —
  get that wrong and every strip reads a shade too loud. `paint_glyph` is the one painter,
  and the canvas's medallions go through it too, so a kind's glyph on a card and the same
  kind's glyph in a menu cannot differ. Four glyphs are still painted by hand because each
  is a picture of *state*: the key badge (it draws text), the colour strip (a gradient),
  the spinner (a frame per angle) and the filter funnel (two states in one width).
- **An `ActionSpec` may carry a glyph, and only the pop-ups paint it.** `icon` is a
  `(QColor) -> QIcon` painter, rendered by `build_menu`, `append_action` and a toolbar
  dropdown — all built fresh on every open. The menu bar's QActions outlive every theme
  change, so a colour baked into one goes stale; that is the same trap as `option.palette`.
  Every Type toggle carries the glyph its node's medallion wears (`theme/icons.py`'s
  `GLYPH_ICONS` vocabulary), so the Type submenu, the aspect bar and the node agree.
- **A theme is provided, never listed.** `theme/providers.py` is the contract — a
  `ThemeProvider` is an id, a label, `refusal()` (why not on this machine, None when it
  applies, asked once per build), `groups()` (its themes, in the lists the Theme menu
  shows) and, for one that follows the desktop, `current()`; a provider follows exactly
  when it has a `current`, derived never declared. `BUILTIN` there is the fallback every
  build has (the house themes and every Omarchy default, generated from `colors.toml` by
  `scripts/import_omarchy_themes.py` through the one mapping in `theme/omarchy.py`:
  anchors from the file, ramps derived); `modules/theme_omarchy/` and `theme_system/`
  export theirs from a Qt-free `themes.py` with no window half, and the root's
  `theme_providers()` is the tuple, built once in `app.main`. The persisted
  `appearance/theme` is `system` or `<provider>/<name>`; absence means system, so a fresh
  install follows its desktop. `ThemeService` polls the serving provider at `POLL_MS` and
  applies on `!=`, holds no colour-scheme override while following (Qt echoes an override
  back), and keeps `effective_choice` as a field — no state callback reads a file.
  `modules/appearance/` renders View ▸ Theme (specs, so the palette keeps them; long
  lists nest through `submenu="Theme ▸ Omarchy"`) and Settings ▸ Appearance. Never
  construct a `ThemeService` over the machine's providers in a test: `new_session()` and
  `configure_application()` default to the built-in alone. `ARCHITECTURE.md`'s *A theme
  is provided, never listed* has the reasoning.
