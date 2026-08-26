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
below. It is what separates two panels stacked in one area, and it is the right-click target
for moving the panel — the panel's own widget keeps its own context menu, so there would be
nowhere else to put it. **A panel's content therefore never prints its own caption**; the
header already says what it is, and two captions is the one thing `#InspectorCaption` forbids.

A panel with nothing to show goes off screen rather than showing a placeholder, and an area
with nothing in it takes no width at all. The reasoning is the card rule one level up: an empty
box is worse than no box.

## Cards

The one sanctioned box. A panel that hosts *independent features contributed by different
modules* gives each feature a card (`framework/cards.py`: `ToolCard` in a `CardStack`).
Cards separate features from each other; they never group one form's fields — that is
still spacing.

- A card is a **well** on the elevated panel: `$BG_BASE`, 1 px `$BORDER`, `RADIUS_MD` —
  the same contrast as a plain field, so a panel of cards and a panel of fields read alike.
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

## Buttons

- One **primary** action per surface: `#PrimaryButton` (accent fill, `$ON_ACCENT`
  text). It is the action the user came to perform — Apply, Save, Start.
- Everything else is a quiet bordered button (the `#ToolbarButton`/`#OpenDialogButton`
  look) or a plain default `QPushButton`.
- Destructive or dismissive actions (Cancel, Reject) never get the accent.

## Colour

- One warm accent, used sparingly: the primary button, the checked state, focus.
- Semantic region tints (diff added/removed, status colours) are low-alpha constant
  `QColor`s that read on every theme (deliberate exception #2 — see the diff highlighter
  in `modules/sync/view.py`); never opaque theme-specific backgrounds.
- Every other colour comes from a `Theme` field, through `theme.qss` or the palette.

## Lists of rich items

A `QListWidget` of multi-line entries uses a `QStyledItemDelegate`, not concatenated `\n`
text: the delegate gives each row real padding, a primary/secondary text hierarchy, wrapped
text that re-lays out on resize, and a selection state that recolours both lines legibly.
