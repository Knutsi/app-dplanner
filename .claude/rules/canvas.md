---
paths:
  - "{src/dplanner,tests}/modules/{canvas,problems}/**"
  - "src/dplanner/theme/{cards,tones}.py"
  - "tests/cli/test_{layout_cli,step_duplicate,stack_cli}.py"
  - "scripts/render_graph_editor.py"
---

# Canvas — the graph editor's modes, gestures, cards and marks

- **A canvas key names action ids; it is never an `ActionSpec.shortcut`.** A bare `h` on a
  menu-bar QAction fires application-wide and eats a keystroke in the step editor. Bind it in
  `modules/canvas/keymap.py`, where a key names the verbs it means in order and the
  first the context allows runs — that is how one Delete key covers links and steps.
- **A painter never trusts `option.palette`.** Qt fills `QStyleOptionGraphicsItem.palette`
  once, when the scene is created, and never refreshes it, so every canvas item kept the
  colours of whatever theme its tab opened in. `items.live_palette()` is the only source of
  colour on the canvas. Its cousin: **a colour copied out of the palette onto a widget goes
  stale** — `TabHost` tints its tab titles, so it re-tints on `QEvent.PaletteChange`. If a
  surface stores a colour, it owes that hook.
- **The Problems list stands beside the canvas, inside the tab.** Where clicking a problem
  and landing on its step is a short trip. It is a `SidePanel(title, icon, build)` on
  `CanvasDeps`, named by the composition root and hosted through
  `framework/side_panel.py` (`shell-ui.md`'s bullet has the mechanism), so `canvas`
  imports nothing from `problems` and `problems` registers no panel (it offers
  `create_panel()`, the `step_properties` arrangement). Whether it stands is a field on
  `Look`, like every other preference the editor keeps, and `canvas.side_panel` is the verb.
  **Its reading is the count** — `ReadingPanel`, one string and a signal — which the strip's
  leading band shows beside its glyph as `(4)`, read from the panel's last settled rebuild
  rather than probed in a state callback. `docs/architecture/canvas.md`'s *The Problems list lives
  in the graph, not in the window* has the reasoning.
- **Canvas input is a stack of modes, and Escape pops one.** A mode handles input and has
  power over the view; a hook that returns False lets the event fall through to the canvas
  keymap and then to Qt, which is why `IdleMode` is nine lines and why a mode that claims a
  press suppresses node dragging without a flag anywhere. A mode still only *reports* — the
  activity turns its signals into commands. The current mode is published into the context, so
  a mode-switch action's `checked` stays a pure function of it. A mode that drags something
  the canvas draws — a card's frame, one side of a cut — is a `GestureMode`: it says what it
  holds, how to restore it on Escape and what the release means, and inherits the rest.
  `docs/architecture/canvas.md`'s *Who owns the canvas's input* has the reasoning; add a behaviour
  as a mode, never as a field.
- **Lasso is a mode, and it touches cards.** `LassoMode` draws a `QPainterPath`, and on
  release the scene answers `nodes_touching(path)` by the node's *body* rect — never
  `scene.items(path)`, whose hit shape is the body plus `PAINT_MARGIN` and includes the
  edges. One lasso ends the mode, Shift on the release adds to the selection, and the mode
  switch is `steps.lasso` (`S` on the canvas), the same shape as `steps.connect`. Lasso and
  divide share one `OutlinePreviewItem` through `Canvas.aim_outline`.
- **Divide is a mode, and it pushes a side.** `DivideMode` (Graph ▸ Divide ▸ Vertical or
  Horizontal; `D` and `Shift+D` on the canvas) lays a cut under the cursor from edge to
  edge, and the press hands over to `DivideDragMode`, a `GestureMode` that holds every card
  and shifts the ones on the side dragged towards by the snapped distance. Which side a card
  is on is its **centre** at the press, and a drag back past the cut flips the sides. The
  release is one `graph_divided` signal and one `Divide Graph` command, written only for the
  cards that moved; one divide ends the mode, and Escape puts the cards back and leaves. The
  band drawn beside the cut — the room being made — is the same `OutlinePreviewItem`.
  `docs/architecture/canvas.md`'s *Who owns the canvas's input* has the reasoning.
- **Contract is Divide's other half, and it stops a gap short.** `ContractMode` (Graph ▸
  Divide ▸ Contract Vertically or Horizontally; `X` and `Shift+X`) lays the same cut, and
  `ContractDragMode` pulls the side *behind* the drag after it as one block, clamped live
  by `geometry.contract`: it stops the sorts' gap (`H_GAP`, `V_GAP`) short of the first card
  ahead of it whose extent across the travel overlaps a mover's, the room rounded towards
  the cut onto `GRID`. A card in another band never stops it and a pair already overlapping
  is ignored, so it never makes an overlap; the status line names the pair that stopped it.
  The release is `graph_contracted` and one `Contract Graph` command — `divide_command`
  under that label. **Both drags are one `_CutDragMode`** whose `follow` is the Qt-free rule
  the `layout` verb runs (`shift` for Divide, `contract` here), so the canvas never carries a
  second copy of either; it runs them over `stacks.Packing`'s blocks, so a stack travels
  whole. `docs/architecture/canvas.md`'s *Contract closes a gap and stops one short* has
  the reasoning.
