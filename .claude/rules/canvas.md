---
paths:
  - "src/dplanner/modules/project_editor/**"
  - "src/dplanner/modules/problems/**"
  - "src/dplanner/theme/{cards,tones}.py"
  - "tests/modules/test_{project_editor,canvas,graph_layout,marks,problems}*.py"
  - "tests/cli/test_{layout_cli,region_cli,step_duplicate}.py"
  - "scripts/render_graph_editor.py"
---

# Canvas — the graph editor's modes, gestures, cards and marks

- **A panel the graph tab hosts is not a dock panel.** A dock panel follows the *window* —
  one instance, retargeted by the context. A panel inside a project tab follows *that tab*:
  one per tab, handed a context naming its own project, so a background tab never follows
  the tab in front. The Problems list is the one — beside the canvas, where clicking a
  problem and landing on its step is a short trip. What goes there is a
  `SidePanel(title, icon, build)` on `ProjectEditorDeps`, named by the composition root and
  reached through `framework/panels.py`'s `ContextPanel` protocol, so `project_editor`
  imports nothing from `problems` and `problems` registers no panel (it offers
  `create_panel()`, the `step_properties` arrangement). The seam is the splitter's and the
  panel draws no edge; whether it stands is a field on `Look`, like every other preference
  the editor keeps. **A panel may also carry a *reading*** — `ReadingPanel`, one string and
  a signal — which the strip's leading band shows beside its glyph as `(4)`; that is why
  that seat is a widget (`panel_button.py`) where every other is an action, and why the
  count is read from the panel's last settled rebuild rather than probed in a state
  callback. `ARCHITECTURE.md`'s *The Problems list lives in the graph, not in the window*
  has the reasoning.
- **Canvas input is a stack of modes, and Escape pops one.** A mode handles input and has
  power over the view; a hook that returns False lets the event fall through to the canvas
  keymap and then to Qt, which is why `IdleMode` is nine lines and why a mode that claims a
  press suppresses node dragging without a flag anywhere. A mode still only *reports* — the
  activity turns its signals into commands. The current mode is published into the context, so
  a mode-switch action's `checked` stays a pure function of it. A mode that drags something
  the canvas draws — a region, a card's frame — is a `GestureMode`: it says what it holds, how
  to restore it on Escape and what the release means, and inherits the rest.
  `ARCHITECTURE.md`'s *Who owns the canvas's input* has the reasoning; add a behaviour as a
  mode, never as a field.
- **Lasso is a mode, and it touches cards.** `LassoMode` draws a `QPainterPath`, and on
  release the scene answers `nodes_touching(path)` by the node's *body* rect — never
  `scene.items(path)`, whose hit shape is the body plus `PAINT_MARGIN` and includes the
  edges. One lasso ends the mode, Shift on the release adds to the selection, and the mode
  switch is `steps.lasso` (`S` on the canvas), the same shape as `steps.connect`. Region and
  lasso share one `OutlinePreviewItem` through `Canvas.aim_outline`.
- **Divide is a mode, and it pushes a side.** `DivideMode` (Graph ▸ Divide ▸ Vertical or
  Horizontal; `D` and `Shift+D` on the canvas) lays a cut under the cursor from edge to
  edge, and the press hands over to `DivideDragMode`, a `GestureMode` that holds every card
  and shifts the ones on the side dragged towards by the snapped distance. Which side a card
  is on is its **centre** at the press, and a drag back past the cut flips the sides. The
  release is one `graph_divided` signal and one `Divide Graph` command, written only for the
  cards that moved; one divide ends the mode, and Escape puts the cards back and leaves. The
  band drawn beside the cut — the room being made — is the same `OutlinePreviewItem`.
  `ARCHITECTURE.md`'s *Who owns the canvas's input* has the reasoning.
- **Redirect is a mode, and it moves one end of a bundle.** Pick arrows, run *Step ▸
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
  greyed with the reason otherwise. `ARCHITECTURE.md`'s *Redirecting a link moves one end*
  has the reasoning.
- **Marks are a way of looking, remembered per user — and both are on.** Starts and Ends
  (`project_editor/marks.py`, Qt-free) are the `marks` of the module's one
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
  preference outlives any tab. `ARCHITECTURE.md`'s *Marks are a way of looking* has the
  reasoning.
