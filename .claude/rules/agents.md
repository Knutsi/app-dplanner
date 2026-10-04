---
paths:
  - "src/dplanner/modules/{agent_briefing,step_agent_instruction,step_agent_run,step_review,agent_claude,agent_codex,agent_opencode}/**"
  - "src/dplanner/domain/agents.py"
  - "tests/modules/test_agent_*.py"
  - "tests/{cli,modules}/test_review*.py"
  - "scripts/render_briefing_size.py"
---

# Agents — Run Agent, worktrees, run directories, usage, harnesses, profiles and reviews

- **Running an agent launches a peer, never a task.** *Run Agent* spawns a detached terminal
  the user owns — not a `TaskRunner` body, which would promise cancel and progress nobody
  can honestly deliver. The terminal opens at the project's **git repository root** (via
  the `workdir_for` seam the composition root wires from `find_repo_root`). The prompt goes
  to a per-run temp directory, never the project. The agent reports back through the CLI
  (`status set`, `agent-state set`, `note add`). **The graph gates launching**: a step
  whose `requires` do not all read done (through `status_for` on the module's Deps, the
  Step statuses tab's seam, where a wait reads done once it is over and a step under
  review or waiting on its merge does not — unless the link into this step auto-progresses,
  `progression.outstanding()` being the one answer) gets a confirmation
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
  meant. What the window launches on its own is held to the same number as a *live* cap
  (below).
  **A launch that opened a shell claims the step is in progress** — `mark_started`, the
  writer half of that same seam, applied off the undo stack the way the launch stamp is
  (`planning/status.py`'s `record_started`), because Ctrl+Z must not file a step as pending while
  an agent works in it. Over a selection it is claimed per step as each shell opens, so a
  run that stopped at its third step has claimed two. It is the *Agent profiles ▸ On launch* switch
  beside *Max agents launched at once*, on by default: the agent's own first report is
  minutes away and a step somebody is working on that still reads pending is a lie the
  plan was never asked to tell. Only Run Agent and its unattended twin `launch_due` make
  the claim — in the step loop, never in the shared `_launch` — so a conflict handed to an
  agent, a merge of two writers' plan files and not the step's work, claims nothing.
  **The briefing never rides in argv, and the peer is a top-level session.** The
  agent's opening line is `launcher.opening_prompt` — a pointer at `prompt.md`, carrying
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
  `ARCHITECTURE.md`'s *Running an agent launches a peer, not a task* has the reasoning.
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
  suite never depends on being run by an agent. `ARCHITECTURE.md`'s *An agent finishes at
  Ready for review* has the reasoning.
- **A step that collects is briefed with what it collects, and its sources are told.**
  `agent_briefing/sections.py`'s `step_sections` adds *Work you collect* for a step with auto-progress links: each
  source's key, title, status, branch, PR and worktree — `agent_briefing.worktree.workdir(facts, source)`
  under the source's run name, said as a path only when the directory is on this machine —
  then the duty to land that work, the right to `status set <source> done`, and the way to
  send unready work back (`review start|post|wait <collector> --to <source>`). That is why
  `step_sections` is handed the repository facts, as the preamble is. Each source's
  `epilogue` names who collects it and leaves its done to them. The status guard
  needed nothing: an agent may already finish a step under review.
- **The window launches what the plan made due, and only a window does.** Due is the root's
  one derivation `_due_now`: `progression.due` (an agent step, pending, no run, nothing
  outstanding, and a prerequisite fulfilled *through* an auto-progress link) and
  `step_review/aspect.py`'s `due_turns` (a conversation's side with the turn, no run, not launched for that
  turn — `*_turn_launched` holds the stamp that began it, equality not order). The terminal
  says it (`_status_written` after every status-moving verb, text only; `progression show`'s
  `due`) and `step_agent_instruction/auto_launch.py` launches it: **level-triggered** — after
  every change of any origin, the day turning, a run ending (`StepAgentRunDeps.ended`), the
  watcher settling (`LibraryWatchDeps.settled`) and once at start, over a **0 ms**
  `Debounced` registered with the service — never on an edge, and never held behind a
  modal, which a view's settle is; a title or prose edit only forgets that step's refusal. A pass stands down while
  `changed_underneath()`, asked only once something is due and the **live cap** (*Max
  agents* against the tracker's live runs) has a slot; re-reads each step before its shell
  opens; launches through `launch_due`, which asks nothing (no confirmation, no clone, no
  fallback — a refusal is a status line, remembered until that step, the switch or a
  profile changes); and writes the claim at the spawn — in progress whatever *On launch*
  says, or the round's stamp for a turn — flushing at once. It must run **after** the
  adoption that woke it (the store mutes dirty forwarding while adopting), so its tests turn
  immediate mode off and `flush_all()`. The profile is the step's (`preferred_agent`: a
  review's agent, refused when no profile runs it). **Who launches**: *Agent profiles ▸ When
  a step becomes due*, per user and machine, **off by default**, and among windows on one
  library the holder of a `LaunchLock` (`QLockFile` under `config_dir()/auto-launch/`,
  stale only once its process is gone), built once per session by `new_session` so a
  reload keeps the hold — none in a test or script unless handed a directory. **Plan mode
  waits on a person**: `record_launch(plans_first=)` from the harness's `plan_mode` words,
  `asks_person` for *Waits for you*, and a notice while an agent launched here waits.
  `ARCHITECTURE.md`'s *Auto-progress is launched by the window* has the reasoning and the
  race across machines.
- **A step names the code location it works in.** With several code rows in a project,
  the agent-instruction entry's `workplace` holds a location id (`aspect.workplace`,
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
  `ARCHITECTURE.md`'s *An agent may be opened with nothing to do* has the reasoning.
- **A shell of your own where a step's work is, and it is not a run.** *Step ▸ Open
  Terminal in Worktree* (`agent.open_shell`; *…in Checkout* for a step whose worktree is
  off) opens the default profile's terminal on `launcher.shell_script` — `cd` there, export
  `$DPLANNER_PROJECT`, then the person's `$SHELL` (on Windows a `cmd` of its own, since a
  row that runs the script and closes would close on the prompt) — and nothing else: no
  briefing, no shell facts, no exit file, no run recorded, nothing claimed in progress, a
  `notice()` when no terminal opens. Its directory is found by the wrapper script's own
  name for it (`worktree_path(workdir, run_name_of(step))`), so it is greyed with *Run Agent
  prepares one* until that directory exists. It is in Step ▸ `agent` beside *Show Agent
  Terminal* and *Open Pull Request*, so a status row's ⋮ offers all three.
