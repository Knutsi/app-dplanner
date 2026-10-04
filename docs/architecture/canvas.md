# Canvas — the graph editor's modes, gestures, cards and marks

The reasoning behind `.claude/rules/canvas.md`: the rules there are the short, imperative form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## The Problems list lives in the graph, not in the window

What is wrong with a plan is fixed on the graph: you click a problem and the canvas moves
to the step it is about. So the panel stands inside the project tab, beside the canvas,
where that trip is a short one. (It took the slot the Features panel had, which went with
the feature catalogue — *A feature is a step*.)

**What it shows is the lint registry, not a second one.** `cli/lint.py` already owns the
shapes and every module already exports `lint_checks()` from its own Qt-free `cli.py`; the
composition root's `_lint_checks()` assembles them once and hands the same tuple to
`dplanner project lint` and to `ProblemsDeps.checks`. That is `_machine_checks`'s
arrangement exactly, and it is what makes the window and the terminal unable to disagree
about what is wrong with a plan. A second registry would have been the entropy: a gap in a
plan is one fact whoever is asking.

**The count on the strip is a reading, and a reading is read, never computed.** The panel
is built with the tab whether or not the frame is shown, so it keeps answering while it is
hidden, and the button beside the canvas reads the last answer. No action state ever runs a
lint pass — the checklist's rule, and the reason its own count sits in a menu label. The
panel says the reading through a `ReadingPanel`, one string and a signal, so
`canvas` never learns what is being counted; that is also why the button is a
widget where every other seat on the strip is an action, since a `Toolbar` renders a verb
as a glyph with its words in the tooltip and a count has to be seen.

**A run that fixes a plan has no step, and is not recorded.** The panel hands its findings
to the agent module through two plain-data callbacks the root wires (the
`LibraryWatchDeps.hand_to_agent` arrangement); the launch has no worktree and opens in the
*plan's* own repository, because that agent changes the plan and not the code. `AgentRun`
is keyed by the step it is working on, so a plan-wide run gets no chip, no end-of-shell
watch and no usage row. That is a gap said out loud rather than a zero invented.

**The module never learns whose widget it is.** What goes beside the canvas is named by
the composition root as a `SidePanel` — a title, a glyph and a way to build the widget —
and reached through `framework/panels.py`'s existing `ContextPanel` protocol, which the
features list already satisfied structurally. `canvas` imports nothing from
`problems`; `problems` registers no panel and offers a `create_panel()` instead, the
arrangement `step_properties` already uses for the step panel. How it is stood is the next
section's.

## Copy and paste are a clone through the same command

A copied step is a `StepClip` (`canvas/clipboard/clip.py`): its title, its links, every
module's data and prose, and the bytes of every file beside it, plus where it sat. A paste
turns a list of clips into **one** `CompositeCommand` — the same object the window pushes
and `dplanner step duplicate` applies (`modules/steps/cli.py`, handed the canvas's
`duplicator` by the root) — so a paste is one undo step and one transaction.
Duplicate is that paste with the clipboard left alone: what the user had copied stays copied.

Four rules, each a decision:

- **A copy is a clone.** Every clone has a fresh id and an empty folder name, so the store
  mints it a directory of its own. Reusing the id was considered and rejected: in the same
  project it collides with the store's record of where the original lives, and in another it
  makes `library.has()` resolve a step that is not there.
- **Only the links inside the copy travel, and they go through `SetEdgesCommand`.** The
  pasted set keeps its internal arrangement and arrives disconnected from everything outside
  it, in the same project or another: links *between* copied steps are remapped through the
  old-to-new map, and a link to anything else is dropped. Keeping an outside link where it
  happened to resolve was tried first and read as a bug — a duplicate that silently waited on
  its original's upstream — so wiring the copy in is the user's next move, never a guess the
  paste makes. Setting `step.edges` on the clone before the add would skip `link_refusal`
  and `edges_changed`, which is why the links are commands in the same composite.
- **Files ride in the payload and are written after the command.** A cut removes the step and
  the next autosave's orphan sweep deletes its directory, so a paste after that has nowhere
  else to read an attachment from — the bytes have to travel with the clip. They are written
  once the clones exist, because a file area is settled from the node's place in the library;
  and they stay off the undo stack, the trade `FORMAT.md` makes for every attachment. The
  same pre-existing gap applies: a paste undone before the first autosave leaves an `assets/`
  directory behind, exactly as attach-then-undo-creation does today.
- **Two modules have a say, and the rest copy verbatim.** Aspect data is opaque here, so a
  module that cannot let its entry travel as it is hands in a `PastePolicy` from its Qt-free
  half and the composition root assembles the tuple (`_paste_policies`). The policies see the
  whole batch before any command exists, which is what lets `testing` mint ids across three
  pasted steps without a collision — an id is per project, and a copy that kept `T100` would
  make "T100 failed" name two things. `step_agent_run` drops its entry: a chip and a marching
  ring on a step nobody is running would be a lie. Everything else — status, estimate,
  spec figures, the milestone label, the PR ref — copies as it is, and two of those
  are judgment calls worth naming: a duplicated milestone shares its label, and a duplicated
  step keeps its PR ref, because a cut-and-paste move must keep both and a duplicate is rarer
  than a move. If that proves wrong, `github` is one more entry in the tuple. `feature` is
  the third policy: a copy drops the marker, because a record has one instance and the
  original keeps it — the same rule the drop and `feature set` refuse a second placement by.

Where the block lands is the canvas's business, through the same seam New uses: the anchor
is the last click, centred as New centres, and the block keeps its arrangement around it;
with no click yet — or for Duplicate — every clone goes one row below its original. The
arrivals then become the selection and the remembered point steps past them, so pasting
twice stacks two blocks rather than hiding one under the other.

## Who owns the canvas's input

Interaction is a **stack of modes**. A mode is an object that handles input and has power over
the view; pushing one changes what the canvas does, and popping it puts back exactly what was
there before. Escape pops. `GraphView` normalises each event and offers it to the current mode,
then to the canvas keymap, then to Qt.

The alternative was the shape this replaced: one set of Qt handlers on the scene with the
gesture's state in fields beside them — `_link_from` next to `_press_at`. That works for one
gesture. It produced its first bug at one: a handler cleared `_link_from` on its first line and
asked about it on its third. A mode has a beginning and an end, so there is no field anybody
has to remember to clear, and `exit()` is where "put the cursor and the drag mode back" lives
whatever happened while the mode was on.

Three properties make it cheap rather than another layer:

- **Declining an event costs nothing.** A hook that returns False lets the event fall through,
  and Qt still does rubber-band selection, item dragging and hand-scrolling for free. `IdleMode`
  is nine lines: it catches a press on a link handle and declines everything else.
- **A mode that claims a press suppresses node dragging for free.** The scene's remaining mouse
  handling is the record of what Qt's own item drag moved, which has to run *after* Qt updates
  the selection — so it lives on the scene, where the event arrives already handled. Connect
  and Pan consume the press, the scene never sees it, and nothing anywhere asks "which mode?".
- **A mode reports; it never writes.** It emits the canvas's signals and the activity turns
  those into commands. The chain above is untouched; the mode is one more way to reach its top.

`modes.Canvas` is a written-out protocol rather than "pass the scene around", because it is the
whole of a mode's power. A new mode cannot quietly grow a reach nobody sanctioned, and a mode
can be driven in a test by anything that satisfies it.

**The mode is published into the context**, as an edge on the activity node. That is what lets
`steps.connect`'s toolbar button check itself: its `state(context)` stays a pure function, so
the button, the menu entry and a test all read the mode the same way and nothing reaches for a
widget to ask.

**Canvas keys name action ids; they are never `ActionSpec.shortcut`s.** A bare `h` on a menu-bar
QAction fires wherever the application has focus and would eat a keystroke in the step
description editor. `keymap.py` binds keys that exist only while the canvas has focus, and what
they run is the same verb the menu runs. A key names the verbs it means *in order* and the first
one the context allows runs — which is how one Delete key means "remove everything picked" when a
step is among it and "remove these links" when only arrows are, with no branch on the canvas at
all (*A right-click is composed by what is under it* has why steps go first).

That leaves two families of verb, and the distinction is worth stating: **step verbs change the
plan** (they push commands and are undoable), while **canvas verbs steer a surface** — move the
selection, enter a mode, frame the graph. Canvas verbs push nothing, and they reach the current
canvas through a typed callback on their own `Deps`. Where a node *is* is still a fact about the
model — `layout.positions()` answers it — so "the nearest node to the right" is a pure function
and only the last step, telling the canvas what to select, needs a window.

**A gesture that drags something the canvas draws is a `GestureMode`.** The card resize and
the drag of one side of a cut (a divide's, a contract's) each hold what they move (so a sync
from the model leaves that geometry alone until the release), put it back on Escape, and
report on the release before popping — one skeleton. The base owns the hold, the cursor, the Escape and the pop; a
subclass says what it holds, how to restore it, and what the release means. It was written
at the third copy of the skeleton, when a region's drag and resize were two of them; the
regions went (*Regions were retired*) and the base stayed, because the divide had become a
copy of its own by then.

