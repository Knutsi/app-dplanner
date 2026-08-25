# DPlanner

A desktop project planner: a plan is a tree of tasks kept as plain files on disk, so it can
live in version control next to whatever it is planning. Built on
[app-framework](https://github.com/Knutsi/app-framework) — PySide6 (Qt 6, LGPL), managed
with uv, running on Linux and macOS.

## Status

Early. The model, the storage layer and three features are in place and tested; the views
that make a planner worth using — a board, a timeline, a "what can I start now" list — are
not written yet.

**What a plan is.** A tree of tasks. The root is the project, anything with children reads
as a phase, and a leaf is work. There is deliberately no separate type for each: a phase that
turns out to be one piece of work should not need converting.

Beyond the tree, a task carries the four things a plan is made of — who it is for, when it
runs, how big it is, and what it waits on. Two consequences fall out of that and are worth
knowing before using it:

- **Estimates roll up, and say when they are guessing.** A phase shows the sum of its
  children, plus a count of the leaves that carry no estimate at all — because a total that
  silently treats unestimated work as zero understates the plan.
- **A phase is done when everything under it is.** Derived, never stored, so a phase cannot
  disagree with its contents. Status is editable on leaves only, and the control says why.
- **Dependencies are the one structure that does not follow the tree.** A task in one phase
  routinely waits on a task in another, so they are stored as ids on the task that waits.
  Self-dependencies and cycles are refused at the model, not discovered later.

**What works today**: the plan tree with status and roll-ups, a tab per task with its
description, a properties panel for status, assignee, estimate, dates and dependencies, and
everything the framework brings — undo across the whole application, autosave, workspaces on
a folder or in git or on GitHub, Save as a commit, the settings dialog, background tasks and
the LLM plumbing.

## Running

```bash
uv sync
uv run dplanner                                  # last-opened, or the Open dialog
uv run dplanner --workspace ~/DPlanner/roadmap   # a specific plan; created if empty
```

A plan can also be named by scheme: `file:~/path` forces a plain folder, `git:~/path`
requires a git checkout, and `github:owner/repo` clones on first open. Whichever you use, the
application adapts: against a plain folder there is no Save action at all, because there
would be nothing for it to do.

## On disk

One directory per task, nested exactly like the plan:

```
roadmap/
├── plan.json              the project: id, title, format version, child order
├── description.md
├── discovery/
│   ├── task.json          id, status, assignee, estimate_days, start, due, depends_on
│   ├── description.md     (absent when empty)
│   └── interviews/
│       └── task.json
└── build/
    └── first-slice/
        └── task.json
```

Ordering lives in the parent's `children` list, folder names are frozen at creation, and
absent means default — so a diff shows exactly the tasks whose plan actually changed. See
`FORMAT.md`.

## Development

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q   # tests (always prefix the platform)
uv run ruff check                            # lint
uv run mypy                                  # strict type checking, whole tree
```

Layering rules are enforced by `tests/test_architecture.py`; the module recipe and the rules
live in `CLAUDE.md`. `DESIGN.md` is the UI standard.

## Layout

```
src/dplanner/
├── identity.py            what this application calls itself
├── menus.py               the menu bar's shape, including the Task menu
├── app.py                 bootstrap: QApplication, the session, the first open
│
├── core/                  ── from the template. Qt-free, application-independent.
│   ├── storage/             three providers behind one protocol: folder, git, GitHub
│   ├── repository.py        what the framework knows about the plan, and no more
│   ├── formats.py           the format-migration engine
│   ├── module_data.py       per-module JSON, its versions and takeovers
│   ├── signals.py  fsio.py  text_diff.py
│
├── domain/                ── the planner itself. Qt-free.
│   ├── model.py             Task, Plan: the tree, roll-ups, dependencies
│   ├── store.py             the on-disk format above
│   ├── migrations.py        its version history — append only
│   ├── commands.py          undoable changes, and their merge rules
│   ├── fields.py            bindable text fields
│   └── sample.py            the starter plan a new workspace is seeded with
│
├── framework/             ── from the template. The Qt machinery modules plug into.
│
├── modules/
│   ├── __init__.py          THE COMPOSITION ROOT — read this to know the application
│   ├── plan_tree/           the sidebar: the plan, its statuses and its roll-ups
│   ├── task_editor/         one tab per task, hosting the properties panel
│   ├── task_properties/     status, assignee, estimate, dates, dependencies
│   ├── appshell/  workspaces/  sync/  settings/  taskcenter/  debug/
│   └── llm/  llm_openai/  llm_anthropic/
│
└── theme/                 22 themes, the palette, and a chrome-only stylesheet
```

## Where it came from

Generated from `app-framework`'s template; `.appframe` records which commit. Nothing depends
on that repo at runtime — the code here is complete and editable — but
`git -C app-framework diff <revision> -- template/` will show what has changed upstream since
the fork.
