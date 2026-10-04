# Persistence — save, two writers, outside changes, reload and repositories

The reasoning behind `.claude/rules/persistence.md`: the rules there are the short, imperative
form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## A project's forms live in its dialog

A project has a handful of things a person edits about it rather than about any step: its
name and summary, where its plan and its code live, the standing instruction every briefing
opens with, and the instructions every compiled document follows. They are the tabs of
*Project ▸ Settings…* — the Project dialog (`modules/projects/project_dialog.py`), whose
first tab, **Repositories**, is its own, and whose others are whatever registered into
`services.project_settings`.

**One host says each fact once.** The dialog already holds the project's name, summary and
Locations table, and reads `plan_in_code` and `warns` for its warning and its set-up offer;
a second surface for the same project would word each of those facts again. So the host
that has the facts, the name and a Close-only footer also takes the prose editors.
(*decisions.md* has what it replaced.)

**The registry survives, because the contract did.** Two modules still have something to say
about a project, and neither should learn about the other or about the host: a registry is for
whoever turns up. `project_settings` is an `InspectorSectionRegistry` like the step's tabs and
its Details blocks, named after its host as `step_details` is, with a project id in
`show_target`. A provider-and-Protocol handover from one module to the host answers only while
one module has a project surface; the moment a second wants one, "whoever turns up" is the right
question. The dialog builds one extension per section when it is first built — on first use,
after every module has registered — so a section carries no registration-order rule. A section's
`hint` is its tab's tooltip; `stretch` means nothing to a tab host.

**One dialog per window is re-aimed, so the aim is guarded.** Every *Settings…* calls
`show_project`, and `ProseSection.show_target` rebinds whenever it is called, which throws
the caret to the start. So the tabs are aimed only when the project changes — an
unchanged-id guard, which any host that is re-aimed needs. A context republished mid-typing
reaches nothing, since the dialog reads no context. And because the dialog outlives a
visit, **leaving it seals the undo step** a prose tab was growing (`hideEvent` →
`break_coalescing`): a text edit merges by field and
time, not by who typed it, so the next visit's typing would otherwise grow the last one's
step. `dispose()` lets go of the model before a dialog is deleted — New Project's create
dialog calls it too, so its subscriptions never outlive it.

