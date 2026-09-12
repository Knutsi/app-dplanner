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
| a dialog, a confirmation, a one-line prompt | `DialogFrame`, `confirm()`, `LinePrompt` | `framework/dialog.py`, `framework/widgets.py` | the modal: `dialog-*`, `dialog-refused-*` |
| a table | `Table`, `Column`, `Cell`; `key_badge_icon` for a milestone | `framework/table.py`, `theme/icons.py` | the table tab: `table-*`, `table-selected-*` |
| a strip of verbs over a surface | `Toolbar` | `framework/toolbar.py` | the table tab's strip |
| a filter on a strip | `FilterButton` | `framework/toolbar.py` | `table-filtered-*`, `filters-*` |
| a combo box on a strip or in a dialog | a plain `QComboBox` — the stylesheet dresses it | `theme.qss` | `dropdown-*` |
| "the view is rebuilding" | `UpdatingIndicator` — a `Spinner` on its own | `framework/signalling.py` | the strip's right end, `dialog-working-*` |
| "this button's work is running" | `Spinner` | `framework/signalling.py` | `dialog-working-*` |
| busy, ok, error or plain information in words | `StatusLine` | `framework/signalling.py` | the modal's *Signalling* block |
| a page with nothing in it | `EmptyState(stands_in_for=…)` | `framework/widgets.py` | `table-empty-*` |
| a caption over a block, a remark under it | `caption()`, `note()` | `framework/widgets.py` | the modal's form |
| a two-line list row | `TwoLineDelegate` | `framework/list_rows.py` | the palette, the notes tab |
| when a rebuild is owed | `Debounced.pending_changed` | `framework/debounce.py` | — |
| a margin, a gap, a height | a token | `theme/tokens.py` (*Tokens*) | — |

## How people move through it

The rules below are derived from what a person actually does here, not from taste. Four
flows, and what each surface on the way must make unmistakable:

- **New step → details → run agent.** *New* drops a card and opens Step Details on it with
  the name selected, so typing is naming; the aspect bar says what the step is. *Run
  Agent* is a plain button on the Agent tab. When the graph says the step's prerequisites
  are not done, a confirmation names them — the count in its title (*Run 3 Agents*), the
  step in its lead, the waiting steps in its body — with *Run Anyway* as the primary. The
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

Five principles fall out of them, and every rule below is one of these applied:

1. **The primary action is the flow's next step**, and it moves as the flow does — *Connect*
   until connected, *Refresh* while there is something to take in, then nothing.
2. **A confirmation names what it is about**: the thing in its lead, the count in its title.
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
  the 3 px status bar it replaced is gone — one strip, two facts.
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

A report of several columns whose rows relate — the coverage view's spec, features,
milestones, tests — draws each column as a **lane** (`$BG_ELEVATED`, 1 px `$BORDER`,
`RADIUS_MD`, a bold secondary caption inside its top) with the cards stacked inside and
the connections as curves in the **gutters** between lanes, never across a lane. A lane
scrolls on its own — the wheel over it, a 4 px thumb at its right edge that exists only
while it overflows — and the view itself never scrolls. Picking a card lights its path
and dims everything else to about a third; the picked lane never moves, every other lane
brings its first lit card into view. A card's state is a mark at its top-right corner —
a hollow accent ring for *behind*, a filled accent dot for *drifted*, green for *ok*, red
for *failed* or *lost*, a faint ring for *pending* — never a word.

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
- A dialog whose every edit is live and already undoable carries **no buttons at all** —
  there is nothing to confirm and nothing to cancel, and a Close button under a form that
  has already saved is a line of chrome saying so. Escape and the title bar close it; the
  step details dialog is the worked example.
- **Past two or three verbs on one thing, the glyph buttons become a `⋯` menu.** A row of
  bordered glyphs is a row of riddles — each says its verb only in a tooltip, and the row
  grows with every feature. One `⋯` beside the thing, dropping a menu of *glyph plus
  words*, says all of them at once and costs one control. Build the menu when it opens
  (a glyph carries the colour it was painted in) and grey what cannot run right now, with
  the reason in the entry's own words — never drop it, or the list changes shape and stops
  being learnable. The Project dialog's repository columns are the worked example.

## Dialogs

Every dialog is a `DialogFrame` (`framework/dialog.py`), and its anatomy is the frame's:

