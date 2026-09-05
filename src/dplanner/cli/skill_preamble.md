DPlanner plans **projects**: each one a directory inside a git repository, listed in the
user's per-user project library.

```
Library  ── the account level: the projects a user is planning
└── Project  ── a unit of work with a beginning and an end, in its own repository
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

- **Call a step by its key.** Every row prints one — `S7`, `F3` for a feature step, `M1`
  for a milestone, `C2` for a check — and every step verb takes it (`dplanner status set
  S7 done`; `s7` and a bare `7` work too). The number is the step's for life; the letter
  follows what the step is. Use the key rather than a title, which may match two steps,
  and put it first in anything you name after the step — a branch, a PR title (`S7: …`),
  a commit message.
- **Read before writing.** `dplanner project list`, then `dplanner project show <project>`,
  then **`dplanner topology show <project>`** — the project's own account of how its graph
  is shaped. The graph-editing verbs (`step add`, `step link`, `feature add`, …) refuse
  until the current topology has been read on this machine, and refuse again when it
  changes; a project with none refuses until one is written (`topology set`). Say what you
  found and what you propose before you change it.
- **Make small, named changes — and author them whole.** One `step add` per step, carrying
  everything the step needs in the same call: `--describe-file F`, `--agent` if an agent
  will execute it, `--days N`, `--attach a1`, `--test 'what must keep being true'`,
  `--after` for its dependencies, and `--feature f1` on the one step that realises a
  feature. One authored step is one line in the diff and one thing the user can disagree
  with; five half-steps are noise.
- **The description is the briefing.** Write one good description per step — what it is,
  what done means (see *Writing descriptions*) — and mark agent-executed steps with
  `--agent` (or `dplanner agent on` later). The executing agent receives the description
  as its instructions; do not write the same text twice. `--agent-file F|-` / `agent set`
  exist only for the rare step whose *how* genuinely differs from its description
  (`agent set <step> --clear` merges one back without unmarking the step), and
  project-wide conventions belong in one standing instruction
  (`agent set --for-project <project> --file -`), not in every step.
- **Do not invent structure the user did not ask for.** A plan with twenty imagined steps is
  harder to correct than an empty one.
- **Show the shape.** `dplanner project graph <project>` renders the step graph as a
  Mermaid flowchart — paste it into a PR description or a report instead of describing the
  graph in prose (`--short` when full titles render too wide).
- **Mind the two totals.** `dplanner schedule show` prints the serial total (one worker,
  steps end to end) *and* the critical path (dependency-aware, unlimited workers). Real
  staffing lands between them — read the labels, and quote the one you mean.
- **Re-planning?** `dplanner project clear-steps <project>` removes every step at once and
  keeps the specs, the features (unplaced again), the topology and the start date — then
  rebuild with authored `step add`s.

## Writing descriptions

A description serves two readers: the person reviewing the plan, and — on an agent step —
the agent executing it, who receives the description verbatim as its instructions. Write
it in two parts:

- **Open with the human part.** Two or three sentences anyone can skim: what the step is,
  why it exists, what done means.
- **On an agent step, follow with a clearly delimited section** — a `## Approach` heading
  works well — of numbered **tasks to accomplish**, each stated as an outcome: what to
  read first, what to build, what to verify. Name the tasks, not the route: the executing
  agent makes its own plan (usually in plan mode), so a how-to sequence only belongs there
  when the order genuinely is the point. Anything the agent must not miss belongs in that
  section, not in prose a reviewer skims.
- **Name every attached figure and what to take from it.** An image attached with
  `describe attach` or `--attach` reaches the agent as a bare file path; the text is what
  says why it matters. Reference each one from the markdown and say what it shows.
- **Reuse before re-attaching.** `asset list <project>` shows every image the project
  already carries and what uses each; `asset uses <project> <ref>` finds one by name,
  sha prefix or title. To reuse an image beside another step, read its absolute `path`
  from `asset list --json` and `describe attach` it there — content-addressing makes the
  second copy cheap and keeps every link local. `asset name` gives an image a title,
  `asset attach` stages one in the project pool before anything uses it, and
  `asset prune` (dry-run; `--apply` deletes, not undoable) sweeps copies nothing
  references any more.
