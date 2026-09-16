---
paths:
  - "src/dplanner/modules/{step_agent_instruction,step_agent_run,agent_claude,agent_codex,agent_opencode}/**"
  - "src/dplanner/domain/agents.py"
  - "tests/modules/test_agent_*.py"
  - "scripts/render_briefing_size.py"
---

# Agents — Run Agent, worktrees, run directories, usage, harnesses and profiles

- **Running an agent launches a peer, never a task.** *Run Agent* spawns a detached terminal
  the user owns — not a `TaskRunner` body, which would promise cancel and progress nobody
  can honestly deliver. The terminal opens at the project's **git repository root** (via
  the `workdir_for` seam the composition root wires from `find_repo_root`). The prompt goes
  to a per-run temp directory, never the project. The agent reports back through the CLI
  (`status set`, `agent-state set`, `note add`). **The graph gates launching**: a step
  whose `requires` do not all read done (through `status_for` on the module's Deps, the
  progression board's seam) gets a confirmation naming them before a shell opens — the
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
  **A launch that opened a shell claims the step is in progress** — `mark_started`, the
  writer half of that same seam, applied off the undo stack the way the launch stamp is
  (`step_status`'s `record_started`), because Ctrl+Z must not file a step as pending while
  an agent works in it. Over a selection it is claimed per step as each shell opens, so a
  run that stopped at its third step has claimed two. It is the *Agent profiles ▸ On launch* switch
  beside *Max agents launched at once*, on by default: the agent's own first report is
  minutes away and a step somebody is working on that still reads pending is a lie the
  plan was never asked to tell. Only Run Agent makes the claim — in the step loop, never
  in the shared `_launch` — so a conflict handed to an agent, a merge of two writers' plan
  files and not the step's work, claims nothing.
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
- **A worktree is the step's decision, and the run is named after the step.** Whether the
  agent gets a fresh git worktree is the agent aspect's `worktree` (absent = on; the Agent
  tab's checkbox, `dplanner agent worktree <step> off`, `step add --no-worktree`) — a fact
  about the step, never a setting, because only a step that must act on the checkout the
  window shows (a release cut, a conflict) turns it off. The wrapper script prepares
  `.dplanner-worktrees/<run name>` on branch `agent/<run name>` **and stops with git's
  reason if it cannot** — the first version swallowed the error and ran two "isolated"
  agents on one checkout, because `.dplanner/` is the pointer *file* a subfolder project
  leaves at the repo root. The run name is `launcher.run_name`: the step's key, its ticket
  key and its title slug, ref-safe (`f7-PROJ-12-build-the-modal`), composed by the root
  from aspects the launcher never reads. The briefing's preamble names that very worktree
  and tells the agent to **stop if it is not in it**; the epilogue addresses every verb by
  the step's key. Inside a worktree the CLI resolves the branch's copy of the plan to the
  library project of the same id (`cli/discovery.py`), so `dplanner status set` reaches
  the plan the window shows. `ARCHITECTURE.md`'s *A worktree is the step's decision* has
  the reasoning.
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
- **What a run consumed is read back when it ends, and kept on the step.** The run
  remembers its harness and its session (`AgentRun.harness`, `.session`); when the
  shell ends the tracker asks the harness's `report` and writes a row — harness,
  session, input, output, the vendor's own breakdown under `details`, when — to the
  step's `agent_usage` aspect (`step_agent_run/usage.py`, a second aspect id in that
  package), directly, off the undo stack, with its own origin: tokens were spent
  whether or not anybody presses Ctrl+Z. **Totals are derived** (`usage.totals`), a
  session recorded twice is one row, and `input` means everything sent (cache reads
  and writes included) and `output` everything generated, so two harnesses' numbers
  add on one step. `dplanner usage show|list|record` is the terminal's half —
  `record` reads through the same harness readers, or takes `--input`/`--output` by
  hand; the Agents browser row and the Agent tab say the same words. Claude's
  transcript is an internal format read tolerantly; the OpenTelemetry metrics are the
  supported channel and need a collector, which is deliberately not built here.
  **And what the run was *handed*:** `prompt_chars`, measured in `launcher.prepare` —
  the one place that knows what reached `prompt.md` — carried on `LaunchFiles` to the
  tracker, kept on the **`AgentRun`** and copied onto the usage row when one is written.
  The run is the home because a run still going has no row yet, and a harness with no
  token reader never gets one; a faked zero-token row would have the step claim it spent
  nothing rather than say nothing. **A size does not total** — two briefings added
  together is not a quantity anybody spends — so `usage list`, `usage.totals` and the
  step's own phrase stay tokens-only, and `brief_words` says the unit out loud
  (*briefed 18.4k chars*) because the number beside it is tokens.
  `ARCHITECTURE.md`'s *What a run was handed* has the reasoning, including why this
  needed no format bump where `progress_history` did.
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
  `counts_tokens` is a reader; `capabilities()` words them for the dropdown. Codex and
  OpenCode mint their own ids, so their `report` finds the run by the directory it
  worked in and the launch time, and a found id is what makes such a run resumable
  afterwards. `ARCHITECTURE.md`'s *An agent CLI is a harness* has the reasoning.
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
  the one profile — with a multiplexer, one pane each. The Ready-to-start board's Ready
  lane is the same menu again: each ready card carries a tick, and the lane's *Run N
  Agents* button (top right, level with the caption) drops the child down over the
  ticked steps, publishing them as it opens.
