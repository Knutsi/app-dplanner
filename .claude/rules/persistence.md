---
paths:
  - "src/dplanner/domain/{store,library_file,plan_repo,relocate,repositories,migrations}.py"
  - "src/dplanner/core/storage/**"
  - "src/dplanner/core/{fsio,repository}.py"
  - "src/dplanner/framework/{autosave,session,window_watch,project_list_segment}.py"
  - "src/dplanner/modules/{sync,library,library_watch,projects,github}/**"
  - "src/dplanner/cli/discovery.py"
  - "tests/domain/test_{store,library_file,plan_repo,relocate,repositories}*.py"
  - "tests/core/test_{storage_contract,locations,pointer,remotes}.py"
  - "tests/framework/test_{autosave,session}.py"
  - "tests/modules/test_{sync,library,projects,project_dialog,open_projects,move_plan,github}*.py"
  - "tests/cli/test_{library_verbs,project_repos}.py"
---

# Persistence — save, two writers, outside changes, reload and repositories

- **There is no Save-file action.** Autosave writes 1.5 s after the last change; *Save*
  means recording a version: **one commit per dirty repository, scoped to that repository's
  project directories** — several projects in one repo save as one commit, and the user's
  source code is never swept up. Quitting with dirty repos asks once, listing them
  (`modules/sync/exit_dialog.py`, on the dialog frame), and **the save that follows is an
  ordinary task under a modal progress dialog** — a row per repository, publishing then
  committing (`modules/sync/save_progress.py`) — with the **close deferred** until it ends:
  the guard starts the save and returns False, and the dialog closes the window. That is
  what retired the synchronous save-at-quit exception; a failure stands in that dialog
  rather than being lost with the window. **Its bar reads the repositories recorded as a
  floor and fills between them from how long the last save took** — `TaskService`'s
  duration memory, kept across sessions — never an estimate that could contradict what has
  landed. Never `exec()` a dialog from inside a close
  guard — the guards run inside `closeEvent`, so a nested modal loop there is re-entrant.
  Branch verbs act on the focused project's repository.
  The CLI has no timer: a run is a transaction that flushes once, at the end, and writes
  nothing if the verb failed. `ARCHITECTURE.md`'s *Save spans repositories; the exit dialog
  says what it records* has the reasoning.
- **Two writers are expected.** An agent runs `dplanner` against a project a window has
  open. The store records what each project directory last looked like and **refuses to
  flush over anything that changed underneath** (`StaleWorkspaceError`) — checked **per
  project**, so one project's outside edit never blocks saving another; the library file
  has its own stamp. That one check also makes a lock between CLI runs unnecessary. **What
  it looks at is the plan, not the directory**: `PLAN_ENTRIES` (`project.dproj`,
  `modules/`, `steps/`) — a project directory is often the repository root, and counting
  the source tree or an agent worktree under `.dplanner-worktrees/` as another writer
  reloaded the window on every edit anyone made.
- **The window takes an outside change in place, entry by entry.** The same per-file
  record says *which* files changed, and each plan file is one entry of one node, so
  `LibraryStore.adopt_outside_changes` reads the change into the live model through the
  mutators with `OUTSIDE_ORIGIN` — prose as `diff_hunks`, so an open editor keeps its
  caret — and re-stamps exactly what it read. Every view repaints as for any foreign edit;
  the window, its tabs, selection and undo history stay. **An entry this window changed and
  has not flushed is a conflict**, reported and not adopted: that project's flush stays
  refused, autosave stays paused, and `modules/library_watch/` asks in a modal — hand both
  versions to the configured agent (Run Agent's launcher; the window yields to disk and the
  merge arrives like any outside change), take theirs, keep mine, or later. The watcher no
  longer waits for a quiet window: a flush re-stamps as it writes, so our own writes never
  read as foreign. Branch switch and pull go through the same `SessionControl.refresh`,
  clearing undo history (theirs describes another tree). `ARCHITECTURE.md`'s *Adopting the
  other writer's changes in place* has the reasoning.
- **A branch switched underneath the window is taken in, and said.** The sync module
  asks every repository's branch at the workspace watcher's cadence (`POLL_MS`) and
  compares it with the one this window last saw; a switch it did not make — a terminal's
  `git checkout`, an agent working in the checkout with its worktree off — goes through
  the same `_take_worktree` as the window's own switch (tree into the model, undo history
  dropped when anything was taken, autosave resumed) and then a warning names the
  repository and both branches. The window's own operations re-baseline when they end,
  so only a switch from outside is ever reported. `ARCHITECTURE.md`'s *A branch switched
  underneath the window* has the reasoning.
