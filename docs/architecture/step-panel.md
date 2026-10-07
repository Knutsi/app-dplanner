# Step panel — aspect toggles, the shelf, Details blocks, prose editors and assets

The reasoning behind `.claude/rules/step-panel.md`: the rules there are the short, imperative
form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## How a panel gets editors it has never heard of

The step detail panel shows a Details tab first — estimate, description, figures — and a tab
per remaining aspect — Ticket, Agent, Milestone — and nothing in it knows any of them exist.
Two seams do that, and they are worth naming because they answer every "feature A needs
feature B" question this application will have.

**Nobody hosts the panel.** `step_properties` owns it, and `steps.details` is where it
appears; what it shows is the step the verb was run on. No view declares a Protocol for it
and none is handed a factory: the Protocol-plus-factory shape is the right answer when one
module needs a *widget* from another, and it is not the answer here because the answer to "how
many are there" is one. (*decisions.md* has what it replaced.)

**A registry for the contributors.** Aspect modules register an `InspectorSection` into
`services.inspector_sections`; the panel reads that registry when it is *built*, not when the
modules load, so a contributor's position in the composition root is free — its position
*ahead* of `step_properties` is not, and the root says so.

The composition root is the only place that knows both, and the two panel modules need no
wiring between them:

```python
step_properties = StepPropertiesModule(
    StepPropertiesDeps(..., sections=services.inspector_sections)
)
canvas = CanvasModule(CanvasDeps(..., panels=services.panels))
projects = ProjectsModule(ProjectsDeps(..., open_project=canvas.open))
```

**Where provider-and-Protocol is the answer.** The order view's start-date bar is that
shape, and it holds there and not here because the two questions are different: a *widget one
surface hosts* is not a *surface the window anchors*.
`estimation` provides a `create_start_bar()` and registers nothing for it, `step_order`
declares a `StartBar` Protocol of its own and takes a `Callable[..., StartBar] | None`, and
the composition root is the only file that knows both names. Why a `create_…` rather than a
registry entry is worth stating too: a registry is for *whoever turns up*, and this control
belongs to exactly one surface. When there is only one host, a registry is ceremony that hides
which module supplies what. (This is Writer's arrangement, borrowed wholesale — its
`segment_properties` serves a corkboard, a segment editor and a continuous editor the same
way, which is the evidence that the shape survives a second host and a third.)

**What the panel is not.** The project's name and summary are not a section. An
`InspectorExtension`'s whole contract is `show_target(step_id | None)` — one target vocabulary —
and making the project form a peer of the aspects would force every aspect editor to answer
"what if this is a project?" and hide itself — a second target vocabulary smuggled into every
editor. (`shown_for` is not that: it hides a section per *step*, inside the one vocabulary.)
It is the Project dialog's own header instead — *A project's forms live in its dialog*.

## The step editor is a modal

`steps.details` puts a `StepPanel` in a dialog, and that is the **only** place a step's
aspects are edited — never a panel anchored in the window's right area following the
selection. (*decisions.md* has when it was both.)

**What an anchored seat would cost.** A step's aspects are a page of tabs — Details, Ticket, Docs,
Tests, Covers, Agent, Feature, Milestone, GitHub — and a page of tabs in a 360 px column is an
editor in which nobody finishes a sentence: the tab bar already needs scroll buttons and
elided labels to hold nine, five of the aspect bar's ten toggles fold into its `…`, the Tests
tab's list and its editor stack instead of sitting side by side, and every prose field is a
slot. The dialog is 900×850 and has none of those problems. Worse, the panel *competed*: it
appears on a selection, so working down a Tests roster put a step editor above the Test panel
the reader had actually opened, answering a question nobody had asked with the aspects of the
step the test happened to hang off. Two editors of different things in one column, and the one
somebody summoned underneath.

