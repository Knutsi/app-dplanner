# DPlanner's shape, and why

`CLAUDE.md` and its area files under `.claude/rules/` carry the rules in their short,
imperative form; the files under `docs/architecture/` are where the reasoning lives, one per
area and named after its rules file, so the short form does not have to be taken on faith.
Each section states the rule as it stands today. How a rule came to be — what it replaced,
and when — is in [`decisions.md`](docs/architecture/decisions.md), dated.

app-framework's `docs/index.html` documents the machinery this is built on — the ten
registries, the origin token, the two version axes, where state lives. These documents cover
only what DPlanner added on top, and the reasoning is the point: the code shows *what*, and
this is the place for *why*.

**To cite a section**, name the file and the heading: `docs/architecture/canvas.md`'s *Marks
are a way of looking*. `tests/test_rules.py` holds every such pointer to a heading that
exists, so a renamed section is caught where it is cited.

## [Core — what binds every edit](docs/architecture/core.md)

- The goal
- Library → Project → Step
- Aspects
- Two surfaces, one vocabulary
- How a gesture becomes a change on screen
- The rulebook is loaded by where you work
- Deriving rather than storing
- A kind is what a node is; a facet is what it carries
- A workflow is one function under both surfaces
- Planning owns status
- Pressure points, named before they hurt
- Where this is going

## [Graph model — edges, auto-progress links, step numbers and isolation](docs/architecture/graph-model.md)

- The graph, and what it stores
- A step has a number, and the letter in front of it is derived
- An auto-progress link is an aspect on the step that waits
- A branch stretch is bracketed by a cut and a landing

## [Canvas — the graph editor's modes, gestures, cards and marks](docs/architecture/canvas.md)

- The Problems list lives in the graph, not in the window
- Copy and paste are a clone through the same command
- Who owns the canvas's input
- Contract closes a gap and stops one short
- Redirecting a link moves one end, and which end is the tool's, not a guess
- An explicit sort persists; the ambient layout never does
- Wave view derives positions; only Free view saves them
- A stack is presentation over a chain
- One in, one out is a rule the domain asks
- A stack's frame is the stack's handle
- Shift-drag restacks one card, and the cards make way
- Regions were retired
- The canvas is a plane, and why that is one decision rather than three
- Marks are a way of looking
- A card pulses where a person moves next
- An arrow into a review wears its talk bubble
- A problem is a squiggle, and the reading is shared
- The spotlight is one derivation, and a held key lends the look
- The palette a painter is handed is a snapshot
- The key block names the card and says who works it
- A picked node is lifted, not recoloured
- A card's size is the step's, and a layout never says how big
- A card on a branch names it
- The ground is a preference; snapping belongs to the gesture
- A step placed by pointing at a spot earns a stored position

## [Shell — seams, panes, primitives, menus, toolbars, glyphs and themes](docs/architecture/shell-ui.md)

- The index tree
- Where the user left off is remembered by key
- Home is where a window starts
- Motion is a library
- A submenu is one child menu per title, and groups separate inside it
- An action may carry a glyph, and only the pop-ups paint it
- The menu bar is sorted by subject
- View is the window; Graph is the canvas
- A right-click is composed by what is under it
- A strip of verbs is cut into bands, and a band folds whole
- The glyphs are somebody else's, and they are copied in
- An acknowledgement is asked, not written
- One picker, two lists
- A panel inside a tab follows the tab
- The command palette says where a verb lives
- Edit verbs belong to the surface whose things they act on
- A child menu of data is rebuilt when it opens
- Where a panel goes
- A seam belongs to the splitter, and only a split window marks a pane
- A primitive carries the rule; a dialog's stylesheet does not
- A roster has three shapes: a table sets values in the row, a list stays a list, a well keeps its widgets
- The context is announced once per turn, and a panel that steps aside keeps its content
- A theme is provided, never listed

## [Step panel — aspect toggles, the shelf, Details blocks, prose editors and assets](docs/architecture/step-panel.md)

- How a panel gets editors it has never heard of
- The step editor is a modal
- A markdown toolbar is verbs over a selection, and one splice each
- Expanding an editor is a second binding, not a copy
- A pasted image is an attachment and a link, not an embed
- An asset library is a view, not a store
- Inserting an existing asset is a paste with a different source
- Status is an aspect, and step types are emergent

## [Persistence — save, two writers, outside changes, reload and repositories](docs/architecture/persistence.md)

- A project's forms live in its dialog
- Two writers, one folder
- Closing a window is not discarding it
- Syncing an external fact
- A project names its locations
- Save spans repositories; the exit dialog says what it records

## [Agents — Run Agent, worktrees, run directories, usage, harnesses, profiles and reviews](docs/architecture/agents.md)

- The description is the instructions
- An agent finishes at Ready for review
- A review is a conversation kept on the step that asks
- Auto-progress is launched by the window
- Running an agent launches a peer, not a task
- Runs, questions and claims are three records in the plan

## [Playbooks — stages, gates, loop-back, presets and headless invocations](docs/architecture/playbooks.md)

- A playbook is a list of stages around one step
- A gate gets two rounds, then somebody decides
- A loop-back resumes the session that did the work
- Who acts: roles, profiles and the four actors
- The presets
- A step names its playbook; a project names its default
- The mark on the one card
- A failure is never a verdict
- The run record is the ledger
- Each stage is one headless turn per harness
- Decided at S4 (coordinator) — for Knut to confirm at the final review

## [Specs — the spec editor and its document sources](docs/architecture/specs.md)

- Editing a spec in-app is a replace
- A spec source is a kind the spec module runs

## [Schedule — order, progression, time estimates, progress and milestone colour](docs/architecture/schedule.md)

- Progression is the status-aware frontier
- The order says what order, and how much — never when
- Today is handed in
- Time estimates: two worker pools, one greedy simulation

## [Collectors — scopes, features, citations, tests, documentation and notes](docs/architecture/collectors.md)

- What reaches a step is derived at read time
- A test belongs to a step, and a step carries several
- A test says who it is for
- A test is filed under a category, and its words are the key
- A test is run from a panel, and a double-click there opens the test
- A right-click on a test is its step's
- A reference is a link, and a link is a preview
- The test format is read before a test is written
- A test goes stale when the step under it moves
- A check is a scope over the graph, and so is a milestone
- Documentation is fragments, and a collector compiles them
- A test result is not a step status
- One open run per project, and a run freezes its membership
- A feature is a step
- A citation is a quote and a digest; its place is derived
- A note is a record with a label, and the briefing carries an index

## [CLI — the entry word, install, the checklist, the topology gate, the skill and reports](docs/architecture/cli.md)

- The window is a word, and everything else is the CLI
- Installing is one act, and the pieces stay
- A checklist is a registry of probes, and every module owns its own
- The skill is a projection, not a document
- Lint belongs to no feature
- Authoring a step is one verb, many modules
- The topology is read before the graph is edited
- A report is a publication, not a record
- The Windows check is a disposable target, not a pipeline

## [Runtime — telemetry, diagnostics, discarding a build, LLM calls and dictation](docs/architecture/runtime.md)

- An LLM call is a task, and the service is GUI-bound
- Dictation is a provider, and capture is a peer process
- A view refresh is coalesced, and hears one project
- How the application scales
- The journal: what ran, how long it took, and why it hung