The lasso is the mode that shows the stack paying for itself. A rubber band is a box and a
cluster on a busy canvas rarely is, so `LassoMode` claims the press, grows a path under the
cursor, and on release asks the scene which cards the outline *touches* — the node's body
rect, not Qt's hit shape, which is the body inflated by the paint margin and would also hand
back the edges. It then calls `select_steps` and pops, so one lasso ends the mode the way one
link ends connect; Shift on the release folds the catch into what was already selected.
Nothing in it is new machinery: the outline it draws is the same `OutlinePreviewItem` the
divide draws its band with, reached through one `aim_outline` on the `Canvas` protocol.

The divide is the stack used twice over. `DivideMode` is switchable like the lasso — Graph ▸
Divide ▸ Vertical or Horizontal, `D` or `Shift+D` on the canvas — and does nothing but lay a
cut under the cursor from edge to edge; the press hands over to `DivideDragMode`, a
`GestureMode` in the card resize's mould, which *takes the divide mode's place* on the stack
and so ends it when it pops: one divide ends the mode the way one lasso does, and Escape
mid-drag puts the cards back and leaves, as it does for a resize. Every card is held for the
drag, because either side may be the one that moves: which side a card is on is decided once,
by its centre at the press, and the sign of the drag says which side goes — so dragging back
past the cut returns the far side and pushes the near one with no state to clear. The release
is one `graph_divided` signal carrying only the cards that moved, and the activity makes it
one `Divide Graph` command, so a whole side comes back with one Ctrl+Z. Nothing is stored
about the cut itself — a divide is a move of many cards, and what makes it a tool rather than
a drag of a selection is that it names the side by geometry, not by what was picked — and the
band it draws while it lasts, the room being made, is the outline item the lasso already had.

## Contract closes a gap and stops one short

Divide opens room; somebody who opened too much, or whose plan lost the steps that stood in
a hole, wants the other half. **Contract pulls the side *behind* the drag after it**, where
Divide pushes the side ahead of it, and so closes the gap at the cut. It is the divide's
shape again: `ContractMode` lays the cut and a press hands over to `ContractDragMode`, and
the two drags are one `_CutDragMode` apart from their rule. That base is also what retired
the divide's own copy of its side rule. Each drag's `follow` is the Qt-free function the
`layout` verb runs — `geometry.shift` for Divide, `geometry.contract` for Contract — handed
the seats at the press, the cut and the snapped distance. The window and the terminal
therefore cannot disagree about which cards move or how far, and `shift` takes its distance
as given (the verb snaps `--by`, the scene snaps the drag) so the drag with Snap to Grid off
is not snapped behind its back.

**It stops the sorts' gap short of the first card it would meet** — `H_GAP` across an
upright cut, `V_GAP` across a level one. Three rules decide that stop:

- **Stopping at nothing** would let a pull run cards into each other, and making room again
  would be the next person's job.
- **Stopping at contact** would leave two cards touching. The measurement calls that a gap
  of none, and `layout tidy` would then pull the pair apart again.
- **Stopping at the gap** leaves neighbours where every sort and tidy puts them, so a
  closed hole reads as the spacing the rest of the graph already has, and a tidy after it
  changes nothing there.

**What can stop it is a card whose extent across the travel overlaps a mover's**, not a card
in the same sort lane. The promise is *never an overlap*, and a tall card spans two row
lanes: a lane test would let a card in the second lane slide into the part of the tall card
hanging down into it. By the same logic a card in another band is not in the way at all,
and a pair already overlapping before the pull is ignored. Counting it would clamp the
travel to nothing, and the pull did not cause that overlap.

**The room is rounded towards the cut onto the grid.** `V_GAP` is 44 and the default width
220, neither a multiple of `GRID`, so an exact stop would leave a side that sat on the grid
4 units off it. Rounding the travel down keeps the side on the grid, at the cost of a gap up
to one grid step wider than the sorts' own; rounding up would break the no-overlap promise.
The side moves as one rigid block, which is what makes the rule a single minimum over the
pairs that could meet rather than a per-card packing — and why its answer names **one pair**.
The status line says it while the drag is held, and `layout contract` reports it, because a
drag that will not go further should say what it met.

## Redirecting a link moves one end, and which end is the tool's, not a guess

Connect makes one arrow between two steps. The other half of linking is taking a *bundle* of
arrows already drawn and moving one of their ends somewhere else — "these six things wait on
the new step now" — which without a tool is six unlinks and six links, six chances to lose one.

`RedirectMode` is that tool, and it is the divide's shape exactly: it is switchable, it takes
what it needs at entry (the picked arrows — every press is consumed, so the selection cannot
move underneath), the step under the cursor wears the same valid/invalid ring a link drag
paints, and one redirect ends the mode. The mode reports where; the activity makes the command.

**Which end travels is a property of the verb, and there are two verbs.** It is tempting to
infer it — move whichever end the picked arrows have in common — and the case the tool exists
for is exactly the one where that fails: two steps' incoming dependencies agree on *neither*
end. A rule with a special case is a rule nobody can predict, so the two ends are two entries
in one *Redirect* child menu: **To Step** moves the arrowhead (`WAITER`; the links come to
point at the step you click) and **From Step** moves the tail (`SOURCE`). The arrow on the
canvas already runs from the step waited on to the step that waits, so *to* and *from* are the
picture, not jargon.

**Both are gated on the same fact: are any arrows picked?** A greyed entry rather than a
hidden one, because the precondition *is* the thing to learn — that arrows are things you can
select at all.

The model does the rest. `Library.redirection(edges, anchor, end)` answers one question about
each arrow — may this end sit there? — through `link_refusal` and nothing else, and returns
what will move beside what was refused and why. That one answer is read four times: the ring
under the cursor, the click, the status line, and `dplanner step redirect`. Asking it against
the graph as it *stands* rather than as it will be is sound and not merely convenient: every
edge a redirect creates touches the anchor at the moving end, so none of them can open a new
path *into* the anchor and the removals can only break paths — the check can decline a
redirect that would in fact have been legal (when the moved edges were themselves the cycle),
never allow one that is not.

**A redirect can therefore half-happen, and says so.** Four arrows move and one would close a
cycle: the four move and the status line names the refusal. Refusing the whole gesture for one
bad arrow would make the tool useless on exactly the tangled graphs it is for.

`redirect_edges_command` writes one `SetEdgesCommand` per affected `(waiter, kind)` list
carrying that list's *final* content — never one command to remove and another to add, which
would each be built from the state before either ran (the trap `remove_edges_command`
documents). For a source-end move both halves land on the same list, which is why the content
is computed per list rather than per edge.

The terminal cannot pick arrows, so `dplanner step redirect` names them by the steps they hang
off: `--to` takes every link pointing at the named steps, `--from` every link leaving them
(`Library.edges_of`). Different way of saying *which*; same `Redirection`, same command.

## An explicit sort persists; the ambient layout never does

Two things place a node, and they persist differently on purpose. The **ambient layout** —
where a never-moved node sits — is recomputed from the graph every time the project opens
(`layout.auto_positions`, which is `sorts.layered_flow`). Storing it would mean opening a tab
dirties the project, autosave flushes it 1.5 seconds later, and every step an agent creates
through the CLI grows a position file the next time a window happens to open. A **sort
action** (`canvas.sort_*`, or `dplanner layout sort`) is different in kind: somebody asked
for that arrangement, so it is a gesture like a drag — one `CompositeCommand` of position
writes on the undo stack, and one Ctrl+Z takes the whole arrangement back. The rule
"derived facts are computed, never stored" survives intact because what is stored is not the
derivation but the user's decision to keep its output.

The same line separates the two other things this feature stores. A **named layout** is a
snapshot a person saved — authored, not derived — kept as one entry on the *project* node
under the same `project_editor` id as the per-step positions (the `estimation` cross-level
precedent in `FORMAT.md`). Applying one builds the same position commands a sort does, which
is what makes a CLI `layout apply` undoable in an open window. **Which layout is currently
applied** is per-user presentation state and lives in `user_config` (QSettings), never the
project: two people sharing a repository can be looking at different layouts of the same
graph. The picker's modified dot is a comparison against the snapshot, recomputed — never
stored.

**The canvas's spatial gestures exist as verbs, and geometry is derived on every read.**
An agent plans through the CLI and cannot see the canvas, so the picture had to become
words: `dplanner layout show` measures the graph — the stored positions with the ambient
layout filling the gaps, the card sizes, the waves, the box round everything, every
overlapping pair and the gap between neighbouring columns and rows in pitches — and
`--map` draws it as text, one cell per column and row pitch. Nothing it prints is stored:
it is `geometry.measure` over the same `placement.positions` the canvas syncs from, so a
second copy of where things are cannot disagree with the first. Its three hands are of the
same kind as a sort. `layout shift` is the Divide gesture as a function
(`geometry.shift`): the side rule is the body's centre against the cut, a positive
distance pushes the far side and a negative one brings the near side back, the verb snaps
the distance to the grid as the drag does with Snap to Grid on, and the result is
`geometry.divide_command` — the very `Divide Graph` composite `_on_side_moved` pushes,
so the window and the terminal cannot build two commands for one gesture. `layout
contract` is the Contract gesture the same way (`geometry.contract`, the same builder
labelled `Contract Graph`; *Contract closes a gap and stops one short*): the sign of
`--by` is the direction of travel, no `--by` closes the far side fully, and a stop with no
room left reports *Nothing to close* and exits 0, so an agent that closes a hole it has
already closed is told so rather than failed. `layout tidy`
is the sixth sort (`sorts.tidy`; `canvas.sort_tidy` under Graph ▸ Sort): somebody asked
for that arrangement, so it persists through the undo stack like the five before it.

