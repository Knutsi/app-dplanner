# Shell — seams, panes, primitives, menus, toolbars, glyphs and themes

The reasoning behind `.claude/rules/shell-ui.md`: the rules there are the short, imperative
form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## The index tree

The template's sidebar was a tab set: one page per module, one visible at a time. DPlanner
replaced it with a single tree whose folders come from an `IndexSegmentRegistry`, and
deleted the tab set rather than keeping both.

The argument for the tree is that it shows the library's *shape* — projects, and the steps
under them — where a tab set shows one feature and hides the rest. The argument for deleting
the old one is that anything a page could hold is a folder here, so keeping both would have
been two navigation mechanisms competing for the same 275 pixels.

The tree is not a slot in the window; it is one **panel** anchored in the left area
(below), which is why it can be moved and hidden like anything else contributed to the window.
Three things still live in the panel rather than in each segment, because a shared tree is not
the same problem as a stack of independent widgets: **selection is published exactly once** (Qt
selection is per-tree and `ContextService` has one selection scope, so segments would
otherwise fight over it); **a segment supplies its own menu** rather than the spec naming a
`MENU_STRUCTURE` menu, because a menu name is application vocabulary and has no business in
a framework spec; and **expansion state survives a rebuild** through shared helpers, because
rebuilding on change is the normal case and that bookkeeping is what every segment would
otherwise copy — and survives a *restart* too, which is *Where the user left off is
remembered by key* below.

**A folder's own row is one of its segment's rows.** A folder is not furniture: Home is a row
at the top of the index with nothing under it, and a right-click on *Projects* is where a
person reaches to add one. Home as a row *inside* some other folder would sit under a heading
it does not belong to, so the panel hands a click, an activation and a right-click on a folder
row to its segment like any other row's, and a segment with nothing to say about its folder
ignores it — a folder row carries none of the roles their rows are read by. Only selection
still skips it: a folder row is not selectable, so it never stands for anything in the
context. The Projects folder's right-click renders the File menu's `project` group through
`build_menu`, so the index and the menu bar cannot disagree about how a project joins.

### A click is a glance: preview tabs

A single click on an entry row opens its surface as a **preview tab** — VS Code's
arrangement, adopted whole rather than reinvented. The host (`framework/tabs.py`) keeps at
most one preview; the next preview replaces it, and a deliberate act keeps it: activating
the row again (a non-preview open of the same URI), or moving the tab. A preview-open of
something already open is a plain focus that changes nothing — the tab you kept stays kept,
the preview stays where it was.

Two consequences fell out of making every step idempotent. **The double-click needs no
timer**: click one previews, click two's activation pins, and the trailing click event Qt
fires after an activation lands on "already open → focus" and disturbs nothing. And **"jump
to the thing that is open" needed no code at all** — the host already deduplicates by URI,
so a click on an entry whose tab exists anywhere simply focuses it, in whichever pane it
lives. The preview's mark is an italic title, painted by the tab bar itself so the host's
active-pane dimming keeps working underneath it.

The gesture reaches the segment through a fifth `IndexSegmentView` hook, `clicked`, and the
panel forwards only plain left-clicks — a Ctrl/Shift-click is building a selection, and a
right-click is asking for a menu. On the entry it is `open_preview`, a second callback
beside `open`, both closed over the owning module's `open(..., preview=…)` by the
composition root; `None` is an entry whose surface has no preview form.

### A project tab says its project's short title

Ten tabs are one side of a project — *Order*, *Estimates*, *Specs* — and each once led with
the project's whole title, so three of them open on *DPlanner changes 2* filled the strip
with one name. They now lead with a **short title** (`domain/short_titles.py`): the
initials of a title of several words, numbers whole (*DC2*), a one-word title whole. The
canvas tab is the project itself and keeps the whole title, so the long form is always on
screen somewhere.

**It is unique among the library's projects, so it is derived and never stored.** Two titles
with the same initials grow letters of their first word until they part (*DerM*, *DelM*),
and a pair that cannot part keeps its whole titles. That makes a title a fact about the
siblings too: renaming one project can relabel another's tabs. So `follow_project_tabs`
(`framework/activity.py`) re-reads every project tab's title when *any* project's field
changes or the library's membership does — where `follow_entity_tabs` before it retitled
only the renamed project's own tab — and ignores a step's field change, so typing a step's
title costs no tab anything. `project_tab_title` is the one place the label is composed,
where ten activities each had their own copy of the line.

## Where the user left off is remembered by key

Two things follow a person across a restart: which folders in the index tree were open, and
which tabs the window had. Neither is a property of the plan — a colleague pulling the
repository must not inherit somebody's open tabs — so neither goes near the project
directory. They live in the per-user store, and `framework/user_config.py` now has two
scopes because two different kinds of thing are being kept.

**A preference is the person's; where they left off is the library's.** "Reopen my tabs" and
"which model" follow the user into every library they open: that is `get_global`. "These
tabs were open, these folders were unfolded" is true of exactly one library, and restoring
library A's tabs into library B would be nonsense: that is `get_scoped`, under a scope
`library_scope(path)` derives from the library file's resolved path. The scope is a digest
rather than the path itself only because a QSettings key is a `/`-separated tree, and a path
put in one whole fans out into a directory's worth of empty groups.

### Restoring by key is what makes a changed library safe

Both halves write down **node ids**, never positions, and restore by looking each one up.
That single choice is what answers "what if the library changed underneath?" — a remembered
project id that names no row is simply not there any more, so the tree comes back with fewer
folders open, and a tab whose project was deleted is not reopened. There is no validation
pass, no version stamp and no migration, because the check *is* the lookup. The obvious
first design — saving the tree's shape, or tab indexes — is the one that comes back wrong
rather than short.

Reopening a tab has two more ways to be stale, and each is a question asked of somebody who
knows the answer. The activity *kind* may be gone from this build, which the tab host
answers (`can_open`); the *target* may be gone from the model, which the composition root
answers by handing the module `Library.has` — so `modules/reopen_tabs/` never learns what a
project is. A third guard catches whatever is left: a factory that raises costs the user one
tab and never the launch, which is the one place in this codebase where a deliberately broad
`except` is the honest answer.

### Written on every change, not at close

Both halves write as the user works rather than on the way out, and the reason is the reload
path rather than crash-safety (though it covers that too). Reloading a library builds the
new window *before* closing the old one — see *Two writers, one folder* — so a list written
in a close hook would be written **after** the window that was going to read it, and every
reload would bring back the tabs from one session ago.

That is also why `TabHost` grew `tabs_changed` beside `activity_changed`. The older signal
is about which tab is *current*, and `_announce` deliberately says nothing when that has not
changed — so closing a tab in a pane the user is not on, which is the ordinary way a project
being deleted takes its tab with it, changed the list and announced nothing. Not a bug in
`_announce`: a second fact the host had no way to say.

### What is deliberately not restored

Pane splits and the preview tab. A split is an arrangement of the *window* around the work,
not part of it, and everything comes back pinned in one pane — reopening a glance as a
glance would mean the next glance silently replaced a tab the user thought they had. The
tree's folders are restored, the tree's *selection* is not: a selection is what the user is
doing right now, and the panels that follow it would be answering for a click nobody made.

### One is the framework's, one is a module's

The index panel keeps its own folders (`framework/index_panel.py`), the way `panels.py`
keeps its own areas: it is the framework's own surface, its rows arrive one segment at a
time as modules register, and each folder restores as it arrives rather than after some
later pass. Tabs are `modules/reopen_tabs/`, because reopening one needs a preference and a
question only the model can answer, and because it must run after every activity factory has
registered — a position in `default_modules()` with a comment saying so.

Only the tabs have a switch (*Settings ▸ Startup*). Folders are cheap to close and nobody
has ever wanted them shut on purpose; a window that reopens six tabs is a real opinion about
how someone starts their day. The list is kept even while the switch is off, so turning it
back on returns the session they last had rather than one from whenever they turned it off.

## Home is where a window starts

A program that starts with no tabs to reopen must not show an empty tab bar over nothing. It
starts on Home: a short getting-started guide, centred, over a
garden that says what DPlanner does, in the `home` tab — kept as the top row of the index
and *Go ▸ Home* for whenever it is wanted. The rules are `.claude/rules/shell-ui.md`'s
*Home is a tab like any other*.

**A tab like any other, opened at the program's start and at no other time.** Home is not a
backdrop behind the tabs; the developer's call was the simpler one: Home is an ordinary
activity, and a blank window is allowed — closing
the last tab leaves nothing, rather than a page the person just closed coming back. So the
one automatic open is the program's start: `app.open_at_startup` calls the composition
root's `start_window` after the build, and it opens Home only when reopen_tabs brought back
no tab. It lives there rather than in a module because only the entry point knows a start
from a rebuild — a reload builds through the same modules and must bring back the window the
person had, blank included — and because the test session is built the same way minus the
entry point, so the suite's windows start as empty as they always did. A surface that
spans the whole library — the Control Centre is the first — is a folder of its own right
after Home, not a row under it: both are a `SurfaceSegment`, a folder that is one row and a
way in. It hung under Home first, through a `HomeDeps.rows` seam; the developer asked for it
as its own row after Home, and the seam went with it, since nothing else hung there — Home
is one folder row again, and no module has a reason to know it.