- **Redirect is a mode, and it moves one end of a bundle.** Pick arrows, run *Graph ▸
  Redirect ▸ To Step* (`E`) or *From Step* (`Shift+E`), click a step: every picked link
  moves that end onto it, in one undo entry. **Which end travels is the verb's, never
  inferred** — the case the tool exists for is a bundle that agrees on neither end — so
  *To* moves the arrowhead (`WAITER`) and *From* the tail (`SOURCE`), matching the arrow
  the canvas draws. `Library.redirection(edges, anchor, end)` is the one question, asked
  through `link_refusal` alone and returning what moves beside what is refused and why;
  `redirect_edges_command` writes one `SetEdgesCommand` per affected list with its *final*
  content. Four readers of that one answer: the ring under the cursor, the click, the
  status line and `dplanner step redirect --to/--from`, which names the arrows by the steps
  they hang off (`Library.edges_of`). **A refusal is per link** — the rest still move, and
  the status line says what did not. The verb is enabled exactly while links are picked,
  greyed with the reason otherwise. `docs/architecture/canvas.md`'s *Redirecting a link moves one
  end* has the reasoning.
- **A right-click is composed by what is under it.** The click makes its subject current —
  a card or an arrow outside the pick *becomes* the pick, one inside keeps it, empty canvas
  clears it and notes the point — and the menu is then a function of the selection alone:
  `menus.py`'s `BANDS` row for a **card** (the Step menu's bands about the step
  itself, `STEP_ITSELF`), an **arrow** (Graph ▸ `links`), a **mixed** pick (Graph ▸
  `narrow`, Edit ▸ `clipboard`, Make Stack, Put on a Branch, then `Step` and `Links` children) or the **background**
  (Graph ▸ `new` and `select`, Edit ▸ `selection`, Go ▸ `survey`), rendered by
  `fill_bands`. **A card is the step, not a table's Step menu**: its type and tests are set
  in Step Details, compiling is the Docs tab's, and a view the index lists as a row under
  the project is left to that row — on the card, on the background and in the Project menu
  alike (their seat in the bar is Go ▸ `views`, which no right-click renders); what a table
  adds is filed in groups of its own (`compile`, `surfaces`) so the card can leave them
  out, and what a step *is* (`classify`) is in no menu at all. A **stack** — the pick exactly
  one stack's members, which a click on its frame makes — leads with Step ▸ *Stack*'s
  `stacked` band flat (Add Step Below, Take Out, Dissolve) and puts the card's bands one
  level down; a card's own menu carries the *Stack* child. A new target is a row and a
  branch in `target_of`; a new verb for arrows registers into Graph ▸ `links` and appears
  wherever that band is rendered. **`IdleMode` claims every right press**: handed
  to Qt, a right press on an arrow (selectable, not movable) clears the whole selection
  before the menu is asked for, so three picked arrows became one. `context_menu()` builds
  and `_on_context_menu` only shows, so a test reads the menu without a modal loop. **Delete
  removes everything picked**: the key names `("steps.delete", "links.remove")`, and
  `steps.delete` takes any arrow picked beside the steps into the same `remove_steps_command`
  — one undo; `links.remove` is the arrows alone, and `steps.unlink` the link between two
  picked steps. `docs/architecture/shell-ui.md`'s *A right-click is composed by what is under it*
  has the reasoning.
- **Marks are a way of looking, remembered per user — and both are on.** Starts and Ends
  (`canvas/marks.py`, Qt-free) are the `marks` of the module's one
  `Look` (`look.py`, with the spotlight, the background and Snap to Grid beside them),
  written to `user_config` and fanned to every scene like `RenderHints`; a tab opened later
  wears them. **On by default**: a socket with nothing on it is what a graph can be wrong
  about, and a preference that has to be found before it can help is one that helps nobody
  — so switching one *off* is the deliberate act, and `Marks.from_json` gives an absent
  name the default rather than False, which lets a default change reach somebody who never
  touched that switch. There was a third, Orphans, a refusal-red ring round a node with no
  links; the squiggle below covers it, and a stored `orphans` is now ignored.
  Which sockets a node has connected is `ordering.ports()` over the drawn edges, derived
  every sync — in the domain rather than beside the marks because `graph.orphan` lint asks
  the same question, and a module may not import another module's copy of an answer. The toggles' `checked` reads the module and the module calls `context.refresh()` —
  the theme-toggle pattern, deliberately not an edge on the activity node, because a
  preference outlives any tab. `docs/architecture/canvas.md`'s *Marks are a way of looking* has the
  reasoning.
