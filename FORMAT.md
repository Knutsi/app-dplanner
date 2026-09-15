# Data formats and how they change

A project is a folder of plain files that people share, keep in version control, and open
with builds of the application that are not all the same age — and, in DPlanner, that a
coding agent writes to through the CLI while somebody has a window open on it. That makes
the on-disk format a public contract, and this document is the contract's rules.

There are **two independent version axes**, and keeping them independent is the whole idea:

| Axis | Covers | Version lives in | Owned by |
|---|---|---|---|
| Project format | the folder layout and the keys in `project.dproj` / `step.json` | `project.dproj`'s `"format"` | `domain/migrations.py` |
| Module data | each `modules/<module_id>.json`, opaque to the store | the file itself, `"format"` (absent = 1) | the module that writes it |

A module changing its own JSON never bumps the project format, and `domain/` never learns a
module's schema. **Whoever owns a piece of data owns its history.** Each project directory
carries its own format stamp and migrates on its own — one library can hold projects
written by different builds, and each gets exactly the migrations it needs.

## Where a value goes

Four places, and the choice is not stylistic:

| Where | What | Mechanism | Travels with the project? |
|---|---|---|---|
| The project directory | content, and anything a collaborator should see | your model, or `module_data` / `module_text` / a module file area | yes — it is in the files, and in the commits |
| Per user, per machine (Qt-free) | what the CLI must also read: the project library | `core/config_dir.py` + `domain/library_file.py` | no — it is a list of *this machine's* paths |
| Per user, per machine (Qt-free) | what happened and how long it took: the telemetry journal, and a native crash's stack | `core/telemetry.py` under `config_dir()/telemetry/` — see *The telemetry journal* | no — it is this machine's diagnostics |
| Per user, per machine (Qt-free) | who is working on a plan right now: an agent's *at work* claim | `domain/at_work.py` under `config_dir()/at-work/` — see *An agent's at-work claim* | no — it is a process that is running here, now |

| Per user, per machine (GUI only) | preferences: panel layout, model choices, the agent launch profiles | `framework/user_config.py`'s `get_global` (QSettings) | no |
| Per user, per machine, per library | where the user left off: open index folders, open tabs | `framework/user_config.py`'s `get_scoped`, under `library_scope(path)` | no |
| The OS keychain | credentials, API keys — the LLM keys, a Confluence token per site (`spec_confluence.token:<host>`) | `core/secrets.py` | no, and never on disk |

If you are unsure, ask who the value belongs to. A colleague opening the project should
see its conventions and none of your preferences.

The last two rows differ over *whose truth it is*. "Reopen my tabs" is the person's and
follows them into every library; "these tabs were open" is one library's, and restoring it
into another would be nonsense. Anything in the scoped row is written **keyed by node id**,
so a value naming something that has since been deleted restores nothing — which is why
neither needs a version stamp or a migration.

**A project answers two repository questions, and they go to different rows.** *Where does
the plan live?* — the **plan repository** — is never stored: it is the git repository
enclosing the project directory, `find_repo_root`'s answer. *Which code does it plan?* —
the **code repository** — is `"repository"` in `project.dproj`, the remote URL as git
prints it (or, for a repository with no remote, its resolved path), shared with everyone
who opens the plan. *Where is that code on this machine?* is the library file's `checkout`
column, per user, per machine, below. `ARCHITECTURE.md`'s *Two repositories, two
questions* has the reasoning; `domain/repositories.py` is the one derivation over the three.

## The library file

`library.json` records **membership**: which project directories this user is planning —
and, per project, where this machine has the code that project plans.

```json
{
  "format": 2,
  "projects": [
    {"path": "/home/anna/plans/widget", "checkout": "/home/anna/code/widget"},
    {"path": "/home/anna/code/gadget/planning"}
  ]
}
```

- The default lives at `$XDG_CONFIG_HOME/dplanner/library.json` (platform equivalents on
  Windows/macOS — see `core/config_dir.py`); `--library PATH` or `$DPLANNER_LIBRARY` names
  another. It is per user and per machine, and never belongs in version control.
- Paths are absolute (`~` is allowed) and the array order is the order the Projects panel
  shows.
- `checkout` is optional: where this machine has the project's code repository. It is
  written by the Project dialog, by `dplanner project set --checkout`, and by the first
  `dplanner` call that runs inside a checkout whose `origin` is the project's code
  repository — **straight into the file** (`LibraryStore.set_checkout`, read-modify-write
  and re-stamp), never through a dirty mark, because a read verb's transaction must never
  be refused over a per-machine fact. A format-1 file reads as format 2 with no checkouts.