**The guide is data, and its buttons are the verbs.** `modules/home/guide.py` is a tuple of
steps, each a title, a sentence from the README and an **action id**. The page restates each
button from that spec's `ActionState` on every context change and runs it through the
registry, exactly as a menu entry does — so *Open Agent in Code* greys with its own *no
project is open* until a project is picked in the index, and a verb refiled tomorrow is still
the verb the guide means. A guide that described verbs in its own words would drift from
them; one that called them directly would skip their gates. A test holds every id to the
registry.

**The garden is the one ornament that moves, and it earns it by saying what DPlanner is.**
A first version listed the tabs a person kept lately; the developer's call was that a
newcomer's first page should say what the application is for instead, and without a word.
So the garden is a plan: seeds are steps, the roots between them are links, and a seed
sprouts only once everything it waits on has bloomed — which is the whole of what *ready*
means. Agents, wearing the sparkle every agent step wears on its card, fly to what is ready
and sprinkle it; it grows, opens petal by petal and blooms, and a pulse runs down its roots
to what it unblocks. Two agents work side by side when two things are ready, the milestone
blooms last and keeps its halo, and when everything is in bloom the garden rests, lets its
petals go and is sown again. Everywhere else a still surface is the rule (DESIGN.md's
*Focus and motion*) because every change on it is a change of fact; this strip is the stated
exception, and it keeps the exception cheap: a frame costs about four milliseconds at a
thousand pixels, it ticks only while shown, and after two seasons it rests, still, in full
bloom until the pointer passes over it or Home is shown again — a page left open is not a
reason to spend a core. Somebody who would rather not have it turns it off in *Settings ▸
Home* — a global preference, since it is about the person and not the library. It has no
close button of its own: a ✕ in the corner was one more control on a page that is otherwise
only the guide, and the developer's call was to leave the garden clean. `garden.py` is what
happens and `garden_widget.py` how it looks; the first version,
a cloud over nine identical stems, taught that the look is most of the message.

## Motion is a library

The canvas already moved in two places, each on a hand-rolled `QTimer` — the agent ring
and the pulse step every 80 ms, twelve frames a second, and the spinner has its own — and
Home's garden would have been a third. `framework/motion/` is what they
share instead, shaped for the canvas though Home is its first user:

- **One clock per surface, at the display's rate, only while seen.** `FrameClock` runs on
  Qt's own animation driver — the one `QPropertyAnimation` uses, about sixty ticks a second,
  paused by Qt when nothing animates — and hands its listeners the *seconds* since the last
  tick, so motion is measured in time and never in ticks; a long gap is one short step.
  `follow(widget)` starts it on a show and stops it on a hide, so a background tab costs
  nothing, and `step(dt)` is how a test or a render sets the time rather than waiting for it
  — the same promise the debounce service's immediate mode makes.
- **What moves is plain state.** `curves` (easings, a tween, a spring, a coherent breeze, a
  Bézier) and `particles` import no Qt, so a model like the garden's is tested as arithmetic
  and a render is deterministic. A spring is the right tool for anything *moved* — it glides
  and settles from wherever it is, however often its target changes; a tween for anything
  *shown*, which has a start and an end.
- **Drawing is batched, because Python pays per call.** A glow is one radial gradient, never
  a blur; a tapering stroke one filled outline; a particle system one path per tone and step
  of fade, filled once. Measured on the garden, those three moved a frame from nineteen
  milliseconds to six, and caching the layers that change slowly — grass, stars, roots,
  redrawn twenty times a second — to four.

**What the canvas would use it for** is written down here so the next step starts from it,
and none of it is built: motion that *explains a change of fact* rather than decorates one,
never longer than a quarter second and never holding input back — the model changes at once
and only the view catches up. Sort, Layout, Divide and a paste would glide each card on a
spring from where it was to where it went, so a person sees where a step moved rather than
hunting for it; Find, *Show in ▸ Graph* and Frame would pan and zoom along an eased path
instead of cutting; a new step would grow from the point clicked and a deleted one leave a
brief fading ghost; a new link would draw itself from source to waiter; and a step that
turns done while it is watched would bloom — a soft green glow and a few sparks from its
key block, the garden's own gesture, so *an agent makes the plan bloom* means the same
thing on both surfaces. The ring and the chevrons would move to the frame clock, smoother
and silent in a background tab. It needs two things first: DESIGN.md's *Focus and motion*
amended from "only these move" to "motion explains a change", and one *Reduce motion*
preference that completes every tween at once — which the suite would run under, as it runs
the debounce service immediate.

**The first of it is built, and it needed neither.** A stack making way for a card dragged
through it (F19, *Shift-drag restacks one card* below) is the first canvas motion on the
frame clock, and the one slide DESIGN.md now allows by name rather than by a general
"motion explains a change". It needed no *Reduce motion* either, because it is a different
kind of motion from everything listed above: it happens only under a hand, the model has
not changed yet, and the release settles every glide before anything is written — so there
is nothing for a preference to complete, and a test calls the gesture's `settle()` the way
a render does. The list above still waits on both.

**The second is a card's foot growing to its playbook strip** (S27, `canvas.md`'s *A card
running a playbook says where its pass stands*), and it is the first motion that is not under
the hand, so it brought the two pieces the list waited on in their smallest form: DESIGN.md
names it as one more allowed motion, and *Reduce Motion* exists — as a field of the canvas's
`Look`, since the canvas is the only surface it governs yet; a second surface that needs it is
the moment to lift it to an application preference. It rides the canvas's own clock, which
now measures motion in seconds and ticks at the display's rate only while something grows.

**A well can be as tall as its rows.** The guide is a `RowWell`, which is a scroll area, and
`QScrollArea` stops its size hint at twenty-four lines of text whatever its adjust policy —
so five steps sat behind a scroll bar with half the page empty around them. The primitive
now honours `AdjustToContents` as Qt documents it: its hint is its rows', its
`heightForWidth` their height at that width (their notes wrap), and its minimum stays the
scroll area's, so a short window still scrolls it rather than growing.

## A submenu is one child menu per title, and groups separate inside it

A spec names a `menu`, a `group` and optionally a `submenu`, and for a long time the child
menu was keyed by *(group, title)*. The Step menu paid for it in the open: `test` (Add,
Archive, Put Back) and `test_result` (Mark Ok, Failed, Skipped, Clear) both named the submenu
`Test`, so the menu rendered **two child menus with the same name**, one under the other,
with a rule between them. `CLAUDE.md` described the behaviour the keying prevented.

The fix is to say what was meant: a submenu is one child menu per title within a menu, and a
**child menu is a container of the same kind the menu is** — it holds the menu's groups, and
a rule is drawn where its entries change group, under the same never-leading, never-dangling
rule the menu bar has always applied to itself. Both presenters do it (`framework/menubar.py`
pre-creates a hidden separator per group boundary in every container; `action_menu.fill_menu`
draws one as it goes), and `tests/framework/test_menubar.py` asserts they render the same
shape, because a menu bar that disagreed with a right-click is the one thing four presenters
of one registry exist to prevent.

Two things fall out of it that the Step menu needed. A group that only feeds an existing
child menu adds **no rule to the menu itself** — only the child's menuAction carries a group
there — so "what a test did" can be its own group without costing the menu a line. And
several submenus can sit in one group as a band: the Step menu's `classify` holds Type,
Status and Test with no rules between them, because a rule between two adjacent child menus
separates nothing that their names do not already separate. That is what took the canvas's
right-click menu from eight rules to five. The cost is small and worth naming: a child menu
sits at its first entry's `order`, so sibling child menus in one group have to claim bands of
it (Status the 200s, Estimate the 400s in `track` — written down in `dplanner/menus.py`).
`order` still only ranks inside one group; it is now also how two child menus in that group
know which comes first. (Type and Test have since left the menus for Step Details — *The menu
bar is sorted by subject* — and Step ▸ Show in is the child two groups feed today.)

## An action may carry a glyph, and only the pop-ups paint it

`ActionSpec.icon` is a painter — `(QColor) -> QIcon` — not a QIcon, and the presenters that
render it are the ones built fresh on every open: `build_menu`, `append_action`, a toolbar
button's dropdown. The menu bar deliberately does not, and the reason is the same trap as
*The palette a painter is handed is a snapshot*: its QActions are created once and live for
the application, so a colour baked into one at startup would still be there three themes
later. A pop-up has no such problem — it is thrown away when it closes.

