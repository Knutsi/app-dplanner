# Repository roles and positions: a project's locations table

*Proposal, 2026-09-17. Status: **draft for discussion**. Written from a full read of the
code at `main` (1ace237); every file named below is on that commit. It builds on
`plan-and-code-repositories.md`, which split the plan repository from the code repository
and is implemented; this one generalises the code side.*

## The short version

A project today names **one** code repository and nothing else. Everything that reaches
outside the plan directory has grown its own way of saying *where*: the code repository is
`Project.repository` with a per-machine `checkout` in the library file; a spec kept in git
is a locator of its own (`{url, ref, path}`) inside `modules/spec.json`, checked out into a
private cache the person never sees; and documentation and tests have no place outside the
plan at all — the compiled document is a plan entry, and an agent compiling docs is told to
"write nothing in this checkout". Three vocabularies for one idea, and none of them can say
*two* code repositories, or *this folder of that repository*.

The proposal replaces the one string with a **table of locations** on the project, shared in
`project.dproj`. A location is a **role**, a **repository** and a **position** — a directory
inside it:

| role | repository | position |
|---|---|---|
| code | `acme/widget` | `.` |
| code — *UI* | `acme/widget-ui` | `.` |
| specs | `acme/specs` | `products/search/` |
| docs | `acme/widget` | `docs/search/` |
| tests | `acme/widget` | `tests/e2e/search/` |

The plan repository is not a row. It stays what it is — the git repository enclosing the
project directory, derived and never stored — and the table lives *in* it, so a plan
repository does carry the repositories its projects are about, which is what lets a clone
of the plan set everything else up. The roles are a **registry**: `code` is the domain's,
because the CLI must find a project from a code checkout without loading a module, and
`specs`, `docs` and `tests` are declared by the modules that act on them, in a Qt-free file
the composition root gathers — so a module that wants a kind of place a project can name
adds a role, and the dialog, the card, the CLI and the briefing all learn it without being
edited.

The recommendation, in one paragraph:

> A project gains `"locations"` in `project.dproj`: rows of `{id, role, repository, path,
> ref, label}`, absence encoding the default, `"repository"` migrating into the first
> `code` row. The library file's per-project `checkout` becomes a per-machine map from
> **repository** to checkout, because a checkout is a fact about a repository on this
> machine and not about a project — two projects planning one repository share it, and
> the three lookups that exist today to find "the checkout somebody else's project has"
> become one. Whether a location needs a checkout the person can see follows from its
> role: a location that is **worked in** (code; docs and tests, which are written) needs a
> real checkout and is asked about once per machine, as the code repository is today; a
> location that is only **read** (specs) is fetched on demand into a managed clone under
> `config_dir()`, which is what the git spec source already does and which moves down to
> `core/storage/` so every reading role shares it. A checkout shared with the code —
> `docs/` inside the code repository, the common case — costs nothing to ask about at all.
> `domain/repositories.py` stays the one derivation, now over rows, and every existing
> reader (Run Agent, GitHub refs, discovery, lint, the briefing, the card, the dialog)
> keeps its seam and reads the `code` row through it.

Two things I would add to what was asked, both argued below: **a step names the code
location it works in** when there is more than one, as an aspect with a default rather
than a project setting, because two code repositories in a project means some steps are in
one and some in the other; and **a location writes only through a working checkout** — a
managed clone is read-only by construction — because "write into a repository nobody has
checked out" is a commit and a push made on somebody's behalf, and that is not a question
this proposal should answer by accident.

## What the code holds today, and where it strains

The code was read for how it locates anything outside the plan directory. Three findings
shape the design.

