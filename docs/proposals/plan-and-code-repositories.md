# Plan repositories and code repositories

*Proposal, 2026-09-05. Status: for decision. Written from a full read of the code at `main`
(4fd3759); every file and line named below is on that commit.*

## The short version

A project's directory sits inside a git repository, and today that repository is also the
code the project plans. Every "main drifts" report is that one fact: *Save* commits plan
files to the code repository's `main`, every agent worktree and feature branch carries a
copy of the plan, a `git checkout` in the code checkout swaps the plan under the window,
and a merged branch can carry stale plan files back onto `main`.

The proposal separates the two, and the code is ready for it. Which repository a project
belongs to is read at exactly three seams the composition root already wires — `workdir_for`
(Run Agent), `repository_for` (GitHub refs) and `find_current_project` (the CLI) — plus the
membership dialogs. The store, autosave, the two-writers machinery, the sync module and the
wrapper script keep their shape.

The recommendation, in one paragraph:

> A project keeps living in a directory inside a git repository — the **plan
> repository** — and Save, branches and Update from Remote keep acting on that repository
> exactly as now; nothing new is stored for it. A project gains one shared fact, the **code
> repository** it plans, written into `project.dproj` as the remote URL, and each machine
> keeps one private fact, where that code is checked out here, in the per-user library
> file. Run Agent, the worktrees and the GitHub tab move to the code repository. The CLI
> finds the current project from a code checkout by matching the checkout's `origin`
> against every project's code repository, so an agent needs no configuration — and the
> first `dplanner` call from a checkout records where the code lives. A plan kept inside
> its code repository is still allowed but *warned*: in the window, in `project lint`, and
> in every agent briefing. One verb, `dplanner project move`, and a wizard that calls the
> same function take an existing plan into a plan repository, commit both sides and
> re-point the library.

Two things I would add to what was asked, both argued below: make the plan repository's
committed index (`.dplanner`, one line per project) the way a colleague's clone joins a
library, and let *Save* rebase before it pushes, because a repository that holds only plans
is one where that is safe.

## What the code assumes today, and why main drifts