**The gesture is the one every view already has.** Every view's double-click on a step runs
`steps.details` (`CLAUDE.md`), and the surface has that one host. The dialog never reads
the context: it is opened *about* a step and stays on it, driven by `show_step` directly,
which is what lets a table row open it for the row under the cursor even when that pane's
publish was suppressed. It carries no buttons but Close: every edit inside it is already
applied and already on the undo stack, so there is nothing to confirm and nothing to cancel.
It is also where a fresh step is configured — New and the canvas double-click open it on the
step they just made, with the name field focused and selected.

**Why the dialog is not a breach of "one panel, not one per tab".** That rule forbids a panel
*per surface*, where N tabs meant N copies on screen at once. The dialog is one transient host
the user summoned, disposed when it closes, and building a second stack of extensions is the
section contract's sanctioned use — one extension instance per host — which the project
panel's cards had already proved. A test drives it the way the application does, through the
`step_editor` fixture, because there is no anchored panel left to reach for.

**The Details tab hosts the same contract, as blocks.** The first thing a step should show —
what it is, how big it is, what it looks like — is one tab, not an Estimate tab and a
Description tab each a click away. A module that wants its editor on the first tab
registers an `InspectorSection` into `services.step_details`, the registry's third
instantiation, and `step_properties` contributes one ordinary section labelled "Details"
whose extension (`modules/step_properties/details.py`) stacks the blocks: a caption from
each section's `label`, the widget under it, and the section's `stretch` deciding who gets
the leftover height — the description says `stretch=1` and takes the room, the estimate
stays a compact row, the spec module's read-only Figures gallery appears only on a step
that carries attachments (`shown_for`, re-asked on model changes exactly as the panel
re-asks it for tabs). Why a third registry instance and not a `placement` flag on
`InspectorSection`: a host is addressed by *which registry you register into*. That keeps
each host's vocabulary greppable, spares every host from filtering every section by a mode
field, and is the same reasoning that made `project_settings` a second instance rather than a
`kind` — three hosts, and the dataclass has no idea. Because the composite is just a
section, any host of the panel renders it for free.

**A block host owes its stack a trailing stretch and a cap on the rest.** `stretch` on the
section says who gets the leftover height — the description, which is what a step's prose
wants and the estimate's spin box does not. When that block is hidden its stretch factor
can claim nothing, and Qt falls through to a rule nobody wrote down: a `QWidgetItem`
reports itself *expanding* when the widget's own layout is expanding, whatever the widget's
policy says, and every block's layout is expanding because a block adds its content with a
stretch of its own. So with the description off, the surplus was spread equally over the
blocks that remained — a 42 px name block became 328 px, its caption and field sinking to
the foot of it, an inch and a half from where the eye expects a field under its caption.

The fix is two halves, and either alone is wrong. A trailing `addStretch(0)` gives the
leftover somewhere to go; at a factor of **1** it would instead split that leftover with the
description block and halve the prose editor whenever the block *is* shown. And
`QSizePolicy.Maximum` on every block whose section declared no stretch takes away the
GrowFlag that was promoting it behind the data's back — which is the real statement of the
fix: **the cap is what makes `InspectorSection.stretch` authoritative.** Without it the
declared stretch is advisory and Qt's propagation decides, which is why the bug read as
arbitrary. `Maximum` rather than `Fixed`, so a panel shorter than its blocks still
compresses rather than clipping.

## A markdown toolbar is verbs over a selection, and one splice each

Every prose document here is markdown kept as plain text, which is the right trade for
the binding (*A pasted image is an attachment and a link*) and leaves the marks themselves
to be typed. Most are two characters and nobody minds. The ones people stop writing rather
than type are the ones that are tedious in proportion to what they mark: `**` around a
phrase already selected, a `- ` down eleven lines, a table's pipes and dashes. So those
become verbs, and `framework/markdown_toolbar.py` is the strip.