- **A step something is wrong about wears a squiggle, and the reading is settled.** The
  editor's underline, 3 px of refusal red hanging `PROBLEM_DROP` below the body and
  starting past the key block — *look here*, where the Problems panel is the asking. It stands
  for **every** lint check there is, which is why it replaced the orphan ring: `graph.orphan`
  is one such check, so a ring and a squiggle would have been two red vocabularies for one
  fact, and a *preference* that could hide a problem is not a way of looking. The canvas
  never learns what a problem is — `NodeAccent.flagged` is the composition root's
  translation, like every other accent. **Nothing runs lint on a sync**:
  `modules/problems/findings.py` is one settled reading with two readers, the panel and the
  canvas, because the checks are super-linear in the size of a plan (1 ms at 40 steps,
  9 ms at 120, 66 ms at 300). It names the project on both its signals — `changed` for the
  panel, which lists messages, and `flagged_changed` for the canvas, which draws one mark
  per step and must not repaint because a title moved. `docs/architecture/canvas.md`'s *A problem is
  a squiggle, and the reading is shared* has the reasoning.
- **A picked step lights its arrows, and the spotlight fades the rest.** One derivation —
  `selection.neighbourhood(edges, picked)`, the arrows with an end among the picked steps and
  the steps at their far ends, re-derived every selection change and every sync — read twice.
  The arrows it names are drawn in the accent **always**: that is the second half of what
  being selected means, not a setting. Fading everything else *is* a setting, because it
  hides part of a true picture: `Look.spotlight` (*Graph ▸ Spotlight Selection*), off by
  default where the marks are on, **and holding Alt lends it for a glance** — the view owns
  the held half and ends it on `focusOutEvent`, since Alt+Tab is Alt held and then taken
  away. Not a mode: it handles no input. **Nothing picked lights nothing**, so the
  preference left on never dims a canvas to say nothing. The fade is item opacity at
  `DIM_OPACITY` (`theme/cards.py`, shared with the coverage trace's lit path), never a
  paint-level flag — a card recedes whole and `renderers.py` learns nothing.
  `docs/architecture/canvas.md`'s *The spotlight is one derivation* has the reasoning.
- **A scrollable area's extent must never depend on what the user is moving.** The canvas is
  a *plane*: a constant scene rect centred on the origin, far larger than any graph. That is
  what lets panning go on for as long as anybody wants, and it is also the answer to the older
  bug — an extent recomputed from the items moved under every node drag, and the canvas
  appeared to pan away under it. A constant cannot. The scroll bars are hidden with it (a
  handle a two-hundredth of its groove says nothing true) and the minimap orients instead.
  The wheel scrolls and Ctrl+wheel zooms. **Space drags the plane, wherever the press
  lands** — `PanMode` claims every press and scrolls the hidden bars by the pointer's travel
  itself, never Qt's `ScrollHandDrag`, which hands a press to the card under it and moved
  the card while Space was held — **and with Space held the arrows and `hjkl` page it**, a
  third of the viewport at a time, a tenth with Shift, claimed in the mode so the same keys
  stop selecting steps while the hand is on the plane.
- **The key block is the card's left edge, and it says who and where.** `paint_key_block`
  (`theme/cards.py`, shared with the coverage lanes' step cards and copied by the report's
  `drawings.py`, which a test holds to it) draws a 56 px strip inside the left edge,
  clipped to the body and washed by status — busy blue for in-progress, warn amber for
  ready-for-review (a person looks next), the good green for ready-to-merge and done (only
  done also greens and mutes the body), bad red for blocked, a quiet shade otherwise
  (`NodeAccent.key_tone`, read from `theme/tones.py`'s `STEP_STATUS_TONES`; a wait wears
  none, whatever it stored — `_card_status`) — carrying the
  key set level and bold, and over it **who works the step**: the sparkle for an agent
  step, a person otherwise (milestones, features and checks included), and a wait's clock
  in the attention amber, always (`key_glyph`, `key_glyph_tone`). The two ambers are told
  apart by shape: a clock is a stroke on a quiet block, a review is the block's own wash.
  **One rule, three surfaces**: `_primary_glyph` in the composition root answers for the
  canvas, the coverage lanes and the report's graph, and Find's rows wear the same glyph.
  The top edge's medallions say what a step *is* and never who works it — no spark and no
  clock among them — because a card says a thing once. The title and the left-edge
  decorations start past the block (`LEFT_INSET`), and `MIN_NODE_W` grew with it.
  `docs/architecture/canvas.md`'s *The key block names the card and says who works it* has the
  reasoning. The icon's box (`KEY_GLYPH`, 28) is sized so a broad glyph spans a
  three-character key; the report's copy of it is pinned by the same test.
- **A milestone's outline is doubled** — `theme/cards.py`'s `MILESTONE_BORDER_W` on the canvas
  and the coverage lanes, twice the report's own border there — and it is at least that when
  the card is picked or aimed at: selection recolours a milestone's outline, never thins it.
- **A picked node is lifted, not recoloured — and every card rests on a shadow.** Selection
  thickens the border to the accent, *gains* whatever fill the node already had (so a picked
  milestone is still purple), lifts the card two pixels over a deeper shadow than the faint
  one every card sits on, and claims a Z of its own. The fill is painted **opaque** —
  `renderers.over()` blends the tint over the palette's window colour — so nothing under a
  card shows through it: not the shadow, not the ground's grid. The
  rings composite, so a shadow's alpha buys twice what it looks like. `PAINT_MARGIN` is the
  one number every decoration is measured against and `boundingRect` is exactly it,
  **constant whether or not the node is selected**; `shape()` is the card and its resize
  band, never the bounding rect. `docs/architecture/canvas.md`'s *A picked node is lifted, not
  recoloured* has the reasoning.
- **A card's size is the step's, stored beside its position; absence is the default
  footprint.** Drag an edge or a corner (`NodeResizeMode`; the band is `GRAB_IN` inside the
  border and `EDGE_REACH` outside it, and `IdleMode` shows the arrows over it) and one
  `Resize Step` command writes `x, y, w, h`; a move carries the size back in
  (`write_position(x, y, size)`), a paste keeps it, and every sort and layout spaces by
  `positions.node_size` and never changes one. Every painter takes the body rect it is
  handed — nothing measures from `NODE_W` — the title wraps onto as many lines as the card
  has room for, and the bottom line holds the estimate at the right in full ink — a
  wait's how long it holds, `until 21 Oct` or `3 wd` — and nothing in words: every aspect a
  card wears is a medallion, a badge, a bar or a pill, never a phrase.
  `docs/architecture/canvas.md`'s *A card's size is the step's* has the reasoning. **The one
  exception is the branch strip** (`NodeAccent.strip`): a card whose work is on a feature branch names it in a `STRIP_H` band across its foot, and **the card is that much
  taller** — `positions.footprint(step, strip, body=node_size)` is the one size rule, the
  canvas sizes its cards by it and every arranger is handed it as `size_for` (the editor's
  `strips` seam, the CLI's `strips` on `layout sort`); the arrows, the handle and the marks
  meet the *body's* middle, and a resize stores the body. `docs/architecture/canvas.md`'s *A card on
  a branch names it* has the reasoning. **The second is the playbook strip**
  (`NodeAccent.playbook`: `passes.standing`'s phrase, tone and stages, through the root's
  `PassStandings`), under the branch strip at the very foot, its stages the tooltip — **and a
  click on it opens the step's pass in Step Details**: `StripPressMode` claims the press (a
  button, never a handle), and a release on the strip emits `playbook_opened`, which the
  activity turns into `steps.details` with a `playbook` entity, a turn later — and **never in
  the footprint**: a pass is transient, so the card adds it to
  what it draws, hits and hands its stack (`size()`), never to what the scene pushes
  (`footprint()`), a resize stores or the arrows meet. `docs/architecture/canvas.md`'s *A card
  running a playbook says where its pass stands* has the reasoning.
- **The look is one per-user value, and snapping is the gesture's, never the write's.**
  `canvas/look.py`: the marks, the background under the graph (plain, dots, lines,
  crosses — painted by `ground.py`) and *Snap to Grid* are one `Look`, kept under one key,
  pushed to every canvas by one setter, and read by every toggle in `view_verbs.py`; the
  next preference is a field there, never a third copy of that plumbing. While snapping is
  on, a drag, a resize and a placed step land on `GRID` through the scene's one
  `snap()`; what reaches disk is `snapped(value)` — a whole unit, as a float — so a CLI verb
  stores what it was given, a sort what it computed, and `layout shift` — a drag by a
  distance — snaps that distance as the gesture would. The drawn pitch is
  `pitch_for(zoom)`, a power-of-two multiple of `GRID` kept a readable distance apart on
  screen, so the ground is always a coarsening of what snaps. `docs/architecture/canvas.md`'s *The
  ground is a preference; snapping belongs to the gesture* has the reasoning.
- **Automatic graph layout is never persisted; an explicit sort is.** A node nobody moved is
  placed by dependency depth every time the project opens — storing that would make merely
  opening a tab dirty the project, and every CLI-created step would grow a position file
  behind the user's back. A sort *action* (`canvas.sort_*`, `dplanner layout sort`) is a
  user gesture, so it writes through the undo stack like a drag. Named layouts are a
  project-level entry under the same `project_editor` id — `docs/architecture/canvas.md`'s *An
  explicit sort persists; the ambient layout never does* has the reasoning.
- **Wave view derives positions; only Free view saves them.** Whether a project is in Wave
  view is per-user `user_config` (`layouts/verbs.wave_view`), and toggling it writes nothing:
  `ProjectActivity._sync` substitutes `sorts.arranged_in_waves`' seats in the `NodeSpec`s at
  the default size, and the diff sync moves the same items. The one way it reaches the store
  is *Keep This Arrangement* (`canvas.waves_keep`, one undo, then Free view) — `dplanner
  layout sort <project> waves` builds the same seats; a sort or a named layout leaves Wave
  view first, and Divide and Contract are greyed in it. **A card there is pinned**
  (`GraphScene.set_pinned`): picked, linked and opened, never dragged, resized or restacked.
  **The arrangement must hold still**: down a column by earliest start, then the highest
  source's place in the column before, then project order — one forward pass, top-aligned —
  so a link moves only what it changes the wave of, and nobody else swaps places; never add
  a sweep or a centring. Stacks fold through `stack.fold` (N39/N76). The ruler (`layouts/ruler.py`)
  numbers waves as the Order tab does — START, WAVE 2… — and reads each `Wave`'s span (which
  `layout show` prints too, off the same arrangement) and the cards' muted accents.
  `docs/architecture/canvas.md`'s *Wave view derives positions; only Free view saves them* has the
  reasoning.
