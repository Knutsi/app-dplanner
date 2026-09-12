# DPlanner

A development planner: your **projects**, each one a folder of plain files inside its own
git repository, so every plan lives in version control next to the code it plans. Built on
[app-framework](https://github.com/Knutsi/app-framework) — PySide6 (Qt 6, LGPL), managed
with uv, running on Linux and macOS.

It has two front doors, and they are equals: a desktop window, and a `dplanner` command that
any coding agent can drive.

## What a plan is

```
Library  ── the account level: a per-user file listing project directories. One per window.
└── Project  ── a unit of work with a beginning and an end, in its own repository
    └── Step  ── a node in that project's graph
```

**Steps are a graph, not a list.** An edge lives on the step that waits: `requires` orders
the graph and refuses cycles, `relates` is a plain link. Deleting a step deliberately does
*not* rewrite anybody else's edges, because undo has to restore the graph exactly.

**Aspects are what the graph does not know.** An estimate, a ticket, a description, an
instruction for a coding agent: none of them are fields on a step. Each is a module's namespaced entry beside the step — JSON, prose
or files — versioned by the module that writes it, so a feature arrives without the model
learning anything about it. `dplanner aspect list` says which exist in a build.

## Status

Early, and honest about it. The model, the storage layer, the index tree, the whole CLI, the
graph editor and the order view are in place and tested. Fourteen aspects ship — estimate,
ticket, description, agent instruction, agent run, status, milestone, feature, GitHub refs,
spec figures, tests, checks and the two documentation ones — each with verbs in the CLI and most with an editor in the step panel
(`dplanner aspect list` is the authoritative roll call). Estimation runs over the graph: a project start date and
the estimates give every step a running total and a date, in the order table and in
`dplanner schedule show`. Progression reads the same graph with the statuses in hand:
the execution board and `dplanner progression show` say what can be launched right now.
Tests are what a step must keep passing once it is done: a step carries several, a *check*
step gathers every test it waits on, and a *test run* records what each one did. Every
image and file a project carries is browsable in one place — the Assets tab and
`dplanner asset` list what exists, who uses each, and what a sweep may safely remove —
and any prose editor can reuse one with Insert from Assets…. The Time Estimates tab
also says how far each milestone has come against the plan as it stood at the start —
the plan then, the plan now with the change between them, and what actually landed — and
`dplanner progress show` prints the same, with the steps and estimates that moved it.
What a project learns along the way — decisions, handoffs, spec changes, what was
deferred — is one labelled log beside it (`dplanner note add`, the project panel's Notes
card), and every agent's briefing carries an index of the notes that reach its step, with
the ones addressed to it in full.

## Running

```bash
uv sync
uv run dplanner window                                  # your library; created empty on first run
uv run dpw                                              # the same, with the word typed for you
uv run dplanner window --library ~/plans/library.json   # another library, in its own instance
uv run dplanner --help                                  # the CLI; a bare `dplanner` prints this too
```

To have it on hand outside the checkout, `uv tool install --editable .` puts `dplanner`
and `dpw` on PATH (*Tools ▸ Install dplanner Command…* runs the same), and `dplanner
desktop install` adds DPlanner to the applications menu — a `.desktop` entry on Linux, an
app bundle in `~/Applications` on macOS, a Start Menu shortcut on Windows — opening that
`dpw`; the dialog writes it in the same go. `dplanner desktop status` says whether the
launcher still opens this build, and `desktop uninstall` takes it out.

The library file lists your projects and lives per user (`$DPLANNER_LIBRARY` also names
one). A plan lives in a **plan repository** — a git repository holding several projects,
listed in its `.dplanner` index — and records the **code repository** it is about, so an
agent works in the code and every `dplanner` call reaches the plan. *File ▸ New Project…*
starts one in a plan repository you pick, initialise or clone; *Open Projects…* browses a
plan repository and adds the projects you work on; *Project ▸ Settings…* is one column per
repository — its log and open pull requests over what the repository is and where it is on
this machine, with a ⋯ menu of everything you can do to either — and *Move Plan…* moves a
plan into a plan repository, out of the code it was kept in or on from one picked wrongly.
*New/Open Project Library* starts a separate instance.

## Working with an agent

```bash
uv run dplanner skill install          # ~/.claude/skills/dplanner/
uv run dplanner skill install --repo   # ./.claude/skills/dplanner/, so it travels
```

The skill is **generated from the command registry**, so it cannot describe a command that
does not exist; `dplanner skill status` says whether the installed copy matches the build,
and *Tools ▸ Install Agent Skill…* does the same from the window.

Commands find the current project by walking up from the working directory for
`project.dproj`, so an agent already sitting in the repository needs no configuration. A
plan kept in a subdirectory the walk would never enter is reachable through a one-line
`.dplanner` pointer file at the repository root — see `FORMAT.md`. Everything takes
`--json`, `--library` and `--project`.

```bash
dplanner library list
dplanner project create "Search rewrite" --dir ~/code/widget/planning --summary "Replace the index"
dplanner step add search "Read the spec"
dplanner step add search "Draft the model" --after "Read the spec"
dplanner estimate set "Draft the model" --days 5
dplanner describe set "Read the spec" --file notes.md
dplanner agent set "Draft the model" --file how-to.md   # what an agent should know first
dplanner test add "Draft the model" "Rejects an empty query" --text "1. POST /q with ''
2. 400, and no row is written."
dplanner check set "Ship the beta"       # gathers every test behind it
dplanner test-run start --scope "Ship the beta" --label "Pre-ship 3"
dplanner test-run mark T100 failed --note "still 500s"
dplanner docs set "Draft the model" --file notes.md   # what this step documents
dplanner docs status                     # which features and releases need writing up
dplanner docs collect "Ship the beta"    # everything it documents, as one document
dplanner order show search               # every step, numbered, in dependency order
dplanner order show search --ready       # just what can be started right now
dplanner schedule start search --date 2026-09-01
dplanner schedule show search            # the same order, with running totals and dates
dplanner project export search > plan.json   # and `import` reads the same shape back
```

**Run Agent is the window's way in.** *Step ▸ Run Agent…* opens a terminal at the
repository root with the step's briefing — through a **launch profile** from *Settings ▸
Agent*: a name over an agent (Claude Code, Codex, OpenCode — each a module that says
what its CLI can do) and a terminal or multiplexer (Ghostty, iTerm, Terminal, Windows
Terminal, kitty, WezTerm and the rest; herdr, zellij and tmux to land several agents
side by side — marked when not installed). The first profile is what *Run Agent…* runs;
*Step ▸ Run Agent With* offers the others. Select several ready steps — on the canvas,
in the progression board — and one gesture launches one agent per step, all through the
profile you pick. The step wears a chip and a marching ring while the shell runs, the
chip follows what the agent reports (`dplanner agent-state set … needs-input` when it has
a question), and the ring goes when the shell ends — finished, failed or closed, which
the status bar says, with the tokens the run consumed once its CLI's record has been read
(`dplanner usage show|list` prints the ledger per step and per project). *View ▸
Agents…* lists every run this window launched, with the command that picks an ended one
up again; *Step ▸ Show Agent Terminal* brings its window or pane back.

**Both writers may be live.** An agent can work while a window is open on the same folder:
the window reloads when it owes nothing, and neither side ever overwrites a file it has not
seen. See `FORMAT.md`.

## Reports

A plan is also a page. *File ▸ Export ▸ Plan Report (HTML)…* writes one self-contained
file — the graph as the window draws it, the order, the time estimates and the progress
chart, every step with everything the modules know about it, and a last section that says
what DPlanner is and how to open the plan — for a sponsor, a product owner or a tester who
has no DPlanner. Click a card, a row or a milestone anywhere on it and every view answers.
*Plan Report (PDF)…* prints the same report; *Plan Tables (Excel)…* writes its tables as a
workbook, beside the Order and Time tabs' CSVs. *Project ▸ Preview Report* opens the page
in the browser.

Every Save also writes the plan repository's site under `reports/` — a page per project and
an index — into the same commit as the plan, so anyone with the repository has the plan as
a website (turn it off under *Settings ▸ Reports*; *Write Now* writes it on demand).

```bash
uv run dplanner report html search --out search.html   # one project's page
uv run dplanner report site                             # the plan repository's site, uncommitted
uv run dplanner report xlsx search --out search.xlsx    # every table as a workbook
uv run dplanner report csv search --table order         # one table, to stdout
```

## On disk

```
<repository>/
└── planning/                  the project directory — any folder in the repo
    ├── project.dproj          id, title, summary, format, children
    ├── modules/
    └── steps/
        └── read-the-spec/
            ├── step.json      id, title, edges: {"requires": [ids]}
            └── modules/
                ├── estimation.json         a module's data
                ├── testing.json            the tests this step keeps
                ├── step_description.md     a module's prose
                ├── docs.md                 what this step documents
                └── step_description/       a module's files
```

The per-user library file (`library.json`) lists project directories and never enters
version control; each project migrates on its own format stamp.

Ordering lives in the parent's `children` list, folder names are frozen at creation, and
absent means default — so a diff shows exactly the steps whose plan actually changed. See
`FORMAT.md`.

## Development

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q   # tests (always prefix the platform)
uv run ruff check                            # lint
uv run mypy                                  # strict type checking, whole tree
```

The suite runs on every core, so the whole thing takes about two minutes; run the whole thing.
`-n0` gives a single-threaded run when a failure needs readable output or a debugger, and
`pytest tests/core tests/domain tests/cli` is the Qt-free layers on their own in under twenty
seconds.

Layering rules are enforced by `tests/test_architecture.py`; the module recipe and the rules
live in `CLAUDE.md`. `ARCHITECTURE.md` explains the shape and why. `DESIGN.md` is the UI
standard, `FORMAT.md` the on-disk one.

## Layout

```
src/dplanner/
├── identity.py            what this application calls itself
├── menus.py               the menu bar's shape: File, Edit, View (the window), Project, Graph (the canvas), Step, Tools
├── app.py                 bootstrap: QApplication, the session, the first open
├── entry.py               the one `dplanner` command: the CLI, or `dplanner window` (`dpw`)
├── assets/                what the application ships: the icon, one PNG per size, read by the window and the launcher alike
├── scripts/measure_edit_cost.py   what an edit costs the GUI thread, measured headless through the journal
├── scripts/gc_catalog.py          a pytest plugin listing each test's Qt garbage in the collector's order
├── scripts/layout_item_double_delete.py   the layout-item double delete built to order, and the finalizer that stops it
├── scripts/render_icon.py         the application icon at every size, from the theme's colours — committed under assets/
│
├── core/                  ── from the template. Qt-free, application-independent.
│   ├── storage/             three providers behind one protocol: folder, git, GitHub
│   ├── repository.py        what the framework knows about the model, and no more
│   ├── formats.py           the format-migration engine
│   ├── module_data.py       per-module JSON, its versions and takeovers
│   ├── png.py               RGB buffer → PNG bytes, stdlib only, deterministic
│   ├── telemetry.py         the journal both surfaces write: spans, a ring, a JSON-lines file

│   ├── anchors.py           where a quoted passage sits in a document: exact, fuzzy or lost, and behind when the text moved on
│   ├── signals.py  fsio.py  text_diff.py
│
├── domain/                ── the planner itself. Qt-free.
│   ├── model.py             Library, Project, Step: the graph, its edges, its aspects — and the
│   │                        per-project step number a key (S7) is made of
│   ├── store.py             the on-disk format above, one provider per project, the stale-write guard
│   ├── library_file.py      the per-user library file: which projects exist
│   ├── aspects.py           what an aspect is: id, label, summary, data format
│   ├── ordering.py          what order a project can be done in, and what can start now
│   ├── scope.py             what a collector gathers: the cone, truncated at the next one
│   ├── schedule.py          the same walk carrying estimates: running totals, dates, and when each
│   │                        step lands in a staffed simulation
│   ├── progression.py       the status-aware frontier: what can be launched right now
│   ├── commands.py          undoable changes — the vocabulary the GUI and CLI share
│   ├── shelf.py             where a turned-off aspect's data waits: turn_off / turn_on, and the migration into it
│   ├── fields.py            bindable prose, keyed by the module that owns it
│   ├── assets.py            attaching files to a module's file area, and listing them
│   ├── migrations.py        the format's version history — append only
│   └── seed.py              what a brand-new library, and a brand-new project, contain
│
├── cli/                   ── the headless surface. Qt-free.
│   ├── command.py           CliCommand, CliContext, CliRegistry
│   ├── discovery.py         finding the library and the current project; opening and flushing
│   ├── main.py              the argparse tree, built from the registry
│   ├── lookup.py            a key (S7 / 7), an id, a folder name, or part of a title
│   ├── aspects.py           `aspect list`
│   ├── desktop.py           `desktop install`/`status`/`uninstall`: the launcher an applications menu opens, one class per platform
│   ├── assets.py            `<noun> attach`/`assets` — the per-aspect pair — and `asset list`/`uses`/`prune` over every module's areas
│   ├── lint.py              `lint` — every module's checks over the library, one report
│   ├── scopes.py            `scope show` — what a check, feature or milestone gathers
│   ├── authoring.py         `step add` — one verb, each module contributing its flags
│   ├── telemetry.py         `telemetry show|path|clear` — the journal, read back
│   ├── report/              the plan as a page for people with no DPlanner: what modules say
│   │                        (parts.py, the vocabulary a module's report.py speaks), assembled
│   │                        (assemble.py), drawn as one HTML file with inline SVG (page.py,
│   │                        drawings.py), as sheets (sheets.py), as a plan repository's site
│   │                        (website.py) — `dplanner report html|site|xlsx|csv|tables`
│   └── skill.py             the agent skill, generated from the registry

│
├── framework/             ── from the template, and evolved here. The Qt machinery.
│   ├── panels.py            the window's left/right/bottom areas, and what modules anchor there
│   ├── index_panel.py       the index tree: folders from whoever registered them
│   ├── inspector.py         what a module registers to appear in a detail panel
│   ├── aspect_bar.py        one submenu's toggles as a bar — templates worded left, every toggle glyphed right, » overflow
│   ├── aspect_toggle.py     the Type toggle an aspect module registers, declared once: shelve off, restore on
│   ├── step_selection.py    which step, or which steps, a verb acts on — one reading for every verb
│   ├── prose_section.py     a panel section over one document, bound to the undo stack
│   ├── prose_edit.py        that section's editor: a pasted file becomes a markdown link
│   ├── mime_files.py        the files a paste or a drop carries — both editors' one answer
│   ├── text_dialog.py       the same document in a big modal editor — a second binding
│   ├── asset_gallery.py     a module's attached files as thumbnails; click to view
│   ├── asset_picker.py      a modal picker over named files — Insert from Assets…'s dialog
│   ├── image_preview.py     the modal lightbox the gallery (and anyone) opens
│   ├── window_watch.py      noticing, and taking in, another writer's changes to the library
│   ├── debounce.py          a coalesced refresh: a burst runs once, and tests run it inline
│   ├── diagnostics.py       the stall watchdog, the failure hooks, the crash log — app.main's
│   └── …                    registries, actions, tabs, undo, autosave, tasks, LLM

│
├── modules/
│   ├── __init__.py          THE COMPOSITION ROOT — read this to know the application
│   ├── library/             which library: File ▸ New/Open Project Library, the title; `library …` verbs
│   ├── projects/            the Projects folder in the index, the project verbs, New Project…, Open
│   │                        Projects…, the Project dialog (a column per repository: log, facts, ⋯ menu),
│   │                        the Repositories card, Move Plan, and the repositories folder clones land in
│   ├── project_editor/      a project in a tab: the canvas, its modes (connect, redirect, lasso, divide, regions, resize) and renderers,
│   │                        sorts, named layouts, and the user's look (look.py: marks, background, snap to grid;
│   │                        ground.py paints the background)
│   │                        (clipboard.py is what a copied step is; clipboard_verbs.py the Edit menu's
│   │                        Cut/Copy/Paste/Duplicate; `dplanner step duplicate` is the same clone)
│   │                        (its panel also hosts the modules' project-level cards)
│   ├── step_properties/     THE step detail panel — one in the window, following the context
│   │                        (its first tab, details.py, stacks whatever registered a Details
│   │                        block, name.py leading it; and `steps.details`: the same panel as
│   │                        the double-click's modal, which New opens on a fresh step)
│   │
│   │   ── the thirteen aspect modules (`dplanner aspect list`); the `step_` prefix is not the
│   │      marker — `estimation`, `github` and `spec` are aspects too, and `step_order` /
│   │      `step_properties` are views of steps, not aspects:
│   ├── estimation/          estimates: the editor, the bulk Estimates tab, the schedule
│   ├── step_ticket/         ── the other step aspects: data, editor and verbs each
│   ├── step_description/
│   ├── step_agent_instruction/   … this one also holds the project's standing instruction,
│   │                             the step's worktree choice, and assembles and launches Run
│   │                             Agent (`launcher.py`: the terminal and multiplexer table,
│   │                             the run name a worktree and branch carry, the wrapper script
│   │                             that prepares the worktree and reports back; `profiles.py`:
│   │                             the named agent-and-terminal pairs Run Agent With offers)
│   ├── agent_claude/        ── one module per agent CLI, each a Qt-free `harness.py`: the
│   ├── agent_codex/            command, how it resumes, the marks it leaves in its shells, and
│   ├── agent_opencode/         a reader of its own records (`domain/agents.py` is the contract)
│   ├── step_agent_run/      where a launched agent stands — stamped at launch, moved by
│   │                        `dplanner agent-state`, cleared when the shell ends (`runs.py`
│   │                        reads the wrapper's report; `terminal.py` finds the window or
│   │                        pane again; the status-bar button and the Agents browser are
│   │                        `view.py`) — and what its runs consumed (`usage.py`, the
│   │                        `agent_usage` aspect; `dplanner usage show|list|record`)
│   ├── step_status/         where a step stands — a Status submenu, no tab
│   ├── step_milestone/      the steps that mark a milestone — the Milestone tab and the Type ▸ Milestone toggle
│   ├── feature/             the project's feature catalogue (catalogue.py: records and the
│   │                        passages each cites) and the step that realises each: the Features
│   │                        panel and its drag onto the canvas, the Feature tab, the Type ▸
│   │                        Feature toggle, `dplanner feature` (cite, uncite, reanchor)
│   ├── step_check/          a step that gathers every test it waits on — the Type ▸ Check toggle
│   ├── testing/             what a step must keep passing: the tests it carries, the runs over
│   │                        them, the project's Tests tab and the library-wide roll call
│   ├── github/              the branch and PR a step lands in: refs, pickers, PR-state refresh, where
│   │                        they stand now (the tab's standing line, `dplanner github show`), the missing-gh notice
│   │
│   ├── step_order/          the sorted table of steps, and `dplanner order show`
│   ├── progression/         the execution board — what can be launched now — and `dplanner progression show`
│   ├── time_estimates/      the staffing matrix, the start dates and milestones in sequence and the calendar
│   │                        they date — `dplanner schedule matrix`, `schedule palette`, `schedule team`,
│   │                        `schedule milestone`; and progress against the plan (progress.py derives it,
│   │                        recorder.py writes the day's history, chart.py draws three plots on one time
│   │                        axis: progress, scope change, milestone shifts) — `dplanner progress show|record`
│   ├── reporting/           the window's half of the report: File ▸ Export's HTML, PDF (paper.py) and Excel,
│   │                        Project ▸ Preview Report, the publisher that writes `reports/` on every Save,
│   │                        Settings ▸ Reports
│   ├── notes/               what a project records along the way — decisions, handoffs, spec changes,
│   │                        deferrals — one labelled log (log.py), what reaches a step and the briefing's
│   │                        index (reach.py), how the two retired modules reach it (migrate.py),
│   │                        `dplanner note`, and the project panel's Notes card
│   ├── spec/                spec documents beside a project, their figures, and the project's
│   │                        topology — `dplanner spec`, `dplanner topology` (pdf.py: text layers
│   │                        and page rendering; editor.py: the in-app markdown editor)
│   ├── coverage/            the spec and what became of it: passages → features → milestones →
│   │                        tests and docs (trace.py, one derived picture), the Coverage tab's
│   │                        four lanes (scene.py), and `dplanner coverage show|spec|review`
│   ├── project_assets/      every asset a project carries and what uses each — the Assets
│   │                        tab, the pool, display titles, and `dplanner asset`
│   ├── library_watch/       taking what something else wrote in place; asking when it collides with an unsaved edit
│   ├── install/             getting DPlanner onto this machine from the window: the agent skill, the `dplanner` command and the desktop launcher
│   ├── reopen_tabs/         the tabs this library had last time, and the switch for it
│   ├── appshell/  sync/  settings/  taskcenter/  debug/
│   └── llm/  llm_openai/  llm_anthropic/
│
└── theme/                 22 themes, the palette, a chrome-only stylesheet, the glyphs, tones.py —
                           the semantic colours a node body and a kind button share — and cards.py,
                           the card primitives the canvas and the coverage view both paint with
```

## Where it came from

Generated from `app-framework`'s template; `.appframe` records which commit. Nothing depends
on that repo at runtime — the code here is complete and editable — but
`git -C app-framework diff <revision> -- template/` will show what has changed upstream
since the fork. `CLAUDE.md` lists the places DPlanner deliberately changed the framework,
each of which is a candidate to carry back.
