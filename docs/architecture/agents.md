# Agents — Run Agent, worktrees, run directories, usage, harnesses and profiles

The reasoning behind `.claude/rules/agents.md`: the rules there are the short, imperative form,
and this file is why. `ARCHITECTURE.md` is the index of every area.

## The description is the instructions

**An agent step is briefed with its own description.** A description and a separate agent
instruction draw a distinction ("what it is" versus "how to do it") that reads well in a
docstring and nowhere else: in practice the two say the same thing twice, or an agent driving
the CLI sets one when it means the other, and a step with a rich description and no instruction
cannot be briefed at all. (*decisions.md* has what it replaced.) Marking a step for agent
execution is the `step_agent_instruction` aspect's `module_data` entry (Step ▸ Type ▸ Agent,
`dplanner agent on`, `step add --agent`); the briefing's `## Instructions` block is the
description body and its images, and the separate `## Description` context section is omitted so
the text appears exactly once.

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
brief a step differently. A described, uninstructed step renders its text as
`## Instructions` — the heading the executing agent actually obeys.

**A landing is the one step whose instructions are generated.** What a landing must do is
the same for every landing — check its stretch has merged, merge the mainline in, open the
branch's PR — and what differs is data the graph already holds: the branch, its base and the
steps on it. Asking somebody to write that protocol into every landing's description would be
asking for it to drift from the branch model, so `instruction` hands a landing to
`_landing_instruction`, which writes it from the stretch it closes. The step's own prose is
not dropped: it rides inside the block as *what else to see to*, and is still said once.

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
  the window word refuses on — an agent CLI's marker in the environment, read by
  `domain/agents.py`'s `shell_marker` over the composition root's `agent_harnesses()`,
  which the entry point and the root's `status set` wiring each read directly (`shell_marker`
  defaults its `env` to this process's own, so neither caller passes it). **A person's own
  terminal and the window are never asked**: the developer marking a step done is the
  acceptance.
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

## One launch under both surfaces

`dplanner agent run <step>` is the launch a director or a daemon makes, and the window's
Run Agent is the same launch with a person's questions put in front of it. The 10-04 run
showed what two launches cost: the director rebuilt Run Agent by hand for every step, and
"forgot to set in-progress" and "a landing on a new branch instead of the feature branch"
were both a hand-built launch drifting from the real one. So there is one
(`agent_launch/launch.py`), and both surfaces run it in one order:

1. **The step's launch lock**, taken first and held until the run started or nothing was
   written — an OS lock, `supervisor.launching`, so a dead launcher's is free at once. Two
   `agent run`s of one step, or a window and a terminal, both passed the "no run yet" check
   before either wrote a record, and two agents ran; under the lock the second is refused.
2. **The gate**: the step's own facts, the branch plan's refusal (two stretches that do not
   nest leave a plan with nothing *but* a refusal, which would otherwise launch from the
   default branch), where it works, and a headless run not over — resumed through `agent
   supervise`, never launched a second time.
3. **Where it works** (`worktree_of`, `place`). The worktree is prepared by git *in Python*
   — `agent_briefing/worktree.py`'s `prepare` — not by the terminal's wrapper script: a
   headless run has no script. It is the slow part, a fetch, so the window runs it on a task
   from plain values, and **re-checks them when it returns**: a step renamed meanwhile would
   be briefed to stop unless it stands in the new worktree while it stands in the old one,
   so it is refused with the reason. The checkout gets the checkout timeout, and a worktree
   git left half made — still under the `initializing` lock `worktree add` holds until its
   checkout finished, or with no commit checked out — is removed and made again, never
   reused.
4. **Its files and its record** (`prepare_run`): `prompt.md` and its assets —
   `config_dir()/runs/<run>/` for a headless run — and the run's ledger record, format 2 for
   headless (`stage`, `attempt`, a session minted for a harness that names one), format 1 for
   a terminal. The record is the launch's intent.