- **There are no regions; a project saved with them opens without them.** Titled rectangles
  behind the graph were retired — annotation the graph knows nothing about goes stale with
  every sort, tidy and move. `positions.DATA_FORMAT` is format 2, whose one migration drops
  the project entry's `regions` and every named layout's region rects on read; that
  migration is the only code that knows they existed. **The project entry's one composer
  brings what it carries current first** (`entry_with` runs `migrated()`): an entry adopted
  from another writer since the open has not met the migration pass, and stamping it format
  2 as it stood would keep what the pass drops. `tests/old_canvas.py` is the old project
  every proof of this opens. `docs/architecture/canvas.md`'s *Regions were retired* has the
  reasoning.
- **A stack is one tall card to everything that reads positions.** Canvas data over a real
  `requires` chain, never a model object (`canvas/stacks/stack.py`, N3): every member's
  entry says `"stack": "<id>"`, the **first member's seat is the stack's** and the others
  store none, and the order is read from the chain. `positions()` derives the column — the
  members left-aligned under the first, `MEMBER_GAP` apart rounded onto the grid, inside
  `FRAME_PAD` of frame — and ignores a seat a member below the first stored. **Every
  arrangement goes through one fold**: `fold(project)` is the graph with each stack one block
  under its first member's id, sized to its frame, waiting on what the first member waits
  on and waited on by whatever waited on any member; `Packing` is its geometry alone (card
  seats → block seats → card seats). The five sorts and tidy fold inside themselves, so no
  caller changes; `layout show` measures the folded picture (N39: a stack stands in its first
  member's wave); `boxes()`, and so `free_spot`, see a frame; and `layout shift`/`contract`
  and the canvas's cut drag hand `geometry.shift`/`contract` the packing's blocks — a cut
  through a stack sends it to the side its frame's centre is on, whole. **Every write that
  moves a card goes through `position_commands`**, where the first member wins and a
  member's seat moves its stack; a resize is `resize_command`, and a member below the first
  writes only its size. A paste mints a new stack for a stack copied whole and drops the key
  from part of one. Add a reader of positions through the fold, never beside it — a second
  copy of the column is one that can split a stack. `docs/architecture/canvas.md`'s *A stack is
  presentation over a chain* has the reasoning.
- **A stack's frame is the stack's handle.** `StackItem` (z −2, under the arrows) is the one
  place the column lives on screen: `follow()` lays every member under the first card by
  `member_seats` at the cards' live sizes and fits the frame round them, so a sync, a resize
  and every drag show the derived column; the scene lays frames out after the cards and
  before the arrows, and a member's move reaches its frame first. **An arrow meets an item at
  a port** — a point and a heading: every card's near side, across, as always — so a
  stack's way in meets its first card's side and its way out leaves its last card's, the
  sockets any card has — and the chain's own links drawn **straight, down the frame's
  middle**, still `EdgeItem`s, so they keep their lane, lighting and picking. The "+" is `StackAddItem` (z 0.5), and a
  press on it runs `stacks.add_below` on the last card through a constructed context. A
  stacked card is never Qt-movable, shows a link handle only as the last, grows only right
  and down (`resize_command` stores no seat for a member below the first). **A drag moves
  the pick, and a stack moves whole**: `IdleMode` claims, in order, a right press, the
  handle, the "+", a resize band, any card with Shift held or a loose card the press leaves
  alone in the pick (the next bullet), a card in a stack or a picked card beside one, and
  then — after an arrow drawn over it, which stays Qt's — the frame; the drag is `BlockDragMode`,
  moving each block's anchor and reporting through `nodes_moved` (*Move Stack* for one
  stack); a click on a card narrows to it, one on the frame picks the stack, and a double
  click on the frame makes nothing. **A link end landing on a stack means its first card for
  an arrowhead and its last for a tail** (`GraphScene.link_end`, `link_target_at`, frames
  included) — link drag, Connect and Redirect alike — and the verdict is still
  `link_refusal`'s. New Stack is Graph ▸ `new`; Make Stack (`stack`) and Add Step Below,
  Take Out, Dissolve (`stacked`) feed Step ▸ *Stack*; each pushes its `stacks/edits.py` builder.
  **Make Stack links whatever is picked into one line** — the links' order, else left to
  right — and a mixed pick's right-click offers it flat, since a drag across a line picks
  its arrows too.
  `docs/architecture/canvas.md`'s *A stack's frame is the stack's handle* has the reasoning.