- **A worktree is the step's decision, and the run is named after the step.** Whether the
  agent gets a fresh git worktree is the agent aspect's `worktree` (absent = on; the Agent
  tab's checkbox, `dplanner agent worktree <step> off`, `step add --no-worktree`) — a fact
  about the step, never a setting, because only a step that must act on the checkout the
  window shows (a release cut, a conflict) turns it off. The wrapper script prepares
  `.dplanner-worktrees/<run name>` on branch `agent/<run name>` **and stops with git's
  reason if it cannot** — the first version swallowed the error and ran two "isolated"
  agents on one checkout, because `.dplanner/` is the pointer *file* a subfolder project
  leaves at the repo root. The run name is `agent_briefing.worktree.run_name`: the step's key, its ticket
  key and its title slug, ref-safe (`f7-PROJ-12-build-the-modal`), composed by
  `run_name_of` from the step's key and ticket, which the launcher never reads. The briefing's preamble names that very worktree
  and tells the agent to **stop if it is not in it**; the epilogue addresses every verb by
  the step's key. Inside a worktree the CLI resolves the branch's copy of the plan to the
  library project of the same id (`cli/discovery.py`), so `dplanner status set` reaches
  the plan the window shows. **What a step is can rule a worktree out**: `agent_briefing.worktree.no_worktree`
  says why — a review reads the work it reviews — and every surface asks its
  `worktree(step)`, never the aspect: Run Agent, `agent prompt`,
  *Open Terminal in Worktree|Checkout*, the Agent tab (its box unticked and greyed with the
  reason) and `agent worktree … on` (refused). `ARCHITECTURE.md`'s *A worktree is the
  step's decision* has the reasoning.
- **A run starts from the remote, and the plan names its base.** `planning.branches.BranchPlan` —
  decided once by `branches/plan.py`'s `branch_plan`, handed to Run Agent as `branch_plan` and to
  `brief()` as a plain value — is the branch a worktree is
  on (its own `agent/<run name>`, or the feature branch for a landing), where a new one
  starts, what the first run in a stretch may cut on the remote, and the PR's base. The
  wrapper script **fetches and starts the branch from the plan's start** — a stretch's
  branch, else the code row's `Location.ref` as the mainline, else the remote's default,
  looked up — **never from whatever the checkout has checked out**, with `--no-track` (a
  landing on the feature branch tracks it); it cuts a missing branch only when told to
  (`create`, set while nothing on the stretch has recorded a branch or a PR) by pushing a
  ref, never checking one out, and **refuses a branch gone from the remote** rather than
  re-cut it from the mainline. It sets `gh-merge-base` as a backstop for the `--base` the
  epilogue names; the preamble checks the plan's branch. Every name is checked with
  `sparse.valid_ref` before it reaches a script. A landing is briefed like a review is —
  its instructions generated from the stretch it closes (`agent_briefing/instructions.py`, *Work you
  land*): merge the mainline in as a merge commit, never a squash, and open the branch's
  own PR. **A PR merged into the branch of an open stretch accepts its step** from
  ready-for-review (`record_merged(accepted_by_merge=)`, the root's `finish_merged` on both
  surfaces), since the branch's review comes after its landing; the GitHub aspect records
  the base a PR merges into (`pr_base`, format 2). `ARCHITECTURE.md`'s *A branch stretch is
  bracketed by a cut and a landing* has the reasoning.
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
  `ARCHITECTURE.md`'s *The peer reports back through its run directory* has the
  reasoning.