5. **The claim, saved** (`workflows.py`'s `run_agent`), and **then the start**
   (`start_run`) as its follow-up — `core.md`'s *A workflow is one function under both
   surfaces*: the change is persisted, then the effect is performed. Starting first lost
   the claim whenever another writer made the flush refuse, with the agent already running.
   A save that is refused starts nothing and takes the record back (the CLI's
   `CliContext.unwritten`, the window's `flush` answer). A start that fails takes the record
   back and **withdraws the claim** — a second change (`workflows.withdraw`), which restores
   the entry the step had unless somebody has changed it since — and says what happened.
   The window applies both off the undo stack, since what they record cannot be undone.

**A launch interrupted between its record and its start is settled by `revive`.** Its record
has no turn and no supervisor holds it; once nobody holds the step's launch lock either, the
run is started when its step still reads in progress, and its record deleted when it does
not. The window does that at its start, and `agent run` before it takes its own lock.
**Everything is read again inside the lock, from disk**: a caller that loaded the step as
pending before another launch saved its claim would otherwise delete that launch's record in
the moment between its start and its supervisor taking the run's lock — so the status comes
from the plan on disk (`claimed_on_disk`), and a record is deleted only past a two-minute
grace, with no supervisor holding it. The same reasoning keeps a failed start's rollback
under the lock until the withdrawal is written, and has the window save before every start:
a step that already read in progress may hold a claim nobody saved.

**The plan's half is the workflow, and the rest is not.** A `workflows.py` returns a
`Change` and never persists anything; a launch writes files, runs git and spawns processes,
so those live in the Qt-free `launch.py`, and the workflow is the claim and its withdrawal.

**It replaced the intent file.** `launch_unattended` wrote an intent (`intents.py`) before
its shell and forgot it once its claim was on disk; nothing ever called it. The run record
written before the start carries the same fact where every reader already looks
(`decisions.md`, 2026-10-07).

**What the window asks, the CLI refuses.** The window keeps a person's questions: the graph
gate, the clone, the limit on a selection, and the prompt fallback when no terminal opens.
`agent run` has nobody to ask, so each is a sentence and an exit 1 — prerequisites not done
until `--anyway`, a repository not checked out here naming Run Agent, which clones. It is
headless by default, and `--profile` picks the profile whose agent command names the harness.

**A supervisor is the build and the library that launched its run.** `start_detached` runs
`sys.executable -m dplanner --library <path>`, never whatever `dplanner` is on PATH, and every
turn's environment carries `DPLANNER_LIBRARY`, `DPLANNER_PROJECT` and `DPLANNER_RUN`: with two
projects planning one repository, an agent's `dplanner` calls are otherwise ambiguous — or
reach whatever project the caller's shell named — and a launch from `--library` elsewhere
loses its library altogether.

**A machine's start picks up its lost turns.** A reboot or a killed supervisor leaves a run
whose last turn never ended; `revive` starts a supervisor for each such run of this machine
that no supervisor holds, which ends the turn `failed`/`lost` and retries it. A parked run —
its last turn ended — waits for a person and is never touched, unless it is waiting for its
reset, or holds an answer — the clock's, a person's on another machine — that no supervisor
delivered before it died: each of those has a supervisor's work to do, so `revive` starts one.

**Plan mode is waiting on a person, and says so.** The Claude preset starts in plan mode, so
a launched Claude writes a plan and waits for somebody to approve it — and a session in plan
mode runs nothing that writes, so it never reports `plan-for-review` itself. The launch
stamp carries it instead (`plans_first`, read off the command through the harness's
`plan_mode` words, so a profile edited out of plan mode launches an agent that does not
wait), and `asks_person` reads it with the states that ask: such a step is *Waits for you*
on the boards and in `progression show` (*Progression is the status-aware frontier*).

The rules are in `.claude/rules/agents.md`.

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
instructions*) and, after it, the notes index. **A landing's briefing leaves it out**: the
standing instruction is written for the work on a stretch — in the 10-04 run it said "work in
your worktree, open a PR into the branch", which a landing, working on the branch itself and
opening the branch's own PR, must not do — and a landing's instructions are generated from
the stretch it closes, so they already say all that applies.

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
through the launch's workflow — `agent_launch/workflows.py`'s `run_agent`, a `Change` built
from `planning/status.py`'s own `status_command`, so the status module keeps the only place
its words are spelled.

Three decisions sit in that one line.

**It is off the undo stack**, with an origin of its own, exactly like the launch stamp
beside it (*The peer reports back through its run directory* has that reasoning). The
claim rides on something Ctrl+Z cannot take back — a detached shell now exists — and an
undo entry would let the next Ctrl+Z file the step as pending while an agent is still
working in it. The claim is no command at all when the step already
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
other maker is `dplanner agent run`, which always claims: *On launch* is a switch for a
person at a window, and a launch nobody watches must say the step was taken (*One launch
under both surfaces*).

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
(`agent_briefing.protocol.opening_prompt`): *read your briefing in `<file>` in full, then follow it*. The
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
that cannot sign in. A rule over the prefix alone catches the session id but not the pid;
a list read off the binary does not guess.

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
would grey switches that work.

### A worktree is the step's decision, and the run is named after the step

Whether an agent works in a fresh git worktree is the agent aspect's own field —
`"worktree": false` is the opt-out, absence is on — not a switch on the settings page,
because the question is about the step, not the machine: nearly every step wants
isolation, and the few that do not (a release cut that must tag the checkout the window
shows, a conflict the window hands over, a step that only reads) are the same few on
every machine. A global switch is also one nobody dares turn off, since turning it off for
one step turns it off for the twenty launched after it. The Agent tab carries the checkbox
beside Run Agent, `dplanner agent worktree <step> off` and `step add --no-worktree` are the
CLI's word, and the skill tells an agent to leave it on unless the step genuinely must
share the working tree.

**The worktree is prepared before the run, and a worktree that cannot be prepared stops
it.** A project kept in a subfolder of its repository leaves a `.dplanner` pointer
*file* at the root (FORMAT.md's pointer), so a worktree under `.dplanner/` fails with *Not a
directory*; and a script that hid such a failure carried on in the main checkout — so two
agents launched "into fresh worktrees" edited one checkout on one branch, which is the bug
this section exists for. So the worktrees live in `.dplanner-worktrees/`, and
`agent_briefing/worktree.py`'s `prepare` prunes stale registrations, reuses the branch when
it exists, verifies the tree is a linked worktree (a `.git` *file*), and otherwise refuses
with git's reason — a sentence in the window's status bar, an exit 1 from `agent run` — and
nothing starts. Never the main checkout by accident. It was the wrapper script's job until
a headless run, which has no script, needed the same worktree (*One launch under both
surfaces*).

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
refused by the agent, not just by `prepare`. A step whose worktree is off is told so
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

A terminal is resolved by one table, `TERMINALS`, not a platform `if`-chain:
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

**tmux is last, because first looks like a bug in the terminal.** A DPlanner started
from a shell inside tmux inherits `$TMUX`, so its probe answers yes, and an Automatic that
reached for it would open every agent with `tmux new-window` — a new window in whatever
session tmux calls current, inside a Ghostty window the person is typing in, and a
different one each time the current session changes. It reads as "the agent lands in a
random split". Ghostty itself
never does that: its `-e` forces a fresh process (`gtk-single-instance=false`) with a
window of its own. So tmux is the last resort — what Automatic reaches for over ssh with
no terminal installed — and a desktop application's agent gets a desktop window.

### An agent CLI is a harness, and a harness is a module

An agent CLI carries facts beyond its command — whether it can be resumed, where it keeps
its transcripts, the environment variables it sets in its shells — and a launcher that
held them would grow an `if preset.id == "codex"` block per CLI. So an agent CLI is a
**harness** (`domain/agents.py`), and each one is a module:
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

**A harness has a headless half, and it is a second record.** `AgentHarness.headless` is a
`domain/headless.py` `Headless`: the argv for one unattended turn of a playbook stage, a reader
for the CLI's JSON events and how the turn ended. It is not more templates beside `command`
because nothing about it is a terminal's: the supervisor spawns the argv itself, with no shell
to quote for and no person to wait on, and reads the stream as it comes. Classification is one
function over what the readers normalise, so each CLI's quirks live in its own reader and the
order of the rules is written once; `playbooks.md`'s *Each stage is one headless turn per
harness* has the table and the reasons. **A schema-valid final message always wins**: no prose
heuristic — a refusal, a question, a wait — is applied to a turn that produced one. The prose
heuristics are the fallback for untyped text (opencode, a plan), and when unsure they park
rather than say done, because a false park costs a card or one cheap "continue" turn and a
false done loses work without a word. Two misreadings are accepted as that fallback's known
limits rather than chased: a question quoted at the very end reads as asked, and "waiting on
the build was the bug" reads as an abandoned wait.

### Installed is not usable

A CLI on PATH can still be unable to run a turn: signed out, or broken. Headless, that is
worse than missing — a signed-out Claude retries for minutes before it fails — so each harness
says how to ask (`AgentHarness.sign_in`) and `agent_launch/availability.py` asks in three
levels, stopping at the first that fails: on PATH, a version, signed in. The sign-in probes are
the research's (`docs/research/2026-10-07-headless-agents/` §9): `claude auth status`'s JSON,
`codex login status` (which answers on stderr, so a shell gives both streams together), and
for OpenCode a credential **or** a built-in model — it ran on its own `opencode/*` models with
no login at all, so "0 credentials" alone would have called a working agent dead. Which of
those built-in models are free is not told apart: any model the `opencode` provider lists
counts, and the row says it is running on them.

**Everything goes through a shell bound to the found path.** The harness's probe gets a
`Shell` that runs *its* CLI with arguments; it never names a binary, so a Windows `.cmd` shim
runs as `which` found it, and a probe of another machine — a worker — is another `which` and
another shell, with nothing in a harness to change. OpenCode's credentials are asked of the
CLI rather than read from `auth.json` for the same reason.

**Asking is fresh, reading is cached.** The Setup Checklist's rows always probe — a person who
has just signed in and pressed *Re-check* must see it — and every probe lands in the cache;
`cached` and `why_not` read it and never run a CLI, so a state callback on the UI thread may
ask whether a playbook's agents can run. A reading lives a minute, which is long enough for a
menu opened twice and short enough that a sign-in elsewhere is noticed. One shared cache per
process is the composition root's to wire when Run Playbook reads it (S17); until then each
checklist builds its own.

**A CLI that is not installed is not a problem.** Nobody needs all three, so its row is well
and says it is optional; *An agent CLI* is the row that fails when none can run. Only a CLI
that is there and cannot run asks for something, with its own sign-in command as the remedy.

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
shipped earlier. Profiles are per user, per machine, never the plan — and kept in
`config_dir()/agent-profiles.json`, not QSettings, because `dplanner agent run --profile`
reads them from a terminal that loads no Qt. The window adopts what QSettings held before
the move once (`profiles.adopt`), the list and the seed flag with it, so nothing is seeded
twice. **A file that is there and cannot be read is three states apart from one that is
missing**: read leniently it looked empty, and the next seed wrote the defaults over a
person's list. So `profiles.problem()` names it, the default profile stands in, nothing
writes the file, the window shows a notice and a read-only page, and `agent run` refuses.

**The verb has one seat, and it is the child menu.** A flat *Run Agent…* beside a *Run Agent
With ▸* is two entries for one act, and the flat one hides the choice the other offers. So
the child menu *is* Run Agent: the profiles, a rule, and *Manage Agent
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

## Runs, questions and claims are three records in the plan

*The run record and its supervisor are built (S10, below), the question record and its
door (S13), and the claim record, its verbs and its heartbeat (S18); the inbox cards and the
coordinator are built to these records, and FORMAT.md's* The `ledger` directory *(format
2),* The `questions` directory *and* The `claims` directory *are the formats.* Every one of them
rests on the finding of `docs/research/2026-10-07-headless-agents/`: **DPlanner never
waits on a process for a person.** A headless run is one turn of a process that exits;
whatever needs somebody is recorded and the process ends; the answer resumes the same
session. A closed window, a reboot or an exhausted quota then costs time and nothing else —
but only if what the run was waiting for is written down somewhere that outlives every
process, and readable by whoever is to answer it. That is these three records.

### A run is the ledger record, and the playbook ledger is its runs

The ledger already had the shape a run needs: one file per launch, one writer — the
launching machine, the only one that can read the vendor's records — committed with the
plan, outside `PLAN_ENTRIES`. A second record for "the run" beside it would have meant two
files per launch that must agree, written by the same process at the same moments. So the
record grows to format 2 instead: who ran it (`callsign`, `claim`), which stage of which
playbook it was (`playbook`, `stage`, `attempt` — `playbooks.md`'s words), and its
**turns**. And for the same reason there is no separate playbook ledger: a step's stage
history is its runs read in order, so the two cannot disagree.

**A run is one stage attempt; a resume is a turn.** What resumes is a *session*, and a
session is what the vendor keeps: `claude -p --resume`, `codex exec resume`, `opencode run
-s` all continue the one that parked. Making every resume a run would have split one
conversation's cost and story over several records that each had to name the others. A
fresh session, on the other hand, really is a new attempt and gets a new run — and so does
a **loop-back**, when a gate sends the work back, even when it resumes the same session:
the attempt it fixes is over, its verdict judged that attempt and no later one, and the
next review must be able to say which attempt it read. So a session may span several runs,
and a run is never found by its session. **Which is why usage moves onto the turns**: the
format-1 harvest rewrote a session's cumulative total into the record, and three runs on one
session would have summed it three times. A turn's usage is the slice of the session's
records — subagents included — between the cursors at its start and its end, so every count
is somebody's once, and re-harvesting one turn cannot change another stage's cost. And
**a pass is named, not inferred**: every run and gate question carries `pass`, and the
pass's resolved `settings` — preset, revision, rounds, roles, overrides — are stored once,
on its first run or, when it begins at a gate, its first gate question, so a pass parked for a day resumes
with the cap and reviewer it began with, whatever the step's overrides say now. **The run carries the playbook's results, not
just its cost**: a review run's `verdict` (pass or changes, and typed findings) and a fix
run's `declined` findings with their reasons, so a gate's history is read from runs as a
review's used to be read from its stamps, and `playbooks.md` has why.

**How a turn ended is the record's centre, and it has six words.** The research's five —
`done`, `asked`, `denied`, `limit`, `failed` — exist because exit codes lie: Claude asks in
prose and exits 0, opencode auto-rejects a permission and exits 0 having done nothing. The
supervisor classifies the stream and the result, and writes the class. The sixth,
`stopped`, is for a run a person or the coordinator fenced, or whose step went away:
filing it under `failed` would have the supervisor retry exactly what somebody just stopped.
The retry-or-abandon split of the 10-03 failure classes is the supervisor's count of
`failed` turns, not another word. Running, parked and over are read from the turns, never
stored, so nothing can say a run is parked while its last turn says done.

**A lost turn is found by the machine that ran it, and a takeover fences it.** A turn records
its `pid`, the machine's boot id and the process's start time, because "no `end`" alone
cannot tell a running turn from one a reboot killed, and a pid alone may since belong to
another process. Only that machine can look, so it does, when it starts: a turn whose three
no longer match a live process ends `failed` as `lost`, and the
supervisor's retry takes it from there. A machine that never comes back cannot do even that,
so a takeover writes a `fence` on its runs — the one write to a run from anywhere but its
launcher — and the launcher, fetching before every turn, ends a fenced run rather than
resuming it.

**The run directory leaves `/tmp`.** A parked run must survive a reboot with its stream,
its briefing and DPlanner's copy of the plan it wrote (Claude otherwise leaves only the one
in `~/.claude/plans/`), and `/tmp` is a RAM disk on the machines this runs on — 76 % full in
the 10-04 run. It moves to `config_dir()/runs/<run id>/`, derived from the id and never
stored, because only the launching machine can use it.

### A headless run is driven by its supervisor, and nobody waits on the supervisor

A run needs something to start each turn, read it while it runs and decide what follows —
and that something must outlive the window that asked for it, or closing the window would
kill the work. So it is a process of its own per run, `dplanner agent supervise <run>`
(`modules/agent_supervisor/`), started detached and holding nothing but the run: no library
open, since a process that lives for hours must not hold the store, and its record is
outside the plan's files anyway. It parks rather than waits — the process simply exits on
anything that needs a person — so a parked run costs no process at all, and whoever answers
starts a supervisor again with `--prompt answer|continue|reset|retry`.

**Three guards, because none of the CLIs has them.** The 10-03 probes left all three CLIs
silent on a hung API for over five minutes, and opencode looping forever on a malformed
reply while still emitting events. Silence alone cannot be the test: a twenty-minute test
suite is silent and working. So the **stall** clock runs only while no tool call is open —
each reader keeps the open calls in `TurnLog.tools`, and opencode, which reports a tool only
once it has finished, gets twice the threshold instead — the **runaway** count is events in a
row with nothing produced (`TurnLog.idle`), and the stage's **wall clock** catches a tool that
never returns. Each ends the turn's whole process group, since a CLI's own children (a test
run, a subagent) must die with it — and *the group*, not the CLI: a test worker that ignores
SIGTERM outlives an agent that obeys it, so the group is asked until it is empty and killed
when the grace runs out (Windows has no group to ask, and `taskkill /T /F` reaches the tree
only while its root lives, so it is killed at once). Each records its own `why`; the
classifier would only have said *killed*. Ending the group is also what every way out of a
turn does — a disk that fills mid-tee, a ledger that will not write — so no turn is ever left
running with nobody watching it; such a turn ends `failed` as `supervisor-error`. And the
stream closing is not the turn ending: a CLI can close its output and hang on the way out,
so the guards run until the process has exited, and what it said while it was being killed
— a SIGTERM handler's last totals — is read before the turn is written.

**Retry what time mends, park what it does not.** A crash, a hang, an overrun or a lost turn
retries after 30 s, 2 min and 10 min — failures.md's backoff — resuming the session if its
stream ever named one and starting fresh if not, and a fourth failure in a row parks for a
person: four in a row is a pattern, not luck. A runaway parks at once, because what loops
once loops again; so do a dead login, an empty balance and a retired model, which no wait
mends. A turn that ended waiting on its own background work is told to continue straight
away. A fence read between turns ends the run `stopped`, and a SIGTERM does too, so a run a
person stopped never reads as lost and is never retried.

**Usage is counted from the turn's own stream.** FORMAT.md's design had cursors into each
vendor's session records, so that two runs sharing a session would each count only their
turns. The stream the supervisor already tees *is* exactly one turn's window, so its counts
need no cursor and no new reader per harness; the supervisor writes them as the turn ends,
and the next supervisor counts a lost turn from the stream it left. That makes the
supervisor the record's one writer, so a harvest leaves a headless record alone — beside a
live supervisor it would be a second writer, and the vendor's whole-session total would
count a shared session twice. What it costs is subagents the stream does not report.

**One supervisor per run, one writer at a time, and the turn says which process it was.** A
lock *file* that a supervisor creates and a stale one deletes cannot be made safe: two can
each find the other's file half-written and both go on. So both locks are the operating
system's (`flock`, `msvcrt.locking`) on files nobody deletes, and the system drops them when
their holder dies — there is no staleness to judge. `supervisor.lock` is held for the
supervisor's life. `record.lock` is held across one read-modify-write of the record, by the
supervisor and by `fence()` alike, each re-reading inside it: an atomic replace stops a torn
file but not a lost update, and the update lost would be the fence. **A run's end is written
in the same write as the turn that ended it**, so no crash leaves a finished turn on a run
that reads as parked — which `--prompt retry` would have run again; a supervisor that finds
one anyway ends the run. Each turn records its process's `ProcessStamp` (`core/process.py`:
pid, boot id, start time — a pid alone is reused) the moment it starts, so a supervisor
started after a reboot tells a turn still running from one the machine lost.

