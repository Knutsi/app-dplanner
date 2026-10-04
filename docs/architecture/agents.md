# Agents — Run Agent, worktrees, run directories, usage, harnesses, profiles and reviews

The reasoning behind `.claude/rules/agents.md`: the rules there are the short, imperative form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## The description is the instructions

A step used to carry two prose fields — a description and an agent instruction — and the
distinction ("what it is" versus "how to do it") read well in a docstring and nowhere
else. In practice the two said the same thing twice, or an agent driving the CLI set one
when it meant the other, and a step with a rich description and no instruction could not
be briefed at all. The fix deleted the duplication instead of documenting it harder:
**an agent step is briefed with its own description.** Marking a step for agent execution
is the `step_agent_instruction` aspect's `module_data` entry (Step ▸ Type ▸ Agent,
`dplanner agent on`, `step add --agent`); the briefing's `## Instructions` block is the
description body and its images, and the separate `## Description` context section is
omitted so the text appears exactly once.

The *separate instruction* survives as the opt-out, not the default: the "Separate agent
instruction" checkbox in the Description tab (a `SeparateInstructionLink` of typed
callbacks — the description module never learns the agent module's name), `dplanner agent
set`, or `step add --agent-file`. Writing separate text implies both the mark and the
opt-out, which is what keeps plans authored before the mark existed working with no
migration. The opt-out itself is *stored* (`{"separate": true}`) rather than derived from
text-presence, because "opted in but not yet typed" is a real state that must survive a
selection change; the encodings cannot disagree because turning the aspect off clears
both. With a separate instruction present, the description returns to its own
`## Description` section and the separate text takes `## Instructions`.

The seam lives where the other cross-module prompt decisions do: `agent_briefing`'s
`instruction(library, step, files) → PromptPart` reads the description through its
module's `aspect.py`. Run Agent, the Agent
tab's Prompt page and `dplanner agent prompt` all assemble through it, so no surface can
brief a step differently. One consequence worth naming for existing plans: a described,
uninstructed step that used to render `## Description` now renders that text as
`## Instructions` — the same words, under the heading the executing agent actually obeys.

**A review is the one step whose instructions are generated.** What a review must do is
the same for every review — read its subject through its lenses, post findings, wait,
approve or escalate within its cap — and what differs is data its aspect already holds
(the lenses, the cap) and its subject, which the graph holds. Asking somebody to write that
protocol into every review's description would be asking for it to drift from the verbs,
so `instruction` hands a review to `_review_instruction`, which writes it from
the aspect and the subject. The step's own prose is not dropped: it rides inside the block
as *what to look for*, the one thing a person adds to a review, and is still said once. A
lens this build names carries its question (`Lens.asks`, beside the checkbox that picks
it); one it does not name is a skill of the person's own, so the agent is told to use that
skill rather than guess what the word means. `A review is a conversation kept on the step
that asks` has the rest of how both sides are briefed.

## An agent finishes at Ready for review

The spec was plain: agents must stop at *Ready for review*, never at done, because a person
or a reviewing agent looks next. **Done means somebody accepted the work**, and an agent
saying so about its own work is the one claim the plan cannot check. So three places say
it, and one holds it:

- **What agents read.** The briefing's epilogue (`agent_briefing/protocol.py`) ends at `status set
  <key> ready-for-review`, and the skill's *Running as an agent step* says the same, both
  naming the way out. Both word it apart from the agent-run state `plan-for-review`, which
  is the agent's *plan* waiting for a look mid-run, not the step's work finished.
- **What the CLI holds.** `status set <agent step> done` from inside an agent's shell, on a
  step not already under review or waiting on its merge, exits 1, naming
  `ready-for-review`. A reviewing agent is not stopped: from review or merge it may finish
  the step. It is a guard on *who is reporting*, not on the word, so it reads the same fact
  the window word refuses on — an agent CLI's marker in the environment, read by the
  composition root's `agent_shell_marker` over `domain/agents.py`'s `shell_marker`, which
  the entry point imports (the root, which wires the verb, may not import the entry
  point, so the reading lives there rather than in `entry.py`). **A person's own terminal and
  the window are never asked**: the developer marking a step done is the acceptance.
- **The way out is a reason, and the reason is kept.** Some steps have nothing to review — a
  docs-only change, a step that only reports. `--because '<reason>'` sets done and writes a
  `decision` note on the step in the same run (*Done without review*, the reason as its
  body), so skipping review is a recorded choice that reaches every later step's briefing,
  never a silent one. A flag rather than a second word keeps the vocabulary to what a step
  *is*, and a note rather than a field keeps the model to what it already stores.

`tests/conftest.py` scrubs every harness's markers from the suite's environment, because the
suite is routinely run *by* an agent, and a test that wants an agent's shell sets the marker
itself.

The same `status set` also takes the agent's banner down: a status that says nobody is
working the step ends the at-work claim on it — *An agent at work says so, and the window
says it back* has why.

## A review is a conversation kept on the step that asks

The spec asked for a step whose agent reviews another's work before it lands. The person
picks the agent and the lenses and sets a cap on the rounds, and the two agents talk back
and forth through `dplanner`. Four questions shaped the answer.

**What a review is.** A review is a step, as *Status is an aspect, and step types are
emergent* rules. It is an agent step carrying `step_review`, keyed `R`. Its entry holds only
how the review is run: the agent (a harness id, absent for the default profile), the lenses
(absent for architecture and security) and the cap (absent for three). Absence encodes each
default, so a later change of default reaches every review that never chose.

**What it reviews is read off the graph.** Its *subject* is the step it `requires`, never an
id stored in the entry. Relinking a review re-aims it, and no verb that rewrites edges
learns that reviews exist. The price is that a review can be linked to nothing or to
several steps, and lint's `review.subject` says so rather than a verb refusing, because a
plan reshaped in several calls passes through both.

**Every link into a review auto-progresses, by rule rather than by flag.** A review must
start while its subject reads ready for review, and its subject becomes done only when the
review approves it — the collector's deadlock again. The rule is ORed into the one
`auto_progress.aspect.auto_progresses`, so the frontier, Run Agent's gate, the doubled edge on the canvas and
`project graph` agree without a word each. Nothing is written onto the review. The Edge
menu's *Auto-progress* shows such a link checked and greyed, with its reason (*Hidden
means absent; disabled means not now*).

**The conversation lives on the step that asks.** Three homes were weighed:

| Where | Cost |
|---|---|
| **On the reviewed step** | One step can be answering two askers at once, a review and a collector. Each would need its own list keyed by asker, and the cap would sit on the step that does not own it. |
| **In the notes log** | Notes are the project's record, indexed into every later briefing. A round is a turn in a protocol with a state; a log full of them would bury every decision. |
| **On the asker** (`review_rounds`, chosen) | The asker owns the questions and the cap. Each round names its party. A collector's conversations with three sources are three rounds lists in one entry. |

Both sides write that one entry, through verbs in separate runs, and the stale-workspace
check serialises them. **A round holds only texts and stamps**: opened, posted, taken,
replied, then approved or escalated. Its state and whose turn it is are **derived from
which stamps are there**, never stored. A stored state could disagree with its stamps, and
the verbs, `review wait` and the Review tab would each need to keep it true.

**Each verb moves the statuses the way the person would.**
- `post` puts the subject back in progress.
- `reply` makes it ready for review again.
- `approve` sets the subject done and the review ready to merge. It also copies the
  subject's branch and PR onto the review, so the review carries the PR into the merge.
- `escalate` blocks the review. What the person must decide becomes a handoff note, which
  is where the house already says why a step is blocked.

Every one of these goes through `status_command`, the writer `status set` uses. So a
stopped status ends an at-work claim the same way whichever verb stopped the work.

**A collector talks the same way.** Who a step may talk to is whoever it takes work from
review on — `auto_progresses` again: a review's subject, or a collector's flagged sources.
So `start`, `post`, `take`, `reply` and `wait` serve a collector sending work back upstream,
with `--to` naming the source. `approve` and `escalate` are a review's verdicts: a collector
refuses them and names its own way out, `status set`.

**`review wait` polls, and holds nothing while it does.** The other side is another
process, often in another terminal, possibly on another machine once the plan syncs. The
CLI has no process to be told anything, so the waiting side reads.
- Each poll opens a fresh `LibraryStore` and closes it. The run's own library would be
  stale by the second poll, and there is no lock to hold: the stale-workspace check is the
  whole of the coordination.
- A whole library loads in tens of milliseconds, so it polls every two seconds.
- The default timeout is nine minutes, under the ten minutes an agent CLI allows one tool
  call.
- On a timeout it exits **3**, which is neither a refusal (1) nor an arrival (0). An
  agent's loop can tell *nothing yet* from *wrong*.

The loop is one pure function, `await_turn(load, ready, timeout, sleep, clock)`. A test
drives it with a sleep that writes the other side's turn between polls, and no thread.

The window has no verb that posts a finding, because only an agent writes one. The Review
tab shows the conversation read-only, following the ledger as the verbs write it. The rule
is in `.claude/rules/agents.md`, and the edge rule in `.claude/rules/graph-model.md`.

**A conversation is read in a dialog of its own, and the ledger is what opens it.** The
Review tab lists each message as a heading and its first line, which says where a review
stands but not what it said, and a finding is prose. *Step ▸ Review Conversation…* — and
the tab's *Open Conversation…*, and a double-click on one of its rows — opens
`step_review/conversation_dialog.py`:
- the messages on the left, each wearing who said it: the review's glyph for the step that
  asks, the agent's for the step that answers;
- the picked message rendered in full on the right;
- where the conversation stands, in the footer's status slot.

Three choices shaped it:

- **It is enabled by the ledger, not by the aspect.** A collector sending work back upstream
  keeps the same `review_rounds` entry and talks with the same verbs (*A collector talks the
  same way*). Gating on `is_review` would have hidden the one conversation that has no other
  place in the window. The state asks `rounds(step)`, one entry's rows, because an action
  state runs on every announce. It greys with *no rounds yet* on a review and *not a review*
  anywhere else.
- **It follows the ledger while it is open.** An agent's `review reply` arrives from another
  process. The watcher adopts it on a timer of its own rather than a settle, so nothing holds
  the adoption back behind the modal: *A settle behind a modal waits for it* is about the
  views behind one. The dialog hears `module_data_changed` directly, as the tab does. It keeps
  the reader's pick by the message's identity (party, round, kind), not its row, because a
  collector's ledger can gain a stamp on an earlier round.
- **One builder names each message**, for the tab and the dialog alike (`message_rows`,
  `where_it_stands`), so the two cannot word a message differently. The tab's full-text
  tooltip went: the dialog is where a message is read.

**Both agents are briefed with the protocol, because the verbs alone do not say when to
use them.** A review and its subject are two peers in two terminals that never talk except
through the plan, so each briefing has to carry its half of the conversation in full:
- **The review** is told whom it reviews and where that work is (*Work you review*, the
  same line *Work you collect* prints, so a collector and a review are never told where
  work is two ways), through which lenses, the round protocol and the cap (its generated
  `## Instructions`, *The description is the instructions*), and that its verdict is its
  status — its epilogue asks for no PR and no `status set`, because `approve` and
  `escalate` move both steps and carry the subject's PR.