**The project row only selects its project.** A row that opened a tab would open one for every
glance at the index. Every Project verb, *Settings…* among them, acts on it from the menu bar
and the row's right-click; the Steps row opens the graph; a double-click still folds the row
(Qt's behaviour, not fought). What shows while no tab is open is the window's to decide, not any
one project's — a blank window, with Home opened only at the program's start (*Home is where a
window starts*). The rule is `.claude/rules/step-panel.md`'s project-level editor bullet and
`CLAUDE.md`'s panel bullet.

## Two writers, one folder

The scenario DPlanner is built for — an agent refining a plan *with* the user — means the
CLI writes while a window is open on the same folder. The framework's ordinary contract,
"memory is authoritative and disk follows", quietly loses data under those conditions: a
flush 1.5 seconds after the user's next keystroke rewrites nodes from a model that never saw
the agent's edit, and orphan removal deletes a directory the agent just created.

A lock would be the cheap fix and it is the wrong one, because both writers being live *is*
the feature. So the rule is instead:

> **Nothing writes over a file it has not seen.**

`LibraryStore` records what each project directory looked like when it last read or wrote
it and raises `StaleWorkspaceError` rather than flushing over anything that changed
underneath. The check is **per project** — flush verifies exactly the projects it is about
to write, so an agent editing project B never blocks saving project A, and the refusal
names the project. The library file is a third written thing with the same treatment under
its own stamp, because two instances can both add a project; membership reaches disk
through the ordinary flush, as a structure mark on the library root. **A stamp says what
was seen, so it is taken before the read and never over a change this store did not take
in**: `load` and the adoption stat the file before reading it, and `set_checkout` — which
writes one key straight into the file outside the flush — re-stamps only when the file was
already as last seen. Its old unconditional re-stamp hid another writer's new project from
the watcher, and the next membership flush wrote that project out of the file (the
structural review's probe, `tests/domain/test_store_adoption.py`). Around that one check:

- A **CLI run** reports it as one line and writes nothing. A run is a transaction, so
  running it again picks up the change and is correct.
- A **window** takes the change into its live model, entry by entry — the next section —
  and a flush that was refused is retried once the folder has been seen.
- A **window that changed the very same entry** and has not flushed it stops on that
  entry: autosave keeps its marks and pauses itself, and a modal makes the choice the
  user's — an agent, theirs, ours, or later. Nobody else can make that call.

The same check is why **two CLI runs need no lock between them**: the second is refused for
exactly the same reason and can be run again. One mechanism, three cases.

### Adopting the other writer's changes in place

The simple answer to an outside change is the whole rebuild: `AppSession.reload()` builds a
second window, shows it, and discards the first. Correct, and visibly a close-and-reopen —
the undo history, the selection, the canvas viewport, the caret, split panes and open
dialogs all go with the discarded build, and an agent running five CLI verbs in a row would
rebuild the window once per two-second tick. So the rule is the one above with a second
half:

> **Nothing writes over a file it has not seen — and nothing rebuilds over a model it can
> still reconcile.**

`LibraryStore.adopt_outside_changes` is the reconcile, and it is possible because of four
things the format and the model already were:

- **The stamp is per file, and a plan file is one entry of one node.** `project.dproj` is a
  project's title, summary and child order; `steps/<slug>/step.json` a step's title and
  edges; `modules/<id>.json` one module's data; `modules/<id>.md` one module's prose; a step
  directory a node. The diff between what was last seen and what is there is a set of paths,
  and `_classify` turns each into *which node, which entry*. Nothing else is compared, so a
  re-read of a fifty-step project touches the entries the agent wrote and no other.
- **Identity is the id.** A fresh read of the project is matched to the live one by uuid,
  through the same `_load_project` opening uses — on the record's own provider, so a tick is
  a file read and never a git subprocess.
- **Every mutator takes an origin, and every view treats an unknown one as "repaint".**
  Adoption calls `set_field`, `set_edges`, `set_module_data`, `apply_text_edit`,
  `add_child`, `remove_child` and `reorder_children` with `OUTSIDE_ORIGIN`; the canvas
  reconciles by key, the step panel drops a vanished step, the index rebuilds. No view
  learned anything.
- **A prose edit is positional.** A whole-document `describe set` arrives as
  `diff_hunks(live, fresh)` applied highest position first, so `TextBinding` splices each
  hunk through a `QTextCursor` around the user's caret. One replacement from position zero
  would have collapsed the caret to the start.

Three decisions inside it:

- **Mutators, not commands.** Adoption never pushes and never undoes; a command's only
  extra over the mutator is the before-state it keeps for undo, which nothing would use.
  Membership already applied the mutators directly with `LIBRARY_ORIGIN`; this is the same
  case. *Syncing an external fact* below is the third writer that bypasses the stack, and
  the reasoning there — the stack is the GUI user's journal — is the reasoning here.
- **Dirty is muted while adopting.** A change read off disk is not something to write back:
  forwarding it would have autosave rewrite the agent's file 1.5 s later and race the
  agent's next run into a `StaleWorkspaceError` of its own.
- **A conflict is per entry, and the store knows it.** Autosave's `(owner, aspect)` marks
  say a step's module data is dirty, not *which* module's — too coarse to tell a local
  estimate from the agent's status on the same step. So the store keeps `_unflushed`, fed
  from the typed signals (which carry the module id) and cleared per entry as flushes write.
  An outside change to an unflushed entry is reported as a `Conflict` and left alone, its
  stamp kept old so that project's flush is still refused; `take=` adopts it (theirs),
  `mark_seen` counts it seen (ours). A step with any unflushed entry that disappeared on
  disk is a conflict too, not a removal.

And the boundaries: a project whose read is inconsistent — a torn JSON, a snapshot that
moved during the read — is **deferred** to the next tick rather than adopted half-written,
which is what the strict read exists for (the tolerant one that opens a library would take
a torn file for an emptied node); a torn *library file* likewise, or every project would
read as departed. A pending format migration, or any failure halfway, sets
`rebuild_required`, and `SessionControl.refresh` falls back to `reload()`: the rebuild is
still correct by construction, it is just not the first move. The watcher does not hold off
while this window owes a write — a flush re-stamps as it writes, so our own files never read
as foreign, and the conflict rule answers the case such a guard would exist for.

**The undo history survives an agent's edits and is dropped by a branch switch.** An entry
that names a step the agent removed, or prose whose positions moved under adopted hunks, is
refused by the model when undone; `UndoService` drops that entry and the redo tail after it
rather than leaving the pointer past a still-applied command. A checkout or a pull replaces
the tree wholesale, so its refresh passes `forget_history=True` and the stack is cleared —
only when something was actually taken, which is why New Branch, which changes no plan
file, keeps it.

**An undo never overwrites a value somebody else wrote, and a composite never stops half
way.** `SetFieldCommand`, `SetModuleDataCommand` and `SetEdgesCommand` remember what their
redo left in the model — read back, since `set_edges` de-duplicates and `set_module_data`
keeps the caller's dict — and refuse with `ValueError` when an undo finds anything else
there; a replayed redo refuses the same way when the value is no longer what its undo put
back — otherwise undoing a rename would restore the old title over the agent's newer one,
and nothing would say so. The refusal reaches `_drop_from` like the two above, so the user's history
before it stays usable. A refusal inside a `CompositeCommand` — or a gesture the stack
recorded — reverses what the composite had already applied and then goes on, so the model
is either wholly before the gesture or wholly after it; a composite that half applied
before the stack dropped it left a graph neither surface had asked for (Codex's probes,
structural review §11). Text undo needed nothing: `apply_text_edit` already refuses a
removal that does not match.

**The conflict modal hands the merge to an agent** because the user asked for that over a
banner. `modules/library_watch/` names the entries and the agent module writes the window's
version of each into the run directory (`mine/<path>`) *before* the window yields to the
plan on disk — the run directory is the one place the unsaved version survives. The prompt
(`conflict_prompt`) points at both, asks for a merge written back through the owning verb,
and ends with `agent-state clear`; no worktree, because the agent must write to the
checkout the window shows. The launch is the ordinary one, so the run is tracked on the
step like any other — chip, ring, Agents browser — and the merge arrives as an outside
change. *Later* leaves a status-bar button that reopens the question; *Keep Mine* on a step
the agent deleted writes back only what this window changed, which is the honest reading of
"mine".

What the check *looks at* is the plan, not the directory. A project directory is often
the repository root itself — New Project's git-init flow makes exactly that — and then the
directory holds the user's source tree, `.git/` and the worktrees Run Agent keeps under
`.dplanner-worktrees/`. None of it is anything the store reads or writes, and a snapshot
that walked all of it made every source edit, every Save and every file an agent touched
read as "another writer" and reload the window. So `LibraryStore._snapshot` walks
`PLAN_ENTRIES` — `project.dproj`, `modules/`, `steps/` — which is exactly the set a flush
could overwrite, and therefore the only set the question is about.

### An agent at work says so, and the window says it back

Everything above makes the *mechanics* of two writers safe: the change lands, nothing is
overwritten, a collision is put to the user. What none of it does is make the other writer
**visible**. A developer with a window open sees a graph quietly rearranging itself and,
the first time they type into a step an agent is also rewriting, a modal asking them to
settle a collision they had no way to see coming. The mechanism was right and the
experience was of being ambushed by a tool that knew something it was not saying.

So the agent says it. `dplanner agent-work start '<what I am doing>'` writes a **claim** —
project, optionally a step, one line of prose, optionally the agent's own count of what it
is working through, when it started and when it was last heard from — and
`modules/agent_at_work/` stands one notice for every claim below the window's content while
any stands. Six decisions carry it.

**Silence lapses, and the next sign of life undoes it.** This was the whole design question. A
heartbeat the agent must remember is a heartbeat it will forget mid-task; a pid is a process the
announcing `dplanner` run does not own — its parent may be a shell that lives for the session or
one that exits with the call, and nothing can tell which. A quiet claim that only changes tense
(*was at work … last heard 40 minutes ago*) and stands until somebody who knows something ends
it is the wrong way round: agents finish and stop without a word far more often than they think
for an hour, so the window collects bands from agents long gone, and a banner that is usually
stale teaches the developer to read past the one surface they must not. So a claim not heard
from in `FRESH_MINUTES` (three) **lapses**: `AtWorkBoard.claims()` stops returning it, and the
window, `agent-work show` and the library watcher all stop saying it at once. What makes a lease
safe here, where the usual objection is that it is too short, is that **a lapse deletes
nothing**: the file stays until the day-old sweep, and the agent's next `dplanner` run renews
it, so it stands again. That run is exactly the moment it matters — an agent that is not
touching the CLI is not touching the plan either, and the banner exists to keep a person off the
plan while an agent writes it. The lease began at thirty minutes and was still the wrong way
round in use — bands stood long after the work had finished — so it is three: a quiet agent's
band may drop out between two runs and come back with the next, which costs a person nothing,
where a stale one teaches them to stop reading. The tense went with it: one threshold where
there were two, and every standing claim reads *is at work*, with when it was last heard said in
its own words. It goes for good four ways — the agent ends it, `status set` says its step is
finished (below), a person clears it, or a claim made a day later sweeps it.

**Every `dplanner` run is the sign of life, and only an agent's is.** An agent that is
working is already running verbs — a status, a note, a link — so `cli/main.py` renews the
project's standing claims on every invocation and the agent never carries a heartbeat of
its own. It never *makes* a claim: running a verb is evidence for a claim somebody made,
not a claim of its own. And the renewal is handed to the run only from inside an agent's
shell — `entry.py` passes the board when `agent_shell_marker()` says so, the same fact the
window word is refused on, read from the other side — because a developer running
`dplanner step list` in their own terminal would otherwise be vouching for an agent that
died an hour ago.

**A claim is this machine's, never the plan's.** It goes under `config_dir()/at-work/`
beside the telemetry journal, for the reason FORMAT.md gives: a record that changes every
few seconds and means "a process is running here, now" would, in a project directory, be
committed into everybody's history, arrive at every collaborator as an outside change, and
make the window adopt an edit every two seconds. One file per claim rather than one per
project, so several agents on one plan — the four Run Agent will launch at once — never
lose each other's updates to a read-modify-write race, and a reader is a directory listing.

**The window makes no claim, ever.** Its only write is the clear. A window that could say
"an agent is at work" would be a surface asserting something only the other process knows,
and the first time it was wrong the banner would stop meaning anything. That is also why
there is no window verb to start one and why `agent_at_work` registers no action beyond the
band's own *Clear* and the dialog a click on it opens.

**One band for every agent, and the list behind it.** The first build stood a notice per
claim, and with four agents on one plan that was four amber rows over the content — four
things to read past before the work, each saying most of what the one beside it said. What
the person needs first is *that* agents are writing the plan and which steps they are on,
so there is one notice: one agent's own line when there is one (it has room to say what the
agent is doing), and otherwise a count with the projects and step keys (*3 agents are at
work on DPlanner changes 2 · S4, F7, S23*, `claims_words`). Its meter is everything the
agents counted together — done over total across the claims that declared a count
(`combined_fraction`) — so a big job weighs more than a small one and a claim that promised
nothing adds nothing either way. *Clear* on it ends every claim it stands for. The rest is
behind a click on the band (`Notice.open`, the whole band as the target, the way a
status-bar button opens what its words count): *Agents at Work*, the Agents browser's shape
— a `DialogFrame` over a `RowWell`, non-modal so the poll keeps it current — with a row per
claim saying what the agent wrote, its count as a bar, and when it was last heard, *Reveal*
selecting its step, and a ✕ that clears that one claim, which is the only way to drop a
dead agent's claim without clearing the live ones beside it. It is a dialog the person
opened, which DESIGN.md's *never a modal for a background fact* does not forbid: the fact
is still said where it bites, in the band.

**A status that says the work stopped ends the claim on that step.** The banner a finished
agent forgot to take down was the common stale one, and asking the briefing to say *end
your claim* louder only moves the sentence. The one verb every finishing agent is sure to
run is `status set` — the epilogue ends at `ready-for-review` and the CLI holds it there —
so `ready-for-review`, `ready-to-merge`, `done` and `blocked` each end the claim on the step
they are set on, in the same run and whoever runs them, because each says nobody is working
it and a claim saying otherwise contradicts it. The composition root hands the board to
`step_status/cli.py` as one callback (`end_claim`); a status set in the window ends nothing,
since the window's only write to the board is the clear, and the lapse covers it. The
briefing says it once, where it happens: *once the PR is open, set the status straight away
— it takes the window's banner down with it*.

The payoff is the collision. `library_watch` now asks one question of this module — is an
agent at work on the project this conflict is in? — and while the answer is yes it leaves
its question in the notice bar and the status bar instead of raising the modal. The
question is deferred, never dropped: the person presses *Settle…* when they are ready, the
next collision after the agent goes quiet raises it as before, and the dialog names the
agent in its own words, because *Take Theirs* means taking that agent's work and a dialog
that did not say whose would be asking the developer to guess. The notice is the only
reminder — there is no status-bar button beside it: two surfaces would say one thing, and
the one a person can look away from is the one to leave out.

What the banner is made of is the existing vocabulary and nothing new. DESIGN.md allows
three motions in the whole application; the arc that says *something is running here* is
one of them, and it leads the band for as long as it stands. The tone is amber throughout —
a lapsed claim is not shown at all rather than shown quietly. The count is the one amendment:
a bar is for work whose end the application knows, and "never for an agent" was written
when an agent's progress was unknowable. An agent that runs `agent-work set --done 8 --of
20` has declared a count, and a declared count is a count; a claim that declares none still
gets the arc and no promise.

#### The banner is a band, and the band is the meter

The first build said all of that in a dot beside secondary words with a 4 px strip under
them, and it was too quiet for what it means. Two things were wrong and both are about
where a fact of this kind is read. The tone was *busy*, which is the blue this application
says "a piece of work is running" in — true of the agent and beside the point for the
reader, whose problem is that **somebody else is writing this plan and they should keep
their hands still**. That is a caution, not a report, and the vocabulary had no word for
it: `warn` is the fifth tone, the amber the canvas chips already wear, and it is not a
weaker error — an error is this work failing and carries its remedy, where a warning is
something nobody can fix and everybody must see. And a tone said in a dot is a tone for a
surface somebody has chosen to look at; a standing notice is the opposite, so it wears the
tone as a **band across the whole row**. It is the one surface in the application where
that is right, and the reason is exactly that it is the one surface a person must not read
past.

The 4 px strip went the same way, for a reason that generalises past this banner: **a meter
has to be legible as a meter before anything has happened.** At nought per cent the strip
was a hairline under the words, indistinguishable from the seam above it, so the first
thing a reader learned about the agent's progress was learned only once the agent had made
some. The band fills instead — the same hue at a greater weight, from the left — and the
percentage stands at the right, next to the verb, where the eye is already going. An amber
row saying *0%* is plainly something that fills; a hairline is not. The strip keeps every
other job it had (a fetch, a save over three repositories, always under the fact that leads
it), because those are read inside a surface the person came to, and the notice is the
surface that came to them.

#### The band stands at the foot of the content

The bar first stood above the tabs, on the reasoning that the top of the content is the one
place a person cannot be looking away from. In use, placement mattered less than movement.
A band that comes and goes above the tabs pushes everything below it up or down: the table
row under the pointer, the canvas, the line being read. Once claims lapsed after three
minutes of silence, a quiet agent's band dropped out and came back several times over one
task, and each time it moved everything. At the foot of the content, between the tabs and
the status bar, the band moves only the content's bottom edge. A full-width amber band is
not missed there, because the band itself, not its position, is what makes it hard to read
past.

### A branch switched underneath the window is taken in, and said

The window's own Switch Branch takes the tree in and drops the history (above). A switch
made *outside* it — `git checkout` in a terminal, an agent whose step runs in the checkout
itself — would otherwise arrive as nothing in particular: the workspace watcher adopting
whatever plan files differ, a status-bar flash, a stale branch label, and every edit from
then on autosaved onto a branch nobody had named. *A window should warn when the
checkout's branch changes underneath the plan.*

So the sync module polls. Every repository's branch is asked of git directly — not
through the service's second-long cache, since seeing a change is the point of asking —
at the workspace watcher's cadence (`framework/window_watch.POLL_MS`), one cadence for
"did something change underneath", and compared with the branch this window last saw. A
difference is handled exactly as the window's own switch is: `_take_worktree` reads the
tree into the model and, when anything was taken, clears the undo history and resumes
autosave; then a modal names the repository and both branches, once per switch. Three
things keep it honest. The poll stands down while an operation of the module's own is
running, and every such operation re-baselines when it ends — New Branch, Switch Branch,
a pull — so only a switch from outside is ever reported. A membership change re-baselines
too, since a project that just arrived was not "underneath" anything. And the history is
dropped by the refresh's own rule — only when something was actually taken — so a switch
the watcher's tick happened to adopt first keeps the stack, and the model's refusal of an
entry that no longer applies is what covers it (*The undo history survives an agent's
edits*, above). The cost is one `git branch --show-current` per repository every two
seconds on the GUI thread, a few milliseconds; `refresh_dirty` already pays the same
after every flush.

### Storage operations that rewrite the working tree are synchronous

CLAUDE.md's rule says blocking work runs through `TaskRunner`, and the sync module's own
Save and Update honour it. Three of its operations deliberately do not, and the exception is
a decision, not a leak:

- **Branch switch and create** (`SyncService.switch_branch_sync` / `create_branch_sync`,
  run through `_run_guarded` in `modules/sync/module.py`). A checkout rewrites the very
  files the application is showing; taking them into the model must follow *immediately*,
  not after an event-loop round trip during which a paint, a context change or an autosave
  could read a model that no longer matches the tree. `_run_guarded` pauses autosave around
  the body for the same reason, and resumes it once the tree is in the model.
- **The branch list** before the switch dialog opens: a subprocess, but a local one, and
  the dialog's contents must be current at the moment it appears.
- **Moving a plan** (`ProjectsModule.move_plan` over `domain/relocate.move_project`). The
  project's files leave one directory for another and the store is re-pointed; the reload
  that follows discards the build, so there is no runner to come back to. The publish that
  may follow a move or a New Project into a fresh GitHub repository rides the same
  exception, under a wait cursor: the repository was written a moment ago and the person
  is waiting on it.

**Save at quit is not an exception**, though its case once looked like one: *the window is
closing; there is no task centre left to watch a task in, and returning to the event loop
mid-teardown is exactly the window a lost write needs.* Both halves turn on the window
closing, and the close is **deferred**: the guard starts the save and answers "not yet", so
nothing is tearing down while it runs, and the progress dialog is the watcher the task centre
cannot be. A synchronous save at quit costs what the exception never mentioned — a frozen
window, for as long as publishing, committing and pushing several repositories takes, with
no way to tell it from a hang.

The boundary to keep: an operation whose completion the *running* application must observe
before doing anything else at all may be synchronous; anything the user merely waits on goes
through the runner. A new storage verb defaults to the runner. And the lesson of Save at quit
is worth keeping beside it: **before granting the exception, ask whether the constraint
that forces it is itself a choice.** "The window is closing" was.

## Closing a window is not discarding it

A build is a window, its services and one instance of every module. Two places let one go: a
reload, which replaces it, and a test, which is finished with it. Both go through
`discard_build()` in `framework/session.py`, and the reason that is one function rather than
two similar blocks is that the second copy of it left out one line.

The line is `deleteLater()`. **A closed `QWidget` is still alive** — `close()` hides it and
runs its close hooks, and Qt goes on holding it in `topLevelWidgets()`. Everything hangs off
the window, so the entire build stays reachable: services, model, every module. In
the application that costs nothing worth noticing; a person reloads a library a handful of
times. In the test suite, which builds a whole application per test, each discarded build left
28 top-level widgets and about 2,700 objects behind, permanently.

That would be merely untidy if nothing walked the result. `tests/conftest.py` collects cyclic
garbage after every test — it has to: `framework/gc_policy.py` switches Python's automatic
collector off (left to itself it frees PySide wrappers on a worker thread or mid Qt event
dispatch, and the SIGSEGV moves whenever anything else changes), so the boundary is where the
suite's cycles die. A full collection costs what the live object graph costs. So the leak made
every test pay for every test before it, and a suite that should be linear was quadratic: early
tests ran in about 0.45 s, tests two thirds of the way through took over ten seconds each, and
`tests/modules` alone took 25 minutes. With the one line restored it takes 4m36s.

**`deleteLater` and not simply dropping the reference**, because `discard_build` is called with
the window's close hooks still unwinding on the stack; deleting it under them is a crash. The
deletion happens the next time the event loop runs — which is the second half of the rule:

> Anything that discards Qt objects without an event loop to follow must dispatch the deferred
> deletes itself.

A running DPlanner always has one, so the reload path is already correct — measured, not
assumed: reload a library nine times and the top-level widget count settles and stays flat.
A test suite has none, which is why `AppSession.close()` ends with
`sendPostedEvents(None, DeferredDelete)` and why that call is *there* rather than inside
`discard_build`: only a caller that is on no Qt stack at all can promise it is safe.
`processEvents()` will not do — Qt deliberately skips DeferredDelete in it, and that is exactly
the trap this closes.

`tests/framework/test_builder.py` asserts the property by counting top-level widgets across two
build-and-close cycles, rather than trusting that the line is still there.

## Syncing an external fact

The GitHub aspect stores each PR's *last-seen* state so a merged PR stays green offline —
which means something has to keep that cache current, and in a window that something is a
background refresher, not the user.

The refresher builds the same `SetModuleDataCommand` every other writer builds, but calls
`redo()` directly instead of pushing it onto the undo stack, with an origin of its own
(`REFRESH_ORIGIN` in `modules/github/refresh.py`). The reasoning:

- **Undo is for decisions.** The stored state is a cache of something GitHub decided; an
  undo entry here would make Ctrl+Z restore a *stale* state instead of undoing the user's
  last edit, and the user never asked for the refresh in the first place.
- **The stack is not what persists.** Autosave flushes on the store's dirty signal, which
  `Library` emits for every model change regardless of who applied it — so the write
  reaches disk without the stack's help.
- **There is precedent, not exception.** The CLI applies commands the same way (a run is a
  transaction; version control is the undo). The rule "every model change goes through a
  command" is about having one vocabulary of change, not about the stack: the stack is the
  *GUI user's* journal, and a background sync is not the GUI user. (The format migrations
  at open sit *below* the vocabulary: they run in `core/`, which may not import
  `domain/commands`, so they write through the `Repository` protocol directly — before any
  surface that could undo exists.)

The concurrent-writer story needs nothing new: the refresh dirties the project like any
edit, and *Two writers, one folder* above already covers an agent flushing underneath. The
store's own adoption of an outside change (*Adopting the other writer's changes in place*)
is the same shape one level down — a change nobody in this window decided, applied with an
origin no view claims, off the stack — with one difference: it is *read off disk*, so it
does not dirty anything.

**A merged PR finishes a step waiting on its merge.** *Ready to merge* means exactly that
the PR is all that is left — a review's `approve` leaves itself there, carrying its
subject's PR — so the moment GitHub says *merged* is the moment the step is done, and
nobody should have to remember to say so. It is the same external fact, so it is written
the same way: `record_merged` in the status aspect applies `status set`'s own command
directly, with an origin of its own (`MERGED_ORIGIN`, beside `STARTED_ORIGIN`, whose
launch claim is the precedent), because Ctrl+Z restoring *ready to merge* would file a
merged step as still waiting on it. Three choices shape it:

- **It crosses a module boundary through the root.** The GitHub module knows PRs and not
  statuses, so `GithubDeps.finish_merged` and `github_cli.commands(finish_merged=…)` are
  callbacks the composition root answers — `record_merged` in the window, `status set`'s
  writer in the CLI, so a merge ends a claim exactly as the verb would.
- **Every surface that learns the state applies the rule.** The refresher, the GitHub tab
  and `github refresh|show` all learn a PR merged; the first two share one writer
  (`refresh.adopt`) so the tab cannot write fresh state and forget the rest.
- **What is stored counts, not only what is fetched.** A merged PR is terminal and never
  fetched again, but a step can reach *ready to merge* after its PR did — a review approved
  once the developer had merged by hand inherits a state nobody will refresh. So each tick,
  and each `github refresh`, also offers the steps whose stored state already reads merged.
  A merged PR on a step nobody accepted says nothing: only *ready to merge* moves.

## A project names its locations

A project answers three questions about repositories, and for a year the code let one
answer serve the first two. *Where does the plan live?* was the git repository enclosing the
project directory — derived, never stored, and still is. *Which code does it plan?* was
assumed to be the same repository, and that assumption is what field testing kept
reporting as "main drifting": *Save* committed plan files to the code repository's
`main`, every agent worktree carried a copy of the plan, and a `git checkout` in the code
repository swapped the plan under the window. A plan and the code it plans have different
rhythms — the plan changes on every `dplanner status set`, the code on every merge — and
one branch cannot carry both without each getting in the other's way.

So the second question became a stored fact — first as one string, the code repository's
remote, and then, when a project turned out to be about more than one place, as a
**table of locations**. A location is a **role**, a **repository** (the remote URL as git
prints it; a repository with no remote is stored as its resolved path — the only identity
a repository that cannot be shared has) and a **position**, a directory inside it, with an
optional ref and a label to tell two rows of one role apart:

| role | repository | position |
|---|---|---|
| code | `acme/widget` | `.` |
| code — *UI* | `acme/widget-ui` | `.` |
| specs | `acme/specs` | `products/search/` |
| docs | `acme/widget` | `docs/search/` |

It lives in `project.dproj` where everyone who opens the plan sees it (`FORMAT.md`), and
the first `code` row is *the* code repository every older reader means — `RepositoryFacts.
repository` and `.checkout` are that row's, so Run Agent, the GitHub tab, discovery, lint
and the briefing kept their seams when the string became a table. Three things the table
decided are worth writing down. **The plan repository stays derived**:
`find_repo_root(project directory)`, exactly as before, so the plan's history is still the
repository's history and nothing stored can disagree with git — and the table lives *in*
it, which is what lets a clone of the plan set everything else up. **A row has an id**
(`l1`, `l2`, …), minted per project and kept while the row is edited, because a spec
source and a step's workplace name a row by it and editing a repository URL must not
orphan them — the same reason a step's folder name is frozen and its id is its identity.
And **roles are a registry**: the domain declares `code`, because `cli/discovery.py` must
find a project from a code checkout without loading a module, and every other role is
declared by the module that acts on it in a Qt-free `roles.py` (`spec` by the spec
module, `reporting` by the reporting module) that the composition root gathers into one list the
Add menu, the card, `dplanner location roles`, lint and the briefing all read — a module
adds a kind of place and every surface learns it. A role this build does not know is
loaded and written back untouched, the edge-kind rule, because a colleague's build may
have a module this one lacks.

The third question — *where is each of those on this machine?* — is per user, per
machine, and goes to the library file's `checkouts` map (`FORMAT.md`), **keyed by
repository, never by project**. The earlier column was per project, and three places had
grown a search over other projects' rows for "the checkout somebody else already has of
this repository" — the tell that the fact was filed under the wrong key. A checkout is
this machine's fact about a repository; two projects naming one repository share it, a
second plan for the same code never asks for a second clone, and the three lookups are one
dictionary read. It is written straight into the file rather than through the flush,
because the first `dplanner` call from a checkout records it and a read verb's transaction
must never be refused over a per-machine fact. `domain/locations.place` is the one answer
to where a row stands, in a fixed order: the recorded checkout; the plan repository itself
when the row names it; a managed clone for a role that only reads; or nowhere yet, which
every verb that needs it says in words.

**The roles are three, and they are the people around a plan.** A *spec author* commits
functional specs to a repository and wants the project to read them, without ever managing
a folder for DPlanner. A *developer* has everything checked out and works with agents in
those checkouts. A *team lead* reads specs and reports, has nothing checked out, and does
not want to. So a row is **Code** (what agents change), **Spec** (what DPlanner reads) or
**Reporting** (the one place DPlanner *writes* for people who read without it: the report
site on export, and where the tests export is offered). Docs and Tests as roles of their own
were a guess about filing; reporting is the act, and it is what they had in common.

**Whether a location needs a working checkout follows from whether its role writes** —
and whether one is checked out is not the person's problem unless they want it to be. A
read-only location (spec) is fetched on demand into a managed clone — the git spec
source's blobless, shallow, sparse cache under `config_dir()`, keyed as it keys it, so a
spec row and the source fetched from it share one directory — and never asks; **a managed
clone is never written**. A worked-in location (code; reporting) needs a checkout, and a
verb that needs one gets it from the projects module's **checkout service**
(`modules/projects/checkouts.py`): the one this machine recorded, at once, else a clone
made now on a task and recorded per repository. The **clone policy** beside the
repositories folder (*Settings ▸ Repositories*) decides *where* that clone lands — kept by
DPlanner under `config_dir()/checkouts/` (`core/storage/kept.py`, the default: a full
working clone, hardened only while it is made, never inside a plan repository, a project
directory or the person's repositories folder) or into the repositories folder, asked
once — and **never whether the verb runs**. There is no *not checked out on this machine*
dead end: Run Agent and Open Agent in Code read *clones acme/widget first* and
clone before they launch; the Open
Project wizard's Repositories page shows only under the folder policy, where a developer
says *use a checkout I have* before anything lands among their own. A kept clone is a
checkout like any other — `Placement.kept` changes the wording (*kept by DPlanner at …*)
and nothing else — and a repository stored as a path is placed there only when a working
tree is there, so a bare `file://` remote is cloned like any other.

**A reporting location is where the report site is exported, never where Save commits.** The
site writer takes a *target* (`website.SiteTarget`: the repository the site sits in, and the
directory the pages go in), so the plan's `reports/`, a reporting row's position and any picked
folder are one layout. *File ▸ Export ▸ Report Site (Folder)…* opens its folder picker at the
focused project's reporting location when this machine has that repository; `dplanner report
site` writes there by default, `--out DIR` anywhere. Neither commits — what lands in the
reporting repository is its people's to record, and Save writes no reports at all (`cli.md`'s *A
report is a publication, not a record*). The flows this settles, end to end: a spec author adds
their repository from the Specs tab (*Add Spec ▸ From Repository…*, below); a developer opens a
shared plan with everything checked out and is asked nothing; a team lead opens the same plan on
an empty machine and is asked nothing; Run Agent on code nobody checked out clones and launches.

`domain/repositories.py` is the one derivation over the three — `RepositoryFacts`, every
row placed, with four states read off the code rows: **separated**, the shape the
application wants; **colocated**, the same remote or either checkout inside the other;
**legacy**, no code location and no index line naming the project — a plan that is its
repository's root, or one from before the index — read as colocated so nothing breaks on
the day the build updates; and **unset**, no code location in a plan repository that lists
the project, whose code is simply not recorded yet (below). *Warns* is one predicate — the
plan is in its code (`plan_in_code`: legacy or colocated) and not accepted — asked by lint
(`repo.legacy`, `repo.colocated`, exit 1; and the table's own `location.invalid`,
`location.unknown_role`, `location.duplicate`), by the briefing's preamble (WARNING: leave
the plan files alone), by the Project dialog, and by the opening
status line; `colocation: "accepted"` silences all of them at once, because it is the
people on the project saying the shape is on purpose.

**Unset is not legacy, and the index is what tells them apart.** For a while every
project with no code row read as legacy, and *File ▸ New Project…* made exactly such
projects: it never asked for the code, so a plan created in a plan repository was read as
living inside its own code — Run Agent opened in the plan repository, the GitHub tab read
its origin, lint told the person to `project move` a plan that was already where it
belonged, and the Project dialog offered to set up a plan repository for it. The guess
"no code named means the plan is in its code" was right for every plan made before the
fact existed and wrong for every plan made in a plan repository since, and the two are
told apart by a fact already on disk: a plan repository names its projects in its
`.dplanner` index, while a plan from before it had none (and a project that *is* its
repository's root is never listed). So a listed project with no code row is **unset** —
no derivation reads it as anything: Run Agent and Open Agent in Code grey with *no code
repository is recorded*, refs read nothing, `repo.unset` names `location add`, the briefing says
the code is not recorded, the dialog shows the plan's own history with no set-up offer,
and Move Plan moves it on still unset, because the repository it leaves was never its
code. Accepting colocation does not quiet it, since there is no colocation to accept.
`code_root` and `code_remote` are the fallback in one place — the plan's root and origin
for legacy, nothing for unset — and every reader asks them rather than spelling the
fallback itself, which is what let the guess spread to five readers in the first place.
One shape pays for it: a plan made in a subfolder of its code after new projects began to
be written into the index is listed, so it reads unset until its code row is recorded —
which, naming the same repository, makes it colocated again. The alternative, a heuristic that
looks for source files beside the plan, would be a guess about the person's tree; the
index is their own word.

The readers are seams the composition root wires. The agent module is handed
`facts_for(step)` and decides *where an agent works*: the checkout of the code location
the step's `workplace` names — an aspect with a default, the primary, because two code
repositories in a project means some steps are in one and some in the other, and which is
a fact about the step exactly as its worktree choice is — else `code_root`, the plan's own
repository for the legacy shape and nowhere for an unset one, greyed with the reason
("acme/ui is not checked out on this machine — Project ▸ Settings…", "no code repository
is recorded — Project ▸ Settings…") until the fact is there — and
`store.checkout_changed` refreshes the context, since nothing in the context graph
changed. A conflict handed to an agent is about plan files and opens in the plan
repository whatever the code is. The github module's `repository_for`, `dplanner github`
and the report's refs all read `code_remote`: the primary code repository, the plan's
origin only for the legacy shape. `dplanner project show`, `location list`, `agent prompt --json` and
the Project dialog's Locations table print the same facts, and the briefing tells the agent the table
in words — which repositories the project is about and where each stands here, so an
agent never guesses a path. Discovery (`cli/discovery.py`) gained one rule: a `dplanner`
call from a checkout — or a worktree of it — whose `origin` is one of a project's code
locations finds that project, spelt however git spells it (`canonical_remote`), so an
agent in the code needs no configuration; the wrapper script also exports
`DPLANNER_PROJECT`, so nothing is even looked up.

The alternatives weighed, for the record. *Keep one code repository and let each module
store its own place* — the spec locator stays private, docs gets a path setting — was the
status quo extended: three vocabularies become four and no surface can show all the places
a project is about. *A `locations` module owning the table as module data* fails on the
first reader: `cli/discovery.py` must read code rows and `cli/` never imports a module.
*Let a managed clone be written and pushed by Save* was the seductive version of the
request — reporting working on a machine that never chose a folder — and is the
"main drifting" story again with a different repository. The reporting row *receiving*
the report site is the phase this design leaves open; the table is the same either way.

### The Project dialog is the Locations table over two log columns

(`DESIGN.md`'s *Facts under the thing they are about*, its *Tables* and the `⋯` rule under
*Buttons* are the standard this settled.)

The dialog once stated three things above its logs: the plan repository, the code
repository, and the code's checkout. Nobody could say why there were three, and the
reason is that the code was allowed two facts — *which code* (shared, in `project.dproj`)
and *where it is here* (per machine, in the library file) — while the plan was allowed one.
The count was an artefact of which facts happened to be stored, not of what a reader is
asking, and the two log columns underneath were already saying the true thing: there are
**two** repositories. When the code became a *table* the same reasoning gave the same
shape one level up: every row answers the two questions — which repository and position,
where it is on this machine — and the **Locations table** (`locations_table.py`, the
`Table` primitive) states them for every row at once, greyed where nothing is here yet,
under a caption with **Add ▾** rendering the role registry and **⋯** the selected row's
verbs. A right-click on a row renders the same ⋯ — the row made current first, so the
menu reads the same selection the button would. Adding or editing a row is one fit dialog
(`location_dialog.py`), built for the person who has never managed a folder for DPlanner:
the repository as an editable combo led by what the project and the library already name
(a project reports beside its code more often than not, so the default is the answer) and
followed by the repositories `gh` knows, listed on a task the first time the dialog is
seen and again on a refresh glyph whose arc turns meanwhile — a refusal is a line under
the row, never a dialog; the position with *Browse…* over the checkout when this machine
has one and over the remote's tree listing — the git spec source's probe, worn by a
position, as a tree with its first two levels open — when it does not, so nobody types a
subdirectory blind and nothing is cloned to pick a folder; and the shortest way of all in
the ⋯, *From a folder on this computer…*, which reads the repository, the position and the
checkout off one picked folder (`domain.locations.located_folder`) — the spec author's way
in, and the one reader of a folder's identity, shared with *Choose Checkout…* and the
wizard's *Use a checkout I have…*; refused in words while the row cannot stand. Nothing about a checkout is asked there: a repository already checked out
needs none, a read-only role needs none, and a worked-in repository this machine lacks
shows *not checked out* in the table with *Clone…* in its ⋯ — a decision the person can
make now or after Create. **Create mode is the same table over a draft** the form holds
until Create seeds the project, so the two modes cannot word a row differently; a clone
run from the draft's ⋯ lands in `NewProjectSpec.checkouts`, recorded per repository once
the project exists. The **Open Project wizard asks after the clone**: its Repositories
page (`repositories_page.py`) lists the worked-in repositories the joined plan names that
this machine lacks — clone into the repositories folder, use a checkout I have, or later —
and never lists a read-only row; *Later* is always allowed, because a plan is readable
without any of them. That is what let the link page stop asking where the code goes: a
link needs to name nothing but the plan.

The two log columns kept their reasoning, which is the paragraph below.

So the facts moved under the columns they belong to. Each column now answers the same two
questions — `repos.code_lines` and `repos.plan_lines`, one derivation for both columns, so
no two surfaces can word the same fact differently — printed small
under the well, with the vertical rule between them doing the work of saying which is
which. A line with nothing to name says what is missing (*not checked out on this
machine*) rather than standing blank, and `#RepoLineMissing` is what greys it: the shape
of the footer is then constant, and a reader learns where to look once.

A column's verbs are one ⋯ per column (`RepoAction`, `RepositoryColumn.entries`), not glyph
buttons scattered across its rows. The menu is **built when it opens** — the same
reason `action_menu` builds one fresh: a glyph carries the colour it was painted in — and
an entry that cannot run right now is **greyed with its reason in its words**, never
dropped, so the list to learn is the same list whatever the project's state. These verbs
are dialog-local rather than registered actions, which is why `RepoAction` restates the
presenter policy in four lines instead of reaching for `append_action`; if a second
surface ever needs one, that is the moment it becomes a spec. *Move Plan…* is the
exception that proves it — it has a spec, and the dialog reaches it through the `move`
callback the module hands in, which is the very function `projects.move` runs, so the
menu and the card cannot mean different things by it.

**Create mode keeps its form, and it asks where the code is.** With nothing on disk yet
there is no log to read, so the fields *are* the answer: the plan repository with its
`RepoPicker`, the folder, and then the code repository — a question nobody can skip,
because skipping it silently is what once made a plan in a plan repository read as its own
code. `code_choice.py` is a plain combo box with nothing current until it is answered: the
code repositories this library already plans first (picking one brings its checkout
along, through the checkouts map every project shares), then the two ways to name another —
*From GitHub…* over the listing `gh` knows, and *A folder on this computer…*, which reads
the repository, the position and the checkout off one picked folder through
`located_folder` — and then *No code repository yet*, which is an answer too: the project
is created unset and says so everywhere until the code is recorded. Create is refused in
words until one is picked. The combo is a **view of the draft**, never a second record:
it shows the draft's primary code row, and the Locations table below edits the same draft,
so a code row added or removed there moves it, and *No code repository yet* drops the
draft's code rows. The two modes still share the verbs rather than paralleling them —
`_code_url`, `_set_repository` and `_record_checkout` answer into the draft or into the
model, so neither mode can grow a behaviour the other lacks. It is a combo and not a
radio list or a strip of buttons because the list is the library's, and grows with it.

**A plan repository holds several projects for several people.** Its root carries the
`.dplanner` index (`FORMAT.md`), which is what lets *Open Project…* and `dplanner library
browse` list what a clone holds, with who worked on each and when (`activity`, one git log
per project). It may be local-only — `git init` from New Project or Move Plan — or on
GitHub, published from the same dialogs through `gh`; clones land in one *repositories
folder*, asked for once from the likely candidates on disk and kept per user.

**Moving a plan is a storage operation that rewrites the working tree**, and so is
synchronous (below): `domain/relocate.move_project` copies the plan entries, rewrites the
meta — with the code repository it left as the first code row when the plan was legacy,
and nothing added for an unset one — maintains both indexes, removes the source,
re-points the store and commits on both sides, best-effort; the window pauses autosave
around it and reloads after, because every view that cached a directory is rebuilt rather
than patched. It is the one place colocation is *refused* rather than warned about: moving
a plan into its own code repository is the shape the move exists to end.

**Move Plan is offered on every project, because picking a plan repository is a choice
that can be got wrong.** It stood down once the plan was apart from its code — the verb
read as a one-time migration — and the first plan put on the wrong repository had no way
back but the CLI, which is the wrong answer for a mistake made in a dialog: the surface
that made a choice is the surface that has to be able to change it. Nothing in the move
was a special case of the first one; the only thing the second move must not do is
*inherit*. When no checkout is recorded, `move_project` falls back to the source
repository's main checkout only if `_is_code_repository` says it is one — true when the plan
is leaving the code, and wrong the moment the repository it leaves is a plan repository — so
a plan with no checkout here gains none by moving. The
card's button says which of the two offers this is (*Set up a plan repository…* while the
plan is inside its code, *Move Plan…* once it is out), and the skill still tells an agent
to run `dplanner project move` when the developer asks and never unasked.