**Tidy is a sort that reads the picture, not the graph, and every rule in it is a simpler
one that failed.** It keeps every cluster and the left-to-right, top-to-bottom order of
what is there, resolves overlaps, evens the spacing to the pitches, closes any hole wider
than a threshold to one gap, snaps to the grid and starts at the origin — and it must be
idempotent, or an agent's verify step would read a graph that changes under a second
tidy. The cards are read into *lanes* across each axis, and the lanes cluster on edges,
not centres (left-aligned cards of different widths have different centres, and a centre
rule split such a column on the second run); the join is inclusive of half a pitch (the
flow sort centres a column by whole half-pitches, and a strict rule spread every flow
layout whose columns differed by an odd count into twice the rows); two cards in one
column and one row are given a sub-row of their own rather than a stack inside the cell
(a stack beside a taller card in the next column was not a fixed point); and a hole is
measured against the reach of everything before it and *rounded* to whole pitches (a
floor let eight points of snap noise collapse a kept empty row). The same lanes are what
`layout show` reports gaps by and what the map is drawn on, so the number the report
prints is the number a tidy acts on. One number to know: the column pitch, 300, is not a
multiple of the grid, 8, so a tidy of a flow layout moves alternate columns by four
points and nothing else — the fixed point of a sorted graph is the sorted graph snapped.

## Wave view derives positions; only Free view saves them

Wave view is a second way of looking at the same graph: every card in the column of its
dependency depth, under a ruler saying what each wave is and when it runs. Positions have
two owners, and the line between them is the rule of the previous section applied to a view
that is shown live. **Free view's positions are the user's**: loaded from the store, written
by a drag, a sort, a named layout or tidy. **Wave view's come from `sorts.arranged_in_waves`
on every sync and are never saved** — whether a project is in Wave view is per-user state in
`user_config` beside the applied layout (`layouts/verbs.wave_view`), so toggling it leaves the
plan byte-identical and dirties nothing. The one arrow from Wave view to the store is **Keep
This Arrangement** (`canvas.waves_keep`), a sort in kind: one undo step of position writes,
after which the canvas is in Free view. `dplanner layout sort <project> waves` is its headless
form (N41) and builds the same seats. Applying a sort or a named layout leaves Wave view first,
since what it writes is what Free view shows; the cut drags (Divide, Contract) are greyed
there, because they write the seats the canvas shows.

**Only the seats change, so no view learns a concept.** `ProjectActivity._sync` hands the
scene the derived seats in the same `NodeSpec`s, every card at the default size, and the diff
sync moves the same items — toggling rebuilds nothing, and a link an agent makes from the
terminal lands in its wave through the ordinary sync without a seat being written. What the
scene does learn is that a card's seat is not the hand's: `set_pinned` takes a card's
`ItemIsMovable` and its resize band away, `BlockDragMode` holds no pinned block, and Shift
restacks nothing — a press still picks, links and opens. A step born in Wave view is born
where nobody pointed (`layouts/placement.free_spot`), since a point on a derived seat means nothing to
the arrangement it will be stored in; it lands in its wave all the same.

**A live layout has to hold still, and that decided the algorithm.** The sorts' `_layered`
runs four barycenter sweeps, and one new edge can reorder a whole column — fine for a gesture
somebody asked for, unusable for a view that re-derives on every keystroke. So down a column
the blocks go by **earliest start** (`schedule.earliest_starts`, the critical path's bracket
per step), then by **where the highest of their sources stands in the column before**, then by
project order — one forward pass. Every key compares facts a new link changes only for the
waiter and what follows it, so by induction over the columns *no other card swaps places*:
it keeps its wave and its place among the others, and moves at most by the room a mover took
or left in its column. That is why it is the highest source and not the mean the guide's
"barycenter" suggests — a mean can swap two cards whose sources never moved relative to each
other — and why the columns start together at the top rather than centred (a centred column
shifts every card whenever its length changes). Columns are as wide as their widest card and
a stack's frame stands outside its cards, so a stack arriving in a column never pushes the
columns after it; every seat is on the grid, so the scene's snap never moves a card off the
seat Keep would write. The tests pin the invariant over sixty seeded graphs rather than a
picture: every card that changes column is the waiter or waits on it.

A stack is one block in the wave of its first member, and what follows takes its depth from
the stack as one node (N39), through the same `stack.fold` every sort uses — never a second
copy of the column (N76). Keep spaces the same columns and order by each card's own stored
size, like every sort, so it is exactly what Wave view showed while no card is resized and
never makes an overlap when one is.