It earns its place on the Type verbs, where each toggle wears the very glyph its node
will wear, and it is what lets the aspect bar paint the same glyphs (through the specs, so
they are the registry's and not a copy) instead of the panel hand-building a list of
aspects it is not allowed to know.

## The menu bar is sorted by subject

The bar grew by accretion, a verb at a time into whichever menu its feature first touched.
By F8 the Project menu held eleven spec-document verbs beside the project's own, Step held
nine ways to show a step somewhere else, and the project's views — every tab a project has —
were in no menu at all, since F7 took them out of Project rather than repeat the index rows
beside it. The pass that sorted it kept **ids fixed** — keys, toolbars, the palette and the
keymap name ids, so every move was a `menu`, `group` and `label` edit and nothing a person
had learned stopped working — and settled on four principles, which `shell-ui.md` states:

- **A top-level menu names a subject.** File is the library and what it writes; Edit history
  and the clipboard; View the window; **Go the places** — a project's surfaces; Project the
  verbs on a project; Graph the canvas; Step the picked steps; Tools this machine. A verb is
  placed by asking what it is about, which is the question *View is the window; Graph is
  the canvas* (below) first asked of the canvas.
- **No menu is greyed whole where people spend their time** — a project's graph open,
  nothing picked. A menu that opens onto a column of grey says nothing about why, and the
  bar is where somebody new goes to learn what the application does.
- **What a step *is* is set where its aspects are.** Type (the kind toggles) is the aspect
  bar across Step Details and Test (add, archive, file, record) is the step's Tests tab
  there, the Tests strip and the Test panel — so Step's `classify` band is `in_menus=False`
  and the palette finds it. The band had grown to Type, Test, Test Category and Test Sort
  Key, four child menus that repeated an editor already open beside the step, and the
  developer's call was that they are better off there. What went with them is the one
  thing only a menu did: filing many picked tests at once, which `dplanner test file` does
  and the window no longer offers; the Tests tab's right-click, which led with the results,
  is its step's Step menu now, like every table's.
- **A family about one kind of thing is a child menu**, labelled for itself: Project ▸
  Specs (adding a spec, then the picked document, then its source), Step ▸ Show in (*Graph*,
  *Order*, *Coverage* — where a label that repeats "Show in" is noise). Eleven greyed spec
  verbs among the project's own buried both; one child menu names the subject once.
- **No two entries in one menu share a mnemonic.** Qt answers a letter two entries share by
  moving between them rather than running either. The bar deals each top-level title the
  first letter no earlier menu took (`marked_titles` — Go before Graph leaves Graph its *r*),
  and `tests/modules/test_menu_bar.py` holds every menu and child menu to it, with the first
  principle and every composed band beside it.

**Go is the views' seat in the bar, and N50 still holds for right-clicks.** F7 took the
views out of Project because the index's right-click renders Project whole, beside the very
rows it would have repeated. That reason is about right-clicks, and Go keeps it: no
right-click renders Go, so the index row stays the views' seat in the window, and Go gives
the bar — and a window with the index hidden — a way to them. Estimate Steps and Preview
Report went with them: they are places too, the two with no row, and empty canvas's
right-click renders Go ▸ `survey` for them as it rendered Project's. **Show in keeps a
table's reach.** A table still needs Order, Step Statuses and Tests from a row (F7's *A card
is the step* has why), so they stand in Show in beside the entries that land on the step,
as second seats with `palette=False` (`order.open_step` beside `progression.open_step`); a
card renders only `open`'s half of the child, the entries about the step itself.

## View is the window; Graph is the canvas

The graph editor's own verbs — Sort, Layout, Divide, Frame, the marks, Snap to Grid and the
Background — are a top-level **Graph** menu. Inside **View** they would make it half a window
menu (panels, tabs, theme, zoom) and half a drawing-surface menu, and leave the surface this
application is mostly *about* with no heading of its own. View is about the window — which
is what decides where the Problems panel's switch sits: the panel is inside one project's
tab, so it is the graph's chrome and not the window's, and View ▸ Panels is about the areas
around the tabs.

**A verb is filed by where its subject is picked.** Because the right-click is composed by
what is under it (below), where a verb is filed does not decide where the canvas offers it.
Filing the canvas verbs on **Step** would cost every table that renders Step by name New,
Find, Go, Lasso and Redirect greyed — each needs a canvas the table does not have — and give
an arrow's right-click Rename. So the question is *what does the verb act on, and where is
that picked*:

- a **point** on the canvas — `new`: New Step, and Paste's second seat (its home is Edit,
  where Ctrl+V lives; one enabled QAction may own a shortcut);
- the **plane** as a place — `select`: Find, Lasso, Select Nearest;
- a **mixed** pick — `narrow`: Select Only Steps, Select Only Links;
- a picked **arrow** — `links`: Remove Link and the Redirect pair;
- the drawing itself — `arrange`, `look`, `panels` as before;
- picked **steps** — Step: Rename, Delete, Connect, Link, Unlink (the link between two
  picked steps, which a table can offer with no arrow in sight), Isolate, and *Show in ▸
  Graph*, in `surfaces` because it is the way from a table's row to a step's card.

The test is still not "which surface does this run on" — nearly every one of these runs on
the canvas — but "what is its subject": a step, or something only the canvas can point at.

## A right-click is composed by what is under it

The canvas's right-click rendered the Step menu for everything: a card, an arrow and empty
canvas all got New, Find, Go, Lasso, Redirect, Status and Run Agent — twenty verbs of which a
handful applied to the thing clicked. It now renders a row of bands chosen by that thing
(`canvas/menus.py`):

| Under the cursor | Bands |
|---|---|
| a card | Step's bands about the step itself: `edit`, `link`, `track`, `agent`, `open` |
| an arrow | Graph ▸ `links` |
| steps and arrows | Graph ▸ `narrow`, Edit ▸ `clipboard`, then the card's bands and `links` as `Step` and `Links` child menus |
| empty canvas | Graph ▸ `new`, Graph ▸ `select`, Edit ▸ `selection`, Go ▸ `survey` |

**The click makes its subject current, and the menu is a function of the selection.** A card
or an arrow outside the pick becomes the pick, one inside keeps it — the rule the card had
always followed, so "Delete 2 Steps" can be said — and empty canvas clears the pick and notes
the point, so New and Paste land there. Choosing the row from the *selection* rather than from
the item under the cursor means the verbs offered and the pick they act on are one fact: a
mixed pick right-clicked on one of its cards is still a mixed pick. A mixed pick leads with
narrowing it because nothing else is about steps and arrows at once — and with Make Stack
beside what acts on any of it, because a drag across a line picks the line's arrows too, and
stacking what was dragged across is the reason to drag (S18). Put on a Branch sits beside it
for the same reason: a stretch dragged across comes with its arrows.

**A card is the step, not a table's Step menu.** The first cut rendered the Step menu whole
on a card, which took the canvas's verbs off it and left a table's: Type, Test and the test
filing menus (a step's kind is set in Step Details, where the aspect bar is, and a test is
picked only in a Tests tab), Compile with Agent (the Docs tab's strip carries it with the
profiles), Show Order, Show Step Statuses and Show Tests (each a row under the project in the
index, standing beside the canvas), Test Details, Estimate Steps and Reveal in Graph (which
on the graph would only centre what was just clicked). A table still wants all of those —
from a row, the index is not beside you and the graph is a tab away — so they are **filed,
not dropped**: `track` (Status, Estimate) came out of `classify`, `compile` out of `agent`,
and `surfaces` out of `open`, and the card renders `edit`, `link`, `track`, `agent` and
`open` while every table and the menu bar render the whole menu. Empty canvas follows the
same rule for the project: Go ▸ `views` is the views the index already lists, so the
background renders Go ▸ `survey` — Estimate Steps and Preview Report, the two looks over the
whole plan with no row there — instead. The Project menu followed the same way: those views
(Specs, Assets, Steps, Order, Step Statuses, Time Estimates, Coverage, Tests) repeated rows
standing beside it, and the index's right-click renders it, so they left it — the index row
is their seat in the window and Go their seat in the bar (*The menu bar is sorted by
subject*, above), and no right-click lists them beside the rows. `fill_menu` takes several
groups for this, in the menu's order and ruled as the menu rules them, so the card is one
band and the mixed pick's `Step` child is the same band.