**Dense and un-banded**, against DESIGN.md's own mapping of a tool palette to
`Toolbar.add_group`. The measurement decided it: a banded strip's buttons are squares, so
twelve verbs in three bands come to roughly 450 px, and every `ProseSection` in the
application lives in a ~360 px dock — *Insert* would have folded into the `…` on every
surface, and often *Blocks* too. Dense seats them in about 330. It is the aspect bar's
argument with the same numbers: a strip that answers a question about the thing on screen
stops answering it when it folds, and a formatting palette that is never all there is not
a palette.

**A verb is one splice, and that is not a detail.** Qt reports `contentsChange` per edit
*block*, so two operations inside a `beginEditBlock` collapse into a single signal naming
the whole document — measured at `(0, 23, 26)` where one contiguous replacement reported
`(12, 6, 10)`. A `TextBinding` host would push an `EditTextCommand` carrying the entire
document twice for a bold. So every verb is a pure `Splice` — start, end, replacing text,
and what to leave selected — applied in one `insertText`, sealed either side the way
`ProseEdit._embed` seals a pasted link.

**Where the selection lands is the design**, and it is one rule: a verb leaves selected
whatever a second press of the same verb would act on. Bold leaves the bolded words, so
pressing it again unwraps them; Heading 2 leaves the lines; Link leaves `url`, because
typing the address is what you do next and a prompt for it is more ceremony than the two
brackets it saves. With nothing selected a wrap puts the caret between its fences, so
Ctrl+B and then typing works the way it does everywhere else.

**The keys belong to the editor, not the strip.** `Toolbar.add_verb` gained `keys=`
beside `shortcut=`: the first only prints the key in the tooltip, the second claims it.
A strip lives in a window, so a `QAction` shortcut on it fires wherever that window has
focus — the same fact as *A canvas key names action ids; it is never an
`ActionSpec.shortcut`*, from the other side. The verbs' keys are `QShortcut`s on the
editor at `WidgetShortcut`, which is what the spec editor was already doing for Ctrl+B
before any of this.

`ProseSection` builds one unconditionally rather than behind a flag. It is what a prose
editor *is* here, the same way the highlighter and the expand button are; a flag would be
a decision every host had to make again, and none of them has a reason to answer it
differently. The microphone arrives the same way — with the strip, wherever a host hands
the strip a `DictationService` (*Dictation is a provider, and capture is a peer process*).

## Expanding an editor is a second binding, not a copy

A side panel gives prose a few hundred pixels, and some descriptions and instructions are
screens long. The expand affordance (`framework/text_dialog.py`) opens the same document in
a modal editor sized to the screen — and the mechanism is the whole point: the dialog holds
a second `TextBinding` over the *same* `TextField`, nothing else. Each binding treats the
other's commands as foreign changes — the exact path a CLI edit or an undo already travels —
so the inline editor tracks the dialog keystroke for keystroke, one undo stack serves both,
and closing the dialog can lose nothing because nothing ever lived only there. The
alternative — copy the text out, edit, copy it back on OK — would have invented a second
place where prose lives and a Cancel button that discards work, both of which the binding
discipline exists to prevent. The affordance is a small corner button `attach_expand` pins
onto the editor itself, so every host — the Description block, the Agent tab's two
instruction editors, the Project dialog's two prose tabs — offers the same gesture without
growing a header row.

## A pasted image is an attachment and a link, not an embed

Every prose document in the application is markdown kept as **plain text**, and
`framework/markdown_highlight.py` says why: a rich-text widget (`setMarkdown`/`toMarkdown`)
edits a document *tree* and writes back a normalised serialisation, so a keystroke stops
being the one small splice `TextBinding` needs. That decision has a consequence nobody had
paid until somebody pressed Ctrl+V: a `QPlainTextEdit` cannot show a picture. So the editor
does the half it honestly can — the file is content-addressed into the module's file area
and `![alt](assets/…)` is typed at the caret — and the gallery under the editor renders the
thumbnail. The spec module's editor is a `QTextEdit` and embeds instead; that is the *only*
difference between them, and it follows from the binding, not from taste.

