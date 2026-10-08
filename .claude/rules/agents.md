---
paths:
  - "src/dplanner/modules/{agent_briefing,agent_claims,agent_launch,agent_questions,agent_supervisor,agent_usage,step_agent_instruction,step_agent_run,agent_claude,agent_codex,agent_opencode}/**"
  - "src/dplanner/domain/agents.py"
  - "src/dplanner/domain/questions.py"
  - "src/dplanner/domain/{claims,claim_sync,ledger,expenditure}.py"
  - "src/dplanner/core/process.py"
  - "tests/modules/{agent_claims,agent_launch,agent_questions,agent_supervisor,agent_usage,step_agent_instruction,step_agent_run}/**"
  - "tests/modules/agent_briefing/**"
  - "tests/domain/test_{ledger,questions,claims,claim_sync,expenditure}.py"
  - "tests/modules/test_agent_readers.py"
  - "scripts/render_briefing_size.py"
---

# Agents — Run Agent, supervisors, questions, claims, the coordinator, worktrees, usage, harnesses and profiles

- **Running an agent launches a peer, never a task.** *Run Agent* spawns a detached terminal
  the user owns — not a `TaskRunner` body, which would promise cancel and progress nobody
  can honestly deliver. The terminal opens in the step's code checkout
  (`agent_briefing.worktree.workdir` over `deps.facts_for`, or its worktree). The prompt goes
  to a per-run temp directory, never the project. The agent reports back through the CLI
  (`status set`, `agent-state set`, `note add`). **The graph gates launching**: a step
  whose `requires` do not all read done (through `status_for` on the module's Deps, the
  Step statuses tab's seam, where a wait reads done once it is over and a step under
  review or waiting on its merge does not — `progression.outstanding()` being the one
  answer) gets a confirmation
  naming them before a shell opens — the
  person may know the work landed unrecorded, so it asks rather than refuses, **once for
  the whole gesture** whichever of the chosen steps wait.
  **It runs one agent per chosen step, and the count is the last precondition.** The verb
  reads `chosen_steps` — the framework's one definition, the same Delete acts on — so
  lassoing three agent steps is *Run 3 Agents…* and one gesture; a step in the
  selection that cannot run greys the verb for all of them, naming that step and why,
  because launching the subset that qualifies would run fewer agents than were asked for
  and say nothing. Past *Settings ▸ Agent profiles*'s **Max agents launched at once** (four by
  default, per user and per machine like the terminal beside it) the count itself is the
  refusal — a lasso is one flick of the wrist, and a deskful of terminals is not what it
  meant.
  **A launch that opened a shell claims the step is in progress** — `agent_launch/workflows.py`'s
  `run_agent`, a `Change` the window applies off the undo stack the way the launch stamp is,
  because Ctrl+Z must not file a step as pending while an agent works in it. Over a selection it is claimed per step as each shell opens, so a
  run that stopped at its third step has claimed two. It is the *Agent profiles ▸ On launch* switch
  beside *Max agents launched at once*, on by default: the agent's own first report is
  minutes away and a step somebody is working on that still reads pending is a lie the
  plan was never asked to tell. Only Run Agent and `dplanner agent run` make the claim — in
  the step loop, never in the shared `_launch` — so a conflict handed to an agent, a merge of
  two writers' plan files and not the step's work, claims nothing.
  **The briefing never rides in argv, and the peer is a top-level session.** The
  agent's opening line is `agent_briefing.protocol.opening_prompt` — a pointer at `prompt.md`, carrying
  nothing the project is about — because the whole briefing as one argument was every
  agent's command line, and one agent's `pkill -f "Web.Host"` matched four others.
  `launcher.spawn` hands the terminal `scrubbed_environment()`: every harness's shell
  markers are taken out (a nested `claude` under Claude's is a child session of the
  outer one), the person's `CLAUDE_CONFIG_DIR`-style configuration stays. The Claude
  harness names the run's session (`--session-id {session}`, minted per launch); the
  wrapper records it with `dir` and `resume` in the shell facts, and an ended row in
  the Agents browser shows the command that picks the agent up again. It also hands
  the run directory over as an additional working directory (`--add-dir {run_dir}`,
  before another option: the flag takes a list and would swallow `{prompt}`), so
  reading the briefing asks nothing, and `new_run_dir` resolves the path so the flag
  and the file agree on macOS (`/var` is a symlink) and Windows (a short-name Temp).
  **A harness whose command changes lists the texts it replaced**
  (`AgentHarness.superseded`): the settings store the picked text, and
  `launcher.current_command` reads a stale one as the harness. The skill and the
  briefing's preamble both say *never kill by name or pattern*.
  `docs/architecture/agents.md`'s *Running an agent launches a peer, not a task* has the reasoning.