**It is `fill_bands`, not an entry in `MENU_STRUCTURE`**: an entry there is a place verbs are
registered into, and nothing registers here. `fill_bands` (`framework/action_menu.py`) is
the one policy for a composed pop-up: a rule only between two bands that each drew
something, none between two child menus (their names part them, as in Step's `track`), and
an empty child taken away. The cost of composing from groups is that a band naming a group
nothing registers into renders nothing, silently — so a test holds every composition to
what is registered (`tests/modules/test_menu_bar.py`), which is the check a refiling of the
menu bar leans on. A stack's frame was the fifth target, and it took one row and one
branch in `target_of`: a pick that is exactly one stack's members leads with the stack's own
verbs and offers the card's one level down (*A stack's frame is the stack's handle*). A new
arrow verb registers into Graph ▸ `links` and appears in the arrow's menu and the mixed
pick's *Links* without an edit here.

**An arrow had to become right-clickable, and Qt was in the way.** A right press on an item
that is selectable but not movable is ignored by `QGraphicsItem`, falls through, and
`QGraphicsScene` clears the whole selection before the context menu is asked for — measured,
on Qt 6.11: three picked arrows, right-click one, and Remove Link took one. A card is movable
and so kept its pick, which is why the canvas never noticed. `IdleMode` therefore claims
every right press, as it claims a press on a handle; the context menu still arrives (Qt
sends it whether or not the press was accepted), and the handler decides what the click
picks. The same claim ended a stray `LinkDragMode` a right press on a card's handle used to
start.

**Delete removes everything picked, in one undo.** The Delete key named `steps.unlink` first,
so on two linked steps it removed the link between them, and on steps and arrows picked
together it deleted the steps and left the arrows. It now names `("steps.delete",
"links.remove")`: `steps.delete` hands the picked arrows to `remove_steps_command` beside the
steps, where they join the links into the doomed steps in **one** per-list removal (two
commands on one list would each be built from the state before either ran), and the entry
reads "Delete 3 Items"; with no step picked, `links.remove` takes the arrows alone. Unlink
kept only the two-step case, where it is a step verb.

## A strip of verbs is cut into bands, and a band folds whole

The canvas strip carried nine words and eleven glyphs in six unlabelled groups, and read
as a sentence rather than as a tool palette. DESIGN.md's *Toolbars* had already said what a
strip of verbs is — a glyph with its words in the tooltip — and named this conversion as
owed: the strip was built on `ActionToolbar`, the presenter that predates the `Toolbar`
primitive and has no overflow of its own.

**The band is the structure a toolbar has, so it is named.** Nineteen glyphs in a row are
nineteen riddles; *Go · Step · Link · Arrange · History · Options* is a thing to learn
once, and the name under a band is structure rather than an explainer — it says what the
glyphs above it are *for*, where a word on each button would repeat the tooltip. The bands
are spelled out in `toolbar.py` rather than inferred from the menus, where these
verbs sit under four different headings: what a person reaches for together is not what a
menu bar files together.

**And the band is the unit that folds.** A canvas can always be dragged narrower than its
own strip. The old answer was Qt's `»`, which pops the hidden buttons up as glyphs again —
no help at all to somebody who could not read the glyph on the strip. The primitive takes
a whole band off from the right and lists it in the `…` menu as glyph **and** words, with a
rule where each band begins: half a band on the strip and half in a menu says less than
either, because the bands are how the strip is read. **It folds again whenever a control
asks for room, not only when the strip is resized**: the Problems count gaining a digit, or
a glyph polished on first show, grows a button without resizing the strip, and a strip that
folded only on a resize drew its bands over one another until the window next moved. That
surfaced when the Step band gained New Stack and Make Stack (S18). `Toolbar.event` refolds
on the `LayoutRequest` such a control posts.

**A band's buttons are squares, and only a band's.** A palette is a grid of targets of one
size, and a square is also what puts a glyph in the middle of its button rather than a few
pixels left of centre. It is the *banded* strip that gets it, not every dense one: the
aspect bar seats ten toggles in a 360 px dock, and squaring them costs it two — which for a
row that answers "what does this step carry" is the row not answering. The two strips want
opposite things from the same primitive, so the property says which.

**And a control that is not a verb goes in the band it is about.** The layout picker names
the arrangement the canvas is showing, so it sits at the end of *Arrange*, added as a
widget — which never enters the `…` menu and hides when there is no room, the way a filter
does. It stood *outside* the strip while the strip was one undifferentiated row and the
rule was "it must survive every width"; beside a row of named bands a lone worded button
past the end read as something that had fallen off, and the band it belongs to says what it
is better than its own isolation did.

**The glyphs come from the specs.** Every verb on the strip carries `ActionSpec.icon` now,
which is what let the module's own `ICONS` table — and the `_WORDED` map beside it — be
deleted rather than extended. A module that adds a verb to the strip adds its glyph where
the verb is registered, and the strip learns nothing.

**A checked glyph takes `$ON_ACCENT`.** The standing reason the mode switches and the marks
were *words* was that a checked button is filled with the accent and a glyph painted in the
quiet tone vanishes into it. The fix belongs in the primitive, not in an exception per
surface: `Toolbar` re-inks a verb's glyph on its toggle, taking the ink from the palette's
`BrightText`, which `theme/palette.py` now carries the theme's `on_accent` in (it held
`accent_hover`, which nothing ever read). A painter has no stylesheet, and the palette is
the only way it can learn a colour the stylesheet writes.

**The marks became a face.** Six worded switches on a strip of glyphs was a row half words,
and *how the graph is drawn* is a question asked rarely and answered best in a menu, where
each choice says what it means. *Options* is one glyph dropping the Graph menu's `look`
band — rendered through `fill_menu`'s new `group` filter, so it is the menu and never a
copy of it, and a mark added later appears under it having touched nothing. It is a face
and not a verb with an arrow: there is no verb under it, so it wears the layout picker's
look rather than the hairline that says two halves do different things.

## The glyphs are somebody else's, and they are copied in

Forty-odd hand-painted `QPainter` calls was the right answer at a handful and the wrong one
at forty: the strokes drifted between glyphs, nobody could draw a new one to match, and the
result was, in the developer's words, "ok, but not super nice". They are **Tabler Icons**
(MIT) now — the set is the largest permissive one, which matters because this application
needs glyphs a small set does not have: redirect to and from, isolate, divide, three kinds
of mark.

**Copied in, not depended on.** Fifty-two SVG files come to 212 KB, against a dependency
that would bring a package, a version to resolve and a release cadence to follow — and the
full set is over six thousand files, which no repository wants in order to use fifty.
`scripts/vendor_tabler_icons.py` holds the mapping from *what a glyph means here* to the
Tabler icon that says it, so the key is ours and outlives any set: changing icon sets is
changing that file's right-hand column and running it again. The tag is pinned in
`theme/icons.py`, because the application is what has to state the version — in Help ▸
About, which an MIT notice and a bug report both want.

**One painter, and the alpha is the painter's.** Qt's SVG renderer knows no
`currentColor`, so the ink is substituted into the source before rendering — the trick
`drop_arrow_url` already plays for the combo arrow — and the colour's *alpha* becomes the
painter's opacity, because an SVG stroke colour has none. A strip's glyphs are the text
colour at `SECONDARY_ALPHA`, so a painter that dropped the alpha would make every toolbar
in the application read a shade too loud. The canvas's medallions go through the same
`paint_glyph`, which is what retired the five `paint_*_glyph` functions and the if/elif
chain that chose between them: the kind *is* the glyph's name.

**What stayed hand-painted is what is a picture of state rather than of a thing**: the key
badge draws text, the colour strip is a gradient, the spinner is a frame per angle, and the
filter funnel is two states drawn to one width. No icon set has those, because they are not
icons.

## An acknowledgement is asked, not written

Help ▸ About was a `QMessageBox.about` naming the template's product, which is two faults in
one line: a platform dialog where every other surface is a `DialogFrame`, and a name nobody
had looked at since the fork. What replaced it answers the question a licence page is for.

**The list of components is ours; every fact beside it is the installation's.** A package
cannot say what it *does here* — "the OS keychain a source's token is kept in" is a sentence
about this application — so that line is written. The version and the licence are read from
`importlib.metadata`, in the order the answers got vaguer: `License-Expression` (an SPDX
expression, and the one to believe), then the free-text `License`, then the trove
classifiers, which say *MIT License* where the package itself says *MIT*. Asked the other
way round, two components under one licence read as two different ones.

A hand-kept licence table is a table that drifts, and the one thing an acknowledgement must
not do is claim the wrong licence: a dependency bumped to a version under different terms
would go on saying the old ones. And a component this build does not have — an optional
one, a source checkout missing a wheel — says so in its row rather than vanishing from the
list, because an acknowledgement that quietly shortens is worse than one that admits a gap.

## One picker, two lists

*Find Step…* wanted what the command palette already was: a field over rich rows, ranked by
what was typed, one pick. The palette's constructor had the registry and the context wired
into it, so the honest move was to lift the shape out — `framework/picker.py`'s
`PickerDialog` over plain `PickerRow`s — and rebuild the palette on it as the half that
knows what a verb is. A third picker is a list of rows, not a third dialog.

**A label match always wins.** A row is searched by its name first and by what it *also*
answers to second — the menu path for a verb, the key for a step — so a verb actually
called what was typed is never pushed under one merely filed there. `also` is deliberately
separate from what the row *shows*: a palette row's shortcut sits at its right, and folding
that into the haystack would make "ctrl" match every verb that has one.

**A picker over a long list opens on its landmarks.** Three hundred steps is not a list
anybody scrolls, so `PickerRow.landmark` says which rows are worth showing before anything
is typed: Find opens on the plan's milestones and features, and everything is in play
from the first keystroke. A list with no landmarks opens whole, which is what the palette
wants. One field on the row, and the rule is the same both ways.