**Typing the link is the whole implementation.** Going in through `textCursor().insertText`
makes it an ordinary edit — `contentsChange` → the field's command → the undo stack → every
other view bound to the same document — so the expanded ⤢ editor tracks it keystroke for
keystroke and Ctrl+Z removes it. Nothing new was plumbed for any of that. What *did* need
plumbing is the opposite: the link must not merge into the sentence being typed.
`EditTextCommand` coalesces an append at exactly the caret, which a paste always is, so one
Ctrl+Z would have taken the prose with the picture. `ProseEdit` seals the step on both sides
of the insert — `UndoService.break_coalescing`, the same call a focus change already makes.

**The write itself stays off the stack**, as `FORMAT.md` requires: undoing a paste must never
leave prose pointing at a file that had gone. An orphaned blob is recoverable; a dangling
link is not.

**The editor does not write the file; it is handed an `Attach` callable.** Attaching is three
steps — resolve the area, write, redraw the thumbnails — and `AssetGallery.attach_bytes`
already does all three, including answering in words for a node autosave has not flushed yet.
An editor that only did the middle step would put a pasted image on disk with no thumbnail
beside it and would need a second answer for the unflushed case. One callable buys both.

**The area is aimed by a call, not by another `…_for` callable.** `ProseSection.set_area` is
made by the host from its own `show_target`, because the node a document is *keyed by* is not
always the node its *files* live beside: a test's body is keyed by the test, and a test's
images belong to the step — which is where `dplanner test attach` has always written them.
A `Callable[[str], AreaFor | None]` would have handed the testing pane a test id it must
discard, and that is the kind of seam that reads correct and is wrong.

**A text widget's standard menu is not a `build_menu` menu.** `CLAUDE.md`'s rule that a
right-click renders a menu named in `MENU_STRUCTURE` is about menus of *application verbs*.
`Insert Image…` acts on one widget's caret, means nothing without one, and would be a
permanently disabled entry in the palette and the menu bar — the state *Hidden means absent;
disabled means not now* above reserves for a verb whose precondition the user can still meet,
which this one never could. So it is appended to Qt's own `createStandardContextMenu()`,
exactly as the spec editor's formatting verbs are methods rather than `ActionSpec`s.
Overriding `canInsertFromMimeData` is not decoration either: Qt's own answer for image-only
clipboard data is False, which greys **Paste** in that same standard menu — on the one thing
here that most wants pasting.

## An asset library is a view, not a store

The Assets tab looks like a place where files live. It is not — it is a *derivation*, and
that was the decision that shaped everything else about it. Every file stays where its
aspect put it, in the per-(node, module) areas `store.files()` hands out; what the tab,
`dplanner asset list` and `asset prune` share is `domain/assets.catalog()`, one walk over
every contributed `AssetSource`, computed on each read and never written down.

**Why no central blob directory, when one was the obvious design.** Three costs, each
structural. Every prose surface resolves `assets/<sha>.png` against *its own module's
area* — the paste path, the lint, the agent briefing, the spec viewer all share that one
convention — so a central store means either rewriting links in every existing project's
prose (undoable state, churned by a storage decision) or two link forms with two
resolution rules forever. A node's directory would stop being self-contained: deleting a
step currently takes its files with it and undo restores the graph exactly *because*
nothing outside the step was touched — a shared store would need reference counting as
core machinery, which is the exact complexity the blob/link split in `FORMAT.md` exists to
avoid. And centralising would not even buy the feature: "what uses this file" is a
question about *prose*, so the scanners are needed either way. The storage cost of copies
is near zero — git's object store is itself content-addressed, so identical bytes at five
paths are one blob in history.

**Reuse is therefore a copy.** Picking an existing asset into an editor copies the bytes
into the target's own area through the ordinary attach path — `spec attach-to-step`'s
`copied_to_step` generalised. Content-addressing makes this cheap and makes it *legible*:
identical bytes carry the same `assets/<sha16><suffix>` name in every area, so the catalog
groups by name and one row honestly means one image, wherever it lives.