**One string, one path, three questions.** `Project.repository` (`domain/model.py`) is the
code repository's remote; `LibraryEntry.checkout` (`domain/library_file.py`, format 2) is
where this machine has it; `find_repo_root(project dir)` is the plan. `domain/repositories.py`
derives `RepositoryFacts` over the three, and — this is the good news — every reader asks
it rather than the fields: Run Agent's `_workdir` (`facts.checkout if facts.repository else
facts.plan_root`), GitHub's `repository_for`, `cli/discovery.py`'s `_planning`, lint's
`repo.unset`/`repo.colocated`, the briefing's `_plan_whereabouts`, the Repositories card
and the Project dialog's `code_lines`/`plan_lines`. Generalising the storage is therefore
one derivation's change plus a handful of seams, not a hunt through the modules.

**The spec module already has positions, privately.** `modules/spec_git/source.py` stores
`{"url", "ref", "path"}` per source and clones into `config_dir()/spec-git/<digest of
url+ref+path>`: blobless, shallow, sparse to the folder, size-guarded before a blob exists,
versioned by blob oid. That *is* "a repository and a position in it, fetched on demand
without asking for a folder" — exactly the UX the reading roles want — and it is the
largest kind module because the clone door is in it. The folder kind and the git kind share
`domain/document_folder.py`'s walk, whose `subdirectory` argument is the only "position
inside a repository" concept in the tree today.

**Docs and tests never touch a repository.** `modules/docs/prompt.py` tells the compiling
agent to write nothing in the checkout: the deliverable is `dplanner compiled set`, a plan
entry. `modules/testing/` keeps bodies as strings in the step's aspect; files appear only at
the boundaries the person names (`--file`, export). `coverage`, `notes` and `feature` store
nothing outside the plan. So "docs and tests are written to their repository" is not a
storage change to those modules — it is a new act, and the location table is what gives it
a target.

Three smaller facts that the design leans on: the three surfaces that ask "does this machine
already have that repository?" — `ProjectsModule._checkout_of(remote)` behind the dialog's
`known_checkout`, `project_link.find_checkout` on the link page, and `find_clone` for plan
roots — all search other projects' rows for a matching remote, which is the tell that the
checkout was filed under the wrong key; `LibraryStore.repo_groups()` already gives Save
"one commit per dirty repository, scoped to its projects' directories", so a write into a
second repository has a save path waiting for it; and `Project.repository`'s edit is a
`SetFieldCommand`, which is the shape a whole-table edit can keep.

## The design

### A location is a role, a repository and a position

```python
@dataclass(frozen=True)
class Location:
    id: str          # minted per project: "l1", "l2" — stable while the row is edited
    role: str        # a role id from the registry: "code", "specs", "docs", "tests"
    repository: str  # the remote URL as git prints it; a resolved path for a remote-less one
    path: str = ""   # POSIX, relative, inside the repository; "" is the root
    ref: str = ""    # a branch or tag; "" is the repository's default branch
    label: str = ""  # tells two rows of one role apart: "UI", "backend"