- **An agent's run ends at Ready for review, and the CLI holds it there.** The briefing's
  epilogue (`agent_briefing/protocol.py`'s `epilogue`) and the skill's *Running as an agent step* end at
  `status set <key> ready-for-review` — a person or a reviewing agent looks next and sets
  `ready-to-merge`, then `done` — worded apart from the mid-run `plan-for-review`, which is
  the agent's *plan* waiting for a look. `status set <agent step> done` **from inside an
  agent's shell**, on a step not already under review or waiting on its merge, exits 1
  naming `ready-for-review` — unless `--because '<reason>'`, which sets done and keeps the
  reason as a `decision` note on the step in the same run — and a status that says the work
  stopped also ends the step's at-work claim (`persistence.md`'s *An agent at work says
  so*). A person's own terminal and the
  window are never asked: the guard is about who reports, read through
  `domain/agents.py`'s `shell_marker` over the harnesses (the entry point's window guard
  reads the same), and `tests/conftest.py`'s `_no_agent_shell` scrubs the markers so the
  suite never depends on being run by an agent. `docs/architecture/agents.md`'s *An agent finishes
  at Ready for review* has the reasoning.
- **One launch under both surfaces: `dplanner agent run` is the window's Run Agent.** Both
  run `agent_launch/launch.py` in one order, **under the step's launch lock**
  (`supervisor.launching`, `config_dir()/launches/<project>-<step>.lock`, an OS lock) from the
  first check to the start: the gate (`refusal`, which includes `BranchPlan.refusal`, and
  `unfinished_run` — a headless run not over is resumed with `agent supervise`, never
  launched again); `worktree_of`/`place` (prepared by git in Python, on a task in the window,
  whose result is re-checked against the step's run name and branch plan before use);
  `prepare_run` (the briefing, then **the run's ledger record** — format 2 headless in
  `config_dir()/runs/<run>/`, format 1 for a terminal); then **the claim**, `workflows.py`'s
  `run_agent`, **applied and saved before anything starts**; and only then `start_run`, the
  follow-up. A save that fails starts nothing and takes the record back (the CLI's
  `CliContext.unwritten`); a start that fails takes the record back and the claim
  (`workflows.withdraw`, a second change), and says so. Effects never go in a `workflows.py`.
  **What the window asks, `agent run` refuses**: prerequisites not done (until `--anyway`), a
  repository not checked out here, a profile whose agent has no headless mode. It is
  headless by default (`--terminal` for a terminal) and always claims — `--playbook` starts a
  playbook's pass instead, through the same gate, lock and claim (`playbooks.md`). **A supervisor is
  `sys.executable -m dplanner --library <the launch's>`**, and every turn's environment
  carries `DPLANNER_LIBRARY`, `DPLANNER_PROJECT` and `DPLANNER_RUN` — which nothing started
  detached inherits (`core.process.detached_environment`: `spawn_detached`, a terminal's
  launch, the window's `dplanner` calls), since a stop ends every process carrying its run.
  `docs/architecture/agents.md`'s *One launch under both surfaces* has the reasoning.
- **A machine's start settles its headless runs.** `supervisor.revive(project_dirs,
  claimed=, library=)` starts a supervisor for each run of this machine whose last turn has
  no end and that no supervisor holds (`supervised`, the OS lock) — the supervisor ends the
  turn `failed`/`lost` and retries — and for each run with **no turn** whose step is still
  claimed (a launch interrupted between its record and its start). A turnless run is
  settled **inside the step's launch lock, re-reading the record and the step's status from
  disk** (`claimed_on_disk(library)`, never a model loaded earlier), and its record is
  deleted only when no supervisor holds the run, its step reads unclaimed and it is older than
  `LAUNCH_GRACE` (two minutes) — a supervisor just started may not hold its lock yet. The
  window calls it once at start (`agent_usage`'s module); `agent run` before its own lock,
  over its own project — and nothing else, so a killed supervisor's run waits for one of
  the two. A
  turnless run of a playbook's pass that is not its first record is started whatever the
  step's status: its pass is its claim.
  A parked run is a person's, never touched — except one waiting for its reset
  (`waits_for_reset`) or holding an answer nobody delivered (`answer_waiting`), whose
  supervisor is started again. A failed start's rollback — the record deleted,
  the withdrawal written — happens under the launch lock too, and the window saves before
  every start, a claim it did not make included. `docs/architecture/agents.md`'s *One launch
  under both surfaces* has the reasoning.
- **A step names the code location it works in.** With several code rows in a project,
  the agent-instruction entry's `workplace` holds a location id (`planning.agent.workplace`,
  `with_workplace`; `dplanner agent workplace <step> code:UI|primary`), absent meaning
  the primary — the project's first code row — because which repository a step's change
  lands in is a fact about the step, exactly as its worktree choice is.
  `agent_briefing.worktree.workdir(facts, step)` places that row (Qt-free, so the briefing can place a
  source's worktree); a named row that is gone falls back to the primary. A run
  across two repositories at once is two steps.
- **An agent may be opened with nothing to do, and that is a second invocation.**
  *Project ▸ Open Agent in Code* is the same profiles in the same child menu, opening a
  shell where a step's agent would work (the code checkout — cloned first, where the
  clone policy says, when nobody has one here — else the plan's repository for the legacy
  shape, and greyed while the project's code is not set)
  with the harness's `open_command` — `claude`, `codex`, `opencode` — and **no briefing at
  all**: no `prompt.md`, no opening line, no worktree. It is the planning before the plan,
  when a spec has landed and there is no step to be about yet. The bare command is the
  harness's own fact, never the briefed one with its `{prompt}` dropped: that would leave
  Claude's `--permission-mode plan` behind, which is the one mode a session about to write
  a plan must not be in, so a command nothing here knows greys the entry with that as its
  reason. In the launcher it is one shape and no special case — `prepare` with empty prompt
  text writes no prompt file and gives the script no opening line. The run has no step, so
  nothing is tracked, nothing is claimed *in progress* and no usage row is written, as for
  the Problems panel's run; unlike those, it also has no prompt, so a launch that opens no
  terminal ends in a **notice** rather than the prompt fallback.
  `docs/architecture/agents.md`'s *An agent may be opened with nothing to do* has the reasoning.
- **A shell of your own where a step's work is, and it is not a run.** *Step ▸ Open
  Terminal in Worktree* (`agent.open_shell`; *…in Checkout* for a step whose worktree is
  off) opens the default profile's terminal on `launcher.shell_script` — `cd` there, export
  `$DPLANNER_PROJECT`, then the person's `$SHELL` (on Windows a `cmd` of its own, since a
  row that runs the script and closes would close on the prompt) — and nothing else: no
  briefing, no shell facts, no exit file, no run recorded, nothing claimed in progress, a
  `notice()` when no terminal opens. Its directory is found by the name `worktree.prepare`
  gives it (`worktree_path(workdir, run_name_of(step))`), so it is greyed with *Run Agent
  prepares one* until that directory exists. It is in Step ▸ `agent` beside *Show Agent
  Terminal* and *Open Pull Request*, so a status row's ⋮ offers all three.
- **A worktree is the step's decision, and the run is named after the step.** Whether the
  agent gets a fresh git worktree is the agent aspect's `worktree` (absent = on; the Agent
  tab's checkbox, `dplanner agent worktree <step> off`, `step add --no-worktree`) — a fact
  about the step, never a setting, because only a step that must act on the checkout the
  window shows (a release cut, a conflict) turns it off. `agent_briefing/worktree.py`'s
  `prepare` makes `.dplanner-worktrees/<run name>` on branch `agent/<run name>` before the
  run — in Python, for a terminal and a headless run alike, so no script carries git; the
  checkout under `sparse.CHECKOUT_S`, and a worktree git left half made (still locked
  `initializing`, or no commit checked out) removed and made again — **and
  refuses with git's reason if it cannot**: the first version swallowed the error and ran two
  "isolated" agents on one checkout, because `.dplanner/` is the pointer *file* a subfolder project
  leaves at the repo root. The run name is `agent_briefing.worktree.run_name`: the step's key, its ticket
  key and its title slug, ref-safe (`f7-PROJ-12-build-the-modal`), composed by
  `run_name_of` from the step's key and ticket, which the launcher never reads. The briefing's preamble names that very worktree
  and tells the agent to **stop if it is not in it**; the epilogue addresses every verb by
  the step's key. Inside a worktree the CLI resolves the branch's copy of the plan to the
  library project of the same id (`cli/discovery.py`), so `dplanner status set` reaches
  the plan the window shows. Every surface reads the one answer, `planning.agent.uses_worktree`:
  Run Agent, `agent prompt`, *Open Terminal in Worktree|Checkout* and the Agent tab.
  `docs/architecture/agents.md`'s *A worktree is the step's decision* has the reasoning.
- **A run starts from the remote, and the plan names its base.** `planning.branches.BranchPlan` —
  decided once by `branches/plan.py`'s `branch_plan`, handed to Run Agent as `branch_plan` and to
  `brief()` as a plain value — is the branch a worktree is
  on (its own `agent/<run name>`, or the feature branch for a landing), where a new one
  starts, what the first run in a stretch may cut on the remote, and the PR's base.
  `worktree.prepare` **fetches and starts the branch from the plan's start** — a stretch's
  branch, else the code row's `Location.ref` as the mainline, else the remote's default,
  looked up — **never from whatever the checkout has checked out**, with `--no-track` (a
  landing on the feature branch tracks it); it cuts a missing branch only when told to
  (`create`, set while nothing on the stretch has recorded a branch or a PR) by pushing a
  ref, never checking one out, and **refuses a branch gone from the remote** rather than
  re-cut it from the mainline. It sets `gh-merge-base` as a backstop for the `--base` the
  epilogue names; the preamble checks the plan's branch. Every name is checked with
  `sparse.valid_ref` before it reaches git. A landing is briefed by what it is —
  its instructions generated from the stretch it closes (`agent_briefing/instructions.py`, *Work you
  land*): merge the mainline in as a merge commit, never a squash, and open the branch's
  own PR — and **without the project's standing instruction**, which is written for the
  stretch's work (`compose.brief`). **A PR merged into the branch of an open stretch accepts its step** from
  ready-for-review (`record_merged(accepted_by_merge=)`, the root's `finish_merged` on both
  surfaces), since the branch's review comes after its landing; the GitHub aspect records
  the base a PR merges into (`pr_base`, format 2). `docs/architecture/graph-model.md`'s *A branch
  stretch is bracketed by a cut and a landing* has the reasoning.
- **The peer reports its end through its run directory, and the window clears the chip.**
  The wrapper script is the one process that knows when the agent exits, so it writes the
  shell's facts (`shell`: tty, pid, tmux pane, terminal program, window title) beside the
  prompt on start and the exit status (`exit`; `closed` on a hang-up) at the end — no
  terminal-specific hook, so it is the same on every platform and terminal. The agent-run
  module (`step_agent_run/`) polls the runs it launched, clears the step's state when a
  shell ends — directly, with the launch origin, the way the launch was stamped — and
  **stands down while the plan changed underneath**: the watcher adopts the change first
  (or the rebuild it falls back to re-adopts the runs from the per-user store) and the
  next tick checks again, so an exit is never written over the agent's own last
  `dplanner` call. Runs are per-user, per-machine facts (`user_config`), never the
  plan. The Agents browser (status-bar button, *View ▸ Agents…*) is the management view and
  **Tools ▸ Agent List** the quick switch — a data child menu of the live runs, each entry
  raising its terminal; *Step ▸ Show Agent Terminal* focuses the window through
  `terminal.py`'s per-platform provider (tmux pane, tty via AppleScript, ancestor pid via
  xdotool, PowerShell pid). All three grey a run that cannot be switched to with its
  reason, **per run** (`terminal.focus_reason` — a tmux, herdr or WezTerm pane is
  reachable on a desktop whose bare windows are not; the wrapper records each
  multiplexer's own name for the pane); *Clear Agent Run* is the window's twin of
  `agent-state clear`.
  **The browser lists what is happening now, newest first.** The live runs are on top in
  launch order reversed — the one just launched at the eye's first stop — and the ended
  ones are not listed at all until *Show ended* asks for them, under the live ones and
  by when they ended: each group is sorted on the very stamp its rows print, so the times
  read down the list. The default list empties itself, which is what replaced a *Clear
  ended* somebody had to remember; that verb now comes up with the switch and is greyed
  without it, because a verb that deletes what the list is not showing acts blind. Nothing
  kept off screen goes unsaid: the footer counts the live and the ended either way, and
  the empty state names the switch that has the rest — an empty state per filter.
  `docs/architecture/agents.md`'s *The peer reports back through its run directory* has the
  reasoning.
- **What a run consumed is a ledger record, harvested by anyone — never caught at the
  end.** The launch writes the run's record into `<project>/ledger/YYYY-MM/<run id>.json`
  (`domain/ledger.py`; `agent_usage/aspect.py`'s `launch_record`, through the tracker's
  `project_dir` seam):
  step, harness, the worktree it works in, the session when the harness names one. A
  harvest (`agent_usage/harvest.py`) re-reads the CLI's own records of the run's whole
  tree — main agent and every subagent, per model, as `in`/`cached`/`out` — and rewrites the
  record; it is idempotent, so the triggers are many and none is load-bearing: the wrapper's
  `dplanner usage harvest --run` after the agent exits (`launcher.HARVEST`, no window
  needed), the tracker on settle (`aspect.end`, then `StepAgentRunDeps.ended` sets
  `AgentUsageModule.sweep` going), and that sweep at start and every five minutes through a
  `TaskRunner` — started only when `harvest.anything_due` finds a run of this machine not
  read since it ended. **Never add a usage path that depends on
  seeing the end.** One writer per file (only the launching machine can read the vendor
  records), outside `PLAN_ENTRIES`, committed by Save, carried by Move Plan; a harness that
  mints its session claims the earliest *unclaimed* one (`RunFacts.claimed`) and the record
  keeps it. No dollars: tokens only. **`modules/agent_usage/` is the package its id names**:
  the ledger's words and readers (`aspect.py`, the surface other modules import), the
  harvest, the `usage` verbs, the sweep and Expenditure. `agent_usage` on the step is
  retired, absorbed into `legacy` records at every open — the window's too, since the
  module declares the format. `dplanner usage show|list|harvest|record` is the terminal's half.
  `docs/architecture/agents.md`'s *Usage is a ledger, harvested by anyone* has the reasoning.
  **And what the run was *handed*:** `prompt_chars`, measured in `launcher.prepare` —
  the one place that knows what reached `prompt.md` — carried on `LaunchFiles` to the
  tracker, kept on the **`AgentRun`** and on the run's ledger record. **A size does not
  total** — two briefings added together is not a quantity anybody spends — so `usage
  show`'s total and the step's own phrase stay tokens-only, and `brief_words` says the unit
  out loud (*briefed 18.4k chars*) because the number beside it is tokens.
  `docs/architecture/agents.md`'s *What a run was handed* has the reasoning.
- **Expenditure is the order read for what it consumed — tokens, never money.** The ledger's
  tab, in `agent_usage/` (`ExpenditureActivity`; columns, words and the tab in `expenditure_activity.py`, the
  walk in `domain/expenditure.py`): the same rows as Order through
  `framework/step_table.py`'s `StepTable` — which is where a row's look lives, so a third
  step table subclasses it rather than copying it —
  then runs, models, **in / cached / out** (cache reads apart: they are context, not work),
  the running total, *expected* and the running offset. Expected is the estimate × a rate
  of tokens of work per estimated day **learned from the library's other projects first**
  (from the same steps the offset would end at 0% by construction), and empty, never
  invented, with no history. The offset's tone follows the number shown (`+0%` is `ok`).
  *By model* rebuilds the table with an in/out pair per model; the export is long — a row
  per step and model. The ledger is written by other processes, so the tab polls
  `ledger.fingerprint` beside `follow_project`, into one `Debounced`. No dollars: a price is
  a derivation somebody can add over the counts (`docs/architecture/agents.md`'s *Expenditure is the
  order, in tokens*).
- **An agent CLI is a harness, and a harness is a module.** `domain/agents.py` is the
  contract: an `AgentHarness` is the command (`{prompt}`, `{session}`, `{run_dir}`), how
  a run resumes, the texts it shipped earlier, the variables it sets in the shells it
  runs, and a `report` that reads the CLI's own record of one run back — its session
  and a `Usage`. `modules/agent_claude/`, `agent_codex/` and `agent_opencode/` each
  export one from a Qt-free `harness.py`, the root's `agent_harnesses()` is the tuple
  (first is the default), and the launcher, the settings page, the run tracker, the
  `usage` verbs and `entry.py`'s shell guard all read it — a fourth agent is a fourth
  module and no `if`. **Capabilities are derived, never declared**: `names_session`
  is `{session}` in the command, `resumes` is a resume template plus a way to the id,
  `counts_tokens` is a reader; `capabilities()` words them for the dropdown. A `report`
  reads the run's whole tree, per model (`RunReport.agents`). Codex and OpenCode mint
  their own ids, so their `report` finds the run by the directory it worked in, the
  launch time and the sessions other runs have not claimed, and the found id, kept on
  the ledger record, is what makes such a run resumable afterwards. `docs/architecture/agents.md`'s
  *An agent CLI is a harness* has the reasoning.
- **Installed is not usable: an agent's status is three levels, asked through a shell.**
  `agent_launch/availability.py`'s `probe` walks on PATH → `--version` → the harness's
  `sign_in` (`AgentHarness.sign_in`: a probe over a `Shell` and the command a person signs in
  with) and answers an `AgentStatus` whose level is the first it could not pass; a hang (10 s)
  or a CLI that will not run is words, never a raise. A harness never names its binary to its
  probe — the shell is bound to the path `which` found, which is the seam a probe on another
  machine takes. **`check` probes; `cached` and `why_not` never do**, so a UI-thread reader
  reads a reading at most a minute old, or "checking…", and a `TaskRunner` runs
  `refresh_stale`. **The window keeps one** (`_Root.availability`): the checklist's rows probe
  into it and Run Playbook greys from it, refreshing it on a task when it goes stale; the suite's
  `_no_agent_probes` makes it find nothing on PATH. The checklist has a row per harness beside *An agent CLI*; a CLI not on
  PATH is well (*not installed — optional*), and only broken or signed out is advice.
  `docs/architecture/agents.md`'s *Installed is not usable* has the reasoning.
- **Which terminal opens is a table, not a chain — and the multiplexers are its last
  rows.** `launcher.TERMINALS` is one row per known terminal *and multiplexer* per
  platform with a probe saying whether it is installed; *Automatic* is the first
  installed row (the platform's own default), and the settings dropdown lists the same
  rows and pre-fills the editable template — the harnesses' pattern. A new terminal is
  a row, never an `if`. tmux led the table once, and a DPlanner started from a tmux
  shell inherits `$TMUX`, so every agent opened as a tmux window inside whatever
  terminal the person was using; a desktop agent gets a desktop window, and a
  multiplexer (herdr, zellij, tmux — `TerminalPreset.multiplexer`) is what Automatic
  reaches for only when nothing else is installed, and what a *profile* picks on
  purpose to land several agents side by side. Ghostty's `-e` is always a fresh
  process and window. **A multiplexer that needs two calls is one template with
  `&&`**: herdr's row is `herdr workspace create … && herdr pane run {pane} {script}`,
  `launcher.spawn` runs the stages in turn with `{pane}` as what the earlier
  stage printed, and a stage that fails is a reason and no run — the fallback dialog
  hands the prompt over, exactly as when no terminal exists.
- **A launch profile is a name over the two choices, and the first is the default.**
  `agent_launch/profiles.py`: a `Profile` is an agent command and a terminal
  template under a name, kept per user in `config_dir()/agent-profiles.json` — never
  QSettings, because `agent run --profile` reads it with no Qt; the window `adopt`s what
  QSettings held before, once, the two single settings profiles replaced included. **A file
  that is there and cannot be read is never written over** (`profiles.problem()`): the
  default profile stands in, nothing seeds or saves, the window shows a notice and the page
  is read-only, and `agent run` refuses. `agent.run` runs
  the first — the Agent tab's button and the palette — and its seat in the Step menu is
  *Step ▸ Run Agent*, a data child menu of every profile, the default marked, each
  greyed with its own reason (`launcher.template_refusal`: a row's probe, asked before
  any step is), then a rule and *Manage Agent Profiles…*, which lands Settings on the
  page (`SettingsModule.open(section)`, wired by the root). The verb and the link are
  `in_menus=False`: registered, runnable, in the palette under the child's path, seated
  nowhere else. **The list is seeded once** (`seed_profiles`, from the module's
  `register()`): every harness in Ghostty, herdr and Automatic, appended after what is
  stored, a pairing skipped when a stored profile already means it by its choices, and
  the `profiles_seeded` flag written with it so a removal stands. **Add Detected…** on
  the page is the same act on purpose: `detect_pairings` (Qt-free) pairs every harness
  with every terminal row and says what the machine has of each, `detect_dialog.py`
  lists them as tickable rows, and `add_profiles` appends the ticked — the seam the
  coming first-start checklist reuses. A profile's name
  follows its choices — *Claude Code in herdr* — until somebody types one, and a taken
  name is numbered rather than refused. Over a selection every chosen step goes through
  the one profile — with a multiplexer, one pane each. The Step statuses tab's strip is
  the same verb again: `agent.run` seated with its arrow dropping this child
  (`StripVerb("agent.run", data_menu=RUN_MENU_ID)`), over the rows ticked in its check
  column — which are the published selection, so no context is constructed for it. **The
  Control Centre's strip is the same seat over ticks from several projects**, and nothing
  was added for it: the gate asks each chosen step's own project where a shell opens, so
  *Run 2 Agents…* over two projects is one gesture opening each in its own checkout.
- **Runs, questions and claims are three records in the plan, and there are no others**
  (FORMAT.md's *The `ledger` directory* format 2, *The `questions` directory*, *The
  `claims` directory*). **A run is the ledger record**: one stage attempt, whose resumes —
  an answer, a reset, a retry — are its `turns` (a loop-back is a new run), each ending `done`, `asked`, `denied`, `limit`, `failed` or `stopped` —
  classified from the stream, never the exit alone — written only by the launching machine;
  running, parked and over are read from the turns, and **the playbook ledger is a step's
  runs**, never a second record. Its working files are `config_dir()/runs/<run id>/`, never
  `/tmp`. **Every inbox card is a file in `questions/`** — `AskUserQuestion`'s shape, a usage
  hold included (`kind: limit`) — so nothing else may feed the inbox. **A claim is a squad's
  lease in `claims/`**: heartbeat at most every ten minutes, a heartbeat-only push at most
  every thirty, acquired by a push before anything spawns, abandoned past a ninety-minute lease
  unless parked, and a person's override releases one step from it, not the squad.
  **Built for one machine** (`modules/agent_claims/`, over `domain/claims.py` and the git half
  `domain/claim_sync.py`): **ownership is decided locally, per step** — the earliest
  `acquired` holds, a takeover's per-step `supersedes` is final, and a claim stands down from
  what it lost before it renews. **A claim publish never rewrites the checkout**: `claims/` by
  pathspec under `sync_lock` (which Save and sync take too), then a push — never a fetch,
  rebase or stash; a refused push waits for the window's sync. **Ownership is checked in the
  one launch** (`launch.claim_for`, both surfaces) and again under the launch lock in
  `start_run`. **Every way a step leaves a squad goes through `ownership.py`**, which fences
  and stops its runs (an end, exactly the steps its locked write held; an ended claim never
  grows) and halts the step's playbook pass under the claim — a stage done or a gate waiting
  included — with the engine's stop (`engine.halt_claimed`, handed in as `ownership.Halt`);
  a live turn reads its fence each poll, and a fenced run is over for the next launch
  only once its turn is gone — what outlived its supervisor is ended by identity, every
  process carrying the run's `DPLANNER_RUN` and its provable group
  (`supervisor.end_orphaned_turn`; Linux reads environments, elsewhere the recorded leader)
  by `revive`'s supervisor and by **the one stopper, `supervisor.stop_and_wait`** (the launch's `stop_fenced`, *Stop Playbook*), which signals a
  supervisor here, waits for it, and ends a fenced run nobody drives under its supervisor
  lock (`settle_fenced`) — never another machine's. The
  heartbeat is every agent-shell `dplanner` run (this machine's claims) and a **live** turn's
  supervisor, never a wait; only a *person's* override — a stopped status, a stopped playbook
  — releases a step (the `Release` follow-up, `ownership.released_by_person`).
  It never absorbs the at-work claim, nor the at-work claim it: two clocks, two jobs.
  **An answer counts only once its run's machine has consumed it.**
  `docs/architecture/agents.md`'s *Runs, questions and claims are three records in the plan*
  has the reasoning.
- **One question door, and every park stands on a question.** `dplanner question ask` (the
  Qt-free `modules/agent_questions/`, over `domain/questions.py`) records a question on the
  run `$DPLANNER_RUN` names — the supervisor sets it and `$DPLANNER_PROJECT` on every turn —
  withdraws that run's earlier one, and tells the agent to end its turn; outside a headless
  run it records nothing and sets `needs-input`. The supervisor hands the recorded question to
  `classify`, and writes the question for every other park (prose, denied, limit, blocked) —
  `Turn.question` always names one, and the card is written **before** the parked ending.
  `question answer` only records (`inbox.answer`, the one function the card calls too) and
  nudges; **the supervisor delivers** — it looks for an answered question on its run when it
  starts and again after letting go of a parked run — and **claims** the resume under the
  run's lock and the question's, re-reading both (this machine's, not fenced, not over,
  parked on that question), writing the next turn with the answer before marking it
  consumed; a turn holding an answer and no pid is started only if it was never marked
  `spawning` (and after the same locked check) — marked, it ends `lost-at-spawn` and parks
  on a `blocked` card, never applying an answer twice. **Who answers
  is the caller's shell**: inside a run or an agent's shell, the coordinator, never its own
  run's question — no flag says otherwise. Going on by itself or parking again withdraws
  every earlier card not consumed; a start mends a park with no card and an ended run's
  standing cards; a resume that is no answer and a run's end withdraw what the run had
  standing. The
  coordinator may not answer a `person` gate (`may_answer`); `question escalate` passes an
  open question to a person. No warm hosting of Claude's own question tools yet. `docs/architecture/agents.md`'s *A question
  is a file, and the inbox is the directory* has the reasoning. **The window's inbox is a card
  per open or escalated question on top of the Control Centre** (`agent_questions/cards.py`,
  handed to `status_board` as the `question_cards` factory): who asks — a playbook's gate says
  whose judgement it waits for — the step, the kind,
  the question, a button per choice and a person's own words — `inbox.answer` with the person
  as `by` — *Retry Now* on a `limit` or `blocked` card (`inbox.retry_now`) and *Go to Step*;
  oldest first, polled by `questions.fingerprint` and reconciled by id so a half-typed answer
  survives. `docs/architecture/agents.md`'s *The inbox is cards on top of the Control Centre*
  has the reasoning.
- **A coordinator is a briefing over the verbs, never an engine.** `agent_briefing/coordinator.py`
  composes it and `dplanner agent coordinate <keys> [--callsign <word>]` prints it: take the
  claim, start each ready step with `agent run --playbook --callsign <member>`, watch, answer
  what `may_answer` allows and escalate the rest, verify and merge into the feature branch,
  release. **Only agent steps get members**; a milestone, cut, wait or person's step in the
  selection is context, and only a selection with no agent step is refused. **Callsigns** are
  `claims.member`: the squad word, `-actual` for the coordinator, `-two`… in selection order,
  `-two-one` for a sub-agent, `-watch` for the verifier. **The coordinator chooses its own
  word**: with no `--callsign` the briefing opens with *Choose your squad word* (the rules and
  the words running now) and its first order is `claim take`, which refuses a word a live or
  parked claim in the library answers to unless the caller's `DPLANNER_CALLSIGN` is that
  squad's. **Step ▸ Autonomous Work ▸ Local ▸ <profile>** (`agent_launch/module.py`'s
  `_coordinate`) saves, then opens the profile's terminal in the code checkout on that
  briefing with `at_once` the window's *Max agents* — no worktree, no claim of its own, no
  squad word picked; *Remote ▸* waits for workers. **`DPLANNER_CALLSIGN` names the member a
  shell is**: the coordinator sets its own once it has a word, the supervisor sets each turn's
  to its run's member, and an agent shell's heartbeat renews that squad's claims alone. A
  pass's stages run as the member that started it (the first run records it); a worker's
  preamble names it; workers' branches stay `agent/<run name>`. A lesson a run teaches the
  coordinator is one sentence in its loop, not a paragraph. **Headless, it needs a waker
  and `--allowedTools "Bash(gh pr merge:*)"`** — a `-p` turn has no scheduled wake-up, and
  Claude's auto mode refuses its merge; the loop says both.
  `docs/architecture/agents.md`'s *A coordinator is briefed, never built in* has the reasoning.
- **A headless run is driven by its supervisor, and nothing waits on it.** `dplanner agent
  supervise <run>` (`modules/agent_supervisor/`, started detached by
  `supervisor.start_detached`) is the record's **one writer**: it starts each turn through
  `Headless.command`, tees the stream to `turn-<n>.jsonl`, kills a stall (no output while no
  tool runs, `Headless.stall`), a runaway (`Guards.runaway` events producing nothing) or an
  overrun (the stage's wall clock), writes the turn's end and its usage — counted from that
  stream — and then ends, parks or retries (a review done without its verdict is asked once
  more, prompt `verdict`; a playbook's run that ends `done` starts its pass's
  `playbook advance`, detached): `done`/`stopped` end it; `asked`, `denied`,
  `limit`, a runaway and a failure no retry mends park it and the process exits (but for a
  limit whose reset is known); other
  failures retry after 30 s, 2 min and 10 min, and a fourth in a row parks. A parked run
  resumes by `--prompt answer|continue|reset|retry`, or bare on an answered question. It
  opens no library. **A limit with a known reset waits in its supervisor**, which answers the
  `limit` question for the clock (`answer.by.kind: clock`) at the reset and resumes with
  `reset`; **Retry now** is a person's answer to the same question (`inbox.retry_now`, `dplanner
  agent retry`, *Step ▸ Retry Now*), resumed with `retry` — inside the waiting supervisor,
  in the environment it started with; only with none waiting does the answer start one. A reset the turn did not report is
  the account's last-known one (`limits.py`, `config_dir()/usage-limits.json`); with neither,
  the run parks for a person; one already past is waited for once (`past-reset`), never
  twice in a row. **A SIGTERM during the wait leaves the run parked** for `revive`; only a
  fence ends a waiting run — `supervisor.stop`'s fence and SIGTERM end it at once. *Retry now* is a retry only on a `limit` or `blocked` question
  (`supervisor.RETRYABLE`) — on any other, the words are the answer. An account is the
  harness and its config home (`limits.account_of`), and every observation carries its
  turn's end: older windows never replace newer, and only a turn answered after the
  exhaustion lifts it. **Nothing else starts on an account that ran out** — a turn
  carrying no answer parks `limit`/`held` unstarted — and **a new headless launch waits** while
  a window is at or above `limits.hold_at()` (95 %): `limits.hold`, which `launch.headless_refusal`
  returns, so `agent run` and every headless launch refuse with its words. **Its locks
  are the OS's** (`supervisor.lock` for its life, `record.lock` across every read-modify-write
  of the record — `fence()` takes it too), never a file judged stale and deleted. **A kill
  ends the whole process group**, and every way out of a turn ends it, so nothing runs
  unwatched (`failed`/`supervisor-error`). **A turn that ends the run is written with the
  run's end.** The harvest, `store` and `aspect.end` never write a headless record. Never add
  a path that waits on a process for a person. `docs/architecture/agents.md`'s *A headless run
  is driven by its supervisor* has the reasoning.
