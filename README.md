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
graph editor and the order view are in place and tested. Fifteen aspects ship — estimate,
ticket, description, agent instruction, agent run, status, milestone, feature, handoff,
GitHub refs,
spec figures, tests, checks and the two documentation ones — each with verbs in the CLI and most with an editor in the step panel
(`dplanner aspect list` is the authoritative roll call). Estimation runs over the graph: a project start date and
the estimates give every step a running total and a date, in the order table and in
`dplanner schedule show`. Progression reads the same graph with the statuses in hand:
the execution board and `dplanner progression show` say what can be launched right now.
Tests are what a step must keep passing once it is done: a step carries several, a *check*
step gathers every test it waits on, and a *test run* records what each one did. Every
image and file a project carries is browsable in one place — the Assets tab and
`dplanner asset` list what exists, who uses each, and what a sweep may safely remove —
and any prose editor can reuse one with Insert from Assets….

## Running

```bash
uv sync
uv run dplanner                                  # your library; created empty on first run
uv run dplanner --library ~/plans/library.json   # another library, in its own instance
```

The library file lists your projects and lives per user (`$DPLANNER_LIBRARY` also names
one). *File ▸ New Project* creates a project folder inside a git repository — offering
`git init` when there is none — and *Open Project* adds an existing one; both update the
library live. *New/Open Project Library* starts a separate instance.

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
repository root with the step's briefing — the agent and the terminal are both a dropdown
of known choices in *Settings ▸ Agent* (Claude Code, Codex, OpenCode; Ghostty, iTerm,
Terminal, Windows Terminal, kitty and the rest, marked when not installed). The step wears
a chip and a marching ring while the shell runs, the chip follows what the agent reports
(`dplanner agent-state set … needs-input` when it has a question), and the ring goes when
the shell ends — finished, failed or closed, which the status bar says. *View ▸ Agents…*
lists every run this window launched; *Step ▸ Show Agent Terminal* brings its window back.

**Both writers may be live.** An agent can work while a window is open on the same folder:
the window reloads when it owes nothing, and neither side ever overwrites a file it has not
seen. See `FORMAT.md`.

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
├── menus.py               the menu bar's shape, including the Project menu
├── app.py                 bootstrap: QApplication, the session, the first open
├── entry.py               the one `dplanner` command: a window, or a verb
├── scripts/measure_edit_cost.py   what an edit costs the GUI thread, measured headless through the journal
├── scripts/gc_catalog.py          a pytest plugin listing each test's Qt garbage in the collector's order
│
├── core/                  ── from the template. Qt-free, application-independent.
│   ├── storage/             three providers behind one protocol: folder, git, GitHub
│   ├── repository.py        what the framework knows about the model, and no more
│   ├── formats.py           the format-migration engine
│   ├── module_data.py       per-module JSON, its versions and takeovers
│   ├── png.py               RGB buffer → PNG bytes, stdlib only, deterministic
│   ├── telemetry.py         the journal both surfaces write: spans, a ring, a JSON-lines file

│   ├── signals.py  fsio.py  text_diff.py
│
├── domain/                ── the planner itself. Qt-free.
│   ├── model.py             Library, Project, Step: the graph, its edges, its aspects
│   ├── store.py             the on-disk format above, one provider per project, the stale-write guard
│   ├── library_file.py      the per-user library file: which projects exist
│   ├── aspects.py           what an aspect is: id, label, summary, data format
│   ├── ordering.py          what order a project can be done in, and what can start now
│   ├── scope.py             what a collector gathers: the cone, truncated at the next one
│   ├── schedule.py          the same walk carrying estimates: running totals and dates
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
│   ├── lookup.py            an id, a folder name, or part of a title
│   ├── aspects.py           `aspect list`
│   ├── assets.py            `<noun> attach`/`assets` — the per-aspect pair — and `asset list`/`uses`/`prune` over every module's areas
│   ├── lint.py              `lint` — every module's checks over the library, one report
│   ├── scopes.py            `scope show` — what a check, feature or milestone gathers
│   ├── authoring.py         `step add` — one verb, each module contributing its flags
│   ├── telemetry.py         `telemetry show|path|clear` — the journal, read back
│   └── skill.py             the agent skill, generated from the registry