- **Reloading the library is a full rebuild — and the fallback, not the rule.**
  `SessionControl.refresh()` adopts; `reload()` is what it falls back to when the store
  cannot read what it found (a pending format migration, a failure halfway), and what *File
  ▸ Reload from Disk* still does. A rebuild is a rebuild because registries refuse duplicate
  ids, which is what makes that the only implementable answer — and the correct one. The
  new window takes the old one's geometry. Opening a *different* library is not even a
  reload: File ▸ New/Open Project Library spawns a detached instance
  (`modules/library/module.py::spawn_instance`).
- **Project membership changes bypass the undo stack.** New Project may `git init` and
  always writes outside any store; Open Projects and Remove from Library only remember and
  forget. Neither is honestly reversible, so they apply directly with `LIBRARY_ORIGIN` —
  the root's `connect_project` — and the library file is rewritten by the ordinary flush
  (a structure mark on the library root). The verbs live in `modules/projects/`; the
  library module keeps New/Open Project Library and the title.
- **The GitHub tab's standing line is the picker fetch.** Showing a step fetches the
  repository's branches and PRs (again past `LISTS_TTL_S`), and the answer says where
  the refs stand — the PR's state and title now, whether the branch is still on the
  remote — writes fresh PR state into the step with the refresher's origin, and enables
  *Open PR* / *Open branch* (`aspect.py`'s `pr_url`/`branch_url`, the recorded URL over
  one built from the number). `dplanner github show` is the terminal's copy.
- **Two repositories, two questions.** *Where does the plan live?* — the **plan
  repository** — is derived: `find_repo_root(project dir)`, never stored. *Which code does
  it plan?* — the **code repository** — is `Project.repository`, the remote URL as git
  prints it (a resolved path for a remote-less one), shared in `project.dproj`. *Where is
  that code here?* is the library file's per-machine `checkout`, written straight into the
  file by `store.set_checkout`. `domain/repositories.py` is the one derivation
  (`RepositoryFacts`: separated, colocated, legacy; `warns` unless `colocation ==
  "accepted"`), and every reader asks it — lint's `repo.unset`/`repo.colocated`, the
  briefing's preamble, the Project dialog, the Repositories card, the opening status line.
  The root hands the agent module `facts_for` and it decides where an agent works: the
  code checkout, or the plan's own repository for the older shape; a conflict is settled in
  the plan repository whatever the code is. `cli/discovery.py` finds the project from a
  checkout whose `origin` is its code repository (`canonical_remote`) and records the
  checkout the first time; the wrapper exports `DPLANNER_PROJECT`. A plan repository holds
  several projects for several people under a `.dplanner` index (`FORMAT.md`); *File ▸ New
  Project…* is the Project dialog in create mode over a picked plan repository, *Open
  Projects…* browses one and adds the chosen projects, and *Move Plan…* moves a plan
  through `domain/relocate.py` and reloads. **It is offered on every project**: picking a
  plan repository is a choice that can be got wrong, and the surface that made it is the
  one that has to be able to change it — so the second move is not a special case, and the
  only thing it must not do is *inherit* (a plan leaving a plan repository keeps the
  checkout it had, and gains none it never had). The card's button says which offer this
  is — *Set up a plan repository…* inside the code, *Move Plan…* once out. `dplanner
  project move` is the same function from the terminal; the briefing and the skill tell an
  agent to run it when the developer asks and never unasked. Never store a plan root, and
  never compare paths where `RepositoryFacts` already answers.
  `ARCHITECTURE.md`'s *Two repositories, two questions* has the reasoning.
- **The Project dialog is two columns, not three fields.** A repository answers two
  questions — *which repository is it* and *where is it on this machine* — and the dialog
  asks both of both, under the column each belongs to, parted by the vertical rule that
  says they are two. `repos.code_lines`/`plan_lines` are the one derivation of those lines
  and the Repositories card reads them too, so neither surface can word a fact the other
  way; a line with nothing to name says what is missing rather than standing blank. Every
  verb of a column is an entry in its **⋯ menu**, built when it opens (a glyph carries the
  colour it was painted in) and greyed *with its reason in its words* rather than dropped,
  so the list to learn never changes shape. `ARCHITECTURE.md`'s *The Project dialog is two
  columns, not three fields* has the reasoning.