```

`domain/locations.py`, Qt-free, beside `repositories.py`. The id is what a spec source, a
step's workplace and a CLI call name a row by, so editing the repository URL of a row does
not orphan what points at it — the same reason a step's folder name is frozen and its id is
its identity. `path` is validated as the project link's is (`PureWindowsPath`: no anchor, no
`..`), because a plan is shared and a colleague's row is input. `ref` is validated as the
git spec source validates its ref today.

The plan repository is deliberately not a row. It has no repository field that could
disagree with git, it needs no position (the project directory *is* the position), and the
rule "never store a plan root" (`persistence.md`) holds. What changes is the sentence
around it: *a project sits in its plan repository and names the locations it is about.*

### What is stored where

**`project.dproj`** gains one key and loses one:

```json
{
  "id": "…", "created": "…", "format": 3,
  "title": "Search rewrite",
  "colocation": "accepted",
  "locations": [
    {"id": "l1", "role": "code", "repository": "https://github.com/acme/widget"},
    {"id": "l2", "role": "code", "repository": "https://github.com/acme/widget-ui", "label": "UI"},
    {"id": "l3", "role": "specs", "repository": "https://github.com/acme/specs", "path": "products/search"},
    {"id": "l4", "role": "docs", "repository": "https://github.com/acme/widget", "path": "docs/search"},
    {"id": "l5", "role": "tests", "repository": "https://github.com/acme/widget", "path": "tests/e2e/search"}
  ]
}
```

- Absence encodes the default, as everywhere in `FORMAT.md`: no `path` is the root, no
  `ref` is the default branch, no `label` is the only row of its role, no `locations` is a
  project that plans no repository — the legacy shape, still read as colocated and still
  warned about.
- The array order is the order the card and the dialog show, and it is the **default
  order**: the first `code` row is the project's primary code, which is what every seam
  that used to read `Project.repository` now reads.
- `"repository"` is gone: format 3's migration (`domain/migrations.py`, one entry appended)
  moves it into `{"id": "l1", "role": "code", "repository": …}`. A format bump rather than
  an optional key, because the shape changed and an older build reading `locations` as
  absent would silently plan no repository; refusing a newer format by name is the honest
  behaviour `FormatHistory` already has.
- **A role this build does not know is loaded and written back untouched**, the edge-kind
  rule. A row's role is a module's word, and a colleague's build may have a module this one
  lacks; the card shows the row greyed as *unknown role* rather than losing it.
- `colocation` stays a project-level acceptance, now meaning "at least one code location is
  the plan's own repository, on purpose".

It is a model field on `Project`, not module data, for the reason `repository` was:
`cli/discovery.py` reads the code rows to resolve a project from a checkout, lint reads them
for colocation, and `cli/` may import `domain` but never a module. `Project.locations` is a
tuple; `_write_meta`, `_load_project`, `_meta_differs` and `_adopt_entry` round-trip it as
they do the four scalar fields; `project_document` exports it.

**`library.json`** goes to format 3, and the checkout moves from the project row to a map
keyed by repository:

```json
{
  "format": 3,
  "projects": [
    {"path": "/home/anna/plans/search"},
    {"path": "/home/anna/plans/billing"}
  ],
  "checkouts": {
    "github.com/acme/widget": "/home/anna/src/widget",
    "github.com/acme/widget-ui": "/home/anna/src/widget-ui"
  }
}
```

The key is `canonical_remote(repository)` — the spelling `find_checkout` already matches
on — so a row typed as `git@github.com:acme/widget.git` and one typed as the https URL
share a checkout. The migration from format 2 runs at read: a row carrying `checkout` files
it under the canonical remote of the checkout's `origin` (a remote-less repository under
its resolved path), and the row keeps only its path. `LibraryStore.set_checkout` takes a
repository rather than a project id, still writes straight into the file with the same
reasoning (a read verb's transaction is never refused over a per-machine fact), and
`checkout_changed` carries the repository. What this removes: `known_checkout`,
`find_checkout`, `_checkout_of(remote)` and the loop in `_planning` that consulted every
project's row — they are one dictionary lookup.

What it gives up: two projects planning one repository from two different clones. That was
never a designed feature, only a consequence of the column's position, and the case a
person might mean by it — working on two things in one repository at once — is what
worktrees are for. If somebody needs it, a per-project override is a row-level `checkout`
in the map's value, addable without a format change; it is not proposed now.

**Managed clones** land under `config_dir()/checkouts/<digest of canonical remote + ref +
path>`, one per (repository, ref, position) — the git spec source's cache, generalised and
moved: `core/storage/sparse.py` (working name) takes the blobless, shallow, sparse clone,
the size guard, the `GIT_NO_LAZY_FETCH` listing, the timeouts and the process-group kill
out of `modules/spec_git/source.py`, and the module keeps what is its own — the walk to
documents and the dialog. Keyed on all three for the reason the spec cache is: one
directory per position, so two positions in one repository never cross sparse patterns.
Disposable, as now: wipe it and the next read pays one tree fetch. `FORMAT.md` gets a row
for it in *Where a value goes* (per user, per machine, Qt-free, never travels).

### Roles are a registry, and modules add to it

```python
@dataclass(frozen=True)
class LocationRole:
    id: str                 # "specs"
    label: str              # "Specs"
    summary: str            # one line for the Add menu and `dplanner location roles`
    writes: bool            # docs, tests, code: true; specs: false
    several: bool = False   # may a project name more than one row of this role?
    default_path: str = ""  # offered when a row is added: "docs", "tests"
```

`domain/locations.py` declares `CODE = LocationRole("code", …, writes=True, several=True)`
and the domain knows no other. A module that wants a role declares `ROLE` in a Qt-free
`roles.py` in its package — a new name in `HEADLESS_FILES`, held to the `aspect.py`
standard — and the composition root gathers them in `default_location_roles()`, the
sibling of `default_module_formats()`: one list the CLI, lint, the dialog's Add menu and
the card all read. The spec module declares `specs`; the docs module `docs`; the testing
module `tests`. A module *acts* on rows of its own role by filtering `project.locations`
on its id — it never needs to know another module's role exists, and modules still never
import each other.

`writes` is the one property with consequences, and the next two sections are about them.

### Resolving a location to a place on this machine

One function, `place(location, checkouts, plan_root) -> Placement`, in
`domain/locations.py`, answers *where is this location here?* in a fixed order:

1. **The checkout this machine recorded for the repository**, from the library's map,
   joined with the position: `~/src/widget/docs/search`.
2. **The plan repository itself**, when the location's repository is the plan's remote
   (colocated: the older shape, or a docs folder kept beside the plans): `plan_root / path`.
3. **A managed clone**, for a role that does not write: fetched on demand, sparse to the
   position, read-only.
4. **Nowhere yet**: the verb that needs it is greyed with the reason in its words —
   *acme/widget-ui is not checked out on this machine — Project ▸ Settings…* — the exact
   sentence `_workdir_refusal` prints today.

```python
@dataclass(frozen=True)
class Placement:
    location: Location
    directory: Path | None   # the position on disk, or None while nowhere
    managed: bool            # a clone the application keeps, never the person's