- **A step something is wrong about wears a squiggle, and the reading is settled.** The
  editor's underline, 3 px of refusal red hanging `PROBLEM_DROP` below the body and
  starting past the spine — *look here*, where the Problems panel is the asking. It stands
  for **every** lint check there is, which is why it replaced the orphan ring: `graph.orphan`
  is one such check, so a ring and a squiggle would have been two red vocabularies for one
  fact, and a *preference* that could hide a problem is not a way of looking. The canvas
  never learns what a problem is — `NodeAccent.flagged` is the composition root's
  translation, like every other accent. **Nothing runs lint on a sync**:
  `modules/problems/findings.py` is one settled reading with two readers, the panel and the
  canvas, because the checks are super-linear in the size of a plan (1 ms at 40 steps,
  9 ms at 120, 66 ms at 300). It names the project on both its signals — `changed` for the
  panel, which lists messages, and `flagged_changed` for the canvas, which draws one mark
  per step and must not repaint because a title moved. `ARCHITECTURE.md`'s *A problem is a
  squiggle, and the reading is shared* has the reasoning.
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
  `ARCHITECTURE.md`'s *The spotlight is one derivation* has the reasoning.
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
- **The spine is the card's left edge, and it says who and where.** `paint_spine`
  (`theme/cards.py`, shared with the coverage lanes' step cards) draws a 26 px strip
  inside the left edge, clipped to the body, carrying the key rotated a quarter turn and
  washed by status — busy blue for in-progress, bad red for blocked, the good green for
  done, a quiet shade otherwise (`NodeAccent.key_text`, `spine_tone`, read from
  `theme/tones.py`'s `STEP_STATUS_TONES`; the 3 px status bar it replaces is gone). The
  title and the left-edge decorations start past it (`LEFT_INSET`).
- **A picked node is lifted, not recoloured — and every card rests on a shadow.** Selection
  thickens the border to the accent, *gains* whatever fill the node already had (so a picked
  milestone is still purple), lifts the card two pixels over a deeper shadow than the faint
  one every card sits on, and claims a Z of its own. The fill is painted **opaque** —
  `renderers.over()` blends the tint over the palette's window colour — so nothing under a
  card shows through it: not the shadow, not the ground's grid, not a region's wash. The
  rings composite, so a shadow's alpha buys twice what it looks like. `PAINT_MARGIN` is the
  one number every decoration is measured against and `boundingRect` is exactly it,
  **constant whether or not the node is selected**; `shape()` is the card and its resize
  band, never the bounding rect. `ARCHITECTURE.md`'s *A picked node is lifted, not
  recoloured* has the reasoning.
- **A card's size is the step's, stored beside its position; absence is the default
  footprint.** Drag an edge or a corner (`NodeResizeMode`; the band is `GRAB_IN` inside the
  border and `EDGE_REACH` outside it, and `IdleMode` shows the arrows over it) and one
  `Resize Step` command writes `x, y, w, h`; a move carries the size back in
  (`write_position(x, y, size)`), a paste keeps it, and every sort and layout spaces by
  `positions.node_size` and never changes one. Every painter takes the body rect it is
  handed — nothing measures from `NODE_W` — the title wraps onto as many lines as the card
  has room for, and the bottom line holds the estimate at the right in full ink and nothing
  in words: every aspect a card wears is a medallion, a badge, a bar or a pill, never a
  phrase. `ARCHITECTURE.md`'s *A card's size is the step's* has the reasoning.
- **The look is one per-user value, and snapping is the gesture's, never the write's.**
  `project_editor/look.py`: the marks, the background under the graph (plain, dots, lines,
  crosses — painted by `ground.py`) and *Snap to Grid* are one `Look`, kept under one key,
  pushed to every canvas by one setter, and read by every toggle in `canvas_verbs.py`; the
  next preference is a field there, never a third copy of that plumbing. While snapping is
  on, a drag, a resize, a region and a placed step land on `GRID` through the scene's one
  `snap()`; what reaches disk is `snapped(value)` — a whole unit, as a float — so a CLI verb
  stores what it was given, a sort what it computed, and `layout shift` — a drag by a
  distance — snaps that distance as the gesture would. The drawn pitch is
  `pitch_for(zoom)`, a power-of-two multiple of `GRID` kept a readable distance apart on
  screen, so the ground is always a coarsening of what snaps. `ARCHITECTURE.md`'s *The
  ground is a preference; snapping belongs to the gesture* has the reasoning.
- **Automatic graph layout is never persisted; an explicit sort is.** A node nobody moved is
  placed by dependency depth every time the project opens — storing that would make merely
  opening a tab dirty the project, and every CLI-created step would grow a position file
  behind the user's back. A sort *action* (`canvas.sort_*`, `dplanner layout sort`) is a
  user gesture, so it writes through the undo stack like a drag. Named layouts and regions
  are project-level entries under the same `project_editor` id — `ARCHITECTURE.md`'s *An
  explicit sort persists; the ambient layout never does* has the reasoning.
- **The canvas's spatial gestures exist as verbs, and geometry is derived on every read.**
  `dplanner layout show` (`--map`) measures the graph from the stored positions and
  `positions.node_size` through `project_editor/geometry.py` and stores nothing — the
  waves, the bounds, every overlap and the gaps between neighbouring columns and rows in
  the sorts' pitches, read through the same **lanes** (`sorts.lanes`, `measured`) that
  `layout tidy` acts on and the map is drawn on. `layout shift` is Divide as a verb:
  `geometry.shift` is the side rule (the body's centre against the cut; a negative
  distance brings the near side back; the distance snaps to `GRID` as the drag does) and
  `geometry.divide_command` is the one `Divide Graph` composite both `_on_graph_divided`
  and the verb push. `layout tidy` / `canvas.sort_tidy` (Graph ▸ Sort) is `sorts.tidy`, a
  sort in kind — pure, deterministic, size-aware, idempotent — so it persists like one:
  it keeps every cluster and its order, reads the cards into lanes on *edges* with an
  inclusive half-pitch join, gives an overlap a sub-row, measures a hole against the
  reach and rounds it, and closes one past `--gap` (`DEFAULT_AIR`, 2) to one gap. None
  of the three reshapes the graph, so none declares `edits_graph`. Regions are neither
  carried nor drawn, and the generated skill does not name their verbs (`in_skill=False`):
  they are on their way out, and the canvas keeps them only for whoever already has some.
  `ARCHITECTURE.md`'s *An explicit sort persists; the ambient layout never does* has the
  reasoning.
- **A live agent run is a chip and a marching ring.** The chip on the bottom edge names the
  state; the dashed ring round the body moves, which is what says "somebody is on this one
  right now". One `QTimer` on the scene advances every ring and runs only while a node
  wears one — `GraphScene._settle_ring_timer` after every sync. The ring is derived from the
  chip (`NodeAccent.chip_text`), so one field says both.
- **A step placed by pointing at a spot earns a stored position.** `StepVerbs.create()` is
  the one place a step is born on the canvas — New and the double-click on empty space both
  come through it — and it writes the position **in the same command** as the node,
  because a gesture is one undo. Where it lands is `GraphView.last_click`, which
  every button press records *before* the mode stack sees it, and which a right-click
  refreshes so the menu's own New lands where the menu was raised. No click yet means no
  stored position, which is the ambient layout doing what it always did. The step then
  becomes the **selection**, the remembered point steps one row down (`placement.below()`),
  and `steps.details` opens on it — the first two through the `placed` seam a paste shares,
  the dialog through `created`, which only a birth calls — because they belong to the
  canvas, not to the verb — so New twice in a row leaves two nodes rather than one hiding
  another, and naming a step is the gesture's second half. A step that arrives *carrying*
  something — a dropped feature's marker — arrives named, so it is placed but not `created`.
- **A step born where nobody pointed lands somewhere free.** `placement.free_spot` reads
  every card as the canvas draws it and opens a fresh column to the right of everything,
  walking down a row at a time while anything is in the way — so the Specs tab's *Cite…* ▸
  *New feature step…* never lands on a card somebody placed, and two in a row never stack.
  It is Qt-free and deterministic; the root places through `project_editor.create_step`
  with it, and the step arrives **as the Feature template** (marker and estimate opt-out in
  the one command, the same set the template names). A CLI verb writes no position: it has
  no gesture behind it, so the ambient layout answers, as it does for `step add`.
- **The Edit menu's Cut, Copy, Paste, Duplicate, Delete and Select All are the graph's.**
  Registered by `project_editor` as ordinary `ActionSpec`s — no dispatcher until a second
  surface needs a clipboard, because a shortcut can be owned by one enabled QAction at a
  time. Cut/Copy/Duplicate act on `verbs.chosen_steps` exactly as Delete does; only Paste
  needs a current canvas. The Ctrl keys are **menu shortcuts** (every text widget reclaims
  them through `ShortcutOverride`; measured, not assumed) and Delete is **not** (a bare `Del`
  would fire in every list, and `StandardKey.Delete` also claims Ctrl+D). Deleting steps and
  regions no longer asks — undo is the safety net. A copy is a **clone**
  (`project_editor/clipboard.py`): fresh ids, links between copies remapped and every link
  to the outside dropped, files in the payload and written after the one composite
  command, and a `PastePolicy` per module with a say (`testing` re-mints ids,
  `step_agent_run` forgets, `feature` keeps the marker and drops the passages — they were
  read into *that* feature, and citing them again is a claim only a person can make).
  `dplanner step duplicate` is the same function.
  `ARCHITECTURE.md`'s *Edit verbs belong to the surface whose things they act on* and *Copy
  and paste are a clone through the same command* have the reasoning.