- **The reviewed step** is told not to stop at *ready for review*: set `pending-approval`,
  `review wait`, take each round, fix, push and reply. And it is told when to stop — the
  review approves (it is done), escalates (a person decides), or an hour passes with
  nothing new. That last one is what makes waiting safe to abandon: a relaunched step is
  briefed with any round that arrived meanwhile.
- **A conversation still going is a section of the briefing on both sides** (*Review
  rounds with …*: where it stands, then what each side said). Nothing stores that a step
  is mid-review; the ledger is read when the briefing is assembled, so relaunching either
  agent resumes the conversation instead of starting a second one. An ended conversation
  is left to the Review tab — it asks nothing of the next worker.

**A review runs in no worktree of its own.** An agent step gets a fresh worktree by
default, and a review in one would be reading a new branch off `main` — not the work it
reviews. What it reads is the subject's worktree when that is on this machine, and its
PR or branch otherwise, without checking anything out; it commits nothing, so it needs no
branch. That is a fact about what a review *is*, not a choice somebody should have to
untick, so `agent_briefing.worktree.no_worktree` rules a worktree out whatever the agent
aspect says, and every surface asks its `worktree(step)`: the launch, the preflight
(which tells a review to leave the checkout as it found it — no commits, branch switches or
stashes), the Agent tab's box, greyed with the reason, and `agent worktree … on`, refused.
Both surfaces import that one function, so neither can declare its own.

## Auto-progress is launched by the window

An auto-progress link says a step may start once its sources reach review; a review may
start once its subject does. Until this, *may* meant a person noticing and clicking Run
Agent, which is the one thing the round of three agents and a collector was meant not to
need. The spec's question was who starts it — *likely an issue for race conditions* — and
whether it could just happen when a step's dependencies are fulfilled. It happens now, and
five decisions say how.

**Only a window launches.** The terminal cannot: which agent CLI, which terminal and how
many at once are this desk's settings, kept per user in QSettings, which the CLI has no
business reading — and an agent that launched its collector from its own shell would start
a child of itself, the nested session *The peer is a top-level session* exists to prevent.
So the terminal's half is to *say* it: `status set` and the `review` verbs print a line for
every step the change made due (`_status_written`, the wrapper already on the status-moving
verbs, generalised rather than joined by a second one), and `progression show` marks due
rows. `--json` keeps its one document — the line is text for whoever reads the terminal,
and `progression show --json` carries `due` for a caller that parses.

**What is due is one derivation, read by every surface.** `agent_launch/due.py`'s
`due_now` joins two owners' halves and never stores the answer — headless, so that a process
with no window can one day launch by the same rule; the root only widens *running* with the
runs the window watches, and `due.claim` is the claim either would write:
- `progression.due` — an agent step, pending, with no run recorded, nothing it waits on
  unfinished, and at least one prerequisite fulfilled *through* an auto-progress link (it
  reads review or merge across one). The last clause is the difference from Ready to
  start: a collector whose sources a person set done by hand is ready for a person to
  launch; one whose sources just reached review was made ready by the flag, and the flag's
  promise is that it starts on its own.
- `step_review.aspect.due_turns` — a side of a conversation whose turn it is (`step_review.aspect.turn`), whose
  agent has gone, and that nobody launched *for this turn*. That last needs memory the
  graph does not have, so the round keeps it: `party_turn_launched` / `asker_turn_launched`
  hold the stamp that began the turn launched for, and equal means launched. A stamp that
  names the turn rather than the moment is immune to another machine's clock, and it lives
  in the ledger so the terminal, a second window and a second machine all read the same
  answer. It covers a collector's upstream conversations too, since the ledger is shared.