**Rename-safety is structural, and a name is metadata.** A link can never break on rename
because the name *is* the content; what a person calls the image is a display title in the
browser module's own `module_data` beside the project, keyed by content name — one title
covers every copy, written through a command, undoable, and never part of any link.

**What "used" means is each source's own claim.** A description image is used while the
markdown links it; a test image while any test body does (archived included — evidence
outlives the roster); a spec figure while the index, an attachment record or a markdown
body names it. A documentation image is used project-wide by *name*: a compiled document
renders images from its source steps' areas (`framework/markdown_view.py` asks each in
turn), so a fragment's image may be needed by a collector's compiled text long after the
fragment dropped it — content-addressing makes the name-match exact, not a heuristic.
Instruction files are used *by existence*: the area is handed to agents wholesale, so an
unreferenced file there is payload, not litter; a note's file is used while a note's body
links it, and `note attach` writes the link as it copies the file in. The pool
is `prunable=False` — a staging shelf swept for being a staging shelf would punish the
workflow it exists for. `asset prune` deletes per *location*, only what its own source
called unused, dry-run first, and never enters a directory no source scanned — which is
also why a retired module's leftover area is invisible to it on purpose: unknown data is
carried, never cleaned (the same tolerance unknown edge kinds get).

## Inserting an existing asset is a paste with a different source

`Insert from Assets…` plumbs nothing new. The picker (`framework/asset_picker.py`) answers
in `Payload`s — bytes and a filename, never a path — and `ProseEdit._embed` does to a
picked payload exactly what it does to a dropped one: the host's `Attach` copies it into
the editor's own area, the link is typed at the caret, the undo step is sealed on both
sides. Payloads rather than paths is the load-bearing choice: a path handed across that
line would become a link into somebody else's directory, and the copy-by-value rule above
would quietly stop being true.

The picker itself is framework, not module: three hosts wanted it on day one (description,
test bodies, both agent instructions), and it knows nothing but titles, details and byte
readers — the same test `asset_gallery` and `image_preview` passed. The *catalog* it shows
cannot live there (the framework never imports modules), so the composition root composes
the one `pick_assets(node_id)` closure — resolve the node's project, run `catalog()`, join
the display titles, open the dialog — and hands it down each host's `Deps` as a typed
callback. `ProseSection.set_picker` is `set_area`'s sibling, aimed from the same
`show_target` for the same reason: the node a picker serves is the node the files land
beside, and only the host knows which that is.

## Status is an aspect, and step types are emergent

There is no `type` field on a step, and none is coming. A *milestone* is a step carrying the
`step_milestone` aspect; an *agent task* is one carrying `step_agent_instruction`; a step can
be both at once, which no exclusive type field could say. What a step "is" emerges from
which aspects have something to say about it — the same way its subtitle on the canvas
already does.

Status went the same way after being weighed as a model field. It is a stored fact, not a
derivation — the graph can say what is *ready*, but only a person or an agent can say what
is *finished* or *stuck* — yet storing it does not make it a field: `VALUE_FIELDS["step"]`
is still `("title",)`, and that is the central design decision of the model holding. As an
aspect it costs no project-format migration, absence encodes `pending`, both surfaces got
the verb from one declaration (`dplanner status set '<step>' ready-for-review` is how an
agent reports back), and the derivation that wants it — the status-aware frontier the Step
statuses tab reads —
is handed a `status_for(step)` function, because a wait's status depends on the day.

The one enum also shows where an aspect's GUI does not have to be a tab: status registers a
*Status* submenu of checkable Step verbs instead, and the canvas right-click, the order
table, the menu bar and the palette all grew it from that single registration. The canvas
never learned the vocabulary either — it renders a neutral `NodeAccent(muted, badge)`, and
the composition root translates "done" into muted and a milestone label into the badge.

