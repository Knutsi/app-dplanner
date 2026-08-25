DPlanner plans a **product**: one codebase, its repository, and the work planned against it.

```
Product  ── the system level: a name, a repository URL, a checkout
└── Project  ── a unit of work with a beginning and an end
    └── Step  ── a node in that project's graph
```

Steps are a **graph**, not a list. An edge lives on the step that waits: `requires` orders
the graph and refuses cycles, `relates` is a plain link. Steps also carry **aspects** — an
estimate, a ticket, a description — which the graph itself knows nothing about. Run
`dplanner aspect list` to see which exist in this build.

## How to work

The user is planning something with you, and the plan is a shared artefact: it is plain
files in a folder, usually in version control, and a DPlanner window may be open on it while
you work. So:

- **Read before writing.** `dplanner project list`, then `dplanner project show <project>`.
  Say what you found and what you propose before you change it.
- **Make small, named changes.** One `step add` per step, one `step link` per dependency.
  Each is a separate line in the diff and a separate thing the user can disagree with.
- **Do not invent structure the user did not ask for.** A plan with twenty imagined steps is
  harder to correct than an empty one.

## Importing a specification

You read the document — a PDF, a wiki page, a thread. DPlanner does not parse it, because
you have already understood it better than a parser would. Turn what you read into the shape
`dplanner project export` writes, and pipe it in:

```bash
dplanner project export <existing> | head -40   # to see the shape
cat plan.json | dplanner project import
```

Prefer building the project up with `project create` and `step add` when there are only a
few steps: the user sees each one arrive and can stop you. Use `import` for something large
that you have already agreed on.

## Conventions

- **`--json` on any command** gives machine-readable output. It works before or after the
  verb.
- **Names or ids.** Anywhere a project or step is named you may use its id, its folder name,
  or a unique part of its title. An ambiguous name is refused and the message lists the ids —
  use one of those rather than guessing.
- **Exit 1 with one line on stderr** means something you can fix. A traceback means a bug in
  DPlanner; report it rather than working around it.
- **Nothing is written when a command fails.** A run is a transaction.
- **Someone else may be writing too.** If a command says the workspace changed on disk, a
  window or another run wrote to it. Run the command again — you will be working from what
  is actually there.
