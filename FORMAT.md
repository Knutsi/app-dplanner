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
| Per user, per machine (Qt-free) | a headless run's working files: its briefing, each turn's stream (`turn-<n>.jsonl`) and stderr, DPlanner's copy of a plan the agent wrote (`plan.md`), the findings a fix was handed (`findings.json`), the supervisor's and the record's locks (`supervisor.lock`, `record.lock`: OS locks on files never deleted) | `config_dir()/runs/<run id>/` (`ledger.run_dir`), named by the run's ledger record and never stored on it; not swept yet | no — only the launching machine can resume the run, and it needs them across a reboot, which is why they are not in `/tmp` |
| Per user, per machine (Qt-free) | what each agent account last said about its usage — its windows, whether it ran out and until when — and the share a new headless launch waits at | `modules/agent_supervisor/limits.py` in `config_dir()/usage-limits.json` — see *An agent account's usage* | no — an account is a login on this machine |
| Per user, per machine (Qt-free) | a read-only location's managed clone, and a git spec source's: blobless, shallow, sparse to one folder | `core/storage/sparse.py` under `config_dir()/spec-git/<digest of remote, ref and folder>` | no — disposable: wipe it and the next read pays one tree fetch |
| Per user, per machine (Qt-free) | the agent launch profiles: `{"format": 1, "profiles": [{"name", "agent", "terminal"}…], "seeded": bool}`, the first the default | `agent_launch/profiles.py` at `config_dir()/agent-profiles.json`, because `dplanner agent run --profile` reads them with no Qt; the window adopts what QSettings held before, once | no — which terminal a person prefers is not the project's business |
| Per user, per machine (Qt-free) | a working clone DPlanner keeps for a verb that needed the repository here and nobody had checked out — Run Agent's code, a report's destination — under the default clone policy | `core/storage/kept.py` under `config_dir()/checkouts/<name>-<digest of remote>`, one per repository; recorded in the library file's `checkouts` map like any checkout | it is a checkout: commits an agent made there and never pushed are in it and nowhere else, so it is not wiped by the application |

| Per user, per machine (GUI only) | preferences: panel layout, model choices, the agent launch settings | `framework/user_config.py`'s `get_global` (QSettings) | no |
| Per user, per machine, per library | where the user left off: open index folders, open tabs | `framework/user_config.py`'s `get_scoped`, under `library_scope(path)` | no |
| The OS keychain | credentials, API keys — the LLM keys, a Confluence token per site (`spec_confluence.token:<host>`) | `core/secrets.py` | no, and never on disk |

If you are unsure, ask who the value belongs to. A colleague opening the project should
see its conventions and none of your preferences.

The last two rows differ over *whose truth it is*. "Reopen my tabs" is the person's and
follows them into every library; "these tabs were open" is one library's, and restoring it
into another would be nonsense. Anything in the scoped row is written **keyed by node id**,
so a value naming something that has since been deleted restores nothing — which is why
neither needs a version stamp or a migration.

**A project answers three repository questions, and they go to different rows.** *Where
does the plan live?* — the **plan repository** — is never stored: it is the git repository
enclosing the project directory, `find_repo_root`'s answer. *Which places is it about?* —
its **locations**, each a role, a repository as git prints its remote (or, for one with no
remote, its resolved path) and a position inside it — is `"locations"` in `project.dproj`,
shared with everyone who opens the plan. *Where is each of those on this machine?* is the
library file's `checkouts` map, per user, per machine, below, for a location that is worked
in; a read-only one is fetched into a managed clone and never asks.
`docs/architecture/persistence.md`'s *A project names its locations* has the reasoning;
`domain/repositories.py` is the one derivation over the three.

## The library file

`library.json` records **membership**: which project directories this user is planning —
and where this machine has the repositories those projects name.

```json
{
  "format": 4,
  "projects": [
    {"path": "/home/anna/plans/widget"},
    {"path": "/home/anna/code/gadget/planning"}
  ],
  "checkouts": {
    "github.com/acme/widget": "/home/anna/code/widget"
  },
  "archived": [
    {"path": "/home/anna/plans/launch"}
  ]
}
```

- The default lives at `$XDG_CONFIG_HOME/dplanner/library.json` (platform equivalents on
  Windows/macOS — see `core/config_dir.py`; `$DPLANNER_CONFIG_DIR` moves the whole of that
  directory); `--library PATH` or `$DPLANNER_LIBRARY` names another. It is per user and per
  machine, and never belongs in version control.
- Paths are absolute (`~` is allowed) and the array order is the order the Projects panel
  shows.
- `checkouts` is optional: where this machine has each repository, keyed by the
  repository's canonical spelling (`canonical_remote`: host and path, lowercased, `.git`
  dropped; a remote-less repository by its resolved path). **Per repository, never per
  project** — a checkout is this machine's fact about a repository, so two projects naming
  one repository share it and a second plan for the same code never asks for a second
  clone. It is written by the Project dialog, by `dplanner location checkout`, by the Open
  Project wizard's Repositories page, and by the first `dplanner` call that runs inside a
  checkout whose `origin` is one of a project's code locations — **straight into the file**
  (`LibraryStore.set_checkout`, read-modify-write of that one key), never through a dirty
  mark, because a read verb's transaction must never be refused over a per-machine fact. A
  format-2 row carried its project's code checkout instead; reading one files it under the
  checkout's own origin. A format-1 file reads as format 3 with no checkouts.
- `archived` is optional: the project directories this user took out of the library and
  kept listed, in the order they left. An archived project is never opened, watched or
  saved, and attaching its directory again — *Restore Project*, *Open Project…* on it,
  `dplanner library add` or `library restore` — takes it off the list. Per user like the
  rest of this file: archiving is one person's tidying, and nothing about it reaches the
  plan. **Format 4 is this key**, bumped because a format-3 writer rebuilds the file from
  what it knows and would drop the list; no reader checks the stamp, so a format-3 build
  that writes membership still drops it, which leaves the directories on disk and costs
  what *Remove from Library* costs. A format-3 file reads as format 4 with nothing archived.
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
stored: how long ago that was, whether the claim still stands, and how far along the agent
says it is are all computed on every read (`domain/at_work.py`). A claim whose `seen` is
three minutes old has **lapsed** — no reader shows it — but its file is kept, so the next
renewal makes it stand again.

**It is never in the project directory**, and that is the whole reason it is a row of its
own above: it changes every few seconds and means "a process is running on this machine,
now". In a plan it would be committed into everybody's history, arrive at every
collaborator as an outside change, and have the window adopting an edit every two seconds.
The file name is only a name — a reader takes the project and step from inside the record —
and there is no migration: a file this build cannot read is skipped, and a claim nobody has
renewed for a day is deleted by the next writer.