- **Shift-drag restacks one card, a loose card joins by any drag, and the cards make
  way.** A Shift press on any card narrows the pick to it and starts `RestackMode`, and so
  does a plain press on a loose card the press leaves alone in the pick — joining needs no
  key; Shift is what tells a member's restack from moving its stack, and several loose
  cards picked together stay Qt's drag, a plain move. Below the drag distance it is a
  click. The card follows the hand, and its **centre** against each frame's rect at the press,
  grown by `FRAME_PAD` — its own stack's first — says where it is; the slot is the one whose
  gap centre (`member_seats` over the order the drop would make, from the columns as they
  stood) is nearest. The other cards **glide** to that column over `MAKE_WAY_S` on one
  `FrameClock` the mode owns, running only while a card glides, stopped, unsubscribed and
  deleted on exit; `settle()` ends every glide for a test or a render — never wait on the
  clock. Out past its own frame the card is leaving (the column closes up, the frame
  shrinks, an empty one hides); a loose card over a stack joins at the slot, and over
  nothing is a plain move through `nodes_moved` that says nothing on the status line.
  **The mode reports where, never which verb**: `dropped_into_stack(step, stack_id, slot)`
  and `dropped_out_of_stack(step, x, y)`,
  and `StackVerbs.drop_into`/`drop_out` ask the model — `move_command` for a member,
  `add_command` for anyone else, `take_out_command` at the snapped drop — one undo each.
  Whether a stack may be reordered or joined is `StackVerbs.refusal` through
  `Canvas.stack_refusal` (`line_refusal`, then `join_refusal` for a joiner — the builders'
  order), asked once per stack per gesture; a refused stack opens no gap and its drop does
  nothing, and a member onto another stack stays refused (N118). **A gesture borrows a
  frame** — `StackItem.stand(rect)` stops `follow()` laying the column, and it must be
  lent *before* the card moves — and a drop frees it **without** laying it out, popping
  before it reports, so the command's sync lays out the new order and the old one never
  flashes; a refused command re-syncs. The card's arrows are not drawn while it is in a
  stack or joining one (`lift_links`). The frame says *Shift-drag to reorder* only while the
  pointer is over its rect (`hint_at`, from `IdleMode.mouse_move`; any other mode or the
  pointer leaving the view quiets it). This is DESIGN.md's one slide.
  `docs/architecture/canvas.md`'s *Shift-drag restacks one card, and the cards make way* has the
  reasoning.