**The ruler numbers waves as the Order tab does.** The column with nothing before it is
START — Order's wave 1 — and the next is WAVE 2, so a step has one wave number in the ruler,
the Order tab, `layout show` and the off-view pills. Its day ranges are each `Wave`'s span,
from the column's earliest start to its latest finish, a stack lasting as long as its members
together — the one arrangement read twice, by the ruler and by `layout show`, and worded once
(`sorts.span_words`); *k of n
done* is counted from the cards' own muted accent, so the ruler and the cards under it cannot
disagree. The ruler is chrome (`layouts/ruler.py`, DESIGN.md's *Overlays on a canvas*): a child of the
view like the minimap, following the plane across and never down; the band behind every
other column is painted with the ground in `GraphView.drawBackground`, never as items. The
glide between the two views and a drag within a column are F30's, which replaces the still
block drag at exactly the two seams in `modes.py`.

## A stack is presentation over a chain

A stack is the answer to a line of steps that keeps growing while somebody iterates —
task → task → task, spreading right across the canvas, and a link to break and remake for
every step put in the middle. The canvas draws such a line as one tall card: its members in
a column inside a frame. **What it is in storage was the decision**, and two shapes were
weighed (N3 in *DPlanner changes 2*).

**The one declined was a stack in the model**: a node of its own beside steps, holding its
members, carrying the links in and out. It reads naturally, and it would have taught every
derivation a second kind of node. `ordering`, the schedule, Ready, progression, scope,
lint, the report, the order view and every CLI verb walk steps and their `requires`; each
would have had to learn that an edge can end on a stack and what that means for a wave, a
finish date or a frontier — and a stack says nothing about the work that the chain under it
does not already say. **The one chosen is canvas data over a real chain.** Each member's
`project_editor` entry carries `"stack": "<id>"`, the order is the members' own `requires`,
and nothing below the graph editor learns stacks exist: the schedule of a stacked plan is
the schedule of the same plan unstacked, because it is the same graph. The price is that
"one in, one out" is a rule someone has to keep rather than a shape the model has (*One in,
one out is a rule the domain asks*), and a
stack broken from outside — a merge, a hand edit — is possible; it is read with its gaps
(`Stack.gaps`), drawn with them, and named rather than repaired.

**The order is derived, never stored.** A list of members would be a second copy of the
chain, and the CLI is what catches a second copy out: `dplanner step link` changes a graph
with no window running to notice. `stack.chain` reads the direct links among the members —
runs from each member nothing among them precedes, then from whatever is left — so every
member lands somewhere, and a gap is where one run meets the next.

**The seat is the first member's, and the others store none.** Moving a stack is then a
one-file diff, as moving a card is, and there is no project-level map of stacks for two
writers to merge. A member's seat is derived — the column under the first, `MEMBER_GAP`
apart and rounded up onto the grid, since the canvas snaps every card it places and a
default card's 76 plus 24 is not a multiple of 8 — so a member cannot drift out of its
column, and a seat one of them stored (an older build moved it) is ignored. The gap was 16
until S40 asked for a little more air inside a stack: the grid allows only whole steps, so
it grew by one, between the cards rather than round them — about 15 % more air inside a
stack of three, and nothing off the grid.

**Every reader of positions goes through one fold.** There are a dozen of them — the
ambient layout, five sorts, tidy, `layout show` and its map, shift, contract, the canvas's
cut drag, `free_spot`, a named layout, a paste, the report — and each could have learned the
column for itself, which is a dozen chances to split one. Instead `stack.fold` hands every
arrangement a graph in which each stack *is* a card: one block under its first member's id,
as big as its frame, and `Packing.unfold` turns the arranged blocks back into every card's
seat. The algorithms did not change a line. A block waits on what the first member waits
on, and whatever waited on any member waits on the block — so what follows a stack takes
its depth from the stack as one node, which is what Wave view needs (N39). Only the first
member's inputs count: a later member's input, which only a broken stack has, would often
fold the block into a cycle with its own dependents. A broken stack can still fold into
one, which is why every walk over a graph guards against a cycle.
The fold needed one change below it: `ordering.depths` reads the edges off the project it is
handed rather than looking steps up in the library, so a folded project is measured as
itself. And every write that moves a card goes through `position_commands`, where the first
member's seat wins and a member's seat moves its stack, because a member cannot be given a
seat of its own.

**The format moved to 3 for a key that only adds**, by `FORMAT.md`'s own rule: an older
writer rebuilds the entry from the seat and the size and would destroy `stack`. No reader
checks the stamp — the library's format 4 made the same trade — so an older build still
drops it from a card it moves; the number is the record that it does. `canvas.md`'s *A stack
is one tall card* has the rule.

## One in, one out is a rule the domain asks

A stack is canvas data over a chain (*A stack is presentation over a chain*), so "one in, one
out" is not a shape the model has — it is a rule somebody has to keep. The spec's words were
"1 in and 1 out: the first node gets the inputs, and the last one gets the outputs", and
that is how it is read: links come in at the first member and leave from the last, each end
may carry several, and the chain between is the stack's own. `canvas.md`'s *Every stack
edit is one command* and `graph-model.md`'s *What may link to what* have the rules; this is
why they are shaped so.

**Where the rule lives.** `Library.link_refusal` is the only authority on a legal edge, and
every surface already asks it — the canvas under the cursor, `steps.link`'s greyed state,
Redirect's per-link answer, `step link`, `set_edges` before it writes. A second check in the
canvas would have been a second answer, and the CLI would not have had it at all. But the
domain may not import a module, and a stack is `canvas`'s. So the library grew one
seam: `link_rules`, a tuple of `(library, waiter, kind, source) → refusal` the composition
root installs on the window's library in `default_modules` and on the CLI's through
`entry.py → run → open_library`, asked after the four refusals every graph owes. A
simulation's scratch library and a test's `Library()` carry none, because the tuple is set
per instance.

**The rule counts links; it never reads positions.** A `requires` link W ← S is refused when
W already waits on a member of its own stack (W is below the first), when a member of S's
own stack already waits on S (S is above the last), or — for a link between two members of
one stack — when W already waits on anything or S already has a dependent. Every
condition says *some other link exists*, which makes the rule **downward-closed**: a link
that is legal in a graph is legal in every part of that graph with the same membership. That
is what makes one gesture at a time safe. On a stack that is one line every new link into
its middle meets one of the conditions or the cycle check, and a multi-target `set_edges`
cannot sneak two interfering ones past it. Redirect judges each move against the graph as it
stands, in which the chain link it would move still counts, so moving a chain link by
either end is refused (a test pins it — judging against the after-state would open a gap).
Counting rather than reading the chain's order also keeps the rule cheap: it scans for
dependents only when an end is stacked. A stack somebody broke has several run heads, and
each counts as a first member — lenient exactly where lint already speaks.

**A rule judges what a person links, and nothing else.** An undo puts back what was there.
A redo replayed later repeats a link that was judged when it was made. The store adopting
another writer's list, `project import` and a paste's clones copy links that already exist.
Judged, any of these could refuse — and in the middle of a composite that is the worst
place: `UndoService` drops an entry whose undo raises, half applied, and a push that raises
leaves its first half in the model with nothing to take it back. So `SetEdgesCommand` asks
the rules on its first redo only, those paths pass `rules=False`, and the four refusals
every graph owes still judge them all. The unlink, isolate and redirect a person runs may
still open a gap; that is a removal, the rule has nothing to refuse, and lint's
`stack.broken` names the result.

**Every stack edit is a rewire, and the builder's refusal is its gate.** A stack edit moves
links *and* changes membership, and the order matters. `rewire_command` takes each list's
final content and writes every removal, then `between` — the membership, the seat, a node
born or removed — then every addition. Every graph a redo passes through is then a part of
the graph after, and every graph an undo passes through a part of the graph before; a part
of an acyclic graph is acyclic, so the cycle check cannot trip halfway through, whatever
order the lists come in. That one ordering also carries a stack edit's own logic:
additions land on the finished membership, and an undo's re-additions on the one they came
from. The rewire writes with `rules=False`. That was not the first design — the first had
it judged, leaning on downward closure — and a review found the case that sank it. Stack S
is clean, `[A, B, C]`; stack T is `[T1, Y]`, and another writer made Y wait on C as well,
which breaks T but not S, since C is S's last and may have dependents. Delete C: the rewire
removes Y's link to C, removes C, then moves Y's link onto the new last, B — and T's rule
refuses it, because Y already waits on T1. The delete would stop halfway. What a rewire
adds is a line its builder already allowed as a whole, plus links that existed before and
are only moving, so judging it again adds nothing but that failure. **The gate is the
builder**: `make_refusal`, `line_refusal` and `join_refusal` refuse what cannot come out one
line, and the tests walk every builder part by part to prove the graph after is one line
and every graph on the way is a part of the one before or after (`stack_helpers.walk`).

**Make links what it stacks** (S18, at the developer's word: "if you select multiple nodes
that are not connected, that should not stop you from stacking them"). It first refused any
pick that was not already one free line, which made stacking three loose cards three links
and a Make. Now the line runs in the order the links among the steps give, and where none
does, left to right then top to bottom as the cards stand — the order a line that spread
across the canvas was read in. Each step waits on the one before it and nothing else among
them: every link between two of them runs forward in that order, so what the chain drops
it also implies. Outside links move to the ends, the fold's own reading of a stack (*A stack
is presentation over a chain*): what any of them waited on, the first waits on, and what
waited on any of them waits on the last — so no step waits on less than it did, only on
more. The one pick that cannot be a line is one with a step left out *between* two of its
steps: the line would have to wait on it and be waited on by it at once, a cycle, so
`make_refusal` names it. It is the one walk make does, and it is why there is no other
refusal to keep.

**Why a broken stack refuses edits but never a Delete or a dissolve.** Over a stack that is
one line, the relink's result is one line by construction. Over a broken one it would
silently mend gaps or carry a stray link into a new place — links the person did not touch.
So add, move and take out refuse and name the link that mends it; `stack dissolve`, which
changes no link, always works; and a Delete of a broken stack's member removes it plainly
rather than bridging, because a Delete is never refused. Insert Wait Before is the one
insertion that never refuses: it is a splice — the wait takes over everything the step
waited on, and the step waits on it — which leaves any stack no more broken than it was, and
a lone step is just a line of one, so the root's hand-wiring became `create_step(before=)`.

**What moves with the ends.** When the first or last member changes, the stack's outside
inputs or dependents follow, in the place in each list where the old end stood, so a list
whose neighbour did not change is not rewritten. A step joining is disconnected first — both
kinds, as Isolate takes them — and a step leaving goes with no links at all, which is how
the developer asked for a drag in and a drag out to behave. A moved link arrives plain,
without an auto-progress flag, the way a redirected one does. A link that no longer resolves
stays where it is, since moving a ghost is a write the graph's own refusals turn down, and a
kind this build does not know is carried untouched. The seat is the first member's, so it is
handed on whenever the first changes — and only when one was stored.

## A stack's frame is the stack's handle

S16 made a stack canvas data and S17 made every edit of one a command; this is the canvas
learning to show one and let it be handled. `canvas.md`'s bullet of the same name has the
rules. Five choices shaped it, each because the obvious alternative failed somewhere.

**The column lives in the frame, on screen.** `StackItem.follow()` lays every member under
the first card by `member_seats`, at the sizes the cards have *now*, and fits the frame round
them. The alternative was letting each gesture place every member itself — the sync from
`positions()`, the cut drag from `Packing.unfold`, a resize by hand — and a resize is where
it broke: `NodeResizeMode` moves one card, so the cards under a growing member stayed put
until the release and overlapped it meanwhile. With the column in `follow()` every gesture
moves only what it means — a block drag moves each stack's first card — and the rest
follows, so a live picture cannot disagree with the derived one. Two orderings keep it
honest: the scene lays the frames out after the cards and before the arrows, and during the
sync a card's move does not reach its frame at all, or a frame still holding a member the
sync just took out would lay it back into the column. A stacked card grows only right and
down, because `resize_command` stores no seat for a member below the first: a left or top
drag would snap back on release.

**An arrow meets an item at a port, and the chain stays arrows.** A stack takes its links in
at its first card's side and sends them out from its last card's, the sockets any card has,
and the chain between is drawn straight down the frame's middle. The first cut brought the
links in at the frame's top and out from under its "+"; the developer turned that down —
the way in is on the left and the way out on the right, as everywhere else on the canvas —
and that also kept the handle, the marks and the drawn arrow in one place. The first design
of the chain hid its arrows and painted
connectors in their place; review sank it, because a chain link is a real link — it can
auto-progress, and the rails that say so live on `EdgeItem`; it lights when a member is
picked, so the spotlight kept a member's stack-mates in view; and it can be picked and
removed. So the edge asks each end for a port — `(point, heading)` — and a card answers its
near edge travelling across, which is every curve the canvas drew before, while the frame
answers for a link between two of its neighbouring cards, straight down. A link a broken
stack carries into its middle meets the card's own side, so the break is drawn where it
lands.

**A press on a stack drags the stack, and a drag moves the pick.** Qt's item drag moves
cards one by one; a member moved that way stood alone until the release, when
`position_commands` turned its seat into its stack's. So a member is never Qt-movable, and
a press on one — or on the frame, or on a picked card beside a stack — starts
`BlockDragMode`, which moves each block's anchor and reports through the same `nodes_moved`
Qt's drag does. The press picks what it landed on unless that is already picked, as Qt's
does, so what moves is always the pick: moving only the stack out of a mixed pick left the
other cards behind, and moving only the loose cards left the stack. The developer's note on
S17 asked for exactly this — a drag on a stacked card moves the whole stack live — and left
Shift free for reordering (F19).

**A link end on a stack means its first or last card.** The domain already refuses a link
into a stack's middle (*One in, one out is a rule the domain asks*), with words naming the
first step. On the canvas that refusal would be the answer to nearly every drop, since a
stack is mostly middle; so a drop anywhere on it — any card, its frame — *aims* at the first
card for an arrowhead and the last for a tail (`GraphScene.link_end`), for a link drag,
Connect and Redirect alike, and the ring lights the card the link will land on. The verdict
is still `link_refusal`'s; the canvas only decides which card was meant. Only the last card
shows a handle, and the line of a link being dragged starts where the arrow will, under the
"+".

**A greyed stack verb reads a reading built on first read.** Whether a stack is still one
line, and whether a pick would make one, each take a walk over the project's links — the
kind of work CLAUDE.md keeps out of an action state, which runs on every keystroke. The
pattern there is a settle after a pause (`DocsModule._frontier_of`). Here it would have
dropped a gesture: a stack's "+" runs `stacks.add_below` through its state gate, so a "+"
pressed within the settle's 300 ms of New Stack would do nothing, and the suite — whose
debounce runs inline — would never see it. So `StackVerbs` builds the answer the first time
a state asks and forgets it when a link, a step or the canvas's own data changes: one walk
per change to the graph, never one per keystroke, and the app and the tests read the same
thing. The price is a refusal worded before a rename keeping the old title until the graph
next moves.

## Shift-drag restacks one card, and the cards make way

S18 gave a plain drag on a stack to the stack as a whole; this is the other half of the
developer's note on S17 — "Shift gates reorder and disconnect from stack", and a step
dragged in from outside joins at the drop. `canvas.md`'s bullet of the same name has the
rules. Six choices shaped it.

**One mode, whatever the card and wherever it goes.** Reorder, take out and join could have
been three gestures; they are one `RestackMode`, because the hand does not know which it is
doing until it lets go — a card dragged out of its stack and back is a reorder, a loose
card carried over a stack and past it is a move. So the mode keeps one question — which
frame holds the card's centre, and at which slot — and answers it on every move, and the
release reports only *where*: into this stack at this slot, or out of its own at this seat.
Which verb that is — `move_command` for a member, `add_command` for anyone else,
`take_out_command` for a member let go outside — `StackVerbs` asks the model, the way a
redirect's plan is asked again on release rather than carried over from the gesture, and
beside the menu's stack verbs, so a refusal is worded by the same `_push`.

**Joining needs no key (S40).** F19 held the join behind Shift with the reorder, and a
loose card carried over a stack only overlapped it. Shift is there to tell apart two
meanings of one press: a member's plain drag moves its whole stack (*A stack's frame is the
stack's handle*), so restacking that member needs a key. A loose card's plain drag has only
one meaning, and hovering a stack gives it no second one, so a loose card the press leaves
alone in the pick starts `RestackMode` with no key held and joins whatever stack it hovers.
Over nothing it is the plain move it always was, and it says nothing on the status line —
"drop it on a stack" on every move of every card would be noise, and a word an earlier aim
put there is cleared rather than left to outlive it. Qt's own item drag is left only for
several loose cards picked together, which have no one slot to take. `canvas.md`'s bullet
has the rule.

**The refusal is the builders'.** `stack_refusal` is `line_refusal`, then `join_refusal`
for a card coming in — `add_command`'s own order — asked once per stack per gesture: a broken stack of its own
leaves the card where it is with the reason on the status line, and a refused stack opens no
gap and does nothing on release. A member carried onto *another* stack is refused this way
too, "take it out first", because moving between stacks in one gesture is two builders over
two states of the graph (N118).

**A slot is the nearest gap, measured on the columns as they stood.** Each candidate slot is
`member_seats` over the order the drop would make, from the stack's seat at the press, and
the card takes the one whose gap centre is nearest its own. Measuring against the cards as
they are drawn — mid-glide, or already out of the way — made a boundary where the answer
changed the geometry that decided it, and the slot flickered between two. Against the
columns as they stood, the answer depends on the pointer alone.

**The frame is lent, and a drop does not give it back.** `StackItem.follow()` is the one
place a column is laid out (*A stack's frame is the stack's handle*), so while a gesture
places the cards itself the frame must stop: `stand(rect)` fits it round the column the drop
would make and leaves the cards alone, and `free()` hands it back. The first move lent it
too late — the card moved, its frame laid it straight back into the column, and nothing
seemed to drag. On a drop the frame is freed *without* being laid out: the model has not
changed yet, so laying out now would show the old order for one frame before the command's
sync arrived with the new one. The mode pops before it reports, so that sync finds nothing
held and lays everything out from the model; a refused command triggers one itself.

**The card's arrows are lifted with it.** A stacked card's links are rewired by every drop
— the chain closes behind it or opens in front of it, and the stack's way in and out
follows whichever card is first and last — and a joining card's are dropped. Drawn while it
is in the hand, they ran to ports computed for a column it was no longer in: straight lines
down the frame's middle to nowhere. Faded, they were the same lines, fainter. So they are
not drawn until it lands (`lift_links`), and the column shows its chain as it stands
without the card.

**One clock per gesture, and gone with it.** The make-way is the frame clock's first canvas
use (*Motion is a library*): each card that moves eases on `out_cubic` over 120 ms from
wherever it is, re-aimed mid-flight, and the mode's own `FrameClock` runs only while one is
gliding. It is parented to the view and deleted on exit, and its listener is unsubscribed
first, because a parentless `QObject` connected to its own method is one of the shapes the
suite has crashed on (`suite-crash`); the test holds that no `FrameClock` is left under the
view once the gesture ends. The hint that says *Shift-drag to reorder* is drawn only while
the pointer is over that stack, decided by the frame's rect rather than what is on top, so
crossing a chain arrow never blinks it.

## Regions were retired

Regions were titled rectangles painted behind the graph — "Database setup", "Finalize
release" — kept as a list on the project's `project_editor` entry, snapshotted by every
named layout beside the steps' seats, and drawn by the canvas, the minimap and the report.
They are gone, for two reasons that are one. **A stack is the canvas's container** —
canvas data over a real `requires` chain (*A stack is presentation over a chain*) — and two
containers would be two answers to "what belongs together". And **annotation
nothing structures drifts**: the model never learned a
region existed, so every sort, tidy, divide and hand-drag left the rectangles where they
were and the steps somewhere else — `region fit` existed only to re-wrap one after the fact,
and tidy and the map had already stopped carrying them. A stack is read from the chain it
stands on, so it cannot drift from the graph that way.

**An old project opens exactly as it was, minus the rectangles.** `project_editor`'s data
format went to 2, and its one migration drops the project entry's `regions` and every
layout's region rects on read — the migration pass runs at every open, window and CLI, and
persists what it changed, so the first open by this build cleans a plan once. The stamp
moving from 1 to 2 rewrites every positioned step's entry too, once: a pass-through, the
price every format bump pays (`estimation` and `step_status` paid it before). One door
needed the same care: `positions.entry_with`, the composer every project-level write goes
through, carries the keys it does not own untouched, and an entry *adopted* since the open
— an import the CLI wrote while a window was up, a pull — has not met the migration pass.
Stamping that format 2 as it stood would have kept its `regions` forever, so the composer
brings what it carries current first — and an entry that held nothing but regions migrates
to nothing, which must still replace it rather than read as "nothing to migrate". `tests/old_canvas.py` is the old project the proof
opens: in a window, through `layout show --map` and `apply`, in a report, and as an export
imported.

**The verbs were deleted, not hidden.** When the skill stopped naming them they were kept
runnable behind `in_skill=False`, on the grounds that removing a verb an older script calls
is a decision to make on purpose. This is that decision, and the flag went with them —
it existed for nothing else. What stayed is what the other gestures share: `GestureMode`
(the card resize and the divide), `OutlinePreviewItem` and `aim_outline` (the lasso and the
divide), and the `region` glyph, which a test category may wear.

## The canvas is a plane, and why that is one decision rather than three

`GraphScene` sets its scene rect once, in its constructor: a square centred on the origin,
`CANVAS_EXTENT` out in every direction and never touched again. Three things follow from that
one line, which is the reason it is worth a section.

**Panning does not stop.** The complaint was that it did — a few hundred pixels past the last
step, most obviously downwards, because the extent was the graph's bounds plus a margin. A
plane two hundred viewports across has an edge nobody reaches.

**Nothing about the graph can move the extent.** The older code recomputed the rect from
`itemsBoundingRect` on every model change, and a move *is* a model change: dragging a node
changed the rect's origin, the scroll bars re-ranged under a fixed value, and the canvas slid
out from under the drag. The fix at the time was a floor that only grew and was left alone
mid-drag — a constant is the same rule with nothing left to get wrong. The alignment fix that
came with it (a scene *smaller* than the viewport re-centres itself whenever its rect changes)
went away with it too: this scene is never smaller than a viewport. The rule generalises past
this canvas: **a scrollable area's extent must not be a function of what the user is moving.**

**The scroll bars go.** On an extent like that a scroll bar is a nub that says nothing true
about where you are, so both are `ScrollBarAlwaysOff` — and still there, so the wheel still
scrolls (Ctrl+wheel zooms) and a pan has something to move. `PanMode` claims every press
while Space is held and scrolls the bars by the pointer's travel itself — Qt's
`ScrollHandDrag` hands a press to the item under it first, so a press on a card moved the
card, which is the one thing a hand holding Space does not mean — and with Space held the
arrows and `hjkl` page the plane a third of the viewport that way, a tenth with Shift,
claimed in the mode so the keymap's movement verbs stand down while the hand is on the
plane. What replaces the bars is `minimap.py`, anchored in the canvas's lower-left corner: the
graph small, the viewport as a frame on it, and a click to go anywhere. It is *given* node
rectangles rather than reaching for a scene, so it imports nothing from the module around it
and cannot outlive what it draws; `GraphView` pushes on `QGraphicsScene.changed` and on every
scroll, and is the one object in a position to know whether there is still a scene to ask.
And it is parented to the view rather than to the viewport, because `QGraphicsView` pans by
`QWidget::scroll`, which drags the viewport's children along with the pixels.

## Marks are a way of looking

*Mark Starts* and *Mark Ends* colour a node's unconnected sockets. Three decisions sit
behind two short functions — a third mark, *Orphans*, is covered at the end of this
section by the thing that replaced it.

**They are a preference, not a fact about the project.** Whether the graph's ends are lit
says nothing about the plan, so the value never reaches the project directory — it is the
`marks` of the one `Look` on the editor module (`look.py`: marks, the background under the
graph, Snap to Grid), written to `user_config` and pushed to every open canvas the way a
mode's `RenderHints` are fanned out. That is also why a tab opened later wears them: the
module hands its current look to every activity it builds. One value rather than one per
preference, because the plumbing — a key, a setter, a fan-out, a pair of callbacks on the
verbs — was the same for each, and the second copy of it (the ground beside the marks) was
the signal to fold them: the next preference is a field on `Look`, not a third copy.

**What a socket has connected is derived every sync.** `marks.ports()` reads the edges whose
both ends are in the project — exactly the edges the canvas draws — and the activity puts the
answer on each `NodeSpec`. Stored, it could disagree with the graph the moment `dplanner step
link` ran with no window open, which is the same argument as the ordering's.

**The toggle reads the module and re-asks, rather than the context.** A mode's `checked` is
an edge on the activity node because a mode is something the user is *in* on one canvas. A
mark outlives any tab, so publishing it per activity would be a copy that has to be kept
agreeing; the toggle's state reads the module's value and the module calls
`context.refresh()` when it changes — the pattern the theme and panel toggles already use for
state that lives outside the context graph.

**All three are on, and switching one off is what gets remembered.** They shipped off, on
the reasonable-sounding ground that a mark is a preference and a preference starts quiet.
The trouble is what they mark: a socket with nothing on it and a node with nothing at all
are the two things a graph can be *wrong* about, and both are invisible in a drawing of it —
a card with no arrow reads exactly like a card whose arrow is off screen. A preference that
has to be found before it can help is one that helps nobody, so the graph arrives saying
what it knows and the deliberate act is telling it to stop.

That makes the stored value's absence rule matter: `Marks.from_json` gives a name the
stored value does not mention the *class* default rather than False, which is `FORMAT.md`'s
absence rule and the only reason this change reaches anybody who already has a look on
disk. A stored `false` still wins — somebody who switched a mark off keeps it off.

There was a third mark, and it is gone. The orphan's ring was the refusal red at full
strength round a node nothing touched: the socket discs say *this is where the graph ends*,
which is often correct, while a ring said *nothing touches this at all*, which almost never
is. What retired it is the squiggle below — `graph.orphan` is a lint check like any other,
so the general mark covers the case the ring was invented for, and covers it better,
because the Problems panel then says *which* thing is wrong. A stored `orphans` is ignored
rather than refused, which is `from_json`'s tolerance doing its job.

## A card pulses where a person moves next

A step ready to merge, and a step ready for review that no live agent takes on, breathe: a
glow in the key block's own tone swells and fades round the card every 3.2 seconds. The
rule is `canvas.md`'s; the three decisions behind it are these.

**It is a fact, not a way of looking.** The marks above are a preference because what they
light is a reading of the graph a person may not want; this is the plan saying *you are
waited on here*, and a preference that could switch it off would be a way to stop hearing
that. So it is an accent the root translates — `_persons_turn`, over `progression.taken` —
never a field on `Look`, and it is the boards' own answer: the card pulses exactly when the
Step statuses tab and the Control Centre list it under *Ready to merge* or *Ready for
review* (*Progression is the status-aware frontier*). Why a pulse at all, where everything
else on a card is still, is DESIGN.md's *Focus and motion*: the one fact waiting on the
reader is the one found without looking for it.

**Its colour is the key block's.** Amber for a review and green for a merge are already
on the card, on its left edge; a glow in a hue of its own would be a second vocabulary for
the same status. So the painter takes `key_tone` and the accent carries only *that* it
pulses. It is painted before the body, whose opaque fill covers its inner edge, and its
reach is measured into `PAINT_MARGIN` like every other decoration's.

**It rides the ring's clock.** Two timers on one scene would be two things ticking on an
idle canvas's behalf and two phases to line up; the one clock (`advance_motion`) moves the
ring's dashes, the flowing chevrons and the pulse's breath together and stops the moment
nothing moves. The period is 20 of its phase units — a divisor of the phase's wrap, so a
breath never jumps — and slow on purpose, so the pulse reads as *waiting* beside the ring's
*working*.

## An arrow into a review wears its talk bubble

A link into a review step carries the review's glyph — the talk bubble its Type toggle
wears — in a circle at the middle of its length. The spec asked for it so a review reads as
a review from across the graph, and the arrow is the right place: a review is a relation to
the step it reviews, not only a kind of card.

**A medallion, and only here.** The same step's instructions first asked for a chevron
medallion on every auto-progress link as well; F11 had already drawn those links doubled
with chevrons along their whole length, which reads from across the graph where a medallion
at the middle would be a dot (N65). A link into a review is doubled by that same rule — every
link into a review auto-progresses — so the bubble adds what the rails cannot say: *this
arrow is a conversation*. `EdgeAccent.medallion` names a glyph and nothing more, so the
canvas still never learns what a review is.

**It is found the way the chevrons are.** The middle is half the flattened track's length,
walked by hand — `percentAtLength` costs ~40 µs a call — and the chevrons stop a clearance
short of it either side, so a flowing mark passes behind the bubble rather than through its
rim. It is part of what a press and a hover hit (`shape()` takes in its disc), and the
bounding rect grows while the accent names one, a function of the accent alone, so a sync
that moves nothing changes no geometry. A stack's own link is a card's gap long; a bubble
there would sit on both cards, so an arrow too short for it wears none.

## A problem is a squiggle, and the reading is shared

A plan can be wrong about a step — no description, no estimate, a dangling `requires`, a
feature nothing gathers — and until now the canvas could not say so. The Problems panel
lists every finding, but it is a panel: you have to be looking at it. The mark that says
*look here* without saying more is the squiggle every code editor draws under a line it
cannot make sense of, and it is the right shape for exactly the reason it is in editors:
it points, and something else explains.

**It stands for every check, which is what made it worth replacing the ring with.** The
canvas had one red mark already and it could only ever mean *orphan*; two reds a pixel
apart for "this step has a problem" and "this step has *that* problem" is the confusion
the seam rule exists to prevent. One mark, every check, and the panel for the rest.

**The canvas never learns what a problem is.** `NodeAccent.flagged` is a boolean the
composition root sets, the same translation every other accent gets — the editor does not
know what lint is, any more than it knows what a milestone is.

**Nothing runs lint on a canvas sync.** This is the load-bearing constraint, and it was
measured before anything was designed around it: the checks are super-linear in the size of
a plan — 1 ms at 40 steps, 9 ms at 120, **66 ms at 300** — and the canvas syncs once per
event-loop turn while a title is being typed. So `modules/problems/findings.py` is one
settled reading with two readers: `of()` hands back the last answer and asks for a fresh
one after a quiet spell, and a project asked about for the first time answers nothing and
arrives on the next settle. A squiggle appearing a moment after you delete a description is
the honest behaviour — the answer is a walk of the whole plan, and the plan is what moved.
Moving the derivation out of the panel is also what stops it being computed twice; the
panel reads the shared one now.

**Two signals, because the readers ask different questions.** Both name their project, so a
view of one project hears its own changes and no others — `follow_project`'s rule, kept by
hand because this is not a model signal. `changed` fires whenever the findings move, which
is what the panel lists; `flagged_changed` fires only when the set of flagged *ids* moves,
which is all the canvas draws. Without the second, renaming a step would change every
message about it and repaint the canvas one settle later, every time.

## The spotlight is one derivation, and a held key lends the look

A picked card says *this one*, and said nothing about what it is joined to — on a graph of
any size, tracing a step's dependencies meant following curves by eye across cards that all
looked equally present. Two answers, from one derivation.

**Selection lights its arrows, always.** `selection.neighbourhood(edges, picked)` names the
arrows with one end among the picked steps and the steps at their far ends; the scene
re-derives it on every selection change and every sync, and every arrow it names is drawn in
the accent the picked card's border already wears. Nothing is stored and nothing is
configurable: it is the second half of *what is selected*, the way a picked node's lift is,
and a graph relinked by a CLI run this window adopted lights correctly the moment the arrow
is drawn — the same argument as `marks.ports()` and the ordering's.

**The spotlight fades what the neighbourhood leaves out**, and that *is* a preference: it
hides part of a true picture, and the part it hides is the one you need while you are
drawing the graph. So it is a field on the one `Look` beside the marks — off by default,
where the marks are on, because a mark says what the graph could be *wrong* about and this
only chooses which of two true pictures you are shown. `Graph ▸ Spotlight Selection` is the
switch, and **holding Alt lends the same look for as long as the key is down**: the thing
you want nine times in ten is a glance, and a glance should not cost two menu trips.

**Held is not a mode, and not the preference.** It handles no input — nothing about what a
click means changes — so a mode would be a stack entry that declines every hook, and one
that Space's pan would then have to nest inside correctly for no gain. It is not the
preference either: a key that wrote the setting would leave the menu's tick flickering under
the user's thumb. So the scene keeps the two sources apart and lights on either
(`set_spotlight`, `hold_spotlight`), the view owns the held one — because only the view
learns when the keyboard goes, and **Alt+Tab is precisely Alt held and then taken away**,
which is why `focusOutEvent` ends it.

**Nothing picked lights nothing.** The neighbourhood of an empty selection is empty, and the
scene fades nobody when it is — a spotlight over an empty selection would dim the whole
canvas to say nothing at all. That one rule is what makes the preference safe to leave on.

The fade is `QGraphicsItem.setOpacity` at `DIM_OPACITY`, not a paint-level flag: one number
fades a card's fill, border, title, medallions and the shadow under it together, which is
what receding is, and `renderers.py` never learns that a spotlight exists. The coverage
trace already dimmed its cards that way to light a path through its lanes, so the constant
moved to `theme/cards.py` — the same argument that put the card primitives there. The ground
stays as it is: it is the table, not the graph.

## The palette a painter is handed is a snapshot

`QStyleOptionGraphicsItem.palette` is filled once, when the scene is constructed, and Qt never
refreshes it. Nothing about that is visible until the application changes its palette: a theme
switch repainted the canvas with the *old* theme's ink, and light-on-light lost the graph
altogether. `items.live_palette()` reads the scene's palette instead, which follows the
application's, and no canvas item may read `option.palette` again.

The same shape one layer up, with a different cause: `TabHost` copies a palette colour onto
each tab with `setTabTextColor` to dim the panes the user is not in, and a copy does not
follow the original. It re-tints on `QEvent.PaletteChange`. **A surface that stores a colour
owes that hook** — the palette is live, everything derived from it is not.

Two more colours reach past both: Qt's tab-close cross is a bundled red bitmap that no
stylesheet or palette touches, so `theme/style.py`'s proxy answers `SP_TabCloseButton` with a
painted glyph — and the style is rebuilt on each theme change because `QCommonStyle` caches
the icon it is given.

**Node positions are stored, automatic layout is not.** A step nobody has moved is placed by
`requires` depth, recomputed each time the project opens. Persisting that would mean merely
opening a tab dirtied the project, autosave flushed it 1.5 seconds later, and every step an
agent created through the CLI grew a position file the next time a window happened to open. A
test asserts the project is unchanged after a tab is opened, because that is the kind of rule
that decays silently.

## The key block names the card and says who works it

A step's key — `S7`, `F3` — is what a person says, what its branch and PR are named after,
and what the agent's `dplanner` verbs address, so it has to be found from across the
graph. And a graph that plans agents beside people has a second question every card must
answer at a glance: *who does this one?* Both are painted in the **key block**: a 56 px strip
inside the card's left edge, clipped to the rounded body, with one glyph for who works the
step over the key set level and bold, the pair centred.

It used to be a 26 px *spine*, the key rotated a quarter turn up it the way a book's spine
reads — vertical because a level label wide enough to read would take a line the title
needs. The spec asked for the primary icon "in the same place as the step id", and an icon
cannot be read sideways the way a word can, so the strip widened to hold both level: 56 px
is the widest key a plan realistically deals (`M1234`, 37 px bold at the chrome font's nine
points) with air either side. It costs the title thirty pixels of width and no height; the
minimum card (`MIN_NODE_W`, 176 from 144) and the coverage lanes' minimum (`LANE_MIN_W`, 198
from 168) grew by exactly that, so the narrowest title kept the room it had.