It is not the **claim** in a project's `claims/` directory (below), and neither absorbs the
other: this one says *a process here is editing the plan right now* and lapses in minutes;
that one says *this work is taken by a squad*, is renewed every ten minutes, holds for an
hour and a half, and is committed so other machines see it.

## An agent account's usage

`config_dir()/usage-limits.json` is what every supervised turn writes and every headless
launch reads (`modules/agent_supervisor/limits.py`). **An account is a harness and the home
its login is in** — `<harness id>:<home>`, the home `$CLAUDE_CONFIG_DIR` or `~/.claude`,
`$CODEX_HOME` or `~/.codex`, OpenCode's data directory (`AgentHarness.home`) — resolved alike
by a launch and the supervisor it starts, so two logins are two accounts.

```json
{
  "format": 1,
  "hold_at": 0.95,
  "accounts": {
    "claude:/home/knut/.claude": {
      "seen": "2026-10-07T17:42:10+00:00", "run": "20261007T150000Z-1a2b3c4d",
      "windows": [{"name": "five_hour", "used": 1.0, "resets": "2026-10-07T18:10:00+00:00"},
                  {"name": "seven_day", "used": 0.34, "resets": "2026-10-09T09:00:00+00:00"}],
      "out_until": "2026-10-07T18:10:00+00:00", "out_at": "2026-10-07T17:42:10+00:00"
    }
  }
}
```

- **`hold_at`** is the setting (*Settings ▸ Agent profiles ▸ Hold new headless launches at*,
  95 % when absent): a new headless launch waits while any window is at or above it, until
  that window resets.
- **`windows`** are the vendor's own — Claude's `rate_limit_event`, Codex's rollout
  `rate_limits` — `used` a share from 0 to 1, as reported by the turn that ended at `seen`;
  a turn that ended earlier never replaces them, whatever order the supervisors write in.
- **`out_until`** is set when a turn ended `limit` with a known reset, the turn's end in
  `out_at`, and removed only by a turn that ended `done`, `asked` or `denied` after `out_at` —
  a failure, or an answer older than the exhaustion, says nothing. While it stands, no turn
  starts on the account except one carrying an answer — the supervisor parks it
  `limit`/`held` instead.

It is read-modify-written under an OS lock on `usage-limits.lock` beside it, because every
supervisor writes it. It is advice, so a file this build cannot read reads as nothing known,
and a turn never fails for want of writing it.

## The project format


A project is one directory **inside a git repository**, one directory per node below it,
nested exactly like the model:

```
<plan repository>/
├── .dplanner                  the index: one project directory per line, relative
└── widget/                    the project directory — any folder in the repo
    ├── project.dproj          id, title, summary, repository, colocation, created, format, children
    ├── ledger/                its agent runs: what each did and consumed, a file per run (below)
    ├── questions/             what its agents asked and who answered, a file per question
    ├── claims/                which squad has taken which steps, a file per claim
    ├── modules/               module data belonging to the project itself
    │   ├── notes.json         the notes the project made along the way
    │   └── notes/assets/      files those notes link
    └── steps/
        └── read-the-spec/     folder name, frozen at creation
            ├── step.json      id, title, edges
            └── modules/
                ├── estimation.json         structured data
                ├── step_status.json        {"status": "done", "since": …, "started": …}
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
  and never written; `docs/architecture/graph-model.md`'s *A step has a number* has the reasoning.
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

**Two keys on the project say where it stands with its code.** `"locations"` is the table
of places the project is about — rows of `{"id", "role", "repository", "path", "ref",
"label"}`, absence encoding the default: no `path` is the root, no `ref` the repository's
default branch, no `label` the only row of its role, and no code row at all one of two
things, told apart by the `.dplanner` index below: a project the index lists has its code
**not set yet**, and nothing reads the plan repository as its code; one it does not list —
a project that is its repository's root, or one from before the index — plans the
repository it sits in, the older shape, warned about by lint, the briefing and the window
until it is moved or accepted. The `id` (`l1`, `l2`, …) is minted per
project and kept while the row is edited, because a spec source and a step's workplace
name a row by it; `role` is a word from the registry — the domain's `code`, and `spec` and
`reporting` from the modules that act on them — and **a role this build does not
know is loaded and written back untouched**, the edge-kind rule; the first `code` row is
*the* code repository every older reader means. `"colocation": "accepted"` is the
acceptance: the people on the project decided the plan stays inside its code on purpose,
and every warning stands down. Both are set by the Project dialog and the `dplanner
location` and `project set` verbs; `project move` adds the first code row to a plan of
the older shape and drops the second as it goes. Format 3 moved the earlier `"repository"` string into the first row.

**Edges are keyed by kind**: `"edges": {"requires": ["<step id>", …]}`. One line per edge
rather than an object per edge, and the direction cannot be read the wrong way round —
`requires` is what *this* step waits on. The kind vocabulary is the domain's
(`domain/model.py`), because a kind only some builds understood would make a shared project
mean different things to different people. **A kind this build does not know is loaded and
written back untouched**, so a colleague's newer link survives an older build opening the
file.

### The `.dplanner-worktrees` directory

Run Agent and `dplanner agent run` keep a step's worktree at
`<repository>/.dplanner-worktrees/<run name>` on the branch `agent/<run name>`, where the run
name is the step's key, its ticket key and its title slug (`f7-PROJ-12-build-the-modal`).
Local and never versioned: `agent_briefing/worktree.py`'s `prepare` adds
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
`"path": "."` is a plan repository that is one project. A `path` that is absolute or climbs
out with `..` is refused, and so is a remote that starts with `-`: a link comes from
somebody else, and it may name a folder inside its plan repository and nothing more. `"format"` is the link's own axis,
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
project *is* the root. Save never writes it — generated pages committed by every Save
collide between people sharing a plan repository — and nothing commits it: `dplanner report
site` writes it from a terminal, and the window's *File ▸ Export ▸ Report Site (Folder)…*
writes the same layout into any folder. A shared plan repository is best off ignoring
`reports/` in its `.gitignore`. The index is a
function of the set of `*/summary.js` present, so its bytes change only when a project
joins or leaves — the rule that keeps two writers from conflicting over a generated page.
The directory name is a constant, not a setting. Nothing in it is versioned or migrated:
every write rewrites it whole from the plan. `docs/architecture/cli.md`'s *A report is a
publication, not a record* and *Reports are written on request, never on Save* have the
reasoning.

### The `ledger` directory

What every agent run on a project consumed, one file per run, beside `steps/`:

```
<project dir>/ledger/
└── 2026-10/                                  the month the run was launched
    └── 20261001T192149Z-1a2b3c4d.json        the run: launch to the second, UTC, and 8 hex