- **Every stack edit is one command from `stacks/edits.py`, and the stack rule is the
  domain's to ask.** New, make, add, move, take out and dissolve each build one composite
  the canvas and `dplanner stack …` push alike; `bridged_removal` is what Delete, Cut,
  `step remove` and `project clear-steps` run, so a member that goes closes the chain; and
  `insert_before_command` is Insert Wait Before (`create_step(before=)`) — a stacked step's
  wait joins its stack in its slot. One relink rebuilds a line in its new order: the chain,
  the first member's outside inputs on whoever is first now, the last's dependents on
  whoever is last, a step joining disconnected first and a step leaving left with no links;
  **the seat is handed on whenever the first member changes**. Make links any pick into one
  line (`line_order`, `_link_line`): each step waits on the one before, the first on every
  input any of them had from outside, and whatever waited on any of them on the last — no
  step waits on less. A builder refuses a stack that is no longer one line, and make a pick
  with a step left out between two of its steps (`line_refusal`, `make_refusal`,
  `join_refusal` — a greyed
  state reads them from `StackVerbs`' per-project reading, built on first read and forgotten
  when the graph or the canvas's data changes, never walks a project per announce); dissolve and the removal never refuse, and dissolve lays a placed stack out as
  a row and pushes the far side by Divide's rule, never contracting. What may link to a
  stack is `stack.link_rule`, asked through `Library.link_refusal` (`graph-model.md`):
  links arrive at the first member and leave from the last. What another writer brought in
  anyway is `stray_links`, named beside the gaps by `stack list` and lint's `stack.broken`,
  never repaired. `docs/architecture/canvas.md`'s *One in, one out is a rule the domain asks* has
  the reasoning.
- **The canvas's spatial gestures exist as verbs, and geometry is derived on every read.**
  `dplanner layout show` (`--map`) measures the graph from the stored positions and
  `positions.node_size` through `canvas/geometry.py` and stores nothing — the waves,
  the bounds, every overlap and the gaps between neighbouring columns and rows in the sorts'
  pitches, read through the same **lanes** (`sorts.lanes`, `measured`) that `layout tidy`
  acts on and the map is drawn on. `layout shift` is Divide as a verb: `geometry.shift` is
  the side rule (the body's centre against the cut; a negative distance brings the near side
  back; the distance is taken as given — the verb snaps it to `GRID` as the drag does) and
  `geometry.divide_command` is the one composite both `_on_side_moved` and the verb push.
  `layout contract` is Contract as a verb over `geometry.contract`: the sign of `--by` is
  the direction, no `--by` closes the far side fully, and the report names the pair that
  stopped it — a stop with no room left is *Nothing to close*, exit 0. `layout tidy` /
  `canvas.sort_tidy` (Graph ▸ Sort) is `sorts.tidy`, a sort in kind — pure, deterministic,
  size-aware, idempotent — so it persists like one: it keeps every cluster and its order,
  reads the cards into lanes on *edges* with an inclusive half-pitch join, gives an overlap
  a sub-row, measures a hole against the reach and rounds it, and closes one past `--gap`
  (`DEFAULT_AIR`, 2) to one gap. None of the four reshapes the graph, so none declares
  `edits_graph`. `docs/architecture/canvas.md`'s *An explicit sort persists; the ambient layout
  never does* has the reasoning.
- **A run at work is a marching ring; a terminal run is a chip too.** The chip on the bottom
  edge names a terminal run's state; the dashed ring round the body moves, which is what
  says "somebody is on this one right now". The ring is one field, `NodeAccent.ring` (its
  tone), and the root fills it from either run: a terminal run's chip, or a playbook turn
  under way (`Standing.live` — not parked, not waiting, not ended), which has no chip. Never
  a second animation for a second kind of run. `docs/architecture/canvas.md`'s *A card
  running a playbook says where its pass stands* has the reasoning. **The squad holding a
  step is the chip's still mirror** on the bottom edge's right end (`NodeAccent.squad`, the `attention` tone once the claim is abandoned): a claim is
  ownership, not work, so it never marches; each chip takes at most its own half of the edge.
  `docs/architecture/agents.md`'s *A claim is a lease in git* has the reasoning.
- **The canvas has one motion clock.** One `QTimer` on the scene (`_motion_clock`,
  `advance_motion`) moves every ring and every pulse on one phase, and runs only while a
  card `moves()` — `_settle_motion_clock` after every sync, so an idle canvas ticks nothing. A new motion rides this clock, never a timer of its
  own; the one exception is a gesture's own `FrameClock` (the restack's make-way), which
  lives and dies with the gesture. A test calls `advance_motion(seconds)` rather than waiting.
  **Motion is measured in time**: the clock ticks at `GROW_TICK_MS` while a card's playbook
  strip grows and `MOTION_TICK_MS` otherwise, and the phase advances by elapsed seconds, so
  the ring and the pulse keep their pace. **A motion that is not under the hand honours
  `Look.reduce_motion`** (*Graph ▸ Reduce Motion*) and completes at once; a card new in a
  sync is dressed before it joins the scene, so opening a tab moves nothing.
