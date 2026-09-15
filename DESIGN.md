# Design guidelines

How the UI should feel: calm, spacious, unhurried. These rules exist because Qt's defaults
produce cramped, administrative-looking surfaces, and because a desktop application is
judged on its spacing long before anyone reads a word of it. Every new dialog, panel and
list applies them from the start. All colours flow through the theme (`$TOKEN`s in
`theme.qss` or the palette) — the two deliberate exceptions are noted below.

**This document is the standard for all UI work in this repo.** New surfaces follow it
from the first commit; touching an existing surface includes bringing it up to these rules
(the boy-scout rule applies to pixels too — *Bringing a surface up*, at the end, is the
checklist). The rules are kept by shared **primitives**, and the primitives are shown by
**Debug ▸ Design Example…** and **Debug ▸ Design Example Table** — the table below says
which is which and where to see it. When a rule here is ambiguous, match the example; for
a panel, match the step detail panel in `modules/step_properties/panel.py`. `CLAUDE.md`
points agents here; `ARCHITECTURE.md`'s *A primitive carries the rule* is why a rule lives
in a primitive rather than in a stylesheet entry per surface.

## Primitives

What a surface is made of, where the primitive lives, and where to see it. The two example
surfaces are `modules/debug/design_example.py`; `scripts/render_design_example.py` renders
them in both themes into `docs/screenshots/f1-design-example/` (its `README.md` names each
image). Improving the system means changing the primitive and its rule together, then
re-rendering — never styling one surface by name.

| You are building | Use | In | See it |
|---|---|---|---|
| a dialog, a confirmation, a one-line prompt, what a gesture came to | `DialogFrame`, `confirm()`, `LinePrompt`, `notice()` | `framework/dialog.py`, `framework/widgets.py` | the modal: `dialog-*`, `dialog-refused-*`; every dialog on it: `s16-dialogs/` |
| a table | `Table`, `Column`, `Cell`; `key_badge_icon` for a milestone | `framework/table.py`, `theme/icons.py` | the table tab: `table-*`, `table-selected-*` |
| a value set in a table's row | `Column(editor=NumberEditor(…) \| DateEditor(…))`, and `chips=` for its usual values | `framework/table.py` | `s15-tables-and-browsers/estimates-*`, `time-*` |
| rows that each carry their own verbs and outlive a refresh | `RowWell`, `WellRow` | `framework/row_well.py` | `s15-tables-and-browsers/tasks-*`, `agents-*` |
| words in the status bar that open what they sum up | `StatusBarButton` | `framework/widgets.py` | — |
| a fact that holds until it stops holding, over the whole window | `Notice`, `NoticeBar` | `framework/notices.py` | the modal's *Signalling* block |
| a strip of verbs over a surface | `Toolbar` | `framework/toolbar.py` | the table tab's strip |
| a strip that is a tool palette | `Toolbar.add_group` | `framework/toolbar.py` | the toolbars tab: `toolbars-*`, `toolbars-folded-*` |
| a verb the registry owns, with an arrow | `Toolbar.add_action(menu=…, data_menu=…)` | `framework/toolbar.py` | the Documentation view's strip |
| a fuzzy picker over a long list | `PickerDialog`, `PickerRow` | `framework/picker.py` | the palette, and Find: `s7-graph-editor/find-*` |
| a filter on a strip | `FilterButton` | `framework/toolbar.py` | `table-filtered-*`, `filters-*` |
| a combo box on a strip or in a dialog | a plain `QComboBox` — the stylesheet dresses it | `theme.qss` | `dropdown-*` |
| "the view is rebuilding" | `UpdatingIndicator` — a `Spinner` on its own | `framework/signalling.py` | the strip's right end, `dialog-working-*` |
| "this button's work is running" | `Spinner` | `framework/signalling.py` | `dialog-working-*` |
| busy, ok, warn, error or plain information in words | `StatusLine` | `framework/signalling.py` | the modal's *Signalling* block |
| a list of facts about this machine | one `StatusLine` per row, grouped | `modules/checklist/dialog.py` | `docs/screenshots/f13-checklist/` |
| a page with nothing in it | `EmptyState(stands_in_for=…)` | `framework/widgets.py` | `table-empty-*` |
| a caption over a block, a remark under it | `caption()`, `captioned()`, `note()`, `block()` | `framework/widgets.py` | the modal's form |
| a settings page | `settings_page()`, then `block()`s — no margin of its own | `framework/settings_registry.py` | `s16-dialogs/settings-*` |
| a verb in a dialog's or a page's body | `quiet()`; `GlyphButton` when it carries a glyph | `framework/widgets.py` | `s16-dialogs/settings-openai-*`, `project-colocated-*` |
| a list of rich items | `RichList` — a `QListWidget` on `TwoLineDelegate` | `framework/list_rows.py` | `s15-tables-and-browsers/notes-*` |
| a control a strip offers only sometimes | `Toolbar.set_shown` — never `hide()` | `framework/toolbar.py` | the Time tab's day fields |
| when a rebuild is owed | `Debounced.pending_changed` | `framework/debounce.py` | — |
| a margin, a gap, a height | a token | `theme/tokens.py` (*Tokens*) | — |

## How people move through it

The rules below are derived from what a person actually does here, not from taste. Four
flows, and what each surface on the way must make unmistakable:

- **New step → details → run agent.** *New* drops a card and opens Step Details on it with
  the name selected, so typing is naming; the aspect bar says what the step is. *Run
  Agent* is a plain button on the Agent tab. When the graph says the step's prerequisites
  are not done, a confirmation names them — the count in its window title (*Run 3 Agents*),
  the step and the steps it waits on in its body — with *Run Anyway* as the primary. The
  status bar records the launch; the card's spine goes busy. Never ambiguous: **which
  steps** the shells are about, and **whether a shell opened**.
- **Import a spec → cite → plan.** The document lands in the tree and its strip says
  whether it is project-owned and editable or sourced and read-only. Selecting text and
  *Cite…* lists every feature by name with *New Feature…* last — a one-field prompt with a
  caption and a verb, never a bare input box. The strip's *Cited* count rises; the status
  bar says which feature took the passage. Never ambiguous: which feature received it, and
  whether this document can be edited.
- **A source with updates → sync.** The source's strip carries the facts (*from
  Confluence · 12 pages · fetched today*), then one line that changes with the data: *3
  pages changed at the source — Refresh to take them in* (info), *Fetching…* (busy), *12
  pages, 3 updated* (ok), a refusal with its remedy (error). *Refresh* is the strip's one
  primary while there is something to take in. Never ambiguous: a **check writes nothing**,
  a **Refresh writes the plan and is undoable**, and what is on screen is the last fetch.
- **A machine without gh.** No modal at launch. The GitHub tab still records typed refs and
  says, in one status line at its top, *gh is not installed — branches and PRs are typed,
  not picked*, with the install as a plain button; a verb that needs gh greys with *needs
  gh* in its words. The Checklist is where this machine's facts live, one status line each
  with its remedy. Never ambiguous: **this is about this machine, not the project**, and
  nothing typed is lost.