```

```json
{
  "format": 1, "run": "20261001T192149Z-1a2b3c4d", "project": "<id>", "step": "<id>",
  "harness": "claude", "launched": "2026-10-01T19:21:49+00:00",
  "machine": "<machine id>", "host": "knut-arch", "dir": "/abs/worktree",
  "session": "<the main agent's>", "ended": "…", "exit": 0, "harvested": "…",
  "measurement": "native", "account": {"vendor": "anthropic", "plan": "claude_max", "id": "<opaque>"},
  "prompt_chars": 18412,
  "agents": [
    {"id": "main", "session": "…", "models": {"claude-opus-5-5": {"in": 115063, "cached": 2035193, "out": 24725}}},
    {"id": "a6318…", "parent": "main", "kind": "Explore", "models": {"claude-opus-5-5": {"in": 120636, "cached": 5635747, "out": 8286}}}
  ]
}
```

- **One file, one writer.** The id is minted at launch; only the machine that launched the
  run can read the vendor records it is filled from (`machine` is the id in
  `config_dir()/machine-id`), so only that machine writes the file. Two machines add two
  files and git never conflicts; nothing locks.
- **A snapshot, rewritten whole.** Launch writes the record with no `agents`; every harvest
  rewrites it from the vendor's records, larger while the run goes on. A write that would
  change nothing is skipped. `ended` and `exit` are written once, never cleared.
- **Three counts per model, one meaning across vendors:** `in` is fresh input and cache
  writes, `cached` cache reads, `out` everything generated, reasoning included.
  `measurement` is `native`, `partial` (part of the tree unreadable — a floor),
  `manual` (`dplanner usage record --input/--output`) or `legacy` (absorbed from the
  retired aspect; model `unknown`).
- **No address.** `account` is a vendor, a plan and an opaque id — the file is committed
  with the plan, which colleagues read.
- **Outside `PLAN_ENTRIES`**, so the store's stale check and outside-change watch never
  see it; Save commits it with the project, because Save's scope is the whole project
  directory; `dplanner usage …` writes it and never commits; Move Plan carries it.
- Absence encodes the default; a file this build cannot read is skipped; there is no
  migration — the format is in every record. Totals are summed on read.

`docs/architecture/agents.md`'s *Usage is a ledger, harvested by anyone* has the reasoning.

#### Format 2: the record is the run

Written by the run supervisor (`modules/agent_supervisor/`) for a headless run, `"mode":
"headless"`; a run in a terminal is still written as format 1, which every older build reads.
A headless run is turns of one session that park between them (`docs/research/2026-10-07-headless-agents/`), and the record above grows to
hold them rather than a second record growing beside it. **It is the playbook ledger too**:
a step's stage history is its runs, read in order — there is no other.

```json
{
  "format": 2, "run": "20261007T101500Z-9c1e44ab", "project": "<id>", "step": "<id>",
  "harness": "claude", "launched": "2026-10-07T10:15:00+00:00", "machine": "<machine id>",
  "session": "…", "mode": "headless",
  "playbook": "plan-execute-review-other", "pass": "20261007T101455Z-0d9e8f7a",
  "stage": "execute", "attempt": 1,
  "callsign": "kettle-three", "claim": "20261007T100212Z-5a0b7c3d",
  "turns": [
    {"n": 1, "prompt": "launch", "started": "…", "ended": "…", "end": "asked", "why": "prose",
     "reason": "<the question>", "exit": 0, "pid": 41822, "boot": "<boot id>", "pid_started": "<start time>",
     "question": "20261007T103341Z-e1f2a3b4", "usage": {"agents": [ … ]}},
    {"n": 2, "prompt": "answer", "started": "…", "ended": "…", "end": "limit", "exit": 1,
     "pid": 42010, "boot": "<boot id>", "pid_started": "<start time>", "resets": "2026-10-07T15:00:00+00:00",
     "consumed": {"question": "20261007T103341Z-e1f2a3b4", "answer": "20261007T104102Z-4c4c9a01"},
     "usage": {"agents": [ … ]}},
    {"n": 3, "prompt": "reset", "started": "…", "pid": 51377, "boot": "<boot id>", "pid_started": "<start time>"}
  ],
  "measurement": "native"
}
```

A review run carries its `verdict`, and the fix run after it what it `declined`:

```json
"verdict": {
  "outcome": "changes", "summary": "One race in the sweep",
  "findings": [
    {"severity": "high", "file": "src/dplanner/domain/at_work.py", "line": 374,
     "text": "The sweep can delete a claim renewed since it was read",
     "evidence": "_sweep reads, then unlinks without re-reading"}
  ]
}
```

```json
"declined": [
  {"finding": {"run": "20261007T120000Z-77aa01bc", "index": 0},
   "reason": "_still re-reads just before the unlink; the window is microseconds"}
]
```

- **One run is one stage attempt.** Resuming its session — with an answer, after a limit
  reset, on *Retry now*, or to nudge it on — is another **turn** of the same run. A
  **loop-back** — a gate sent the work back — is a **new run** with the next `attempt`, even
  when it resumes the same session, because the attempt it fixes is over; so one `session`
  may span several runs, and a session id never identifies a run. A fresh session is a new
  run too. `playbook`, `stage` and `attempt` are the playbook's words, and
  `docs/architecture/playbooks.md` says what they mean.
- **`pass`** names the playbook pass the run belongs to; every run and gate question of
  the pass carries it, so a pass is never inferred from the order of records. The pass's
  resolved settings are pinned once, as `settings` — `{preset, revision, rounds, roles,
  overrides}` — on the pass's first record only: its first run, or its first gate question
  when the pass begins at a `person` or `coordinator` gate. `playbooks.md` says what each holds.
- **`stage`** is the stage's id in its playbook — its kind, numbered where the kind repeats
  (`review-2`) — or `fix`, the execute a gate with no work before it sends its findings to;
  `agent run` alone writes `execute`. A pass's runs are stamped to the microsecond
  (`launched`), so two made in one second still say which came first.
- **`prompt`** is why the turn began: `launch` for every run's first turn, whether its session
  is fresh or resumed for a loop-back, then `answer`, `continue`, `reset`, `retry` or
  `verdict` — a turn resumed on the clock's answer to a limit is `reset`, on *Retry now*
  `retry`, and a review that ended without its verdict, asked once more for it in its
  session, `verdict`. A launch resumes a session exactly when an earlier run of its pass names
  the same one; nothing else marks it.
- **`verdict`** is on a review run: its typed final message (`--json-schema`,
  `--output-schema`), recorded by the supervisor and never posted by the agent — `outcome`
  `pass` or `changes`, a `summary`, and `findings`, each with `severity`, `file`, `line`,
  `text` and `evidence`. A review that ends without one has no verdict, and that is a
  failure, never a pass.
- **`declined`** is on a fix run: each finding the implementer would not act on, by the
  review run's id and the finding's `index` in its list (a person's note is `{"question": <id>,
  "index": 0}`), with the `reason` the next round reads. The fix's typed final message names
  them by their number in its briefing (`TURN_SCHEMA`'s `declined`); the supervisor turns the
  numbers into these references through the run directory's `findings.json`, the list the
  engine handed it.
- **`end`** is how a turn ended, and it is read from the stream and the result, never from
  the exit alone — a headless `success` can hide an open question:

  | `end` | Means | The run |
  |---|---|---|
  | `done` | the agent finished its stage | is over |
  | `asked` | it asked through `dplanner question ask`, or ended on a question in prose; `question` names the record | parks until the question is answered |
  | `denied` | a permission was denied or auto-rejected | parks on a `permission` question |
  | `limit` | the account ran out; `resets` is when it comes back, `why: held` when the supervisor parked the turn without starting it, its account being out, `why: past-reset` when the reset had already passed as the turn ended (waited for once, the grace only; a second in a row has no `resets`) | parks on a `limit` question: with a `resets`, its supervisor waits, and the clock answers it then; with none, a person does |
  | `failed` | a crash, a hang, a runaway, a dead login; `why` says which — `headless.Ending.why`'s words, or the supervisor's own `hang`, `runaway`, `timeout`, `lost` and `lost-at-spawn` | retries with backoff, then parks on a `blocked` question; a runaway, a `lost-at-spawn` and a failure no retry mends park at once |
  | `stopped` | a person or the coordinator ended it, or its step went away | is over, and is never retried |

  A turn with no `end` is running, or was lost with its machine — which only that machine
  can tell: every turn records the process's `pid`, the machine's `boot` id and the
  process's start time, `pid_started` (`/proc/<pid>/stat`'s `starttime` on Linux, the
  process creation time on Windows), and a process is live only if all three still match —
  so a reused pid never reads as live (`core/process.py`'s `ProcessStamp`; `boot` is "" on
  Windows, where the creation time alone tells two processes apart). A supervisor started on
  a run whose last turn has no end and no live process ends it `failed`, `why: lost`, and
  retries; ending the lost turns of every run when a machine starts is not built yet.
  `reason` says the rest in words: what failed, or the question the turn ended on.
  **`question`** names the question record the run parks on — the one the agent asked
  through `dplanner question ask`, or the one the supervisor wrote for any other park (a
  question found in prose, a denial, a limit, a run that cannot go on alone) — so every
  parked run stands on a card in the inbox.
- **`usage` is the turn's own consumption, never a running total**, counted from the turn's
  own stream — which is exactly that turn's window of the session, so it needs no cursor into
  the vendor's records — when the turn ends, or when the next supervisor ends a lost one from
  the stream it left. `agents` names the model where the stream does. A run's usage is its
  turns' sum, so several runs sharing one session each count only their own turns. In format
  2 `agents` is on turns, never on the record, and a harvest leaves the record alone: the
  supervisor is its one writer. Subagents count as far as the stream reports them.
- **`consumed`** is on the turn an answer resumed: which question, and which answer — its
  identity, not its text. See the questions directory for when an answer may be consumed.
  A resume that is no answer (`continue`, `reset`, `retry`, or words handed to the
  supervisor) withdraws the question the run parked on, and a run's end withdraws whatever
  it still had standing.
- **Whether a run is running, parked or over is read, never stored.** `ended` and `exit` now
  say the *run* is over — its last turn ended `done` or `stopped`, or a person gave up on
  it — not that a process exited; every turn keeps its own.
- **The launching machine is still the one writer.** Only it has the session's files and
  the worktree, so only it can start the next turn; an answer given anywhere else reaches it
  as the question's file, through git. `callsign` and `claim` say which squad's worker ran it.
  **The one exception is a `fence`** — `{at, by, why}`, written by a takeover from anywhere —
  after which the run is over: the launching machine fetches before every turn and ends a
  fenced run `stopped` instead of resuming it, and in a merge the fence wins. `why` is
  prose, but one value is read: `taken over by a person` (*Open Session*), which a pass
  reads as *Taken over* rather than *Stopped*.
- **`summary`** is on a work run (`plan`, `execute`, `fix`) that ended `done`: the agent's own
  account of what it did — its typed final message's `summary`, or, from a CLI with no schema,
  its final text — what a person reviewing the pass reads first. A run recorded before the key
  existed has none; the Playbook tab reads it back from the run's own stream, which only the
  launching machine keeps.
- **A plan stage's final text** — the plan — is copied to the run directory's `plan.md`, so
  DPlanner's copy does not depend on the one Claude leaves in `~/.claude/plans/`.
- **Why the format is 2:** a format-1 harvest rewrites the record whole from the keys it
  knows and would drop `turns`, and format 2 moves usage onto them. A format-1 build skips a format-2 record, as it skips any
  newer one, so the cost of the bump is that such a build does not count these runs' usage —
  and only these: a terminal run, with no turns, is still written as format 1.

### The `questions` directory

Written by `dplanner question ask` and the run supervisor (`domain/questions.py`). Everything
a run needs a person — or the coordinator — for, one file per question, so two agents asking at once add two files and
git never conflicts:

```
<project dir>/questions/
└── 2026-10/                                  the month it was asked
    └── 20261007T103341Z-e1f2a3b4.json        minted as a run id is; shown as Q-e1f2
