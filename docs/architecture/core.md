# Core — what binds every edit

The reasoning behind `CLAUDE.md`'s rules: the model, the two surfaces, the chain every change
follows, and the planning tier. Each area of the code has a file of its own beside this one;
`ARCHITECTURE.md` is the index.

## The goal

Plan software work in a form that survives being shared, and that a coding agent can drive
as well as a person can. Two consequences fall out of that sentence and shape everything
below:

- **The plan is plain files in version control**, so the format is a public contract and its
  diffs are meant to be read by humans. `FORMAT.md` is that contract.
- **There are two front doors, not one and a hatch.** A window and a `dplanner` command,
  equals, over one model — and expected to be in use at the same time.

## Library → Project → Step

A planner needs a level above "the project" — but the earlier answer, a **Product** owning
its projects inside one workspace folder, put the boundary in the wrong place. A person's
projects do not all belong to one codebase, a project's planning files want to live *with*
the code they plan, and "where is the repository" turned out to be a fact the directory
already knows rather than one worth storing. So the top level is the **Library**: a per-user
file (see `FORMAT.md`) listing the project directories this user is planning. It is the
account level, not a document — the in-memory `Library` aggregate exists only to be the one
place a change can happen (the flat node index and the signals live there), and nothing on
disk stands for it but the membership list.

A **Project** is a unit of work with an end — a directory holding `project.dproj`, inside a
git repository, opened through its own storage provider. A **Step** is a node in its graph.

**Why membership changes bypass the undo stack.** Creating a project may `git init` a
repository and always writes files outside any store; removing one only forgets it. Neither
is something Ctrl+Z could honestly reverse, so File ▸ New Project, Open Project and Remove
from Library apply their model change directly with their own origin — the same discipline
as syncing an external fact, below. New and Open live with the project verbs
(`modules/projects/`), Remove from Library with the archive (`modules/project_archive/`,
since it forgets an archived row as readily as a live project): New Project is the Project
dialog in create mode and Open Project is a wizard over the two ways in, and all of them start from the same question — *which plan
repository?* — answered by one picker. The library module keeps only the question of
*which library*.

**An archive is Remove from Library that remembers.** A finished project should leave the
working set without being forgotten, so *Project ▸ Archive Project* (`library archive`)
detaches it exactly as Remove does and files its directory under the library file's
`archived` list. Four decisions shaped it.