**Six words, and one of them is where an agent stops.** *pending, in-progress,
ready-for-review, ready-to-merge, done, blocked*, in the order work moves through them. The
two in the middle came with agents doing the work: *ready-for-review* is the agent's work
finished with somebody — a person or a reviewing agent — to look next, and
*ready-to-merge* is accepted and waiting on its merge (*An agent finishes at Ready for
review*, below, has why an agent stops there). They are `planning/status.py`'s `Status`,
and every reader compares members, never words (*Planning owns status*). They cost **no
format bump**: an older build reads a word it does not know as `Unknown` and leaves the
entry on disk. It once read such a word as pending, and the structural review's probe showed
what that costs: an otherwise eligible agent step became due again, so a window on an older
build would relaunch work a newer one had claimed. Unknown holds the step instead —
`status.held` reads it as blocked, so the frontier skips it and
the board lists it with Blocked, and Run Agent refuses it, so no launch writes
`in-progress` over the word. Absent data is the only thing that reads as pending. `started` is
stamped the first time a step enters any *worked* status — in progress, under review or
waiting on its merge — because a step an agent ran without the claim still began when it
came back. And **a status verb acts on every chosen step as one undo step** (`chosen_steps`,
the same definition Delete and Run Agent read), is checked only when all of them already
stand there, and greys with its reason when a wait is among them — which is what lets the
Step statuses tab tick three reviews and accept them with one press.

The *Type* submenu is the same idea one step further: one checkable toggle per type-ish
aspect (Milestone, Feature, Agent, Ticket), each independent, because a Type radio group
would reintroduce the exclusive type field this section rules out. Toggling Milestone on
generates the next label from the project's existing ones (`next_milestone_label` in
`planning/milestone.py`, shared with `dplanner milestone set`); toggling any of them off
shelves what it held, so nothing asks and the next toggle-on brings it back.

**A tab follows its aspect.** An `InspectorSection` may carry a `shown_for(step_id)`
predicate; the step panel re-asks it on every target change and on model writes to the
shown step, and hides the tab (`QTabBar.setTabVisible` — indices stay stable, so the
tab-to-page mapping never re-shuffles) when the answer is no. Only on a change, and
followed by `updateGeometry()`: `setTabVisible` clears its own layout-dirty flag when
handed an unchanged value and lays nothing out itself, so a blanket loop leaves the strip
painting stale rects — the framework diary (`docs/history/`) §10 has the trap. Milestone, Agent and Ticket
answer with "does this step carry the aspect", so toggling one off removes its tab and
toggling it on brings the tab back *with* whatever the toggle generated — which is the
answer to the earlier worry that a generated milestone label needs somewhere to be edited:
it has one from the moment it exists. This deliberately reverses an older decision that
every tab is always visible; seven tabs on a step that is neither a milestone, an agent
step nor tracked anywhere taught nothing and buried the four that mattered. Sections
without a predicate (Estimate, Description, Handoff, GitHub) behave exactly as before,
and the Project dialog's tabs are exempt — they hold project-level facts no step toggle
should touch.

### Every tab follows a toggle, and absence encodes the default

The rule above started with five aspects and three exceptions: Estimate and Description were
unconditional blocks, Handoff and GitHub unconditional tabs. A milestone therefore came with
an estimate field for work it does not do, a description editor and a GitHub tab it will
never use — and "seven tabs that taught nothing" was the same complaint, one layer in.

So all four became toggles, and the mechanism was already written down: `FORMAT.md`'s
**marker entry**, the `{"on": true}` shape `step_ticket` and `step_check` use. No new store,
no format bump, and a fifth injection style avoided.

The part worth arguing about is which way absence points, and the answer is not the same for
all four:

| Aspect | Absence means | Because |
|---|---|---|
| Ticket, Check, Feature, Milestone, Agent, Tests, Handoff, GitHub | **off** | most steps are none of these; the marker records the claim |
| Estimate, Description | **on** | most steps are work, and work has a size and a name; the marker records the *opt-out* |