- **A machine that is not set up.** *Tools ▸ Setup Checklist…* is a status line per check,
  grouped, each with its remedy on a second line and — where DPlanner can run the fix — a
  plain button on the row, whose room is kept when there is nothing to press. The primary is
  *Re-check*, and the arc turns in its glyph. It opens by itself in exactly two cases: once,
  on a machine DPlanner has never greeted, whatever that machine has; and afterwards only
  while the person left *"open this at start"* ticked **and** something **required** is
  missing. Nothing advisory ever raises it — that is principle 3 below, and it is why there
  is still no modal at launch for gh. *Tools* carries the count of what is required and
  missing in its own words. Never ambiguous: **what would stop DPlanner, and what is only
  worth knowing**.

Five principles fall out of them, and every rule below is one of these applied:

1. **The primary action is the flow's next step**, and it moves as the flow does — *Connect*
   until connected, *Refresh* while there is something to take in, then nothing.
2. **A confirmation names what it is about**: the thing in the question it asks.
3. **A state is said where the person is looking** — the strip, the footer's status slot,
   the field it concerns — never in a modal about a background fact.
4. **A refusal carries its remedy in words**: a greyed verb says why, a refused primary says
   why, a missing tool says how to get it.
5. **What changed is recorded once, where it happened**: the status bar for a launch, the
   strip for a fetch, undo for the plan.

## Space

Use the 4-point scale: **4 / 8 / 12 / 16 / 20 / 24**. Never invent in-between values, and
never type one: every value below is a token in `theme/tokens.py` (the *Tokens* table at
the end), and a literal `20` in a layout is a copy that drifts.

- Dialogs: 20 px outer margins, 12 px between sections, 8 px inside a section.
- Side panels (inspector, sidebar tools): 16 px outer margins, and more space *between*
  blocks (12 px) than *within* one (6 px between a caption and its field) — grouping is
  spacing, not boxes.
- Rows in a list of rich items: 10 px vertical, 12 px horizontal padding, and the row's
  content lines 4 px apart.
- Text wells (read-only panes, editors in dialogs): the text never touches the frame — at
  least a 12 px document margin, and ~130 % line height for anything longer than a label.

When a surface feels "heavy", the fix is almost always more space, not more chrome.

## Panels

A panel anchored in one of the window's areas (`framework/panels.py`) gets a **header strip**
from its frame: the panel's name in `#InspectorCaption`, 16 px from the sides, 12 above and 6
below. It names the panel — the seam below separates it from whatever is stacked beside it —
and it is the right-click target for moving the panel; the panel's own widget keeps its own
context menu, so there would be nowhere else to put it. **A panel's content therefore never
prints its own caption**; the header already says what it is, and two captions is the one thing
`#InspectorCaption` forbids.

A panel with nothing to show goes off screen rather than showing a placeholder, and an area
with nothing in it takes no width at all. The reasoning is the card rule one level up: an empty
box is worse than no box.

## Seams

Two surfaces that meet at a splitter meet at a **seam**: a 1 px `$BORDER` hairline inside a
7 px handle — thin enough to read as a rule, wide enough to grab. Under the cursor the line
thickens to 2 px and goes `$BORDER_STRONG`; while it is being dragged it is `$ACCENT`. The
handle stays 7 px through all of it, so nothing either side moves as the pointer crosses.

It is the same seam wherever two surfaces meet: between two tab groups, between a panel area
and the tabs, between two panels stacked in one area. **A surface never draws its own edge
where a seam already falls** — one line, not two, which is why a panel area has a ground and
no border. One `QSplitter::handle` rule covers every splitter in the application, present and
future, and no surface names a ground of its own: the 3 px of window ground a seam leaves
beside an elevated panel reads as a groove, which is cheaper than an exception.

**The pane you are in wears a 2 px `$ACCENT` edge along its top, and only while the window is
split.** One pane is the whole window and there is nothing to tell it apart from; two or three
need saying, because every menu, every panel and every toolbar is answering for exactly one of
them. Its neighbours' tab titles dim at the same moment, and for the same reason.

## Overlays on a canvas

A surface that floats *inside* a drawing area — the minimap in the graph editor's lower-left
corner — is chrome, not content, and is read as such: `$BG_ELEVATED` with a 1 px `$BORDER`
and `RADIUS_MD`, the same look as the strip of verbs above the canvas. It is not a well; a
well is `$BG_BASE`, and the canvas already is.

- 12 px from the canvas's corner, 8 px inside its own frame.
- It goes off screen when it has nothing to show, exactly as a panel does.
- What it paints comes from the palette, so it follows the theme with the graph.
- It is a child of the *view*, never of the viewport: a `QGraphicsView` pans by scrolling its
  viewport, and that carries the viewport's children away with the pixels.

## Cards on the canvas

A step on the graph is a card on a table, and the canvas is drawn to say so.

- **Every card rests on a shadow**, faint, and a picked card lifts two pixels over a deeper
  one — the lift, not a colour, is what marks it (see *Colour* below). The fill is opaque:
  the ground never shows through a card.
- **The spine names the card and says where it stands.** A 26 px strip inside the left
  edge carries the step's key (`S7`, `F3`) set bold and read bottom-to-top, washed by
  status: busy blue in progress, the bad red blocked, the good green done, a quiet shade of
  ink otherwise. It is the one thing on a card meant to be found from across the graph, and
  the 3 px status bar it replaced is gone — one strip, two facts. A coverage card that is a
  step — a milestone, a feature, a step in the steps lane — wears the same spine.
- **The title is the card**: two points larger than the chrome, normal weight, wrapping onto
  as many lines as the card has room for above its bottom line. A card can be dragged larger
  by any edge or corner to show more of a long name; the default footprint fits two lines.