- **It is per user, never on the plan.** A flag in `project.dproj` would archive the
  project for everybody who has it, and would keep it loaded and saved in every window
  just to hide it. The library file is already one person's view of which plans are live,
  so the archive is one more list in it (`FORMAT.md`'s format 4). An archived project is
  not opened, so it costs a library nothing at load and nothing at save.
- **The store holds the list, as it holds the checkouts.** `LibraryStore` writes the file
  whole on every membership flush, so a list anybody else kept would be dropped on the next
  one. The same holds for the other writer: `_adopt_library_file` takes the list in
  *before* it attaches anything, so a project another window restored is not un-archived
  here twice.
- **Restoring is attaching.** `store.attach` takes a directory off the list, so *Restore
  Project*, *Open Project…* on the folder, `library add` and `library restore` are one path
  with four doors, and a project can never be listed as both live and archived. The one
  exception is deliberate: `library add <plan repository>` adds *every* project a
  repository lists, and it skips the archived ones by name, because a bulk add is not a
  request to undo somebody's archiving.
- **Remove from Library generalises rather than gaining a twin.** The archive is part of
  the library, so the one verb forgets an archived entry when that is what is picked, and
  `library remove` falls back to the archive when no live project matches. An archived
  project is published as `archived_project`, keyed by its directory, and every other
  Project verb reads `project`, so none of them can mistake one for a project it could
  open. The Project menu's *membership* band holds all four verbs, and it is the whole of
  the right-click on the index's Archive folder and in the Archive tab.

The store lets go before the model does, for Remove as much as for Archive. Sync rewires
its repository groups on the structure signal and reads them from the store's records, so
a model change heard first rewired onto a project that was still attached.

**A project link is the third way in, and the only one that works on a machine with
nothing.** Open Project's browse page assumes a plan repository you can already name;
somebody being brought onto a project cannot name one. So *File ▸ Share Project…* writes
what they are missing — the plan repository's remote, the project's path inside it, and the
code repository — as a line to paste, a `.dlink` file to send, or a QR code to hold up, and
the wizard's link page reads any of them, clones what this machine lacks and connects the
result. `domain/project_link.py` owns the document and both encodings; neither surface
parses anything itself, which is what makes `dplanner project share` and `project open` the
same feature rather than a second one.

Three decisions are worth writing down. **The link is readable, not packed**: a person
asked to open somebody else's link can see which repositories it names before opening it,
and that is worth the extra characters. **It carries no access**, and the Share dialog says
so in a sentence — the failure mode of a thing that looks like an invitation is somebody
assuming it is one. And **the terminal never clones**: `project open` resolves the link
against the clones the library already has and otherwise refuses with the `git clone` line
to run, exactly as `library add` does, because a verb an agent may call should not reach
the network on its own — while the window, where a person is watching, does clone, inside
the page they pressed the button in.

**Why opening another library is another process.** Every registry refuses a duplicate id,
so two libraries in one process was never implementable — and unlike the old
workspace *switch* (one document replacing another in the same window), two libraries are
genuinely two applications' worth of state someone wants side by side. File ▸ New/Open
Project Library therefore spawns a detached instance and the in-process switch machinery is
gone; `reload` — the full rebuild — remains, because branch switches, pulls and external
writes still invalidate the build wholesale.

**Why a graph and not a tree.** Work has prerequisites that do not nest: the thing you must
do first is routinely in another part of the plan. A tree forces that relationship into
either a false hierarchy or a side-channel; the template's demonstration domain had exactly
that side-channel (`depends_on` beside the tree) and it was the most-explained field in the
model. Making the graph the primary structure removes the exception.

**Why edges live on the step that waits.** `"edges": {"requires": [...]}` on the waiting step
reads unambiguously — this is what *I* am waiting for — and makes a step self-contained:
delete it and its links go with it. Storing edges centrally in `project.json` would make
every link change touch one heavily-shared file, which is the wrong shape for merges.

**Why deleting a step leaves other steps' links alone.** Undo has to restore the graph
exactly. Silently rewriting other steps' edge lists would make delete-then-undo lossy, so
resolution is tolerant instead: `Library.requires()` skips ids it cannot resolve.

## Aspects

An estimate, a ticket, a description. None of them are fields on `Step`, and that is the
central design decision of the model.

The alternative — a field per useful fact — makes every new feature a change to
`domain/model.py`, a format migration, and a change to everything that serialises a step. It
also forces the model to have an opinion about facts it cannot validate. A team that tracks
work in Jira and a team that does not would be carrying each other's fields.

So an aspect is **a module's namespaced entry beside the step**, in one of three stores
chosen by what the content is:

| Store | For | Why not the others |
|---|---|---|
| `module_data` → `modules/<id>.json` | structured facts | JSON is mergeable and versioned per module |
| `module_text` → `modules/<id>.md` | one document of prose | markdown inside JSON is one escaped line per edit, and loses the text stack |
| a file area → `modules/<id>/` | images, attachments | opaque bytes nobody merges, and not undoable |

`module_text` deserves its own note, because it looks like a field and is not. The framework
already has a text stack — positional splicing with a staleness check, undo coalescing per
burst, origin-based echo suppression — and a description that lived in a JSON value would
have been a whole-document rewrite per keystroke, with a second text stack growing to fix
that. Keying prose by module id instead of naming it as a field gives any module a real
prose document and *removed* code: the demonstration domain had two hardcoded text fields
with a signal and a field class each, and this is one of each.

An aspect declares itself once, in its package's Qt-free `aspect.py`: `SPEC` (id, label,
one-line summary, data format) plus typed `read`/`write` helpers. That one declaration feeds
the CLI verb, the generated skill, `dplanner aspect list`, the module's `data_format`, and
whatever editor arrives later. Shipping an aspect with no editor is deliberate rather than
unfinished — the `data_format` declaration is what makes the project forward-compatible,
so the CLI can write the data today and a card can arrive without a migration.

## Two surfaces, one vocabulary

The rule that keeps a window and a command line from becoming two applications:

> A menu action and a `dplanner` verb build the **same object from `domain/commands.py`**.
> The GUI pushes it onto the undo stack; the CLI applies it and lets the store flush.

Everything follows from that. A CLI edit is undoable in a window. Neither surface can grow a
behaviour the other lacks without somebody editing that one file. And the validation that
refuses a cycle lives in the model, so it is the same refusal on both sides — the CLI just
renders it as one line instead of a dialog.

The layering that protects it is `core → domain → cli → framework → modules`. The
interesting rule is that `cli/` sits **below** `framework/` and imports no Qt, and that a
module's `cli.py` and `aspect.py` are held to the same standard. That is not tidiness: an
agent refining a plan makes dozens of small calls, and importing a GUI toolkit for each one
cost 792 ms and a hard dependency on graphics libraries that a container may not have.
Making the module packages' `__init__.py` files docstring-only took the same import to
18 ms, and `tests/test_architecture.py` asserts the property directly so it cannot rot.

There are therefore two composition roots, and both are in `modules/__init__.py`:
`default_modules(services)` builds the window, `default_cli_commands()` builds the verbs.
Reading that one file still answers "what is this application".

## How a gesture becomes a change on screen

This is the application's central mechanism, and everything else here is a consequence of it.
It is one chain, and **nothing is allowed to take a shortcut through it** — the short,
imperative form of that rule is in `CLAUDE.md`; this section is why each link exists.

```
a gesture, a menu item, the command palette, or the CLI
        │
        ▼   the Context: URI strings only — never widgets, never model objects
   ActionSpec.state(context) gates it, ActionSpec.run(context) performs it
        │
        ▼   a Command from domain/commands.py — the same object either surface builds
   undo.push(command)   (the window)        command.redo(library)   (the CLI)
        │
        ▼   one mutator, one change
   the model, which emits exactly one signal carrying an `origin`
        │
        ▼   synchronous, on the GUI thread
   every view applies it — except the one whose origin it is, which already shows it
```

**The command is a step, not an implementation detail.** An action does not change data; it
pushes a command that does. That is what makes the change undoable, and it is what carries the
origin token down to the signal. A mutation made directly is a change Ctrl+Z cannot see and no
other view hears about.