**Landing is centring.** `steps.reveal` opened the project's tab and called `setSelected`,
which selects a step that may be a screen away — a reveal that reveals nothing. The canvas
grew `GraphView.centre_on_step`, and `ProjectActivity.select_step` calls it, so every view
that reaches a step through the registry — the order table, the Step statuses tab, the
Agents browser, `feature.reveal` — now lands on it. The zoom is untouched: Frame is the
verb that changes how much of the graph is in view, and a jump that also zoomed would lose
the scale somebody had chosen to work at.

## A panel inside a tab follows the tab

A panel inside a tab is not a dock panel, and the difference is which question it follows.
A dock panel follows *the window* — one instance, retargeted by the context on every change
(*Where a panel goes*). A panel inside a tab follows *that tab*: there is one per tab, and
each is handed a context the tab constructs — its own project, its own picked row — so a
tab in the background never follows the tab in front. That is the same rule as "only the
active pane speaks for the user", read from the other side.

**The hosting was written once when the second host arrived.** The Problems list was the
first, and its frame, strip button and splitter lived in `canvas`. The Test panel
was the second: as a dock panel it was one instance retargeted by whoever published, so it
hung around when the Tests tab was not in front and needed the project form to yield to it
by name. Moving it beside the roster meant a second copy of the same hosting, which is the
signal to promote — `framework/side_panel.py` now holds `SidePanel`, the frame, the
`PanelButton` and `HostedSidePanel`, and each host is a handful of lines: name the spec,
seat the button, feed the panel from its own selection, and run its own preference verb.

**The seam belongs to the splitter, and the width is given when the seam is closed.** The
tab's surface and the panel meet in a `QSplitter`, so the line between them is the one
every splitter in the application wears and the panel draws no edge of its own. A splitter
hands out the width it had when its children were added, and a tab is built before it is
on screen — so a panel switched on later would arrive at nought pixels wide and read as
nothing having happened; `set_shown` opens the seam to the spec's width when it finds it
narrower, and leaves a wider one the user dragged alone.

**Fed while hidden, so it is right the moment it is stood.** The tab feeds its panel on
every selection change whether or not the frame is on screen — off screen and showing
nothing are different states, the rule *A panel that steps aside keeps its content*
learned on the dock. What differs from the dock is the preference: a tab's panel has no
*View ▸ Panels* entry, so each host keeps its own — a field on the graph's `Look`, one bool
for every Tests tab — and both the strip button and the frame's close run that one verb.

**Whether it stands is a preference, so it is a field on `Look`.** The marks, the
spotlight, the ground and the snapping are one value kept per user and fanned to every
canvas; a panel beside the canvas says no more about the plan than a grid does, and the
plumbing — a key, a setter, a fan-out, a context refresh so the switch re-reads itself —
already exists. A second copy of it for one boolean is what `look.py` was written to
prevent.

## The command palette says where a verb lives

A palette row of the spec's label and its shortcut works for *Frame Graph* and fails
completely for *Vertical* and *Horizontal*, which are written to be read under the word
*Divide* and say nothing without it. The label cannot absorb the missing half — the menu
would then read *Divide ▸ Divide Vertically* — so the row carries the **menu path** instead,
on a second line under the name, with the shortcut right-aligned beside the name and the
verb's glyph at the left (`framework/list_rows.py`'s two-line row, the same one every rich
list here uses).

The path is the menu and the submenu, never the group: a group is a module's word for a band
of entries and is not a heading anybody ever sees, so printing it would name something that
does not exist on screen.

Once the path is on the row it is worth searching, and the ranking is the whole design: a
match on the *label* always outranks one that needed the path, as a `(where, -score)` sort
key. So "vertical" still puts *Vertical* first, and "divide vertical" — how somebody who
remembers the submenu and not the entry looks for it — finds it at all.

## Edit verbs belong to the surface whose things they act on

The Edit menu holds Undo and Redo from the app shell, and then Cut, Copy, Paste, Duplicate,
Delete and Select All — and those six are the graph editor's, registered by
`canvas` as ordinary `ActionSpec`s. The alternative was a dispatching layer: a
generic `edit.copy` whose meaning is supplied by whichever surface is current. It was not
built, because the machinery above already gives that behaviour for free. A state callback
reads the context, so Copy is enabled exactly when steps are chosen; *disabled, never hidden*
keeps the menu stable while it is not; and a greyed menu-bar action's shortcut does not fire.
A dispatcher would be a second action registry with one registrant. **The moment for one is
when a second surface needs Cut/Copy/Paste** — a shortcut can be owned by one enabled QAction
at a time, and two surfaces enabled at once would be Qt's *ambiguous shortcut*, which fires
neither. Until then, a second surface's verb is a second spec with a distinct label, and the
context greys the one that does not apply.

What they act on is what Delete acts on: `step_verbs.chosen_steps` — the selected steps, else
the focused one — so Cut and Copy work wherever Delete does, a table's right-click included.
Only Paste needs a canvas: it is the target. Its state never reads the clipboard;
`ClipboardWatch` counts what the clipboard holds when the clipboard changes and re-emits
the context, the same idiom that keeps the Undo label current.

**Standard keys are menu shortcuts here, and Delete is not.** The canvas-keymap rule in
`CLAUDE.md` is about bare keys: an `H` on a menu-bar QAction eats a keystroke in every
editor. Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+D and Ctrl+A are different, and this was measured
rather than assumed: `QPlainTextEdit` and `QLineEdit` claim all of them through
`ShortcutOverride`, so a window-wide menu shortcut never fires while an editor has focus —
the property `tests/modules/appshell/test_appshell.py` pins for Ctrl+Shift+Right. A table claims
none of them, but every table here is a tab, so no table ever competes with a canvas for a
key, and a table has no Ctrl+X of its own to lose. Delete is the exception in the other
direction: a bare `Del` on the menu bar would fire in every list in the window, and
`QKeySequence.StandardKey.Delete` binds Ctrl+D as well as `Del`, which would collide with
Duplicate. So Delete keeps its canvas key and the Edit-menu entry shows no shortcut — and
that entry is `steps.delete_edit`, the verb's second seat: `steps.delete` stays on the Step
menu because a card's right-click, five tables and the toolbar render that menu by name.
Paste has the mirror image: its home is Edit, with Ctrl+V, and `steps.paste_graph` is its
second seat on Graph ▸ `new` beside New Step — both land where the canvas was clicked, which
is what a right-click on empty canvas offers, and that menu cannot render Edit ▸ `clipboard`
without four verbs greyed for want of a pick.

**Deleting asks nothing any more.** A prompt in front of an undoable verb teaches the wrong
lesson — that the gesture is dangerous, when Ctrl+Z is the safety net — and the CLI's `step
remove` has said so since it existed. Steps and regions (since retired) lost their prompt in
one pass, because the Delete key ran whichever of them the selection called for and one
gesture should not sometimes ask. The prompts that remain guard what undo cannot reach:
removing a project from the library, a release, an outside edit.

## A child menu of data is rebuilt when it opens

The menu bar's QActions are created once and restated on every context change, and for verbs
that is right: an action's identity is fixed, only its state moves. A list whose *entries*
are born and die at runtime — the live agent runs behind Tools ▸ Agent List, a "Recent…"
menu anywhere — does not fit that shape. Registering an ephemeral `ActionSpec` per row would
mint action ids nobody manages, leak each row into the command palette, and need the
un-registration door the registry deliberately keeps shut (reload is a full rebuild for the
same reason).

The layout picker already answered this on the toolbar: saved layout names are data, so the
popup is built fresh every time it opens, and only the entries with a fixed identity render
through the registry. `DataMenuSpec` is that answer given to the menu bar. The spec carries
`menu`, `group` and `order` — placed and sorted by the same table as any action, so the
group separators need no new rule — plus a `fill(QMenu)` the presenter calls after clearing
the child menu on every open. Rows can never go stale because they never outlive a look at
them; a fixed verb inside the list (the Agent List's *Agents…*) renders through
`append_action`, never as a copy.

One deliberate asymmetry: a spec-fed child menu disappears when everything in it is hidden,
but a data child menu stays visible with an empty list. The menu itself is the capability —
*hidden means absent* — and its emptiness is the fill's own story to tell with a disabled
entry ("No agents running from this window"), which is the same greyed-teaches-the-
precondition rule every other presenter follows.

## Where a panel goes

The window has a centre — the tab groups — and three areas around it: **left, right and
bottom**. Anything anchored in one is a `PanelSpec` in `services.panels`, and the framework's
`PanelDock` puts it there. The index tree is one, and the only one: a project's forms are its
dialog's tabs and the Test panel stands beside its roster. Right-clicking a
panel's header moves it between areas or hides it, and *View ▸ Panels* switches it back on;
an area no panel stands in hides its whole-side toggle, because HIDDEN is for a capability
absent from this build and a verb that folds nothing teaches nothing.

**One panel, not one per tab.** This is the whole reason the dock exists, and it was learned by
getting it wrong: the step detail panel used to be built *inside* `ProjectActivity`, so opening
a second project built a second panel with a second set of aspect editors, and splitting the
window put both on screen at once. Two copies of one editor is not a richer window — it is the
same 360 pixels spent twice, and it raises a question with no good answer ("which one is the
real one?"). So a panel belongs to the window. (That editor has since left the areas
altogether — *The step editor is a modal* — but the rule it taught governs every panel
there is.)

**It follows the user by reading the context, not by being told.** A panel that cares implements
`ContextPanel.show_context(context) -> bool`; the dock calls it on every context change and
takes the panel off screen when it answers False. Nothing pushes at a panel, and no panel
subscribes to the context itself — there is one subscription, in the dock.

That one decision is what makes "follow the focused tab" cost nothing. The rule that *only the
active pane may write to the selection scope* already existed, for a different reason; a panel
that reads the scope therefore shows the active pane's selection by construction, and
`ProjectActivity` **lost** its `_panel` field rather than gaining an "am I the visible one?"
check. It also means a surface nobody planned for gets a panel for free: the Tests tab
publishes a test selection and never had to know the Test panel exists.

**Areas, not draggable docks.** `QDockWidget` gives floating windows, tear-off drags and a
serialized layout blob nobody can read or reason about. What this needs is "put that over
there" — three fixed places and a menu — so that is what it has, and where each panel sits is
three legible `QSettings` keys under `layout/`.

**An area with nothing in it takes no space.** An empty right side is a wider canvas, not a
blank column, which is what lets two panels share one area and take turns — each answering
`show_context` for itself, neither having heard of the other.

**A panel that belongs to a tab is the other thing.** The Problems list beside the canvas
and the Test panel beside a roster are not dock panels at all: they follow one tab, not the
window — *A panel inside a tab follows the tab*, under *The Problems list lives in the
graph*.

## A seam belongs to the splitter, and only a split window marks a pane

Two surfaces that meet at a splitter meet at a hairline. That line used to be drawn by the
*surface*: `#PanelAreaLeft` carried a `border-right` and `#PanelAreaRight` a `border-left`,
each area knowing which of its sides faced the tabs. It worked for the three areas and for
nothing else, which is why splitting the window produced two tab groups with no boundary at
all between them, and two panels stacked in one area separated by a caption and a dead band.