### A usage limit waits in its supervisor, and Retry now is an answer

A run that runs out of usage is parked on a `limit` question, and something has to resume
it after the reset. **Its own supervisor waits for the reset**, holding the run's lock and
looking at the question every few seconds, then answers it for the clock and resumes the
session with "your limit has reset". A timer in the window would leave a headless run
stranded whenever no window is open — the coordinator's whole case — and a sweep started by
`agent run` would resume nothing on a machine that launches nothing more. A clock is not a
person, so this is not waiting on one: *Retry now* needs no process at all — it answers the
same question as a person, and the waiting supervisor finds the answer as it finds every
other. A supervisor lost to a reboot is picked up the same way: `revive` starts it bare on a
run parked on a limit with a known reset, it waits, and a reset already past resumes it at once.
**So a SIGTERM during the wait is not a stop**: a reboot sends one to every process, and
ending the run then would cancel every limit wait on the machine. The supervisor exits and
leaves the run parked on its open question; only a fence ends a waiting run.

**The reset is the turn's, else the account's.** A real Claude limit carries it in the
stream (`rate_limit_event` rejected, with `resetsAt` — 2026-10-07's run hit it mid-step), but
a 429 the CLI stops on before any event carries none (E8), so every turn's telemetry is kept
per account (`config_dir()/usage-limits.json`) and a limit with no reset of its own takes the
fullest window's. A reset the turn reported that has already passed — its cleanup crossed
it, or this clock runs ahead — is still the deadline: the run resumes once after the grace,
and the turn says `past-reset`. A second such turn in a row has no reset, so stale telemetry
never loops a run against the wall; with no reset at all the run parks for a person, rather
than probing the account on a timer.

**An account is a harness and the home its login is in.** The ledger record names no
account for a headless run, and a CLI's login lives in its config home — `$CLAUDE_CONFIG_DIR`,
`$CODEX_HOME` — so two homes are two accounts, and switching homes is how a person reaches
another login. The launch and the supervisor it starts resolve the key alike, from the same
environment. **Each observation is stamped with its turn's end**: supervisors of overlapping
turns write in any order, so a turn that ended earlier never replaces newer windows, and an
exhaustion is lifted only by a turn the model answered after it — never by a failure, and
never by older tokens. Two holds read the file. A **new headless launch waits** while a window is at or above the
threshold (95 % by default: the real limits struck at 98 and 99 %, and a launch past 95 %
would start hours of work into the wall), with the reason shown. And **nothing else starts on
an account that ran out**: a turn carrying no answer is written `limit`/`held` without a
process and parks on the same question as any limit. A turn carrying an answer always starts,
since the answer was consumed for it; a hold's only other way out is a later answered turn,
which says the account is back. Terminal runs are not held — the person at the
terminal sees the limit and may mean another login.

### A question is a file, and the inbox is the directory

A question needs answering from anywhere — the window on another machine, a person who
pulled the plan, the coordinator — so it is project data in git, never this machine's. **One
file per question**, for the ledger's reason: two agents asking at once add two files, and
nothing conflicts. Its body is Claude's `AskUserQuestion` shape, because that shape is
already what a Control Centre card needs (a question, a header, options with descriptions)
and because the warm path — a Claude process DPlanner hosts over stream-json — hands over
exactly that and takes back exactly `answers`; any other shape would be a translation in
both directions. `dplanner question ask`, the door every harness can use because every
harness can run a shell command, writes the same record with one question in it.

**The door is a noun's verb, `question ask`, not a word of its own.** The research named it
`dplanner ask`; every other verb is `<noun> <verb>`, the registry and the generated skill
index are built on that, and one bare word would have been the first exception to both. An
agent runs `question ask` as readily as `ask`, and `question list|answer|escalate` sit
beside it where an agent looking for the answer verb will find it.

**Every park stands on a question, whoever wrote it.** The agent's own question is the one
it recorded through the door, which the supervisor finds on the run when the turn ends and
hands to the classifier, so the turn says *asked* even though its last words were "ending my
turn". Any other park — a question found in prose, a denied permission, an exhausted
account, a run that cannot go on alone — gets its question written by the supervisor as it
parks, named on the turn. Otherwise the inbox would show some parked runs and not others,
and whoever reads it would have to know which endings make a card.

**Answering records; the supervisor delivers.** `question answer` writes the answer and
nothing else that counts; it nudges the run's supervisor when this machine launched the run,
but the nudge is not the delivery. Delivery is the supervisor's: whenever it starts, and once
more *after* it has let go of a parked run, it looks for an answered question on its own run
and resumes with it. That last look is what makes an answer given at any moment arrive — a
nudge refused because the old supervisor still held the run is made up for by the old
supervisor's own look, taken after the lock was free; an answer given while the asking turn
was still ending parks the turn on that very question and resumes it at once. An answer given
on another machine waits in the file for the run's own machine.

**The resume is claimed under the run's lock and the question's**, both re-read: the run still
this machine's, not fenced, not over, its last turn parked on this question, the question
answered. One ledger write then records the next turn — `prompt: answer`, the answer it
consumes, no process yet — and only then is the question marked consumed. Just before the
process starts, the turn is marked `spawning`. A supervisor that dies before the mark leaves a
turn the next one starts, after the same locked check, without consuming anything again; one
that dies after it leaves a turn whose agent may already have acted on the answer — the pid is
written only once the process exists — so that turn ends `lost-at-spawn` and parks for a
person rather than apply an answer twice. Checking under an earlier snapshot would let a fence
written meanwhile be overtaken by a resume.

**Cards are written before what they explain, and mended on start.** A parked ending is
committed with its card already on disk, so a crash leaves at worst a card on a lost turn,
which the retry withdraws — never a parked run nobody is asked about. A run that goes on by
itself (a retry, a nudge to continue) or parks again withdraws every earlier card not
consumed — an answer nobody acted on included, since no turn will consume it now —
and a run's end withdraws everything it had standing; a supervisor starting on a parked run
with no card writes one, and on an ended run with cards standing withdraws them.

**Who answers is read from where the call comes from.** Inside a run or an agent's shell the
caller is the coordinator — there is no flag to say otherwise — and a run may not answer its
own question; a person's own shell answers as a person. A flag would let the agent a gate is
meant to check say it was the person.

**A terminal run asks the person in front of it.** In a terminal the developer is right there
and the agent's process is still waiting for its next message, so `question ask` outside a
headless run records nothing: it sets the step's `needs-input`, as the briefing used to say
outright, and tells the agent to put the question in the terminal. Recording it as well would
need a rule for when such a question closes — the agent simply carries on in its terminal —
and nothing tells DPlanner that. Every briefing can therefore name one door.

**The warm path is not built.** A Claude process hosted over stream-json offers its own
`AskUserQuestion` and `ExitPlanMode`, and the record takes them unchanged. It needs a live
process held open briefly and an unverified mix of `--permission-mode auto` with the stdio
permission tool, and the cold door already lifts every question into DPlanner, so it waits for
a step of its own.

**A usage hold is a question too.** It could have been only a fact on the run (`end:
limit`, `resets`), with the cards reading parked runs beside questions. Then the inbox
would have had two sources with two ways to be answered and two ways to go stale. As a
`limit` question it is one more card, answered by *Retry now* or by the clock when the reset
passes — and the run still carries `resets`, which is when the clock answers it.

**A playbook's gate is a question too.** A `person` gate and a `coordinator` gate have no
run — nobody launches anything — so the question carries the gate's `stage` and `attempt`,
and the playbook's history is still runs and questions read in order. The two gates differ
only in who may answer: the coordinator may answer a `coordinator` gate's question, and
must escalate a `person` gate's, because that gate is the playbook's promise that a person
looked.

**An answer counts once it is consumed, and only the launching machine consumes.** Two
people may answer one question on two machines, and an agent may already be acting on the
first when the second arrives — with an earlier timestamp, on a skewed clock. So no
timestamp decides: the launching machine fetches, checks the run can still resume, pushes
the question marked `consumed` and only then starts the turn, which names the answer it
consumed. A playbook's question has no run to resume, so the pass's owner — the
engine on the machine that launched the pass — consumes it the same way, targeting the
pass, stage and attempt, and only then completes the step or advances the pass. From then
on that answer is the record's truth, and any competing one is kept as
a *late answer* and never applied. A withdrawal is terminal too, and beats any answer not
yet consumed: a run that was stopped must not be resumed by somebody who had not heard.
Gate, round-cap and escalation questions say which they are in `purpose`, and carry `pass`,
for the reason runs do. An open question never times out into an approval; it is the one
thing in this design that waits, and it waits in a file.

### The inbox is cards on top of the Control Centre

The rule is `.claude/rules/agents.md`'s *One question door* (its last sentences).

A person looks at the Control Centre to see what needs them, so that is where a question
goes: **a card per open or escalated question, above the board**, counted with the board's
rows in the tab's title. A headless run parked on a question sets no agent state, so its step
is not under *Waits for you* — the card is the only place it shows, and a plain sum of cards
and rows double-counts almost nothing. A card says who asks (callsign and harness), about
which step, the kind, the question, and the ways to answer: a button per choice, a person's
own words on the same line, *Retry Now* where a retry is an answer (`supervisor.RETRYABLE`:
a usage hold or a block), and *Go to Step*. A usage hold's words are the card's own, worded
from `resets` as it is read: the time the supervisor wrote is stale by the next morning.

**The questions module owns the card; the board only hosts it.** `agent_questions/` gained a
`module.py` that registers nothing and hands out `create_cards`, the Control Centre takes it
as a factory typed by a protocol it owns (`QuestionLane`), and the root wires the answer as
`inbox.answer` with the person as `by` — so the card and `question answer` are one function
and `status_board` learns nothing about questions. Putting the cards in `status_board` was
fewer files, but then the board would know kinds, resets, harnesses and the inbox.

**It polls, and reconciles.** Nothing watches `questions/`; supervisors, agents and git pulls
write it. The lane compares each project's `questions.fingerprint` every two seconds and
re-reads only what changed, then keeps every card whose facts are the same and builds only
the new ones: a rebuild per poll would take a half-typed answer with it.

**Oldest first, and gone when settled.** The question that has waited longest leads. An
answered one leaves the lane at once — it waits in its file for its run's machine, and the
status bar says so in `inbox.answer`'s own words. With no card the lane is hidden rather
than saying *no questions*, since the board under it already says what needs nobody. The lane
is as tall as its cards up to about two, then scrolls: the board keeps the rest of the page.
A splitter between them was tried and dropped — two framed wells either side of a seam drew
three lines where one belongs, and a lane that fits its cards needs no dragging.

### A claim is a lease in git, and at-work stays beside it

Knut's brief: what work is taken by which agent is project-level data, in git, with when and
the last sign of life, pushed as the agent goes. The 4 October multiplayer note asked for
the same thing as a lease — expiring unless renewed, so a crashed worker frees its area by
itself — and the claim is that record: a squad's callsign, the worker's machine, the step
ids, a heartbeat and a lease. **One claim per squad**: which callsign works which step is
already on the run, and a second copy of it here would be a second thing to keep true.

**It does not absorb `domain/at_work.py`, and at-work does not absorb it.** They look
alike — a file per claim, a last sign of life — and answer different questions on different
clocks. At-work is *a process on this machine is editing this plan right now*: renewed by
every CLI call, lapsed after three minutes, and kept out of the plan because a heartbeat
every few seconds in git would land in everybody's history and have every window adopting
an edit. A claim is *this work is taken*: it must be seen from other machines, so it is in
git, so its clock has to be slow. Merging them would either commit the fast clock or slow
the banner that stops a developer editing what an agent is rewriting. Each points at the
other, and the band can name the squad by matching its step to a run.

**Acquiring a claim is a push, not a write.** Two machines that pulled the same unclaimed
step would each add a claim file, and git would merge the two additions without a conflict
— so a file's existence proves nothing until it is on the remote. A claim is fetched against,
committed and pushed before anything is spawned, a rejected push is checked again, and if a
merge still brings two onto one step, the one pushed first holds it. Version one runs on one
machine, but the protocol is written now so the second machine is not a redesign.

**The cadence keeps git quiet.** The heartbeat is written only when it is ten minutes old —
by the coordinator's own `dplanner` runs, as at-work is renewed by them, and by the
supervisor of any of the squad's live runs, because a coordinator waiting out a two-hour
stage makes no calls and live work must not read as abandoned. The claim is pushed when something happened anyway (claimed, merged, released), and a
commit that carries nothing but a heartbeat goes at most every thirty minutes — pushed by
the supervisor while the coordinator is silent, and retried at the next beat if it fails,
since a renewal nobody else sees renews nothing. The lease is
ninety minutes, three pushes, so one rejected push or a little clock skew between machines
does not read as death; the reader's clock judges it, which is good enough at that length
and needs no service.

**A stale lease is abandoned, and nothing is deleted** — unless the squad is parked. Work
waiting on a person is still owned, and nothing is live to renew it, so a parked squad keeps
its claim while its questions are open, escalated, or answered and not yet consumed — an
answer nobody has acted on is still waiting — until the work resumes, is cancelled, or
`max_park_hours` passes. The window says so; another
squad may take the steps with a claim that names the old one in `supersedes` and fences its
unfinished runs; the old coordinator, if it was only asleep, finds the newer claim at its
next check and stands down. **The director wins, one step at a time**: a person who sets one
of the claim's steps done or blocked moves that step into `released` and stops its worker,
and the squad keeps the rest — ending the whole claim would hand its other steps to another
squad while their workers still ran. *Clear* ends all of it. That is the one deliberate
second writer; the coordinator re-reads before every write, and in a merge the person's act
wins.

**As built — one machine, simpler than the protocol above.** Version one decides ownership
**locally, from the files, per step**, and leaves the arbitration between machines for
multiplayer. Ranking claims by which file reached the remote first was the first version,
and Kettle Watch found two ways it handed a step to two squads: a squad *growing* an old
claim outranked one that had taken the step before it, because the file's age is not the
step's; and a superseded squad that woke and renewed got its steps back, because the
takeover was not part of the ranking. So each step a claim holds carries its own
**`acquired`** stamp and the earliest wins, a tie by claim id; a takeover names in
**`supersedes`**, step by step, the claim it took from, and that is final; and a claim
**stands down before it renews** from any step it no longer holds. `claim take` checks under
the project's taking lock, writes and publishes. **A publish never rewrites the person's
checkout**: it commits `claims/` by pathspec under the repository's sync lock — the one the
window's own Save and sync take — and pushes; a refused push is left for the window's next
sync, never fetched, rebased or stashed under the person's unsaved plan, which is what a
heartbeat racing autosave and the window's rebase did. Unpublished, a claim still holds
here, since this machine decides. **The heartbeat needs no verb**: every `dplanner` run from
an agent's shell renews the claims this machine holds in the project — a coordinator renews
by working — and a live turn's supervisor renews its run's claim; a backoff wait or a park
renews nothing. Renewing what *this machine* holds costs one thing: two squads on one
machine keep each other alive, until the coordinator's launch can set a
`DPLANNER_CALLSIGN`.

**Ownership is checked inside the one launch, twice.** `launch.claim_for` refuses a step
another squad holds on both surfaces — a person's Run Agent too, which the first version let
straight through — and `start_run` asks again under the step's launch lock, just before
anything starts: a worktree takes seconds to prepare, and a release or a takeover in that
time must start nothing. **Every way a step leaves a squad stops its worker, through one
function** (`agent_claims/ownership.py`): a takeover, `claim release`, `claim end`, *End
Squad Claim* and a person's stopped status each fence the squad's unfinished runs on the step
and signal their supervisor here, and a live turn reads its fence on every poll — so the
first version's release and Clear, which changed the claim and left the worker running, are
the same act as the override. A release takes the step's launch lock when it is free; when a
launch holds it — the window's own, possibly, on its GUI thread — waiting would deadlock, and
the launch's own re-read covers the gap, since its record already exists to be fenced. A
fenced run counts as over for the next launch only once nothing of it runs here — and a
supervisor can be killed while its turn's detached process group survives it, which a
supervisor lock alone cannot see. So the launch, and the supervisor `revive` hands a fenced
run, end any such turn by its recorded process stamp first (TERM, grace, KILL), and a turn
that will not end refuses the launch with the reason. Ending a claim fences exactly the steps
it held when its locked write ended it, and `claims.grown` refuses an ended claim, so a take
racing an end can neither escape the fence nor grow a closed claim. A playbook stage's run
launches under whichever claim holds its step at the time.
**Only a person's status releases a step** (the status workflow's `Release` follow-up): a
worker setting its own ready-for-review must not hand the step back before its coordinator
has verified and merged; the release is written, and Save carries it. The window polls
`claims/` and `questions/` (the questions say whether a quiet squad is parked), re-reads once
a minute for the clock alone, wears the squad as a still chip on the card's other bottom
corner — the run chip marches, a claim is ownership — and names it in the Control Centre's
*Squad* column. Not built — the second machine: which squad pushed first, a fence reaching
the machine that runs the turn, and a claim file conflicting in a merge.