- **The bottom line is a number, never a sentence**: the estimate at the right in full ink,
  bold only where the number is the point of the card (a milestone's days and date), with
  the PR pill and the branch glyph beside it. Every aspect a card wears is a medallion, a
  badge, a bar or a pill; none is repeated as a phrase.
- **The ground is quiet.** The default is a dot at every grid crossing, at an alpha that
  keeps a card's resting shadow the darkest thing on the plane; lines, crosses and plain are
  offered beside it, and the pitch coarsens as the graph zooms out so the ground never turns
  to noise. What is drawn is always a coarsening of what a drag snaps to.

## Lanes joined by lines

A report of several columns whose rows relate — the coverage view's milestones, features,
spec, tests — draws each column as a **lane** (`$BG_ELEVATED`, 1 px `$BORDER`,
`RADIUS_MD`, a bold secondary caption inside its top) with the cards stacked inside and
the connections as curves in the **gutters** between lanes, never across a lane. A lane
scrolls on its own — the wheel over it, a 4 px thumb at its right edge that exists only
while it overflows.

**The lanes read left to right, and a pick fills the lane after it.** A click picks within
its own lane and clears the lanes to its right; Ctrl-click adds to that lane. Nothing is
dimmed: a lane stands what the picks stand up and nothing else, and a lane with nothing in
it says, in the secondary ink at its top, which pick would fill it. A lane whose content
changed starts at the top. A card's state is a mark at its top-right corner — a hollow
accent ring for *behind*, a filled accent dot for *drifted*, green for *ok*, red for
*failed* or *lost*, a faint ring for *pending* — never a word; a line into or out of a
picked card takes the accent and thickens. **A lane the reader can do without is a
checkable verb on the strip** (the coverage view's *Show steps*), and the lines follow
what stands: a connection is drawn only between two lanes side by side, so taking a lane
away joins its neighbours directly.

## Cards

The one sanctioned box. A panel that hosts *independent features contributed by different
modules* gives each feature a card (`framework/cards.py`: `ToolCard` in a `CardStack`).
Cards separate features from each other; they never group one form's fields — that is
still spacing.

- A card is a **well** on the elevated panel: `$BG_BASE`, 1 px `$BORDER`, `RADIUS_MD` —
  the same contrast as a plain field, so a panel of cards and a panel of fields read alike.
- That contrast assumes **elevated ground**. On a tab page — which is `$BG_BASE`, the same
  colour as the well — a bare card is one faint border and the list has no shape. Give the
  list its own ground first: a *lane* (`$BG_ELEVATED`, 1 px `$BORDER`, `RADIUS_MD`) with
  the cards inside. `#ProgressionLane` is the worked example.
- 12 px padding inside; one `#InspectorCaption` header (with the feature's glyph in
  `$TEXT_SECONDARY`, repainted on theme change) and 8 px to the body; 12 px between
  cards; the stack keeps the panel's 16 px margins.
- The stack **scrolls vertically and never horizontally**: cards wrap their text and
  fit the panel's narrowest width (200 px). Alternate controls rather than placing
  them side by side (Start *or* Stop, not both).
- A card with nothing to say **hides entirely** (`tab_visible()` false) — never an empty
  box. A card that always has something to say can **split in two** with a rule
  (`card_rule()`, 12 px above and below): controls above, what they produced below. A
  section that is empty *for now* says so in words rather than vanishing.
- A card's action is a plain button. The one-primary rule applies to the panel, not to
  each card, so no card gets the accent.
- Avoid widgets with their own scroll bars inside a card (a text pane, a list): wheel
  events stop at the inner scroller and the stack no longer scrolls under the cursor.

## Hierarchy

Qt widgets render everything at one size and colour unless told otherwise; say what
matters explicitly:

- **Primary** content (the thing itself): `$TEXT_PRIMARY`, normal weight.
- **Secondary** content (reasons, metadata, counts, captions): `$TEXT_SECONDARY` via a
  QSS object name — or, where a painter has only the palette, the text colour at ~63 %
  alpha (deliberate exception #1: opacity-derived secondary text is theme-independent
  by construction).
- **Captions** over a block: the `#InspectorCaption` look — bold, secondary colour,
  small. One caption per block, never two sizes of caption. A remark under it (a notice,
  a hint) is `#InspectorNote`: same colour, normal weight.
- A two-line list row states the *what* on line one (primary) and the *why* on line two
  (secondary). Never run them together in one undifferentiated blob.

## Words

**No explainers.** A line under a field restating a convention the reader already knows
("Working days. A week is five.") is chrome that never stops being read, and it costs a
line of vertical space on every visit for a sentence that was only ever needed once. Put
the unit *in* the field — a suffix, a placeholder, a chip — and where a convention genuinely
needs stating, put an `info_icon()` glyph in `$TEXT_SECONDARY` beside the caption with the
sentence as its tooltip (`InspectorSection.hint` does this for a Details block).

`#InspectorNote` is for a remark that **changes with the data**: what a run recorded, why a
verb is unavailable, what this scope turned out to hold. Never for a standing definition.

**Empty states.** A tab page with nothing in it says so with `EmptyState`
(`framework/widgets.py`): one short line, a size smaller and in `$TEXT_SECONDARY`, centred
both ways in the space the content would have taken, wrapped at a readable measure. The
content it stands in for is hidden, not shrunk — the two trade places, and the state is
told which content that is (`stands_in_for`) so one `say()` does the swap; a page never
toggles the two by hand. Never a note left where the layout happened to put it, and never
a heading, a glyph or a paragraph: the line says what would be here and names the way to
put something there — as a plain button under the line when that is one verb of this page
(*Add Note…*), in words when it is a toggle or a terminal command.

The same rule decides a control's fate. A selector with one entry, a switch whose two
positions give the same answer, a caption over a single obvious field — each is a thing to
read that teaches nothing. Compute whether it would say anything and leave it out when it
would not; the Covers tab's New/Cumulative switch is the worked example.

## Buttons

- One **primary** action per surface: `#PrimaryButton` (accent fill, `$ON_ACCENT`
  text). It is the action the user came to perform — Apply, Save, Start.
- Everything else is a quiet bordered button: the `#ToolbarButton` look on a strip, the
  footer's own look in a `DialogFrame`. A plain `QPushButton` anywhere else is Fusion's,
  and reads as such.
- Destructive or dismissive actions (Cancel, Reject) never get the accent, and a verb that
  discards is never the default — see *Dialogs*.
- A dialog whose every edit is live and already undoable carries **Close and nothing
  else** — there is nothing to confirm and nothing to cancel, so no primary and no
  Cancel; the footer is the way out rather than an answer to a question. It carries one
  because a window manager that draws no title bar (a tiling one) leaves Escape as the
  only way out, and a way out nothing shows is not one. The step details dialog is the
  worked example.
- **Past two or three verbs on one thing, the glyph buttons become a `⋯` menu.** A row of
  bordered glyphs is a row of riddles — each says its verb only in a tooltip, and the row
  grows with every feature. One `⋯` beside the thing, dropping a menu of *glyph plus
  words*, says all of them at once and costs one control. Build the menu when it opens
  (a glyph carries the colour it was painted in) and grey what cannot run right now, with
  the reason in the entry's own words — never drop it, or the list changes shape and stops
  being learnable. The Project dialog's repository columns are the worked example.

## Dialogs

Every dialog is a `DialogFrame` (`framework/dialog.py`), and its anatomy is the frame's:

- **Top to bottom: the body, then the footer. The frame prints no heading of its own.**
  A title inside a dialog repeats what the title bar already says and costs a line and a
  half at the top of a surface that is small on purpose; a lead under it costs another. A
  dialog's content is what the person opened it for, and it starts at the top. The title
  names the **window**, for the switcher, and nothing is drawn from it. What a dialog is
  about is said by its content — the question a confirmation asks, the caption over a
  prompt's field — never by a heading over it.
- **The one exception is a dialog that opens itself** (`set_heading`). A surface nobody
  asked for is the only one that has to name itself: the person clicked no entry, read no
  title in passing, and has a window in front of them they did not summon. The Setup
  Checklist is the case, and the rule is the test — **a dialog a gesture opened must not
  call it**, because that gesture already said what this is. Then **the footer as a band**, edge to edge
  below the page: the elevated ground under a faint hairline, its buttons 12 px inside it.
  It is the one place a dialog has a second ground, so the eye finds the way out without
  reading.
- **Footer slots, left to right: destructive · status · stretch · secondaries · Cancel ·
  primary.** The destructive verb is a different exit that costs something (*Quit Without
  Committing*, *Delete*), never an answer to the question; the far left is as far from the
  accent as the footer allows, so a hand travelling to the primary never crosses it, and
  the status slot between them keeps the two from reading as a pair. Cancel sits beside
  the primary, where the eye goes to leave.
- **Close alone when every edit is live and undoable** — no primary, no Cancel, one
  dismissal in the footer, and Escape does the same thing. Step Details is the worked
  example; see *Buttons* for why it carries one at all.
- **Enter runs the primary, Escape dismisses, Ctrl+Enter is Enter from a multi-line
  field.** Cancel is the default only while there is no primary, so a confirmation whose
  only verb discards work answers Enter with nothing lost — the one data-loss hazard on
  record was a footer whose default was *Clear*.
- **A refused primary is disabled, keeps its name, and says why** in the footer's status
  slot (`refuse(reason)`) — the same rule every greyed menu entry follows. A label that
  grows a reason moves the footer; a button with no reason teaches nothing.
- **Three sizes.** *Fit* — the content's, never under 420 px — for a prompt, a
  confirmation, a connect form. *Framed* — a preferred size clamped to 80 % of the screen,
  resizable — for a Project or Step Details. *Editor* — 80 % of the screen outright,
  because a place to work is what was asked for.
- **A confirmation is a fit dialog on the frame, never a `QMessageBox`**, which prints a
  platform icon and arranges its sentences and buttons the platform's way — a second
  design for exactly the moments a person must read carefully. `confirm()` builds one: the
  question as the body (it is the content, not a heading over it), the verb a *quiet*
  button (it discards), Cancel the default.
- **A one-line prompt is a `LinePrompt`, never a `QInputDialog`.** It is the commonest
  dialog in the application, so it must be the most designed: a caption over the field, a
  note under it for what is wrong, a primary named for the verb (*Create*), the field
  focused and selected.
- **Fields in the body**: line and text edits wear the panel field's look with an accent
  border while focused, and a combo box wears the quiet bordered look of the button beside
  it, with the arrow's room at its right — Fusion's combo beside our buttons read as
  another product's. Spin boxes and check boxes stay Fusion's, from the palette; a boxed
  spin box shows two styles.

## Forms

- **The caption is over the field, never a label to its left.** A left label sets a column
  as wide as the longest word in the form, so every field's x depends on a word elsewhere
  and no two forms align; over the field, fields fill the width and stack at the caption
  gap, which is what `#InspectorCaption` does everywhere else. `caption()` and `note()` in
  `framework/widgets.py` make the two labels.
- **The unit lives in the field** — a suffix, a placeholder — never in a line under it.
- **Validation**: the primary is refused while a value is wrong or missing, and the reason
  goes under the field it is about, in the error tone, present only while it is wrong
  (`LinePrompt.problem`); a reason that belongs to no one field goes in the footer's
  status slot. Never a dialog that closes and then complains.
- **Help** is an `info_icon()` beside the caption with the sentence as its tooltip.
- **Required is the default and unmarked**; the optional field says so in its placeholder
  (*What this step delivers (optional)*). Marking the majority is noise.

## Facts under the thing they are about

Where a surface shows a thing and some facts about it, the facts go **under** it, a step
down in size, not into a row of fields above it. Two surfaces side by side then read as a
pair — the same lines in the same places under each — and the divide between them does the
work a caption would otherwise have to. A fact nobody has recorded still gets its line,
saying what is missing (*not checked out on this machine*), greyed and italic: the shape of
the block is then constant and a reader learns where to look once. A line too long for its
column elides in the **paint**, never in a resize — a widget that rewrites its own text
while being resized can drive the layout in a circle — with the full text as the tooltip,
and a path elides from the left, because a path's tail is what names it.
`ARCHITECTURE.md`'s *The Project dialog is two columns, not three fields* has the
reasoning, including why the count of fields was the symptom rather than the disease.

## Colour

- One warm accent, used sparingly: the primary button, the checked state, focus.
- Semantic region tints (diff added/removed, status colours) are low-alpha constant
  `QColor`s that read on every theme (deliberate exception #2 — see the diff highlighter
  in `modules/sync/view.py`); never opaque theme-specific backgrounds.
- Every other colour comes from a `Theme` field, through `theme.qss` or the palette.
- **A milestone wears its place in the sequence, not one purple.** The project picks a
  colour map (`theme/palettes.py`; *View ▸ Milestone Colours* and the Time tab's picker set
  the same stored choice) and every milestone is dealt a shade of it by where it falls in
  the roadmap. One hex, eight surfaces: the card on the canvas, its badge and tag medallion,
  the order table's row and key badge, the Ready-to-start board's card, the Tests tab's
  grouping heading, the Docs tab's medallion, the coverage lane, the Milestone tab's swatch,
  the calendar's band and the report — so a colour means *this milestone* wherever it is
  seen. A shade never invents an alpha: `tones.toned(name, hex)` recolours the tone the
  purple had, so a milestone's card is exactly as loud as it always was. Nothing else in the
  application deals colour by position, and nothing else should.
- **A selected item is lifted, not recoloured.** The accent goes on the border; the item's
  own fill *gains* rather than being replaced, so whatever the colour was saying — this is
  the second milestone, finished work is green — it still says while the item is picked. Where
  a surface can afford it (a canvas), a couple of pixels of rise over a soft shadow is what
  makes the difference unmistakable without a second colour. `renderers.paint_node` is the
  worked example.

## Lists of rich items

A `QListWidget` of multi-line entries uses a `QStyledItemDelegate`, not concatenated `\n`
text: the delegate gives each row real padding, a primary/secondary text hierarchy, wrapped
text that re-lays out on resize, and a selection state that recolours both lines legibly.
`framework/list_rows.py`'s `RichList` is the one to use: a `QListWidget` on its
`TwoLineDelegate`, wearing the table's well, hover and picked edge.

- **A list when there is one column of things; a table when a reader compares across
  rows.** A list row is two lines — the *what* in primary ink, the *why* under it in
  secondary **and a point smaller**, 4 px apart, 10 px above and below, 12 px at the
  sides — the same row a two-line table cell draws, so the two never disagree. The row's
  glyph sits on the first line, never centred on the pair: it is the name's.
- **The trailing note** (a date, a count, a shortcut) sits at the right of the first line
  in secondary ink, measured first so the name elides against what is left.
- **Hairlines only under a pinned row that heads the list**; between ordinary rows the
  padding is the separator.
- **A row's own verbs sit at its right, and a row that has none keeps their room.** At most
  two named or glyph buttons — the act, and a link where somebody else's page is the answer
  — then a `⋮` for what the row can be *told*, built when it opens. Room kept while hidden
  (the `UpdatingIndicator`'s rule), so a row that is fixed does not move the rows under it.
- **Rows that carry verbs of their own and must outlive a refresh are a well**
  (`RowWell`): the task and Agents browsers, where a pressed *Cancel* has to survive the
  next tick. Rows are reconciled by key, never rebuilt; each is a title with its verbs, a
  `StatusLine` whose tone is the row's mood, and a note — never a table row with buttons
  planted in it.
- **A list of things that should be true is drawn as one**: the `StatusLine`'s mark becomes
  ☑ when it is and ☐ when it is not, and the tone still carries the mood. Nothing else
  changes that glyph — a second mood glyph would be a second vocabulary.

## Tables

Every table is a `Table` (`framework/table.py`): its columns declared, the rules applied
once, its delegate painting what a row wears. Debug ▸ Design Example Table is the reference.

- **The strip above a table carries its verbs, then its view.** Creation first (*Add
  Step*), then what acts on the picked rows — greyed until a row is picked and worded with
  the count when several are (*Delete 3 Steps*): disabled, never hidden, the rule every
  greyed menu entry follows, and the count is what says a verb is about to act on more
  than the eye is on. Then a divider, then the view's own controls (a filter, a grouping),
  and at the strip's far right the Updating indicator. The strip is a `Toolbar`
  (*Toolbars*); on a real surface its verbs come from the registry.
- **Cell text is the UI size; the second line is a point smaller.** A whole table one step
  down reads as a spreadsheet, and a table is the content; the step down belongs to the
  line that is *about* the first (`detail_font`, the same step the empty state takes).
- **Column headers are left-aligned**, whatever the column holds
  (`header.setDefaultAlignment`, not Qt's centred default). Numeric *cells* still
  right-align so their digits line up, with the unit inside the cell (*3 d*) — or once in
  the header (*Estimates (d)*) where a column of chips would print it on every chip; the
  header reads from the left with everything else. The header stays bold secondary over one
  hairline — it is `#InspectorCaption` laid on its side, chrome above the rows and not a
  weight among them.
- **Row height comes from the font, never from a pixel.** The UI font is the platform's;
  a fixed height clips two lines at twelve points. A plain row is the line plus 6 px above
  and below; a rich row is the two lines at their two sizes, the 4 px gap and 10 px above
  and below — each rounded up onto the 4-point scale (≈ 32 and ≈ 56 at the default font)
  and set on the vertical header, the one mechanism that sizes a delegate-drawn row.
- **The row is the unit.** The pointer over any cell washes the whole row (the text
  colour at ~5 %, theme-independent like every painter's tone); a picked row wears a 2 px
  `$ACCENT` edge inside its left over the quiet `$BG_OVERLAY` ground — the edge the active
  pane wears on its top — and *gains* its ground rather than losing its tint, so a
  milestone's row keeps its shade while picked (*Colour*). Nothing else marks it: the focus
  frame Qt draws round the *current cell* is stripped, because a dotted box lingering on
  the last cell clicked is a second mark, on one cell, for what the edge already says.
- A row that is a **fixed point** among its neighbours (a milestone) goes bold, and is the
  one weight in the table: a glance down a column of quiet lines finds the milestones
  without reading. Emphasis for any other reason is size or colour, never a second bold.
- A table of mixed kinds gives every row the glyph of what it is (the tag, the layer stack,
  the card), so a reader never has to infer a kind from a column further right — and **the
  glyph slot is reserved on every row of that column**, filled or not, so titles start at
  one x and a row that gains a kind later does not shift its neighbours. The slot is
  `KEY_BADGE_W` (28 px) wide — room for a **key badge** — and a glyph sits at its left.
  **The glyph sits on the first line**, centred on the name and never on the pair of
  lines: a glyph half way between a title and its key belongs to neither.
- **A milestone's row wears its key as a badge** where the glyph would be: `F1`, `M2` as a
  rounded chip in that milestone's own shade (`key_badge_icon`), the key being what a
  milestone is known by across the graph. The second line then says what the row gathers,
  not the key again.
- **A group heading is a spanned row nobody can pick**: bold secondary words at a plain
  row's height, no hover, no edge (`add_heading`). Nothing else separates the groups; the
  heading is the separator.
- **A value set in the row is the column's**, never a widget planted in a cell: one column
  carries an editor (`NumberEditor`, `DateEditor`) that a double-click, F2 or a typed key
  opens over the cell — a picked row aims its keys at it — and a commit lands in the cell
  and is announced once, through `Table.edited`, which the host turns into its command.
- **A column's usual values are chips**, when seeing them matters as much as setting them
  (`Column(chips=…)`): painted in the cell, one accent-filled for the row's value, a click
  sets it. Down the rows they line up into a grid — the Estimates tab reads small, large and
  unsized before a number is read. A value that is a claim rather than a step on the scale
  stands past a hairline (`Chip(apart=True)`), and beside an editor a last `…` chip opens
  it and wears a value off the scale, so an unusual value never reads as none.
- **No header sorting.** Every table here is a derivation whose row order *is* its
  answer — a topological order, a roster filed under headings, a log newest first. Another
  view is a selector on the control strip, in words, and it survives a rebuild; a clicked
  header is hidden state a rebuild silently resets.
- **Empty**: the table hides and `EmptyState` takes its stretch — one swap, and the table
  is what it `stands_in_for`.
- **Updating**: the table keeps the last picture while the Updating indicator turns at the
  right end of the control strip (*Signalling*).

## Toolbars

A strip of verbs over a surface is a `Toolbar` (`framework/toolbar.py`); Debug ▸ Design
Example Table wears one.

- **A verb is a glyph, and its words are the tooltip** (with the shortcut beside them). A
  row of words is a sentence the eye has to read every time; a row of glyphs is learned
  once, and the tooltip is there for the first time. Every glyph is one of
  `theme/glyphs/`'s vendored Tabler SVGs, inked in the secondary tone and re-inked on a
  theme change —
  and painted at the screen's device pixel ratio, because a 16-pixel pixmap shown at 16
  points on a 2× display is upscaled, and every stroke in it goes soft.
- **A control that drops a menu asks for its arrow's room** (`ARROW_ROOM` for a split
  button, `INDICATOR_ROOM` for a face). A styled subcontrol is outside Qt's size hint, so
  nothing widens the button by itself: without the padding the arrow is painted over the
  glyph, and a clipped icon is the only sign. **And the divider between the halves is one
  colour for every state** (`$BORDER_STRONG`, which reads on the quiet ground and on a
  checked button's accent fill alike): a second rule for the checked state — a pseudo-state
  on a subcontrol — makes Qt drop the button's own left border everywhere.
- **What no longer fits folds into a `…` menu at the strip's end**, as glyph *and* words,
  taken from the right — never a second row, and never Qt's own overflow, which pops the
  hidden buttons up as glyphs again. A widget among the verbs (a filter) never enters the
  menu; it hides when there is no room for it. The strip's own size hint is the `…`
  button's, so a page can be dragged as narrow as it likes and the strip folds rather than
  squeezes.
- **Every control on a strip is one height** (`CONTROL_HEIGHT`, 32 px), set in code: a
  glyph button, a worded button and a combo box disagree by a few pixels under the style,
  and a strip whose buttons are not one height reads as several strips.
- **A strip whose glyphs are read as one set is `dense`** (`Toolbar(dense=True)`): the same
  height, narrower sides, `DENSE_GAP` between them. A strip of *verbs* folds gracefully,
  because losing a verb to the `…` costs a click; a strip that answers a question about the
  thing on screen — the step panel's aspect bar, *what does this step carry* — stops
  answering it when it folds. Ten toggles at the verb strip's metrics seat five in the width
  that panel can be; dense seats all ten. It is a mode the primitive offers, never a surface
  styled by name.
- **A divider is the hairline at half strength** (`$BORDER_FAINT`, the border blended
  halfway into the elevated ground), 6 px short of the controls' top and bottom: it parts
  groups without being read as a control.
- **A strip that is a tool palette is cut into named bands** (`Toolbar.add_group(label)`):
  the glyphs of a band sit `DENSE_GAP` apart and read as one set, the bands stand
  `CONTROL_GAP` apart with a divider between them, and each carries its name under it — a
  point smaller, secondary, centred. Nineteen glyphs in a row are nineteen riddles; six
  named bands of three or four are something to learn once. The name is *structure*, not
  an explainer: it says what the glyphs above it are for, where a label on each button
  would say what the tooltip already says.
- **A band's glyph buttons are squares** — `CONTROL_HEIGHT` each way, the padding derived
  from the height rather than typed. A palette is a grid of targets of one size, and a
  square is also what puts the glyph in the middle of its button. A *dense* strip that is
  not banded stays narrow: the aspect bar wants ten toggles in a 360 px dock, and squaring
  them costs it two.
- **The band is then the unit that folds.** What no longer fits leaves the strip a whole
  band at a time and is listed in the `…` menu with a rule where each band begins — half a
  band on the strip and half in a menu is worse than all of it in either.
- **A control that is not a verb goes in the band it is about**, as a widget: the graph's
  layout picker names the arrangement the canvas is showing, so it sits at the end of
  *Arrange*. A widget never enters the `…` menu — it hides when there is no room — which is
  what keeps "not a verb" true without standing it outside the strip, where a lone worded
  button past a row of named bands reads as something that fell off.
- **A checked verb's glyph takes `$ON_ACCENT`.** A checked button is filled with the
  accent, and a glyph left in the quiet tone disappears into it — which is why the canvas's
  mode switches carried words for as long as they did. The primitive re-inks on the toggle,
  so a glyph is legible in both states and nothing on a strip needs words to be readable.
- **A control the host takes off stays off.** `Toolbar.set_shown(widget, False)`, never
  `hide()`: the reflow shows whatever it measures, so a hidden combo came back on the next
  resize. The Time tab's day fields and the Estimates tab's scope come and go this way.
- **A face is a glyph that stands for a band of the menus** (`Toolbar.add_menu_face`):
  one control dropping a menu the action table renders, never a copy of it — the graph's
  *Options* is *Graph*'s `look` band. It has no verb under it, so it wears the layout
  picker's look rather than the split arrow of a button that runs one.
- **A combo box on a strip is one of the buttons** — the quiet bordered look, the arrow's
  room at its right — and **the list it drops down is a menu**: the overlay ground behind
  a strong hairline, rounded, 6 px around every entry, the accent on the one under the
  pointer. Its arrow is the theme's own SVG (`theme/__init__.py`'s `drop_arrow_url`): a
  border-drawn triangle flattens into a bar at a 2× scale.
- **A filter is one control with two buttons** (`FilterButton`): a face — the funnel
  glyph and the word — that drops the filters down as a menu of checkable entries stacked
  vertically, which stays open while they are toggled, and a clear button joined to its
  right, greyed until a filter is on and never hidden. **The indicator is the glyph**: an
  outline funnel while nothing is on, a filled one with a dot in the slot before it while
  something is, so the face never changes size; the face then wears a wash of the accent
  over its ground (`$ACCENT_WASH`) and the accent on its border and glyph, never a fill —
  a filter being on is a state, not a mode being pressed — and the tooltip names what is on.
- **A verb whose work is running turns its glyph** — a `Spinner` attached to the verb's
  action (*Signalling*, Working); the example's Refresh does so while its rebuild is owed.
- On a real surface the verbs come from the registry — `ActionToolbar` over registered
  `ActionSpec`s becomes a `Toolbar` fed by them in the design passes; the example wires
  plain slots to show the shape.

## Signalling

What a surface says while it is not yet showing the truth, and where. One vocabulary,
three widgets (`framework/signalling.py`: `UpdatingIndicator`, `Spinner`, `StatusLine`)
and one stylesheet rule for the progress bar:

- **Updating** — a rebuild is owed after the person's own change: `UpdatingIndicator`
  follows the view's one `Debounced` and **turns the same three-quarter arc a working
  button turns**, from the first trigger to the rebuild's end, at the right end of the
  control strip, *outside* the `Toolbar` so folding the strip can never take it,
  keeping its room while hidden so the strip never reflows. The content stays; nothing
  dims. **A view with no control strip puts it at the right end of its caption row** — a
  board and a two-pane list have a caption and no toolbar, and that row is their strip;
  give the caption the stretch and the indicator the end. A view that settles once per
  event-loop turn — the canvas — gets none: there is no span to read.
- **An arc, not the word.** The indicator carried *Updating…* for one step and the word was
  wrong three ways: it was the only prose on a strip of controls, it was four times the
  arc's width at the end of a row already competing for room, and it would need
  translating where a glyph does not. It is a glyph-sized square with the words in its
  tooltip — and it is the *same* motion as a working button's, which is what makes "the
  application is busy with something here" one thing to learn rather than two.
- **Busy** — work with no known end (a probe, a fetch): a `StatusLine` in the busy tone,
  where the answer will land — a dialog footer's status slot, a page strip's note. Never a
  modal, never a caption rewritten to say *Reading…*.
- **Working** — the button whose verb started the work says so in its own glyph: a
  `Spinner` turns a three-quarter arc in the glyph slot until the work is done, then the
  glyph comes back (`attach(button).follow(debounced)`, or `start()`/`stop()` around a
  task). The slot is always there, so nothing moves — which is why a button that starts
  work carries a glyph beside its words, and a spinner refuses one that does not. Attach a
  bare `QLabel` instead and the arc stands on its own, which is all an `UpdatingIndicator`
  is: one motion, two places to put it.
- **Pending** — a fact nobody has recorded: a greyed italic line saying what is missing
  (*Facts under the thing they are about*); no glyph, because an absence is not a state.
- **Error** — the error tone in the same place the busy was, with the remedy in its words.
- **Success** — the ok tone in that place, standing until the next change; the window's
  status bar carries the one-line record of a gesture (*3 agents launched*).
- **A `StatusLine` is a glyph in a tone beside secondary words**: the glyph carries the
  mood, the words carry the fact, and a paragraph of red is shouting. Five tones — info
  (the line's own ink), busy (the spine's blue), ok (the good green), warn (the chips'
  attention amber), error (the bad red), `theme/tones.py`'s `STATUS_TONES`, the same shades
  the canvas spine wears. **Warn is not a weaker error**: an error is this work failing and
  carries its remedy, where warn is something going on that the reader should not walk
  into — another writer at the same plan — which nobody can fix and everybody must see.
- **A progress bar is 4 px, accent, no text, no frame** — one bare `QProgressBar` rule,
  under the fact that leads it (*Publishing 2 of 5 repositories*) — and only for work whose
  end the application knows: a fetch of 12 pages, a save over 3
  repositories. Never for the debounce, never for an agent's own running (a peer, not a
  task, and nothing here can see how far it has come), and not indeterminate: an unknown
  fraction is *busy*, and busy is a line. **A count the agent itself declares is a count**,
  though — `dplanner agent-work set --done 8 --of 20` is the agent saying what it is working
  through — so that fills a bar exactly as the fetched pages do, and a claim that declares
  none gets the arc and no promise. The task browser shows a bar only for a task that
  reports its fraction; every other running task is a busy line.
- **A remembered duration may fill a bar, under a fact that leads it.** How long the last
  run of the same operation took (`TaskService`'s duration memory, kept per user and
  machine) is a fair guess and a poor promise, so it is never the *only* thing a bar
  reads: the known count leads — repositories recorded, pages fetched — and the estimate
  only fills the gap between one landing and the next, so the bar never sits behind what
  has actually happened. An estimate that runs out holds just short of full
  (`ESTIMATE_CAP`), because a bar that reads complete while the work goes on is worse than
  one that reads slow. With nothing remembered the bar is the count alone, which is the
  honest picture on a machine's first run.
- **A fact that holds goes over the content, not in the status bar.** *An agent is editing
  this plan right now*, *2 entries changed here and outside* — true until they stop being
  true, and the person must not miss them while they work — are a `Notice` in the
  `NoticeBar` above the tabs (`framework/notices.py`): a row per owner, the same
  vocabulary as a `StatusLine` (a tone, and the turning arc when it is about something
  running), one quiet verb at the right, and the bar gone while nothing stands. The status
  bar says what a gesture *came to*; this says what is *the case*.
- **A standing notice wears its tone as a band, and the band is its meter.** This is the
  one surface where the tone is the whole row rather than a glyph beside the words, because
  it is the one surface a person must not read past: the row is washed in its tone
  (`BAND_ALPHA`, a semantic tint over whatever ground the theme has) — amber while another
  writer is at work, red while something is owed — and plain information wears none, which
  is how a claim that has gone quiet stops shouting without leaving the screen. **A
  declared count fills that band from the left** at the same hue's greater weight and says
  how far in words at the right, beside the verb. It is the one place the 4 px bar is not
  used, and the reason is what a meter has to do before anything has happened: a strip at
  nought per cent is a hairline nobody reads as a meter, where a band saying *0%* is
  plainly something that fills.
- **Never a modal for a background fact.** A modal asks; a fact is said where it bites.
  **And a modal waits while somebody else is already interrupting**: while an agent says it
  is at work, the collision question stands in the notice bar rather than being thrown over
  a person who has just been asked to keep their hands off the graph.
- **A field being dictated into wears the accent edge.** The microphone verb is checked
  while it listens and its glyph turns while the words are on their way; the editor says
  the same thing on its own border (`dictating`), the way a checked verb's glyph takes the
  accent, and nothing meters the level — a live meter would be a fourth motion.

## Focus and motion

- **Initial focus is the first field**, selected when it holds a default; a confirmation
  with no field focuses its default button — the primary, or Cancel when the verb discards.
  The frame does this; a dialog never reaches for `setFocus` unless it wants a later field.
- **Tab order is reading order through the body, then the primary, then the secondaries,
  then the destructive last**: the first Tab out of the body lands on the action the
  person came for.
- **The only things that move are the agent ring, the Updating indicator and the glyph of
  a button whose work is running.** No fades, no slides: on a still surface every change
  is a change of fact, so the eye is drawn only by facts.
- **Selection follows the keyboard**: arrows move the row edge and whatever follows the
  selection follows it, as a click would.

## Tokens

Every metric a surface uses, on the 4-point scale, declared once in `theme/tokens.py` and
reaching `theme.qss` as `$NAME` for free. A literal in a layout is a copy that drifts.

| Token | Value | Where |
|---|---|---|
| `DIALOG_MARGIN` | 20 | a dialog's outer margin |
| `PANEL_MARGIN` | 16 | side panels and tab pages |
| `SECTION_GAP` | 12 | between sections; between blocks; between cards; body to footer |
| `FIELD_GAP` | 8 | fields within a section; footer buttons |
| `CAPTION_GAP` | 6 | a caption to its field, a note to its field |
| `ROW_PADDING_V` / `ROW_PADDING_H` | 10 / 12 | a rich row: lists and two-line cells alike |
| `ROW_LINE_GAP` | 4 | between a rich row's two lines |
| `CELL_PADDING_V` / `CELL_PADDING_H` | 6 / 8 | a plain table cell, and its header section |
| `CONTROL_GAP` | 12 | between the controls on a strip; a button's own padding is 6 / 12 |
| `DENSE_GAP` | 4 | between the glyphs of a dense strip, and its buttons' sides (*Toolbars*) |
| `CONTROL_HEIGHT` | 32 | every control on a strip, set in code |
| `ICON_SIZE` (+ `ICON_GAP`) | 16 (+ 8) | a glyph, and the gap after it |
| `ARROW_W` / `ARROW_ROOM` | 20 / 24 | a split button's arrow, and the room the words leave it |
| `INDICATOR_ROOM` | 20 | the room a *face* leaves — a control that is only a menu |
| `KEY_BADGE_W` | 28 | a key badge, and the slot a glyph column reserves on every row |
| `RADIUS_SM` / `RADIUS_MD` | 5 / 8 | buttons, chips, fields / wells, cards, tables, lanes |
| `SECONDARY_ALPHA` | 160 | a painter's secondary ink (~63 %) |
| `SCREEN_SHARE` | 0.8 | the screen a framed or editor dialog may claim |
| a title | +2 pt | a dialog's title, a page's answer line, a card's title (`title_font`) |
| a secondary line | −1 pt | a row's second line, the `EmptyState` line (`detail_font`) |
| an edge | 2 px | a picked row's left, the active pane's top |
| a hairline | 1 px `$BORDER` | a header's rule, a seam, a pinned row |
| a progress bar | 4 px | the one kind there is |
| `$BORDER_FAINT` | derived | the hairline blended halfway into the elevated ground: a strip's dividers |
| `$ACCENT_WASH` | derived | the accent washed over the overlay ground: a control that is on |

## Bringing a surface up

The checklist a later step runs over a surface it touches — each answerable yes or no
from the code or a screenshot, and Debug ▸ Design Example is what *yes* looks like:

1. Is every margin, gap and padding a token, never a literal?
2. Is a dialog a `DialogFrame` and a page a control strip over its content — not a
   hand-rolled layout?
3. Does the dialog start at its content — no title and no lead printed over it?
4. Is there exactly one accent primary, and is it the flow's next step?
5. Is every confirmation `confirm()` and every one-line prompt a `LinePrompt` — no
   `QMessageBox`, no `QInputDialog`?
6. Does Enter run the primary, Escape dismiss, and is a discarding verb never the default?
7. Does focus land on the first field, or the right button, when it opens?
8. Is every caption `caption()` over its field, with no label to the left?
9. Is the table a `Table` — height from the header, the glyph slot on every row and on
   the first line, numbers right-aligned, headings spanned, its verbs on the strip above
   it greyed until a row is picked?
10. Does a row wash on hover and pick with the edge over the quiet ground?
11. Does an empty page swap through `EmptyState.stands_in_for`, and nothing else?
12. Is the strip a `Toolbar` — glyphs with their words in tooltips, folding into `…`, every
    control one height — with a `FilterButton` where there are filters, and named bands
    where it is a tool palette rather than a handful of verbs?
13. Does the Updating indicator turn at the strip's right from the first trigger to the
    rebuild's end?
14. Is every busy, ok and error a `StatusLine` in place, and every rewritten `QLabel` gone?
15. Is any progress bar 4 px, accent and determinate?
16. Does nothing fade, slide or animate except the ring, the indicator and a working
    button's glyph — and does that button carry a glyph, so nothing moves when it turns?

**The surfaces, as audited when the system was written (September 2026)** — what makes
each read as Qt, and so what its pass has to change. A surface not named here was not
looked at; look before assuming.

Dialogs:

- *(done)* `StepDetailsDialog` — live edits and one Close, on the frame; its title is the
  window's alone.
- *(done — S16)* `SettingsDialog` — Close alone; the tree and the page parted by a
  splitter's seam, a folder a heading the arrow keys step over, every page in a scroller of
  its own and built from `settings_page` and `block` — captions over fields, the standing
  explanations behind the caption's glyph.
- *(done — S16)* `ProjectDialog` — Close alone in settings mode; create mode a form of
  captioned blocks whose Create is refused in words; what a request came to in the footer's
  status slot, and the plan column's set-up offer the verb of an `EmptyState`.
- *(done — S16)* `OpenProjectDialog`, `MovePlanDialog`, `RepositoriesFolderDialog`,
  `GhRepoListDialog` — on the frame; the repository picker's four glyph buttons one ⋯
  menu and its note a `StatusLine`; the GitHub list captioned, its listing in the status
  slot; the prompts `LinePrompt`s and the result boxes `notice()`s.
- *(done — S16)* `ExpandedTextDialog`, `ChartDialog`, `ImagePreviewDialog` — two editor
  dialogs and a fit one, Close alone; the preview's two verbs quiet secondaries that say
  what they did in the status slot rather than in a box.
- *(done — S16)* `AssetPickerDialog` — *Insert* the primary, refused until something is
  picked; the empty page an `EmptyState` standing in for the grid.
- `TaskBrowserDialog` / `AgentBrowserDialog` — a well of rows, styled once and copied
  whole with no stylesheet for the copy; one row-well primitive would absorb both.
- *(done — F5, focus in S16)* Confluence `ConnectDialog` — on the frame with captions
  over its fields; it opens on the email, the read-only site a click-to-copy fact.
- *(done — S16)* `PromptFallbackDialog` — a text well under the note; *Copy Prompt* a
  secondary that says so in the status slot.
- *(done — S16)* `ConflictDialog` — the agent the primary, refused with its reason in the
  status slot and its name kept; *Take Theirs* and *Keep Mine* quiet; *Later* is Escape's.
- *(done — S16)* `InstallDialog` — its rows read as the checklist's, ☐/☑ in the same
  tones; *Remove* at the far left; *Install*/*Update* the primary and Enter's.
- `SaveSnapshotDialog` — the panel's 6 px idiom hand-simulated with `addSpacing`; the box's
  Save.
- *(done — S16)* `DiffDialog` — a captioned picker, shown only for several repositories,
  over a monospaced text well; *Save Now* the primary.
- *(done — the graph editor pass)* `CommandPalette` is a `PickerDialog`
  (`framework/picker.py`) and the frame is styled: the menu's own ground and hairline, a
  focused field, and a picked row wearing the accent on its edge rather than a band of
  colour. *Find Step…* is the same picker over a project's steps.
- *(done — S16)* The Run Agent confirmation — a `RunAnywayDialog` on the frame: the launch
  count in its title, what each chosen step waits on in its body, *Run Anyway* the primary.
  Of the fourteen `QInputDialog.getText` prompts, the Project family's four are
  `LinePrompt`s; feature, project_editor, testing and sync still have theirs.
- *(done — the graph editor pass)* Help ▸ About was a `QMessageBox.about` still naming the
  template's product. It is a `DialogFrame` over a `Table` now: the name and version, then
  what DPlanner is built on, a row per component with its licence.

Tables and lists:

- *(done — S9)* Order — the first table onto the `Table` primitive: heights from the font,
  the row as the unit of hover and selection, its milestones marked by their key badge,
  bold and their own wash rather than by a rule and extra air, and an empty state. The
  `#OrderTable` rules left `theme.qss` with the last widget borrowing them (S15).
- *(done — S15)* Tests — a `Table` under one strip of glyph verbs and selectors, results in
  their tone, a milestone's heading in its shade at a plain row's height; the step panel's
  roster is a small `Table` too.
- *(done — S15)* Estimates — two columns, the step and its sizes as chips in the cell
  (a grid down the rows), the number editor behind the last chip, an empty state per
  filter, a debounced rebuild with its indicator.
- LLM Calls, Telemetry — a `QTreeWidget` pretending to be a table; nesting drawn as four
  spaces; columns re-measured every second.
- *(done — S15)* Implementation notes — a `RichList` under a strip with its verbs and a
  label filter.
- *(done — the Specs tab pass)* Specs tree — the uniform row heights are gone, and both
  strips are `Toolbar`s of glyphs over a `StatusLine`. The pinned Topology row stays as it
  is: `EMPHASIS_ROLE` + `RULE_ROLE` together are what `list_rows.py` offers for a row that
  reads as a header, and it genuinely selects and shows a page, so it is on the primitive
  rather than faking one.
- *(done — S15)* Assets — two `Table`s under one strip (attach, open, copy the path,
  delete, clean up) and a filter over *unused* and each source.
- *(done — the problems pass)* Problems panel — two-line rows, the finding's remedy on
  the second line, one worded face dropping the launch profiles, and an `EmptyState`
  where the list would be. It stands inside the project tab, beside the canvas. (It
  replaced the Features panel, which went with the feature catalogue.)
- *(done — S16)* Agent profiles — a strip over a two-line table: the name over the two
  commands, the default the one bold row, its verbs greyed with the reason in their words.
- Index tree — unstyled or ink-only hover. *(The palette list is done — S15: it says when
  nothing matches, and speaks the strips' words.)* *(The Settings tree is done —
  S16: the picker list's wash and edge, folders as headings.)*
- *(done — S15)* Task and Agents browsers — one `RowWell` on the dialog frame; a task
  with no known fraction is a busy line. Milestones list — a `Table` with the day each
  milestone begins set in the cell, its colour and *Begin When the Previous Lands* on the
  Time tab's one `Toolbar`.
- *(done — the signalling pass)* Every debounced view now carries the indicator, and the
  Time tab's hand-shown *Recalculating…* label is gone; `ExitDialog` is on the frame, and
  the quit-time save has a progress dialog over its repositories.
- *(done — the documentation pass)* The Documentation view is on the primitives: its rows
  are `TwoLineDelegate` with the state in the trailing slot (a date when there is nothing to
  act on), its strip is a `Toolbar` whose verbs come from the registry and whose arrow drops
  a data child menu, where a document stands is a `StatusLine`, and its own copies of
  `CONTROL_GAP`, `SECONDARY_ALPHA` and the row paddings are gone. The explainer under its
  caption went with them — `docs/screenshots/s11-documentation/`.