```

```json
{
  "format": 1, "id": "20261007T103341Z-e1f2a3b4", "project": "<id>", "step": "<id>",
  "run": "20261007T101500Z-9c1e44ab", "asked": "2026-10-07T10:33:41+00:00",
  "by": {"callsign": "kettle-three", "harness": "claude", "machine": "<machine id>", "host": "knut-arch"},
  "kind": "decision",
  "questions": [
    {"question": "Keep both records, or let the claim absorb at-work?", "header": "At-work",
     "multiSelect": false,
     "options": [{"label": "Keep both", "description": "Two clocks, two jobs"},
                 {"label": "Absorb", "description": "One record, committed"}]}
  ],
  "state": "consumed",
  "answer": {"id": "20261007T104102Z-4c4c9a01",
             "answers": {"Keep both records, or let the claim absorb at-work?": "Keep both"},
             "by": {"kind": "person", "name": "Knut"}, "at": "2026-10-07T10:41:02+00:00"},
  "consumed": {"at": "2026-10-07T10:41:30+00:00", "run": "20261007T101500Z-9c1e44ab", "turn": 2}
}
```

- **`kind`** is `decision`, `plan-approval` (the plan is the `body`), `permission` (what was
  denied is the `body`), `blocked` (the run cannot go on alone: a dead login, retries spent,
  a terminal run its multiplexer says is waiting) or `limit` (`resets` is when the account
  comes back). **A usage hold is a question** answered by *Retry now* or by the clock, so
  every card in the inbox is one of these files and nothing else.
- **A playbook asks too**: a gate, a round cap reached, or an escalation. Such a question
  has no `run`, names no harness, and carries `pass`, `stage` and `attempt` beside the step,
  and `purpose` — `gate`, `round-cap` or `escalation` — so what it is for is never read from
  its place in the order. Its kind is `plan-approval` for a gate after a plan and `decision`
  for everything else — but for an `escalation` the pass raises because it could not act (a
  stage's launch refused, or `progress` unable to merge), which is `limit` with `resets` when
  the account is held and `blocked` otherwise, answered *Retry now* or by the clock. An
  agent's own question has no `purpose`. A `progress` gate, like a `person` gate, only a
  person answers. **A person's look at a pass that is through is a gate too**, at the stage
  `look`, which no playbook lists: *Send Back* asks it and answers it with the note at once
  (`dplanner playbook send-back`), and it stands after every stage, so its *changes* goes
  back to the last work stage and its rounds count like any gate's.
- **`questions` is Claude's `AskUserQuestion` shape exactly** — question, header, options
  with descriptions, `multiSelect` — so a hosted Claude's own question is written through
  unchanged, and `dplanner question ask` writes a list of one. `answer.answers` is the shape Claude
  takes back (`updatedInput.answers`): each question's text to the chosen label, or to free
  text.
- **`state`** is `open`, `escalated` (the coordinator passed it to a person: `escalated`
  holds `at`, `by` and `why`), `answered`, `consumed` (the answer was acted on:
  `consumed` holds `at` and, for an agent's question, the `run` and `turn` it resumed; for a
  playbook's, the `pass`, `stage` and `attempt` it settled), or `withdrawn` (the run ended or asked again:
  `withdrawn` holds `at` and `why`; `why` is prose, but `taken over by a person` — *Open
  Session* withdrawing a pass's gate — reads the pass as *Taken over*, as the run's fence does).
  `consumed` and `withdrawn` are terminal.
  `answer.by.kind` is `person`, `coordinator` or `clock` — the last only for `limit` — and
  `answer.id` is minted as a run id is.
- **Who may answer.** A person may answer any question. The coordinator may answer an
  agent's question and a `coordinator` gate's; a `person` gate's it may only escalate. The
  gate is named by `stage`, and the playbook says which kind it is.
- **Only the launching machine consumes an answer**, and only after it has fetched, found
  the run still resumable — not over, not fenced, its last turn parked on this question — and
  pushed the question marked `consumed` with the turn it starts; a rejected push means fetch
  and check again before the turn begins. The resumed turn records the answer's id
  (`consumed` on the turn). *As built, one machine:* the check is made under the run's lock
  and the question's, re-reading both; one ledger write records the resumed turn with the
  answer it consumes before the question is marked `consumed`. Just before its process is
  started, that turn gains `spawning` (when); a turn found holding an answer with no pid is
  started only if it has none — one with `spawning` may have acted on the answer, so it ends
  `failed`, `why: lost-at-spawn`, and the run parks on a `blocked` question naming the answer. The fetch and the push are not
  written yet. The run's supervisor delivers an answer: it looks for one whenever it starts
  and after it lets go of a parked run.
- **Who answers is read from the caller's shell**: inside a run or an agent's shell it is
  the coordinator (`answer.by.kind`), and a run may not answer its own question.
- **Every change is a read-modify-write under an OS lock** on
  `config_dir()/questions/<id>.lock` — per machine, never in the plan — so two answers given
  on one machine cannot both land. A person types a question as `Q-e1f2`: the first four
  characters of the id's random half.
- **A playbook's question is consumed by the pass's owner** — the engine on the machine that
  launched the pass — with the same fetch, check and push, its target the `pass`, `stage` and
  `attempt` rather than a run: still the current gate of a pass not over. Consuming it acts:
  a Spike's approval completes its step, a gate's verdict or a round-cap decision advances
  its pass.
- **Several writers, one after another.** The asker creates the file; the coordinator may
  escalate it; whoever may answer it does, and the verb refuses a second answer. When a merge
  meets two writers anyway: **consumed beats everything** — a competing answer, earlier or
  later, goes into `late` and is shown as a late answer, never applied; **withdrawn beats
  open, escalated and an answer not yet consumed**; answered beats escalated beats open; of
  two answers neither consumed, the launching machine consumes the one its fetch found and
  the other goes into `late`. No timestamp decides anything. An open question never times
  out into an answer.
- Outside `PLAN_ENTRIES` like `ledger/`, so a window never adopts it as an outside change
  and reads it by polling a fingerprint; Save commits it; Move Plan carries it. Absence
  encodes the default, a file this build cannot read is skipped, and there is no migration.

### The `claims` directory

Written by `dplanner claim take|release|end`, the heartbeat and a person's override
(`domain/claims.py`; the git half is `domain/claim_sync.py`). Which work is taken by which
squad — a lease in git, so a person or a worker on another machine sees it at their next pull:

```
<project dir>/claims/
└── 2026-10/                                  the month it was taken
    └── 20261007T100212Z-5a0b7c3d.json        minted as a run id is; shown as C-5a0b