**Three glyphs and no more**: sparkles for an agent step, a person otherwise, and a clock
for a wait. The person is on milestones, features and checks too — a person closes those,
and a rule with exceptions is one nobody reads at a glance, which is the whole point of it.
The clock is the one glyph not drawn in the
key's ink: a wait is nobody's work, and it wears the attention amber — the chips' *careful*,
`STATUS_TONES["warn"]` at full strength, since a stroked glyph at a wash's alpha reads as a
smudge — whatever its date. The rule is written once, `_primary_glyph` in the composition
root, and read by every surface that shows a key: the canvas (`NodeAccent.key_glyph`), the
coverage lanes (`Readers.glyph`) and the report's graph (`Node.glyph_markup`); Find's rows
wear it too. **The top edge's medallions stopped carrying the spark and the clock** when the block
took them: they say what a step *is* — milestone, feature, tests, check — and a card that
said who works it twice would be teaching the eye to read two places for one fact.

The block is also where the card says where the step *stands*: its wash is the status —
busy blue for in-progress, the warn amber for ready-for-review (a person looks next), the
good green for ready-to-merge and done, the bad red for blocked, and a quiet shade of ink
otherwise, so the strip is always there and the key always has a ground. Only done also
greens and mutes the body, which is how the two greens are told apart; and a review's amber
is the block itself where a wait's is a clock stroked on a quiet block, which is how the two
ambers are. A wait has no status, so its block is quiet whatever it stored before it became
one (`_card_status`, the status every card surface reads). It
replaced the 3 px status bar that once sat in the same edge: one strip carrying the key,
who works it and the status is the same idea as the bar with something to say written on
it. The done wash sits on the done body's green — the body says the work receded, the block
says why. Everything on the left edge starts past it (`LEFT_INSET`): the medallions, the
chip, the title.