```

`RepositoryFacts` keeps its plan half (`plan_root`, `plan_remote`, `colocation`) and grows
`placements: tuple[Placement, ...]`; `facts.code` is the primary code placement, or None,
and `repository`/`checkout` become properties over it so the seams below change one line
each. `colocated` becomes "any code location's remote is the plan's, or any code checkout
nests with the plan root". `repository_facts(project, project_dir, checkouts)` takes the
map instead of one path. The rule *never compare paths where `RepositoryFacts` already
answers* keeps its force with more to answer.

### Which locations need a checkout — the rule the UX rests on

The question the request raised is the right one: a person opening a plan should not be
asked to pick a folder for every repository it names. The answer falls out of `writes`:

- **A worked-in location needs a working checkout the person can see.** Code, because an
  agent opens a shell there and commits; docs and tests, because a document or a test
  written there is a change somebody will commit and push, and that must happen in a
  checkout they own, on a branch they chose, through the Save they already understand. The
  checkout is asked for **once per repository per machine** — not per project, not per
  row — and a row whose repository is already checked out (docs at `docs/search` inside
  the code that is already at `~/src/widget`) asks for nothing.
- **A read-only location never asks.** A specs row is fetched into a managed clone the
  first time a Specs tab looks, exactly as the git spec source is today, and the card says
  *fetched on demand · 2 hours ago* in the line where a checkout would show.
- **A managed clone is never written.** The application does not commit and push on
  somebody's behalf from a directory they cannot find. A docs or tests row on a repository
  nobody has checked out reads as *not checked out here* and greys the writing verbs, the
  same standing Run Agent has today for a missing code checkout.

The consequence for a person opening somebody else's plan: they are asked about the
repositories they will **work in**, which is the code and — only when it is a repository
of its own — the docs or tests one, offered as a clone into their repositories folder or a
checkout they already have; everything read-only is silent. That is the shape the request
described, arrived at by a rule rather than by a list of exceptions.

### The seams, one by one

**Run Agent** (`modules/step_agent_instruction/module.py`, `_workdir`): the workplace is a
code placement's directory, else the plan root for the legacy shape, unchanged in
behaviour for a project with one code row. With two, **a step names its code location** —
a `workplace` field on the existing agent-instruction aspect, holding a location id, absent
meaning the primary — because which repository a step's change lands in is a fact about
the step, exactly as its worktree choice is (`agents.md`). The Run Agent dialog shows the
choice only when the project has more than one code row; a step whose named row is gone
falls back to the primary and lint says so (`location.workplace_missing`). A run across two
repositories at once is out of scope, and said to be.

**GitHub refs** (`repository_for`): the step's workplace repository, else the plan's
origin, as now; the `-R owner/repo` door in `github/gh.py` is untouched.

**Discovery** (`cli/discovery.py`, `_planning`): a `dplanner` call from a checkout whose
`origin` matches **any** code row of a project finds that project, and records the checkout
under the repository key — the same rule, one loop wider, and simpler for losing the
per-project checkout comparison.

**The briefing** (`_plan_whereabouts` and a new `_locations` paragraph): the agent is told
the table in words — *Specs come from acme/specs at `products/search/` (read-only, fetched
by the window). Documentation for this project goes in `docs/search/` of this checkout;
tests in `tests/e2e/search/`.* — with `dplanner location list` as the verb that prints it
again. A location the machine lacks is named as lacking, so the agent never guesses a
path.

**Specs** (`modules/spec_git/`): a git spec source's locator becomes `{"location": "l3"}`
plus an optional `subpath`, and `valid_locator` resolves it through the table, refusing a
row that is not a `specs` role. Adding a specs row in the dialog adds the source; *Add
Spec ▸ Git Repository…* becomes *From a Specs Location…*, listing the project's `specs`
rows with *Add a location…* as the last entry — the presets-first rule. The folder and
Confluence kinds are unchanged: a folder on this computer and a wiki are not repositories,
and forcing them into the table would be the special case beside a general one. The
module's docstring rule *a git spec source is a cache, never the plan* becomes the
sparse-clone door's rule, one level down.

**Docs and tests**: the target exists once the table does, and the *act* is a separate
step. The proposal for it, argued but not scheduled: *Compile Docs* offers **Write to
`docs/search/`** beside the plan entry, writing the compiled document as files into the
docs placement's directory — the person's checkout — where Save records it as one more
dirty repository (`repo_groups()` gains the placement's root, scoped to its position, so
the commit covers exactly that folder). `dplanner test export` gains `--to-location`.
Neither module stores a path: they ask the table. The open question is not where but
*when* and *on which branch* — see *Open questions*.

**Save** (`modules/sync/`): unchanged until docs and tests write, and then one more
repository group; the exit dialog's "one commit per dirty repository" already has the words
for it.

**Lint** (`cli/lint.py`, `modules/problems/findings.py`): `repo.unset` becomes *no code
location*; `repo.colocated` reads the placements; two new findings — `location.unknown_role`
and `location.duplicate` (two rows of one role on a role that says `several=False`).

**The project link** (`domain/project_link.py`): unchanged in format. It carries the plan
remote and the path; the table is read from the plan once it is cloned, and the wizard's
page after the clone offers the worked-in repositories. The link's `code` field stays as
the courtesy it is — what the page can say before cloning — filled from the primary code
row.

**Move Plan** (`domain/relocate.py`): rewrites nothing in the table, because the table
names repositories and a move changes only which repository the plan is in. The one check
it keeps is the one it has: a move *into* a code location's repository is refused.

## The UX

### What the person thinks, and what the surfaces ask

The narrative in the request is the right test: *I'm going to open a plan repository.*
Everything below is measured against it. The person names repositories in exactly one
place, the project's **Locations** table; a machine is asked about a checkout only for a
repository it will work in, once; and nothing read-only ever asks.

### New Project

The Project dialog's create mode keeps its first two blocks — the plan repository's
`RepoPicker` and the folder — and replaces the *Code repository* combo and the *Checkout*
field with the **Locations table**, seeded with one `code` row. It is the `Table` primitive
from `DESIGN.md`'s *Primitives* (the roster shape that sets values in the row), four
columns: a role glyph and label, the repository as a person knows it (`acme/widget`), the
position, and *on this machine* — the checkout path eliding from the left, *fetched on
demand* for a read-only row, or *not checked out* greyed with `#RepoLineMissing`. Each row
carries the `⋯` the code column has today (`RepoAction`, built when it opens, greyed with
its reason): *Set Repository…*, *Pick from GitHub…*, *Choose Position…*, *Choose
Checkout…*, *Clone into Repositories Folder*, *Open on GitHub*, *Remove*. Above the table,
**Add ▸** renders the role registry: *Code Repository*, *Specs*, *Documentation*, *Tests*,
each with the module's summary as its tooltip — a module contributes a role and the entry
appears.