**Level-triggered, never edge-triggered.** The launcher (`agent_launch/
auto_launch.py`) does not react to "A3 moved to review": the window may have been closed
when it happened, or adopt three such moves in one tick, and an edge missed is a collector
never started. It re-derives what is due after every change of any origin — adopted
outside changes included — when a run ends, when the day turns (a dated wait can make a
step due overnight) and once at start, which also launches what became due while no window
was open. What makes a level trigger launch once is **the claim, written the moment the
shell opens**: the run stamp, and in progress for what auto-progress made due or the
round's stamp for a turn — both off the undo stack like the launch stamp, and flushed at
once rather than after autosave's pause. The next pass reads the step as no longer due. In
the window, *running* is also a run the tracker is watching, so a claim still on its way to
disk can never make a live shell's step due again. The claim is made whatever *On launch*
says, because without it the step is due again the moment its run ends; a turn's claim is
the stamp alone, since `post` and `reply` already moved its side's status.

**A launch is an external effect: its intent is written before the shell.** The claim
reaches the plan file at the pass's flush, and the first version spawned, claimed in
memory and flushed afterwards — a window that died in between left no trace, and the next
one launched the step again. Now `launch_due` writes an intent (`intents.py`: step, run id,
actor, run directory) under the lock's own directory before it spawns, drops it when no
shell opened, and the pass forgets it only once autosave says everything is on disk. A
pass that finds one left over reconciles it before launching anything: a shell that
started (its wrapper wrote the `shell` file into the run directory) is a run, so its step
is claimed; one that never started is refused with a sentence for a person — **never
retried blind**, since a shell slow to start would otherwise be a second one. The intent is
this machine's fact, beside the lock, never the plan's: a run directory and a pid mean
nothing on another machine. Only the unattended launch records one; a person's Run Agent is
watched by the person who clicked it.

**It never launches on a plan it has not seen.** A pass stands down while the plan changed
underneath and is not taken in yet (`changed_underneath`, asked only when something is due
and a slot is free — the walk is the tracker's 300–500 ms on a large library), and it must
run *after* the adoption that woke it: the store mutes dirty forwarding while it adopts, so
a claim written inside an adoption would never reach disk. A **0 ms** settle guarantees the
order — once per event-loop turn, so a burst adopted in one tick is one pass — which is why
the launcher's tests run with coalescing on. And unlike a view's settle it never waits
behind a modal (*A settle behind a modal waits for it* is about rebuilding what a person is
not looking at): the first run found a first-start checklist left open holding every
launch, and a dialog left open is exactly the desk nobody is at. A pass is cheap enough to
run that often — 0.75 ms over an 820-step library — and a title or prose, which never make
a step due, do not wake it at all. A stand-down is woken by the
library watcher's `settled` hook as well as by model signals, because some settles change
nothing the model announces — *Keep Mine*, an identical rewrite, a project still unreadable.
Each step is re-read from the live model just before its shell opens. Past *Max agents*
live runs — this window's tracker's count — the rest wait, the status bar says who, and the
tracker's `ended` hook retries: a run that ends frees a slot even when the agent had
already cleared its state and the plan did not change.

**An unattended launch asks nobody.** `launch_due` is Run Agent for one step with the
person's questions taken out: no prerequisite confirmation (a due step waits on nothing),
no clone (a repository not checked out here is a refusal naming Run Agent, which clones),
no prompt fallback. A refusal is a sentence in the status bar and is remembered for the
step until the step, the switch or a profile changes — a refusal repeated every settle
would be a retry nobody asked for. The profile is the step's: a review that names an agent
runs through the first profile running it, and a named agent no profile runs is refused
rather than swapped for the default, which may be the very agent whose work is reviewed.

**Plan mode is waiting on a person, and says so.** The Claude preset starts in plan mode, so
an auto-launched Claude writes a plan and waits for somebody to approve it — and a session
in plan mode runs nothing that writes, so it never reports `plan-for-review` itself. The
launch stamp carries it instead (`plans_first`, read off the command through the harness's
`plan_mode` words, so a profile edited out of plan mode launches an agent that does not
wait), and `asks_person` reads it with the states that ask: such a step is *Waits for
you* on the boards and in `progression show` (*Progression is the status-aware frontier*),
and while one this window launched unattended waits, a notice names it with *Show
Terminal*. That notice's memory is the session's; after a reload the boards still list it.
A profile that does not ask first is the person's to make — nothing ships one.

**Who may launch.** The switch is *Agent profiles ▸ When a step becomes due*, per user and
per machine, **off by default**: it spends terminals and tokens nobody clicked for, and
every machine that opens the plan with it on is one more launcher. Among windows on one
library on one machine, only the holder of a `QLockFile` under `config_dir()/auto-launch/`
launches, and the other window's page says so. The lock is stale only once its process is
gone (`setStaleLockTime(0)`), so a crash never locks the next window out, and it belongs to
the *session* — `new_session` builds the holder once and hands it to every build — because
a reload builds the new window before it discards the old, and the new one must not find
itself locked out by its predecessor.

**The race, across machines.** On one machine the lock makes one window the launcher, and a
claim written at the spawn and flushed at once makes the launch happen once: the next pass,
in that window or after its reload, reads the step as launched. Across machines nothing is
shared but the plan, and the plan travels by commits: the claim reaches another machine
only when one saves and the other pulls. Two machines with the switch on can therefore both
see a collector due, and both launch it, within one sync interval — each claim is true on
its own machine, and the second to land meets the first as an ordinary conflict on that
step's status. No lock can close that gap without a server, which DPlanner does not have;
what closes it is that the switch is per machine and off until a person turns it on, so the
honest setup is one machine that runs the agents.

The rules are in `.claude/rules/agents.md` (the launcher) and `.claude/rules/schedule.md`
(what is due, *Waits for you*).

## Running an agent launches a peer, not a task

*Run Agent* writes the briefing to a per-run temp directory — never the project, which
would dirty it and end up in version control — and spawns a terminal detached
(`start_new_session`). Deliberately **not** through `TaskRunner`: a task promises progress,
cancellation and a completion that returns to the GUI thread, and none of those are honest
about a terminal the user owns from the moment it opens. The agent reports back through the
CLI instead (`status set`, `note add`), which the two-writers machinery already handles.

The briefing opens with the **project's standing instruction** — the same module's prose on
the project node, edited in *Project ▸ Settings…*'s Agent tab and in the step Agent tab's
Project part (two bindings over one field, one undo stack) — ahead of the step's `## Instructions`
(its description, unless a separate instruction exists — see *The description is the
instructions*) and, after it, the notes index.

The briefing is deliberately **self-contained**: between the standing instruction and the
step's own sit the step's facts — its description as a section of its own only when a
separate instruction displaced it, the feature it realises or — on a work step — the
features it *flows into* (titles *and* the spec passages they were read from, so the agent
reads the obligation rather than chasing an id; the flows-into list is `scope.gatherers`,
the same walk the Covers tab reads), and the branch or PR the work lands on. The project's
topology sits ahead of all of these as a *project section*, right after the standing
instruction, because it frames every step the same way. The agent module renders these as opaque
blocks; the composition root words them, exactly as it words the preamble and epilogue,
because each names another module's vocabulary. Two block kinds, one framing: *parts* are
context handed forward from earlier steps, *sections* are facts about this step, and
`section_lines` renders both as `## …` — what differs is where they sit, not how they read.
One builder per kind lives in `modules/__init__.py` and both surfaces — Run
Agent and `dplanner agent prompt` — call the same two functions, so the window and the CLI
cannot brief a step two ways. An executing agent needs `agent prompt` and nothing else;
needing five verbs to reconstruct a briefing was the failure this replaces. Files attached at either level are **staged into the per-run
directory** beside `prompt.md` and referenced by their staged absolute paths: the agent runs
in the repository it opened at, so the prompt's file paths are absolute — anything else would point at
nothing it can reach. Asset names are content-addressed, so staging is a flat, collision-safe
copy; an unreadable path stays in the prompt as itself rather than vanishing.

Resolution is settings template first (`{script}`, `{prompt_file}`, `{workdir}`), then a
platform table, then `None` — and `None` is an answer: the fallback dialog delivers the
prompt itself, because the prompt is the deliverable and the terminal was only one way to hand
it over. `dplanner agent prompt` prints the same assembly (with the same absolute paths —
the run directory does not exist yet), and *Preview Agent Prompt* shows it in the window.

The assembly is also where the CLI grew the composition root's other seam:
`agent_cli.commands(prompt_parts=…, epilogue=…)` takes typed callables the way a module's
`Deps` does, supplied by `default_cli_commands()`. A `cli.py` never imports another module;
what crosses modules arrives as arguments — `skill_commands(specs, described)` made that
shape first, and this is its second use.

### One agent per chosen step, and why the limit is the last check

*Run Agent* reads `chosen_steps` — the framework's one reading of *which steps is this verb
about*, the same one Delete, Cut, Copy, Duplicate and Isolate act on — so a lasso over three
agent steps is *Run 3 Agents…*, and the verb needed no gesture of its own to learn it. Three
decisions came with that.

**Every chosen step must be launchable, or none is.** A step in the selection with no
briefing, no agent mark or no checkout greys the verb for the whole selection, and the label
names that step and its reason. Running the subset that qualifies is the tempting
alternative and the wrong one: it launches fewer agents than were asked for and says so
nowhere, and the person finds out by counting terminals. This is *hidden means absent;
disabled means not now* applied to a set — the precondition is still taught, it just now
names which member failed it.

**The graph gate asks once.** Prerequisites are checked per step, but the question is one
box for the gesture, listing each waiting step with what it waits on. A box per step would
ask four times about a single decision, and *Run Anyway* on the third of four would leave
the person unable to say what they had already agreed to. Cancel means none of them, which
is the only honest reading of one question.

**The count is a precondition, not a warning.** Four agents is four terminals, four
worktrees, four live sessions and four `dplanner` writers against one plan; a selection is
made with one flick of the wrist and can hold the whole graph. So *Settings ▸ Agent
profiles* carries **Max agents launched at once** — four by default — and a selection past
it greys the verb with the number rather than asking. A confirmation would be the wrong
shape here: the limit is not a risk to accept once, it is a standing statement about what
this desk can hold, so the way past it is to change it in the one place it lives. It sits
beside the agent command and the terminal template for that reason — per user, per
machine, never in the plan, because how many peers one machine can carry is not a fact
about the project.

`_run` re-checks the limit rather than trusting the state gate, on the same principle every
verb here follows: a presenter may run a stale state, and the guard that matters is the one
in the act.

### A launch says the work has started

The graph gates launching by *reading* status (`status_for`, the Step statuses tab's
seam); a launch also *writes* one. When a shell opens, the step is claimed `in-progress`
through `mark_started` — the writer half of the same seam, wired by the composition root
to `planning/status.py`'s own `record_started`, so the agent module never learns the vocabulary
and the status module keeps the only place its words are spelled.

Three decisions sit in that one line.

**It is off the undo stack**, with an origin of its own, exactly like the launch stamp
beside it (*The peer reports back through its run directory* has that reasoning). The
claim rides on something Ctrl+Z cannot take back — a detached shell now exists — and an
undo entry would let the next Ctrl+Z file the step as pending while an agent is still
working in it. `record_started` answers False and writes nothing when the step already
claims to be in progress, so a second launch dirties no file; it *does* override `done`,
because launching an agent on a finished step means the work resumed and there is no
other honest reading.

**It is a switch, on by default** — *Agent profiles ▸ On launch*, beside *Max agents launched at
once* and per user like the rest of that page. On, for the reason the marks are on: the
agent's own first report is minutes away (the briefing's protocol has it setting
`agent-state`, not status), and a step somebody
is working on that still reads pending is a lie the plan was never asked to tell. A
switch rather than a rule, because a plan whose statuses a person keeps by hand should
not have the window writing into it — so switching it off is the deliberate act, and
nothing else about the launch changes.