`ARCHITECTURE.md` (*Repository facts are derived from the project's directory*) records
the decision: "A project *lives in* its repository now, so 'which repository does this
project's work belong to' stopped being a stored association and became a derivation." The
derivation is `find_repo_root(project directory)` for the checkout and `origin_url` for the
remote, and it retired the `project_repo` module, which had stored a per-machine checkout
path in the shared plan.

That is a clean rule with one consequence the field test found: *the plan's history is the
code's history*. Concretely:

- **Save commits to the code repository's current branch.** `SyncService.save_sync` commits
  every dirty repository group scoped to its project directories and pushes;
  `GitHubStorage.push` is a plain `git push -u origin <branch>`. On a code repository that
  is a stream of *Save: 2026-09-05T…* commits on `main` between every feature branch's
  merge base and its merge — and a refused push wherever `main` is protected.
- **Every branch carries a copy of the plan.** An agent worktree on `agent/<run>` starts
  with the plan as it was. `cli/discovery.py` deliberately routes `dplanner` calls made
  inside the worktree to the *library's* project — the main checkout's copy — so the
  branch's copy only goes stale, and merges back cleanly only while nobody touched it.
- **A checkout in the code repository swaps the plan under the window.** The sync module's
  branch poll and its *Branch changed* warning (`_branch_switched_underneath`) exist for
  exactly this, and the text says so: "If an agent is working in this checkout, it did
  this."
- **The window watches the repository for another writer**, and had to be narrowed to
  `PLAN_ENTRIES` because the root also held the source tree (`LibraryStore._snapshot`'s
  docstring tells the story).

Each of these is the coupling itself, not a bug in the mechanism around it. Separating the
repositories removes the cause; the mechanisms stay.

## The design

### Two repositories, two questions

The confusion to avoid is treating "the repository" as one thing. A project answers two
different questions, and they want different storage:

| Question | Answer | Stored? |
|---|---|---|
| **Where does the plan live?** | the *plan repository*: the git repository enclosing the project directory | no — derived by `find_repo_root(project dir)`, exactly as today |
| **Which code does it plan?** | the *code repository*, identified by its remote URL | yes — shared, in `project.dproj` |
| **Where is that code on this machine?** | the *code checkout*, a local path | yes — per user, per machine, in `library.json` |

Save, Review Changes, New/Switch Branch and Update from Remote act on the plan
repository (the store's `repo_groups()`), unchanged. Run Agent, the agent worktrees,
`dplanner github …` and the GitHub tab act on the code repository. `dplanner` writes to the
project directory from wherever it is run, so everything an agent records — status,
handoff, docs, tests, GitHub refs — lands in the plan repository by construction; the
code repository never receives a plan file. Neither repository has to be on GitHub: `gh`
features degrade as they do today.

Keeping the plan repository *derived* is the important choice. The retired
`project_repo` module stored both a repository and a checkout in the shared plan, and was
taken out because a per-machine path in a shared file is wrong on every other machine. The
split above resolves that trade honestly: the identity (a remote URL) is shared, the
location (a path) is private — and the Qt-free per-user file the earlier design lacked
exists now (`core/config_dir.py`, `domain/library_file.py`).

### What is stored where

**`project.dproj`** gains two optional keys, absence encoding the default as everywhere in
`FORMAT.md`:

```json
{
  "id": "…", "created": "…", "format": 2,
  "title": "Search rewrite",
  "repository": "https://github.com/acme/widget",
  "colocation": "accepted"
}
```

- `repository` — the code repository's remote URL as git reports it
  (`git@github.com:acme/widget.git` is kept as typed; matching canonicalises). Absent
  means *not set*: the legacy shape, read as "this plan's repository is its code
  repository", so nothing breaks on the day the build updates.
- `colocation` — `"accepted"` once the people on this project have decided the plan stays
  inside its code repository. It silences the window's banner and the lint finding, and
  nothing else. Absent is the default: warn.

Both are model fields on `Project`, added to `VALUE_FIELDS["project"]`, so `SetFieldCommand`
gives them an undoable window edit and a CLI verb from one table; `_write_meta` and
`_load_project` round-trip them; `_meta_differs` and `_adopt_entry` carry a colleague's
change into an open window; `project_document` exports them. No format migration: the keys
are optional, and format 2 reads them as absent. They are model fields rather than module
data on purpose: `cli/discovery.py` has to read the code repository to resolve a project,
and `cli/` may import `domain` but never a module.

**`library.json`** goes to format 2 with one optional key per entry:

```json
{"format": 2, "projects": [
  {"path": "/home/anna/plans/search-rewrite", "checkout": "/home/anna/src/widget"}
]}
```

`checkout` is where this machine has the project's code repository. Per user, per machine,
Qt-free, already read by both surfaces and already watched by the window
(`_adopt_library_file` learns to update a record's checkout when another instance changes
it). A project with no checkout on this machine opens normally — a spec reader never needs
the code — and Run Agent is disabled with the reason.

**`core/storage/git.py`** gains `canonical_remote(url)`: `github.com/acme/widget` from the
https, ssh and `git@` spellings alike, `.git` and trailing slashes dropped, host
lowercased; a local-path origin canonicalises to its resolved path. Re-exported through
`locations.py`, the storage front door every layer may import.
`modules/github/gh.py::parse_repo` keeps its own GitHub-specific owner/repo parse; the two
answer different questions, and its docstring already says so.

**The `.dplanner` file** at a plan repository's root becomes an **index**: one project
directory per line, relative to the file, appended when a project is created or moved into
that repository. One line is exactly today's pointer, so every existing file is a valid
index. See *Several projects, several people* below.

### How the CLI finds the project from a code checkout

This is the one thing separation breaks, and the fix is small. `find_current_project`
(`cli/discovery.py`) becomes:

1. `--project`, then `$DPLANNER_PROJECT` (new, below), as `--library` and
   `$DPLANNER_LIBRARY` pair today.
2. Walk up from the working directory for `project.dproj` or a `.dplanner` index — the
   plan repository side, unchanged except that an index with several lines answers "several" and
   asks for `--project`. Inside a project directory the walk still finds `project.dproj`
   first.
3. **New.** The working directory is inside a git repository — a linked worktree counts,
   since remotes are shared config and `origin_url` answers inside
   `.dplanner-worktrees/<run>` too. Its origin, canonicalised, is compared with every
   library project's `repository`; a repository with no origin is compared by its main
   checkout against every entry's `checkout`. One match is the answer; several is the
   refusal that already exists ("this repository holds several library projects — pass
   --project"); none falls through.
4. Today's rule 3 — the working directory's main checkout is a library project's plan repository
   root — kept for legacy and colocated projects.
5. Nowhere: no current project, as today.

**The checkout records itself.** When rule 3 resolves a project whose library entry has no
`checkout`, the CLI writes the working directory's main checkout into it — an absent entry
only, never over one. The first `dplanner status set` an agent runs from its worktree is
therefore what teaches the window where the code is, and Run Agent on that machine enables
itself. The topology gate already writes a per-user record from a read verb (`topology
show`); this is the second use of that shape, not a new one.

**One code repository, several projects.** Two projects planning the same repository make
rule 3 ambiguous, and the refusal names them. For an agent that is cheap to avoid: the
wrapper script exports `DPLANNER_PROJECT=<project id>` so every verb in that shell is
scoped without the briefing saying `--project` on each line. One line in `_posix_script`
and `_windows_script`, one lookup in discovery.

`dplanner agent prompt --json` and `project show --json` print all three facts —
`plan`, `repository`, `checkout` — so an agent that wants to know never derives them.

### Run Agent, worktrees and GitHub refs

Both seams are already callbacks on the modules' `Deps`, wired in `modules/__init__.py`;
only the root's lambdas change:

- `workdir_for(step)` (root, line 811) — the code checkout from the library entry when the
  project has a `repository`; the plan repository root when it has none (legacy — the briefing then
  carries the colocation caution). A project with a repository but no checkout here answers
  `""`, and `_can_run` greys Run Agent with *"the code repository is not checked out on this
  machine — Project ▸ Settings…"* in place of today's *"not in a git repository"*.
- `repository_for(step)` (root, line 1167) and `modules/github/cli.py::_repo_url` —
  `project.repository`, falling back to `origin_url(project dir)` when unset. PR pickers,
  the refresher and `dplanner github prs|branches|refresh` then read the code repository.
- The wrapper script (`launcher.py`) is untouched: it prepares `.dplanner-worktrees/<run>`
  under whatever `workdir` it is handed, which is now the code checkout — where the
  worktrees always belonged.
- The conflict hand-off (`hand_conflicts`) is the one launch that edits *plan* entries by
  verb and needs no code. It runs in the plan repository root, which exists on every machine that
  has the project; today it runs in `workdir_for`. Give it the plan repository root explicitly.

### The window

**Project ▸ Settings…** replaces *Rename Project…* (`projects.rename` becomes
`projects.settings` in `modules/projects/verbs.py`; the menu slot stays). One dialog, four
blocks, at `DESIGN.md`'s dialog spacing:

1. *Name* and *Summary* — the two fields Rename edits today, through the undo stack.
2. *Plan* — where it lives: the plan repository's label and branch, read-only, and
   **Move Plan…**, which opens the wizard below.
3. *Code* — *Repository*: an editable combo pre-filled from GitHub
   (`GitHubStorage.list_repositories()`, fetched in a `TaskRunner` body through a callback
   the root wires — rule 8 keeps the concrete provider out of the module), free text for any
   URL, and a blank row for "none yet". *Checkout on this machine*: a path with **Browse…**
   and **Clone…** (`GitHubStorage.clone` into the folder the user picks). A checkout whose
   origin differs from the repository field offers to take the checkout's origin; a
   checkout picked for an empty repository field fills it in.
4. The warning, when the code repository is the plan repository (canonical origins
   equal, or either checkout inside the other): *"This plan would live inside the code it
   plans — see why that drifts"*, with **Keep it here** (writes `colocation: accepted`)
   beside **Move Plan…**. Warned, never refused.

**File ▸ New Project** is the same dialog in create mode: the *Plan* block becomes a picker
— the plan repositories this library already uses (last used first, remembered per user
in `user_config`), **Browse…**, **New on GitHub…** (`init_repo` then
`GitHubStorage.publish`) and **Clone…** — plus a folder name. The default is the last
plan repository used, so the second project is two clicks. The CLI twin: `dplanner
project create` gains `--repository URL` and `--checkout PATH` (a warning line, exit 0,
when they coincide with the plan repository); `dplanner project set <project>
--repository | --checkout | --accept-colocation`; `library add` is unchanged.

**A Repositories card** in the project panel (`services.detail_cards`, first in order)
shows the same three facts and the warning permanently, with *Settings…* and *Move Plan…*.
`ARCHITECTURE.md` notes that the card contract is what the retired `project_repo` card
used; this is that card back, holding a different fact. The panel is where a person looks
at a project, so the state belongs there and not only in a modal.

**At open**, one status-bar line counts the projects that are colocated or have no
repository and are not accepted ("2 plans live inside their code repositories — Project ▸
Settings… to move them"); the card carries the detail per project.

### The agent is told

`_agent_preamble` (root, line 1451) gains a *where the plan lives* paragraph in every
briefing:

- Separated: *"The plan you report to lives in its own repository (`acme/plans`), not in
  this checkout. `dplanner` writes there from wherever it is run; never create, edit or
  commit plan files in this repository."*
- Colocated or legacy: *"WARNING: this plan is kept inside the code repository, under
  `planning/`, on the main checkout's branch. Do not edit or commit anything under that
  directory on your branch — every `dplanner` verb writes to the main checkout — and
  expect planning commits to land on `main` while you work: merge or rebase `main` before
  opening the PR."*

The skill preamble gets a matching *Where the plan lives* section. `dplanner project lint`
reports `repo.unset` and `repo.colocated`, silenced by `colocation: accepted`, each with
the verb that fixes it — lint is how an agent hands a plan over clean.

### Several projects, several people in one plan repository

The plan repository is meant to be shared: one repository holding every plan a team is
working on, cloned by everyone who plans, tests, reads specs or runs agents. Three things
make that work.

**The index.** The `.dplanner` file at the plan repository root lists every project directory in
it, one relative path per line, in the order the panel shows them. `seed_project` and
`project move` append a line; `project delete` removes one; a hand-written line is never
lost. `dplanner library add ~/plans` on a directory that holds an index rather than a
`project.dproj` adds every listed project — the whole onboarding is `git clone` and
`library add`. A line that leads nowhere is reported and skipped while others resolve; a
lone dangling line stays the error it is today.

**Roles need different things.** Reading a spec, writing tests and reviewing a plan need
only the plan repository clone; running agents and running the product need the code checkout too.
That is why the checkout is optional per machine, and why Run Agent is *disabled with the
reason*, never hidden, on a machine without one.

**Save must survive a colleague's push.** Today `push` is a plain `git push` and `pull` is
fast-forward-only, so the second person to Save after a pull is refused with a *Storage*
warning and reconciles in a terminal. In the code repository that caution was right; in a
repository holding nothing but plans, *Save* should be *commit, fetch, rebase onto
`origin/<branch>`, push*, and *Update from Remote* should rebase local planning commits
rather than refuse. Plan files are one entry per node, so two people conflict only when
they edit the same entry of the same node — the granularity the in-window conflict rule
already uses — and a rebase that does conflict aborts and says so. This changes
`GitHubStorage.pull` and `push` (an entry for `NOTES-FOR-APPFRAME.md`), and it is safe
precisely because separation guarantees the repository contains no code.



## Alternatives weighed

- **Plans on an orphan branch of the code repository** (the `gh-pages` shape). One
  repository and no second remote: the window would hold a worktree of a `plans` branch,
  and no feature branch would ever carry plan files. Rejected as the default because it
  cannot hold plans for several code repositories in one place, which is the shared
  plan repository you asked for, and because a push to any branch trips CI and
  protection rules on many code repositories. The design does not preclude it: a plan
  location is "a directory inside a git repository", and that repository may be the code
  repository's `plans` worktree. If wanted, it is one more row in New Project's plan repository
  picker, not a new model.
- **Keep colocation and stop Save from committing to `main`** — commit plans to a side
  branch, or never auto-commit. Treats one symptom: a checkout in the code repository still
  swaps the plan under the window, and every worktree still carries a copy.
- **Store the checkout path in the plan** — the retired `project_repo` trade. Rejected for
  the reason it was retired; the split above is the honest form of the same need.
- **A committed `.dplanner` in the code repository naming the plan repository's remote**, for
  zero-configuration discovery from a fresh code clone. Not needed: matching the
  checkout's origin against the projects' repositories needs no file, and a file in the
  user's code repository is a second source of truth. Could be a later `project link`
  convenience for a repository that wants to advertise its plan.

## Migration

### Detecting the old shape

Every project is one of three, at open, in `project show` and in lint:

- **legacy** — no `repository`. Read as colocated by every derivation (Run Agent opens in
  the plan repository root, GitHub refs read its origin), so a project untouched since the update
  keeps working exactly as it does today.
- **colocated** — a `repository` that canonicalises to the plan repository's origin, or
  a checkout inside the plan repository root, or the plan repository root inside the checkout.
- **separated** — anything else.

Legacy and colocated projects warn unless `colocation` is accepted. Nothing is guessed from
directory contents.

### `dplanner project move` and the wizard

One Qt-free function, `domain/relocate.py::move_project(store, project_id, target_dir, *,
init_repo=False)`, called by the verb `dplanner project move <project> --to
~/plans/search-rewrite [--init-repo]` and by the window's wizard — the two-surfaces rule.
In order:

1. **Check.** `target_dir` does not exist; its parent is inside a git repository (or
   `--init-repo`); the target repository is not the project's code repository (refused,
   not warned — the move exists to end that); the project has nothing unflushed (the window
   flushes and pauses autosave first, as `_run_guarded` does for a branch switch; a CLI run
   has nothing pending by construction).
2. **Copy the plan.** `PLAN_ENTRIES` — `project.dproj`, `modules/`, `steps/` — to the
   target, module file areas included, so specs, images and attachments travel.
3. **Record the code.** Write `repository` = the source repository's origin into the
   target's `project.dproj` unless one is set; drop `colocation`.
4. **Index and pointer.** Append the target to the target repository's `.dplanner` index;
   remove the source's line from the source repository's `.dplanner`. A pointer that leads
   nowhere is a `CliError` in `_follow_pointer`, so the file is rewritten or deleted, never
   left dangling.
5. **Remove the source plan** — `git rm -r` where tracked, plain deletion where not.
6. **Re-point the library.** The entry's `path` becomes the target; its `checkout` becomes
   the source repository's main checkout, which is where the code was all along.
7. **Commit both sides**, scoped, through `GitStorage.commit`: the source *"Move the plan
   of «Search rewrite» to acme/plans"* over the removed paths and the pointer; the target
   *"Add «Search rewrite»"* over the new directory. Pushing stays the user's *Save*.
8. **In the window**, `SessionControl.reload()` — the documented fallback for a change the
   store cannot express in place: the store's records moved under the model, and a rare
   operation does not earn a second path. The new window takes the old one's geometry.

The wizard — reached from the card, the settings dialog and the open-time notice — is one
page: *Where should the plan live?*, the plan repository picker from New Project (known plan
repositories, Browse…, New on GitHub…, Clone…), a folder name defaulting to the project's,
and a plain list of what will happen (copied, removed, two commits, the code checkout stays
at `…/widget`), then **Move**. It runs synchronously with autosave paused — the *storage
operations that rewrite the working tree* exception `ARCHITECTURE.md` already documents.

### What the move leaves behind, on purpose

- **History.** The plan's git history stays in the code repository; the target starts at
  *"Add «…»"*. Rewriting it into the plan repository (`git filter-repo`) is a separate
  tool and out of scope; the wizard says so in one line.
- **Worktrees.** `.dplanner-worktrees/` stays under the code checkout; nothing in it is a
  plan.
- **A running agent** keeps working: its next `dplanner` call resolves by the worktree's
  origin (rule 3) and lands in the moved plan. Its branch still carries the old
  `planning/` copy; merging it after `main` removed that directory deletes it cleanly
  unless the branch changed those files, which the caution forbids. The wizard advises
  finishing running agents first and does not refuse.
- **Old clones** of the code repository that still hold the plan directory resolve it by
  the walk (rule 2) and get *"is a DPlanner project, but it is not in your library"* — the
  message that already exists, now also pointing at the plan repository.

## The seams, one by one

| Where | Today | After |
|---|---|---|
| `cli/discovery.py::find_current_project` | walk up; else main checkout == a project's repo | walk up (index-aware); else **origin match** or checkout match; else legacy repo match; records an absent checkout |
| `modules/__init__.py` `workdir_for` | `find_repo_root(project dir)` | code checkout; plan repository root for legacy; `""` disables with reason |
| `modules/__init__.py` `repository_for`, `github/cli.py::_repo_url` | `origin_url(project dir)` | `project.repository`, legacy fallback to origin |
| `modules/__init__.py::_agent_preamble` | worktree check | + *where the plan lives*, + colocation caution |
| `domain/model.py` `Project`, `VALUE_FIELDS` | `title`, `summary` | + `repository`, `colocation` |
| `domain/store.py` `_load_project`, `_write_meta`, `_meta_differs`, `_adopt_entry` | — | round-trip and adopt the two keys |
| `domain/library_file.py` | `[{"path"}]`, format 1 | + `checkout`, format 2; `_adopt_library_file` updates checkouts |
| `core/storage/git.py`, `locations.py` | — | `canonical_remote()` |
| `core/storage/pointer.py`, `_walk_up`, `_follow_pointer` | one line, never clobbered | an index: append and remove lines; several lines answer "several" |
| `core/storage/github.py` `pull`, `push` | ff-only; plain push | rebase before push, rebase on pull |
| `modules/projects/verbs.py`, new `settings_dialog.py`, `card.py` | Rename Project… | Project Settings…, the Repositories card, the Move wizard |
| `modules/projects/cli.py` | `create --dir`, `rename`, `show` | + `--repository`/`--checkout`, `set`, `move`; `show` prints three facts; lint `repo.*` |
| `modules/library/module.py`, `cli.py` | New/Open Project | New Project in the dialog's create mode; `library add <index root>` |
| `domain/relocate.py` (new) | — | `move_project`, one function for both surfaces |
| `modules/step_agent_instruction/launcher.py` | — | `DPLANNER_PROJECT` in the wrapper's environment |
| `modules/step_agent_instruction/module.py::_can_run` | "not in a git repository" | "no code repository" / "not checked out on this machine" |
| `modules/library_watch` → `hand_conflicts` | `workdir_for` | the plan repository root |
| `modules/sync/module.py` | "If an agent is working in this checkout, it did this." | reworded: the plan's own repository |
| `cli/skill_preamble.md` | "each one a directory inside a git repository" | *Where the plan lives*; never edit plan files by hand |
| `tests/conftest.py` | `library_repo` | + `code_repo`; `make_project(repository=…)` |
| `FORMAT.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `README.md` | *Repository facts are derived* | *Two repositories, two questions* |

Everything else — the store's per-file stamps, adoption and conflicts, autosave, the undo
stack, Save/branch/pull over `repo_groups()`, the wrapper script, run tracking, the Agents
browser, the canvas, every aspect — is untouched. That is the finding of the review: the
architecture already isolates "which repository" behind three callbacks and one function.

## Rollout

In the order that keeps every step green and shippable on its own:

1. **Domain and formats** — `Project.repository` and `colocation`, store round-trip and
   adoption, export/import, `canonical_remote`, library file format 2, the index pointer.
   Qt-free; `tests/domain` and `tests/core`.
2. **CLI** — discovery rules 3 and 4 with the self-recording checkout, `DPLANNER_PROJECT`,
   the `project set`/`show`/`create` flags, `project move`, the lint findings, the skill
   preamble section. `tests/cli`.
3. **Root seams** — `workdir_for`, `repository_for`, the preamble text, the conflict run's
   workdir, `_can_run`'s reasons. `tests/modules` for agent run and github.
4. **Window** — Project Settings replacing Rename, the Repositories card, New Project in
   create mode, the Move wizard, the open-time notice, `library add` over an index.
5. **Docs** — `FORMAT.md`, `ARCHITECTURE.md` (the section rewrite and the rule's why),
   `CLAUDE.md`, `README.md`; `NOTES-FOR-APPFRAME.md` for the storage changes.
6. **Save that rebases** — `GitHubStorage.pull` and `push` rebase, for a repository that
   holds only plans.

Phase 2 — plan repository roots as library entries — is parked; see *Parked for later*.

Steps 1 to 3 are what stops the drift for an agent-driven team; step 4 is what makes it
usable from the window. By the skill's own yardstick (four tasks to a day) steps 1 to 3 are
about a day each and step 4 about two; the numbers are a shape, not a promise.

## Parked for later: collaboration beyond git

*Kept so the thinking is not lost. Nothing in this section is part of the first round;*
*it builds on the separation above and is picked up once a team has used it for a while.*

**Phase 2: the plan repository as a library root.** With the index in
place, a library entry can name a plan repository root instead of a project —
`{"root": "/home/b/plans"}` — expanded at load into the projects its index lists, and
re-expanded when the index changes on disk (a `git pull` that brought a colleague's new
project). Membership then travels with the repository: nobody re-runs `library add`, the
panel order is the committed order, and "the library" becomes "the plan repositories I
have cloned". It is additive — a bare project path keeps working — and it is a membership
refactor (`library_file`, `LibraryStore.load`/`attach`/`_adopt_library_file`, the Projects
panel's unavailable rows), which is why it is sequenced after the separation rather than
bundled with it.

### Git first, and what a backend would add

Everything above is collaboration *through git*: the plan repository is the shared
workspace, and a change reaches a colleague when one side pushes and the other pulls. What
git cannot give is *liveness* — a change seen as it is typed, presence, two people inside
one spec paragraph at once. A backend is what adds that. It sits on top of git-based
sharing rather than replacing it, and the separation is the prerequisite for both, because
a repository can only be synced aggressively when it holds nothing but plans.

The ladder, simplest first:

| Option | What it is | When a colleague's change is seen | Both edit the same entry | What has to run |
|---|---|---|---|---|
| Phase 1 only | Everyone clones the plan repository and runs one `library add` on it | After a Save on one side and a pull on the other | The conflict dialog that exists today, per entry | Nothing new |
| Phase 2 | A cloned plan repository *is* the library; new projects appear after a pull | The same, and nobody maintains a project list | The same | Nothing new |
| Auto-sync | The window pulls on a timer and pushes after every Save | Within a minute or two, adopted in place with caret and undo kept | The same, plus a rebase that stops and says so when git cannot merge | Nothing new |
| Sync backend | A small service that syncs the plan repository and pings open windows | Within seconds | The same | A server, or GitHub webhooks |
| Co-editing backend | A service holding live documents with CRDT text | As it is typed, with presence | Merged character by character, no dialog | A server, auth, an offline story, and a CLI that talks to it |

What each step costs and buys:

- **Phase 1 already lets several people work on one project.** The window takes a
  colleague's edits into the live model entry by entry after a pull
  (`adopt_outside_changes`), and a disagreement on the same entry goes to the conflict
  dialog. The one real gap is a Save refused because somebody pushed first, which
  rebase-before-push closes.
- **Phase 2 is only bookkeeping.** It removes the step where each person tells their
  library which projects exist; it changes nothing about how edits flow.
- **Auto-sync is the cheap route to live updates on the graph.** A timer and two git calls
  on a repository that holds only plans. Latency is a minute, not a second, and the history
  fills with small commits, which a plans-only repository can afford.
- **A backend is a different product decision.** Files in git are what make agents,
  offline work, plan history and the review of a plan through a pull request possible. A
  sync backend keeps all of that and adds speed. A co-editing backend gives up files as the
  source of truth, and the CLI would speak to a service instead of a directory. The text
  model already stores prose as positional edits (`TextEdit`), the shape live co-editing
  builds on, but it is not conflict-free by itself.

So the recommendation is Phase 1 with the index and `library add` over a plan repository,
plus rebase-before-push, and then a pause: Phase 2, auto-sync and either backend all build
on that without undoing it, and the choice between them is better made after a team has
used the separated setup for a few weeks.

## Open questions

1. **Colocation acceptance: shared or per person?** Proposed shared, in `project.dproj`,
   so lint and the banner agree across the team. A per-user dismissal would leave lint red
   for everyone who did not click.
2. **The word.** Settled: *plan repository*, in the document and the UI.
3. **Phase 2 now or after?** Settled: after. *Git first, and what a backend would add*
   says what it would and would not change.
4. **Move history?** Out of scope as proposed. If the plan's history matters, the wizard
   can name a manual `git filter-repo` recipe instead of pretending to carry it.