That is not two rules, it is `FORMAT.md`'s one rule — *absence encodes the default* —
applied honestly in both directions. The alternative was writing a marker at every step
creation site, of which there are four (two CLI, two GUI), and a module reaching into four
files outside its own package is exactly what the layering forbids. The inverted default
needs none of them: **existing projects change not at all**, every step keeps its Details
tab, and a milestone loses its estimate the moment somebody says so.

The Details tab *is* its blocks — and since the name is its first block (see *The aspect bar
renders the registry* below), it always has one to show, so it never asks whether it would
open onto blank space.

### Turning an aspect off shelves it

A Type toggle never deletes what the aspect held. Deleting after asking would be honest — a
toggle that silently destroyed a milestone label would be worse — but it would make every
toggle a small act of courage, cost a confirm dialog per aspect, and get in the way of the
gesture the toggles exist for: switching a step from one kind to another and back. So an
aspect turned off is **shelved**: its `module_data` entry and its `module_text` move to a per-node
entry under the domain's own id, `modules/shelf.json` beside the step, and `turn_on`
restores them before it would ever write a fresh entry.

The shelf is a *domain* concern, not a flag inside each module's entry, and that is the
decision worth recording. The alternative — every aspect storing `{"off": true, …its data}`
— would have put a new key in front of every reader: a briefing, a lint, the canvas subtitle,
`dplanner … show`, each learning to check the flag before believing the data, and each a
place to forget. With the shelf, the entry is genuinely absent (or, for the two aspects whose
default is on, replaced by their opt-out marker exactly as before), so *absence encodes the
default* still holds and not one `read()` changed. The shelf only remembers what absence
replaced. Two consequences follow and both are handled once: the migration pass reaches into
the shelf (`migrate_shelved`, beside `migrate_module_data` at both call sites), because
shelved data is a module's data at the version it was shelved; and the asset catalog counts
a shelved prose's links as uses, so `asset prune` never sweeps away a picture the next
toggle-on would bring back to. A module's file area was already left alone by a toggle.

Two builders are the whole vocabulary — `turn_off(step, module, leaving=…)` and
`turn_on(step, module, fresh=…)` in `domain/shelf.py` — and both surfaces use them: a GUI
toggle pushes the command, a CLI `clear` applies it, so `dplanner milestone clear` and Step
▸ Type ▸ Milestone are one behaviour. Every toggle is therefore one
`framework/aspect_toggle.py` factory: a module hands over its
`enabled` predicate, a `fresh` entry (a marker, or a generated milestone label, or one blank
test) and — for estimate and description — what to leave behind, and gets back the
checkable Step ▸ Type verb. The one soft spot, named rather than engineered away: a CLI
`set` on a shelved aspect writes a live entry and leaves the shelf's copy stale until the
next turn-off overwrites it. The shelf is never read while the aspect is on, so nothing
misreads; it is a few stale bytes, not a wrong answer.

### The aspect bar renders the registry, never a copy of it

The toggles live in Step ▸ Type, which is a menu, and a menu is not somewhere a person looks
when the question is *what does this step carry*. So the step panel wears an **aspect bar**
across its top — and the bar lists no aspects of its own. It reads the same specs the *Type*
submenu renders (`framework/aspect_bar.py`), through a context the host hands over, and
every button runs the owning module's toggle through `ActionRegistry.run`. So each stays one
undoable command, an aspect a build does not ship has no button, and adding an aspect is
still one registration in one package.

