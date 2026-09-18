---
paths:
  - "src/dplanner/domain/{store,library_file,plan_repo,relocate,repositories,migrations,at_work,locations}.py"
  - "src/dplanner/core/storage/**"
  - "src/dplanner/core/{fsio,repository}.py"
  - "src/dplanner/framework/{autosave,session,window_watch,project_list_segment}.py"
  - "src/dplanner/modules/{sync,library,library_watch,agent_at_work,projects,github}/**"
  - "src/dplanner/cli/discovery.py"
  - "tests/domain/test_{store,library_file,plan_repo,relocate,repositories,at_work,project_locations,migration_v3}*.py"
  - "tests/core/test_{storage_contract,locations,pointer,remotes,sparse}.py"
  - "tests/framework/test_{autosave,session}.py"
  - "tests/modules/test_{sync,library,agent_at_work,projects,project_dialog,open_projects,move_plan,github}*.py"
  - "tests/cli/test_{library_verbs,project_repos,agent_work}.py"
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
  merge arrives like any outside change), take theirs, keep mine, or later. *Later* leaves
  the question standing in the notice bar with *Settle…* on it — one fact in one place,
  which is what retired the status-bar button it used to leave. The watcher no
  longer waits for a quiet window: a flush re-stamps as it writes, so our own writes never
  read as foreign. Branch switch and pull go through the same `SessionControl.refresh`,
  clearing undo history (theirs describes another tree). `ARCHITECTURE.md`'s *Adopting the
  other writer's changes in place* has the reasoning.