Adding a row asks the two questions a row is, in a fit dialog: *which repository*, a picker
whose first entry is **the same repository as the code** (docs and tests live with the code
more often than not, so the default is the answer), then the project's other repositories,
then *Pick from GitHub…* and a typed URL; and *which folder*, a field pre-filled from the
role's `default_path` with a browse button that lists the repository's tree — over the
checkout when this machine has one, otherwise through the same remote listing the git spec
dialog probes with today (`spec_git/connect.py`), on a `TaskRunner`, with the size guard
beside the folder for a read-only role. The primary is refused in words while either is
missing. Nothing about a checkout is asked here: a repository already checked out needs
none, a read-only role needs none, and a worked-in repository this machine lacks shows
*not checked out* in the table with *Clone…* in its `⋯`, which is a decision the person can
make now or after *Create*.

### Opening a plan somebody shares

The Open Project wizard's link and browse pages end where they do today, at one
`Joined(directory, …)` — and gain one page after the clone: **Repositories**. It lists the
project's worked-in repositories that this machine lacks, one row each, with three answers
per row as radio words: *Clone into ~/Repositories*, *Use a checkout I have…*, *Later*.
Read-only rows are not listed; a sentence under the list says *Specs are fetched when a
Specs tab opens*. *Later* is always allowed — the wizard never refuses to open a plan over
a missing checkout, because the plan is readable without any of them, and the card says
what is missing afterwards. Clones run on the page, through `TaskRunner`, as the link page's
do now; the terminal's `dplanner project open` keeps refusing to clone and prints one
`git clone` line per missing repository.

