# Design guidelines

How the UI should feel: calm, spacious, unhurried. These rules exist because Qt's defaults
produce cramped, administrative-looking surfaces, and because a desktop application is
judged on its spacing long before anyone reads a word of it. Every new dialog, panel and
list applies them from the start. All colours flow through the theme (`$TOKEN`s in
`theme.qss` or the palette) — the two deliberate exceptions are noted below.

**This document is the standard for all UI work in this repo.** New surfaces follow it
from the first commit; touching an existing surface includes bringing it up to these rules
(the boy-scout rule applies to pixels too). When a rule here is ambiguous, match what the
step detail panel in `modules/step_properties/panel.py` does — its captions, its spacing, and
the way its tabs are titled. `CLAUDE.md` points agents here.

## Space

Use the 4-point scale: **4 / 8 / 12 / 16 / 20 / 24**. Never invent in-between values.

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

The same rule decides a control's fate. A selector with one entry, a switch whose two
positions give the same answer, a caption over a single obvious field — each is a thing to
read that teaches nothing. Compute whether it would say anything and leave it out when it
would not; the Covers tab's New/Cumulative switch is the worked example.

## Buttons

- One **primary** action per surface: `#PrimaryButton` (accent fill, `$ON_ACCENT`
  text). It is the action the user came to perform — Apply, Save, Start.
- Everything else is a quiet bordered button (the `#ToolbarButton`/`#OpenDialogButton`
  look) or a plain default `QPushButton`.
- Destructive or dismissive actions (Cancel, Reject) never get the accent.
- A dialog whose every edit is live and already undoable carries **no buttons at all** —
  there is nothing to confirm and nothing to cancel, and a Close button under a form that
  has already saved is a line of chrome saying so. Escape and the title bar close it; the
  step details dialog is the worked example.

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

## Tables

- **Column headers are left-aligned**, whatever the column holds
  (`header.setDefaultAlignment`, not Qt's centred default). Numeric *cells* still
  right-align so their digits line up; the header reads from the left with everything else.
- A row emphasised over its neighbours (the order table's release rows) grows a point
  rather than going bold — weight in a table of quiet lines shouts.