- **A step a person moves next pulses.** `NodeAccent.pulse`, set by the root's
  `step_accents` for a step ready for review or ready to merge — the boards' *Ready for
  review* and *Ready to merge*, the same rule. `paint_pulse` breathes bands of the **key tone** round the body, painted before
  it, reaching `PULSE_REACH` inside `PAINT_MARGIN`, over `PULSE_PERIOD` of the clock's phase
  (3.2 s, a divisor of its wrap). DESIGN.md's *Focus and motion* says why it may move;
  `docs/architecture/canvas.md`'s *A card pulses where a person moves next* has the reasoning.
- **An arrow says more than its kind only through an `EdgeAccent`, translated by the root.**
  `requires` is solid with a head, `relates` dashed without one; beyond that the canvas
  reads `CanvasDeps.edge_accents(project_id)` once per sync, keyed (waiter, kind,
  source), and `GraphScene.sync` pushes it onto new and existing arrows alike;
  `EdgeItem.follow()` does nothing while the arrow's ends stand. **A *lane* is a colour laid
  under the arrow** — `LANE_W` wide at `LANE_ALPHA`, inside the edge's margin, so its geometry never
  changes and the ink on top keeps being lit, picked and faded: the root lays it on every
  arrow of work on a feature branch not yet landed, in a colour dealt from
  `theme/palettes.LANES` in the order the branches were cut, and takes it away once the
  landing is done — colour means *not on main yet*. Every look stays inside its margin and
  keeps the lit, picked, hovered and dimmed rules. `docs/architecture/graph-model.md`'s *A
  branch stretch is bracketed by a cut and a landing* has the reasoning.