- Reading is tolerant: a malformed row is skipped, and an entry that cannot be opened — the
  folder is gone, holds no `project.dproj`, or is not inside a git repository — becomes an
  *unavailable* row in the panel rather than a refusal, and keeps its place in the file
  across rewrites.

## The telemetry journal

`config_dir()/telemetry/journal.jsonl` is what both surfaces write and what `dplanner
telemetry show` reads: one JSON object per line, appended and never rewritten, rotated to
`journal.1.jsonl` past 5 MB by whichever process finds it that size. A line is a *span* —
something that happened and how long it took:

```json
{"id": 41, "t": 1788500000.12, "kind": "action", "name": "steps.link", "ms": 38.4,
 "ok": true, "pid": 4242, "thread": "MainThread", "surface": "window", "parent": null,
 "detail": {}}
```

`kind` is one of `action`, `command`, `slot`, `task`, `autosave`, `poll`, `session`,
`stall`, `cli`, `failure`; `parent` is the id of the span this one ran inside, on the same
thread and in the same process; `t` is the wall clock at the start, which is what lines a
CLI run up against the window's rows; a span that is not `ok` carries an `error` object
(`type`, `message`, `traceback`). Only what is worth reading back reaches the file: every
`failure`, `stall`, `session` and `cli` span, and anything that took `SLOW_MS` (20 ms) or
longer; the rest lives in the window's ring buffer. `crash.log` beside it is
`faulthandler`'s: the Python stack at a native crash, appended to. Neither is versioned
or migrated — a reader tolerates unknown keys and a torn last line, and `dplanner
telemetry clear` is the only maintenance.

## An agent's at-work claim

`config_dir()/at-work/<project>-<step or "plan">.json` is what `dplanner agent-work …`
writes and the window reads: one file per claim, so several agents on one plan each write
only their own and no two can lose an update to each other.

```json
{
  "format": 1,
  "project": "8f2c…", "step": "",
  "doing": "Cutting the graph from the payments spec",
  "done": 8, "of": 20,
  "started": "2026-09-14T09:12:00+00:00",
  "seen": "2026-09-14T09:41:07+00:00"
}
```

`seen` is the last sign of life, renewed by **every** `dplanner` run against that project
from inside an agent's shell — the agent needs no heartbeat of its own. Nothing derived is
stored: how long ago that was, whether it still reads as *at work*, and how far along the
agent says it is are all computed on every read (`domain/at_work.py`).

**It is never in the project directory**, and that is the whole reason it is a row of its
own above: it changes every few seconds and means "a process is running on this machine,
now". In a plan it would be committed into everybody's history, arrive at every
collaborator as an outside change, and have the window adopting an edit every two seconds.
The file name is only a name — a reader takes the project and step from inside the record —
and there is no migration: a file this build cannot read is skipped, and a claim nobody has
renewed for a day is deleted by the next writer.

## The project format


A project is one directory **inside a git repository**, one directory per node below it,
nested exactly like the model:

```
<plan repository>/
├── .dplanner                  the index: one project directory per line, relative
└── widget/                    the project directory — any folder in the repo
    ├── project.dproj          id, title, summary, repository, colocation, created, format, children
    ├── modules/               module data belonging to the project itself
    │   ├── notes.json         the notes the project made along the way
    │   └── notes/assets/      files those notes link
    └── steps/
        └── read-the-spec/     folder name, frozen at creation
            ├── step.json      id, title, edges
            └── modules/
                ├── estimation.json         structured data
                ├── step_status.json        {"status": "done"} — absent means pending
                ├── testing.json            the tests this step keeps, one record each
                ├── step_description.md     prose
                └── step_description/       files this module owns
                    └── assets/diagram.png
```

Four conventions, and each one is a lesson about diffs:

- **Ordering lives in the parent's `children` list**, never in `01-`/`02-` filename prefixes.
  Reordering two projects is then a one-line JSON diff instead of a mass rename.
- **A folder name is frozen at creation** and never follows a retitle. Identity is the id;
  the folder name is presentation. Renaming a folder churns history for no benefit.