- **Do not restate the standing instruction.** Project-wide conventions are prepended to
  every briefing already; the description carries only what is specific to this step.

```
dplanner describe set 'Build the quick-reg modal' --file - <<'EOF'
A one-keystroke registration dialog for the lab bench. It exists because bench
operators log readings mid-procedure; done means a reading lands without touching
the mouse.

## Approach
1. Read ![](assets/3fb2a1c9d4e58807.png) — the three error-modal sketches from
   spec page 6; build the middle one.
2. Add the dialog behind the `quick-reg` action; it must be fully keyboard-driven —
   that is its point.
3. Verify: open with F2, submit with Enter, and the reading appears in the ledger.
EOF
```

`agent prompt <step>` shows the result the way its consumer will see it — read it and ask
whether it is enough to work from.

## Writing tests

A **test** is what the step must keep passing *after* it is done. That is the whole
difference from a description, and it is the one thing to get right:

- The **description** says what the step *is*, and on an agent step it is the briefing.
- A **test** says how somebody would *prove* it works — a year from now, with no memory of
  building it. It outlives the step, and it is run again and again.

A step carries **several tests**, each its own record with its own result in a run. Write
one test per thing that can independently break, not one lumpy test per step. Each is
markdown; keep it to numbered steps somebody can follow without asking you anything:

```
dplanner test add 'Fix list flicker' 'No flicker on render' --text '1. Open the list in
the bench view with 200+ rows.
2. It must not flicker when it first renders, nor when data updates underneath.'
```

Three shapes are worth knowing:

- **A collector** is a step that stands for the work behind it. Three kinds, one derivation:
  a **check** (`dplanner check set`) gathers *everything* it waits on; a **feature step**
  (the one step that realises a record from `feature list` — `step add --feature f1`, or
  `feature set`) gathers its own work up to the previous feature; a **milestone**
  (`dplanner milestone set`) gathers the features it adds since the previous milestone.
  None of them stores what it holds — it is read off the graph, so linking more work behind
  one widens it automatically, and `--scope` takes any of the three.
- **`dplanner scope show <step>`** prints what one gathers: its features as headings, their
  tests under them. `--cumulative` gives everything behind it instead of only what it adds —
  what must pass to ship, rather than what is new.
- **A run** is one occasion of executing a scope. A project has at most one open at a time,
  and starting a new one closes the last:

```
dplanner test-run start --scope 'Pre-release check' --label 'Pre-release 3'
dplanner test-run mark T100 failed --note 'still flickers when rows arrive late'
dplanner test-run mark T101 ok
dplanner test-run show          # what is left, and what failed
```

When you execute a test, **record what actually happened** — including `skipped`, and
including a note on a failure. A run whose results were guessed is worse than no run.
Marking a test the status it already has succeeds, so a batch is safe to re-run.

## Writing the documentation

A step's **fragment** is what it adds to the product's documentation — written while the work
is fresh, in the words a user would read, not the words the plan used. A feature or a
milestone then **compiles** its fragments into one document.

```
dplanner docs set 'Parse the query string' --file - <<'EOF'
Search accepts `field:value` pairs and bare words. Quote a phrase to keep it together.
EOF
```

**You are the model that compiles them.** The window has a Compile button; the CLI has the
loop, which is three verbs:

```
dplanner docs status --json          # every collector: never / current / out of date
dplanner docs collect Auth           # everything it would read, as one document
#  …write the document yourself…
dplanner compiled set Auth --file signing-in.md
```

`compiled set` stamps what it read, so the document reads as up to date until somebody edits
a fragment behind it. Two things worth knowing:

- **A milestone reads its features' compiled documents**, not their fragments again. Compile
  the features first, then the milestone, or the release notes will say everything twice.
- **Out of date is derived, never guessed.** Editing a fragment, or linking more work behind
  a feature, marks that feature's document out of date — and recompiling a feature marks its
  milestone's. `dplanner project lint` reports them as `docs.compiled-stale`.

## Estimating agent work