The painter is `theme/cards.py`'s `paint_key_block`, beside the other card primitives, with
the geometry as a pure `key_block_rects` a test and a card's height can ask without a
painter; the status → shade table is `theme/tones.py`'s `STEP_STATUS_TONES`, because the
canvas is not the only surface where a step is a card. The coverage lanes' milestones,
features and steps wear the same block. **The report draws it too, from a copy**:
`cli/report/drawings.py` may not read `theme/` (the CLI starts with no graphics stack, and
`cli/` sits below `theme/` in the layers), so it keeps the block's numbers beside its other
hex twins and a test holds them to `theme/cards.py`'s; the glyph itself travels as data —
`theme/glyph_source.py`, the one Qt-free reader of the vendored files, hands its drawing to
the module's `report.py`, which puts it on the `Node`. The drawing is placed as a group with
its stroke named, never a nested `<svg>`, a `<use>` or `currentColor`, because the PDF goes
through QtSvg, which honours none of the three.

## A picked node is lifted, not recoloured

Selection used to be a one-pixel-wider border in the accent, and on a graph of twenty nodes
it was genuinely hard to see which one you had. The replacement is four things that each say
"this one" in a different register, and one thing it deliberately is **not**.

The border thickens and takes the accent (2.5 px). The fill **gains**: whatever alpha the
node's own fill had, half again. The node draws two pixels **up**, over a soft shadow left at
its seat — four rounded rings, each wider and fainter, because a `QPainter` has no blur. And
the item claims a Z of its own while selected, since nodes otherwise share one and the
stacking order is whichever `sync` happened to add last, which would let a neighbour crop the
shadow.