- **What a run consumed is a ledger record, harvested by anyone — never caught at the
  end.** The launch writes the run's record into `<project>/ledger/YYYY-MM/<run id>.json`
  (`domain/ledger.py`; `harvest.launch_record`, through the tracker's `project_dir` seam):
  step, harness, the worktree it works in, the session when the harness names one. A
  harvest (`step_agent_run/harvest.py`) re-reads the CLI's own records of the run's whole
  tree — main agent and every subagent, per model, as `in`/`cached`/`out` — and rewrites the
  record; it is idempotent, so the triggers are many and none is load-bearing: the wrapper's
  `dplanner usage harvest --run` after the agent exits (`launcher.HARVEST`, no window
  needed), the tracker on settle (`harvest.end`, then a sweep), and the sweep at start and
  every five minutes through a `TaskRunner` — started only when `harvest.anything_due` finds
  a run of this machine not read since it ended. **Never add a usage path that depends on
  seeing the end.** One writer per file (only the launching machine can read the vendor
  records), outside `PLAN_ENTRIES`, committed by Save, carried by Move Plan; a harness that
  mints its session claims the earliest *unclaimed* one (`RunFacts.claimed`) and the record
  keeps it. No dollars: tokens only. `agent_usage` on the step is retired, absorbed into
  `legacy` records at open. `dplanner usage show|list|harvest|record` is the terminal's half.
  `ARCHITECTURE.md`'s *Usage is a ledger, harvested by anyone* has the reasoning.
  **And what the run was *handed*:** `prompt_chars`, measured in `launcher.prepare` —
  the one place that knows what reached `prompt.md` — carried on `LaunchFiles` to the
  tracker, kept on the **`AgentRun`** and on the run's ledger record. **A size does not
  total** — two briefings added together is not a quantity anybody spends — so `usage
  show`'s total and the step's own phrase stay tokens-only, and `brief_words` says the unit
  out loud (*briefed 18.4k chars*) because the number beside it is tokens.
  `ARCHITECTURE.md`'s *What a run was handed* has the reasoning.
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
  the ledger record, is what makes such a run resumable afterwards. `ARCHITECTURE.md`'s *An agent CLI is a harness* has the reasoning.
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
  `step_agent_instruction/profiles.py`: a `Profile` is an agent command and a terminal
  template under a name, kept per user (`user_config`; the two single settings they
  replaced are read as the default profile when no list is stored). `agent.run` runs
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
- **A review is a conversation kept on the step that asks.** `modules/step_review/` holds
  two aspect ids. `step_review` is the settings: agent, lenses and cap, with absence
  meaning the default profile, architecture and security, and three rounds.
  `review_rounds` is the ledger, on the review or on a collector. Rules:
  - **The subject is the step a review `requires`, read off the graph and never stored.**
    Lint `review.subject` names a review with none or several.
  - **A round holds only texts and stamps.** Its state and whose turn it is are derived
    (`step_review.aspect.turn`), never stored.
  - **Who a step may talk to is whoever it takes work from review on** (the root's
    `auto_progress.aspect.auto_progresses`), so a collector sends work upstream with the same verbs and `--to`.
    `approve` and `escalate` are a review's alone.
  - **Every status a `review` verb moves goes through `status_command`**, the writer
    `status set` uses, handed in as the root's `set_status`. A stopped status ends a claim
    exactly as `status set` does.
  - **The window posts nothing, and reads all of it** — its one write to the ledger is a
    turn's launch stamp (below): the Review tab is the settings and a
    read-only list, and *Step ▸ Review Conversation…* (`review.conversation`; the tab's
    *Open Conversation…* and a row's double-click) opens `conversation.py`'s dialog — every
    message beside the picked one in full, live on the ledger. It is **enabled by the ledger,
    never by the aspect** (`rounds(step)`), so a collector's upstream conversation opens
    too, and the tab and the dialog build their rows with one `message_rows`.
  - **Each side is briefed with the conversation.** A review's `## Instructions` is
    generated (`agent_briefing/instructions.py`) from its aspect and its subject — whom, each lens's
    `Lens.asks` (an id this build does not name is a skill to use), the round protocol and
    the cap — and its own prose rides inside as what to look for. *Work you review* says
    where the subject's work is (`sections.py`'s `_source_line`, *Work you collect*'s line), and the run
    gets no worktree. A step a review `reviews()` is told to set `pending-approval`, `review
    wait`, take and reply, and when to stop waiting; a review's epilogue is its verdicts.
    A conversation still going is a *Review rounds with …* section on both sides, so a
    relaunch resumes it.
  - **`review wait` reads a fresh `LibraryStore` each poll and holds nothing between.** It
    exits 0 on an arrival and 3 on a timeout, under an agent tool's ten minutes. Its loop is
    `await_turn`, tested with an injected sleep and never a thread.

  `ARCHITECTURE.md`'s *A review is a conversation kept on the step that asks* has the
  reasoning.