With a human in the loop — reviewing the plan, answering questions, checking the result —
an agent task takes about **2 hours per task** in its `## Approach` list, coding and the
work around it together. So count the tasks: one task is a quarter day (`--days 0.25`,
the ¼ chip in the window), two are half a day, four fill one. Estimate the step at what
its tasks add up to rather than inflating or rounding it.

## Cutting agent steps

An agent step is one run: one terminal, one branch, one review when it lands. Every step
costs the user a launch and a review, so the plan pays for a step boundary in time — and
an agent works best on one coherent batch of related changes, where the second task
already has the first one's context. So, **unless the project's topology says otherwise,
lump similar work into one large step**: the five endpoints of one API, the three views
that share a layout, the migrations and the model they serve. Cut a step only where the
graph needs a boundary — a real dependency another step waits on, a feature step that
gathers the work, a check or a review the topology asks for, or work that belongs to a
different person or agent. A plan of many quarter-day steps is a plan of many launches;
a plan of a few well-batched days is what an agent and its reviewer both prefer.

**An agent step runs in a fresh git worktree on its own branch — leave that on.** Run
Agent prepares `.dplanner-worktrees/<key>-<ticket>-<slug>` on `agent/<key>-<ticket>-<slug>`
(created once, reused on the next run), so parallel agents never touch one checkout and
the branch is the reviewable result. It is on for every step unless somebody says
otherwise (`dplanner agent worktree <step> off`, or `step add --no-worktree`), and turn
it off **only when the step genuinely must act on the checkout the user is looking at** —
cutting a release from the current branch, settling a conflict the window handed over, a
step that only reads and reports. "It would be convenient" is not a reason: a step in the
checkout shares the developer's working tree with every other agent and with the person.
When you *execute* a step, its briefing tells you which worktree to expect; if you are
not in it, stop and say so rather than working in the main checkout.

## Linking honestly

Link `requires` only when the work truly cannot start before the other step lands. A plan
that is one straight chain is a smell: it usually means dependencies were invented to
impose an order, or the steps are cut too coarse to see what is independent. Independent
steps are what let two agents — or two weeks — run in parallel; `dplanner order show`
groups steps into waves of what can start together, and `project graph` makes the same
shape visible. If the waves are all singletons, revisit the links before adding more steps.

## Leave the graph readable

The graph is what the user reviews, so when a plan settles, make its shape carry meaning
rather than leaving the steps wherever they landed:

- **Sort it.** `dplanner layout sort <project> flow` arranges by dependency depth, left to
  right; `spine` lays the main chain on a central line with feeder work branching off it —
  the right shape when a project drives toward milestones; `timeline` spaces steps by their
  estimates so the graph reads as a schedule. A sort is one undo step in an open window.
- **Place the features, and mark the milestones.** A feature is a record in the project's
  catalogue (`dplanner feature list` — read out of a spec, or added by hand) and it is
  implemented **once**: exactly one step realises it, `step add <project> '<title>'
  --feature f1 --after <its work>`, and the work upstream of that step flows into the
  feature. `feature list` says which are placed and which are not; `project lint` reports
  the unplaced ones. `dplanner milestone set 'Ship the beta' --label MVP` makes a step a
  milestone (`--label` omitted, one is generated); the spine sort drives toward them,
  `milestone list` reads as a roadmap, and `scope show` says what each one adds.
- **Name the areas with regions — coarsely.** A region is a titled rectangle painted
  behind the steps — "Database setup", "Finalize release" — pure annotation, with no
  effect on the plan. `dplanner region add <project> "Database setup" --steps schema
  migrate seed` wraps those steps where they sit, and reports every step the rectangle
  actually covers — read that list, because a wrap can catch a neighbour nobody named.
  A region earns its place by naming a phase or a theme: one or two steps per region is
  usually too granular, and a region whose title restates a step's title says nothing. A
  project rarely wants more than five or six regions — fewer is better, and not every
  step needs one. Use your judgement; a handful of well-named regions is what lets the
  user take a forty-step plan in at a glance.