**The visual update is pulled, not pushed.** An action cannot touch a view — it holds only URI
strings and has no way to reach one. Each view subscribes to the model and decides for itself
what to redraw. That is the property that lets four aspect modules render into one panel
without any of them knowing the others exist, and it is why a canvas drop belongs in an action:
the canvas should not be the thing that knows how to create an edge.

**The origin is what makes the last step safe.** The view that caused the change ignores its
own echo; undo passes a token matching no view, so everyone applies it. Without it you get the
oldest bug in desktop software — B updates from A's edit, B's update fires, A's caret jumps to
the end. Every signal on `Library` carries one, with no exception, because a convention with
one hole is one nobody can rely on.

**"On the GUI thread" is a constraint, not a formality.** `core.signals.Signal` is synchronous
and has no thread affinity, so the model may only be mutated on the GUI thread. Anything
computed off it comes back through `TaskRunner`, which is the one place in the application
using real Qt signals rather than ours — precisely so that hop is queued. The whole rule:
**work may leave the GUI thread; mutation may not.**

### When there is more than one pane on screen

Tab groups add a second way for the activity scope to change: a click in another pane, rather
than a click on a tab. **Activating a group is not a new kind of fact; it is a new cause of an
existing one.** So it runs the same routine a tab switch runs, and nothing downstream — the
menu bar, the toolbars, the right-click menus, undo coalescing, autosave — learns that groups
exist at all.

Two consequences fall out, and both are rules rather than details:

- **Only the pane the user is in may write to the selection scope.** There is one scope and
  several panes, so a background pane re-syncing its canvas — when a step is deleted, say —
  would otherwise clobber what the active pane published. `ProjectActivity` tracks this
  through `on_activated`/`on_deactivated`; anything else that publishes a selection owes the
  same guard.
- **A visible pane that is not active is showing a claim the context no longer holds.** Its
  canvas still paints a selection; an in-tab toolbar would still show the active pane's
  action state. That is inherent to one context and N visible surfaces, not a bug in this
  design — every multi-pane editor has it — and the honest answer is to make which pane is
  active obvious, which is what the dimmed tab titles are for.

The detail panels get the first rule for free, and that is the point of where they live. A
panel reads the context; only the active pane may write to it; so the panel follows the pane
the user is in without a single line about panes anywhere in it.

The tab bar's right-click is the same rule pointing the other way. **A right-click on a tab
makes it current before the menu opens** — the move the canvas already makes when it selects
the node under the cursor — so the menu is built from one notion of "what the user is on" and
every entry in it is a verb the menu bar and the palette already have. That is why the tab
verbs live in View's Tabs submenu rather than in a hand-built popup: `build_menu` renders a
*menu* (its `submenu` filter renders just that child menu), and a right-click that offered
anything else would be a hand-maintained copy waiting to drift. `TabHost` builds none of it —
it emits `tab_menu_requested` with a position, and the module that owns the tab verbs renders
them.

### What this rules out

The graph canvas is the worked example, because it got this wrong first. A drop originally ran
a private signal straight to a command: the verb existed nowhere else, its refusal was checked
by hand in the view — where it read gesture state a later line had already cleared, so *every*
drop was silently refused — and no test could reach it without a widget. Routing the drop
through `steps.link` fixed the bug by deleting the code that held it, and gave the same verb to
the Step menu and the palette for free.

So: **a gesture is not a special case.** If a view can do something, it does it by publishing
what the user picked into the context and running an action. The verb is then testable by
handing it a constructed `Context`, and `tests/modules/canvas/test_canvas.py` does exactly
that with no canvas in sight.

### Hidden means absent; disabled means not now