### A coordinator is briefed, never built in

The rule is `.claude/rules/agents.md`'s *A coordinator is a briefing over the verbs*.

The 4 October run's director rebuilt Run Agent by hand for every step and still forgot what
the window would have done for it. Everything it lacked is a verb now — `claim take`, `agent
run --playbook --callsign`, `question answer|escalate`, `agent limits`, `playbook advance` —
so a coordinator is **an agent with a briefing**, not a daemon: `agent_briefing/coordinator.py`
composes it, `dplanner agent coordinate <keys> --callsign <word>` prints it, and Autonomous
work ▸ Local launches a coordinator with the same text. A daemon would be a second engine
deciding what an agent decides better — which plans collide, what a question means, whether a
person is needed — and the verbs already refuse what it must never do: `may_answer` keeps it
off a person or progress gate, `claim_for` off another squad's step, the hold off a spent
account.

**Callsigns are Knut's radio net.** The squad word is the coordinator's pick and unique among
running squads — the verb refuses a word a live or parked claim answers to, because `claim
take` under one word grows that squad's claim, and two coordinators would quietly share one.
The coordinator is *Actual*, the workers *Two, Three…* in the selection's order, a worker's
own sub-agent *Two-One*, the verifier *Watch* (`claims.member`, `claims.spoken`):
lowercase-kebab where a machine reads it, capitalised in prose, and in every message, note
title and commit trailer. **A member keeps its callsign through every stage of its pass**:
`agent run --playbook --callsign kettle-two` hands it to the engine, the pass's first run
records it, and each later stage reads it back from there (`_latest_pass`) — a stage's run
used to carry only the squad word. The worker hears it in its preamble. **Workers' branches
stay `agent/<run name>`**: the preamble's worktree check, `run_name_of` and the branch plan all
key on it, so only the branches and worktrees a coordinator makes itself carry its callsign.

**It paces itself under the hold.** A coordinator shares the account with its workers, and on
7 October one ran out of usage while its workers ran, leaving nobody to resume them. So the
briefing launches nothing at or above 90 % of any window — under the supervisor's 95 % hold,
leaving the coordinator room — and leaves every reset to the supervisor. *Max agents launched
at once* is a QSettings value no CLI can read, so `--at-once` carries it (three by default).
The loop carries the rest of what the first runs taught, one sentence each: keep the machine
awake, poll GitHub's `mergeable` past UNKNOWN, run the ratchet tests on the integrated branch,
cap a cross-vendor review at two rounds, and brief a small fix fresh rather than resume a long
session.

### What the window reads, and the one-writer rule across all three

The window polls each directory's fingerprint, as Expenditure polls the ledger's; nothing
here is a plan entry, so none of it is adopted as an outside change or trips the stale check,
and Save commits all three with the project. Across machines everything meets at git, and
each record is written so that the meeting is boring: a run has one writer and a fence, a question has
writers in sequence and counts only the answer its run consumed, a claim is held by whoever
pushed it first and released by a director.