- **Sort first, regions second — and re-fit after re-sorting.** The wrap uses where steps
  sit, so a later `layout sort` moves steps out from under their regions. When that
  happens, `dplanner region fit <project> "Database setup" --steps schema migrate seed`
  re-wraps a region in place, keeping its identity so saved layouts still know it.
  `region list` shows what each region covers now — check it before handing the plan over.
- **Save the arrangement.** `dplanner layout save <project> "review"` snapshots every step
  position and region under a name, and the user can return to it from the canvas toolbar
  whenever later edits scatter things.

## Working from a specification

A project can carry the documents it answers to — a PDF, a markdown file, plain text —
and the workflow runs from import to steps an agent can execute *in isolation*:

1. **Import it.** `dplanner spec import <project> spec.pdf` stores the document beside the
   project. Importing under the same name again *replaces* it and keeps the previous
   version, which is what makes step 8 possible. Importing a PDF also extracts its text
   layer.
2. **Read it yourself.** `spec show` prints any document — for a PDF it prints the
   extracted text, page by page (`--page N` for one page) — and `spec path` still hands
   you the original file. Read the whole thing before planning; you understand it better
   than any parser.
3. **Write the topology with the user.** Before a single step, agree on how this
   project's graph is shaped and write it down: `dplanner topology set <project> --file -`.
   Say what counts as a feature *here* (for a React + API project: the views and the API's
   major parts are features; a component is not, unless it is exported and a feature in
   itself), what follows a feature (a **check** after every feature that has something to
   test, say), and where the milestones fall. Then **read it back**: `dplanner topology
   show <project>`. The graph-editing verbs refuse until the current text has been read
   on this machine, and refuse again whenever it changes — the topology is what keeps a
   forty-step plan the right shape, and reading it is cheaper than reshaping the plan.
4. **Read the features out of the spec.** One `dplanner feature add <project> '<title>'
   --document <doc> --quote '…' --page N` per feature you find — the things a person would
   name, demo and test, cut the way the topology says. The quote is checked against the
   document and the page recorded (found automatically when the quote is); when the same
   sentence appears on several pages, `--page` records the occurrence you mean — any page
   the quote anchors on is accepted, another warns and names them. Add `--strict` when a quote that does
   not anchor should stop you rather than warn; `--describe-file` for what the feature is
   in a person's words; `--image` for a mock-up. A feature is often described in more than
   one place: `feature cite <project> f1 --document <doc> --quote '…'` adds a second
   passage, `feature uncite` takes one away. Every passage is stamped with the document
   as it was when you read it, which is what lets step 9 say what changed. The catalogue
   is the durable trace of your reading — the next agent starts from `feature list`, not
   from scratch — and **`dplanner coverage spec <project> <doc> --uncovered`** lists the
   paragraphs no feature was read from yet: read it before you call the reading done.
5. **Render the figures once.** `spec render <project> <doc> --page N` turns a page into
   an image asset (`spec assets` lists them); one rendered page can serve several steps,
   and `feature attach <project> f1 <path>` puts one on a feature.
6. **Create the work steps authored, not as bare titles.** A step with only a title is not
   a plan — the agent who picks it up has nothing to execute. One `step add` carries it
   all: `--after` its dependencies (see *Linking honestly*), `--describe-file` (what it is
   — and, on an agent step, the instructions the executing agent receives), `--agent` (an
   agent will execute it), `--days`, `--attach a1` (the figures its agent must see).
   Project-wide conventions go in one standing instruction (`agent set --for-project
   <project> --file -`); `--agent-file` only where a step's *how* differs from its
   description. The standalone verbs (`describe set`, `agent on`, `estimate set`, `spec
   attach-to-step`) remain for editing later. A work step's briefing names the feature it
   flows into, with the passage it was read from — so it needs no citation of its own.
7. **Place each feature once.** `step add <project> '<title>' --feature f1 --after <its
   work steps>` is the step that realises the feature; the work upstream flows into it,
   and `scope show` prints what it gathers. A record has exactly one such step — a second
   is refused — and `feature list` says which are placed. Follow the topology for what
   comes after (a check, a review). `agent prompt <step>` shows exactly what any executing
   agent will receive — read it and ask whether it is enough to work from.