- **Top to bottom: the title, a lead, the body, the footer.** The title is printed in the
  body — two points up, normal weight, the card-title look — because a window manager may
  draw no title bar at all (the developer's does not), and where it does, the title is the
  platform's type at the platform's size; the window title is set too, for the switcher.
  The lead is one secondary line saying what *this* dialog is about, with the thing's name
  in it (*"Build the modal" waits on 2 steps not done yet*) — never a standing definition,
  which is *Words*' rule. Then the body, then **the footer as a band**, edge to edge below
  the page: the elevated ground under a faint hairline, its buttons 12 px inside it. It is
  the one place a dialog has a second ground, so the eye finds the way out without reading.
- **Footer slots, left to right: destructive · status · stretch · secondaries · Cancel ·
  primary.** The destructive verb is a different exit that costs something (*Quit Without
  Committing*, *Delete*), never an answer to the question; the far left is as far from the
  accent as the footer allows, so a hand travelling to the primary never crosses it, and
  the status slot between them keeps the two from reading as a pair. Cancel sits beside
  the primary, where the eye goes to leave.
- **No buttons when every edit is live and undoable** — the frame then shows no footer
  at all; Escape closes it. Step Details is the worked example.
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
  question as the lead, the verb a *quiet* button (it discards), Cancel the default.
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
- **A selected item is lifted, not recoloured.** The accent goes on the border; the item's
  own fill *gains* rather than being replaced, so whatever the colour was saying — a
  milestone is purple, finished work is green — it still says while the item is picked. Where
  a surface can afford it (a canvas), a couple of pixels of rise over a soft shadow is what
  makes the difference unmistakable without a second colour. `renderers.paint_node` is the
  worked example.

## Lists of rich items

A `QListWidget` of multi-line entries uses a `QStyledItemDelegate`, not concatenated `\n`
text: the delegate gives each row real padding, a primary/secondary text hierarchy, wrapped
text that re-lays out on resize, and a selection state that recolours both lines legibly.
`framework/list_rows.py`'s `TwoLineDelegate` is the one to use.

- **A list when there is one column of things; a table when a reader compares across
  rows.** A list row is two lines — the *what* in primary ink, the *why* under it in
  secondary **and a point smaller**, 4 px apart, 10 px above and below, 12 px at the
  sides — the same row a two-line table cell draws, so the two never disagree. The row's
  glyph sits on the first line, never centred on the pair: it is the name's.
- **The trailing note** (a date, a count, a shortcut) sits at the right of the first line
  in secondary ink, measured first so the name elides against what is left.
- **Hairlines only under a pinned row that heads the list**; between ordinary rows the
  padding is the separator.

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
  right-align so their digits line up, with the unit inside the cell (*3 d*); the header
  reads from the left with everything else. The header stays bold secondary over one
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
  milestone's row stays purple while picked (*Colour*). Nothing else marks it: the focus
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
  rounded chip in the milestone tone (`key_badge_icon`), the key being what a milestone is
  known by across the graph. The second line then says what the row gathers, not the key
  again.
- **A group heading is a spanned row nobody can pick**: bold secondary words at a plain
  row's height, no hover, no edge (`add_heading`). Nothing else separates the groups; the
  heading is the separator.
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
  `theme/icons.py`'s painters, inked in the secondary tone and re-inked on a theme change.
- **What no longer fits folds into a `…` menu at the strip's end**, as glyph *and* words,
  taken from the right — never a second row, and never Qt's own overflow, which pops the
  hidden buttons up as glyphs again. A widget among the verbs (a filter) never enters the
  menu; it hides when there is no room for it. The strip's own size hint is the `…`
  button's, so a page can be dragged as narrow as it likes and the strip folds rather than
  squeezes.
- **Every control on a strip is one height** (`CONTROL_HEIGHT`, 32 px), set in code: a
  glyph button, a worded button and a combo box disagree by a few pixels under the style,
  and a strip whose buttons are not one height reads as several strips.
- **A divider is the hairline at half strength** (`$BORDER_FAINT`, the border blended
  halfway into the ground), 6 px short of the controls' top and bottom: it parts groups
  without being read as a control.
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
  control strip, *outside* the `control_bar` toolbar so the » overflow can never swallow
  it, keeping its room while hidden so the strip never reflows. The content stays; nothing
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
  mood, the words carry the fact, and a paragraph of red is shouting. Four tones — info
  (the line's own ink), busy (the spine's blue), ok (the good green), error (the bad red),
  `theme/tones.py`'s `STATUS_TONES`, the same shades the canvas spine wears.
- **A progress bar is 4 px, accent, no text, no frame** — one bare `QProgressBar` rule —
  and only for work whose end the application knows: a fetch of 12 pages, a save over 3
  repositories. Never for the debounce, never for an agent (a peer, not a task), and not
  indeterminate: an unknown fraction is *busy*, and busy is a line. (The task browser's
  rows keep their indeterminate bars until the design pass reaches that surface — a task's
  end really is unknown, so what they owe the rule is a busy line, not a fraction nobody
  can compute.)
- **A remembered duration may fill a bar, under a fact that leads it.** How long the last
  run of the same operation took (`TaskService`'s duration memory, kept per user and
  machine) is a fair guess and a poor promise, so it is never the *only* thing a bar
  reads: the known count leads — repositories recorded, pages fetched — and the estimate
  only fills the gap between one landing and the next, so the bar never sits behind what
  has actually happened. An estimate that runs out holds just short of full
  (`ESTIMATE_CAP`), because a bar that reads complete while the work goes on is worse than
  one that reads slow. With nothing remembered the bar is the count alone, which is the
  honest picture on a machine's first run.
- **Never a modal for a background fact.** A modal asks; a fact is said where it bites.

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
| `CONTROL_HEIGHT` | 32 | every control on a strip, set in code |
| `ICON_SIZE` (+ `ICON_GAP`) | 16 (+ 8) | a glyph, and the gap after it |
| `KEY_BADGE_W` | 28 | a key badge, and the slot a glyph column reserves on every row |
| `RADIUS_SM` / `RADIUS_MD` | 5 / 8 | buttons, chips, fields / wells, cards, tables, lanes |
| `SECONDARY_ALPHA` | 160 | a painter's secondary ink (~63 %) |
| `SCREEN_SHARE` | 0.8 | the screen a framed or editor dialog may claim |
| a title | +2 pt | a dialog's title, a page's answer line, a card's title (`title_font`) |
| a secondary line | −1 pt | a row's second line, the `EmptyState` line (`detail_font`) |
| an edge | 2 px | a picked row's left, the active pane's top |
| a hairline | 1 px `$BORDER` | a header's rule, a seam, a pinned row |
| a progress bar | 4 px | the one kind there is |
| `$BORDER_FAINT` | derived | the hairline blended halfway into the ground: a strip's dividers |
| `$ACCENT_WASH` | derived | the accent washed over the overlay ground: a control that is on |

## Bringing a surface up

The checklist a later step runs over a surface it touches — each answerable yes or no
from the code or a screenshot, and Debug ▸ Design Example is what *yes* looks like:

1. Is every margin, gap and padding a token, never a literal?
2. Is a dialog a `DialogFrame` and a page a control strip over its content — not a
   hand-rolled layout?
3. Does the dialog print its title in its body, with a lead that names the thing?
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
    control one height — with a `FilterButton` where there are filters?
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

- `StepDetailsDialog` — designed already (no buttons, live edits); not on the frame, so
  its title is only the window's.
- `SettingsDialog` — 12 px margins, an unstyled tree with no seam against the page, a lone
  Close.
- `ProjectDialog` — the most designed; create mode's footer at 8 px against the 12 px
  sections, and its two modes disagree about buttons.
- `OpenProjectsDialog`, `MovePlanDialog`, `RepositoriesFolderDialog`, `GhRepoListDialog` —
  hand-rolled footers with the right shape; no title in the body; the GitHub list's filter
  is uncaptioned and unfocused, and its status line sits in the button row.
- `ExpandedTextDialog`, `ChartDialog`, `ImagePreviewDialog`, `FeatureDialog` — right
  metrics, a `QDialogButtonBox(Close)`.
- `AssetPickerDialog` — Ok/Cancel box for the main insert gesture, a hand-rolled empty
  label.
- `TaskBrowserDialog` / `AgentBrowserDialog` — a well of rows, styled once and copied
  whole with no stylesheet for the copy; one row-well primitive would absorb both.
- Confluence `ConnectDialog` — the one `QFormLayout`, system labels unlike every caption,
  three button clusters, no size.
- `PromptFallbackDialog` — 16 px margins, default spacing, a prompt pane that is not a
  text well.
- `ConflictDialog` — four peers in a `QDialogButtonBox`, no object name (its primary got
  no accent until the primary rule stopped needing one).
- `InstallDialog` (Tools ▸ Install DPlanner…, which replaced the command and skill
  dialogs) — built to this document as it stood: a well of rows modelled on the task
  centre, one primary, Close as the default; its state is a word, not a glyph, and it is
  the readiest candidate for the frame.
- `SaveSnapshotDialog` — the panel's 6 px idiom hand-simulated with `addSpacing`; the box's
  Save.
- `DiffDialog` — no margins, no spacing, an uncaptioned picker over an unstyled pane.
- `CommandPalette` — designed rows in an unstyled frameless frame.
- The Run Agent confirmation — the application's most consequential question, as a
  `QMessageBox` with a bulleted list; and fourteen `QInputDialog.getText` prompts.

Tables and lists:

- Order — the one designed table, still: bold header with no hover on the rows, 5/8 px
  cells, per-row heights, no empty state, no updating.
- Tests — borrows `#OrderTable` by name; a spanned heading as tall as a two-line row.
- Estimates — centred headers, an object name no stylesheet knows, an embedded spin box
  per row, no empty state, no debounce at all.
- LLM Calls, Telemetry — a `QTreeWidget` pretending to be a table; nesting drawn as four
  spaces; columns re-measured every second.
- Implementation notes — the two-line delegate, frameless and borrowing `#OrderTable`.
- Specs tree — uniform row heights under a two-line delegate; a pinned header faked as a
  row.
- Assets — two lists with no object name at all; a baked empty message (now on the swap).
- Features panel — single-line rows with the detail in a tooltip; the hint hides when the
  list is empty, the inverse of every other surface.
- Agent profiles — plain strings with *(default)* appended and three stock buttons.
- Settings tree, Index tree, palette list — unstyled or ink-only hover.
- Task and Agents browsers, Milestones list — widget rows laid out by hand, one of them by
  measuring strings.
- *(done — the signalling pass)* Every debounced view now carries the indicator, and the
  Time tab's hand-shown *Recalculating…* label is gone; `ExitDialog` is on the frame, and
  the quit-time save has a progress dialog over its repositories.