- **A step placed by pointing at a spot earns a stored position.** `StepVerbs.born()` is
  the one place a step is born on the canvas — New and the double-click on empty space
  through `create()`, New Stack and a stack's "+" with the command a stack builder made —
  and the position rides **in the same command** as the node, because a gesture is one
  undo. Where it lands is `GraphView.last_click`, which
  every button press records *before* the mode stack sees it, and which a right-click
  refreshes so the menu's own New lands where the menu was raised. No click yet means no
  stored position, which is the ambient layout doing what it always did. The step then
  becomes the **selection**, the remembered point steps one row down (`placement.below()`),
  and `steps.details` opens on it — the first two through the `placed` seam a paste shares,
  the dialog through `created`, which only a birth calls — because they belong to the
  canvas, not to the verb — so New twice in a row leaves two nodes rather than one hiding
  another, and naming a step is the gesture's second half. A step that arrives *carrying*
  something — a dropped feature's marker — arrives named, so it is placed but not `created`.
- **A step born where nobody pointed lands somewhere free.** `layouts/placement.free_spot` reads
  every card as the canvas draws it and opens a fresh column to the right of everything,
  walking down a row at a time while anything is in the way — so the Specs tab's *Cite…* ▸
  *New feature step…* never lands on a card somebody placed, and two in a row never stack.
  It is Qt-free and deterministic; the root places through `CanvasModule.create_step`
  with it, and the step arrives **as the Feature template** (marker and estimate opt-out in
  the one command, the same set the template names). A CLI verb writes no position: it has
  no gesture behind it, so the ambient layout answers, as it does for `step add`.
- **The Edit menu's Cut, Copy, Paste, Duplicate, Delete and Select All are the graph's.**
  Registered by `canvas` as ordinary `ActionSpec`s — no dispatcher until a second
  surface needs a clipboard, because a shortcut can be owned by one enabled QAction at a
  time. Cut/Copy/Duplicate act on `step_verbs.chosen_steps` exactly as Delete does; only Paste
  needs a current canvas. The Ctrl keys are **menu shortcuts** (every text widget reclaims
  them through `ShortcutOverride`; measured, not assumed) and Delete is **not** (a bare `Del`
  would fire in every list, and `StandardKey.Delete` also claims Ctrl+D). Deleting steps no
  longer asks — undo is the safety net. A copy is a **clone**
  (`canvas/clipboard/clip.py`): fresh ids, links between copies remapped and every link
  to the outside dropped, files in the payload and written after the one composite
  command, and a `PastePolicy` per module with a say (`testing` re-mints ids,
  `step_agent_run` forgets, `feature` keeps the marker and drops the passages — they were
  read into *that* feature, and citing them again is a claim only a person can make).
  `dplanner step duplicate` is the same function (`canvas/cli.py`'s `duplicator`, handed to
  `modules/steps/cli.py` by the root).
  `docs/architecture/shell-ui.md`'s *Edit verbs belong to the surface whose things they act on* and
  *Copy and paste are a clone through the same command* have the reasoning.