An `ActionState` distinguishes *invisible* from *greyed*, and the two are different claims,
not two strengths of the same one. **Disabled says "this exists here, but not right now"** —
the verb belongs to the program, the user just hasn't given it what it needs, and the greyed
entry teaches the precondition (its label carries the reason where there is one:
`steps.link`'s "Cannot Link — cycle" is the worked example). **Hidden says "this capability
is not in front of you at all"** — a storage provider without history has no *Save Version*,
a feature behind a flag leaves no trace. The rule's short form is in `CLAUDE.md`.

The reason it is a rule and not taste: a menu that reshapes itself with the selection cannot
be learned. The user who saw *Show in Coverage* yesterday and cannot find it today has no way to
know whether the feature is gone or their context is wrong — a greyed entry answers that
question before it is asked. It also keeps every surface stable: a toolbar row that reflows
as the selection changes cannot be read, and the menubar's separators stop jumping.

One documented exception: a verb whose *opposite* currently occupies its slot may hide.
`steps.link` stands down when the pair is already linked, because *Unlink Steps* is the verb
that belongs in that position and a greyed "Already linked" beside it would state the same
fact twice. The label still rides on the hidden state — the canvas status bar reads it after
a refused drop.

The presenters split accordingly: the menu bar, toolbars and `build_menu`'s right-click
popups all render a disabled action greyed; only the command palette filters to what is
runnable, because a fuzzy search over verbs that cannot run helps nobody.

## The rulebook is loaded by where you work

`CLAUDE.md` is loaded into every session whole, and on 13 September it was 152 KB — about
38,000 tokens over 1,835 lines, nine times what it had been eighteen days before. Agents wrote
to it in 30 of the last 55 sessions, because nearly every step settles a rule, and 56 merges
had changed it on both sides. A session's first turn had doubled to about 98k tokens, paid
again on each of a step's several hundred turns. None of that was the real cost. A rulebook of
118 mechanical facts of equal weight is one in which the rule a change is about to break sits
between a report's and a credential's, and Claude Code's own guidance is that a long
instructions file is followed less well.

So the rulebook is cut by **when a rule is needed**, and the trigger is the harness's rather
than the model's judgement:

- **The core, `CLAUDE.md`, always loads**: the principles, the checks, the layers, the
  add-a-module recipe, and the mechanical facts that bind an edit wherever it is made — a
  painter never trusts `option.palette`, a verb that does not apply is disabled and never
  hidden, no subprocess runs in an action state. A rule belongs here when it has no path: it
  is defined in `framework/` and applied in every module.
- **Eleven area files under `.claude/rules/` load by path.** Each names the files it governs
  in `paths:`, and Claude Code loads it when one of them is read — which is before any edit,
  because an edit needs a read. The canvas's nineteen rules arrive with the first canvas file
  an agent opens, and a report change never carries them.
- **The crash forensics are a skill, `suite-crash`.** A diagnosis is a procedure reached for
  by a symptom, which is what a model-invoked skill is for — told of a crashed worker in
  three fresh sessions, a model loaded it before anything else all three times. The rules
  those crashes left behind — never read a layout back, parent a layout before filling it —
  are one line each in the core.

**Why not one skill.** It was the first idea, and it is the right shape for the forensics and
the wrong one for the rest: a skill loads when the model decides it is relevant, from a
description capped at 1,536 characters, and "tint the squiggle" never makes a model think it
needs "a painter never trusts `option.palette`". That is exactly the slip a rulebook exists to
prevent. Nested per-directory `CLAUDE.md` files trigger by path too, but a rule does not follow
a directory — the canvas spans `canvas`, `framework` and `theme` — and a hook rebuilds
what `paths:` already does, with its text arriving after the edit it was for.

**What the path trigger cannot reach, and what does.** Measured on Claude Code 2.1.269 with an
`InstructionsLoaded` log before anything moved: a Read loads the rule, a brace glob works, an
unrelated file loads nothing, and a read in plan mode or by an Explore subagent loads it too.
A `cat` through the shell and a Write of a new file load nothing, another agent CLI never reads
`.claude/rules/`, and a plan is written before most of its files are read. `scripts/rules.py`
answers the same question from the same `paths:` for all of those — `for <paths>` before a
plan, `diff` before finishing — and `AGENTS.md` points Codex and OpenCode at both. It is two
verbs and no search, because `grep` searches; and it lives in `scripts/` rather than the
shipped CLI, because `dplanner` plans users' projects, its skill is generated from its
registry, and the `dplanner` on PATH is the installed build, which would read one branch's
rules with another branch's code.

**Verbatim first.** The split moved every bullet and paragraph unchanged into exactly one file,
checked mechanically, so it reviews as a move and a citation of a rule by its title still finds
it. Trimming the long bullets — this file already carries the reasoning for 72 of them — is the
next pass, one area at a time.

**The core has a budget, and every module has an area.** `tests/test_rules.py` holds
`CLAUDE.md` under 32 KiB, a fifth of what it was and small enough that adding to it means
trimming it — the first turn of a fresh session with the same one-line prompt went from
54,870 tokens to 23,036; asserts that every glob alternative still names a file, since a glob that names
nothing is a rule nobody is handed; and makes every module package be claimed by an area or
named in `UNSCOPED`, so a new module forces the question of which rules govern it.
`.gitignore` carries `.claude/rules/` and the one skill into every worktree, and the rest of
`.claude/` stays personal.

## Deriving rather than storing

`domain/ordering.py` answers "what order can this be done in" as a pure function, and the
choice not to store the answer is the same one the canvas made about node positions — for a
sharper reason. The CLI is a first-class writer here: `dplanner step link` changes a graph
with no window running, so a stored index would be stale exactly when an agent is driving,
unless the recompute moved into the model and every `step add` rewrote every step file whose
index shifted.

The index a step carries — its position in that order — is therefore computed with it, by
`ordering.placed()`, which is the shape both the table and `dplanner order show` render. One
function decides what step four is, so the window and the terminal cannot disagree about it.

What "always available" actually requires is not a file but a function every surface can
reach. So the walk lives in the domain, and the canvas layout, the order view and
`dplanner order show --json` are three readers of one implementation. Nothing can disagree
with the graph, because there is nothing else to disagree.

`planning/schedule.py` is the second reader of that same walk, and the one that shows what the
shape was for. "When does this land" is "in what order can this be done", carrying estimates
instead of counting hops — so it takes `ordering.placed()`'s answer and lays the days end to
end from a start date. The order table, `dplanner schedule show` and its `--json` are three
renderings of one function, and none of them can date a step differently from another.

**It reads the estimate where it lives.** The estimate began as a module's `module_data`, and
`schedule()` was handed a `days_for(step)` so the domain never learned its key. Since the
estimate joined the planning tier (`planning/estimate.py`, *Planning owns status*) every walk
reads it by default, and `days_for` survives as a keyword for the callers that mean other
days — calendar days stretched by a focus, the simulator's world, a test's fakes. Whoever
derives from it still needs one implementation rather than one per surface.

The start date itself is the smallest case of the same rule. **A project nobody has dated
starts today**, and that answer is computed (`planning/estimate.py`'s `start_of`) rather than
written when the tab opens. Writing it would dirty a project for the act of looking at it,
and it would be wrong by tomorrow — so the only date on disk is one a person chose, and every
other plan answers "if you start now". Which also deleted a state: there is no "no start
date" any more, so no empty Date column to explain and no branch to carry it.

The rule generalises: **derived data may be cached, but it may not be persisted.** A cache
that is wrong is a bug you find in a session; a file that is wrong is a bug you find in a
diff, months later, in a project nobody can reconstruct.

One carve-out, stated so it stops looking like an oversight: **a derivation keyed by the
content hash of its input is not a stored answer**, because it cannot disagree with what it
came from — the input changing changes the key, and the stale entry is simply never read
again. The worked example is the spec module's PDF text layer
(`modules/spec/documents.py`): extraction is expensive, so the text is written into the
module's file area under a name derived from the content-addressed document blob, and the
read path falls back to extracting in memory when the file is absent. What the rule above
forbids is a persisted answer that *can* drift from its source; a hash-keyed derivation
has no way to.

## A kind is what a node is; a facet is what it carries

The Type submenu grew to ten entries once Estimate, Description, Handoff and GitHub joined
it, and that made a distinction visible that had been implicit all along. A **milestone** is
a kind: a node exists in order to be one, the graph reads differently for it, and it wears a
body colour. An **estimate** is a facet: a fact a step of any kind may hold. Both are
aspects, both are toggles — but only kinds answer the question *New* asks.

So the kinds live on as the bar's *templates* — `StepPropertiesDeps.templates`, each a
kind with the facets it usually carries and the tone it wears — handed to the step panel
by the composition root exactly as `ScopeKind` is handed to the tests module. The bar words
them on its left; the panel learns nothing about features. Deriving the list from the Type
submenu instead would have worded *Description* beside *Milestone*, and the entry that
would have to be filtered out is the proof the two lists are answering different
questions.

**Step ▸ New is one verb, and the dialog is where a fresh step is configured.** The bar says
what a step is in one click, so a submenu of kinds would be a second, narrower way to say the
same thing, with its own list to keep in step with the toggles. New creates a plain step
titled "New step" and opens `steps.details` on it — through the `created` seam, where
selecting the new step lives — with the name field focused and its text selected. Typing
replaces the placeholder, the bar sets the kind, Escape closes. The canvas double-click does
the same at the point it was given. (*decisions.md* has what it replaced.)

The body colours follow the same ranking the model uses. Done outranks a kind — a shipped
milestone reads finished — and a milestone outranks a feature, because that is the coarser
claim, the same order `kind_of()` reads the markers in. What the body cannot say, the
medallion does: a node that is both keeps both glyphs.

Teal was chosen for the feature by where the hues already were, not by taste: 76° from the
milestone's violet so the two collectors never read as one, and 42° from the done green —
which additionally *mutes* its node, so that pair is separated by weight as well as by hue.
The nearest claimed hue is the agent-run chip's teal, and that is a labelled pill on the
bottom edge of a running step, never a body.

Every Type toggle carries **the glyph its node wears** — a medallion's, or for Agent and Wait
the key block's — a painter from `theme/icons.py`'s `GLYPH_ICONS` vocabulary, the same one
the canvas answers in, so one declaration puts the same glyph on the Type submenu entry, on
the aspect bar and on the node itself.

## A workflow is one function under both surfaces

Sharing the command did not share the verb. The window's *Set Status* pushed
`status_command` and nothing else, while `status set` refused a wait, held an agent at
review, kept a `--because` note and ended the claim — so a director marking a step done in
the window left the agent's banner standing, and "neither surface can grow a behaviour the
other lacks" was quietly false. The fix moves the shared object up one level, from the
command to the workflow: `modules/step_status/workflows.py`'s `StatusWorkflow.set_status`
returns a `Change` (`domain/workflow.py`) — one command, and the follow-ups to perform once
it is accepted (`EndClaim`). The window pushes the selection's commands as **one
`CompositeCommand`**, never a gesture of pushes, because a gesture groups history while a
composite is all-or-nothing: a refusal on the third step leaves the first two unmoved and no
claim ended. The CLI applies the command and owes the follow-ups to
`CliContext.after_flush`, which `open_library` runs only once the whole invocation is written
— and the verb's report goes with them, so a run that wrote nothing neither released a claim
nor said it did. Both run `perform`, which attempts every follow-up on its own and reports
the ones that failed (a notice with a retry in the window, a refusal naming the written
status in the CLI); a model change is never rolled back for an effect. `refusal()` is the same function behind the
menu's greyed label and the CLI's error, and because it runs in an action state it reads only
the steps it is handed. The context system is untouched: the `ActionSpec` still decides which
steps a verb acts on.

Three types carry rules a habit would otherwise have to keep. **`Actor = Person | AgentRun |
Daemon`**: the director rule is one `match` — a person may finish a step, an agent run goes
through review — and mypy fails a branch that forgets a kind. **`PlanView`** is `Library`'s
queries alone, so a workflow that tried to mutate does not type-check. **`FollowUp`** is a
union every performer matches with `assert_never`, so a new kind of effect cannot be
silently dropped by one surface. A follow-up is an external fact, performed after the
change and never undone: undoing the director's done brings the status back, not the
agent's claim (*Syncing an external fact* is the same rule from the other side).

**Time reads review and merge as work in flight, and dates it from when it started.** Not
landed — the percent, the Step statuses tab and `requires` all say so — so the Time tab, the
recorder, the matrix, the report and the simulator read both words as *in progress*, through
one fold, `planning/status.py`'s `in_flight` and `work_since`, which every time surface
reads through. The fold covers the day as well as the word. Moving a step to review stamps its `since` today, and the
model credits in-flight work from `since`. Read raw, the day an agent finished would re-cost
its step at the whole estimate from tomorrow and call the plan broken — a forecast that
jumps late exactly when work lands. So `work_since` answers `started` for the two words, and
`status.read_since` keeps the raw day for the one question that wants it: *did a status
change today?*, which the Work page draws a day solid by. The simulator plays only the
prototype's four words, so a folded reading never reaches a real plan (a test pins both).

## Planning owns status

**A tier between the graph and the features, holding what every planning question reads.**
`domain/` is the graph — nodes, edges and aspect entries it treats as opaque — and stays
that way. `planning/` sits on top of it and *interprets* the few aspects every planning
question needs: the status vocabulary and its stored format (`planning/status.py`), the
readiness walk (`planning/progression.py`) and the schedule (`planning/schedule.py`). It
imports `core` and `domain` only, never Qt and never a module, and `domain/` never imports
it; `tests/test_architecture.py` holds both directions. Before it, status lived in three
tiers at once — the words in `domain/progression.py`, the format in
`modules/step_status/aspect.py`, the rules in the composition root — and every reader that
compared a status compared a string. Dependencies now point toward what changes least:
everything reads status, so status sits low, and a feature imports it rather than being
handed it by the root. The structural review (`docs/research/2026-10-03-structural-review/`,
§5, §12 and §14) has the measurements and the admission test for what may join it — an
aspect belongs here only if a headless server or daemon must interpret it to order, claim,
validate or merge.

**`Status` is an `Enum`, not a `StrEnum`, so a copied word is a type error.** mypy's strict
equality (on through `strict = true`) refuses `status == "done"` when the two types cannot
overlap; a `StrEnum` *is* a `str`, overlaps every literal, and would let the copy through.
`.value` is the word on disk, so the format did not change, and `status.word()` is the one
place a reading turns back into a word on its way out — `--json`, a CSV cell, a report's
class name. `tests/planning/test_status.py` runs mypy over a probe to keep the claim true.

**What this build cannot read is a type, not a word.** `stored(step)` answers
`Status | Unknown`: an `Unknown` carries the word a newer build wrote, and the entry stays on
disk untouched. The wait-aware reading on a given day (`schedule.wait_status`) adds
`Waiting`, a wait that is not over, never stored. Readiness — `progression.py`, the review
turns, the Time tab's facts — accepts a `Status` and nothing else, so the caller has to
decide, and `status.held` is the one decision: an unknown word holds its step as blocked
(never due, listed with Blocked, nothing waits past it), and a wait not over is pending.
Reading an unknown word as pending would launch the step again; the type makes forgetting
that a mypy error rather than a duplicate agent. Run Agent's refusal is the one reader that
looks at `Unknown` itself, to name the word.

**Three meanings of done stay three functions.** The stored status (`status.stored`), the
status a card wears (the root's `_card_status`: pending for a step nobody works) and the
status on a day (`schedule.status_on`, waits read in) answer different questions, and a
reader picks one by name rather than by remembering which helper folds what.

**Transitions are not policed.** The graph gates *launching*, not *recording*: a step set
done out of order is honoured (*Progression is the status-aware frontier*). The review's
state-machine sketch would have broken that, so `planning/` owns the vocabulary and the
readiness rules and stops there; who may set what is a workflow's question, asked by the
verb that sets it.

**The estimate joined the tier, and the walks read it rather than being handed it.** The
estimate (`planning/estimate.py`, with the project's start date, under the unchanged id
`estimation`) is interpreted by the schedule, the critical path and progress alike, so it
passes the admission test; `modules/estimation/` keeps the editors and the `estimate` verbs,
and `modules/schedule/` the whole `schedule` noun. Once it
was here, the `days_for` threaded through the root, the order tab, the layout sorts and the
time module carried nothing but the one reader, and went: the walks default to
`estimate.read`, and a function parameter stays only where a caller means other days —
calendar days stretched by a focus, the simulator's world, a folded stack's blocks. The time
module's view of status (review and merge as work in flight, `status.in_flight`) moved with
it, and once the wait joined the tier (*Planning owns what a step is*) `wait_of` went the same
way, leaving `Readers` only agent-ness, the milestone label and the key — planning facts too,
which its fields now default to. The collector vocabulary
(`planning/scope.py`) moved up too, while the walk it reads, `cone()`, stays in
`domain/ordering.py` beside `upstream()` — the graph may not import the tier. Date words
(`planning/dates.py`) live in the tier because its phrases print a day; the chart axis is
drawing and lives in `cli/report/axis.py`.

### Planning owns what a step is

**The kind aspects are facts in `planning/`, and the key's letter comes from one ranking.**
Milestone, feature, check, wait, start, branch cut and landing, review and the agent mark
are each a file in `planning/` (`milestone.py`, `feature.py`, …) under the module id they
always had; the module that edits each keeps its section, its verbs and its UI. Before,
the ranking *milestone over feature over check over wait over cut over review over agent*
was written six times in the composition root, once per question that read it.
`planning/kinds.py` now holds it once, as `RANKING`: a `Kind` enum, the key's letter and
the predicate, coarsest first. `key_of` and `kind_word` read that list and nothing else.

**One ranking, not one policy.** The structural review first proposed that every question
about a kind read one ordered list; Codex's correction, accepted in its §12, was that only
the key and the kind word share a ranking. The others are separate policies that *read*
the facts and stay written out in the root, each where a reader can check it by eye: the
primary glyph says who works a step (an agent's spark, a wait's clock), the medallions show
several marks at once, the body tone lets *done* outrank any kind, and the scope rules say
where a collector's walk stops. Folding them into the ranking would have made each one an
exception to it.

### What holds the tier and the workflows in place

A rule kept by convention erodes, so the review's guards are tests (`tests/test_architecture.py`,
rules 4 and 11–13). **Import facts, inject effects**: a module may reach another through
exactly two files at the top of its package — `aspect.py`, what a step's entry means, and
`workflows.py`, a complete verb returning a `Change` — and nothing they reach, followed to
the end rather than trusted by filename, may load Qt or `framework/`. Anything effectful
(the store, a clock, a launcher) still arrives on a `Deps`, because a test needs a fake for
it; a `workflows.py` builds and its caller persists, so it imports no `domain.store`. The
module graph those imports draw is acyclic, and a failure names the cycle edge by edge:
a cycle is two modules that have to change together and could not move apart again.
Two ceilings record where the move started on 4 October and may only fall — the root's
lines, and the domain commands built and pushed in place outside a `workflows.py` (a
verb that builds its own command is one a second surface will copy). They are lowered by
hand, never raised. The ids a module stores data under are pinned as a set of values, so
a package can move or be renamed and no plan on disk loses its entries. And what `planning/`
interprets is a list, `PLANNING_ASPECTS` (rule 14), so admitting an aspect is a diff somebody
reviews; past about fifteen entries the tier has become "the important aspects" and wants
rethinking rather than another line.

**The root is wiring, split by cluster.** Once the logic had owners, `default_modules()` was
still one function of two thousand lines — forty closures and twenty-five modules built
"before the list" — so where a module's wiring lived was a search. It is now the order alone:
a shared `_Root` (the services, the library, the concrete store, the location roles and the
few seams several clusters read), then one builder per cluster — `_branches`, `_agents`,
`_graph`, `_knowledge`, `_project_tabs`, then the list's own `_shell`, `_assistants`,
`_projects`, `_aspects`, `_step_properties`, `_machine` — each building in the order its
neighbours need it and returning what they read. Building the agents before the graph editor
and the editor before the feature module turned three forward references into plain
arguments; the one true cycle, Coverage and the Specs tab pointing at each other, stays a
lazy lambda inside `_knowledge`. A lambda that wraps a built object's method is kept where a
test patches the class after the build (Sync's reconcile hand-off). Registration order is the
list's and nothing else's, and the split did not move it — the same 52 modules in the same
order. Building inside the root's one file is deliberate: rule 4 lets only
`modules/__init__.py` import a module's Qt half, and a builder in a file of its own would be
a second root.

**A package that registers nothing is surface all through.** The briefing is the case that
needed it: what an agent is told reads a dozen modules' facts, and it lived in the root as
eight callbacks wired onto Run Agent's `Deps` and again onto `agent prompt`. It is now
`modules/agent_briefing/`, which reads those facts through each owner's `aspect.py` — but
Run Agent must import the briefing in turn, and a briefing is neither an aspect nor a
workflow; naming its files after either would make the filename lie. So rule 4 names the
shape instead: a package with **no `module.py`** registers nothing, every file it holds is
checked headless the way an `aspect.py` is, and another module may import any of them. The
harness and theme-provider packages already had that shape. The edge points Run Agent →
briefing and never back: the run-naming helpers the briefing needed (`run_name`, `workdir`,
`worktree_path`) moved out of the launcher into `agent_briefing/worktree.py`, which is what
kept the graph acyclic — the structural review's §4 drew the edge the other way for exactly
those helpers. What the briefing cannot import arrives as a plain value: the branch plan,
which the branches module reads and caches, and the location roles, the root's registry
over every module's `roles.py`. `tests/cli/test_briefing_golden.py` holds the briefing to
the byte, which is how the move was shown to change no text.

### A file name has one meaning

The rule is CLAUDE.md's *Two surfaces, one vocabulary*. The checks are rule 15 and the
headless-file test in `tests/test_architecture.py`.

A newcomer has to be able to tell where a surface is from a directory listing, which is the
one view of a package everybody has. A name that means a tab in one package and a modal in
another tells them nothing. (*decisions.md* has what it replaced.)

**A Qt file's name says its role:**

- `activity.py` (or `<x>_activity.py` where a package has several tabs, as `debug` does) is
  a tab, with the widgets only that tab hosts;
- `dialog.py` or `<x>_dialog.py` is a modal, modal lists included;
- `scene.py` is a `QGraphicsScene`;
- `panel.py`, `status_widget.py`, `section.py` and `settings_page.py` are what CLAUDE.md lists.

**The first three are checked from the class hierarchy.** An `ActivityBase`, `DialogFrame`
or `QGraphicsScene` subclass, followed through subclasses across files, must sit in a file
named for its role. A test reads the classes rather than trusting the names, because a
convention a reviewer has to remember is the one the next feature forgets. The last four
have no base class to key on: a section is an `InspectorSection` value, and a status-bar
widget is any widget. They stay documented.

**A mixed file gives up its dialog, not its logic.** `repo_picker.py` keeps the picker and
`repositories_folder.py` the remembered folder; their dialogs, with the code only a dialog
uses, sit beside them (`repo_list_dialog.py`, `repositories_folder_dialog.py`), so the
headless remainder imports no dialog. The design example's sample rows are
`design_sample.py`, without which the dialog and the tab would import each other.

**`HEADLESS_FILES` is package-relative for the same reason.** Matched by bare name,
`schedule.py` means whichever file has that name in any package, and a rename leaves the entry
matching nothing and the file silently outside the rule. The test lists generic roles once
(`HEADLESS_ROLES`: `cli.py`, `aspect.py`, `report.py`, …) and every other file by package and
path. A listed path that does not exist fails the suite.

**`tests/modules/<package>/` mirrors `modules/<package>/`**, and a test folder must name a
package. That turns each area file's `paths:` into one `{src/dplanner,tests}/modules/{…}/**`
glob rather than a hand-kept list of test files. A test of the composition root, or of
several packages at once, stays at `tests/modules/` beside the root it tests.

## Pressure points, named before they hurt

A whole-codebase review (2026-08) found the architecture holding; these are the places
where growth has a known cost curve, written down so the feature that crosses the line
recognises the moment. None needs action today.

- **`agent_briefing/blocks.py`'s `step_sections()` grows one hand-rolled block per aspect**
  with a briefing presence, each with its own empty-check — nine today, past the six this
  note once named as the line. The exit is the shape `cli/lint.py` and `cli/authoring.py`
  already use: each module exports a Qt-free block builder and the list is assembled once;
  make that move rather than adding a tenth `if`.
- **The step panel's tab order is a cross-module number line.** Each aspect module picks its
  `InspectorSection(order=…)` against numbers that live in six other packages — the GitHub
  module's comment literally names two of them. Fine at this size, and
  `tests/modules/test_aspect_editors.py` pins the resulting sequence; the tenth aspect
  author will have to read seven files to pick a number, and that is the moment the order
  belongs in one place (the composition root already knows it).
- **The index tree has two shapes of project folder.** `projects/index.py` nests
  contributed entry rows under each project, greys unavailable ones and restores the
  selection across a rebuild; `framework/project_list_segment.py` is the plainer cousin
  the Tests and Docs folders share — the third user was the moment the
  rebuild-and-restore-expansion half was extracted. It takes a `LeadingRow` above the
  projects (Tests' *All Projects*) and `ChildRow`s under each (Docs' *Documentation* and
  the notes module's *Implementation notes*, each opening its own tab — the second handed
  across as `DocsDeps.more_rows`, so the folder's owner never learns what it lists); a
  child row stands for its project exactly as the project row does, so the Project menu
  works from it. The
  richer folder is deliberately not folded in: nested contributed entries are a different
  problem that happens to draw rows too.
- **Every per-gesture cost is a constant, and the constants add up.** A click on a step
  costs the same nine section shows at 25 steps as at 400, a details open the same
  thirteen widget trees, a full collection the same quarter second — *How the
  application scales* has the table and the order to take them in. The next surface
  that shows on every selection, or listens to the whole library, is the one to hold
  to those rules.
- **`canvas` accretes by construction.** *Modules never import each other* means a
  feature that lives *on* the canvas — named layouts, sorts, the minimap — cannot
  become its own package, so the surface-owning module grows instead (a quarter of all
  module code). The answer today is internal seams: Qt-free files per concern, split item
  and mode files, the keymap as a table. If a canvas feature ever needs its *own* Deps and
  registration, that is the day the module boundary rule earns a canvas-extension registry.
- **Every GUI test builds all modules.** The `services` fixture constructs the real
  composition root so a test can never drift from production wiring — a strong property,
  deliberately kept. The cost grows with the module count, and the `Deps` dataclasses are
  exactly what would make cheap isolated module tests possible; nothing uses that yet.
  If suite time becomes the complaint, the seam is already there.

## Where this is going

- **A second edge kind that can be drawn rather than only typed.** The mode stack is where it
  goes: a `relates` variant of the linking mode, and nothing else moves.
- **Rebindable keys.** `modules/canvas/keymap.py` is the table a settings page would
  read; nothing reads it yet, which is the only reason it is a constant.
- **Reports** — new folders in the index tree, which is the shape the registry was built for.
  `dplanner schedule show` is the first of them, and it lives in the module that owns the
  dates (`modules/schedule/`, with the rest of the `schedule` noun) rather than in the one
  that owns the table. (The schedule that knows about
  parallelism, once listed here, landed as `parallel_finish` and the time estimates tab —
  see *Time estimates: two worker pools, one greedy simulation*.)