- **An agent at work says so, and the window says it back.** The other writer is
  invisible, which is the whole problem: a developer editing a step an agent is rewriting
  finds out when a modal asks them to settle a collision they did not cause. So an agent
  announces itself — `dplanner agent-work start '<what I am doing>' [--step S7] [--of N]`,
  `agent-work set`, `agent-work end`, `agent-work show` — and `modules/agent_at_work/`
  polls the claims at the watcher's cadence and stands one `Notice` per claim over the
  window's content: an **amber band** across it (the `warn` tone — a caution about another
  writer, never the red an error owns), the turning arc, the agent's words, its own count
  filling that band with the percentage beside *Clear*, and when it was last heard from. A
  claim that has gone quiet drops to plain information and loses the band. **Liveness is
  reported, never guessed** (`domain/at_work.py`): nothing can see another process, so a
  claim that has gone quiet changes tense — *was at work …
  last heard 22 minutes ago* — instead of disappearing, and it ends three ways and no
  other: the agent ends it, a person clears it from the banner, or a later claim sweeps
  one nobody has renewed since yesterday. **Every `dplanner` run is the sign of life** —
  `cli/main.py` renews the project's standing claims, so an agent that is working never
  needs a heartbeat — and **only from inside an agent's shell**, the marker `entry.py`
  refuses the window word on, because a developer's own terminal must not vouch for
  somebody else. A claim is per user and per machine (`config_dir()/at-work/`, one file
  per claim so two agents never lose each other's update), never the plan: a heartbeat in
  a project directory would commit into everybody's history. **The window makes no claim,
  ever** — its only write is the clear. **And while an agent is at work the collision
  waits rather than interrupts**: `library_watch` leaves its question in the notice bar
  and the status bar instead of raising the modal, and names the agent in the dialog when
  the person does open it. `ARCHITECTURE.md`'s *An agent at work says so* has the
  reasoning.
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
  always writes outside any store; Open Project and Remove from Library only remember and
  forget. Neither is honestly reversible, so they apply directly with `LIBRARY_ORIGIN` —
  the root's `connect_project` — and the library file is rewritten by the ordinary flush
  (a structure mark on the library root). The verbs live in `modules/projects/`; the
  library module keeps New/Open Project Library and the title.
- **There are two ways into a library and a project link is what makes the second one
  possible.** *Open Project…* is a wizard (`modules/projects/open_dialog.py`) over a
  chooser page, a **link** page and a **browse** page — the old Open Projects dialog, now
  `browse_page.py` — and, when the joined plan names repositories this machine lacks, the
  **Repositories** page. Every way ends at one `Joined(directory, checkouts)` on disk and
  the module connects it, so none grew a membership path of its own; the chooser remembers
  which way this person uses and a machine that has never chosen opens on the link, the
  only one somebody with no plan repository can act on. *File ▸ Share Project…* writes what
  that page reads. **`domain/project_link.py` is the whole vocabulary** — the document, the
  `.dlink` file, the `dplanner://project?…` line, and `find_clone`, which with the
  library's checkouts map is what stops the wizard cloning something this machine already
  has — and no surface
  parses a link itself. **The window clones and the terminal does not**: the link page runs
  it through `TaskRunner` inside the page the person pressed, while `dplanner project open`
  resolves against known clones and otherwise refuses with the `git clone` line, the rule
  `library add` already set. The link **carries no access**, and the Share dialog says so
  in a sentence rather than leaving somebody to assume otherwise. `FORMAT.md`'s *The
  project link* is the format; `ARCHITECTURE.md`'s *Why membership changes bypass the undo
  stack* has the reasoning.
- **The GitHub tab's standing line is the picker fetch.** Showing a step fetches the
  repository's branches and PRs (again past `LISTS_TTL_S`), and the answer says where
  the refs stand — the PR's state and title now, whether the branch is still on the
  remote — writes fresh PR state into the step with the refresher's origin, and enables
  *Open PR* / *Open branch* (`aspect.py`'s `pr_url`/`branch_url`, the recorded URL over
  one built from the number). `dplanner github show` is the terminal's copy.
- **A project names its locations; the plan repository stays derived.** *Where does the
  plan live?* — the **plan repository** — is `find_repo_root(project dir)`, never stored.
  *Which places is it about?* — its **locations** (`domain/locations.py`: a role, a
  repository as git prints its remote, a position inside it, an optional ref and label,
  an id minted per project) — is `Project.locations`, shared in `project.dproj`; the
  first `code` row is the code repository every older reader means. **Roles are a
  registry**: the domain declares `code` (the CLI must find a project from a checkout
  without loading a module) and a module declares its own in a Qt-free `roles.py`
  (`spec`, `reporting`) that `default_location_roles()` gathers — a role this build
  does not know is kept and written back untouched. *Where is each on this machine?* is
  the library file's `checkouts` map, **per repository, never per project**
  (`store.checkout_for`/`set_checkout`, keyed by `canonical_remote`, written straight into
  the file), and `locations.place` answers it in one order: the recorded checkout, the plan
  repository itself when the row names it, a managed clone for a role that does not
  write (the git spec source's cache, keyed as it keys it), or nowhere. **Whether a
  location needs a working checkout follows from `LocationRole.writes`**: spec is fetched
  on demand and never asks, **a managed clone is never written**; code and reporting need
  one, and **a verb that needs one gets it from `modules/projects/checkouts.py`'s
  `CheckoutService`** — the recorded checkout at once, else a clone on a task, recorded
  per repository. **The clone policy decides where, never whether** (`repositories_folder.
  clone_policy`, Settings ▸ Repositories): `KEPT`, the default, under `config_dir()/
  checkouts/` through `core/storage/kept.py` — a full working clone, hardened only while
  made, never in a plan repository, a project directory or the repositories folder — or
  `FOLDER`, the repositories folder asked once. Run Agent and Open Agent in Code say
  *clones … first* and clone before launching (`StepAgentInstructionDeps.
  ensure_checkouts`); Save clones an unplaced reporting repository first
  (`SyncDeps.prepare_save`), the quit-time save never; the wizard's Repositories page
  shows under `FOLDER` alone. `Placement.kept` is wording only (*kept by DPlanner at …*);
  a repository stored as a path is placed there only when a working tree is there. `domain/repositories.py` is
  the one derivation (`RepositoryFacts` over placements, with `code`/`repository`/
  `checkout` as the primary row's; separated, colocated, legacy; `warns` unless
  `colocation == "accepted"`), and every reader asks it — lint's `repo.unset`/
  `repo.colocated` and `location.invalid`/`unknown_role`/`duplicate`, the briefing's
  preamble and its locations paragraph, the Project dialog, the Repositories card, the
  opening status line. The root hands the agent module `facts_for` and it decides where
  an agent works: the checkout of the code location the step's `workplace` names, else
  the primary's, or the plan's own repository for the older shape; a conflict is settled
  in the plan repository whatever the code is. `cli/discovery.py` finds the project from a
  checkout whose `origin` is one of its code locations (`canonical_remote`) and records
  the checkout the first time; the wrapper exports `DPLANNER_PROJECT`. The verbs are
  `dplanner location list|roles|add|set|remove|checkout` and `project create --code`,
  every mutating one a `SetFieldCommand` on `locations` — the table the dialog pushes.
  A plan repository holds
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
  `ARCHITECTURE.md`'s *A project names its locations* has the reasoning.
- **The Project dialog is the Locations table over two log columns.** A location answers
  two questions — *which repository and position is it* and *where is it on this machine*
  — and the table (`locations_table.py`, the `Table` primitive) asks both of every row,
  greyed where nothing is here yet; `repos.location_words` is the one wording, read by the
  Repositories card too, so neither surface can word a fact the other way. **Add ▾ renders
  the role registry** and a row's **⋯** its verbs (edit, choose checkout, clone, open,
  remove), built when they open and greyed *with the reason in their words* rather than
  dropped; a right-click on a row renders the same ⋯. Adding or editing a row is one fit
  dialog (`location_dialog.py`): the repository as a combo led by what the project and
  the library already name and followed by what gh knows — listed on a task the first
  time the dialog is seen and again on the refresh glyph, whose `Spinner` turns meanwhile;
  a refusal is a line under the row in the information tone — the position with
  *Browse…* over the checkout when this machine has one and over the remote's tree
  (`RepositoryServices.list_folders`, a `QTreeWidget`, never a clone) when it does not,
  and the ⋯'s *From a folder on this computer…*, which reads repository, position and
  checkout off one picked folder (`domain.locations.located_folder`, the one reader of a
  folder's identity, which the Project dialog's *Choose Checkout…* and the wizard's *Use
  a checkout I have…* share) and records the checkout through the `record_checkout` the
  dialog was built with; refused in words while the row cannot stand. **Create mode is
  the same table over a draft** the form holds until Create seeds the project; a clone run from the
  draft's ⋯ lands in `NewProjectSpec.checkouts`. The two log columns keep the primary
  code's and the plan's history, and the code column's ⋯ acts on the primary code row
  through the same `_set_locations`. Every edit is one `SetFieldCommand` on `locations`.
  **The Open Project wizard asks after the clone, under the folder policy**:
  `repositories_page.py` lists the worked-in repositories the joined plan names that this
  machine lacks — clone into the repositories folder, use a checkout I have, or later;
  read-only rows are not listed — so the link page names nothing but the plan; under the
  kept policy nothing is asked and the verb that first needs a repository clones it. `ARCHITECTURE.md`'s *The Project dialog is
  the Locations table* has the reasoning.