The git requirement is **gating at membership, honest afterwards**: New Project initialises
or picks a plan repository, Open Project's browse page lists only what is inside one (the plan's history
*is* the repository's history), but a project whose repository breaks later degrades to
disabled verbs, not a broken library.

## Save spans repositories; the exit dialog says what it records

One library can hold projects in several repositories, so *Save* (record a version) means:
**one commit per dirty repository, covering exactly that repository's project
directories**. The store owns the grouping (`LibraryStore.repo_groups()` — one provider
per distinct repo root, its git operations scoped to the member projects' paths), which is
what keeps two truths at once: several projects in one repo save as one commit, and a Save
can never sweep up the user's source code sitting beside the plan. Branch operations are
different — a branch belongs to one repository — so New/Switch Branch act on the focused
project's repo and are disabled, with the reason in the label, until a project is focused.

Quitting with uncommitted planning changes asks once, honestly: a dialog listing each dirty
repository (checked by default, with its file count and project titles) over one optional
commit message. *Quit Without Committing* is a real choice, not a scare: autosave already
put the files on disk, so nothing is lost either way; only the version history goes
unrecorded until next time.

*Commit & Quit* runs the save as an ordinary task under a modal progress dialog — one
`StatusLine` per repository, publishing then committing, over a determinate bar — and the
**close is deferred until it ends**: the guard starts the save and returns False, and the
dialog's own end closes the window. Three things follow, and each was a decision:

- **"Not yet" is a third answer a boolean guard can give.** `UnsavedChangesHost`'s guard
  returns whether the close may proceed, and False has always meant "the user cancelled".
  It now also means "ask me again in a moment", which needs no protocol change because the
  thing that asks again is ours: the dialog closes the window itself. A guard that could
  answer asynchronously would have been a framework contract change for one caller.
- **`show()`, never `exec()`.** The guards run inside `closeEvent`, so a nested modal loop
  there is re-entrant by construction — and this codebase already carries the scar
  (`modules/github/notice.py`: a nested modal loop deadlocks headless tests). The dialog is
  modal and shown; the event loop that was already running is the one that delivers the
  task's completion.
- **The bar reads a fact and an estimate, and the fact leads.** How many repositories are
  recorded is known, and it is the bar's floor. Between those steps it is filled by how
  long the last save took — `TaskService`'s duration memory, which the application now keeps
  across sessions (`remember=True`), because the estimate that matters most is for the save
  a window has not run yet: quitting a session in which nobody pressed Ctrl+S. A guess that
  could *contradict* what has landed would be worse than no guess, so `max(landed,
  estimated)` is the whole rule, and an estimate that runs out holds at `ESTIMATE_CAP`
  rather than reading complete. With nothing remembered the bar is the count alone.
- **The progress is reported by the service, not inferred by the dialog.** `SyncService`
  emits `saving(index, phase)` from inside the per-repository loop — a Qt signal, so it
  crosses from the worker thread exactly as `notice` does, and inert when nobody is
  listening, which is why File ▸ Save needed no change at all. The dialog tracks the index
  it is told rather than counting its own rows, because a repository that turns out clean
  skips a phase.

A failure stands **in that dialog**, with *Close Anyway* and *Stay*, rather than being
reported into a window that is about to go; the module's ordinary failure→`QMessageBox` hop
stands down while the dialog is up, so it is said once, where the person is looking. One
ordering trap is worth naming: `TaskRunner` emits `busy_changed(False)` *before*
`failed(...)` — deliberately, so a failure handler's modal cannot delay the autosave resume
— so the outcome is settled one event-loop turn later, by which time the error has arrived.

**A push the remote refused has a remedy, so it is explained and offered, not printed.**
The rebase onto `origin/<branch>` that `push` and `pull` run is aborted on a conflict and
raises `DivergedError` (`core/storage/provider.py`), which carries the repository and the
branch. `SyncService._start` sees it on the way out and sends `diverged(root, branch)` just
ahead of the failure. A commit that already landed is not "not recorded": the row says
*committed here, not pushed*. The error's own words do not fit the one-line footer status,
so `modules/sync/not_pushed_dialog.py` says what happened and what to do
in the body instead. The quit dialog shows it under its rows, and Save and Update from
Remote show it in *Not Pushed* rather than a `QMessageBox`. Both offer *Reconcile with Agent*
with every launch profile, and the agent runs in that plan repository, with no worktree and
no step, like the Problems panel's run (`plan_profiles`, `reconcile_remote`). Launching from
the quit dialog answers *Stay*, because an agent at work on the repository is a reason to
keep the window.
