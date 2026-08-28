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
- **Show the shape.** `dplanner project graph <project>` renders the step graph as a
  Mermaid flowchart — paste it into a PR description or a report instead of describing the
  graph in prose.

## Linking honestly

Link `requires` only when the work truly cannot start before the other step lands. A plan
that is one straight chain is a smell: it usually means dependencies were invented to
impose an order, or the steps are cut too coarse to see what is independent. Independent
steps are what let two agents — or two weeks — run in parallel; `dplanner order show`
groups steps into waves of what can start together, and `project graph` makes the same
shape visible. If the waves are all singletons, revisit the links before adding more steps.

## Working from a specification

A project can carry the documents it answers to — a PDF, a markdown file, plain text —
and the workflow runs from import to steps an agent can execute *in isolation*:

1. **Import it.** `dplanner spec import <project> spec.pdf` stores the document beside the
   project. Importing under the same name again *replaces* it and keeps the previous
   version, which is what makes step 6 possible. Importing a PDF also extracts its text
   layer.
2. **Read it yourself.** `spec show` prints any document — for a PDF it prints the
   extracted text, page by page (`--page N` for one page) — and `spec path` still hands
   you the original file. Read the whole thing before planning; you understand it better
   than any parser.
3. **Mark the requirements.** One `dplanner spec mark <project> <doc> --title … --quote …
   --page N` per named obligation you find. The quote is checked against the document and
   the page is recorded (found automatically when the quote is). Requirements are the
   durable trace of your reading — the next agent starts from them, not from scratch.
4. **Create the steps and link them.** `step add` and `step link` build the graph (see
   *Linking honestly*); `dplanner spec link <step> <requirement>` records *why* each step
   exists.
5. **Author every step before moving on.** A step with only a title is not a plan — the
   agent who picks it up has nothing to execute. For each step: `describe set` (what it
   is), `agent set` (how to carry it out — or set one standing instruction for the whole
   project with `agent set --project`), `estimate set --days N`, and put the figures the
   step needs in front of its agent: `spec render <project> <doc> --page N` turns a page
   into an image, `spec attach-to-step <step> <asset-id>` carries it into the step's
   briefing. `agent prompt <step>` shows exactly what the executing agent will receive —
   read it and ask whether it is enough to work from.
6. **Run `dplanner project lint <project>` before handing the plan over.** It lists every
   step missing a description, instruction, estimate or requirement link, every
   requirement no step implements, and every dangling link — each with the verb that fixes
   it — and exits 1 until the plan is complete. Hand over clean.
7. **When the spec changes**, import it again, then `spec diff <project> <doc>` to see what
   moved (PDFs diff by their text layers), and `spec requirements <project> --document
   <doc> --json` to find the linked steps. Update the steps and requirements the diff
   actually touches, and say what you changed.

## Recording your work on GitHub

A step can carry the branch its work lives on and the PR that lands it, so the plan always
says where the code is:

- **When you start working on a step**, record the branch:
  `dplanner github set <step> --branch $(git branch --show-current)`.
- **The moment a PR exists**, add it: `dplanner github set <step> --pr <number>`. With the
  GitHub CLI (`gh`) installed, DPlanner fills in the PR's title and state for you.
- `dplanner github refresh` updates the stored state of open PRs; `dplanner github prs`
  and `dplanner github branches` list what the repository has, for finding the right ref.
- Without `gh`, recording still works — the refs are stored as written, and the state
  fills in when a machine with `gh` refreshes.

Prefer building the project up with `project create` and `step add` when there are only a
few steps: the user sees each one arrive and can stop you. For something large you have
already agreed on, `dplanner project export | dplanner project import` is the blessed bulk
path: the document carries every step's aspects and prose — descriptions, instructions,
estimates, links — and the project's own, including its standing agent instruction, so a
whole authored plan moves in one command. (Module *files* — spec blobs, attached images —
stay behind; import the spec and re-attach figures after.)

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