```

```json
{
  "format": 1, "id": "20261007T100212Z-5a0b7c3d", "project": "<id>",
  "callsign": "kettle", "worker": {"machine": "<machine id>", "host": "knut-arch"},
  "steps": ["<step A>", "<step B>"],
  "acquired": {"<step A>": "2026-10-07T10:02:12+00:00", "<step B>": "2026-10-07T10:40:03+00:00"},
  "released": [{"step": "<id>", "at": "…", "by": {"kind": "person", "name": "Knut"}, "why": "blocked"}],
  "started": "2026-10-07T10:02:12+00:00", "heartbeat": "2026-10-07T11:20:40+00:00",
  "lease_minutes": 90, "max_park_hours": 24,
  "supersedes": [{"claim": "20261006T081500Z-77aa01bc", "step": "<step B>"}],
  "ended": {"at": "…", "by": {"kind": "coordinator", "name": "kettle-actual"}, "why": "released"}
}
```

- **One claim per squad**, written by its coordinator; `callsign` is the squad word — the
  first word of a member's callsign, so `claim take --callsign kettle-two` writes `kettle`,
  and a second take by the same squad grows its one live claim. Which member works which step
  is on the *run* (`callsign`, and `claim` naming this file).
- **Ownership is decided from the files, per step** — the one rule every reader applies
  (`claims.holdings`). **`acquired`** is when the claim took each step it holds, so growing
  an old claim never outranks a squad that took the step first: of the live or parked claims
  on a step, the earliest acquisition holds it, and a tie goes to the lower claim id.
  **`supersedes`** names, step by step, the abandoned claim a takeover took a step from, and
  it is final: the superseded claim never holds that step again, even once it renews.
- **Taking is check, write, commit, push.** `claim take` refuses a step another squad's live
  or parked claim holds (naming the holder), takes over a step whose holder is abandoned, and
  publishes. A playbook stage's run launches under whichever claim holds its step then.
  *One machine, as built:* the check is local, under a per-project OS lock on
  `config_dir()/claims/take-<project>.lock`; which squad pushed first across machines is not
  decided yet.
- **Every launch checks ownership, twice.** Both surfaces' one launch (`launch.claim_for`)
  refuses a step another squad holds — a person's Run Agent included — and a run of the
  holding squad (`agent run --callsign kettle-two`) records the claim. The check is made again
  under the step's launch lock just before the run starts (`launch.start_run`), so a release
  or a takeover made while a worktree was prepared starts nothing.
- **A publish never rewrites the person's checkout.** It commits `claims/` alone, by pathspec,
  under the repository's sync lock — the OS lock in the common git directory that the window's
  own Save and sync take too (`core/storage/git.py`'s `sync_lock`) — and pushes. It never
  fetches, rebases or stashes: a push the remote refuses leaves the commit, marks the claim
  `config_dir()/claims/<id>.unpublished`, and the window's next sync carries it. Unpublished,
  a claim still holds on its machine.
- **`heartbeat`** is renewed, only when it is ten minutes old, by every `dplanner` run from
  an agent's shell — for the claims **this machine** holds in its project (`worker.machine`)
  — and once a minute by the supervisor of any of the squad's runs **while a turn is live**:
  a backoff wait or a park renews nothing. A commit carrying only a heartbeat is pushed at
  most every thirty minutes; when this machine last pushed is
  `config_dir()/claims/<id>.pushed`. **Before it renews, a claim stands down** from every
  step it no longer holds — superseded, or acquired first by another squad — so a squad that
  lost a step hands it back instead of renewing its way back to it.
- **A claim whose heartbeat is older than `lease_minutes` (default 90) is abandoned**, by the
  reader's clock — the lease is three pushes long so one failed push, or a little clock
  skew, does not read as death — **unless the squad is parked**: every step it still holds
  waits on a question that is open, escalated, or answered and not yet consumed. Parked work
  is still owned, and its claim stands until the work resumes, is cancelled (the question
  withdrawn, the run fenced or stopped), or the oldest of those parks is `max_park_hours`
  (default 24) old. An abandoned claim is shown as abandoned and deleted by nobody.
- **A step that leaves a squad stops its worker**, however it leaves — a takeover, `claim
  release`, `claim end`, the window's *End Squad Claim*, a person's stopped status — through
  one function (`agent_claims/ownership.py`): every unfinished headless run of the squad on
  that step is fenced, and its supervisor on this machine is signalled; a live turn also
  reads its fence within a second and ends `stopped`. A fenced run counts as over for the
  next launch only once nothing of it runs here: a live supervisor is signalled, and a turn
  that outlived its supervisor — found by its recorded `pid`, `boot` and `pid_started` — has
  its process group ended (SIGTERM, a grace, SIGKILL) first, by the launch and by the
  supervisor `revive` hands the run; a turn that will not end refuses the launch, saying so.
  Ending a claim stops the workers of exactly the steps it held when its locked write ended
  it, and an ended claim never grows again — a take racing the end starts a claim of its own.
- **A person's override releases one step, not the squad.** Only a *person's* stopped status
  releases — a worker reaching ready-for-review does not, since its coordinator verifies and
  merges first. *End Squad Claim* ends the whole claim. Either is the director's act and a
  second writer on purpose; every write re-reads the file under its lock. A release or an
  end takes the step's launch lock when it is free; a launch holding it re-reads ownership
  before it starts.
- **`ended`** is written once: by the coordinator (`released`, `done`), by a person
  (`by.kind: person`), or when the last step leaves `steps`.
- Outside `PLAN_ENTRIES`, polled, committed by Save, carried by Move Plan; absence encodes the
  default, an unreadable file is skipped, no migration. Every change is a read-modify-write
  under an OS lock on `config_dir()/claims/<id>.lock`. It is the record a multiplayer
  coordination service would broadcast, and git stays the authority. *Not built yet — the
  second machine:* deciding which squad pushed first, delivering a fence to the machine that
  runs the turn, and resolving a merge that conflicts on one claim file.

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
`project_editor` — the `canvas` package's id — is another instance: a position
beside each step — `{"x": 40.0, "y": 160.0}`, plus `"w"` and `"h"` only for a card somebody
resized — and the named layouts beside the project (`{"layouts": {"<name>": {"steps":
{"<step id>": [x, y]}}}}`, coordinates as whole-unit floats: a canvas gesture snaps to the
grid, a write never does). **A step in a stack** — a chain the canvas draws as one tall
card — adds `"stack": "<id>"`, an opaque id minted per stack and never a step id; the
*first* member keeps the seat, which is the stack's, and every other member stores none
(`{"stack": "<id>"}`, plus a size if its card was resized), because its seat is derived
from the column. The order is never stored: it is read from the members' `requires` chain
(`docs/architecture/canvas.md`'s *A stack is presentation over a chain*). It is format 3. Format 1
also kept titled rectangles beside the project (`"regions": [...]`) and each layout's rects
for them (`"regions": {"<id>": [x, y, w, h]}`), and regions were retired, so the first
migration drops both on read — a project saved with them opens as it was, minus the
rectangles (`docs/architecture/canvas.md`'s *Regions were retired*). Format 3 is the `stack` key,
and its migration changes nothing: the number moved because a format-2 writer rebuilds the
entry from the seat and the size and so drops the key from any card it moves — the rule
below. As with the library's format 4, no reader checks the stamp, so an older build still
does exactly that: it draws a stack's members where the ambient layout puts them, and a
card it moves leaves its stack, which this build reads as a shorter stack or a broken one
— never a lost step. A step's entry went to 2 and to 3 unchanged. `feature` is
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
every briefing but a landing's) as `modules/step_agent_instruction.md` beside the project, images in the
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
`{"tests": [{"id": "T100", "title": "…", "body": "…", "audiences": ["qa", "technical"]}]}`
beside a step: a *test* belongs to
exactly one step, a step carries several, and each has its own result in a run. The body is
markdown **inside the record** rather than in `modules/testing.md`, because a node holds
exactly one prose document and this is N of them. The trade is explicit: a body edit diffs as one changed line
rather than line by line, which is bearable while test bodies are a few lines each. Images
are the exception and go where a description's do, in the step's file area. Ids are minted
per *project* and meant to be read — `T100, T101, …`, and `R100, R101, …` for runs — so a
run's results are a flat map, an id is quotable in a bug report, and renaming a test never
detaches its history. **`audiences` says who the test is written for** — a closed list
(`qa`, `technical`, `other`), stored in that order however they were named so the bytes do
not depend on the typing, and **absent when nobody has said**, which reads as `other`
everywhere a test is shown. Absence is not migrated into an explicit `other`, because the
two are different claims: `project lint`'s `test.audience` asks for the answer a test at a
time, which is what lets a plan written before audiences existed stay exactly as it is.
That key is why the format is **2**, under the rule below: `write()` rebuilds each record
from its fields, so an older build that edits one test drops the audiences of every test on
that step. Worth knowing what the stamp does and does not buy — `migrated()` only makes the
*migration pass* leave newer data alone; nothing refuses an older build's write.

**`category` and `sort_key` are the same idea with an open vocabulary, and the category's
list lives beside the project.** A test carries `"category": "Import"` — the category's *words*, not a minted id,
because there is no closed list to mint against and because a diff naming the group a test
moved to is worth more than a stable key nobody can type. Absent is unfiled, which reads as
`Uncategorised` everywhere and which `project lint`'s `test.category` asks about once the
project has any categories at all. The catalogue itself is the project's entry under the
same module id: `{"categories": [{"name": "Import", "icon": "layers"}], "runs": […]}`, in
the order they were written, `icon` a glyph key from `categories.ICONS` and absent when the
category wears none. It is stored rather than derived from the tests precisely so it can be
laid out *before* them; what is **in** a category is never stored, and a category a test
names that the catalogue does not is still real — it is simply one nobody wrote down, which
is how a typo stays visible. **Two writers share that one project entry**, so neither may
hand `set_module_data` a dict built from its own half: `aspect.project_entry()` is the one
composer, and `runs.write()` and `categories.write_catalog()` both go through it. Renaming
a category rewrites every test that carries it — that is the price the words-not-an-id
choice pays, paid in one undoable step by `test-category set --rename` and by the category
editor's Save. **`sort_key` is the second, ergonomic axis** — `"sort_key": "Customer list
view"` — which orders a test *inside* its category and has no catalogue at all, because it
is not a vocabulary anybody maintains: absent is no key, and a key nothing else names is
simply a group of one. All three keys are why the format is **3**; they arrived together
and none has been on anybody's disk without the others, so one pass-through migration
records what two would have.