A person who already has `~/src/widget` checked out is asked nothing on the second
project that plans it, because the checkout is filed under the repository: this is the
case that makes the map worth the format change.

### The Repositories card and the Settings dialog

The Dashboard's Repositories card (`modules/projects/card.py`) becomes the same table,
read-only, under the plan line it keeps at the top: one row per location, the *on this
machine* column saying the placement's state, the colocation remark under it when
`facts.warns`, and the two buttons it has (*Settings…*, *Move Plan…* / *Set up a plan
repository…*). The Settings dialog's plan column stays; its code column becomes the table
with its `⋯` menus live and undoable — every edit is a `SetLocationsCommand` on the undo
stack, so the dialog keeps *Close alone*. A **checkout** chosen here is written straight
into the library file as today, and `checkout_changed` refreshes the context so Run Agent
un-greys. `repos.code_lines`/`plan_lines` become `location_lines(placement)`, still the one
wording both surfaces read.

### The CLI and the agent

One verb group, `dplanner location`, Qt-free in `modules/projects/cli.py`:

```
dplanner location list [--json]                       every row, with where it is here
dplanner location roles                               the registry, with each role's summary
dplanner location add --role docs --repository URL [--path docs/search] [--ref main] [--label UI]
dplanner location set l4 [--repository …] [--path …] [--ref …] [--label …]
dplanner location remove l4
dplanner location checkout l1 PATH | --forget         this machine's checkout for the row's repository
```

`project create` gains `--code URL` (repeatable) in place of `--repository`, `project set
--repository` is retired in favour of `location set`, `project show` prints the table, and
`agent prompt --json` carries the placements. Every mutating verb builds the same
`SetLocationsCommand` the dialog pushes — two surfaces, one vocabulary. A row is addressed
by id or by `role[:label]` (`code:UI`), since an agent reading `location list` should not
have to copy an id.

The generated skill gains one paragraph: where specs, docs and tests are, and that
`location list` prints it. The briefing's paragraph is above.

## Alternatives weighed

**Keep one code repository and let each module store its own place.** The status quo
extended: the spec locator stays private, docs gets a `docs_path` setting, tests another.
Three vocabularies become four, no surface can show *all the places this project is
about*, and a colleague's clone has three things to set up in three dialogs. Rejected for
the reason the aspect registry exists: the interesting logic (naming a repository, a
position, a checkout here) is the same for every role, and writing it once in the domain
is what makes a new role a declaration.

**A `locations` module owning the table as module data.** Attractive for keeping the domain
small, but `cli/discovery.py` must read code rows to find a project, lint must read them
for colocation, and `cli/` never imports a module. The table is a fact about the project
in the same sense `repository` was, so it goes where `repository` went.

**Keep the checkout per project.** Cheaper to migrate, but it leaves the three
"does this machine already have it?" lookups in place and adds a fourth for docs rows on
the code repository. The map is the smaller design once there is more than one row per
repository, which the table guarantees.

**Store checkouts in the plan.** The retired `project_repo` mistake, and the reason the
library file exists; not reconsidered.

**Let a managed clone be written and pushed by Save.** It would make docs and tests work
on a machine that never chose a folder, which is the seductive version of the request.
Rejected: a push from a directory the person cannot find, to a branch the application
picked, is the "main drifting" story again with a different repository. Writing goes
through a checkout the person owns; the door to reconsider is in *Open questions*.

**One role per repository, position in the module.** Simpler table, but the request is
precisely that a position is part of what a project names — `docs/search/` inside the
code repository is the location, not `acme/widget` with a module-side path — and it is
what lets the briefing tell an agent where to write without the agent reading a setting.

## Migration

**Project format 3** — `domain/migrations.py`, one entry appended: `repository` present
becomes `locations: [{"id": "l1", "role": "code", "repository": <it>}]` and the key is
dropped; absent stays absent. `colocation` is untouched. Each `project.dproj` migrates on
its own, as the two-axis rule requires, so a library mixing formats is fine.