**The seam is the handle's, so there is one of them.** One `QSplitter::handle` rule reaches
every splitter the application builds — the tab host's, the dock's, each area's, the Specs and
Tests master-detail splitters — and every splitter written after it. The areas' borders came
off in the same change: a surface that draws its own edge where a seam already falls gets two
lines a pixel apart, and the second one is the one nobody meant.

**No splitter names a ground of its own, either.** A handle is 7 px so it can be grabbed, and
1 px of that is the line; the other 6 have to be *something*. A vertical handle can leave them
transparent and let the splitter's own ground through, so a panel area's elevated ground
arrives for free. A horizontal one cannot, so `$BG_BASE` is written into the rule — and beside
an elevated panel that leaves 3 px of the window's ground either side of the line, which reads
as a groove rather than as a mismatch. An exception for the one splitter it is visible on was
written and then deleted: one rule with no exceptions is worth more than three pixels, and the
exception would have had to restate the hover and drag states too or quietly lose them.

**The two orientations are built differently because Qt paints them differently**, and that is
worth knowing before touching the rule. A horizontal handle honours the box model: the line is
the content box and the ground either side is its borders, centred and exact. A vertical handle
fills its entire rect with the background and draws its borders *outside* it, so the same rule
turned on its side renders a seven-pixel slab. Nothing warns you; a stylesheet is silent about a
rule that renders wrong as it is about one that never matched. `tests/test_theme.py` therefore
**renders** a splitter in both orientations and asserts exactly one row of `$BORDER` across the
handle, which is the property, rather than reading the rule, which is not.