What it is not is a colour of its own. A wash of the accent over the body was the first
attempt and it was wrong for a reason worth keeping: a selected milestone stopped being
purple, a selected feature stopped being teal, and a selected done step stopped looking done.
The kinds' body colours are identity, and identity should not be something the pointer can
take away. A gain on the node's own fill preserves every one of them, and reads on light and
dark alike — the fill is ink over the canvas, so *more* of it means more contrast in either
direction.

**Every card rests on a shadow, and the fill is opaque.** The first cut painted the fill
translucent (`FILL_ALPHA` ink over the canvas) and clipped the shadow to the ground around
the card, because rings left underneath darkened the fill itself and a selected step read as
a hole rather than as a card off the table — on a light theme the selected node came out a
flat dark grey and nothing about the code looked wrong. The grid ground made the same point
again from the other side: dots showing through every card read as a stain. So
`renderers.over()` blends the tint over the palette's window colour and paints the result
opaque — exactly the colour the tint would have had over bare canvas, on any theme, with
nothing underneath able to change it. The clip went with it, and with it the reason a
*resting* shadow could not exist: every card now sits on a faint one (`RESTING_SHADOW`) and
a selected card's is deeper and wider (`LIFTED_SHADOW`), which with the lift is what says
"this one is up". Both are deliberately slight — the rings composite, so the first alpha
that looked right in isolation landed twice as dark, and on a light theme's paper that reads
as a hole. The border and the gained fill are what say "this one"; a shadow only has to seat
the card. The fill-gain test still guards it: a body can only come out at exactly the gained
tint over the ground if the fill is opaque, or nothing at all is painted underneath it.