**Library format 3** — `domain/library_file.py`: rows with `checkout` fold into
`checkouts` under `canonical_remote(origin_url(checkout))` — read at migration, once, in
the Qt-free reader, which may import `core/storage/git.py` — or under the resolved path
for a remote-less repository; a checkout whose directory is gone is dropped with the row
kept, the tolerance the reader already has. Written back as format 3 on the next flush.

**Spec index format 6** — `modules/spec/aspect.py`: a git source's `{url, ref, path}` is
matched against the project's `specs` rows by canonical remote, ref and path, and rewritten
as `{"location": id}`. Where no row matches, the locator is **kept as it is**: a module-data
migration sees only its own file and may not add a row to `project.dproj`, so
`valid_locator` goes on accepting the older shape, the Specs tab shows the source with
*Add as a location* in its `⋯`, and lint's `spec.source.unplaced` names it. Its cache
directory is unchanged in key, so no clone is repeated either way.

**Aspects and links** need nothing: the `.dlink` format is unchanged, and no step aspect
changes shape (the `workplace` field is new and optional).

## Rollout

1. **Domain and CLI.** `Location`, `LocationRole`, `Placement`, `place`; `Project.locations`;
   format 3 and its migration; the library map and its migration; `RepositoryFacts` over
   placements with `code`/`repository`/`checkout` as properties; `SetLocationsCommand`;
   `dplanner location …`; discovery over all code rows; lint. Every existing reader still
   passes its tests through the properties. `tests/domain/test_locations.py`,
   `test_library_file.py`, `test_repositories.py`, `tests/cli/test_location_verbs.py`.
2. **The clone door moves down.** `core/storage/sparse.py` out of `spec_git/source.py`,
   the module reading it; `NOTES-FOR-APPFRAME.md` records the addition. No behaviour change
   — the point is a test that the digest and the guard survive the move.
3. **The window.** The Locations table in both dialog modes and on the card; the role
   registry gathered in the root; the Add menu; the wizard's Repositories page; the briefing
   paragraph; `docs/screenshots/s16-dialogs/` re-rendered.
4. **Specs on the table.** The `specs` role in `modules/spec/roles.py`, the locator over a
   row, the Add Spec entry over the rows, spec index format 6.
5. **Docs and tests write.** Their roles, *Write to location* in Compile Docs, `test export
   --to-location`, Save's extra group — after the open questions below are settled.

Phases 1–3 are one feature; 4 and 5 are each a change of their own on top of it. Nothing in
1–3 changes how a project with one code repository behaves.

## What it removes

The check `CLAUDE.md` asks for at the end, taken at the start. `Project.repository` and its
`SetFieldCommand` entry; `LibraryEntry.checkout`; `known_checkout` on the dialog,
`ProjectsModule._checkout_of`, `project_link.find_checkout`, and the three-way comparison
in `discovery._planning`; `_known_repositories` (the table lists them); the code column's
special-cased verbs in the dialog (`_code_url`, `_set_repository`, `_record_checkout`
become the row's); `spec_git`'s private cache root and clone door; `project set
--repository/--checkout/--forget-checkout`. What it adds is one dataclass, one registry,
one derivation and one table widget, each used from four or more places.

## Open questions

1. **When docs and tests are written, and where they go on the branch.** Writing into the
   person's checkout on whatever branch is checked out is the honest first answer, and Save
   records it. Whether Compile Docs should instead write in the step's agent worktree, so
   the documentation rides the step's PR, is the better long-term answer and depends on
   phase 5's shape. The table is the same either way.
2. **A step in two code repositories.** The `workplace` aspect names one. A change that
   spans `widget` and `widget-ui` is two steps in this design, linked by `requires`, and
   the briefing can say so. Worth confirming against how the field uses two repositories.
3. **A role's `several`.** Code, yes. Specs — a product with two spec repositories is
   plausible, so yes. Docs and tests — one each per project reads as the sane default,
   and the lint says so; a module can flip its own flag.
4. **`ref` on a worked-in row.** A code row with a `ref` would mean "work on this branch",
   which Run Agent does not honour today (it branches from what is checked out). Proposed:
   `ref` is read-only advice on worked-in rows until a step's worktree can branch from it,
   and a hard fact on read-only rows, where it already is.
5. **The wizard's *Later*.** Always allowed above; whether the card should nag (a
   `location.unplaced` finding in Problems) or stay quiet until a verb needs the checkout.
   Proposed: the verb's greyed reason and the card's line, no finding — a checkout is this
   machine's business, and Problems is the plan's.
