# Runtime — telemetry, diagnostics, discarding a build, LLM calls and dictation

The reasoning behind `.claude/rules/runtime.md`: the rules there are the short, imperative form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## An LLM call is a task, and the service is GUI-bound

`framework/llm_service.py` shipped complete and dormant — no consumer, no tests, and no
mention in this file. Compiling documentation was its first and, for one milestone, its only
one; compiling launches an agent now (*Compiling launches a peer*), so the service is dormant
again — **deliberately, and with its rules written down here rather than lost with its
caller**. They cost nothing to keep and they are what the next AI-gated control in this
application is owed. Read them as the contract they are, not as a description of something
running today. (The checklist's `llm.key` row stays for the same reason and says as much.)

**`complete()` is blocking network I/O.** It runs inside a `TaskRunner` body, and because
the runner's body returns nothing, the answer comes back on the owner's own queued Qt
signal — the pattern `install/command_dialog.py` and `github/section.py` already use. A
timeout becomes `TaskTimeoutError` so the task centre shows a timed-out job rather than a
generic failure, and a delivery whose step has stopped collecting is dropped, exactly as a
stale PR refresh is.

**Nothing logs the call.** The service appends every one to a ring buffer *before* the
provider runs, which is what makes even a hung request visible in *Debug ▸ LLM Calls*.

**An AI-gated control is disabled, never hidden**, and carries `status().message` — which
already names *Settings ▸ LLM* — as the reason, on screen rather than only in a tooltip. The
service re-reads its provider on every call, so a control re-asks on `config_changed` and
configuring one ungreys the button where it stands.

**A result a person asked for lands on the undo stack**, unlike `github/refresh.py`'s
background sync. The distinction is who asked: a person pressed a button, so undo must put
back what was there. Note what that rule does *not* reach — a result that arrives from another
process, minutes later, through the CLI, as a compiled document now does; there undo is not
the safety net and a confirmation has to be.

**And the CLI cannot call it.** The service reads its preferred provider through QSettings
and its key through the OS keychain, so it is Qt-bound by construction while `cli.py` loads
no Qt by rule. That is not a gap to route around, and documentation is the proof: the agent
driving the CLI *is* a model, so the loop is `docs status` → `docs collect` → the agent writes
→ `compiled set`, which re-stamps the digest so what it just wrote reads as current — and the
window's part is to *launch* that loop rather than to reimplement it. Same reasoning as
*Running an agent launches a peer, not a task*, which is where that argument ended up.

## Dictation is a provider, and capture is a peer process

Descriptions, notes, tests, fragments, instructions and specs are prose, and most people
speak faster than they type. The step that added dictation asked for it as a *provider
kind* — the way agent CLIs are harnesses and themes are provided — so the application
never depends on one engine. Five decisions fell out of building it.

**The contract is a Qt-free record in `domain/`, not a Protocol in `framework/`.** The
checklist reaches the providers at CLI time (*is any engine ready on this machine*), and a
module's Qt-free half may import `core` and `domain` and never `framework`; so
`domain/dictation.py` holds `DictationProvider` — id, label, the caption of its one
editable text, the default, a `refusal(text)`, and either `transcribe` or `listen` — with
the recorder table beside it, exactly where `domain/agents.py` holds `AgentHarness`. The
capabilities are derived: a provider that carries `listen` is live, one that names a
`setup_action` can be mended from where its refusal is shown. `LLMProvider` stayed a
Protocol in `framework/llm.py` because nothing headless reads it; the two shapes are the
same lineage one layer apart.

**Capture is a peer process, because there is no QtMultimedia.** PySide6-Essentials ships
the stub and not the binary; the Addons package that has it is the hundreds-of-megabyte
choice `pyproject.toml` already refused for QtPdf. Every command-line recorder this
application could meet — PipeWire's `pw-record`, PulseAudio's `parecord`, ALSA's
`arecord`, `ffmpeg`, `sox` — streams raw signed 16-bit mono samples to a pipe, and a
`QProcess` on the GUI thread reads that pipe as it fills: no worker, no lock, every signal
delivered by the event loop. Raw output is what makes stopping simple — a WAV would need
its header patched by a process that may be dead, raw samples have no trailer — so the
stop is one sequence for every row: `q` on stdin (ffmpeg on POSIX takes it), then
`terminate()`, then `kill()` after a grace, which on Windows is the only one that reaches a
console process; the bytes already read survive it, and the ffmpeg rows carry
`-flush_packets 1` so at most a packet is lost. A recorder is a row with a probe, like a
terminal; *Automatic* is the first installed; the rate is the provider's (`{rate}`),
because the whisper family wants 16 kHz and the Realtime API 24 kHz. The alternatives —
a `sounddevice` wheel, a hand-rolled `ctypes` binding per platform — were weighed with the
developer and declined: a table of commands adds no dependency, matches the launcher's
doctrine, and on the two platforms where the table is thin the OS has dictation of its own,
which the page and the checklist say.

**Batch and live are two shapes of one state machine, and live is one undo step.** A
batch provider gets the WAV once the microphone is off and its transcript lands through
`ProseEdit.insert_at_caret` — the dropped-file insert, sealed on both sides. A live
provider is fed the samples as the recorder emits them and its deltas land at a cursor the
verb took where the caret stood when the session began, so the person can read on while
speaking; an utterance's completed transcript replaces the deltas that led to it. Typing
merges within a one-second window and a spoken pause is longer than that, so coalescing
could not make a session one step; `UndoService` grew `begin_gesture`/`end_gesture`, the
context manager's halves as calls, and the verb holds one open from the first word to
the stop. While a gesture is open nothing can be undone or redone — a Ctrl+Z pulling the
step before it out from under commands not yet placed is worse than a refused key.
`Dictation` (`framework/dictation.py`) is the one machine — idle → recording →
transcribing, or idle → listening → finishing — and the strip's verb and the settings
page's *Try it* are two faces of it, so what the page hears is what an editor would get.

**The service owns the one task runner, and a late transcript is dropped.** A
transcription outlives the editor that asked for it — a tab closed mid-sentence must not
strand a *Transcribing…* row in the task centre — so `DictationService` is on the bundle
with a runner parented to the window, every body captures only plain values and a signal
instance, and a delivery to a deleted receiver is suppressed. One microphone, one
provider, one transcription at a time: a second editor's press while one runs is refused
in words. And a dictation belongs to the document it was started over: `ProseSection`
abandons on every re-bind and `ExpandedTextDialog` on dispose, a generation counter drops
whatever the run still delivers, and the two agent-instruction fields that had no strip
got one rather than a second corner button, because *every prose editor wears the strip*
was already the rule and the exception was the entropy. `status()` is memoised between
`config_changed`s — thirteen strips ask at every build, and one provider's refusal is a
keychain round trip — and the builder bridges `llm.config_changed` into it, since the
OpenAI providers run on the key the vendor module keeps.

**Nothing meters the level, and silence is refused before anybody is paid.** DESIGN.md
allows three motions — the agent ring, the Updating indicator, a working button's glyph —
and a level meter at ten frames a second would be a fourth vocabulary. Recording is the
verb checked and the editor's edge in the accent (`#InspectorNotes[dictating="true"]`);
transcribing is the Spinner in the glyph. The check the meter was for happens once: the
clip's RMS is read after a batch stop, and a silent clip is refused with *Nothing was
heard* rather than sent to a provider that bills by the minute.

**Setting it up is presets, and a refusal names its mend.** Settings ▸ Dictation is the
Agent profiles page's shape twice — a dropdown of providers over the provider's one text,
a dropdown of recorders over the command — with a status line under each saying what
stands in the way and, beside it, what fixes it: a link to where the program comes from, or
*Add API key…*, which runs the provider's `setup_action` through the registry. That action
is the vendor module's: `ApiKeyDialog` (`framework/key_dialog.py`) walks through where a
key is made, tests it on a task runner with the vendor's own probe, and stores it in the
keychain only once it worked — the Confluence Connect dialog's shape with the site and the
email taken away, so every vendor can offer the same act. The checklist's two rows name
the same `dictation.settings` action, which is how *Set Up…* on a row lands on the page
without the checklist importing anything.

## A view refresh is coalesced, and hears one project

The window was choppy on edits, and the reason was structural rather than any one slow
function. Every model signal is delivered synchronously (`core/signals.py`), inside the
command that caused it, inside `UndoService.push`; every open tab rebuilt itself completely
on every signal; and no tab asked which project the signal was about. One keystroke in a
description therefore ran the canvas's full automatic layout (even with every node placed),
a topological sort and a schedule walk *per milestone step*, twenty-four schedule
simulations for the Time tab, a fresh `QTableWidget` for the order, every card of the
progression board (now the Step statuses tab), the docs and tests tables, and a directory
listing for the Agent tab's
inherited context — for every open project, not only the one being edited — and then
re-evaluated all ninety-nine action states. Measured headless over an eighty-step project
with seven tabs open, that was **67 ms of synchronous work per keystroke**.

Four decisions, in the order they were applied, each measured with the journal below:

**The derivations stop scanning, and the canvas computes once per sync.** `Project.step()`
is a linear scan and every graph walk asked it once per edge; a set of ids per walk made
`depths`, `cone`, `progression` and the critical path linear again. `positions()` runs the
automatic layout only when some step lacks a stored one — on a settled plan, never — and the
accent seam became `step_accents(project_id)`, one dict per sync with one schedule walk for
every milestone, where `milestone_stat(step)` had walked it per milestone. Nothing about
these needed a timer; they were simply wrong, and the journal is what made them visible.

**A view of one project hears that project.** `follow_project(library, project_id,
changed)` in `framework/activity.py` asks the model's own `belongs_to` about the node each
signal names — the parent of a structure change, the step of an edge or a text edit, the
node of a field or module-data write — and `follow_target` does the same for a panel
section whose step moves under it. It sits beside `follow_project_tabs` because it is the
same shape: feature-blind upkeep that seven modules had copied by hand. The filter is a
question for the model rather than for the view because a view that reads the parent index
itself is a second implementation of "which project is this node in", and there was
already one.

**A burst is one rebuild, and the newest state wins.** `framework/debounce.py` is the
timer `AutosaveService` and the assets tab had each hand-rolled: `Debounced.trigger()`
restarts a single-shot `QTimer`, so within a burst the older triggers never run, at most
one run is pending per view, and nothing queues. That is the answer to "does a new update
cancel the old one": it does not cancel it, it *replaces* it, because until the timer fires
there was nothing to cancel. Zero delay means "once this event-loop turn is over" — the
canvas uses it, so a composite command's forty signals become one sync and a typed title
still lands on its node as it is typed. A real delay means "after a quiet spell": 300 ms
for a table, a list or a board (the assets tab's number, below what reads as lag on a
rebuild nobody is waiting for), 500 ms for the Time tab, whose refresh is the heaviest
reaction in the application. After the conversion the same harness measured **5 ms of
synchronous work per keystroke**; the Time tab rebuilt once per burst (26 ms) instead of
ten times, the order table once (12 ms), the assets catalog once (15 ms). What was left was
the context refresh — every action's state, every toolbar and every panel re-asked — which
the app shell ran inline on every undo push; it is now the same 0 ms `Debounced` as the
canvas (the context service's own `announce`, since *The context is announced once per
turn* below), and the synchronous cost of a keystroke is **0.3 ms**, with the canvas sync
(8 ms) and the context refresh (3 ms) following once per event-loop turn.

**Why not a worker thread.** The off-thread design was drawn up — a derivation with a
generation counter, applying through a queued Qt signal, dropping any result a newer
request had superseded — and it is sound: the model is mutated only on the GUI thread, a
mutation and its signals and the handler's re-request all run in one synchronous turn, and
a queued apply cannot land before that turn ends. It was not built, for three reasons that
hold whatever the numbers say. The derivations are pure Python, so a worker competes for
the GIL and total CPU is unchanged; coalescing, not parallelism, is what removes the
N-times-per-burst cost. A worker still running when a build is discarded emits on a deleted
`QObject` — the exact widget-lifetime hazard the suite's SIGSEGV notes describe, in a suite
that builds hundreds of applications per process. And "an exception mid-read is a
superseded result" swallows real bugs. The one place a thread honestly helps is disk I/O,
and there the cheaper fix is a cache: the branch label's `git` query, asked twice per
keystroke, is remembered for a second. The disk poll (8 ms every two seconds at eighty
steps) and the minimap refresh (0.1 ms) were measured and left alone; a `poll` span appears
in the journal the day a slow disk makes the first one matter.

**Tests run in immediate mode, and that is the whole test strategy.** About a hundred and
fifty tests assert on a view the line after they push a command, and a deferred rebuild
would fail every one of them for no finding. `DebounceService` carries one switch, set by
the suite's `session` fixture: `trigger()` runs the action inline, which is exactly the
behaviour every view had before it was coalesced. The deferred path is tested once with
real timers (`tests/framework/test_debounce.py`) and once per converted view by switching
immediate mode off, pushing three times, and asserting one rebuild after `flush_all()`.
Sprinkling `qtbot.wait` over a hundred tests was the alternative, and it would have made
every one of them slower and none of them more honest.

**A coalesced rebuild owes the user the fact that it is owed.** The delay buys the
keystroke its speed by *deliberately* showing a stale picture for 300 to 500 ms, and a
surface that shows one in silence is indistinguishable from one that is wrong. So every
debounced view carries an `UpdatingIndicator` at the right end of its strip
(DESIGN.md's *Signalling*), and the thing it follows is the `Debounced` itself:
`pending_changed` goes True on the first trigger of a burst and False when the action has
run — *or raised, or been cancelled*. That last clause is why it is a signal on the
mechanism rather than two statements in the view. The Time tab had those two statements
for a year — `show()` in a wrapper around `trigger()`, `hide()` as the first line of the
rebuild — and they were correct only by inspection: nothing paired them, a rebuild that
raised would have left the label up, and the wrapper existed for no other reason. One
parametrized test now asserts the property for every view at once, which is the shape a
rule wants; per-view wiring is three lines and a rule followed by whoever remembers it is
what the primitive replaced.

The canvas is the deliberate exception: at 0 ms it settles once per event-loop turn, so
there is no span for a person to read and an indicator would only flicker.

**Prose reaches the canvas after a settle.** A card shows no prose but whether an agent
instruction exists — the spark — yet every keystroke in a description ran the whole sync,
each card's accents derived before the scene could find that nothing had changed. So
`text_edited` reaches the canvas through a settle of its own and every other signal through
the 0 ms one: a title still lands as it is typed, the spark appears one settle after an
instruction's first character, and behind Step Details, where a settle waits for the modal,
typing costs the canvas nothing until the dialog closes. The settle carries no indicator —
it almost never changes a card, and a spinner over the graph at every pause would announce a
redraw that is not coming. Filtering *which* prose a card reads was the alternative and was
not built: the composition root would have to keep a list of text keys in step with
`step_accent`, a second answer that drifts the day an accent reads prose nobody named.

**And the indicator is a motion, not a word.** It carried *Updating…* for one step. A word
at the end of a control strip is the only prose on a row of glyphs, it is four times the
width of what it replaced, and it is the one thing on that strip a translation would have
to reach; so it is the same three-quarter arc a working button turns, with the words in its
tooltip. The point is not the pixels saved — it is that *something is running here* becomes
**one** thing to recognise wherever it appears, rather than a word in one place and a
turning glyph in another. `Spinner` therefore drives either: a button or toolbar verb, whose
glyph it borrows and gives back, or a bare `QLabel` that *is* the slot and shows nothing when
idle. `UpdatingIndicator` is the second of those with a `Debounced` attached, which is why
wiring a view stayed three lines when the look changed.

**A settle behind a modal waits for it.** Step details moved out of the side panel into a
modal dialog (`steps.details`), and coalescing still let every pause in typing rebuild the
window behind it. Measured on a real plan of 80 steps and 262 spec citations, typing a
sentence into the dialog froze the window for **630 ms** at every pause with the graph, the
Order table and the Time tab open, and for **1.25 s** with every tab open — the Problems
reading (545 ms) and the Coverage tab (573 ms) each re-judging every citation, for views
nobody could see past the dialog or act on until it closed. So a `Debounced` asks, when its
timer falls due, whether a modal dialog is up with its owner outside it, and if so starts
the timer again instead of running. Three choices make that one rule rather than a flag per
view. **The owner is the parent chain** — the first `QWidget` above the `Debounced` — so the
dialog's own sections (its Agent tab's briefing, its Tests tab) go on settling, the docked
panel's copies behind it wait, and an owner that is no widget at all, a service like the
Problems reading, stands behind every dialog. **Only a settle waits**: a 0 ms run promises
the next frame, and the context's announcement is one — holding it would leave the dialog's
own action states a keystroke behind. **Nothing is dropped**: the run stays pending, so the
view's indicator stays up and `flush_all` still settles it, and it runs within one quiet
spell of the dialog closing — once, 20 to 36 ms a view on the same plan. It is a re-armed
timer rather than a close hook because a hook would need every modal to call it —
confirmations, file pickers, the expanded editor — where the check is one
`activeModalWidget()` per due settle. With the citation walk fixed too
(`NOTES-FOR-APPFRAME.md` §46), the longest block while typing in the dialog on that plan is
**28 ms**, with three tabs open or all of them. `scripts/synthetic_library.py` now gives
every project a spec its features quote, because a citation of a missing document costs
nothing, and that is how the scaling harness missed all of this.

## How the application scales

Measured on 2026-09-08, four days after the coalescing pass above and after the coverage
tab, the progress recorder, the notes log and the feature catalogue had landed on top of
it. Two sources, read together: the user's own journal — every stall the watchdog sampled
and every slot over `SLOW_MS` from four days of real sessions on a project of under a
hundred steps — and `scripts/measure_scaling.py`, which builds the application headless
over `scripts/synthetic_library.py` (three projects in one plan repository, two of them
*N* steps with the real aspect mix: statuses, estimates, a milestone every fifteen,
features, agent steps, tests with runs, notes, a description and a stored position on
every step) at *N* = 25, 50, 100, 200 and 400, and runs every gesture the window has in
the deferred regime, pumping the event loop until nothing is pending and the journal has
been silent for 150 ms. The numbers below are the *few tabs* regime — the graph, the
order table and the Time tab open, which is how the project that felt sluggish was being
used; the *all tabs* regime is at the end. The same sweep on the desktop platform
(wayland, by accident) agreed with the offscreen one within noise on every row but paint,
which is the honesty check on the harness.

**The graph math is not where the time goes.** Every domain derivation is linear and
cheap: at 400 steps `depths` is **0.7 ms**, `cone` **0.4 ms**, `progression` **0.6 ms**,
`link_refusal` **0.02 ms**, the automatic layout **3 ms** (and a project with a fifth of
its steps unplaced syncs its canvas in the same 11 ms per keystroke as a placed one). A
title keystroke's synchronous cost — the `command` span — is **0.4 ms at every size**,
exactly the number the section above ended on. What the journal and the harness agree on
is that the cost sits in the *reactions* to a change and to a click, and that most of it
does not scale with the project at all; it is a constant paid per gesture.

| per gesture, ms | 25 | 50 | 100 | 200 | 400 |
|---|---|---|---|---|---|
| **click on a step** — `PanelDock._on_context` | 42 | 43 | 51 | 59 | 80 |
| pick 20 cards on the canvas | 166 | 182 | 201 | 247 | 517 |
| **details dialog** — construct + first show | 108 | 98 | 113 | 115 | 157 |
| prose keystroke — canvas `_sync`, same turn | 3 | 6 | 11 | 24 | 58 |
| prose keystroke — context refresh, same turn | 4 | 4 | 4 | 5 | 6 |
| after a burst — Order table rebuild | 11 | 20 | 38 | 78 | 126 |
| after a burst — Time tab rebuild | 11 | 21 | 43 | 88 | 206 |
| estimate burst — recorder, per run (×2) | 4 | 6 | 9 | 16 | 37 |
| new step — one `AddNodeCommand` | 7 | 7 | 8 | 9 | 11 |
| paste of 20 steps — the command | 122 | 137 | 137 | 156 | 188 |
| **disk poll**, every 2 s | 18 | 26 | 43 | 78 | 151 |
| autosave flush after one edit | 17 | 27 | 49 | 86 | 159 |
| **full garbage collection** (gen 2) | 239 | 250 | 268 | 296 | 360 |
| keyring read, per call | 4.3 | 4.1 | 4.1 | 4.0 | 4.2 |
| cold open: Tests tab | 146 | 171 | 278 | 670 | 1637 |
| cold open: Coverage tab | 113 | 145 | 335 | 973 | 2672 |
| cold open: Estimates tab | 315 | 423 | 707 | 1281 | 2358 |
| session open | 1784* | 288 | 311 | 461 | 710 |

*the first open of the process pays the imports.

**What the click costs, and why it is flat.** *Measured while the step editor was still a
panel in the right area; the row above is that arrangement's and the table is kept as
measured.* A click published the selection, the dock asked every context panel to
`show_context`, and `StepPanel.show_step` called `show_target` on **all nine of its
sections whether or not their tab was visible** (`modules/step_properties/panel.py`,
`_show_in_extensions`). The profile at 100 steps put the whole click in that loop: the
Agent tab rebinds two editors (`TextBinding`, a `setPlainText` of the whole document each)
and assembles the inherited briefing **three times** (`_mark_prompt_stale` from
`show_target`, from `_refresh_derived` and from the follow); the Covers tab runs two `cone`
walks, parses the run history and builds a card widget per gathered test — eighteen widgets
on the synthetic project; the GitHub tab starts a fetch; every prose tab rebinds. The
user's journal has the same slot at **30 to 105 ms** thirty times over four days. *The step
editor is a modal* moved every one of those costs off the click and onto the double-click
that asks for them, which is the one gesture that wants them paid — so the click is now the
remaining panels' `show_context`, and the figures below are what a `steps.details` costs.
`StepDetailsDialog` builds a full panel (nine sections, four Details blocks, about thirteen
widget trees and fifteen subscriptions — 185 `addLayout` calls and sixteen thousand calls
into the Python `styleHint` override of `theme/style.py` per open) and then shows the step
in it. Construction is **80 to 125 ms**, flat until the largest size; the first show is 20
to 30 ms headless, and the journal's three `steps.details` stalls of **~350 ms** are the
same open with real painting behind it. Picking twenty cards costs twenty publishes,
because the scene announces `setSelected` one item at a time and every announcement runs
the whole chain.

**The second wave is real, and it is the recorder.** An estimate, a status, a link, a
birth or a deletion settles at ~1000 ms where a title settles at ~700 ms, and the journal
says why: `ProgressRecorder.record_all` runs 300 ms after the burst, simulates every
project in the library, writes `progress_history` on the project node — and that write is
a `module_data_changed` every `follow_project` view of the project hears, so the canvas,
the Order table and the Time tab rebuild a second time, and the recorder, which listens to
`module_data_changed` too, runs once more to find nothing changed. Two full simulations
and a second round of every rebuild, per burst, for a record that only has to be right
once a day. A title or a prose keystroke escapes it only because the snapshot compares
stretches, not titles. In immediate mode — the test suite's regime — the same ten
estimate edits ran the recorder **nineteen times** and every open view nineteen times,
which is the mechanism with no timer to hide behind.

**Two costs on the GUI thread scale with the plan on disk, not with the graph.** The
workspace poll is `LibraryStore.changed_underneath()` (`domain/store.py`), a `stat` of
every plan file of every open project every two seconds — **151 ms at 400 steps, 43 ms
at 100**, a hitch on a period. And a flush walks the same tree twice per dirty project,
once to check for a foreign change and once to re-stamp what it wrote
(`_snapshot` from `flush` and from `_remember_disk`), which is why saving one title
costs 159 ms at 400 steps. Neither is the graph; both are proportional to
*projects × steps × module files*.

**A full collection is a quarter of a second, whatever the project.** `gc_policy.py`
runs the interpreter's own generational policy from a 200 ms timer on the GUI thread; a
generation-2 pass over the application's **240 000 to 326 000 live objects** takes
**240 to 360 ms**, and the journal has one at 337 ms sampled inside `collect_if_due`.
The project is a small share of that graph — 25 steps and 400 steps differ by 90 000
objects and 120 ms; the rest is the application. Generation 0 is 0.01 ms.

**What does scale, and how.** The canvas sync is superlinear — 3 ms at 25 steps, 58 ms
at 400 — and half of it at the top is `step_accents` → `milestone_stats` →
`project_schedule`, where `planning/schedule.py`'s `working_days_after` walks the calendar
**day by day from the project start for every step**: 0.7 ms at 25 steps, 28 ms at 400,
quadratic in the plan's length in days. The Time tab's `time_report` carries the same
walk through `phases` and `parallel_finish` (10 → 201 ms), and so does the recorder's
snapshot. The Order table is linear in rows (11 → 126 ms, a `QTableWidget` rebuilt whole).
Three tabs are expensive to open cold and get worse faster than the project grows: the
Tests tab and the Coverage tab (about *N*^1.2 and *N*^1.4, both walking every collector's
cone and building a widget per row), and the Estimates tab (linear, a `QWidget` editor
per row, **2.4 s at 400 steps** — the journal's 448 ms stall at `bulk.py:285` (now `bulk_activity.py`) is the same
table at a hundred). Painting is small headless — 3 to 11 ms a frame at a 280 000-pixel
viewport, the dots and crosses grounds costing a few ms over a plain one — but a 4K
display has thirty times the pixels, and the journal sampled two `steps.details` stalls
of **314 and 324 ms** inside `paint_ground`, which draws every grid point of the visible
plane as an antialiased round-capped point on every repaint.

**Two subscribers answer signals that were never about them.** Every `structure_changed`
in the library — a step born, pasted or deleted in any project — reaches the sync
module's `_on_membership` (`modules/sync/module.py`), which rewires the repository
groups and asks git for every branch: **5 to 6 ms per signal**, twenty subprocesses for
a paste of twenty steps, and the largest single slot in the add, paste, delete and undo
scenarios. The notes card hears the same signal and refreshes per step (0.5 → 3.7 ms).
Membership is a change under the *library* node; a step is a change under a project. The
`foreign_edit` scenario — ten title edits on the sibling project — confirms that every
`follow_project` view is clean: not one refresh from the Big project's tabs at any size.

**And the action-state refresh reaches the keyring.** With a milestone or a feature
step selected, the docs module's `compile_state` asks `llm.status()`, which asks the
provider `is_configured()`, which is `keyring.get_password()` — a D-Bus round trip to the
Secret Service of **4 ms**, uncached, on every context refresh while that step is
selected (`modules/docs/module.py`, `framework/secrets_store.py`). Small per call; the
refresh runs on every push and every click. The spec-sources pass already states the rule
this breaks (*A spec source is a kind the spec module runs*: an action's `state` never
makes a keychain round trip — `status()` reads a `user_config` row, and the secret is read
only inside the act), so the fix has that shape too: a *configured* row the state reads,
the key read only when a call is made.

### All tabs open

With all eleven tabs open the same edits cost more only where a view has no project
filter or no timer, and there they cost a great deal. A title keystroke's synchronous
cost goes from 0.4 ms to **6 ms at 25 steps, 15 ms at 100 and 62 ms at 400**, and the
`foreign_edit` scenario — a title edit in the *sibling* project — costs exactly the same,
which names the view: *All tests* (`modules/testing/activity.py`, `AllTestsActivity`)
walks every project and rebuilds its whole table on any structure, field or module-data
change, synchronously, in the signal. The Estimates tab (`modules/estimation/bulk_activity.py`) is
the other: its `_on_structure` rebuilds the table with an editor widget per row on any
`structure_changed`, so **one new step costs 121 ms at 25 steps, 368 ms at 100 and
1.4 s at 400** while that tab is open — the journal's 448 ms stall at `bulk.py:285` (now `bulk_activity.py`) is
this, on the real project — and it rewrites every row's text on any `field_changed` in
the library (4 ms at 400). The Coverage tab is filtered and coalesced, and still costs
**690 ms at 400 steps** once per burst; a click on a step reaches 113 ms with every
section and context panel listening. Everything else in the all-tabs run is the few-tabs
number plus the debounced rebuild each tab already owed.

### What to change, in order

Each of these is a rule about the framework rather than a patch to a view; the numbers
above are what to re-measure after each.

1. **A section shows on demand, not on every selection.** The inspector host
   (`framework/inspector.py`, `StepPanel`) shows the *current* tab's extension on a
   selection change and marks the others stale; a tab switch shows the stale one.
   `AgentSection._refresh_prompt_if_shown` already hand-rolls this for one pane — the
   rule belongs in the host, once, and removes the per-section guards. This is the click
   (42–80 ms → the one visible section) and half the dialog.
2. **The recorder reads the settled state and never re-emits into it.** Record once per
   burst, for the project the burst was in (`belongs_to`), after the views' own settle,
   and write with an origin the `follow_project` views are told to ignore — or write to
   the per-user store, since the record is a fact about the day, not the plan. Ends the
   second wave: one simulation instead of two, one rebuild instead of two.
3. **A derived fact is cached per library revision.** One counter the mutators bump;
   `cone`, `depths`, `project_schedule`, `progression`, `runs.read` and the briefing
   memoise on it. *Computed, never stored* still holds — a cache keyed by the revision
   cannot disagree with its source — and it removes the "asked N times per refresh"
   class at once: the three briefings per click, the five run-history parses per context
   refresh, the schedule walk per canvas sync.
4. **`working_days_after` is arithmetic, not a loop.** Weeks times seven plus the
   remainder. Turns the schedule, the Time tab and the recorder linear.
5. **A structure signal under a project is not a membership change.** `_on_membership`
   checks `parent_id == library.id` before rewiring; the notes card follows its project.
   Removes twenty git subprocesses from a paste.
6. **An action state never leaves the process.** `LLMService.status()` caches until
   `config_changed` — the seam *An LLM call is a task* already names.
7. **Every subscriber follows a project and coalesces.** Convert `estimation/bulk_activity.py`,
   `AllTestsActivity` and `framework/project_list_segment.py` to `follow_project` +
   `Debounced`, and add the rule to `tests/test_architecture.py`: a `library.*_changed
   .connect` outside `framework/activity.py` and the store is a finding.
8. **Full collections run when the window is idle.** `collect_if_due` keeps generations
   0 and 1 on the timer and defers generation 2 until nothing is pending and no input
   has arrived for a moment — the 240–360 ms pause moves to where nobody is waiting.
9. **The poll and the flush walk the tree once.** `changed_underneath` on a worker
   through `TaskRunner` (it is I/O, the one place a thread honestly helps), and the flush
   re-stamps with `_note_written` instead of a second walk.
10. **Then the smaller ones**: a scene that announces a multi-selection once; the
    Estimates and Tests tabs building rows lazily; `AspectBar.refresh` evaluating each
    toggle once; the ground cached as a pixmap tile per (rect, zoom, background).

Re-measure with `uv run python scripts/measure_scaling.py --sizes 25,100,400` after
each; the click, the second wave and the poll are the three rows to watch.

## The journal: what ran, how long it took, and why it hung

Nothing in the application timed anything, configured logging, or caught a crash. A slot
that raised was logged through Python's last-resort handler and gone; a hang was a story
told afterwards. `core/telemetry.py` is the answer, and three decisions shape it.

**One journal per process, like `logging`.** `Signal.emit` is where a model change turns
into every view's work, synchronously, so it is where that work is measured — and it is
`core/`, with no service to be handed. So there is one `current()` instance: a default
that keeps a ring buffer and writes nothing, which every test sees, and the file-backed
one the entry point installs for both surfaces. The hot path is two `perf_counter` calls
per slot and an append under a lock per span; a slot under `SLOW_MS` is timed and
forgotten. `AppServices.telemetry` is the handle a module reads it through, never a way to
build a second one.

**Two stores, one policy, and failures through logging.** The ring holds the last two
thousand spans of every kind but a quick poll; the JSONL file under `config_dir()/telemetry/`
gets what is worth reading back after the fact — every `failure`, `stall`, `session` and
`cli` span, and anything that took `SLOW_MS` or longer — one `write()` per line, so the
window and a CLI run append to the same file and their rows interleave into one timeline,
which is how an agent lines its `status set` up against the window's `session refresh` a
second later. Failures are not caught at each site: `install()` puts a handler on the root
logger, and every `logger.exception` already in the tree — a raising slot, a failed task, a
refused open — becomes a `failure` span with its traceback and its parent. That handler
would silence the console (a root handler means no last-resort output), so `install()`
adds a stream handler when the root has none. The same fact is what lets the test suite
fail on a slot that raised: a collector on the root logger for the duration of each test,
and an opt-out marker for the two tests that raise in a slot on purpose. It caught its
first bug the day it landed — a callback the appshell still invoked by its old name, which
`Signal.emit` had been swallowing under every test that exercised a tab switch.

**A stall is sampled from another thread, and none of it lives in the builder.**
`framework/diagnostics.py`'s watchdog beats a 100 ms `QTimer` on the GUI thread; a daemon
thread that finds the beat 250 ms late samples the GUI thread's stack through
`sys._current_frames()` — which takes the GIL and snapshots each thread's frame, so a stall
inside C++ is sampled when the GIL is next released and shows the Python frame that made
the call — and opens a `stall` span carrying the sample and whatever spans were open on
that thread: "stall 1.2 s during action steps.delete", with the frames. A modal dialog
runs a nested event loop, so the beat continues through one and a dialog never reads as a
stall. With the crash log open, every beat re-arms `faulthandler.dump_traceback_later`, so
a hang that never releases the GIL still gets its stacks dumped by faulthandler's own C
thread. `sys.excepthook`, `threading.excepthook` and Qt's message handler are chained into
`failure` spans (PySide prints a slot's exception through `PyErr_Print`, which calls the
hook; installing a Qt message handler replaces the default one, so the console line is ours
to print); `faulthandler.enable` writes a native crash's Python stack to `crash.log`
beside the journal; a `session` start and end record bracket a run, so a session with no
end is visible afterwards. All of it starts in `app.main` and nowhere deeper, because a
test build has no event loop for a heartbeat to beat in, and pytest owns the hooks while
a test runs — the builder installing any of it would read as one long stall or bypass the
suite's own capture.

The readers are deliberately two: *Debug ▸ Telemetry* polls the ring once a second while
it is current (spans arrive from worker threads and the watchdog's thread, so polling is
what keeps every widget touch on the GUI thread), and `dplanner telemetry show` reads the
file — `--slow 50` for what took long, `--failures` for tracebacks and the crash log's tail,
`--json` for an agent. The generated skill points an agent at it before it reports a hang.
