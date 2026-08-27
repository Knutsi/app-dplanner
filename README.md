# DPlanner

A development planner: a **product** — one codebase, its repository, and the work planned
against it — kept as plain files on disk, so the plan can live in version control next to
whatever it is planning. Built on
[app-framework](https://github.com/Knutsi/app-framework) — PySide6 (Qt 6, LGPL), managed
with uv, running on Linux and macOS.

It has two front doors, and they are equals: a desktop window, and a `dplanner` command that
any coding agent can drive.

## What a plan is

```
Product  ── the system level: a name, a repository URL, a checkout. One per window.
└── Project  ── a unit of work with a beginning and an end
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
graph editor and the order view are in place and tested. Four aspects ship — estimate,
ticket, description, agent instruction — each with a tab in the step panel and verbs in the
CLI. Estimation runs over the graph: a project start date and the estimates give every step
a running total and a date, in the order table and in `dplanner schedule show`. Reports
beyond that one are not written.

## Running

```bash
uv sync
uv run dplanner                                  # last-opened, or the Open dialog
uv run dplanner --workspace ~/Products/widget    # a specific product; created if empty
```

A product can also be named by scheme: `file:~/path` forces a plain folder, `git:~/path`
requires a git checkout, and `github:owner/repo` clones on first open. Whichever you use, the
application adapts: against a plain folder there is no Save action at all, because there
would be nothing for it to do.

## Working with an agent

```bash
uv run dplanner skill install          # ~/.claude/skills/dplanner/
uv run dplanner skill install --project   # ./.claude/skills/dplanner/, so it travels
```

The skill is **generated from the command registry**, so it cannot describe a command that
does not exist; `dplanner skill status` says whether the installed copy matches the build,
and *Tools ▸ Install Agent Skill…* does the same from the window.

Commands find the product by walking up from the working directory for `product.json`, so an
agent already sitting in the checkout needs no configuration. Everything takes `--json`.

```bash
dplanner project list
dplanner project create "Search rewrite" --summary "Replace the index"
dplanner step add search "Read the spec"
dplanner step add search "Draft the model" --after "Read the spec"
dplanner estimate set "Draft the model" --days 5
dplanner describe set "Read the spec" --file notes.md
dplanner agent set "Draft the model" --file how-to.md   # what an agent should know first
dplanner order show search               # every step, numbered, in dependency order
dplanner order show search --ready       # just what can be started right now
dplanner schedule start search --date 2026-09-01
dplanner schedule show search            # the same order, with running totals and dates
dplanner project export search > plan.json   # and `import` reads the same shape back
```

**Both writers may be live.** An agent can work while a window is open on the same folder:
the window reloads when it owes nothing, and neither side ever overwrites a file it has not
seen. See `FORMAT.md`.

## On disk

```
widget/
├── product.json               id, name, repository, checkout, format, children
├── modules/
└── projects/
    └── search-rewrite/
        ├── project.json       id, title, summary, children
        └── steps/
            └── read-the-spec/
                ├── step.json  id, title, edges: {"requires": [ids]}
                └── modules/
                    ├── estimation.json         a module's data
                    ├── step_description.md     a module's prose
                    └── step_description/       a module's files
```

Ordering lives in the parent's `children` list, folder names are frozen at creation, and
absent means default — so a diff shows exactly the steps whose plan actually changed. See
`FORMAT.md`.

## Development

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q   # tests (always prefix the platform)
uv run ruff check                            # lint
uv run mypy                                  # strict type checking, whole tree
```

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
│
├── core/                  ── from the template. Qt-free, application-independent.
│   ├── storage/             three providers behind one protocol: folder, git, GitHub
│   ├── repository.py        what the framework knows about the model, and no more
│   ├── formats.py           the format-migration engine
│   ├── module_data.py       per-module JSON, its versions and takeovers
│   ├── signals.py  fsio.py  text_diff.py
│
├── domain/                ── the planner itself. Qt-free.
│   ├── model.py             Product, Project, Step: the graph, its edges, its aspects
│   ├── store.py             the on-disk format above, and the stale-write guard
│   ├── aspects.py           what an aspect is: id, label, summary, data format
│   ├── ordering.py          what order a project can be done in, and what can start now
│   ├── commands.py          undoable changes — the vocabulary the GUI and CLI share
│   ├── fields.py            bindable prose, keyed by the module that owns it
│   ├── migrations.py        the format's version history — append only
│   └── seed.py              what a brand-new workspace contains
│
├── cli/                   ── the headless surface. Qt-free.
│   ├── command.py           CliCommand, CliContext, CliRegistry
│   ├── workspace.py         finding, opening, migrating and flushing a product
│   ├── main.py              the argparse tree, built from the registry
│   ├── lookup.py            an id, a folder name, or part of a title
│   ├── aspects.py           `aspect list`
│   └── skill.py             the agent skill, generated from the registry
│
├── framework/             ── from the template, and evolved here. The Qt machinery.
│   ├── panels.py            the window's left/right/bottom areas, and what modules anchor there
│   ├── index_panel.py       the index tree: folders from whoever registered them
│   ├── inspector.py         what a module registers to appear in a detail panel
│   ├── prose_section.py     a panel section over one document, bound to the undo stack
│   ├── window_watch.py      noticing that another writer changed the workspace
│   └── …                    registries, actions, tabs, undo, autosave, tasks, LLM
│
├── modules/
│   ├── __init__.py          THE COMPOSITION ROOT — read this to know the application
│   ├── product/             the product's identity: name, repository, checkout
│   ├── projects/            the Projects folder in the index, and the project verbs
│   ├── project_editor/      a project in a tab: the graph canvas, its modes, toolbar and map
│   │                        (its panel also hosts the modules' project-level cards)
│   ├── project_repo/        which repo and checkout a project works against (overrides the product's)
│   ├── step_properties/     THE step detail panel — one in the window, following the context
│   ├── estimation/          estimates: the editor, the bulk Estimates tab, the schedule
│   ├── step_ticket/         ── the other step aspects: data, editor and verbs each
│   ├── step_description/
│   ├── step_agent_instruction/   … this one also holds the project's standing instruction
│   │                             and assembles and launches Run Agent
│   ├── step_status/         where a step stands — a Status submenu, no tab
│   ├── step_release/        the steps that mark a release point
│   ├── step_handoff/        what a step passes forward, and who inherits it
│   ├── github/              the branch and PR a step lands in: refs, pickers, PR-state refresh
│   ├── step_order/          the sorted table of steps, and `dplanner order show`
│   ├── spec/                spec documents beside a project, their requirements, `dplanner spec`
│   ├── workspace_watch/     reloading when something else writes to the workspace
│   ├── agent_skill/         installing the generated skill from the window
│   ├── appshell/  workspaces/  sync/  settings/  taskcenter/  debug/
│   └── llm/  llm_openai/  llm_anthropic/
│
└── theme/                 22 themes, the palette, and a chrome-only stylesheet
```

## Where it came from

Generated from `app-framework`'s template; `.appframe` records which commit. Nothing depends
on that repo at runtime — the code here is complete and editable — but
`git -C app-framework diff <revision> -- template/` will show what has changed upstream
since the fork. `CLAUDE.md` lists the places DPlanner deliberately changed the framework,
each of which is a candidate to carry back.