**A pane is marked only while there is another pane.** The group you are in wears a 2 px accent
edge along its top; one pane is the whole window and needs no mark, and the condition is the
same one that installs `_ActiveGroupWatcher` — because it is the same fact. Two cues now say
the same thing (the edge, and the dimmed titles on everyone else's tabs) and both are set in
`TabHost._paint_active`, so they cannot disagree.

The edge could not go on the group itself. `setDocumentMode(True)` means `QTabWidget` paints no
pane frame, so there is no `::pane` for a stylesheet to reach; and anything a widget paints for
itself is covered by its own children. Styling the `QTabBar` was never an option — QSS replaces
its whole native rendering, which is what the dimming relies on not happening. So each group
sits in a one-widget `_Pane` frame that carries an `active` property, and `group.parentWidget()`
is how the host finds it: a wrapper rather than a second map to keep in step.

One thing that is easy to get wrong, and has a test of its own: `_announce` short-circuits when
the active group and activity are both unchanged, and closing the *other* pane's last tab is
exactly that. So `_drop_group` clears the mark itself rather than trusting the announcement,
or an unsplit window would keep an accent edge on the pane that survived.

## A primitive carries the rule; a dialog's stylesheet does not

(`DESIGN.md`'s *Dialogs*, *Tables*, *Signalling* and *Bringing a surface up* are the
standard this settled; `modules/debug/design_example_activity.py` is the living reference.)

For a year the rules lived in two places that could not see each other: DESIGN.md said
what a dialog looked like, and `theme.qss` said which dialogs looked like it. The accent
primary was styled inside a list — `#ProjectDialog #PrimaryButton, #MovePlanDialog
#PrimaryButton, …` — and the quiet secondary likewise, so every new dialog was added to
four comma lists or got Fusion, and three surfaces that set `#PrimaryButton` in good faith
got no accent at all. The list was not laziness. **A descendant rule outranks a bare id
whatever the order**: `#Dialog QPushButton` is specificity (1,0,1) and `#PrimaryButton`
is (1,0,0), so the moment a dialog's buttons were styled by name, its primary could only
be reached by naming the dialog again. The fix is one line and one fact:
`QPushButton#PrimaryButton` is (1,0,1) too, ties, and **wins by position** — so it is the
last button rule in the file, says so, and no dialog is named again.

That fact generalises. **A primitive names its parts, never itself.** `DialogFrame` sets
`#DialogBody` and `#DialogFooter`; `Table` sets `#Table`; the subclass keeps its own
object name for tests and for whatever one-off it needs. The stylesheet then reaches every
dialog and every table through a handful of constant names, and a new one gets the
designed look having touched nothing — which is the whole of what *done* meant for the
design-system step. The alternative, a rule per dialog, is what the audit found: two
button strategies (a `QDialogButtonBox` with the platform deciding order, a hand-rolled
footer with the accent), margins of 20, 16, 12, 8 and none, four dialogs that set initial
focus, one documented data-loss hazard from a footer whose default was *Clear*.

The same shape recurred wherever a rule had no home. Three copies of one `QTableWidget`
configuration disagreed on nine settings, and four widgets set `objectName("OrderTable")`
to borrow a look — two of them lists. Empty states came in five mechanisms, or none.
Every busy state was a `QLabel` rewritten by hand. Each of these is now one thing in
`framework/`: `Table` applies the configuration once and its delegate paints what a row
wears; `EmptyState.stands_in_for` is the one swap; `StatusLine` is the one busy, ok and
error; `UpdatingIndicator` follows the one `Debounced` a view already has. The review
rounds that followed added, on the same principle, a `Toolbar` whose verbs are glyphs
folding into a `…` menu, a `FilterButton`, and a `Spinner` that turns in a button's own
glyph slot so nothing ever moves. **A rule with
no primitive is a rule that is followed by whoever remembers it**, and the audit is the
measure of how many did.

Two decisions inside the primitives are worth their reasons. **A table's row height is
derived from the font, never a token**: the UI font is the platform's own, and the fixed
28 and 44 the old tables carried clip two lines at twelve points; the paddings are the
tokens, the height is computed and set on the vertical header — the one mechanism that
sizes a delegate-drawn row, learned the hard way in the Tests table. And **a refused
primary is disabled with its reason in the footer's status slot** rather than enabled and
refusing: that is the rule every greyed menu entry already follows, and a dialog with a
second grammar for the same situation is a dialog that teaches the wrong one.

`Debounced` grew a signal for the indicator, `pending_changed`, because the alternative —
the Time tab's wrapper that showed a label before `trigger()` and hid it as the first
line of the rebuild — was two statements paired by hand that a test could never see up.
While it was being wired, `flush_all` turned out to walk a `WeakSet` in hash order: a
flush that writes (the progress recorder) re-triggers the views that follow the model, and
whether that left one pending depended on which object was allocated first. It settles to
a fixed point now.

**The stylesheet is checked against the source.** Forty per cent of it described the
application the template came from — a corkboard, a binder, a reader, a zen mode — and two
of those dead names were quoted in DESIGN.md as the canonical look. `tests/test_theme.py`
asserts every `#Name` in `theme.qss` is a literal some widget sets, so a rule outlives its
surface by exactly one test run. The same test renders rather than reads where it matters:
a stylesheet is silent about a rule that renders wrong exactly as it is about one that
never matched, which is why the primary's accent is asserted from a pixel inside a widget
named `ProjectDialog`.

**Why the reference is a Debug surface and not a document.** A rule is read once; a
surface is opened beside the one being built and compared, in both themes, with every
state on it — the refused primary, the tinted row while picked, the indicator while a
rebuild is owed. Debug ▸ Design Examples is that, a page at a time over sample data,
and `docs/screenshots/f1-design-example/` keeps them rendered so a pull request can show the difference
it made. Every later step that touches a surface points at them; DESIGN.md's *Bringing a
surface up* is the list of what to compare.

**The dialogs pass put every dialog-shaped surface on the frame, and three rules came out
of it** (`.claude/rules/shell-ui.md` states them; the renders are `docs/screenshots/s16-dialogs/`).
**A settings page owns no outer margin.** Nine pages carried 20, 12 or no margin inside a
dialog that added its own, so no two pages started their first caption at the same x, and
one page was taller than the window with nothing to scroll it. The dialog is what knows
where its seam falls and how tall it is, so it insets and scrolls; a page is
`settings_page()` and `block()`s — the design example's form, which the pages would
otherwise hand-write fifteen times, getting the layout-item rule (a child layout joins its
parent before it is filled) wrong in one of them. **What a gesture came to after its dialog
closed is a `notice()`.** A dozen `QMessageBox.warning` and `.information` calls reported a
failed creation, a publish, the caveats of a move — each with a platform icon and the
platform's arrangement of its words, the second design `confirm()` was written to retire
for questions. A state the dialog is still showing is never one: a clone running, a
refusal, a copied path go in its footer's status slot, where the person is looking, and a
move that succeeded is recorded once, in the status bar. **A verb in a dialog's body is
`quiet()`.** The per-dialog list existed to give body and footer buttons one look, and the
tempting replacement, `#DialogBody QPushButton`, is specificity (1,0,1): it would outrank
every id-only button rule inside a body — the step panel's own buttons inside Step Details
among them — which is exactly the trap that grew the list. A property selector,
`QPushButton[quiet="true"]`, is (0,1,1): it gives a body verb the footer's look and loses to
any rule that names its widget, so `QPushButton#PrimaryButton` still wins and a quiet verb
restyled as the primary takes the accent. `GlyphButton` is quiet already, for a verb whose
glyph has to follow the theme on a page that outlives it.

**A dialog on screen never resizes itself.** The Open Project wizard first sized itself
per page — two rows for the chooser, room for a list after it — and on Hyprland the page
after the chooser drew clipped, its footer outside the window, until focus moved. On
Wayland the compositor owns a window's geometry: a client's resize of a shown window is a
request it takes up at its next configure, so Qt lays the new page out at the new size
while the surface stays at the old one. X11, Windows, macOS and the offscreen renders all
apply the resize at once, which is why nothing but a real session showed it. So a dialog's
size is `DialogFrame`'s `size=` and nothing later, and a wizard's pages share one — a short
page sits at the top of the room its longer siblings need.

## A roster has three shapes: a table sets values in the row, a list stays a list, a well keeps its widgets

`.claude/rules/shell-ui.md` has the rule; this is why. The tables-and-browsers pass (S15) took the last
hand-laid rosters onto the primitives, and each of them turned out to be one of three shapes.

**A value set in a table's row belongs to the column, not to a widget in the cell.** The
bulk Estimates tab planted a spin box and nine buttons in every row with `setCellWidget`, and
the Time tab laid its milestone rows out by hand, measuring strings. A widget in a cell
swallows the row's hover and pick, forces a height the font does not give, and costs a
widget tree per row — a plan of four hundred steps is four thousand buttons rebuilt on every
settled change. So a `Column` carries the editing: an `editor` (`NumberEditor`,
`DateEditor`) that Qt's delegate opens over the cell, and `chips` the delegate paints and
hit-tests from one layout, so what is clicked is what was drawn. A commit is announced once
through `Table.edited` and the host pushes its command. Two traps came with it: a fresh
`QTableWidgetItem` is editable by default, and the announcement runs inside Qt's
`commitData` — or inside the click — so a host may write a cell in its slot but must never
rebuild the table there.

**The chips are the Estimates tab's reason to exist.** The pass first made the estimate a
number typed into the cell, with the sizes as Step ▸ Estimate verbs. It read well and lost
the page's most valuable property, which the person using it named at once: one size lit on
every row, down every row, is a grid in which the small, the large and the unsized steps are
seen before a number is read. The chips came back, painted rather than planted. Zero stands
past a hairline because adding no time is a claim, not a size. The last chip opens the
editor and wears any value off the scale, because a four-day step lighting nothing would
read as unsized. The unit moved into the header, once, because it was being printed on
every chip.

**A roster whose rows carry verbs and outlive a tick is a well, not a table.** The task
browser and the Agents browser were one layout written twice. Their rows carry *Cancel*,
*Show Terminal*, *Reveal* and a dismiss, and the task centre refreshes every 250 ms: a row
rebuilt on a tick loses the button being pressed. `RowWell.reconcile(keys, build, update)`
keeps a row per key and updates it in place. A task's indeterminate bar became a busy
`StatusLine`, the rule every other surface already follows: an unknown fraction is busy.

**A table row's own verbs are a painted ⋮, not a well.** The Step statuses tabs wanted each
row's verbs one click away — its agent's terminal, a shell in its worktree, its pull
request — and they are still tables: a reader compares the rows' unlocks and projects down
a column, and the rows are rebuilt wholesale on a settled change, never ticking under a
pressed button. A well would have given up the columns; a button planted in each cell
would have brought back everything the column-owned editors retired. So the ⋮ is a
`Column(menu=True)` the delegate paints and the table hit-tests, as it does the check box
and the chips, and a press says only *which row* and *where* (`menu_requested`): what a
row *is* is the host's knowledge, so the host builds the menu — from the registry, never a
copy. **It picks its row alone first**, where a right-click keeps a pick the row is in,
because `focus_entity` answers with the first selected step: a ⋮ pressed on the third of
three ticked rows would otherwise have offered the first one's terminal. And it never takes
the table's slack, or a table with no stretching column would push the ⋮ to the far edge
of a wide tab, away from the row it belongs to.

**A list stays a list.** Standing note N28 said every `#OrderTable` borrower moves onto
`Table`, and DESIGN.md says a list when there is one column of things. The implementation
notes log is one column of things, and a one-column table would add a header nobody reads,
so it moved onto `RichList` instead: the table's well, hover and picked edge, on the
two-line delegate. The step panel's test roster compares an id, a name and a result down a
column, so it became a small `Table`.

**A strip has to remember what its host took off.** `Toolbar._reflow` set every item's
visibility from the room alone, so a control a view hid came back on the next resize — the
Documentation view's *Group by* had been doing it unnoticed. `set_shown` is the host's
statement, and the reflow counts only what is shown. Three surfaces in the pass needed it.

## The context is announced once per turn, and a panel that steps aside keeps its content

**The rule.** `ContextService` updates its snapshot synchronously and *announces* it
through a seam the builder routes into a 0 ms `Debounced`: every listener — the menu
bar's ~150 action states, six toolbars per canvas, the panel dock, the sync module's
branch label — hears one context per event-loop turn, the final one. A gesture that
changes the selection does so in one `GraphScene.select_steps`, which announces once; a
verb that needs a selection the user never made (`steps.link` after a connect or a drop)
is handed a constructed `Context` instead of the canvas selecting for it; a panel the
dock takes off screen keeps what it was showing; and nothing in an action state or a
structure listener spawns a process.

**What it replaced, measured.** On a real plan — 74 steps, 118 links, 344 notes, the
project tab open, one step selected — a connect (`c`, click, click) blocked the GUI thread
for **1.7 s** and a paste for **0.6 s**, while the link command, the paste command and
the canvas resync each cost under 10 ms. Two causes multiplied. The connect published the
selection *seven* times, synchronously, each publish re-evaluating every action state
(20 ms for the menu bar alone), and the re-selection cleared before it selected, so the
selection was empty between publishes: the step panel stepped aside and came back twice
per gesture, and each swap was `QSplitter.setSizes` at 33–66 ms over the whole widget
tree. The tree was that heavy because the project form cleared every card when a step
was selected and rebound them when the selection emptied — the Notes card tore down and
rebuilt 344 rows of two word-wrapped labels each on every swap (`NoteRow.__init__` ran
1 032 times in one connect), and those 688 labels were what every relayout walked. With
the notes cut to five, the same connect took 0.19 s; with the fixes above, tens of
milliseconds. On top, 59 git subprocesses ran on the GUI thread in that one connect —
`origin_url` from `agent.run`'s and `sync.pull`'s states on every publish, and the sync
module re-asking status and branch of every repository on every `structure_changed`,
including a pasted step's — cheap on Linux and most of a second on macOS.

**Why the fix is the same shape as the view refresh.** The canvas already rebuilt once per
turn through `Debounced`, and the reason it was safe applies to the context verbatim:
nothing a listener does depends on an *intermediate* state, only on the latest, and
`current()` stays synchronous for the one reader that needs the truth right now — the verb
that runs after a publish. Coalescing at the source rather than at the four listeners is
what makes the rule hold for the next gesture somebody writes: a table that publishes
per row costs one fan-out too. The test suite runs the debounce service immediate, so
every existing test stays synchronous and deterministic; a test that asserts coalescing
switches it off and calls `flush_all()`, the pattern the view-refresh tests set.

**Why the selection bug was the same bug.** The canvas selected `[source, target]` so the
Link verb could read the pair from the context — deliberate, and it left two steps
selected, so `selected_step()` was None, the next Connect had no source, and the next
click on a card *selected* it instead of finishing a link. A constructed context is the
sanctioned way to hand a verb a selection (CLAUDE.md: a gesture can be tested by handing
it a `Context` with no widget in sight), and it leaves the user's selection where the
gesture found it, which is what the next `c` needs.

**Why the panel keeps its content.** "Off screen" and "showing nothing" are different
states, and the dock only ever asks for the first. A card bound to a project that is not
on screen costs nothing; a card torn down and rebuilt costs the whole widget tree, twice
per gesture, and throws away every text binding's caret. The step panel already had this
rule in its unchanged-id early return; the project's forms have it too, in the Project
dialog, whose tabs are aimed only when it moves to another project.

**How it stays fixed.** `scripts/measure_scaling.py --scenarios connect,paste` drives
the two gestures over the synthetic library with a step selected and reports, beside
the usual spans, how long the GUI thread was held, how many times the context was
announced and how many times the dock relaid itself — the number to quote before
touching any of this.
`tests/modules/canvas/test_canvas.py` asserts one announcement and no relayout per
connect and per paste in the window's deferred regime, and `tests/modules/sync/test_sync.py`
that a step add asks git nothing.

**An action's state is read on every announce, so it may not derive anything over the
project.** The day compiling documentation moved to a launched agent (2026-09-13), the
*Compile Out of Date* entry gained a label that counts what is due — and its state
callback computed that count by walking every collector's cone and digesting its sources,
on every announce. A title keystroke announces once, so the context refresh went from a
flat 4–6 ms to 198 ms at 400 steps in one commit; the menu bar re-evaluates every state
per announce, and one slow state taxes every gesture in the window. The same rule as the
keyring and the subprocess above, broken by a pure derivation, which is the version
nobody notices until the plan is large.

The fix is the shape the Problems count already has: the module keeps the frontier per
project as last *settled* — a `Debounced` at `SETTLE_MS` recomputes it for the projects
somebody asked about, every library signal forgets what was settled, and the state reads
the last answer (`DocsModule._frontier_of`). A settle that changed an answer announces the
context, so the label catches up one settle after the burst; a project never asked about
reads *checking…*, disabled, for that one settle. The gesture (`_compile_stale`) computes
fresh — it is one click and may pay the walk. In the suite's immediate regime the trigger
runs inline, so the answer a test reads is always current and the settle never re-enters
the announce it was read from (`_reading`). `collect.frontier` is the derivation, one
walk per collector where the state made three; `docs status` reads `compiled_state` over
sources it already holds for the same reason.
`tests/modules/docs/test_docs_compile.py` asserts, in the deferred regime, that ten reads walk
nothing, that a change leaves the label as it was until the settle, and that the settle
announces.

## A theme is provided, never listed

A **theme provider** offers themes, and the application asks its providers rather than a
table — a hand-kept list is one that copies another program's themes by hand and cannot
follow the desktop.

**The contract is a record of callables** (`theme/providers.py`), the shape
`domain/agents.py` set for an agent harness: an `id` the persisted choice carries, a
`label` the settings page shows, `refusal()` — why it does not apply on this machine, None
when it does — `groups()`, the themes it offers in the lists the Theme menu shows them as,
and for a provider that follows the desktop, `current()`. **Capabilities are derived,
never declared**: a provider follows the desktop exactly when it has a `current`. It lives
in `theme/` because it names `Theme`, which `domain/` may not import; `theme/` is a leaf
every layer above may read (`tests/test_architecture.py`, rule 9), and importing the
package loads no Qt — the Qt half is imported inside `apply_theme` — so a provider module
reads it without a graphics stack, which is what lets its file be a `HEADLESS_FILES` name.
The built-in provider is the fallback every build has: the house themes and every theme
Omarchy ships. `modules/theme_omarchy/` and `modules/theme_system/` each export one from a
Qt-free `themes.py` and have no window half, like the harness modules; the root's
`theme_providers()` is the tuple, built **once** in `app.main` and handed to both the
startup apply and the session, so every later reader takes it from `ThemeService`.

**Anchors from `colors.toml`, ramps derived.** Omarchy's file is a terminal palette, and
its own shades are not the ramp a window needs — `solitude` ships a `lighter_background`
equal to its `background`, and `catppuccin-latte`'s "lighter" one is darker than its base.
So `theme/omarchy.py::theme_from_colors` takes exactly the anchors a person tunes —
background, foreground, accent, the selection pair, blue and magenta for the links, the
mode — and derives every surface, border and secondary text with the proportions the
hand-tuned house themes use, which is what the contrast invariants in `tests/test_theme.py`
prove for all twenty-five at once. The selection pair is Omarchy's own (`selection` with
`bright_foreground`, as its terminals show), so the generated themes changed the selection
colour of sixteen hand-copied ones; the ANSI hues reach a `Theme` only as its links,
because status tints are constant tones by design (DESIGN.md's exception #2). The built-in
table (`theme/omarchy_themes.py`) is generated by `scripts/import_omarchy_themes.py` from
`$OMARCHY_PATH/themes` and holds the files' values, not themes: the mapping is code, so it
changes without regenerating, and a test reproduces the committed file byte for byte where
Omarchy is installed. The mapper raises on a missing anchor; tolerance lives in the reader,
because that is where the mid-switch window is.

**The persisted choice names the provider, and "system" names none on purpose.**
`appearance/theme` is `"system"`, or `"<provider id>/<theme name>"`; a bare name from
before providers existed reads as the built-in's, so no migration pass was needed.
`"system"` means *this machine's* desktop, served by the first following provider in the
root's order that applies here, so a profile keeps following when the desktop under it
changes — and **absence means system**: a fresh install picks the right variant for its
desktop by itself, and falls back to the built-in default where nothing follows. A choice
naming nothing here resolves to the default for this run and is never written back; only
`set_theme` writes, so a profile carried to another machine is still itself when it comes
home. What is honoured is a field on the service (`effective_choice`), so a check mark
costs two strings and no state callback ever reads a file.

**The service polls; providers stay Qt-free.** `ThemeService` re-reads the serving
provider's `current()` on a `QTimer` at the workspace watcher's cadence, only while a
following provider serves the choice, and applies on `!=` — never `is`, since a provider
rebuilds its `Theme` on every read, and an identity check re-applied a whole style on
every tick. One mechanism for every following provider: a `QFileSystemWatcher` on
Omarchy's theme directory would die with it (`omarchy-theme-set` removes and replaces it,
then writes `theme.name` in place), and Qt's `colorSchemeChanged` would hear the
application's own writes. A read that lands mid-switch answers None and the service keeps
what it has; a tomllib parse of a 600-byte file every two seconds is fifty microseconds.