8. **Run `dplanner project lint <project>` before handing the plan over.** It lists every
   step missing a description or estimate, every agent step with nothing to brief it,
   every feature no step realises (and any realised twice), every passage that drifted or
   was lost since the spec changed (and every one whose paragraph changed around it), a project with no topology, and every description image
   reference that resolves to nothing — each with the verb that fixes it — and exits 1
   until the plan is complete. Hand over clean.
9. **When the spec changes**, import it again, then run the loop:
   `spec diff <project> <doc>` to see what moved (PDFs diff by their text layers);
   **`coverage review <project>`** for every passage that no longer simply anchors — *behind*
   (the paragraph around it changed: re-read it), *drifted* (reworded: `feature reanchor
   <project> <f> --accept-drift` takes the new text), *lost* (gone: `feature cite` the
   passage as it reads now, or `reanchor --drop-lost`) — each with its verb; `feature
   reanchor <project> --all` once you have read what changed, to re-stamp the rest;
   **`coverage spec <project> <doc> --uncovered`** for what the new text says that nobody
   cites yet — cite it into a feature, or `feature add` one; then adjust the work behind
   the features that changed, and if the *shape* changed, `topology set` it, `topology
   show` it, and say what you changed. `coverage show <project>` prints the whole trace
   — spec → features → milestones → tests and docs — to check the plan still answers the
   spec end to end.
10. **On a project that predates citations** — features with no passage, a spec nobody
   cites — `coverage review` lists them as *unsourced* and *uncited*; retrofit the
   references with `feature cite` from `coverage spec --uncovered`, and `feature reanchor
   --all` stamps what was cited before stamps existed.

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

Prefer building the project up with authored `step add`s: the user sees each step arrive
whole and can stop you. To move an agreed plan into a **new** project in one command,
`dplanner project export | dplanner project import` carries every step's aspects and prose
and the project's own — the feature catalogue, the topology, its standing agent instruction
— import always creates, never merges. (Module *files* — spec blobs, attached images — stay
behind; import the spec and re-attach figures after.) To rebuild an **existing** project, `project clear-steps`
then authored `step add`s.

## Conventions

- **`dplanner --help` lists every noun and `dplanner <noun> --help` its verbs**; `reference.md`
  beside this file has every argument. A bare `dplanner` prints the same help and exits 2.
- **`--json` on any command** gives machine-readable output. It works before or after the
  verb.
- **Names or ids.** Anywhere a project or step is named you may use its id, its folder name,
  or a unique part of its title. An ambiguous name is refused and the message lists the ids —
  use one of those rather than guessing.
- **The positional names the thing the verb acts on.** A step verb (`describe set`,
  `agent on`, `milestone set`, `estimate set`) takes the *step*; a project verb (`step add`,
  `spec …`, `order show`, `region …`, `layout …`) takes the *project*. A step verb finds
  its project itself — from the working directory or `--project` — never as a second
  positional.
- **Already clear is success.** State-clearing verbs (`status clear`, `estimate clear`,
  `milestone clear`, `feature clear`, `feature uncite`, `ticket clear`, `handoff clear`,
  `github clear`, `agent off`, `agent set --clear`) exit 0 when there is nothing to clear —
  safe to batch; so does `feature cite` of a passage already cited.
- **A verb marked *reads the topology first*** refuses until `topology show` has printed
  the project's current topology on this machine. Read it once per session, and again
  after `topology set`; it costs one command and it is the shape of everything you add.
- **Exit 1 with one line on stderr** means something you can fix. A traceback means a bug in
  DPlanner; report it rather than working around it — `dplanner telemetry show --failures`
  has its record, beside the window's own failures, and `telemetry show --slow 50` says
  what took long in either. Read it before reporting a hang or a crash.

- **Nothing is written when a command fails.** A run is a transaction.
- **Someone else may be writing too.** If a command says a project changed on disk, a
  window or another run wrote to it. Run the command again — you will be working from what
  is actually there. A window open on the project shows your changes as they land; only an
  entry the user was editing at that very moment is held back and put to them.
- **A project created inside a git checkout announces itself**: a `.dplanner` pointer
  file is written at the repository root, so discovery works from anywhere in the clone.