What the bar adds to the submenu is a *reading*. Its **left** is every toggle as a glyph.
Its **right** is one dropdown named *Template*, offering the named combinations: *Milestone*
is milestone and description, *Agent* is agent, description and estimate, *Step* is the
estimate and description every step is born with. One control rather than five, because only
one of them is ever true at a time: five worded buttons said the same thing five times and
four of them were always wrong. The face is named for what it **offers**, not for what is
on — which one the step amounts to is the ticked entry — so the bar makes one claim about
the step (the lit toggles) and offers one way to change it, rather than saying the same
thing twice in two vocabularies. Each entry's **glyph** wears its body tone, so a feature's
entry and a feature node are one identity (which is why the tones live in `theme/tones.py`,
where both can reach them) — the glyph and not a ground, because a template is *always*
selected and a wash that is permanently on says nothing, and a glyph needs no per-button
stylesheet. Picking a template
runs whichever toggles differ, on for its set and off for everything else, inside one
`UndoService.gesture`, so *Make Milestone* is one Ctrl+Z however many aspects it moved and
each is still the owning module's own command — the gesture is the framework's answer to
"one gesture, several verbs", and it is what let the bar stay a presenter with no command
of its own. And it goes both ways: a template reads as selected exactly when the step
carries its set and nothing else, so a combination somebody built toggle by toggle lights
up the template it amounts to, and one extra aspect puts it out — onto *Step*, the
catch-all (`AspectTemplate.catch_all`), because a step with an unnamed combination of
aspects is still a step and a bar with nothing lit would be saying it is nothing. Nothing
stores which template is current; it is a set comparison on every refresh, which is the same *derived,
never stored* rule as the ordering. Which templates exist is `StepPropertiesDeps.templates`,
named by the composition root in the order the bar shows them, for the same reason the
scope kinds are wired rather than inferred.

The strip is `framework/toolbar.py`'s `Toolbar`, so what does not fit is taken off from
the right and listed in a `…` menu as glyph **and words** — where Qt's own `»` pops the
hidden buttons up as glyphs again, which is no help to somebody who could not read the
glyph on the strip. It is **dense**, a mode the primitive offers: a strip of verbs folds
gracefully because losing a verb to a menu costs a click, but this row answers *what does
this step carry*, and a row that folds stops answering. The panel cannot be narrower than
479 px — its tab pages, not the bar — which leaves the strip about 356; at the verb strip's
45 px buttons that seats five of the ten toggles, and at the dense 29 px it seats all ten.

And the dropdown sits **beside** the strip rather than on it. A widget added to a `Toolbar`
hides when there is no room for it, so the one control naming what the step *is* would be
the first casualty of a narrow dock — the canvas's layout picker and the *Updating…*
indicator sit outside their strips for exactly that reason. It is also why the face is
named once and left alone: a face whose words changed with the step would re-fold the strip
beside it every time a toggle moved. The kinds are the summary and the facets are the
detail, and it is the summary a narrow dock should keep.

The bar is always on show rather than a list summoned from a "+" beside the tabs, because a
list you have to summon is a poor way to see what a step already is. It settles **"some step
types can never
carry this aspect" needs no mechanism at all**. A toggle whose `state()` returns
`ActionState(enabled=False, label="Estimate — a milestone has no work of its own")` renders
as a greyed button carrying its reason in the tooltip, because *hidden means absent; disabled
means not now* already says so. Nothing was built for it; it is one predicate away when it is
wanted.

The context arrives as a function rather than a `ContextService`, which is what lets the
panel inside the details *dialog* — showing a step nobody selected — hand over one naming
its own step. The specs cannot tell the difference, and neither can they be made to care.

Two smaller rules. A toggle's `state()` **never returns
`visible=False`** — *hidden means absent; disabled means not now* already says a toggle
that cannot apply is greyed, and an aspect a build does not ship never reaches the registry
— so the bar's state is a pair, enabled and checked; a strip that re-shows whatever fits on
every reflow could not have honoured it anyway. And the bar **announces its refresh**
rather than leaving a host to listen to the model: the dialog's lead repeats the bar's
answer in words, and applying a template ends with the bar refreshing itself, which is
after the last write any model listener hears. A host that watched the model showed the
lead one gesture behind.
The panel re-reads the bar on every model write to the shown step, because one toggle can
change another's state.

The name is the first block of the Details tab, not a field of the panel's own above the tab
bar: `step_properties` registers it like any other block at order 0, so the modal's control
stack reads top-down from the one field every step has — and the Details tab, having a block
that always shows, never asks whether it has one.