**Following means no colour-scheme override.** Qt answers `colorScheme()` with the
application's own override once `setColorScheme` has run — `Unknown` does not clear it,
`unsetColorScheme()` does — so a desktop provider would read an echo. `apply_theme(...,
follow_system=True)` therefore clears the override, `set_theme("system")` clears it
*before* it asks, and availability is judged on the reading taken in `theme_providers()`,
before any theme is applied. Wherever following happens the desktop and the theme agree
by construction — Omarchy sets GNOME's scheme to its theme's mode on every switch, and the
desktop provider's polarity *is* the OS's — so the title bar never disagrees with the
window. A fixed theme sets the override to its polarity, as before.

**The menu entries are specs, and a child menu may nest.** Every theme is an
`ActionSpec` rather than a row of a `DataMenuSpec`, against the rule for data-driven
child menus and on purpose: the command palette lists a spec and never a data row, and
*Tokyo Night* one keystroke away is worth more than a list that refreshes while the window
runs — a theme added under `~/.config/omarchy/themes` meanwhile appears at the next start.
Long lists sit one level down: `submenu` accepts a path (`"Theme ▸ Omarchy"`), and both
presenters walk it, creating each level at the first spec's position — the bar computes a
nested child's visibility before its parent's, and the popup's group bookkeeping is per
container. View's `theme_system` and `theme` groups both feed the Theme child menu, so the
rule between *System theme* and the picked themes is drawn inside it. A provider that
does not apply here, or that the person switched off, contributes no entries: absent from
this machine is the one case *hidden* is for. `modules/appearance/` owns View ▸ Theme and
Settings ▸ Appearance, where every provider is a switch with its capabilities under it —
and its reason, greyed, where it does not apply — except the built-in, which is a line,
since a switch that cannot be turned off teaches nothing.