**Only Run Agent makes it.** `_launch` — the one place a terminal opens — is shared with
the conflict hand-over and knows nothing of the claim; it is made one level up, in the
step loop, after `_launch` has answered that a shell exists. That placement buys two
things at once: a run over a selection claims each step as its own shell opens and stops
claiming where the shells stop, so three steps of which the third found no terminal leave
two marked and one not; and an agent handed two writers' versions of a plan file is never
marked as doing the step's work — it is merging, and marking that step in progress would
be the same lie in the other direction. The verb decides; the mechanism obeys. The one
other maker is its unattended twin, `launch_due`, which claims whatever *On launch* says
(*Auto-progress is launched by the window*).

Nothing un-claims it. Finishing is the agent's own `dplanner status set … done`, or the
person's from Step ▸ Status — the run ending clears the agent *chip* (that state is about
the shell) and deliberately says nothing about where the work stands, which is the same
line *A test result is not a step status* draws between two vocabularies that must not
be folded into one.

### The peer is a top-level session, and the briefing stays out of argv

Four agents died at once on 2026-09-05, and DPlanner had not crashed: it was killed, with
them, by one agent's `pkill -f "Web.Host"`. The chain had three links, and each is now a
rule.

**The briefing was the command line.** The wrapper ran `claude … "$(cat prompt.md)"`, so
every agent's argv was its whole briefing — and every briefing in that project mentioned
`Web.Host` in an inherited handoff. An agent restarting its own .NET host by pattern
matched every other agent on the machine. The opening prompt is now one line
(`launcher.opening_prompt`): *read your briefing in `<file>` in full, then follow it*. The
line carries a path and nothing the project is about, so no pattern drawn from the work can
match it; it also stays under the platform's argument limit, which a briefing with a long
handoff would not, and `ps` stays readable. The agent pays one file read.

That read is outside the checkout, and Claude Code asks before reading outside its
working directories — one approval per launch, on every platform, and again for each
staged asset. So the Claude preset hands the run directory over as an additional working
directory (`--add-dir {run_dir}`), which its documentation says makes reads there ask
nothing. Two facts shape the flag's place and its value. `--add-dir` takes a *list*, so
it sits before another option and never before `{prompt}`: probed, a prompt following
it was taken for a second directory and the session started with no prompt at all. And
the directory is resolved when it is made (`new_run_dir`): the permission check compares
a file's resolved path, macOS's temp directory sits under `/var`, a symlink to
`/private/var`, and Windows's Temp is often an 8.3 short name — the pointer line, the
staged asset paths and the flag all derive from that one path, so every spelling agrees.