One number ties it together: `PAINT_MARGIN` in `renderers.py` is the furthest any decoration
reaches out of the body — handle, badge, medallion, chip, lift, shadow — and
`StepNodeItem.boundingRect` is exactly that, *constant whether or not the node is
selected*. A rect that grew on selection would invalidate the wrong region, and the shadow
would be left on the canvas when the selection moved on. `shape()` is a different question —
the card and its resize band — because the bounding rect reaches that margin out on every
side for paint, and a click beside a card is a click on the plane.

## A card's size is the step's, and a layout never says how big

A card can be dragged wider or taller by any edge or corner, and three decisions sit behind
the one gesture.

**The size is stored beside the position, and absence is the default.** `{"x", "y"}` gains
`"w"` and `"h"` only for a card somebody resized (`positions.write_position`), so a project
of untouched cards never learns the keys exist — `FORMAT.md`'s absence rule — and a card
resized back to the default drops them again. It rides in the same per-step entry because a
resize is the same kind of fact as a move: presentation, one file, one diff. It is
deliberately **not** part of a named layout: a layout says where cards sit, and applying one
must leave a card somebody enlarged as it was. Every position write therefore carries the
size back in — a move, a sort, an applied layout, a paste — which is what
`write_position(x, y, size)` and `position_commands(project, …)` are for.

**Every painter takes the body it is handed.** `renderers.py` measures from a `body` rect
and the only fixed numbers left are paddings, radii and how far the decorations reach; the
sorts already spaced by a `size_for` function, which now defaults to `positions.node_size`
— so a large card keeps its room in every arrangement without an algorithm learning about
sizes. What a taller card buys is *title*: the name is set two points larger than the chrome
and wraps onto as many lines as the card has room for above its bottom line, only the last
one eliding. The bottom line holds the estimate — the one number a step answers with — at
the right in full ink, then the PR pill and the branch glyph, and nothing in words: the
aspects' phrases that once filled it as a subtitle were saying what the medallions, the
badge, the bar and the pill already wear, and a card that repeats itself is a card that is
harder to read.

**The gesture is a mode, and the hit shape is the card.** `NodeResizeMode` is a
`GestureMode` with eight grips (the retired region resize had one): a band `GRAB_IN` inside
the border and `EDGE_REACH` outside it, both bands at once being a corner, and the link
handle winning its corner of the right edge as it does on the press. The edge under the
pointer moves, the far edge is the limit (never below `MIN_NODE_W` by `MIN_NODE_H`), and the
card is held for the gesture so a sync from the model leaves it alone. One `Resize Step`
command writes seat and size together, because dragging the left edge moves both and undo
must take both back. The pointer's resize arrows are the gesture's only announcement, shown
by `IdleMode` on mouse moves with no button down — the one mode that can start a resize is
the one that says where.

## A card on a branch names it

A branch stretch (*A branch stretch is bracketed by a cut and a landing*) has to be seen for
what it is: which work goes on which branch. Two marks say it, each where nothing else
already speaks. **The lane** is a translucent band of the branch's colour under the arrows
of its work — under, because the arrow's own ink already means lit, picked, receding and
flowing, and the rails already mean auto-progress; the colour is dealt from a qualitative
set, since two branches side by side are peers where milestones are a sequence. **The
strip** names the branch in words across the card's foot, and it is the one exception to
*nothing in words*: a branch is a name a person has to read, and a medallion could say only
*some* branch. Both stay after the work is done — done work on a branch is not on main
yet — and the lane goes and the strip goes quiet once the landing is done.

**The strip makes the card taller, and one rule says by how much.** A strip painted inside
the stored card would have squeezed the title the card is sized for, and one painted outside
it would have fallen through the hit shape, the lasso, the stack column and every sort's
spacing. So the card *is* taller: `positions.footprint(step, strip, body=node_size)` is the
one size rule, the canvas sizes its cards by it through the editor's `strips` seam, and every
arranger — the sorts, the ambient layout, a stack's column, `free_spot`, the CLI's `layout
sort` — is handed it as the `size_for` they already took. Because the pushed size is the
whole card, the shadow, the ring, the selection, the hit shape, the lasso and the stack's
frame follow without learning a thing; only three readers needed the body instead — where an
arrow, the handle and the marks meet the card (the body's middle, so a card in a row with an
unstriped one keeps its arrows level), what the painter lays the key block and the title
into, and what a resize stores. A view that draws every card at the default size hands the
rule its own `body` — the Wave view's case — so there is never a second size rule.

## The ground is a preference; snapping belongs to the gesture

*Graph ▸ Background* (plain, dots, lines, crosses) and *Graph ▸ Snap to Grid* are two fields
of the same per-user `Look` the marks live on (`look.py`), so they are kept, fanned out and
read by their toggles exactly as the marks are — the view draws the background
(`ground.py` paints it by name), the scene answers `snap()` — and a tab opened later wears
them. The background is the theme menu's shape: one choice of several, exactly one checked.

**What snaps is the gesture, never the write.** Before this the grid was invisible and every
coordinate was rounded to it on its way to disk, which would have made a snap *toggle* mean
nothing: a drag with snapping off would still have landed on the grid the moment the store
wrote it. So `positions.snapped(value)` rounds to a whole unit — short JSON, and still the
float every number on disk owes — and only the canvas passes `GRID`, only while snapping is
on, through the scene's one `snap()`: a node drag (`itemChange`), a resize, a divide's
distance, and the seat of a placed step (a double-click, New, a paste, a drop). A CLI verb has no gesture and stores what it was given; a sort's output is what the
algorithm computed, and the layered ones land on round pitches by construction.

**What is drawn is a coarsening of what snaps.** The ground shows every `pitch_for(zoom)`-th
line of the snap grid — the smallest power-of-two multiple of `GRID` that keeps the marks
`MIN_SCREEN_PITCH` device pixels apart — so a card's corner is always on a line the ground
*could* show, and zooming in reveals the finer ones rather than a grid that drifts against
the cards. Cosmetic pens keep a dot two device pixels and a line one at any zoom: the ground
is a texture, not a drawing that scales with the graph. Its ink is the palette's text at a
low alpha (DESIGN.md exception #1), read at paint time from the view's own palette so a
theme switch repaints it with the graph.

## A step placed by pointing at a spot earns a stored position

The ambient layout is never persisted (*An explicit sort persists; the ambient layout never
does*), and placing a node by pointing at the canvas is the same kind of act as dragging
one: somebody chose where it goes. So it is stored, and the choice arrives on the same
command as the node itself — a gesture is one undo, so New ▸ Feature at a point is one
`CompositeCommand` of add, mark and place rather than three entries on the stack.

That pushed the creation into one function. `StepVerbs.create()` is now the way a step is
born on the canvas, and the double-click on empty space — which already placed a node at a
point — calls it too. The consolidation deleted a second implementation rather than adding a
first. Stacks brought births whose command another module builds — New Stack's first step,
a stack's "+" — so the tail every birth shares, push then `placed` then `created`, is
`StepVerbs.born()`, and `create()` ends in it like the stack verbs do.

Where "the point" comes from is `GraphView.last_click`, recorded on **every** button press
*before* the mode stack is offered the event: "where I last clicked" is true whether or not
a mode claimed the press, and a mode-aware version would have to be right in five places
instead of one. A right-click records too, so the menu's own New lands where the menu was
raised — and the context handler records again for the keyboard menu key, which sends no
press at all and would otherwise reuse a stale point. A canvas nobody has clicked answers
`None`, and New falls back to the ambient layout, which is what it always did.

Three smaller things ride on the same seams, and all belong to the canvas rather than to
the verb, which is why `StepVerbs` takes callbacks rather than doing them itself. Through
`placed` — which a paste shares, handing over every step it added at once — the new step
becomes the **selection**, and the remembered point **steps one row down** —
`placement.below()`, the automatic layout's own row pitch — so pressing New twice leaves two
nodes where a stale point would have hidden one exactly under the other. Through `created`
— which only a birth calls, never a paste, because pasted steps arrive named — the details
dialog **opens on it**, the same `steps.details` a double-click on a node runs, so naming
the step and saying what it is are the gesture's second half. A double-click on empty space
gets all three too: it pointed at a spot in the same sense.


A **drop** is the third caller. Something dragged from a panel onto the canvas — a feature
from the Features panel — is a one-shot gesture exactly like the double-click on empty
space: Qt's drag events never reach the mouse handlers the mode stack reads, and a mode has
state to enter and leave where a drop has neither. So `GraphView` records the point and
hands the mime data up, `ProjectActivity` finds the `CanvasDrop` for its type, and the
handler — written in the composition root, because it reads one module's catalogue and
births through another module's `create` — places the step with its marker and its position
in the one undo step every placed step gets. What the canvas accepts is a tuple of
`CanvasDrop`s on its `Deps`, named by the root like the kinds; a refusal is a `CliError`
whose message is the status bar's, the same words the CLI would print.