- **A step carries a number, and the project keeps the last one dealt.** `"number": 7` in
  `step.json`, `"last_number": 12` in `project.dproj` — one sequence per project, dealt
  where a step joins it and never reused (a deleted step's branch may live on). The
  letter a person sees in front of it (`S7`, `F7`, `M7`) is derived from the step's kind
  and never written; `ARCHITECTURE.md`'s *A step has a number* has the reasoning.
- **Absence encodes the default.** A step with no links writes no `edges` key, and an empty
  document is deleted rather than written blank — so a diff shows exactly the nodes whose
  plan actually changed.
- **Container directories say what a level is.** `steps/` costs one directory and buys a
  reader the shape of the model at a glance. It also means children never sit beside
  `modules/`, so there are no reserved folder names to trip over.

### Bytes on disk

Every file in a project directory is **UTF-8, LF, and ends with a newline**, on every
platform that writes one. JSON goes out with a two-space indent and sorted keys
(`domain/store.py`); prose goes out as the person typed it. `core/fsio.py`'s `write_atomic`
is the one door all of it passes through, and it states each of these explicitly rather than
taking the platform's default — because the platform's defaults are not the same platform's
defaults. Python translates `\n` to `\r\n` on Windows and decodes text as the console code
page, so a plan saved on a laptop and the same plan saved on a Windows box came back as a
whole-file diff against each other with nothing changed. A format whose whole purpose is to
be shared and merged cannot have one platform quietly rewriting every line of it.

This repository's own tree follows the same rule and pins it with a `.gitattributes`, so a
Windows checkout of DPlanner cannot hand the suite CRLF copies of the files it compares byte
for byte. A *user's* plan repository gets no such file: `write_atomic` writing LF is already
enough there (git's `autocrlf` leaves LF alone on the way in), and writing into somebody
else's `.gitattributes` is a bigger intrusion than this needs.

**Two keys on the project say where it stands with its code.** `"repository"` is the code
repository the plan is about, as git names its remote (a resolved path for a remote-less
one); absent, the project reads as planning the repository it sits in — the older shape,
warned about by lint, the briefing and the window until it is moved or accepted.
`"colocation": "accepted"` is that acceptance: the people on the project decided the plan
stays inside its code on purpose, and every warning stands down. Both are set by the
Project dialog and `dplanner project set`; `project move` writes the first and drops the
second as it goes.

**Edges are keyed by kind**: `"edges": {"requires": ["<step id>", …]}`. One line per edge
rather than an object per edge, and the direction cannot be read the wrong way round —
`requires` is what *this* step waits on. The kind vocabulary is the domain's
(`domain/model.py`), because a kind only some builds understood would make a shared project
mean different things to different people. **A kind this build does not know is loaded and
written back untouched**, so a colleague's newer link survives an older build opening the
file.

### The `.dplanner-worktrees` directory

Run Agent keeps a step's worktree at `<repository>/.dplanner-worktrees/<run name>` on the
branch `agent/<run name>`, where the run name is the step's key, its ticket key and its
title slug (`f7-PROJ-12-build-the-modal`). Local and never versioned: the wrapper adds
`/.dplanner-worktrees/` to `.git/info/exclude`, and the store's stale-write check never
looks there. It is a sibling of the `.dplanner` pointer below rather than a directory
under it, because the pointer is a *file* — which is exactly where the earlier
`.dplanner/worktrees/` path failed for every project kept in a subfolder.

### The `.dplanner` index

A **plan repository** is a git repository whose root carries a `.dplanner` file: one
project directory per line, relative to the file (an absolute path also works), in the
order they were added. A one-line file is the pointer it grew from — a plan kept in a
subdirectory beside its code is still reached the same way. The CLI finds the current
project by walking up from the working directory for `project.dproj`, and at each level
for this index; a `project.dproj` in the same directory wins over an index beside it. A
line that leads nowhere is skipped while another resolves — a project somebody deleted by
hand must not hide its neighbours — and an index none of whose lines leads anywhere is an
error rather than a fallthrough: the walk never quietly acts on some other project above
one the user explicitly named. The file is meant to be committed, so everyone who clones
the repository — people and agents alike — gets the discovery, and *Open Project…* and
`dplanner library browse` get their list, for free. A repository with no index is scanned
three levels deep instead, skipping `.git`, `steps/`, `modules/` and the worktrees.

Creating a project inside a git checkout appends its line to the index at the repository
root (`seed_project`, `add_to_index`); moving one out drops the line and adds it where the
plan arrives; deleting one drops it. An existing line is never rewritten — a hand-written
one is the user's word — and a project that *is* the repository root needs none, so none
is written.

### The project link (`.dlink`)

A **project link** is the one file here that is *not* part of a project: it describes one,
so that somebody who has never seen the plan can set it up. Three facts do it — which plan
repository, where in it, and which code — and everything else it carries is only so that
the receiving surface can say what it is about to do before it clones anything.

```json
{
  "dplanner": "project-link",
  "format": 1,
  "id": "9b1c…",
  "title": "Search rewrite",
  "summary": "Replace the index",
  "plan": { "remote": "https://github.com/acme/plans", "path": "search-rewrite" },
  "code": { "remote": "https://github.com/acme/widget" }
}
```

Same bytes rules as everything else (UTF-8, LF, two-space indent, sorted keys, a trailing
newline) and the same *absence encodes the default* rule: an empty field writes no key, and
`"path": "."` is a plan repository that is one project. `"format"` is the link's own axis,
a third beside the project format and each module's — it belongs to
`domain/project_link.py` and to nothing else, and a **newer** one is refused by name rather
than read half-way, because the machine reading it is by definition not the machine that
wrote it.

The same fields travel as one line, which is what a chat window takes and what the QR code
in *Share Project…* encodes:

```
dplanner://project?plan=https://github.com/acme/plans&path=search-rewrite&code=https://github.com/acme/widget&id=9b1c…&title=Search%20rewrite&format=1
```

**Spelt out rather than packed.** A blob would be shorter, and a person asked to open
somebody else's link would have no way to see where it points before opening it. The two
encodings are one dataclass with one reader each, so neither can grow a field the other
lacks; `dplanner project share` and `project open` are the terminal's half, and the
document a `.dlink` holds is exactly what `--json` prints. **It carries no credentials and
grants no access** — it names public URLs and a path, and whoever opens it still needs
their own access to both repositories.

### The `reports` directory

A plan repository may carry its projects' reports beside the plans — derived, never read
back, and outside every project's `PLAN_ENTRIES`, so the store's stale-write check never
sees them:

```
<repository root>/reports/
├── index.html            the site: every project's headline, one card each
├── <slug>/index.html     one project's full report — a single self-contained HTML file
└── <slug>/summary.js     that project's headline figures: window.dplannerProjects.push({…})
```

`<slug>` is the project directory's path relative to the repository root with separators
folded (`plans/search` → `plans-search`); the repository directory's own name when the
project *is* the root. Save writes the directory for each dirty repository and records it
in the plan's commit (the window's Settings ▸ Reports switch, on by default);
`dplanner report site` writes it from a terminal and never commits. The index is a
function of the set of `*/summary.js` present, so its bytes change only when a project
joins or leaves — the rule that keeps two writers from conflicting over a generated page.
The directory name is a constant, not a setting. Nothing in it is versioned or migrated:
every Save rewrites it whole from the plan. `ARCHITECTURE.md`'s *A report is a
publication, not a record* has the reasoning.

### Changing it

The chain lives in `domain/migrations.py` and the engine in `core/formats.py`. DPlanner is
at format 2; the one entry so far dealt every step of a version-1 project its number, in
`children` order, and set the project's `last_number` past the last.

1. **Append a `Migration` to the end of the tuple.** `current_version` is derived from the
   chain, so that edit *is* the version bump.
2. **Never edit an existing migration.** A folder written by version 1 still walks the
   entire chain, and each step's output is the next step's input. Editing step 2 silently
   changes what step 3 receives from every old project on every machine — including ones
   you will never see. If step 2 was wrong, fix it by appending step 4.
3. **Two hooks, for two different jobs.** `node` runs per node as it loads, with the raw
   dict it came from, so it can reach keys the model no longer has fields for. `whole` runs
   once over each finished *project* — the aggregate a format version covers.
4. **Migrate once, at open, then save the whole project.** Never leave a half-migrated
   folder for a later partial autosave to finish.

A project written by a *newer* build is never partly read and never written to — it shows
as an unavailable row while the rest of the library opens normally.
`UnsupportedFormatError.is_newer` distinguishes that from damage, because it is not a
problem with the data — the usual cause is a colleague's push or a branch switch.

## What a module may store

Three siblings under a node's `modules/`, and one naming rule covers all of them:
**`modules/<id>.json` is a module's data, `modules/<id>.md` is its prose, and
`modules/<id>/` is its files.** Every one is round-tripped by name, so **data belonging to a
module this build does not have survives untouched**.

| | For | Reached through | Undoable? |
|---|---|---|---|
| `modules/<id>.json` | structured facts | `node.module_data["<id>"]` | yes — `SetModuleDataCommand` |
| `modules/<id>.md` | one document of prose | `node.module_text["<id>"]` | yes — `EditTextCommand`, positional, coalescing |
| `modules/<id>/` | anything else: images, attachments | `store.files(node_id, "<id>")` | no |

Prose is model state rather than a JSON value on purpose: it diffs line by line, and it gets
the text stack — positional splicing, a staleness check, undo coalescing per burst, and
origin-based echo suppression — which a whole-value rewrite per keystroke would not.

Files are not model state, and that is also on purpose: they are opaque bytes nobody merges.
An asset add is therefore not undoable, which is the honest trade — undoing a paste would
leave the markdown pointing at a file that had gone, and an orphaned blob is recoverable
where a dangling link is not.

To version the JSON, declare a format beside the module's persistence code and expose it as
`data_format`:

```python
DATA_FORMAT = ModuleDataFormat(MODULE_ID, version, migrations)
# invariant, checked in __post_init__: len(migrations) == version - 1
```

Two behaviours follow, and both matter once a project is shared:

- **Data newer than the module declares is left untouched and logged.** An older build keeps
  the project readable and never overwrites a newer build's data — that feature simply
  looks empty until the application is updated.
- **Writing nothing leaves nothing behind.** `stamped()` returns `{}` when the format stamp
  would be the only key, an empty entry removes the file, an emptied file area is removed
  with its directories, and `modules/` goes when it empties.

**A module's namespace may span node kinds.** `estimation` writes `{"days": 3.0}` beside a
step and `{"start": "2026-09-01"}` beside the project those steps belong to — one module id,
one `ModuleDataFormat`, two shapes. `testing` is the third instance and the reason to
mention it twice: a step's tests beside the step, and the project's **test runs** beside the
project — `{"runs": [{"id": "R100", "label": "…", "opened": …, "tests": [ids], "results":
{"T100": {"status": "failed"}}}]}`. A run stores the ids it was opened over, so a closed run
cannot change meaning when the graph does, and a **missing result reads as pending** — the
absence rule again, so a run over two hundred tests writes two hundred ids and no statuses.
`project_editor` is another instance: a position
beside each step — `{"x": 40.0, "y": 160.0}`, plus `"w"` and `"h"` only for a card somebody
resized — and the named layouts and regions beside the project (`{"layouts": {...},
"regions": [...]}`, coordinates as whole-unit floats: a canvas gesture snaps to the grid, a
write never does). `feature` is
the fifth: beside a step, `{"on": true, "cites": [{"document": "auth-spec", "quote": "…",
"page": 4, "digest": "<sha16>"}]}` (format 3; formats 1 and 2 kept a catalogue beside the
*project* and only the record's id beside the step, collapsed onto the steps at open —
*Retiring a module* has the absorption). A feature is a step, so its name is the step's
title and its prose the step's description: what is stored here is the one fact nothing
else holds, where in a specification it was read from. What it *gathers* is never stored.
**A passage is a quote and a digest,
never an offset.** Where the quote sits is found again on every read (`core/anchors.py`:
exact, then fuzzy, then lost), because an offset goes stale on every keystroke of the
in-app editor and `spec import` replaces a document with no window running to notice.
`digest` is the content-addressed stem of the document blob the passage was read against
— the same shape as `docs_compiled`'s — so "the spec moved on since this was read" is a
comparison, and a passage read before stamps existed (`""`) is judged by its match alone. `spec` spans three ways: the document index beside
the project, the figures beside a step, and the project's **topology** — how its graph is
shaped — as `modules/spec.md`, the project's one prose document under that id. **A
document may come from a source** (format 4): the index gains `"sources": [{"id":
"src1", "kind": "confluence_page", "title": "Auth Overview", "locator": {"site":
"https://acme.atlassian.net", "id": "12345", "type": "page"}, "fetched": "2026-09-07"}]`,
and a fetched document's row carries `"source": "src1"`, `"key": "12345"` (the kind's own
id), `"version": "7"` (the kind's stamp, a string compared for equality), `"parent":
"auth-overview"` (the document above it, by name; siblings in list order) and `"title"`.
A row without `source` is the project's own and editable — absence kept its meaning, so
no reader learned a key. **`kind` is a document source kind's own id** and the locator is
that kind's, JSON-safe: `folder`'s is `{"path": "/home/knut/specs"}`, `git`'s is
`{"url": …, "ref": "main", "path": "docs/spec"}` (whose `version` is the file's git blob
oid), `confluence_page`'s and `confluence_folder`'s carry the site and the content id.
It never carries a credential — the Confluence token is the keychain's, the connected
sites `user_config`'s, and a git address with a user name and password in it is refused
rather than stored — and it is re-validated on every read, because a plan is shared.
**Format 5** split the one `confluence` kind in two: a stored record becomes
`confluence_page` or `confluence_folder` by its locator's `type`, which is the migration
the split needed — a read-time shim would have let a format-4 build write the old id back
over it on the next refresh.
`step_agent_instruction` does the same with prose: the
step's own instruction beside the step, the project's standing instruction (prepended to
every briefing) as `modules/step_agent_instruction.md` beside the project, images in the
file area at either level. `module_data` is on every node and `set_module_data` is flat
over ids, so nothing in the model has to know. The cost is on whoever writes the next
migration for that format: it sees both shapes and owes both a thought.

**Two ids are how one package gives a node two documents.** `modules/docs/` writes a
step's documentation fragment as `docs.md` and a *collector's* documentation as
`docs_compiled.md`, because a node holds exactly one prose document per module id and a
feature legitimately has both — its own fragment, and what was made of the four steps behind
it. The alternative, a markdown string inside `docs.json`, is the trade the prose row above
already refuses. `docs_compiled.json` carries what the compile recorded, and the key that
matters is `"digest"`: the fingerprint of the sources it read. Whether a document is out of
date is then a comparison rather than a stored flag, so relinking the graph cannot leave one
claiming to be current. **Format 2 dropped `provider` and `model`**: they named the model
that wrote the document while the window compiled with an LLM call, and with `dplanner
compiled set` as the only writer they would hold one value each forever — which agent a
window launched is that window's own record, per user, never the plan's. `docs` also spans
node kinds — beside the *project* it is the **compilation instructions**, which open every
compile briefing, which is `step_agent_instruction`'s shape for the same reason.

**A record list is the shape for a fact a step has several of.** `testing` writes
`{"tests": [{"id": "T100", "title": "…", "body": "…"}]}` beside a step: a *test* belongs to
exactly one step, a step carries several, and each has its own result in a run. The body is
markdown **inside the record** rather than in `modules/testing.md`, because a node holds
exactly one prose document and this is N of them. The trade is explicit: a body edit diffs as one changed line
rather than line by line, which is bearable while test bodies are a few lines each. Images
are the exception and go where a description's do, in the step's file area. Ids are minted
per *project* and meant to be read — `T100, T101, …`, and `R100, R101, …` for runs — so a
run's results are a flat map, an id is quotable in a bug report, and renaming a test never
detaches its history.

**An aspect toggled on with nothing to say yet is a marker entry.** A step's "on/off" for
a toggleable aspect is the presence of its `module_data` entry, and two aspects need a
shape for "on, but empty": `step_ticket` writes `{"on": true}` when the Type toggle
enables it before any field is filled (a filled ticket's entry replaces the marker),
`step_check` writes `{"on": true}` and never anything else — what it *gathers* is the
graph's answer, not a stored list — and `step_agent_instruction` writes `{"on": true}` — plus `"separate": true` when the step
opts into an instruction distinct from its description, and `"worktree": false` when its
agent is to work in the checkout itself rather than a fresh worktree (absence is on: the
opt-outs are the only keys ever added) — beside the step whose prose file
may not exist at all. Both are format 1 of their existing `ModuleDataFormat`s; a step
carrying only the old prose file still reads as agent-on, so no migration ships with them.
A feature is one of them: `{"on": true}` with no `cites` is a feature that was read from
no specification, which is the whole answer — and it is what the retired `step_feature`
module wrote, so that marker needs nothing done to it beyond its stamp.

**What a step's agent runs consumed is a ledger of rows, never a total.** `agent_usage`
(a second aspect id in `step_agent_run/`) writes `{"runs": [{"harness": "claude",
"session": "<id>", "input": 12345, "output": 678, "details": {"cache_read": …,
"cache_creation": …}, "ended": "<ISO stamp>", "prompt_chars": 18412}]}` beside the step —
`prompt_chars` is what the briefing came to, absent for a row `dplanner usage record`
wrote or one recorded before it was measured, and absence reads as *nobody measured*.
It needs no format bump, and the rule is worth stating because `progress_history` below
looks like a precedent for one: **bump when an older writer would destroy the new key,
not when it merely would not write it.** `usage.with_row` copies every kept row verbatim
and `rows()` filters without rebuilding, so an older build cannot drop this one. One row per run,
appended by the window when the shell ends and by `dplanner usage record` from the
terminal, a row per session so a record read twice replaces itself. `input` is everything
sent to the model and `output` everything it generated, whatever the CLI; the CLI's own
finer split rides under `details` in its own words. Totals are summed on read
(`usage.totals`); absence means no agent has run here. The run's *state* stays in
`step_agent_run` and is cleared at exit — the two are different claims, and only this one
outlives the shell.

**Absence encodes the default, and the default is not always "off".** Every aspect above is
one most steps do not have, so the marker records the *claim*. Two go the other way:
`estimation` and `step_description` are things most steps do have, so absence means **on**
and the stored entry is the **opt-out** — `{"off": true}`, written when somebody says a
milestone has no work of its own. Same rule, read in the direction the fact actually points.
The payoff is that making them toggleable cost no migration and changed no existing project:
every step keeps its estimate and its description until a person says otherwise. An
opted-out `estimation` entry carries no `days` and so reads as unestimated, which every
total already skips.

**An aspect turned off is shelved, not dropped.** Turning an aspect off moves its entry and
its prose to the domain's own entry beside the node — `modules/shelf.json`,
`{"format": 1, "aspects": {"step_milestone": {"data": {…}}, "step_description": {"data":
{…}, "text": "…"}}}` — and leaves the aspect's own entry as absence says it should: gone
for a marker aspect, the `{"off": true}` opt-out for the two above. Turning it on restores
from the shelf before it would write anything fresh, and an emptied shelf leaves no file.
An aspect that held nothing shelves nothing, so a bare marker toggled off is exactly what it
was before. The shelf is *not* an aspect and belongs to no module: `domain/shelf.py` owns
the format, the migration pass migrates each shelved entry with its module's own chain, and
files in a module's area are left where they are — they were never undoable, and the
shelved prose still links them. `dplanner … clear` shelves the same way the toggle does.

**Not every module entry is an aspect.** The graph editor stores each node's position — and,
for a card somebody resized, its size, absent for the default footprint — as
`modules/project_editor.json` beside the step, and it is deliberately *not* an `AspectSpec`:
an aspect is a fact about the work that an agent may want to write, and a layout is
presentation. It is per step rather than one map on the project so that moving a node is a
one-file diff — the same reasoning as ordering living in the parent's list. The time
report's assumptions are the second instance: `modules/time_estimates.json` beside the
project, `{"efficiency": 0.5, "palette": "mako", "team": [2, 3]}` — the focus factor, the
colour map and the team the calendar is dated for, each absent on its default — an
assumption about the team, not a fact about a step. The same module writes `{"start":
"2026-10-05", "color": "#e0602c"}` beside a *milestone* step: the day its stretch of work
begins instead of the day the previous one lands, and a colour chosen over the dealt one
— assumptions again, and the landing date itself is never written. The same package
writes a **second id** beside the project, `modules/progress_history.json` (format 2):
`{"days": [{"day": "2026-09-05", "stretches": [{"milestone": "<step id>", "steps": 8,
"done": 3, "days": 11.0, "done_days": 4.5, "start": "2026-09-07", "finish":
"2026-10-12", "landings": [{"date": "2026-09-09", "steps": 2, "days": 3.0}, …]}]}],
"saved": [{"title": "Kickoff review", "note": "What we thought on day one", "day":
"2026-09-05", "stretches": […]}]}` — under `days`, one row per day on which the plan's
progress or its promise changed, the stretches in the order the sequence ran them that
day (no `milestone` key for the work after the last one, no `finish` for a stretch
nothing dated, no `landings` for one with nothing to land); under `saved`, the
snapshots somebody kept on purpose, the same row with the `title` it is found by and a
`note` when one was given (no `saved` list without one; a row there without a title is
not a saved snapshot and reads as absent). A saved snapshot is never replaced by a later
change, and an automatic day never carries a title. The landings are what the simulation
expected to land on each date, so the plan as it stood that day is drawn exactly from
the row. It is the one derived-looking thing that is stored, because the past cannot be
recomputed: the chart of the plan against what became of it needs where the plan stood
and what it promised on earlier days. The bump to format 2 exists for the `saved` key,
so an older build refuses to rewrite the entry rather than dropping what somebody saved.
**An estimate
remembers what it was** for the same review: `estimation.json` (format 2) carries
`"history": [{"day": "2026-09-12", "days": 3.0}]` beside `days` — the value that stood
when each listed day began, one row per day it changed, written only by a writer that
handed over the entry it replaced, and gone with the entry when a step is unsized. The
asset browser's display titles are the third: `modules/project_assets.json` beside the
project, `{"titles": {"assets/<sha16>.png": "Login mock"}}` — presentation for
content-addressed files, keyed by content name so one title covers every copy and no link
ever carries it. The **note log** is the fourth: `modules/notes.json` beside the project,
`{"notes": [{"id": "N1", "label": "handoff", "title": "…", "body": "…", "made":
"2026-09-05", "step": "<step id>", "for": ["<step id>"], "reach": "project",
"supersedes": "N0"}]}` — a record list like the feature catalogue (every key but `id`,
`label` and `title` omitted when empty; `reach` written only for the one exception,
`"project"` — a note reaches the steps after the one it was made on by default, so
*downstream* is never written), ids minted per project and never reused so a later note can
name the one
it replaces, the label one of the closed list in `modules/notes/log.py`. It absorbed two
earlier shapes at open — `modules/decisions.json` by takeover, and each step's
`step_handoff.md`, `step_handoff.json` and `step_handoff/assets/` by the format's
`absorb` pass (*Retiring a module* below) — so neither is written any more. The
distinction has one
practical consequence worth knowing: the CLI's migration list is built from the aspects
*plus* anything like this, and a format missing from it is data the CLI silently
declines to bring forward.

**A module that writes a number owes it a `float`.** The old format enforced this at the
model boundary, because an `int` writes as `5` where a reloaded float writes as `5.0`
— making a file's bytes depend on whether the project had been reopened since it was
written. Module data is opaque to the model and `stamped()` writes whatever dict it is
handed, so on this axis the duty belongs to whoever owns the number. See
`modules/estimation/aspect.py`, which is the reference for it, and
`modules/project_editor/positions.py`, which owes it for a coordinate.

## Two writers, one folder

DPlanner expects an agent to run `dplanner` against a project a window has open. "Memory
is authoritative, disk follows" is therefore not the whole story, and the rule that completes
it is:

**Nothing writes over a file it has not seen.** `LibraryStore` records what each project
directory looked like when it last read or wrote it and raises `StaleWorkspaceError` rather
than flushing over anything that changed underneath — **per project**, so an agent editing
one project never blocks saving another, and the error names the project. The library file
gets the same treatment with its own stamp, because two instances can both add a project.
A CLI run reports the refusal and writes nothing; a window pauses autosave, keeps the
edits, and offers *File ▸ Reload from Disk*. The same check is why two CLI runs need no
lock between them: the second one is simply refused and can be run again.

## Retiring a module

Its successor's package carries the retired module's on-disk contract — its id, its final
format and a converter — as a `Takeover`. At open, the old entry is brought up to its final
format through the carried chain, converted, merged into the successor's entry, and removed.
The retired module's *code* is gone; only its data contract survives, in the package that
inherited it. Modules never import each other, and this is why they do not have to.

`modules/estimation/aspect.py` is the worked example: `step_estimation` became `estimation`
when it grew a project's start date, and the rename cost no project-format migration and no
import. `modules/step_milestone/aspect.py` is the second: `step_release` became
`step_milestone` when *release* turned out to be the wrong word for a thing that collects
features. `modules/feature/aspect.py` is the third: `step_feature` became `feature` when a
feature grew a catalogue beside the project and stopped being a marker on a step. Its
converter was for a while the one that could not finish the job — a per-entry converter
never sees the project, so it could not mint the record and the entry read as
*unregistered* until a verb did. Format 3 put the feature back on the step, and with no
catalogue left to be missing from the converter's `{"on": true}` is a complete answer
again. Three rules they make concrete:

- **The retired format's version is frozen forever.** `RETIRED_STEP_ESTIMATION` is format 1
  because that is what that module last wrote, whatever the successor does next.
- **`convert` must emit the successor's *current* shape.** The engine stamps the result with
  the successor's version and does **not** run the successor's own chain over it. So a
  successor that later goes to format 2 edits its converter too. This is also the cheap way
  to retire a field: `estimation` drops the old `confidence` simply by rebuilding the entry
  from `days`, and needs no migration of its own to do it.
- **A takeover is one-way.** The old file is deleted at the first open by a build that has
  the change, so an older build opening the project afterwards sees that feature as empty.
  That is the same trade as any format change, and worth saying out loud before a rename.
- **Data that changes owner is an absorption, not a takeover.** A converter sees one entry
  on one owner; a step's prose becoming a record on its project needs the whole
  repository and the aggregate that says how owners relate. `ModuleDataFormat.absorb` is
  that pass — run once per open after every per-entry migration, handed the repository
  and the loaded library, returning the owners it changed, and idempotent because it runs
  on every open. `modules/notes/migrate.py` is the worked example: the retired handoff
  aspect's prose, scope and files become a `handoff` note on the step.
  `modules/feature/migrate.py` is the second, and it adds three things the next one will
  want. **A created node's data goes on the object before `add_child`, and its id is never
  returned**: the builder flushes what an absorption returns with the `module_data` and
  `module_text` aspects only, and a node that did not exist a moment ago has no directory
  recorded — the parent's *structure* mark is what writes the subtree. **The shelf is
  reached from the absorption itself**, because `migrate_shelved` runs afterwards and
  would walk a shelved entry through the per-entry chain, stamping a shape the absorption
  meant to rewrite. And **an absorption may write into a *living* module's namespace** —
  the feature record's description becomes the step's `step_description` prose, its
  opt-out is lifted and its images land in that module's file area — naming the id as a
  **string constant and never an import**, since a module may not import another. Do that
  only where the alternative is worse: here it is keeping a second description beside the
  step's own, which is the duplication the format change exists to remove.