**The window was an agent's process, and its agents were its children.** *The window is a
word* has that half. The launcher's own half is `scrubbed_environment()`: the terminal is
spawned without the session markers an agent CLI sets in its shells, so an agent DPlanner
launches is a top-level session with a transcript of its own, whatever started DPlanner.
The scrub is a list, not the prefix — what Claude Code sets in every shell it runs
(`CLAUDECODE`, the parent's session id, the child-session flag that turns transcript
persistence off, its pid, the effort, the agent flag) and what it scrubs itself before a
session that must stand on its own (its exec path, the trace id), read off the 2.1 binary
rather than guessed, plus any variable under its prefix naming a session, a parent, a
child or the messaging bridge (a 2.1.258 shell carries the parent's bridge socket and
token, which the list did not name and the rule now does) — because the same prefix
carries the person's configuration (`CLAUDE_CONFIG_DIR`,
`CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_MAX_OUTPUT_TOKENS`), and an agent launched without
that cannot sign in. The first version named two markers and a rule; the rule caught the
session id but not the pid, and a list read off the binary is the honest fix.

**Nothing said not to kill by pattern.** The skill's *Cutting agent steps* and the
briefing's preamble now both do: other agents work beside you in the same repository, their
processes carry the same names and paths as yours, kill only by a pid your own shell
started. The preamble is the one text every executing agent reads; the skill is where the
convention lives for an agent driving the plan by hand.

One more thing the incident cost was the way back. The Claude preset now names the run's
session up front (`--session-id {session}`, a UUID minted per launch by `prepare`), the
wrapper writes it into the shell facts beside `dir` (where the agent works, recorded once
it is in place — a worktree, usually) and `resume` (`cd "<dir>" && claude --resume <id>`,
composed from the preset's `resume` template, only for a preset's own command since a
custom command's resume syntax is unknown), and prints the same command above *Press
Enter* when a run ends badly. The Agents browser shows it under an ended row. A *Resume
Agent* verb that opens a terminal on it is the obvious next step and is deliberately not
built yet: the hint is what the recovery needed, and a second launch path is a feature to
ask for.

**A preset that changes carries the texts it replaced.** The settings page stores the
picked preset's *text* — the dropdown reflects the field, which is what lets a preset be
edited into a custom command — so a machine that picked Claude Code before `--session-id`
was added held `claude --permission-mode plan {prompt}` from then on: read as Custom,
launched without a session id, never resumable, and no later change to the preset
reached it. `AgentPreset.superseded` lists every command text the preset has shipped, and
`launcher.current_command` maps a stored one to the current — the settings page reads
through it, so the dropdown shows the preset again, and so do the wrapper and the resume
hint. The same idea as a `Takeover` for module data: the old spelling is the contract,
and the successor carries it.

### The peer reports back through its run directory

A detached terminal tells nobody when it is done, and the four platforms' terminals have
no shared way to ask. What every one of them does have is the wrapper script: the one
process that starts the agent and is still there when it exits. So the script reports,
beside the prompt it was launched with — the shell's facts on start (`shell`: tty, pid,
tmux pane, `$TERM_PROGRAM`, the window title it set) and the agent's exit status at the
end (`exit`; the word `closed` from a HUP trap when the terminal was shut on it). Two
plain files, no terminal-specific hook, so the report is the same for every row of the
terminal table and for an agent CLI nobody has heard of yet.

The other half is the window's, in `modules/step_agent_run/`. It remembers every run it
launched in the **user's store** (`user_config`) — a temp directory and a pid are facts
about this machine, and a per-user file is what a rebuilt window re-adopts from — and
polls them every two seconds *while one is live*. `runs.settle` reads the two files:
exit 0 is *finished*, anything else *failed*, the trap's word or a dead pid *closed*, a
vanished directory *lost*. An ended run clears the step's state the way the launch stamped
it — directly, off the undo stack, with the launch origin — because a chip on a step
nobody is working on is a lie, and the CLI's own `agent-state clear` is the protocol only
for the agent that remembered to send it.

One race is designed around. An agent's last `dplanner status set … done` and its exit
land within a tick of each other, and a window that wrote the exit over a plan it had not
re-read would trip the store's own refusal and leave the user with a conflict notice for
something no person did. So the tick asks the store first — `changed_underneath()`, the
same narrowed answer the library watcher reads — and stands down when it is true. It asks
**only once a run has ended**: the answer is a walk over every plan file, on the GUI
thread, and asked every two seconds for its own sake it stalled a large library's window
for as long as the walk took (300–500 ms, in the journal as `poll` spans) the whole time
an agent ran; settling a run is a handful of stats, so a tick with nothing ended costs
nothing. The
watcher's move is to adopt the change into the live model (*Adopting the other writer's
changes in place*), after which the same module, its runs intact, checks again on the next
tick over a plan it has seen; when the store cannot reconcile and the watcher falls back to
a rebuild, the new module re-adopts its runs from the per-user store and checks then. A
conflict the user has not yet answered keeps the store's answer true and the tick standing
down, which is the rule doing its job: *nothing writes over a file it has not seen* holds
for background writers too.

Finding the window again (*Show Agent Terminal*) is honestly best-effort, and the facts the
script recorded are chosen so the effort mostly succeeds even after the agent has retitled
the window: a tmux pane is selected wherever it is; Terminal and iTerm are asked, through
AppleScript, for the tab on the shell's tty; a Linux terminal that owns its windows (kitty,
Alacritty, xterm, Ghostty) is found by walking the shell's ancestors to the pid that owns
one, with the title as the fallback, through xdotool or wmctrl; Windows activates the
PowerShell pid, then the title. Where a desktop cannot — a Wayland session with neither
tool — the verb is *disabled with the reason*, never hidden: the rule from *Hidden means
absent*. Every provider answers a reason string, so one verb reads them all.

The offer to switch lives in three places, and the gate is the same question asked of the
same run. Tools ▸ Agent List is the quick switch — a data child menu (see *A child menu of
data is rebuilt when it opens*) listing every live run this window launched, one entry per
run raising its terminal, the browser under a rule at the bottom; the browser's rows and
*Show Agent Terminal* are the other two. All three ask `focus_reason`, which is **per run,
not per desktop**: it reads the shell's recorded facts in the same order `focus` tries
them, so a run inside a tmux pane stays offered on a Wayland session with no window tool —
tmux can select the pane wherever its client is — while the run in a bare window beside it
is greyed with what the desktop would need. Gating every row on the desktop's answer alone
was the first version, and it greyed switches that would have worked.

### A worktree is the step's decision, and the run is named after the step

Whether an agent works in a fresh git worktree was a global switch on the Agent settings
page. It is the agent aspect's own field now — `"worktree": false` is the opt-out, absence
is on — because the question is about the step, not the machine: nearly every step wants
isolation, and the few that do not (a release cut that must tag the checkout the window
shows, a conflict the window hands over, a step that only reads) are the same few on
every machine. A global switch is also one nobody dares turn off, since turning it off for
one step turns it off for the twenty launched after it. The Agent tab carries the checkbox
beside Run Agent, `dplanner agent worktree <step> off` and `step add --no-worktree` are the
CLI's word, and the skill tells an agent to leave it on unless the step genuinely must
share the working tree.