│
├── framework/             ── from the template, and evolved here. The Qt machinery.
│   ├── panels.py            the window's left/right/bottom areas, and what modules anchor there
│   ├── index_panel.py       the index tree: folders from whoever registered them
│   ├── inspector.py         what a module registers to appear in a detail panel
│   ├── aspect_bar.py        one submenu's toggles as a bar — templates worded left, every toggle glyphed right, » overflow
│   ├── aspect_toggle.py     the Type toggle an aspect module registers, declared once: shelve off, restore on
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
│   ├── library/             membership: File ▸ New/Open Project and New/Open Project Library
│   ├── projects/            the Projects folder in the index, and the project verbs
│   ├── project_editor/      a project in a tab: the canvas, its modes (connect, lasso, regions, resize) and renderers,
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
│   ├── step_agent_instruction/   … this one also holds the project's standing instruction
│   │                             and assembles and launches Run Agent (`launcher.py`: the
│   │                             agent and terminal preset tables, the reporting wrapper script)
│   ├── step_agent_run/      where a launched agent stands — stamped at launch, moved by
│   │                        `dplanner agent-state`, cleared when the shell ends (`runs.py`
│   │                        reads the wrapper's report; `terminal.py` finds the window again;
│   │                        the status-bar button and the Agents browser are `view.py`)
│   ├── step_status/         where a step stands — a Status submenu, no tab
│   ├── step_milestone/      the steps that mark a milestone — the Milestone tab and the Type ▸ Milestone toggle
│   ├── feature/             the project's feature catalogue (catalogue.py) and the step that
│   │                        realises each: the Features panel and its drag onto the canvas, the
│   │                        Feature tab, the Type ▸ Feature toggle, `dplanner feature`
│   ├── step_check/          a step that gathers every test it waits on — the Type ▸ Check toggle
│   ├── testing/             what a step must keep passing: the tests it carries, the runs over
│   │                        them, the project's Tests tab and the library-wide roll call
│   ├── step_handoff/        what a step passes forward, and who inherits it
│   ├── github/              the branch and PR a step lands in: refs, pickers, PR-state refresh, the missing-gh notice
│   │
│   ├── step_order/          the sorted table of steps, and `dplanner order show`
│   ├── progression/         the execution board — what can be launched now — and `dplanner progression show`
│   ├── time_estimates/      the staffing matrix, the milestones in sequence and the calendar they date — `dplanner schedule matrix`, `schedule palette`, `schedule milestone`
│   ├── spec/                spec documents beside a project, their figures, and the project's
│   │                        topology — `dplanner spec`, `dplanner topology` (pdf.py: text layers
│   │                        and page rendering; editor.py: the in-app markdown editor)
│   ├── project_assets/      every asset a project carries and what uses each — the Assets
│   │                        tab, the pool, display titles, and `dplanner asset`
│   ├── library_watch/       taking what something else wrote in place; asking when it collides with an unsaved edit
│   ├── agent_skill/         the skill dialog, and the install that puts dplanner on PATH
│   ├── reopen_tabs/         the tabs this library had last time, and the switch for it
│   ├── appshell/  sync/  settings/  taskcenter/  debug/
│   └── llm/  llm_openai/  llm_anthropic/
│
└── theme/                 22 themes, the palette, a chrome-only stylesheet, the glyphs, and tones.py —
                           the semantic colours a node body and a kind button share
```

## Where it came from

Generated from `app-framework`'s template; `.appframe` records which commit. Nothing depends
on that repo at runtime — the code here is complete and editable — but
`git -C app-framework diff <revision> -- template/` will show what has changed upstream
since the fork. `CLAUDE.md` lists the places DPlanner deliberately changed the framework,
each of which is a candidate to carry back.