**An aspect toggled on with nothing to say yet is a marker entry.** A step's "on/off" for a
toggleable aspect is the presence of its `module_data` entry, and several aspects need a
shape for "on, but empty": `step_ticket` writes `{"on": true}` when the Type toggle enables
it before any field is filled (a filled ticket's entry replaces the marker), `step_check`
writes `{"on": true}` and never anything else — what it *gathers* is the graph's answer, not
a stored list — `step_start` writes `{"on": true}` on the one step the plan begins from and
never anything else, since what it changes is where the walks stop, not anything the step
holds — and `step_agent_instruction` writes `{"on": true}` — plus `"separate": true` when
the step opts into an instruction distinct from its description, and `"worktree": false`
when its agent is to work in the checkout itself rather than a fresh worktree (absence is
on), and `"workplace"` naming a code location other than the primary — beside the step whose
prose file may not exist at all. Those four are format 1 of their own `ModuleDataFormat`s; a
step carrying only the old prose file still reads as agent-on, so no migration ships with
them. A feature's marker is one more, in its own format: `{"on": true}` with no `cites` is a
feature that was read from no specification, which is the whole answer — and it is what the
retired `step_feature` module wrote, so that marker needs nothing done to it beyond its
stamp.

**What a step's agent runs consumed is not on the step.** It is the project's usage ledger
(*The `ledger` directory*, below). `agent_usage` — the step aspect that kept rows of
`{"harness", "session", "input", "output", "details", "ended", "prompt_chars"}` before the
ledger — survives only as an absorption: each open moves what is left on a step into a
`legacy` ledger record named by its session, and removes the entry. The rule its history
taught is still worth stating, because `progress_history` below looks like a precedent for
a bump: **bump when an older writer would destroy the new key, not when it merely would
not write it.** The run's *state* stays in `step_agent_run` and is cleared at exit.

**`step_agent_run` is where a launched agent stands**, absent when none is:
`{"state": "launched", "launched": "<ISO stamp>"}`, format 1, `state` one of `launched`,
`working`, `plan-for-review`, `pending-approval` and `needs-input`, cleared by the agent at
the end or by the window when the shell ends. A launch into a session that starts in plan
mode adds `"plans_first": true`: such a session writes nothing until its plan is approved,
so the launch says that it waits on a person, and the agent's first state of its own
rebuilds the entry without it. No bump: an older build reads the state and ignores the key,
and its next write drops it, which only takes the step off *Waits for you*.

**`step_wait` makes a step a wait**: `{"until": "2026-11-04"}`, the first day what requires
it may start, or `{"days": 3.0}`, that many working days from when it is reached — one key or
the other, format 1, a count written as a float. A wait is no work: no worker takes it, it
has no status, and every tally leaves it out, while the graph treats it as any other step.
The schedule reads it through the root's `wait_of` as the domain's `Wait`.

**`auto_progress` is retired** (2026-10-07, with no successor; *Retiring a module*). It
was `{"from": ["<step id>", …]}`, format 1, on a step that waited: the links it took work
across from review on. A plan may still carry the file, and this build leaves it untouched.

**`branch_cut` makes a step the cut a feature branch starts from**: `{"branch":
"feature/stacks"}`, format 1 — a name git accepts, since it reaches a script verbatim. A cut
is no work: no worker takes it, it has no status of its own and it reads done once what it
waits on is done. **`branch_land` makes an agent step the landing that merges it back**:
`{"cut": "<step id>"}`, format 1. The pairing counts only while that cut is upstream of the
landing, so an edge verb never rewrites it and a stale id is inert; a paste renames the id
when the cut is copied along and drops the entry otherwise. What is on the branch is never
stored: it is everything after the cut and before the landing (`domain/branches.py`).

**`github` records where a step's work lands**: the branch and the PR, and the PR's last-seen
state, title, URL and — since format 2 — `pr_base`, the branch it merges into. Format 2 is an
identity migration: a format-1 entry has no base, and a merged PR is never asked again, so it
stays unknown; the bump is so an older build, whose `write` rebuilds the entry field by field,
knows it would drop the key.

**`step_playbook` names the playbook a step runs**, on a step and on its project under one
id. On a step: `{"playbook": "plan-execute-review-other", "rounds": 3.0, "reviewer":
"codex"}`, format 1 — a built-in preset's id (`modules/step_playbook/presets.py`), then the
two overrides, each written only when it differs from its default (two rounds; another
vendor's agent), the cap as a float from 1 to 5. On the project: `{"default": "execute",
"landing": "spike"}`, format 1 — what a step that never chose runs, and what a branch landing
that never chose runs — each written only when it differs from its default (no playbook, so
Run Agent; *Land*). Absence is the default throughout, so a changed default reaches
every step that never chose; an id this build does not know reads as absent.
`docs/architecture/playbooks.md`'s *A step names its playbook* has the resolution order.

**`step_review` and `review_rounds` are retired** (2026-10-07, with no successor; *Retiring
a module*). `step_review` made a step a review of the step it `requires`: `{"on": true,
"agent": "codex", "lenses": ["architecture"], "max_rounds": 2}`, format 1, every key but `on`
written only when it differed from its default. `review_rounds` was the conversation that
review held, on itself: `{"rounds": [{"with": "<step id>", "opened": "<stamp>", "findings":
"…", "posted": "<stamp>", "taken": "<stamp>", "reply": "…", "replied": "<stamp>",
"approved": "<stamp>", "escalated": "<stamp>", "note": "…", …}]}`, format 1. A plan may still
carry either file, and this build leaves them untouched; a step that carried `step_review`
reads as the agent step it also was.

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
report's assumptions are the second instance: `modules/schedule.json` beside the
project (format 2), `{"efficiency": 0.5, "palette": "mako", "team": [2, 3],
"efficiency_was": {"until": "2026-09-22", "efficiency": 0.6}}` — the focus factor, the
colour map and the team the calendar is dated for, each absent on its default, and the
focus before its last change with the day the new one began (the day after it was
changed; a second change that day keeps the day's first) — an assumption about the team,
not a fact about a step. The past focus is kept because work under way ran at it; no other
past budget is stored, since a forecast looks forward and each past day's is in its row. The same module writes `{"start":
"2026-10-05", "color": "#e0602c"}` beside a *milestone* step: the day its stretch of work
begins instead of the day the previous one lands, and a colour chosen over the dealt one
— assumptions again, and the landing date itself is never written. The same package
writes a **second id** beside the project, `modules/progress_history.json` (format 3):
`{"days": [{"day": "2026-09-05", "stretches": [{"milestone": "<step id>", "steps": 8,
"done": 3, "days": 11.0, "done_days": 4.5, "changed": 2, "start": "2026-09-07", "finish":
"2026-10-12", "landings": [{"date": "2026-09-09", "steps": 2, "days": 3.0}, …]}]}],
"saved": [{"title": "Kickoff review", "note": "What we thought on day one", "day":
"2026-09-05", "stretches": […]}]}` — under `days`, one row per day on which the plan's
progress or its promise changed or a status was set, the stretches in the order the
sequence ran them that day, each `start` the day its work began — the plan's own day
while the plan held, the first day any of it was done or started once it re-dated itself
(no `milestone` key for the work after the last one, no
`finish` for a stretch nothing dated, no `landings` for one with nothing to land, no
`changed` for one none of whose steps' statuses changed that day — the count that tells a
day of work from a quiet one when nothing landed); under `saved`, the
snapshots somebody kept on purpose, the same row with the `title` it is found by and a
`note` when one was given (no `saved` list without one; a row there without a title is
not a saved snapshot and reads as absent). A saved snapshot is never replaced by a later
change, and an automatic day never carries a title. The landings are what the simulation
expected to land on each date, so the plan as it stood that day is drawn exactly from
the row. It is the one derived-looking thing that is stored, because the past cannot be
recomputed: the chart of the plan against what became of it needs where the plan stood
and what it promised on earlier days. The bump to format 2 exists for the `saved` key,
and to format 3 for `changed`: an older build's writer rebuilds every row, so the number
is how it knows it would drop what it cannot write.
**A status remembers two days** for the same reason: `step_status.json` (format 2) is
`{"status": "done", "since": "2026-09-18", "started": "2026-09-14"}` — the day the status
last changed, and the day the step first went into a worked status (in progress, ready for
review, ready to merge) — stamped by the aspect's `write`, so the window, `dplanner status
set` and an agent's launch all record them, and restored by undo with the rest of the
entry. The word is one of `pending`, `in-progress`, `ready-for-review`, `ready-to-merge`,
`done`, `blocked`; the two in the middle came later **with no format bump**, because a
build that does not know a word reads it as *unknown* and leaves the entry as it is. Unknown
holds the step — never ready, never launched, listed under Blocked — since reading it as
pending would start work another build may already have running. Pending is still absence, but a step set back
to pending keeps its days: an entry with no `status` key, which reads as pending. A copy
keeps the status and forgets the days, which were the original's. An older entry has no
days, and every reader takes that as "not said", never as today.
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
it replaces, the label one of the closed list in `modules/notes/aspect.py`. It absorbed two
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
`planning/estimate.py`, which is the reference for it, and
`modules/canvas/layouts/positions.py`, which owes it for a coordinate.

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

`planning/estimate.py` is the worked example: `step_estimation` became `estimation`
when it grew a project's start date, and the rename cost no project-format migration and no
import. `planning/milestone.py` is the second: `step_release` became
`step_milestone` when *release* turned out to be the wrong word for a thing that collects
features. `planning/feature.py` is the third: `step_feature` became `feature` when a
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
  `planning/feature_migrate.py` is the second, and it adds three things the next one will
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
- **A module with no successor leaves its data where it is.** Nothing declares the retired
  id, so its files are *data nobody declares* (`core/module_data.py`) and round-trip
  untouched — an older build opening the plan still reads them — and no successor is coupled
  to a dead module just to delete them. What keeps that safe is that the id is never used
  again: it leaves `STORED_IDS` for `RETIRED_IDS` in `tests/test_architecture.py`, which no
  module may declare, since a new module under the old name would adopt files it never
  wrote. `auto_progress` is the worked example (2026-10-07); a review step's `step_review`
  and `review_rounds` went the same way.