**The worktree is prepared by the wrapper script, and a worktree it cannot prepare stops
the run.** The first version put the worktrees under `.dplanner/worktrees/` and wrapped
every git call in `|| true`. Two things followed. A project kept in a subfolder of its
repository leaves a `.dplanner` pointer *file* at the root (FORMAT.md's pointer), so `git
worktree add` under that path failed with *Not a directory* on every such project; and the
script, having hidden the failure, carried on in the main checkout — so two agents
launched "into fresh worktrees" edited one checkout on one branch, which is the bug this
section exists for. The worktrees live in `.dplanner-worktrees/` now, and the script
prunes stale registrations, reuses the branch when it exists, verifies the tree is a
linked worktree (a `.git` *file*), and otherwise prints git's reason, waits for Enter and
writes `1` to the exit file — the window reports *failed (exit 1)*, the same way it reports
any agent that died. Never the main checkout by accident.

**The run is named after the step, once.** `agent_briefing.worktree.run_name(key, ticket, title)` —
`f7-PROJ-12-build-the-modal`, made ref-safe — is the worktree's directory, the branch's
last component and the start of the terminal's title. The key first so `git branch` sorts
by step, the ticket so the branch answers the tracker too, the slug for the person reading
the list. The pieces are aspects the launcher never reads, so `run_name_of(step)` beside it
composes them (`planning.kinds.key_of`, the ticket aspect) and both the launch and the
briefing call it, because the **briefing names the worktree**: its preamble tells the
agent to confirm `git rev-parse --show-toplevel` ends in that directory and the branch is
`agent/<name>`, and to stop if either differs. The check costs the agent two commands and
closes the gap the silent script left — a run that somehow lands in the main checkout is
refused by the agent, not just by the script. A step whose worktree is off is told so
instead, and warned that it shares the developer's tree.

**Inside the worktree the plan of record is still the library's.** The plan is usually
versioned, so the walk `cli/discovery.py` makes from the agent's working directory finds
the *branch's copy* of `project.dproj` — a directory not in the library. Resolving that
copy would write the agent's status into a file nobody is looking at until the branch
merges. So a project found by the walk that is not in the library, but whose `project.dproj`
declares the id of one that is, resolves to the library's project — the one the window
shows and autosaves — and the repository match below it counts a linked worktree as its
main checkout (`core/storage/git.py::main_checkout`, which the skill's worktree warning
reads too). The agent's `dplanner` calls therefore land where the person is looking, and
the branch's copy of the plan is never touched, so a merge never has to reconcile it.

### An agent may be opened with nothing to do

Every launch above hands the agent a briefing. The planning that comes *before* the plan
has none to hand: a spec has been imported, the graph is empty, and what the person wants
is an agent sitting in the code with its own prompt, so they can talk it into a set of
steps. Running that through *Run Agent* is impossible twice over — there is no step to be
about, and Claude Code's briefed command opens in **plan mode**, which is exactly the mode
a session that is about to write a plan file must not be in.

So *Project ▸ Open Agent in Code* is its own verb, on the project rather than a step, and
it is the same machinery with two things taken away: no briefing, and a different
invocation. It offers the same launch profiles in the same child menu, opens in the same
place a step's agent would (the code checkout, else the plan's own repository), and
exports the same `DPLANNER_PROJECT`, so the agent's first `dplanner step add` lands in the
project it was opened on.

**The bare invocation is written down, never derived.** `AgentHarness.open_command` sits
beside `command`: `claude`, `codex`, `opencode`. The tempting alternative is to take the
briefed command and drop its `{prompt}` — and for Claude that leaves `--permission-mode
plan` behind, which is the one thing this launch exists to avoid. A flag's purpose is the
vendor's fact and not a string operation, so each harness states both invocations and a
command nothing here knows (a hand-written one) greys the entry with that as its reason,
rather than being guessed at.

**Nothing to hand over is a launch shape, not a special case.** `launcher.prepare` called
with no prompt text writes no `prompt.md` and gives the wrapper no opening line, so one
code path still writes the script, prepares nothing, exports the project and spawns the
terminal. The run has no step, so — like the Problems panel's and the conflict hand-over's
— it is not tracked, claims nothing *in progress*, and gets no usage row. And it has no
prompt, which is the one place it differs from them on screen: a launch that opens no
terminal ends in a notice rather than the prompt fallback, because there is no briefing to
put in the person's hands.

### Which terminal opens is a table, not a chain

The platform `if`-chain that used to resolve a terminal is one table now, `TERMINALS`:
a row per known terminal per platform — Terminal, iTerm and Ghostty on macOS; Windows
Terminal, the Command Prompt and Ghostty on Windows; Ghostty, kitty, Alacritty, foot,
GNOME Terminal, Konsole and xterm on Linux, with tmux *last* on the two platforms it runs
on — each with the command that opens it on the wrapper script and a probe (a binary on
PATH, an application bundle, an environment variable) saying whether it is installed.
*Automatic* is the first installed row, which is the platform's own default terminal, so
an untouched setting behaves the way the machine does; the settings dropdown lists the
same rows, marks the ones the probe cannot find, and pre-fills the editable template —
the agent presets' pattern, applied to the second choice on the same page. One table with
two readers is what keeps the dropdown from ever offering a terminal the launch would not
find, and a new terminal is a row rather than a branch.

**tmux was first, and that was the bug that looked like Ghostty's.** A DPlanner started
from a shell inside tmux inherits `$TMUX`, its probe answered yes, and Automatic opened
every agent with `tmux new-window` — a new window in whatever session tmux called current,
inside a Ghostty window the person was typing in, and a different one each time the
current session changed. It read as "the agent lands in a random split". Ghostty itself
never does that: its `-e` forces a fresh process (`gtk-single-instance=false`) with a
window of its own. So tmux is the last resort — what Automatic reaches for over ssh with
no terminal installed — and a desktop application's agent gets a desktop window.

### An agent CLI is a harness, and a harness is a module

The launcher used to carry a `PRESETS` table of three agent commands and a list of the
environment variables Claude Code sets in its shells, and every other fact about an agent
CLI — whether it can be resumed, where it keeps its transcripts — had nowhere to go. Codex
support was the second CLI to need such facts, and a second block of `if preset.id ==
"codex"` in the launcher was the shape to refuse.

So an agent CLI is a **harness** now (`domain/agents.py`), and each one is a module:
`modules/agent_claude/`, `agent_codex/`, `agent_opencode/`, each a Qt-free `harness.py`
exporting one `AgentHarness` — the command with its placeholders, the resume template,
the texts the command shipped earlier, the shell markers, and a `report` reader — and the
composition root's `agent_harnesses()` is the tuple every reader takes as an argument:
the launcher, the settings page, the run tracker, the `usage` verbs and the entry point's
shell guard. The contract lives in `domain/` beside `assets.py` and `aspects.py` for the
same reason those do: it must be importable without Qt, and it is what modules agree
on rather than what any one of them owns. Three consequences were decided deliberately.

**Capabilities are derived from the record, never declared beside it.** A settings page
wants to say *Codex — resumes, counts tokens*, and the temptation is a `capabilities`
tuple on the record. But a tuple beside the fields it describes is a second statement
that can disagree with the first — a harness whose `resume` template was removed and
whose tuple still said *resumes*. So `names_session` is *is `{session}` in the command*,
`counts_tokens` is *is there a reader*, `resumes` is *a resume template, and a way to the
id* — and `capabilities()` words them. Nothing to keep in step.

**A harness that mints its own id is found afterwards, by where and when.** Claude names
its session up front (`--session-id`, minted per launch), and that is the best case: the
id is known before the shell opens, the wrapper writes it into the facts, and the resume
command is printed on exit. Codex and OpenCode do not take an id; they mint one. Both,
though, record where a session started and when — Codex in a rollout file whose first
line carries the `cwd`, OpenCode in a database row with a `directory` — and the launcher
knows both facts about every run it started. So a harness's `report(RunFacts)` finds the
run by directory and launch time (the earliest record started there at or after the
launch, with two minutes' slack for a stamp taken after the shell) and answers the id
with the usage. A step's worktree is one directory per run, which makes the match exact;
a step that works in the checkout itself shares it with other runs, and the start time
tells them apart. The found id is written back onto the run, and *that* is what makes a
Codex run resumable in the Agents browser — parity with Claude by a different route,
without a flag Codex does not have.

**The reader is tolerant by construction.** Every one of these formats is the vendor's
own, undocumented (Claude Code says so in as many words) and free to change between
releases. A reader that raised on a changed field would take the whole run tracker down
on the day a vendor shipped; one that answers `None` leaves the run ended as before with
no tokens beside it, which is the honest report. The OpenTelemetry metrics Claude Code
exports are the supported channel — `claude_code.token.usage` with a `session.id` on
every point — and they need an OTLP collector listening on this machine, which is a
feature to build when a transcript reader has failed, not before. Its console exporter
writes to the agent's own stdout, so it cannot serve an interactive session.

### A launch profile is a name over the two choices

Run Agent has always asked two questions — which agent, which terminal — and the settings
page answered each once, for the whole machine. Two terminals of agents at once broke
that: a Claude run in a Ghostty window for the step under the cursor, and four Codex runs
side by side in a multiplexer for the four the lasso caught, are not one setting with a
different value; they are two ways of working a person switches between all day.

A **profile** (`agent_launch/profiles.py`) is the two answers under a name,
and the list of them is the setting. The first is the default — what `agent.run` itself
runs, so the Agent tab's button and the palette need no picker — and the whole list is
*Step ▸ Run Agent*, a data child menu rebuilt on open so a profile added in Settings is
offered at once, the default marked. Each entry is greyed with its own reason: the
profile's terminal is one probe (`launcher.template_refusal` — *herdr is not installed*,
*not inside a tmux session*), asked before any step is, because it is the profile's
refusal and not the selection's. Over a multi-selection every chosen step goes through
the one picked profile, one pane per step in a multiplexer — which is the gesture the
whole thing exists for: see four ready steps on the board, select them, pick *Codex in
herdr*, and they are running side by side.

A profile's name is derived until it is typed. A new profile is a copy of the picked one
named by what it does — *Claude Code in herdr* — and the usual next moves, changing the
terminal and then the agent, keep renaming it to match, so the list never holds a *Default
copy* that is actually Codex in tmux. The rule that makes this safe is one comparison in
`update_profile`: a name is *derived* while it still reads as what the profile's old
choices suggested (numbered or not), and a name that reads as anything else was a
person's and is kept. No flag is stored, so an old profile list needs no migration; a
typed name that happens to equal the suggestion behaves as derived, which is the right
answer for a name that says what the profile does. Names stay unique either way — *Run
Agent With* and the default lookup go by name — and a typed duplicate is numbered rather
than refused, since a settings field is no place for a modal.

The two single settings the profiles replaced are read as the default profile when no
list has been stored, so a machine configured before profiles existed keeps its choices
without anybody retyping them — the same idea as a harness carrying the command texts it
shipped earlier. Profiles are per user, per machine (`user_config`), never the plan.

**The verb has one seat, and it is the child menu.** *Run Agent…* used to sit flat beside
*Run Agent With ▸*, two entries for one act, and the flat one hid the choice the other
offered. Now the child menu *is* Run Agent: the profiles, a rule, and *Manage Agent
Profiles…* — the way to the settings page from the menu that needs it, through the
settings module's `open(section)` handed over by the root. The verb `agent.run` still
exists — every button and the palette run it — but it is registered `in_menus=False`:
the menu bar seats no QAction for it and the pop-ups skip it, while it keeps its menu and
its submenu (the child's title) so the palette can say *Step ▸ Run Agent* under it. A
verb whose seat is a data menu's own entries is a new shape for the registry; it owns
no shortcut, because only a seated QAction fires one, and the registry refuses the pair.

**The list is seeded once, and a removal stands.** A person should not have to build
*Codex in herdr* by hand to find out it exists, and a dropdown that offers one choice
teaches nothing. `seed_profiles` runs when the window is built and appends every harness
in Ghostty, herdr and Automatic (the platform's own terminal) after what is stored — the
stored default keeps its place, and a pairing a stored profile already *means* is skipped
by its choices rather than its name, so a hand-named *Claude in Ghostty* is never doubled.
The `profiles_seeded` flag is written with the list: a seeded profile the person removes
is not put back on the next start, which is what makes the seed a migration and not a
default the list keeps falling back to.

**Detection is the same question asked on purpose.** *Add Detected…* on the settings page
opens a fit dialog listing every harness in every terminal row of this platform, and
Automatic, with what the machine has of each — the agent's command on PATH, the terminal
by its row's probe (`detect_pairings`, Qt-free; the dialog is `detect_dialog.py`). A
pairing both halves of which are installed and which the list does not hold is ticked;
the rest are listed with the reason (*codex not found*, *already in the list*) rather than
dropped, so the person sees what installing a tool would unlock. The dialog only answers
— `chosen()` — and the page writes through `add_profiles`, the seed's own appender, so a
pairing already meant is never doubled whichever door it came in by. That split is
deliberate: the first-start checklist that is coming hosts the same rows, and it should
need the detection and the appender, not the dialog.

### A multiplexer is a row, and a two-call one is one template

herdr — the multiplexer built for exactly this, a headless server the person's terminal
attaches to, with a workspace per repository and an agent-state sidebar — adds a shell in
two calls: `herdr workspace create` prints, as JSON, the pane it made, and `herdr pane run
<pane> <command…>` types a command into it. The terminal table's one template per row
cannot say that, and the honest alternatives were a Python opener per multiplexer (a
second table of callables beside the first) or a `sh -c` one-liner nobody could read in
a settings field.

The row is `herdr workspace create … && herdr pane run {pane} {script}`
instead: `launcher.spawn` splits a command at its `&&` tokens, runs the stages in turn to
completion, and fills `{pane}` in a later stage with what the earlier one printed (a
`pane_id` in its JSON, else its last line). It is what a person would type, it stays a
row a person can edit, and tmux's `new-window -P -F '#{pane_id}'` or `wezterm cli spawn`
would feed the same `{pane}` if a second call ever needed it. A stage that fails is a
reason string and no run: the fallback dialog hands the prompt over, exactly as when no
terminal exists, because a workspace that could not be created is not a shell somebody
is in. The wrapper script records each multiplexer's own name for the pane from the
variables it sets (`HERDR_WORKSPACE_ID`, `HERDR_TAB_ID`, `WEZTERM_PANE`, beside tmux's
`TMUX_PANE`), so *Show Agent Terminal* selects the pane through the multiplexer before
it asks the desktop for a window — `terminal.focus_reason`'s per-run rule, extended.

herdr, zellij and tmux sit last in every platform's list, marked `multiplexer`: Automatic
still opens a window, and a multiplexer is what a profile picks on purpose.

### Usage is a ledger, harvested by anyone

Which step cost how many tokens is the question a project's owner asks at the end of a
week. The first answer read the vendor's record once, from the window's poll, when it saw a
shell end, and kept a row on the step. Measured on 2026-10-01
(`docs/research/2026-10-01-agent-token-tracking.md`) it recorded 18 to 42% of what runs
spent, and the ways it missed were structural, not bugs to patch one by one:

- **Subagents are separate records.** Claude Code writes each one beside the session, Codex
  makes it a thread of its own, OpenCode a child session. A reader of one file sees the
  main agent only.
- **Nothing reliably sees a run end.** Agents run in a multiplexer the person closes by hand
  once the PR is up; the window is often not running; `/tmp`, where the run directory and
  its exit file live, is emptied by a reboot; the run list is QSettings, which only the
  window reads. One missed moment was a run never counted.
- **Two writers on one step file collide**, and a deleted step took its history with it.

So usage left the model. **A run is a record in the project's `ledger/`, written at launch
and filled by a harvest that anybody may run at any time** (`domain/ledger.py`,
`modules/agent_usage/harvest.py`). The launch knows the step, the agent CLI, where it
works and — for Claude — the session; everything after is a re-read of the vendor's own
records into the same file. Because that read is idempotent, the triggers do not have to be
reliable, only plentiful: the wrapper script runs `dplanner usage harvest` the moment the
agent exits, with no window; the window does it when its poll sees the end; a sweep at start
and every five minutes reads every run of this machine not read since it ended. Missing one
costs nothing.

**One file per run, one writer per file.** The run id is minted from the clock and a random
suffix; only the machine that launched the run can read the vendor records, so only it
writes. Nothing locks, nothing is lost, and two machines' files never conflict in git — the
at-work claim's *one file per claim*, committed this time because what a run cost is the
plan's history. Outside `PLAN_ENTRIES`, so recording usage never makes a window adopt
anything and never trips the stale check; Save commits it because Save's scope is the whole
project directory. A sweep's write that would change nothing is skipped, and a harvest that
began before the wrapper wrote the exit re-reads the file before writing so the exit
survives.

**A session minted by the CLI is claimed once.** Codex and OpenCode cannot be told a session
id; the run is the earliest session in its directory after its launch *that no other record
owns*, and the harvest writes it into the record, so from then on it is read by id. Two runs
in one checkout no longer take the same session.

**Three counts, never a price.** `in` (fresh input and cache writes), `cached` (cache reads)
and `out`, per model, per agent. Cache reads are their own number because they dwarf the
rest — eleven million against half a million fresh in one measured session — and one
"input" figure would mostly measure context size. Dollars are left out on purpose: the price
of a token depends on the plan, the tier, the mode and the region, and on a subscription
nothing is spent at all; a cost is a derivation somebody can add over the stored counts.

**What is not covered, said out loud:** an agent started outside Run Agent (`dplanner usage
record` adopts one); a `/clear` inside a Claude session, which starts a new session the
record does not follow; a run never harvested before Claude Code deletes its transcript
after thirty days.

### Expenditure is the order, in tokens

The question after *what did this run cost* is *how is the plan doing against what we
thought* — read down the order, which is how the work will be done. So the answer is the
Order tab with other columns, not a report of its own: the rows, the switches, the
gestures and the milestone marks are `framework/step_table.py`'s `StepTable`, which both
tabs host. The tab lived in `step_order` at first, because it *is* the order; it moved to
`agent_usage`, because what it reads is the ledger — its Deps were three callbacks that
existed only to hand the order module the ledger's facts, and a package named for the order
held the one view of what agents spent. Two packages may not import each other's widgets, so
the shared row look went down to `framework/`, where both can reach it.

**Expected is learned, and not from the steps it is compared with.** Nobody estimates
tokens; people estimate days. A rate — tokens of work (fresh input and output) per
estimated day over finished steps that have both — turns an estimate into an expectation.
Learned from this project's own finished steps, the running offset at the last finished
row is zero by construction, which says nothing; so the root learns it from the library's
other projects first and from this one only when nothing else has history, and the tooltip
says which. No history, no expected column: an invented number would be read as a budget.

**Tokens, never money**, for the ledger's reason: the price depends on the plan, the tier,
the mode and the region, and on a subscription nothing is spent. **By model** is a switch
rather than the default because a pair of columns per model is too wide for every day and
right for the day a playbook mixes three; the CSV is long (a row per step and model)
because a spreadsheet pivots on rows, and a new model must add rows, never columns.

### What a run was handed

A ledger of what runs *cost* left the other half unrecorded: how big the briefing was that
each one opened with. It is the number somebody wants the moment a step looks expensive, and
it is the only one DPlanner itself is responsible for — the tokens are the model's doing, the
briefing is ours. Nothing kept it, which is why a whole pass had to be measured with a
throwaway script before anything could be fixed.

It is measured once, in `launcher.prepare` — the one function that knows what actually
reached `prompt.md`, rather than what some caller believed it was sending — and carried on
`LaunchFiles`, which `record_launch` already hands to the tracker, so no signature between
the two moved.

**The run is its home, and the ledger record is a copy.** `AgentRun.prompt_chars` is what
the Agents browser reads, and the launch writes it into the run's ledger record, which now
exists from the first moment — a record with no agents yet says nothing was read, never
that nothing was spent.
The tempting fix — write a usage row at launch with zero tokens — is worse than it looks:
`usage.totals` would then return `Usage(0, 0)` and the step would *claim it spent nothing*
where it currently and correctly says nothing at all. A size is a fact about the run; tokens
are a fact about the plan's cost. Keeping them in the stores that own each is what lets a
live run say one without lying about the other.

**No format bump, and the precedent that looks like it applies does not.** `progress_history`
went to format 2 for its `saved` key so an older build would refuse to rewrite the entry
rather than drop what somebody had authored. Here `usage.with_row` copies every kept row
**verbatim** and `rows()` filters without rebuilding, so an older build cannot lose
`prompt_chars` — and it re-stamps the entry to its own version on the next write anyway, so
the guard would not even guard. `ModuleDataFormat` requires one migration function per
version, so the bump would have put an identity function in the tree for no reader. The rule
worth keeping from this: **bump when an older writer would destroy the new key, not when one
merely would not write it.**

**A size does not total.** Two briefings added together is not a quantity anybody spends, so
`usage list`, `usage.totals` and the step's own phrase stay tokens-only, and `brief_words`
says its unit out loud — *briefed 18.4k chars* — because the number beside it on the same
line is tokens and two magnitudes in one row must not be readable as the same quantity.

**And the launch became a span.** There was none: Run Agent was timed only by the `action`
span `ActionRegistry.run` opens. A detail on that span is not available to a verb body —
`Telemetry.recent()` and `open_spans()` hand out **copies** by deliberate design, which
`tests/core/test_telemetry.py` pins — and adding an accessor for the live span would be a
write path into shared state, in `core/`, for one caller. It would also be wrong: one gesture
launches a shell per chosen step, so three launches are three sizes and could never be one
key on the parent. A child `action` span per launch nests under the gesture for free, renders
in *Debug ▸ Telemetry* with no UI work, and is the shape the rest of the application already
uses. The cost, named: a launch under the 20 ms journal floor is absent from the file — which
only happens where a test monkeypatches the spawn, and the durable record is the run and the
row in any case.

### The briefing says what each block cost

`agent prompt --json` returned the briefing as one opaque string, and `PromptSegment` carried
only a coarse `origin` — so the two `protocol` blocks were indistinguishable from each other,
as were the two `project` blocks, and both notes blocks fused into a single `inherited`
segment. Finding out where 47,000 characters went therefore meant monkeypatching `assemble`
from a script. A measurement that has to be re-invented is one nobody repeats, and "is the
briefing too big?" is now a question with a standing answer: one segment per block, each
carrying its own heading, and `segments` (origin, heading, chars) plus `chars` on the JSON.
The join invariant is untouched — the segment texts still concatenate to exactly the text
that is sent, which is what lets the Agent tab colour it without ever showing something else.
