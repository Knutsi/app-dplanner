# DPlanner's shape, and why

`CLAUDE.md` carries these rules in their short, imperative form — this file is where the
reasoning lives, so the short form does not have to be taken on faith.

app-framework's `docs/index.html` documents the machinery this is built on — the ten
registries, the origin token, the two version axes, where state lives. This document covers
only what DPlanner added on top, and the reasoning is the point: the code shows *what*, and
this is the file for *why*.

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
is something Ctrl+Z could honestly reverse, so File ▸ New Project, Open Projects and Remove
from Library apply their model change directly with their own origin — the same discipline
as syncing an external fact, below. The membership verbs live with the project verbs
(`modules/projects/`): New Project is the Project dialog in create mode and Open Projects
browses a plan repository, and both start from the same question — *which plan
repository?* — answered by one picker. The library module keeps only the question of
*which library*.

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

### The window is a word, and everything else is the CLI

`dplanner window` opens the application. Every other command line is the CLI: a verb runs,
a word the CLI does not know is refused with exit 2, and a bare `dplanner` prints the help.
It was the other way round — the window was the default and the CLI ran only when the first
word was a registered noun — until agents driving the skill ran `dplanner` bare to see the
usage, or mistyped a noun: each time a window opened on the developer's desktop, and the
agent's shell hung until somebody closed it.

The fix is a flipped default rather than an added check, because the asymmetry is total. A
person pays one word, once, and a launcher pays it in a file; an agent that guesses wrong
pays a stray window and a hung shell every time, and can see neither. So the rule is *a
word*, not a test of the environment:

- **Not a terminal test.** A `.desktop` launcher and `spawn_instance` (stdout to `DEVNULL`)
  have no TTY either, so both would need an explicit word anyway — the heuristic buys
  nothing and costs isatty mocking in every test.
- **Not an environment variable from the agent wrapper script.** That covers the agents
  DPlanner launched itself and not the one the developer started in a terminal, which is
  the case that was reported.
- **Not a vendor's variable** (`CLAUDECODE`, …). Every new agent would be a new `if`.
- **Not a registered `CliCommand`** (`library open`). Its `run` would import Qt from a
  module's Qt-free `cli.py` — the upward import `HEADLESS_FILES` exists to refuse.

`window` is the word because it is what this codebase calls the surface — "a window, or a
verb", "one per window" — and because no agent task contains it. It is not a noun and the
skill never renders it: `entry.py` dispatches on it, the top-level `--help` names it, and
`tests/cli/test_entry.py` reserves it against a future noun. Two consequences follow. Qt's
own `-style` and `-platform` come *after* the word, since the first word is the decision.
And a bare `dplanner` prints the whole help at exit 2 — git's convention — because
argparse's own "the following arguments are required" names neither the nouns nor the word,
and the agent that ran it bare was asking for exactly that list. A by-product: the window no
longer builds the whole command inventory just to learn it is not a verb, and the CLI no
longer builds it twice. `python -m dplanner` and `spawn_instance` go through the same door.

**And the word refuses from inside an agent's shell.** The second incident was the first
one's consequence: an agent ran `dplanner show F3` while the window was still the default,
Claude Code kept the window it opened as a background task, and the developer used that
window for an hour — launching three more agents from it. Each inherited the shell's
session markers (`CLAUDECODE`, and the variables that name a session's parent), and a
`claude` started under them makes itself a *child* session of the one that set them: no
transcript on disk, ended when the parent's turn ends. When one agent's `pkill` (below)
killed the first agent, its background window died with it, and every child session went
too. So `entry.py` checks `AGENT_SHELL_MARKERS` before it opens a window and refuses with
the reason. This *is* the vendor-variable check the list above declined — but for a
different question. Dispatch asks *what runs*, and there a missed vendor is a wrong
answer; this asks *who owns the window*, and a missed vendor is a missing guard, which is
the same as today. One row per agent CLI known to mark its shell, and the launcher scrubs
the same markers when it spawns (*The peer is a top-level session*, below), for a window
that got its environment some other way.

**`dpw` is the word typed for you, and the desktop gets a file.** A person launching the
window from a shell every day pays the word every day, so `dpw` — a second entry point,
`entry.window_main`, prepending the word and going through the same door and the same
refusal — is the alias nobody has to write. It is a `gui-scripts` entry rather than a
script because of what an applications menu needs: on Windows a gui-script is an
executable with no console window behind it, which is what a Start Menu shortcut should
open. The desktop itself wants neither word but a file, and each platform's is different:
a `.desktop` entry in the XDG applications directory on Linux (named `dplanner.desktop`
because that is the `app_id` the application declares, and how a compositor matches a
window to its entry), an application bundle in `~/Applications` on macOS whose executable
is a shell script handing over to `dpw`, a Start Menu shortcut on Windows written through
PowerShell because a `.lnk` is a COM object. `cli/desktop.py` is one class per platform
behind one contract — where it goes, what it opens, how it is taken out — with the home
directory, the environment and the process runner as arguments, so every platform's
launcher is built and read back in the suite on whatever machine runs it. The launcher
opens `dpw` by absolute path, since a menu has no PATH to resolve anything with; which
`dpw` is the one beside the `dplanner` running the command, so the launcher opens the
DPlanner it was installed from, and `desktop status` reads *stale* when it opens another.
The launcher is written in the same go as the command (*Installing is one act*, below), and
points at the `dpw` uv just installed — `uv tool dir --bin` says where, rather than looking
beside the build that happens to be running, which may be a checkout's `.venv`. The skill
names neither `dpw` nor the launcher's verbs' target: an agent has no business opening the
window, whichever word it is.

### Installing is one act, and the pieces stay

Three things have to be in place before DPlanner is usable: the `dplanner` command on PATH,
a launcher in the applications menu, and the agent skill. Each had a verb and the first two
had a dialog, and they drifted — a machine with the command and a skill from a build three
weeks old was the ordinary case, and no surface could see it, because no surface asked more
than one of the three questions.

So there is one reader and one writer over all three (`cli/install.py`), and `dplanner
install all` / `install status` / `install remove` and *Tools ▸ Install DPlanner…* are its
four callers. `desktop …` and `skill …` are untouched: the one act is a composition of the
pieces, not a replacement for them, and a person who means only the skill still says so.

- **The reader lives in `cli/`, not in `modules/install/`.** It is what the verbs need, and
  `cli/` may not import a module — so a status reader under the module would have had to be
  copied or reached for illegally. It also sits beside the two files it reads, and the
  module's Qt half imports it the way it already imported `cli.skill`. The checklist's
  `checks()` will read the same function from the module's own Qt-free half.
- **The reader runs no subprocess.** The dialog refreshes on it after every act and the
  checklist will probe with it, and neither can afford a process — the same rule as *No
  subprocess in an action state*.
- **The command's state is `installed` or `missing`, never `stale`.** Whether the `dplanner`
  on PATH came from this build cannot be told without running it, and a status read may not.
  The launcher and the skill keep all three states, which they could already answer.
- **The writer never stops at a failure.** Each of the three reports its own line, so a
  machine ends up as current as it can be rather than as current as its first problem
  allowed; `install all` exits 1 when any piece failed, having done the others.

Two rules keep the command from shadowing an install somebody else made, and both say so
rather than acting silently. **A worktree build never repoints it**: `uv tool install
--editable` into a branch's scratch checkout breaks the moment the worktree is removed, and
every agent now works in one — this is what makes `install all` safe for an agent to run.
**A `dplanner` uv did not install is left alone**: a pipx install, a system package or a
venv is somebody's decision, and `uv tool dir --bin` against the resolved command's own
directory is how that is asked — uv's answer, never a guess at its layout.

**Removing takes out the launcher and the skill and leaves the command.** `uv tool uninstall
dplanner` uninstalls the program running the verb; that is a deliberate act of its own, so
the command's line names the one command instead of running it — composed from the same argv
the installer would use, so the text cannot drift.

## The index tree

The template's sidebar was a tab set: one page per module, one visible at a time. DPlanner
replaced it with a single tree whose folders come from an `IndexSegmentRegistry`, and
deleted the tab set rather than keeping both.

The argument for the tree is that it shows the library's *shape* — projects, and the steps
under them — where a tab set shows one feature and hides the rest. The argument for deleting
the old one is that anything a page could hold is a folder here, so keeping both would have
been two navigation mechanisms competing for the same 275 pixels.

The tree is not a slot in the window any more; it is one **panel** anchored in the left area
(below), which is why it can be moved and hidden like anything else contributed to the window.
Three things still live in the panel rather than in each segment, because a shared tree is not
the same problem as a stack of independent widgets: **selection is published exactly once** (Qt
selection is per-tree and `ContextService` has one selection scope, so segments would
otherwise fight over it); **a segment supplies its own menu** rather than the spec naming a
`MENU_STRUCTURE` menu, because a menu name is application vocabulary and has no business in
a framework spec; and **expansion state survives a rebuild** through shared helpers, because
rebuilding on change is the normal case and that bookkeeping is what every segment would
otherwise copy — and survives a *restart* too, which is *Where the user left off is
remembered by key* below.

### A click is a glance: preview tabs

A single click on an entry row opens its surface as a **preview tab** — VS Code's
arrangement, adopted whole rather than reinvented. The host (`framework/tabs.py`) keeps at
most one preview; the next preview replaces it, and a deliberate act keeps it: activating
the row again (a non-preview open of the same URI), or moving the tab. A preview-open of
something already open is a plain focus that changes nothing — the tab you kept stays kept,
the preview stays where it was.

Two consequences fell out of making every step idempotent. **The double-click needs no
timer**: click one previews, click two's activation pins, and the trailing click event Qt
fires after an activation lands on "already open → focus" and disturbs nothing. And **"jump
to the thing that is open" needed no code at all** — the host already deduplicates by URI,
so a click on an entry whose tab exists anywhere simply focuses it, in whichever pane it
lives. The preview's mark is an italic title, painted by the tab bar itself so the host's
active-pane dimming keeps working underneath it.

The gesture reaches the segment through a fifth `IndexSegmentView` hook, `clicked`, and the
panel forwards only plain left-clicks — a Ctrl/Shift-click is building a selection, and a
right-click is asking for a menu. On the entry it is `open_preview`, a second callback
beside `open`, both closed over the owning module's `open(..., preview=…)` by the
composition root; `None` is an entry whose surface has no preview form.

## Where the user left off is remembered by key

Two things follow a person across a restart: which folders in the index tree were open, and
which tabs the window had. Neither is a property of the plan — a colleague pulling the
repository must not inherit somebody's open tabs — so neither goes near the project
directory. They live in the per-user store, and `framework/user_config.py` now has two
scopes because two different kinds of thing are being kept.

**A preference is the person's; where they left off is the library's.** "Reopen my tabs" and
"which model" follow the user into every library they open: that is `get_global`. "These
tabs were open, these folders were unfolded" is true of exactly one library, and restoring
library A's tabs into library B would be nonsense: that is `get_scoped`, under a scope
`library_scope(path)` derives from the library file's resolved path. The scope is a digest
rather than the path itself only because a QSettings key is a `/`-separated tree, and a path
put in one whole fans out into a directory's worth of empty groups.

### Restoring by key is what makes a changed library safe

Both halves write down **node ids**, never positions, and restore by looking each one up.
That single choice is what answers "what if the library changed underneath?" — a remembered
project id that names no row is simply not there any more, so the tree comes back with fewer
folders open, and a tab whose project was deleted is not reopened. There is no validation
pass, no version stamp and no migration, because the check *is* the lookup. The obvious
first design — saving the tree's shape, or tab indexes — is the one that comes back wrong
rather than short.

Reopening a tab has two more ways to be stale, and each is a question asked of somebody who
knows the answer. The activity *kind* may be gone from this build, which the tab host
answers (`can_open`); the *target* may be gone from the model, which the composition root
answers by handing the module `Library.has` — so `modules/reopen_tabs/` never learns what a
project is. A third guard catches whatever is left: a factory that raises costs the user one
tab and never the launch, which is the one place in this codebase where a deliberately broad
`except` is the honest answer.

### Written on every change, not at close

Both halves write as the user works rather than on the way out, and the reason is the reload
path rather than crash-safety (though it covers that too). Reloading a library builds the
new window *before* closing the old one — see *Two writers, one folder* — so a list written
in a close hook would be written **after** the window that was going to read it, and every
reload would bring back the tabs from one session ago.

That is also why `TabHost` grew `tabs_changed` beside `activity_changed`. The older signal
is about which tab is *current*, and `_announce` deliberately says nothing when that has not
changed — so closing a tab in a pane the user is not on, which is the ordinary way a project
being deleted takes its tab with it, changed the list and announced nothing. Not a bug in
`_announce`: a second fact the host had no way to say.

### What is deliberately not restored

Pane splits and the preview tab. A split is an arrangement of the *window* around the work,
not part of it, and everything comes back pinned in one pane — reopening a glance as a
glance would mean the next glance silently replaced a tab the user thought they had. The
tree's folders are restored, the tree's *selection* is not: a selection is what the user is
doing right now, and the panels that follow it would be answering for a click nobody made.

### One is the framework's, one is a module's

The index panel keeps its own folders (`framework/index_panel.py`), the way `panels.py`
keeps its own areas: it is the framework's own surface, its rows arrive one segment at a
time as modules register, and each folder restores as it arrives rather than after some
later pass. Tabs are `modules/reopen_tabs/`, because reopening one needs a preference and a
question only the model can answer, and because it must run after every activity factory has
registered — a position in `default_modules()` with a comment saying so.

Only the tabs have a switch (*Settings ▸ Startup*). Folders are cheap to close and nobody
has ever wanted them shut on purpose; a window that reopens six tabs is a real opinion about
how someone starts their day. The list is kept even while the switch is off, so turning it
back on returns the session they last had rather than one from whenever they turned it off.

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
handing it a constructed `Context`, and `tests/modules/test_project_editor.py` does exactly
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
be learned. The user who saw *Open Specs* yesterday and cannot find it today has no way to
know whether the feature is gone or their context is wrong — a greyed entry answers that
question before it is asked. It also keeps every surface stable: a toolbar row that reflows
as the selection changes cannot be read, and the menubar's separators stop jumping.

One documented exception: a verb whose *opposite* currently occupies its slot may hide.
`steps.link` stands down when the pair is already linked, because *Remove Link* is the verb
that belongs in that position and a greyed "Already linked" beside it would state the same
fact twice. The label still rides on the hidden state — the canvas status bar reads it after
a refused drop.

The presenters split accordingly: the menu bar, toolbars and `build_menu`'s right-click
popups all render a disabled action greyed; only the command palette filters to what is
runnable, because a fuzzy search over verbs that cannot run helps nobody.

### A submenu is one child menu per title, and groups separate inside it

A spec names a `menu`, a `group` and optionally a `submenu`, and for a long time the child
menu was keyed by *(group, title)*. The Step menu paid for it in the open: `test` (Add,
Archive, Put Back) and `test_result` (Mark Ok, Failed, Skipped, Clear) both named the submenu
`Test`, so the menu rendered **two child menus with the same name**, one under the other,
with a rule between them. `CLAUDE.md` described the behaviour the keying prevented.

The fix is to say what was meant: a submenu is one child menu per title within a menu, and a
**child menu is a container of the same kind the menu is** — it holds the menu's groups, and
a rule is drawn where its entries change group, under the same never-leading, never-dangling
rule the menu bar has always applied to itself. Both presenters do it (`framework/menubar.py`
pre-creates a hidden separator per group boundary in every container; `action_menu.fill_menu`
draws one as it goes), and `tests/framework/test_menubar.py` asserts they render the same
shape, because a menu bar that disagreed with a right-click is the one thing four presenters
of one registry exist to prevent.

Two things fall out of it that the Step menu needed. A group that only feeds an existing
child menu adds **no rule to the menu itself** — only the child's menuAction carries a group
there — so "what a test did" can be its own group without costing the menu a line. And
several submenus can sit in one group as a band: the Step menu's `classify` holds Type,
Status and Test with no rules between them, because a rule between two adjacent child menus
separates nothing that their names do not already separate. That is what took the canvas's
right-click menu from eight rules to five. The cost is small and worth naming: a child menu
sits at its first entry's `order`, so sibling child menus in one group have to claim bands of
it (Type the 10s, Status the 200s, Test the 300s — written down in `dplanner/menus.py`).
`order` still only ranks inside one group; it is now also how two child menus in that group
know which comes first.

### An action may carry a glyph, and only the pop-ups paint it

`ActionSpec.icon` is a painter — `(QColor) -> QIcon` — not a QIcon, and the presenters that
render it are the ones built fresh on every open: `build_menu`, `append_action`, a toolbar
button's dropdown. The menu bar deliberately does not, and the reason is the same trap as
*The palette a painter is handed is a snapshot*: its QActions are created once and live for
the application, so a colour baked into one at startup would still be there three themes
later. A pop-up has no such problem — it is thrown away when it closes.

It earns its place on the Type submenu, where each toggle wears the very medallion its node
will wear, and it is what lets the aspect bar paint the same glyphs (through the specs, so
they are the registry's and not a copy) instead of the panel hand-building a list of
aspects it is not allowed to know.

### View is the window; Graph is the canvas

The graph editor's own verbs — Sort, Layout, Divide, Region, Frame, the marks, Snap to Grid
and the Background — used to be a `canvas` group inside **View**, and one inside **Project**
for regions. That made View half a window menu (panels, tabs, theme, zoom) and half a
drawing-surface menu, and it left the surface this application is mostly *about* with no
heading of its own: the fastest way to a divide was the command palette, which then said
only *Vertical*.

They are a top-level **Graph** menu now, in three groups: `arrange` (the Sort, Layout and
Divide child menus — moving cards, from the wholesale to one cut at a time), `regions`, and
`look` (what is drawn without moving anything). View went back to being about the window.

**What did *not* move is the point of the split.** Connect, Link, Unlink, Isolate and the
Redirect pair stayed on **Step**, because a link is a fact about the steps it joins, and
because the canvas's right-click renders the Step menu (*A right-click renders a menu, never
a copy of one*) — moving them would have taken the graph's most-used verbs off the graph's
own context menu to file them more tidily. Lasso stayed in Step's `navigate` group for the
same reason: it selects steps. The test is not "which surface does this run on" — every one
of these runs on the canvas — but "what is it about": a step, or the drawing of them.

### The command palette says where a verb lives

A palette row used to be the spec's label and its shortcut. That works for *Frame Graph* and
fails completely for *Vertical* and *Horizontal*, which are written to be read under the word
*Divide* and say nothing without it. The label cannot absorb the missing half — the menu
would then read *Divide ▸ Divide Vertically* — so the row carries the **menu path** instead,
on a second line under the name, with the shortcut right-aligned beside the name and the
verb's glyph at the left (`framework/list_rows.py`'s two-line row, the same one every rich
list here uses).

The path is the menu and the submenu, never the group: a group is a module's word for a band
of entries and is not a heading anybody ever sees, so printing it would name something that
does not exist on screen.

Once the path is on the row it is worth searching, and the ranking is the whole design: a
match on the *label* always outranks one that needed the path, as a `(where, -score)` sort
key. So "vertical" still puts *Vertical* first, and "divide vertical" — how somebody who
remembers the submenu and not the entry looks for it — finds it at all.

### Edit verbs belong to the surface whose things they act on

The Edit menu holds Undo and Redo from the app shell, and then Cut, Copy, Paste, Duplicate,
Delete and Select All — and those six are the graph editor's, registered by
`project_editor` as ordinary `ActionSpec`s. The alternative was a dispatching layer: a
generic `edit.copy` whose meaning is supplied by whichever surface is current. It was not
built, because the machinery above already gives that behaviour for free. A state callback
reads the context, so Copy is enabled exactly when steps are chosen; *disabled, never hidden*
keeps the menu stable while it is not; and a greyed menu-bar action's shortcut does not fire.
A dispatcher would be a second action registry with one registrant. **The moment for one is
when a second surface needs Cut/Copy/Paste** — a shortcut can be owned by one enabled QAction
at a time, and two surfaces enabled at once would be Qt's *ambiguous shortcut*, which fires
neither. Until then, a second surface's verb is a second spec with a distinct label, and the
context greys the one that does not apply.

What they act on is what Delete acts on: `verbs.chosen_steps` — the selected steps, else
the focused one — so Cut and Copy work wherever Delete does, a table's right-click included.
Only Paste needs a canvas: it is the target. Its state never reads the clipboard;
`ClipboardWatch` counts what the clipboard holds when the clipboard changes and re-emits
the context, the same idiom that keeps the Undo label current.

**Standard keys are menu shortcuts here, and Delete is not.** The canvas-keymap rule in
`CLAUDE.md` is about bare keys: an `H` on a menu-bar QAction eats a keystroke in every
editor. Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+D and Ctrl+A are different, and this was measured
rather than assumed: `QPlainTextEdit` and `QLineEdit` claim all of them through
`ShortcutOverride`, so a window-wide menu shortcut never fires while an editor has focus —
the property `tests/modules/test_appshell.py` pins for Ctrl+Shift+Right. A table claims
none of them, but every table here is a tab, so no table ever competes with a canvas for a
key, and a table has no Ctrl+X of its own to lose. Delete is the exception in the other
direction: a bare `Del` on the menu bar would fire in every list in the window, and
`QKeySequence.StandardKey.Delete` binds Ctrl+D as well as `Del`, which would collide with
Duplicate. So Delete keeps its canvas key and the Edit-menu entry shows no shortcut — and
that entry is `steps.delete_edit`, the verb's second seat: `steps.delete` stays on the Step
menu because the canvas, four tables and the toolbar render that menu by name.

**Deleting asks nothing any more.** A prompt in front of an undoable verb teaches the wrong
lesson — that the gesture is dangerous, when Ctrl+Z is the safety net — and the CLI's `step
remove` has said so since it existed. Steps and regions both lost their prompt in one pass,
because the Delete key runs whichever of them the selection calls for and one gesture should
not sometimes ask. The prompts that remain guard what undo cannot reach: removing a project
from the library, a release, an outside edit.

### Copy and paste are a clone through the same command

A copied step is a `StepClip` (`project_editor/clipboard.py`): its title, its links, every
module's data and prose, and the bytes of every file beside it, plus where it sat. A paste
turns a list of clips into **one** `CompositeCommand` — the same object the window pushes
and `dplanner step duplicate` applies — so a paste is one undo step and one transaction.
Duplicate is that paste with the clipboard left alone: what the user had copied stays copied.

Four rules, each a decision:

- **A copy is a clone.** Every clone has a fresh id and an empty folder name, so the store
  mints it a directory of its own. Reusing the id was considered and rejected: in the same
  project it collides with the store's record of where the original lives, and in another it
  makes `library.has()` resolve a step that is not there.
- **Only the links inside the copy travel, and they go through `SetEdgesCommand`.** The
  pasted set keeps its internal arrangement and arrives disconnected from everything outside
  it, in the same project or another: links *between* copied steps are remapped through the
  old-to-new map, and a link to anything else is dropped. Keeping an outside link where it
  happened to resolve was tried first and read as a bug — a duplicate that silently waited on
  its original's upstream — so wiring the copy in is the user's next move, never a guess the
  paste makes. Setting `step.edges` on the clone before the add would skip `link_refusal`
  and `edges_changed`, which is why the links are commands in the same composite.
- **Files ride in the payload and are written after the command.** A cut removes the step and
  the next autosave's orphan sweep deletes its directory, so a paste after that has nowhere
  else to read an attachment from — the bytes have to travel with the clip. They are written
  once the clones exist, because a file area is settled from the node's place in the library;
  and they stay off the undo stack, the trade `FORMAT.md` makes for every attachment. The
  same pre-existing gap applies: a paste undone before the first autosave leaves an `assets/`
  directory behind, exactly as attach-then-undo-creation does today.
- **Two modules have a say, and the rest copy verbatim.** Aspect data is opaque here, so a
  module that cannot let its entry travel as it is hands in a `PastePolicy` from its Qt-free
  half and the composition root assembles the tuple (`_paste_policies`). The policies see the
  whole batch before any command exists, which is what lets `testing` mint ids across three
  pasted steps without a collision — an id is per project, and a copy that kept `T100` would
  make "T100 failed" name two things. `step_agent_run` drops its entry: a chip and a marching
  ring on a step nobody is running would be a lie. Everything else — status, estimate,
  spec figures, the milestone label, the PR ref — copies as it is, and two of those
  are judgment calls worth naming: a duplicated milestone shares its label, and a duplicated
  step keeps its PR ref, because a cut-and-paste move must keep both and a duplicate is rarer
  than a move. If that proves wrong, `github` is one more entry in the tuple. `feature` is
  the third policy: a copy drops the marker, because a record has one instance and the
  original keeps it — the same rule the drop and `feature set` refuse a second placement by.

Where the block lands is the canvas's business, through the same seam New uses: the anchor
is the last click, centred as New centres, and the block keeps its arrangement around it;
with no click yet — or for Duplicate — every clone goes one row below its original. The
arrivals then become the selection and the remembered point steps past them, so pasting
twice stacks two blocks rather than hiding one under the other.

### A child menu of data is rebuilt when it opens

The menu bar's QActions are created once and restated on every context change, and for verbs
that is right: an action's identity is fixed, only its state moves. A list whose *entries*
are born and die at runtime — the live agent runs behind Tools ▸ Agent List, a "Recent…"
menu anywhere — does not fit that shape. Registering an ephemeral `ActionSpec` per row would
mint action ids nobody manages, leak each row into the command palette, and need the
un-registration door the registry deliberately keeps shut (reload is a full rebuild for the
same reason).

The layout picker already answered this on the toolbar: saved layout names are data, so the
popup is built fresh every time it opens, and only the entries with a fixed identity render
through the registry. `DataMenuSpec` is that answer given to the menu bar. The spec carries
`menu`, `group` and `order` — placed and sorted by the same table as any action, so the
group separators need no new rule — plus a `fill(QMenu)` the presenter calls after clearing
the child menu on every open. Rows can never go stale because they never outlive a look at
them; a fixed verb inside the list (the Agent List's *Agents…*) renders through
`append_action`, never as a copy.

One deliberate asymmetry: a spec-fed child menu disappears when everything in it is hidden,
but a data child menu stays visible with an empty list. The menu itself is the capability —
*hidden means absent* — and its emptiness is the fill's own story to tell with a disabled
entry ("No agents running from this window"), which is the same greyed-teaches-the-
precondition rule every other presenter follows.

## Where a panel goes

The window has a centre — the tab groups — and three areas around it: **left, right and
bottom**. Anything anchored in one is a `PanelSpec` in `services.panels`, and the framework's
`PanelDock` puts it there. The index tree is one; the step detail panel and the project form
are two more. Right-clicking a panel's header moves it between areas or hides it, and
*View ▸ Panels* switches it back on.

**One panel, not one per tab.** This is the whole reason the dock exists, and it was learned by
getting it wrong: the step detail panel used to be built *inside* `ProjectActivity`, so opening
a second project built a second panel with a second set of aspect editors, and splitting the
window put both on screen at once. Two copies of one editor is not a richer window — it is the
same 360 pixels spent twice, and it raises a question with no good answer ("which one is the
real one?"). So a panel belongs to the window.

**It follows the user by reading the context, not by being told.** A panel that cares implements
`ContextPanel.show_context(context) -> bool`; the dock calls it on every context change and
takes the panel off screen when it answers False. Nothing pushes at a panel, and no panel
subscribes to the context itself — there is one subscription, in the dock.

That one decision is what makes "follow the focused tab" cost nothing. The rule that *only the
active pane may write to the selection scope* already existed, for a different reason; a panel
that reads the scope therefore shows the active pane's selection by construction, and
`ProjectActivity` **lost** its `_panel` field rather than gaining an "am I the visible one?"
check. It also means a surface nobody planned for gets the panel for free: the order table
publishes step selections and never had a detail panel, and now has one without a line of code.

**Areas, not draggable docks.** `QDockWidget` gives floating windows, tear-off drags and a
serialized layout blob nobody can read or reason about. What this needs is "put that over
there" — three fixed places and a menu — so that is what it has, and where each panel sits is
three legible `QSettings` keys under `layout/`.

**An area with nothing in it takes no space.** An empty right side is a wider canvas, not a
blank column, which is what lets two panels share one area and be mutually exclusive: the step
panel shows while exactly one step is selected, the project form shows the rest of the time,
and neither has heard of the other.

## A seam belongs to the splitter, and only a split window marks a pane

Two surfaces that meet at a splitter meet at a hairline. That line used to be drawn by the
*surface*: `#PanelAreaLeft` carried a `border-right` and `#PanelAreaRight` a `border-left`,
each area knowing which of its sides faced the tabs. It worked for the three areas and for
nothing else, which is why splitting the window produced two tab groups with no boundary at
all between them, and two panels stacked in one area separated by a caption and a dead band.

**The seam is the handle's, so there is one of them.** One `QSplitter::handle` rule reaches
every splitter the application builds — the tab host's, the dock's, each area's, the Specs and
Tests master-detail splitters — and every splitter written after it. The areas' borders came
off in the same change: a surface that draws its own edge where a seam already falls gets two
lines a pixel apart, and the second one is the one nobody meant.

**No splitter names a ground of its own, either.** A handle is 7 px so it can be grabbed, and
1 px of that is the line; the other 6 have to be *something*. A vertical handle can leave them
transparent and let the splitter's own ground through, so a panel area's elevated ground
arrives for free. A horizontal one cannot, so `$BG_BASE` is written into the rule — and beside
an elevated panel that leaves 3 px of the window's ground either side of the line, which reads
as a groove rather than as a mismatch. An exception for the one splitter it is visible on was
written and then deleted: one rule with no exceptions is worth more than three pixels, and the
exception would have had to restate the hover and drag states too or quietly lose them.

**The two orientations are built differently because Qt paints them differently**, and that is
worth knowing before touching the rule. A horizontal handle honours the box model: the line is
the content box and the ground either side is its borders, centred and exact. A vertical handle
fills its entire rect with the background and draws its borders *outside* it, so the same rule
turned on its side renders a seven-pixel slab. Nothing warns you; a stylesheet is silent about a
rule that renders wrong as it is about one that never matched. `tests/test_theme.py` therefore
**renders** a splitter in both orientations and asserts exactly one row of `$BORDER` across the
handle, which is the property, rather than reading the rule, which is not.

**A pane is marked only while there is another pane.** The group you are in wears a 2 px accent
edge along its top; one pane is the whole window and needs no mark, and the condition is the
same one that installs `_ActiveGroupWatcher` — because it is the same fact. Two cues now say
the same thing (the edge, and the dimmed titles on everyone else's tabs) and both are set in
`TabHost._paint_active`, so they cannot disagree.

The edge could not go on the group itself. `setDocumentMode(True)` means `QTabWidget` paints no
pane frame, so there is no `::pane` for a stylesheet to reach; and anything a widget paints for
itself is covered by its own children. Styling the `QTabBar` was never an option — QSS replaces
its whole native rendering, which is what the dimming relies on not happening. So each group
sits in a one-widget `_Pane` frame that carries an `active` property, and `group.parentWidget()`
is how the host finds it: a wrapper rather than a second map to keep in step.

One thing that is easy to get wrong, and has a test of its own: `_announce` short-circuits when
the active group and activity are both unchanged, and closing the *other* pane's last tab is
exactly that. So `_drop_group` clears the mark itself rather than trusting the announcement,
or an unsplit window would keep an accent edge on the pane that survived.

## A primitive carries the rule; a dialog's stylesheet does not

(`DESIGN.md`'s *Dialogs*, *Tables*, *Signalling* and *Bringing a surface up* are the
standard this settled; `modules/debug/design_example.py` is the living reference.)

For a year the rules lived in two places that could not see each other: DESIGN.md said
what a dialog looked like, and `theme.qss` said which dialogs looked like it. The accent
primary was styled inside a list — `#ProjectDialog #PrimaryButton, #MovePlanDialog
#PrimaryButton, …` — and the quiet secondary likewise, so every new dialog was added to
four comma lists or got Fusion, and three surfaces that set `#PrimaryButton` in good faith
got no accent at all. The list was not laziness. **A descendant rule outranks a bare id
whatever the order**: `#Dialog QPushButton` is specificity (1,0,1) and `#PrimaryButton`
is (1,0,0), so the moment a dialog's buttons were styled by name, its primary could only
be reached by naming the dialog again. The fix is one line and one fact:
`QPushButton#PrimaryButton` is (1,0,1) too, ties, and **wins by position** — so it is the
last button rule in the file, says so, and no dialog is named again.

That fact generalises. **A primitive names its parts, never itself.** `DialogFrame` sets
`#DialogBody` and `#DialogFooter`; `Table` sets `#Table`; the subclass keeps its own
object name for tests and for whatever one-off it needs. The stylesheet then reaches every
dialog and every table through a handful of constant names, and a new one gets the
designed look having touched nothing — which is the whole of what *done* meant for the
design-system step. The alternative, a rule per dialog, is what the audit found: two
button strategies (a `QDialogButtonBox` with the platform deciding order, a hand-rolled
footer with the accent), margins of 20, 16, 12, 8 and none, four dialogs that set initial
focus, one documented data-loss hazard from a footer whose default was *Clear*.

The same shape recurred wherever a rule had no home. Three copies of one `QTableWidget`
configuration disagreed on nine settings, and four widgets set `objectName("OrderTable")`
to borrow a look — two of them lists. Empty states came in five mechanisms, or none.
Every busy state was a `QLabel` rewritten by hand. Each of these is now one thing in
`framework/`: `Table` applies the configuration once and its delegate paints what a row
wears; `EmptyState.stands_in_for` is the one swap; `StatusLine` is the one busy, ok and
error; `UpdatingIndicator` follows the one `Debounced` a view already has. The review
rounds that followed added, on the same principle, a `Toolbar` whose verbs are glyphs
folding into a `…` menu, a `FilterButton`, and a `Spinner` that turns in a button's own
glyph slot so nothing ever moves. **A rule with
no primitive is a rule that is followed by whoever remembers it**, and the audit is the
measure of how many did.

Two decisions inside the primitives are worth their reasons. **A table's row height is
derived from the font, never a token**: the UI font is the platform's own, and the fixed
28 and 44 the old tables carried clip two lines at twelve points; the paddings are the
tokens, the height is computed and set on the vertical header — the one mechanism that
sizes a delegate-drawn row, learned the hard way in the Tests table. And **a refused
primary is disabled with its reason in the footer's status slot** rather than enabled and
refusing: that is the rule every greyed menu entry already follows, and a dialog with a
second grammar for the same situation is a dialog that teaches the wrong one.

`Debounced` grew a signal for the indicator, `pending_changed`, because the alternative —
the Time tab's wrapper that showed a label before `trigger()` and hid it as the first
line of the rebuild — was two statements paired by hand that a test could never see up.
While it was being wired, `flush_all` turned out to walk a `WeakSet` in hash order: a
flush that writes (the progress recorder) re-triggers the views that follow the model, and
whether that left one pending depended on which object was allocated first. It settles to
a fixed point now.

**The stylesheet is checked against the source.** Forty per cent of it described the
application the template came from — a corkboard, a binder, a reader, a zen mode — and two
of those dead names were quoted in DESIGN.md as the canonical look. `tests/test_theme.py`
asserts every `#Name` in `theme.qss` is a literal some widget sets, so a rule outlives its
surface by exactly one test run. The same test renders rather than reads where it matters:
a stylesheet is silent about a rule that renders wrong exactly as it is about one that
never matched, which is why the primary's accent is asserted from a pixel inside a widget
named `ProjectDialog`.

**Why the reference is a Debug surface and not a document.** A rule is read once; a
surface is opened beside the one being built and compared, in both themes, with every
state on it — the refused primary, the tinted row while picked, the indicator while a
rebuild is owed. Debug ▸ Design Example… and its table tab are that, over sample data,
and `docs/screenshots/f1-design-example/` keeps them rendered so a pull request can show the difference
it made. Every later step that touches a surface points at them; DESIGN.md's *Bringing a
surface up* is the list of what to compare.

## How a panel gets editors it has never heard of

The step detail panel shows a Details tab first — estimate, description, figures — and a tab
per remaining aspect — Ticket, Agent, Milestone — and nothing in it knows any of them exist.
Two seams do that, and they are worth naming because they answer every "feature A needs
feature B" question this application will have.

**Nobody hosts the panel.** `step_properties` owns it and registers it into `services.panels`;
where it sits is the dock's business and what it shows is the context's. Before the dock existed
this was a *consumer-owned Protocol* — `project_editor` declared `widget`/`show_step`/`dispose`
and the composition root handed it a factory — which worked, and cost a panel per tab. Anchoring
it deleted the Protocol, the `detail_panel` dependency, and the question of who owns the one
that is on screen. The Protocol-plus-factory shape is still the right answer when one module
needs a *widget* from another; it stopped being the right answer here when the answer to "how
many are there" became one.

**A registry for the contributors.** Aspect modules register an `InspectorSection` into
`services.inspector_sections`; the panel reads that registry when it is *built*, not when the
modules load, so a contributor's position in the composition root is free — its position
*ahead* of `step_properties` is not, and the root says so.

The composition root is the only place that knows both, and the wiring it used to need between
the two panel modules is gone:

```python
step_properties = StepPropertiesModule(
    StepPropertiesDeps(..., panels=services.panels, sections=services.inspector_sections)
)
project_editor = ProjectEditorModule(ProjectEditorDeps(..., panels=services.panels))
projects = ProjectsModule(ProjectsDeps(..., open_project=project_editor.open))
```

**Where provider-and-Protocol is still the answer.** The order view's start-date bar is
exactly the shape the panel used to have, and it survives the panel's move because the two
questions are different: a *widget one surface hosts* is not a *surface the window anchors*.
`estimation` provides a `create_start_bar()` and registers nothing for it, `step_order`
declares a `StartBar` Protocol of its own and takes a `Callable[..., StartBar] | None`, and
the composition root is the only file that knows both names. Why a `create_…` rather than a
registry entry is worth stating too: a registry is for *whoever turns up*, and this control
belongs to exactly one surface. When there is only one host, a registry is ceremony that hides
which module supplies what. (This is Writer's arrangement, borrowed wholesale — its
`segment_properties` serves a corkboard, a segment editor and a continuous editor the same
way, which is the evidence that the shape survives a second host and a third.)

**What the panel is not.** The project's name and summary are not a section. An
`InspectorExtension`'s whole contract is `show_target(step_id | None)` — one target vocabulary —
and making the project form a peer of the aspects would force every aspect editor to answer
"what if this is a project?" and hide itself — a second target vocabulary smuggled into every
editor. (`shown_for` is not that: it hides a section per *step*, inside the one vocabulary.)
It is a peer of the *panel* instead: a second panel in the same area, with its
own answer to `show_context`. Both ask `Context.selected_entity("step")`, so "there is exactly
one step in front of the user" has one definition rather than two that can drift apart.

**The same panel, briefly modal.** `steps.details` puts a second `StepPanel` in a dialog —
what every view's double-click on a step runs. That is not a breach of "one panel, not one
per tab": the rule forbids a panel *per surface*, where N tabs meant N copies on screen at
once; the dialog is one transient host the user summoned, disposed when it closes. Building
a second stack is the section contract's sanctioned use — one extension instance per host —
and the project panel's cards were already the proof. The dialog never reads the context:
it is opened *about* a step and stays on it, driven by `show_step` directly, which is what
lets a table row open it for the row under the cursor even when that pane's publish was
suppressed. The double-click the tables used to spend on reveal-in-graph moved to the Step
menu as `steps.reveal`, where every view's right-click already renders it. The dialog
carries no buttons: every edit inside it is already applied and already on the undo stack,
so there is nothing to confirm and nothing to cancel, and Escape closes it. It is also
where a fresh step is configured — New and the canvas double-click open it on the step
they just made, with the name field focused and selected.

**The project panel hosts the same contract, as cards.** A module with something to say about
a *project* registers an `InspectorSection` into `services.detail_cards` — the registry type
is deliberately instantiated twice, because "a module-owned surface that appears when it has
something to say" turned out to be identical for a panel tab and for a card stacked inside
one. The project panel renders each as a `ToolCard` and drives the same lifecycle the step
panel does, with a project id in `show_target`. That is what retired `project_repo`'s
provider-and-Protocol handover (`RepoFields` + a `repo_fields` factory on the editor's Deps):
the moment a second module wanted a project surface, "whoever turns up" became the right
question, and a registry is for whoever turns up. The `step_agent_instruction` card — the
project's standing instruction — is the second registrant, and each card must be registered
before `project_editor` builds the panel, which the composition root's list order says.

**The Details tab hosts the same contract, as blocks.** The first thing a step should show —
what it is, how big it is, what it looks like — was scattered across an Estimate tab and a
Description tab, each one click away. Now a module that wants its editor on the first tab
registers an `InspectorSection` into `services.step_details`, the registry's third
instantiation, and `step_properties` contributes one ordinary section labelled "Details"
whose extension (`modules/step_properties/details.py`) stacks the blocks: a caption from
each section's `label`, the widget under it, and the section's `stretch` deciding who gets
the leftover height — the description says `stretch=1` and takes the room, the estimate
stays a compact row, the spec module's read-only Figures gallery appears only on a step
that carries attachments (`shown_for`, re-asked on model changes exactly as the panel
re-asks it for tabs). Why a third registry instance and not a `placement` flag on
`InspectorSection`: a host is addressed by *which registry you register into*. That keeps
each host's vocabulary greppable, spares every host from filtering every section by a mode
field, and is the same reasoning that made `detail_cards` a second instance rather than a
`kind` — three hosts now, and the dataclass still has no idea. Because the composite is
just a section, the docked panel and the `steps.details` dialog render it identically for
free.

**A block host owes its stack a trailing stretch and a cap on the rest.** `stretch` on the
section says who gets the leftover height — the description, which is what a step's prose
wants and the estimate's spin box does not. When that block is hidden its stretch factor
can claim nothing, and Qt falls through to a rule nobody wrote down: a `QWidgetItem`
reports itself *expanding* when the widget's own layout is expanding, whatever the widget's
policy says, and every block's layout is expanding because a block adds its content with a
stretch of its own. So with the description off, the surplus was spread equally over the
blocks that remained — a 42 px name block became 328 px, its caption and field sinking to
the foot of it, an inch and a half from where the eye expects a field under its caption.

The fix is two halves, and either alone is wrong. A trailing `addStretch(0)` gives the
leftover somewhere to go; at a factor of **1** it would instead split that leftover with the
description block and halve the prose editor whenever the block *is* shown. And
`QSizePolicy.Maximum` on every block whose section declared no stretch takes away the
GrowFlag that was promoting it behind the data's back — which is the real statement of the
fix: **the cap is what makes `InspectorSection.stretch` authoritative.** Without it the
declared stretch is advisory and Qt's propagation decides, which is why the bug read as
arbitrary. `Maximum` rather than `Fixed`, so a panel shorter than its blocks still
compresses rather than clipping. `framework/cards.py`'s `CardStack` had the trailing
spacer from the start and never hit this, because no card asks for stretch.

## Expanding an editor is a second binding, not a copy

A side panel gives prose a few hundred pixels, and some descriptions and instructions are
screens long. The expand affordance (`framework/text_dialog.py`) opens the same document in
a modal editor sized to the screen — and the mechanism is the whole point: the dialog holds
a second `TextBinding` over the *same* `TextField`, nothing else. Each binding treats the
other's commands as foreign changes — the exact path a CLI edit or an undo already travels —
so the inline editor tracks the dialog keystroke for keystroke, one undo stack serves both,
and closing the dialog can lose nothing because nothing ever lived only there. The
alternative — copy the text out, edit, copy it back on OK — would have invented a second
place where prose lives and a Cancel button that discards work, both of which the binding
discipline exists to prevent. The affordance is a small corner button `attach_expand` pins
onto the editor itself, so every host — the Description block, the Agent tab's two
instruction editors, the project card — offers the same gesture without growing a header
row.

## A pasted image is an attachment and a link, not an embed

Every prose document in the application is markdown kept as **plain text**, and
`framework/markdown_highlight.py` says why: a rich-text widget (`setMarkdown`/`toMarkdown`)
edits a document *tree* and writes back a normalised serialisation, so a keystroke stops
being the one small splice `TextBinding` needs. That decision has a consequence nobody had
paid until somebody pressed Ctrl+V: a `QPlainTextEdit` cannot show a picture. So the editor
does the half it honestly can — the file is content-addressed into the module's file area
and `![alt](assets/…)` is typed at the caret — and the gallery under the editor renders the
thumbnail. The spec module's editor is a `QTextEdit` and embeds instead; that is the *only*
difference between them, and it follows from the binding, not from taste.

**Typing the link is the whole implementation.** Going in through `textCursor().insertText`
makes it an ordinary edit — `contentsChange` → the field's command → the undo stack → every
other view bound to the same document — so the expanded ⤢ editor tracks it keystroke for
keystroke and Ctrl+Z removes it. Nothing new was plumbed for any of that. What *did* need
plumbing is the opposite: the link must not merge into the sentence being typed.
`EditTextCommand` coalesces an append at exactly the caret, which a paste always is, so one
Ctrl+Z would have taken the prose with the picture. `ProseEdit` seals the step on both sides
of the insert — `UndoService.break_coalescing`, the same call a focus change already makes.

**The write itself stays off the stack**, as `FORMAT.md` requires: undoing a paste must never
leave prose pointing at a file that had gone. An orphaned blob is recoverable; a dangling
link is not.

**The editor does not write the file; it is handed an `Attach` callable.** Attaching is three
steps — resolve the area, write, redraw the thumbnails — and `AssetGallery.attach_bytes`
already does all three, including answering in words for a node autosave has not flushed yet.
An editor that only did the middle step would put a pasted image on disk with no thumbnail
beside it and would need a second answer for the unflushed case. One callable buys both.

**The area is aimed by a call, not by another `…_for` callable.** `ProseSection.set_area` is
made by the host from its own `show_target`, because the node a document is *keyed by* is not
always the node its *files* live beside: a test's body is keyed by the test, and a test's
images belong to the step — which is where `dplanner test attach` has always written them.
A `Callable[[str], AreaFor | None]` would have handed the testing pane a test id it must
discard, and that is the kind of seam that reads correct and is wrong.

**A text widget's standard menu is not a `build_menu` menu.** `CLAUDE.md`'s rule that a
right-click renders a menu named in `MENU_STRUCTURE` is about menus of *application verbs*.
`Insert Image…` acts on one widget's caret, means nothing without one, and would be a
permanently disabled entry in the palette and the menu bar — the state *Hidden means absent;
disabled means not now* above reserves for a verb whose precondition the user can still meet,
which this one never could. So it is appended to Qt's own `createStandardContextMenu()`,
exactly as the spec editor's formatting verbs are methods rather than `ActionSpec`s.
Overriding `canInsertFromMimeData` is not decoration either: Qt's own answer for image-only
clipboard data is False, which greys **Paste** in that same standard menu — on the one thing
here that most wants pasting.

## An asset library is a view, not a store

The Assets tab looks like a place where files live. It is not — it is a *derivation*, and
that was the decision that shaped everything else about it. Every file stays where its
aspect put it, in the per-(node, module) areas `store.files()` hands out; what the tab,
`dplanner asset list` and `asset prune` share is `domain/assets.catalog()`, one walk over
every contributed `AssetSource`, computed on each read and never written down.

**Why no central blob directory, when one was the obvious design.** Three costs, each
structural. Every prose surface resolves `assets/<sha>.png` against *its own module's
area* — the paste path, the lint, the agent briefing, the spec viewer all share that one
convention — so a central store means either rewriting links in every existing project's
prose (undoable state, churned by a storage decision) or two link forms with two
resolution rules forever. A node's directory would stop being self-contained: deleting a
step currently takes its files with it and undo restores the graph exactly *because*
nothing outside the step was touched — a shared store would need reference counting as
core machinery, which is the exact complexity the blob/link split in `FORMAT.md` exists to
avoid. And centralising would not even buy the feature: "what uses this file" is a
question about *prose*, so the scanners are needed either way. The storage cost of copies
is near zero — git's object store is itself content-addressed, so identical bytes at five
paths are one blob in history.

**Reuse is therefore a copy.** Picking an existing asset into an editor copies the bytes
into the target's own area through the ordinary attach path — `spec attach-to-step`'s
`copied_to_step` generalised. Content-addressing makes this cheap and makes it *legible*:
identical bytes carry the same `assets/<sha16><suffix>` name in every area, so the catalog
groups by name and one row honestly means one image, wherever it lives.

**Rename-safety is structural, and a name is metadata.** A link can never break on rename
because the name *is* the content; what a person calls the image is a display title in the
browser module's own `module_data` beside the project, keyed by content name — one title
covers every copy, written through a command, undoable, and never part of any link.

**What "used" means is each source's own claim.** A description image is used while the
markdown links it; a test image while any test body does (archived included — evidence
outlives the roster); a spec figure while the index, an attachment record or a markdown
body names it. A documentation image is used project-wide by *name*: a compiled document
renders images from its source steps' areas (`framework/markdown_view.py` asks each in
turn), so a fragment's image may be needed by a collector's compiled text long after the
fragment dropped it — content-addressing makes the name-match exact, not a heuristic.
Instruction files are used *by existence*: the area is handed to agents wholesale, so an
unreferenced file there is payload, not litter; a note's file is used while a note's body
links it, and `note attach` writes the link as it copies the file in. The pool
is `prunable=False` — a staging shelf swept for being a staging shelf would punish the
workflow it exists for. `asset prune` deletes per *location*, only what its own source
called unused, dry-run first, and never enters a directory no source scanned — which is
also why a retired module's leftover area is invisible to it on purpose: unknown data is
carried, never cleaned (the same tolerance unknown edge kinds get).

## Inserting an existing asset is a paste with a different source

`Insert from Assets…` plumbs nothing new. The picker (`framework/asset_picker.py`) answers
in `Payload`s — bytes and a filename, never a path — and `ProseEdit._embed` does to a
picked payload exactly what it does to a dropped one: the host's `Attach` copies it into
the editor's own area, the link is typed at the caret, the undo step is sealed on both
sides. Payloads rather than paths is the load-bearing choice: a path handed across that
line would become a link into somebody else's directory, and the copy-by-value rule above
would quietly stop being true.

The picker itself is framework, not module: three hosts wanted it on day one (description,
test bodies, both agent instructions), and it knows nothing but titles, details and byte
readers — the same test `asset_gallery` and `image_preview` passed. The *catalog* it shows
cannot live there (the framework never imports modules), so the composition root composes
the one `pick_assets(node_id)` closure — resolve the node's project, run `catalog()`, join
the display titles, open the dialog — and hands it down each host's `Deps` as a typed
callback. `ProseSection.set_picker` is `set_area`'s sibling, aimed from the same
`show_target` for the same reason: the node a picker serves is the node the files land
beside, and only the host knows which that is.

## The graph, and what it stores

A project is a graph, so the tab is a canvas: `QGraphicsView` gives selection, dragging,
hit-testing and zoom for free. Writer's corkboard is 2,200 hand-rolled lines because cards
flow in a grid; free positions are the case Qt already handles.

Two decisions keep it small. **Every item diffs by key** — nodes by step id, edges by
`(waiter, kind, source)` — because an item the user is holding on to has to keep its identity:
a node may be under the mouse mid-drag, and an edge may be selected, waiting for Delete. That
was two rules once, and edges were the ones rebuilt wholesale; the second rule was exactly what
made edges unselectable, so making them selectable *removed* a rule rather than adding one.
**The scene reports, the activity commands** — every gesture ends in a signal, and the activity
turns it into something on the undo stack, so a drag is undoable and the model stays the only
authority on what a legal graph is.

That last point is why `Library.link_refusal()` exists. A link drag needs to know *before* the
drop whether an edge would be a cycle, and the alternative — a second reachability check in the
view — is two implementations that will eventually disagree. So the refusal is a question the
model answers, `set_edges` asks it before writing, and the canvas asks it under the cursor.
There is no error dialog anywhere in the interaction because there is never anything to
apologise for.

**The refusal is about the edge being added, never about the list it joins.** `set_edges`
replaces a whole list, and the first version judged every entry in it. That read as thorough
and was a trap: `remove_child` leaves the survivors' edges naming a deleted step on purpose
(undo has to restore the graph exactly, and `requires()` skips what it cannot resolve), so
after any delete of a step others waited on, every survivor's list held an id that could no
longer pass "no such step" — and Link, Unlink, Redirect and Isolate, which all *replace* that
list, were dead on those steps for the life of the project. On 2026-09-08 that surfaced two
seconds after a Delete as a `ValueError` out of Connect, and the ghost was on disk by the next
autosave. The rule now: an entry already in the list is carried, never re-judged — keeping it
cannot make the graph worse, and carrying is the only way such a list can ever change again.
The same reasoning moved the tidying up one layer: `remove_steps_command` (Delete, Cut, `step
remove`, `clear-steps`) is one composite that drops the links *into* the doomed steps and then
the steps, and because a composite undoes in reverse the steps come back before the lists that
named them. Exact undo needed a composite, not an untouched list; the model's `remove_child`
still rewrites nobody, and lint's `graph.requires-dangling` now only ever names a ghost that
arrived from an edit outside the window or a merge.

### Who owns the canvas's input

Interaction is a **stack of modes**. A mode is an object that handles input and has power over
the view; pushing one changes what the canvas does, and popping it puts back exactly what was
there before. Escape pops. `GraphView` normalises each event and offers it to the current mode,
then to the canvas keymap, then to Qt.

The alternative was the shape this replaced: one set of Qt handlers on the scene with the
gesture's state in fields beside them — `_link_from` next to `_press_at`. That works for one
gesture. It produced its first bug at one: a handler cleared `_link_from` on its first line and
asked about it on its third. A mode has a beginning and an end, so there is no field anybody
has to remember to clear, and `exit()` is where "put the cursor and the drag mode back" lives
whatever happened while the mode was on.

Three properties make it cheap rather than another layer:

- **Declining an event costs nothing.** A hook that returns False lets the event fall through,
  and Qt still does rubber-band selection, item dragging and hand-scrolling for free. `IdleMode`
  is nine lines: it catches a press on a link handle and declines everything else.
- **A mode that claims a press suppresses node dragging for free.** The scene's remaining mouse
  handling is the record of what Qt's own item drag moved, which has to run *after* Qt updates
  the selection — so it lives on the scene, where the event arrives already handled. Connect
  and Pan consume the press, the scene never sees it, and nothing anywhere asks "which mode?".
- **A mode reports; it never writes.** It emits the canvas's signals and the activity turns
  those into commands. The chain above is untouched; the mode is one more way to reach its top.

`modes.Canvas` is a written-out protocol rather than "pass the scene around", because it is the
whole of a mode's power. A new mode cannot quietly grow a reach nobody sanctioned, and a mode
can be driven in a test by anything that satisfies it.

**The mode is published into the context**, as an edge on the activity node. That is what lets
`steps.connect`'s toolbar button check itself: its `state(context)` stays a pure function, so
the button, the menu entry and a test all read the mode the same way and nothing reaches for a
widget to ask.

**Canvas keys name action ids; they are never `ActionSpec.shortcut`s.** A bare `h` on a menu-bar
QAction fires wherever the application has focus and would eat a keystroke in the step
description editor. `keymap.py` binds keys that exist only while the canvas has focus, and what
they run is the same verb the menu runs. A key names the verbs it means *in order* and the first
one the context allows runs — which is how one Delete key means "remove these links" when edges
are picked and "remove these steps" when steps are, with no branch on the canvas at all.

That leaves two families of verb, and the distinction is worth stating: **step verbs change the
plan** (they push commands and are undoable), while **canvas verbs steer a surface** — move the
selection, enter a mode, frame the graph. Canvas verbs push nothing, and they reach the current
canvas through a typed callback on their own `Deps`. Where a node *is* is still a fact about the
model — `layout.positions()` answers it — so "the nearest node to the right" is a pure function
and only the last step, telling the canvas what to select, needs a window.

**A gesture that drags something the canvas draws is a `GestureMode`.** The region drag,
the region resize and the card resize each hold what they move (so a sync from the model
leaves that geometry alone until the release), put it back on Escape, and report on the
release before popping — three modes, one skeleton. The base owns the hold, the cursor, the
Escape and the pop; a subclass says what it holds, how to restore it, and what the release
means. The third copy of the skeleton was the moment to write the base, not the first.

The lasso is the mode that shows the stack paying for itself. A rubber band is a box and a
cluster on a busy canvas rarely is, so `LassoMode` claims the press, grows a path under the
cursor, and on release asks the scene which cards the outline *touches* — the node's body
rect, not Qt's hit shape, which is the body inflated by the paint margin and would also hand
back the edges. It then calls `select_steps` and pops, so one lasso ends the mode the way one
link ends connect; Shift on the release folds the catch into what was already selected.
Nothing in it is new machinery: the outline it draws is the same `OutlinePreviewItem` the
region mode drags out, reached through one `aim_outline` on the `Canvas` protocol.

The divide is the stack used twice over. `DivideMode` is switchable like the lasso — Graph ▸
Divide ▸ Vertical or Horizontal, `D` or `Shift+D` on the canvas — and does nothing but lay a
cut under the cursor from edge to edge; the press hands over to `DivideDragMode`, a
`GestureMode` in the card resize's mould, which *takes the divide mode's place* on the stack
and so ends it when it pops: one divide ends the mode the way one lasso does, and Escape
mid-drag puts the cards back and leaves, as it does for a resize. Every card is held for the
drag, because either side may be the one that moves: which side a card is on is decided once,
by its centre at the press, and the sign of the drag says which side goes — so dragging back
past the cut returns the far side and pushes the near one with no state to clear. The release
is one `graph_divided` signal carrying only the cards that moved, and the activity makes it
one `Divide Graph` command, so a whole side comes back with one Ctrl+Z. Nothing is stored
about the cut itself — a divide is a move of many cards, and what makes it a tool rather than
a drag of a selection is that it names the side by geometry, not by what was picked — and the
band it draws while it lasts, the room being made, is the outline item the lasso already had.

### Redirecting a link moves one end, and which end is the tool's, not a guess

Connect makes one arrow between two steps. The other half of linking is taking a *bundle* of
arrows already drawn and moving one of their ends somewhere else — "these six things wait on
the new step now" — which without a tool is six unlinks and six links, six chances to lose one.

`RedirectMode` is that tool, and it is the divide's shape exactly: it is switchable, it takes
what it needs at entry (the picked arrows — every press is consumed, so the selection cannot
move underneath), the step under the cursor wears the same valid/invalid ring a link drag
paints, and one redirect ends the mode. The mode reports where; the activity makes the command.

**Which end travels is a property of the verb, and there are two verbs.** It is tempting to
infer it — move whichever end the picked arrows have in common — and the case the tool exists
for is exactly the one where that fails: two steps' incoming dependencies agree on *neither*
end. A rule with a special case is a rule nobody can predict, so the two ends are two entries
in one *Redirect* child menu: **To Step** moves the arrowhead (`WAITER`; the links come to
point at the step you click) and **From Step** moves the tail (`SOURCE`). The arrow on the
canvas already runs from the step waited on to the step that waits, so *to* and *from* are the
picture, not jargon.

**Both are gated on the same fact: are any arrows picked?** A greyed entry rather than a
hidden one, because the precondition *is* the thing to learn — that arrows are things you can
select at all.

The model does the rest. `Library.redirection(edges, anchor, end)` answers one question about
each arrow — may this end sit there? — through `link_refusal` and nothing else, and returns
what will move beside what was refused and why. That one answer is read four times: the ring
under the cursor, the click, the status line, and `dplanner step redirect`. Asking it against
the graph as it *stands* rather than as it will be is sound and not merely convenient: every
edge a redirect creates touches the anchor at the moving end, so none of them can open a new
path *into* the anchor and the removals can only break paths — the check can decline a
redirect that would in fact have been legal (when the moved edges were themselves the cycle),
never allow one that is not.

**A redirect can therefore half-happen, and says so.** Four arrows move and one would close a
cycle: the four move and the status line names the refusal. Refusing the whole gesture for one
bad arrow would make the tool useless on exactly the tangled graphs it is for.

`redirect_edges_command` writes one `SetEdgesCommand` per affected `(waiter, kind)` list
carrying that list's *final* content — never one command to remove and another to add, which
would each be built from the state before either ran (the trap `remove_edges_command`
documents). For a source-end move both halves land on the same list, which is why the content
is computed per list rather than per edge.

The terminal cannot pick arrows, so `dplanner step redirect` names them by the steps they hang
off: `--to` takes every link pointing at the named steps, `--from` every link leaving them
(`Library.edges_of`). Different way of saying *which*; same `Redirection`, same command.

### An explicit sort persists; the ambient layout never does

Two things place a node, and they persist differently on purpose. The **ambient layout** —
where a never-moved node sits — is recomputed from the graph every time the project opens
(`layout.auto_positions`, which is `sorts.layered_flow`). Storing it would mean opening a tab
dirties the project, autosave flushes it 1.5 seconds later, and every step an agent creates
through the CLI grows a position file the next time a window happens to open. A **sort
action** (`canvas.sort_*`, or `dplanner layout sort`) is different in kind: somebody asked
for that arrangement, so it is a gesture like a drag — one `CompositeCommand` of position
writes on the undo stack, and one Ctrl+Z takes the whole arrangement back. The rule
"derived facts are computed, never stored" survives intact because what is stored is not the
derivation but the user's decision to keep its output.

The same line separates the two other things this feature stores. A **named layout** is a
snapshot a person saved — authored, not derived — kept as one entry on the *project* node
under the same `project_editor` id as the per-step positions (the `estimation` cross-level
precedent in `FORMAT.md`). Applying one builds the same position commands a sort does, which
is what makes a CLI `layout apply` undoable in an open window. **Which layout is currently
applied** is per-user presentation state and lives in `user_config` (QSettings), never the
project: two people sharing a repository can be looking at different layouts of the same
graph. The picker's modified dot is a comparison against the snapshot, recomputed — never
stored.

**Regions** ride the same project-level entry: titled rectangles painted below the edges,
annotation the model never learns about. Every region gesture is one command writing the
whole list; a body drag also carries the steps whose centres lie inside, as one composite —
undo restores frame and steps together. A named layout snapshots region rects along with
step positions, and applying it moves regions it still finds — never creates or deletes one.

**The canvas's spatial gestures exist as verbs, and geometry is derived on every read.**
An agent plans through the CLI and cannot see the canvas, so the picture had to become
words: `dplanner layout show` measures the graph — the stored positions with the ambient
layout filling the gaps, the card sizes, the waves, the box round everything, every
overlapping pair and the gap between neighbouring columns and rows in pitches — and
`--map` draws it as text, one cell per column and row pitch. Nothing it prints is stored:
it is `geometry.measure` over the same `placement.positions` the canvas syncs from, so a
second copy of where things are cannot disagree with the first. Its two hands are of the
same kind as a sort. `layout shift` is the Divide gesture as a function
(`geometry.shift`): the side rule is the body's centre against the cut, a positive
distance pushes the far side and a negative one brings the near side back, the distance
snaps to the grid as the drag does with Snap to Grid on, and the result is
`geometry.divide_command` — the very `Divide Graph` composite `_on_graph_divided` pushes,
so the window and the terminal cannot build two commands for one gesture. `layout tidy`
is the sixth sort (`sorts.tidy`; `canvas.sort_tidy` under Graph ▸ Sort): somebody asked
for that arrangement, so it persists through the undo stack like the five before it.

**Tidy is a sort that reads the picture, not the graph, and every rule in it is a simpler
one that failed.** It keeps every cluster and the left-to-right, top-to-bottom order of
what is there, resolves overlaps, evens the spacing to the pitches, closes any hole wider
than a threshold to one gap, snaps to the grid and starts at the origin — and it must be
idempotent, or an agent's verify step would read a graph that changes under a second
tidy. The cards are read into *lanes* across each axis, and the lanes cluster on edges,
not centres (left-aligned cards of different widths have different centres, and a centre
rule split such a column on the second run); the join is inclusive of half a pitch (the
flow sort centres a column by whole half-pitches, and a strict rule spread every flow
layout whose columns differed by an odd count into twice the rows); two cards in one
column and one row are given a sub-row of their own rather than a stack inside the cell
(a stack beside a taller card in the next column was not a fixed point); and a hole is
measured against the reach of everything before it and *rounded* to whole pitches (a
floor let eight points of snap noise collapse a kept empty row). The same lanes are what
`layout show` reports gaps by and what the map is drawn on, so the number the report
prints is the number a tidy acts on. One number to know: the column pitch, 300, is not a
multiple of the grid, 8, so a tidy of a flow layout moves alternate columns by four
points and nothing else — the fixed point of a sorted graph is the sorted graph snapped.
Regions are neither carried by a tidy nor drawn on the map: they are annotation on the
way out, and a rule written for them now would be one more thing to retire.

### The canvas is a plane, and why that is one decision rather than three

`GraphScene` sets its scene rect once, in its constructor: a square centred on the origin,
`CANVAS_EXTENT` out in every direction and never touched again. Three things follow from that
one line, which is the reason it is worth a section.

**Panning does not stop.** The complaint was that it did — a few hundred pixels past the last
step, most obviously downwards, because the extent was the graph's bounds plus a margin. A
plane two hundred viewports across has an edge nobody reaches.

**Nothing about the graph can move the extent.** The older code recomputed the rect from
`itemsBoundingRect` on every model change, and a move *is* a model change: dragging a node
changed the rect's origin, the scroll bars re-ranged under a fixed value, and the canvas slid
out from under the drag. The fix at the time was a floor that only grew and was left alone
mid-drag — a constant is the same rule with nothing left to get wrong. The alignment fix that
came with it (a scene *smaller* than the viewport re-centres itself whenever its rect changes)
went away with it too: this scene is never smaller than a viewport. The rule generalises past
this canvas: **a scrollable area's extent must not be a function of what the user is moving.**

**The scroll bars go.** On an extent like that a scroll bar is a nub that says nothing true
about where you are, so both are `ScrollBarAlwaysOff` — and still there, so the wheel still
scrolls (Ctrl+wheel zooms) and a pan has something to move. `PanMode` claims every press
while Space is held and scrolls the bars by the pointer's travel itself — Qt's
`ScrollHandDrag` hands a press to the item under it first, so a press on a card moved the
card, which is the one thing a hand holding Space does not mean — and with Space held the
arrows and `hjkl` page the plane a third of the viewport that way, a tenth with Shift,
claimed in the mode so the keymap's movement verbs stand down while the hand is on the
plane. What replaces the bars is `minimap.py`, anchored in the canvas's lower-left corner: the
graph small, the viewport as a frame on it, and a click to go anywhere. It is *given* node
rectangles rather than reaching for a scene, so it imports nothing from the module around it
and cannot outlive what it draws; `GraphView` pushes on `QGraphicsScene.changed` and on every
scroll, and is the one object in a position to know whether there is still a scene to ask.
And it is parented to the view rather than to the viewport, because `QGraphicsView` pans by
`QWidget::scroll`, which drags the viewport's children along with the pixels.

### Marks are a way of looking

*Mark Starts*, *Mark Ends* and *Mark Orphans* colour a node's unconnected sockets and ring a
node with none. Three decisions sit behind three short functions.

**They are a preference, not a fact about the project.** Whether the graph's ends are lit
says nothing about the plan, so the value never reaches the project directory — it is the
`marks` of the one `Look` on the editor module (`look.py`: marks, the background under the
graph, Snap to Grid), written to `user_config` and pushed to every open canvas the way a
mode's `RenderHints` are fanned out. That is also why a tab opened later wears them: the
module hands its current look to every activity it builds. One value rather than one per
preference, because the plumbing — a key, a setter, a fan-out, a pair of callbacks on the
verbs — was the same for each, and the second copy of it (the ground beside the marks) was
the signal to fold them: the next preference is a field on `Look`, not a third copy.

**What a socket has connected is derived every sync.** `marks.ports()` reads the edges whose
both ends are in the project — exactly the edges the canvas draws — and the activity puts the
answer on each `NodeSpec`. Stored, it could disagree with the graph the moment `dplanner step
link` ran with no window open, which is the same argument as the ordering's.

**The toggle reads the module and re-asks, rather than the context.** A mode's `checked` is
an edge on the activity node because a mode is something the user is *in* on one canvas. A
mark outlives any tab, so publishing it per activity would be a copy that has to be kept
agreeing; the toggle's state reads the module's value and the module calls
`context.refresh()` when it changes — the pattern the theme and panel toggles already use for
state that lives outside the context graph.

**All three are on, and switching one off is what gets remembered.** They shipped off, on
the reasonable-sounding ground that a mark is a preference and a preference starts quiet.
The trouble is what they mark: a socket with nothing on it and a node with nothing at all
are the two things a graph can be *wrong* about, and both are invisible in a drawing of it —
a card with no arrow reads exactly like a card whose arrow is off screen. A preference that
has to be found before it can help is one that helps nobody, so the graph arrives saying
what it knows and the deliberate act is telling it to stop.

That makes the stored value's absence rule matter: `Marks.from_json` gives a name the
stored value does not mention the *class* default rather than False, which is `FORMAT.md`'s
absence rule and the only reason this change reaches anybody who already has a look on
disk. A stored `false` still wins — somebody who switched a mark off keeps it off.

The orphan's ring is the one mark drawn at full strength (`ORPHAN_RING`, and
`ORPHAN_RING_W`, twice the agent ring's weight): the socket discs say *this is where the
graph ends*, which is often correct, while a ring says *nothing touches this at all*, which
almost never is. At the tint's alpha it read as a shadow of the border rather than as a
warning. Being heavier than the ring it shares a gap with, it is the term `PAINT_MARGIN`
takes — a decoration that reaches further than the bounding rect is clipped, and nothing
says so.

### The spotlight is one derivation, and a held key lends the look

A picked card says *this one*, and said nothing about what it is joined to — on a graph of
any size, tracing a step's dependencies meant following curves by eye across cards that all
looked equally present. Two answers, from one derivation.

**Selection lights its arrows, always.** `selection.neighbourhood(edges, picked)` names the
arrows with one end among the picked steps and the steps at their far ends; the scene
re-derives it on every selection change and every sync, and every arrow it names is drawn in
the accent the picked card's border already wears. Nothing is stored and nothing is
configurable: it is the second half of *what is selected*, the way a picked node's lift is,
and a graph relinked by a CLI run this window adopted lights correctly the moment the arrow
is drawn — the same argument as `marks.ports()` and the ordering's.

**The spotlight fades what the neighbourhood leaves out**, and that *is* a preference: it
hides part of a true picture, and the part it hides is the one you need while you are
drawing the graph. So it is a field on the one `Look` beside the marks — off by default,
where the marks are on, because a mark says what the graph could be *wrong* about and this
only chooses which of two true pictures you are shown. `Graph ▸ Spotlight Selection` is the
switch, and **holding Alt lends the same look for as long as the key is down**: the thing
you want nine times in ten is a glance, and a glance should not cost two menu trips.

**Held is not a mode, and not the preference.** It handles no input — nothing about what a
click means changes — so a mode would be a stack entry that declines every hook, and one
that Space's pan would then have to nest inside correctly for no gain. It is not the
preference either: a key that wrote the setting would leave the menu's tick flickering under
the user's thumb. So the scene keeps the two sources apart and lights on either
(`set_spotlight`, `hold_spotlight`), the view owns the held one — because only the view
learns when the keyboard goes, and **Alt+Tab is precisely Alt held and then taken away**,
which is why `focusOutEvent` ends it.

**Nothing picked lights nothing.** The neighbourhood of an empty selection is empty, and the
scene fades nobody when it is — a spotlight over an empty selection would dim the whole
canvas to say nothing at all. That one rule is what makes the preference safe to leave on.

The fade is `QGraphicsItem.setOpacity` at `DIM_OPACITY`, not a paint-level flag: one number
fades a card's fill, border, title, medallions and the shadow under it together, which is
what receding is, and `renderers.py` never learns that a spotlight exists. The coverage
trace already dimmed its cards that way to light a path through its lanes, so the constant
moved to `theme/cards.py` — the same argument that put the card primitives there. The ground
and its regions stay as they are: they are the table, not the graph.

### The palette a painter is handed is a snapshot

`QStyleOptionGraphicsItem.palette` is filled once, when the scene is constructed, and Qt never
refreshes it. Nothing about that is visible until the application changes its palette: a theme
switch repainted the canvas with the *old* theme's ink, and light-on-light lost the graph
altogether. `items.live_palette()` reads the scene's palette instead, which follows the
application's, and no canvas item may read `option.palette` again.

The same shape one layer up, with a different cause: `TabHost` copies a palette colour onto
each tab with `setTabTextColor` to dim the panes the user is not in, and a copy does not
follow the original. It re-tints on `QEvent.PaletteChange`. **A surface that stores a colour
owes that hook** — the palette is live, everything derived from it is not.

Two more colours reach past both: Qt's tab-close cross is a bundled red bitmap that no
stylesheet or palette touches, so `theme/style.py`'s proxy answers `SP_TabCloseButton` with a
painted glyph — and the style is rebuilt on each theme change because `QCommonStyle` caches
the icon it is given.

**Node positions are stored, automatic layout is not.** A step nobody has moved is placed by
`requires` depth, recomputed each time the project opens. Persisting that would mean merely
opening a tab dirtied the project, autosave flushed it 1.5 seconds later, and every step an
agent created through the CLI grew a position file the next time a window happened to open. A
test asserts the project is unchanged after a tab is opened, because that is the kind of rule
that decays silently.

### The spine names the card

A step's key — `S7`, `F3` — is what a person says, what its branch and PR are named after,
and what the agent's `dplanner` verbs address, so it has to be found from across the
graph. It is painted on a **spine**: a 26 px strip inside the card's left edge, clipped to
the rounded body, with the key set bold and rotated a quarter turn so it reads up the
strip the way a book's spine does. Vertical, because a horizontal label wide enough to
read would take a line the title needs; a spine costs the title 26 px of width and no
height at all.

The spine is also where the card says where the step *stands*: its wash is the status —
busy blue for in-progress, the bad red for blocked, the good green for done, and a quiet
shade of ink otherwise, so the strip is always there and the key always has a ground. It
replaces the 3 px status bar that sat in the same edge: one strip that carries the key and
the status is the same idea as the bar with something to say written on it, and two
strips down one edge would have been noise. The done wash sits on the done body's green
— the body says the work receded, the spine says why. Everything on the left edge starts
past it (`LEFT_INSET`): the medallions, the chip, the title.

### A picked node is lifted, not recoloured

Selection used to be a one-pixel-wider border in the accent, and on a graph of twenty nodes
it was genuinely hard to see which one you had. The replacement is four things that each say
"this one" in a different register, and one thing it deliberately is **not**.

The border thickens and takes the accent (2.5 px). The fill **gains**: whatever alpha the
node's own fill had, half again. The node draws two pixels **up**, over a soft shadow left at
its seat — four rounded rings, each wider and fainter, because a `QPainter` has no blur. And
the item claims a Z of its own while selected, since nodes otherwise share one and the
stacking order is whichever `sync` happened to add last, which would let a neighbour crop the
shadow.

What it is not is a colour of its own. A wash of the accent over the body was the first
attempt and it was wrong for a reason worth keeping: a selected milestone stopped being
purple, a selected feature stopped being teal, and a selected done step stopped looking done.
The kinds' body colours are identity, and identity should not be something the pointer can
take away. A gain on the node's own fill preserves every one of them, and reads on light and
dark alike — the fill is ink over the canvas, so *more* of it means more contrast in either
direction.

**Every card rests on a shadow, and the fill is opaque.** The first cut painted the fill
translucent (`FILL_ALPHA` ink over the canvas) and clipped the shadow to the ground around
the card, because rings left underneath darkened the fill itself and a selected step read as
a hole rather than as a card off the table — on a light theme the selected node came out a
flat dark grey and nothing about the code looked wrong. The grid ground made the same point
again from the other side: dots showing through every card read as a stain. So
`renderers.over()` blends the tint over the palette's window colour and paints the result
opaque — exactly the colour the tint would have had over bare canvas, on any theme, with
nothing underneath able to change it. The clip went with it, and with it the reason a
*resting* shadow could not exist: every card now sits on a faint one (`RESTING_SHADOW`) and
a selected card's is deeper and wider (`LIFTED_SHADOW`), which with the lift is what says
"this one is up". Both are deliberately slight — the rings composite, so the first alpha
that looked right in isolation landed twice as dark, and on a light theme's paper that reads
as a hole. The border and the gained fill are what say "this one"; a shadow only has to seat
the card. The fill-gain test still guards it: a body can only come out at exactly the gained
tint over the ground if the fill is opaque, or nothing at all is painted underneath it.

One number ties it together: `PAINT_MARGIN` in `renderers.py` is the furthest any decoration
reaches out of the body — handle, badge, medallion, chip, lift, shadow — and
`StepNodeItem.boundingRect` is exactly that, *constant whether or not the node is
selected*. A rect that grew on selection would invalidate the wrong region, and the shadow
would be left on the canvas when the selection moved on. `shape()` is a different question —
the card and its resize band — because the bounding rect reaches that margin out on every
side for paint, and a click beside a card is a click on the plane.

### A card's size is the step's, and a layout never says how big

A card can be dragged wider or taller by any edge or corner, and three decisions sit behind
the one gesture.

**The size is stored beside the position, and absence is the default.** `{"x", "y"}` gains
`"w"` and `"h"` only for a card somebody resized (`positions.write_position`), so a project
of untouched cards never learns the keys exist — `FORMAT.md`'s absence rule — and a card
resized back to the default drops them again. It rides in the same per-step entry because a
resize is the same kind of fact as a move: presentation, one file, one diff. It is
deliberately **not** part of a named layout: a layout says where cards sit, and applying one
must leave a card somebody enlarged as it was. Every position write therefore carries the
size back in — a move, a sort, an applied layout, a paste — which is what
`write_position(x, y, size)` and `position_commands(project, …)` are for.

**Every painter takes the body it is handed.** `renderers.py` measures from a `body` rect
and the only fixed numbers left are paddings, radii and how far the decorations reach; the
sorts already spaced by a `size_for` function, which now defaults to `positions.node_size`
— so a large card keeps its room in every arrangement without an algorithm learning about
sizes. What a taller card buys is *title*: the name is set two points larger than the chrome
and wraps onto as many lines as the card has room for above its bottom line, only the last
one eliding. The bottom line holds the estimate — the one number a step answers with — at
the right in full ink, then the PR pill and the branch glyph, and nothing in words: the
aspects' phrases that once filled it as a subtitle were saying what the medallions, the
badge, the bar and the pill already wear, and a card that repeats itself is a card that is
harder to read.

**The gesture is a mode, and the hit shape is the card.** `NodeResizeMode` is
`RegionResizeMode`'s shape with eight grips instead of one: a band `GRAB_IN` inside the
border and `EDGE_REACH` outside it, both bands at once being a corner, and the link handle
winning its corner of the right edge as it does on the press. The edge under the pointer
moves, the far edge is the limit (never below `MIN_NODE_W` by `MIN_NODE_H`), and the card is
held for the gesture so a sync from the model leaves it alone. One `Resize Step` command
writes seat and size together, because dragging the left edge moves both and undo must take
both back. The pointer's resize arrows are the gesture's only announcement, shown by
`IdleMode` on mouse moves with no button down — the one mode that can start a resize is the
one that says where.

### The ground is a preference; snapping belongs to the gesture

*Graph ▸ Background* (plain, dots, lines, crosses) and *Graph ▸ Snap to Grid* are two fields
of the same per-user `Look` the marks live on (`look.py`), so they are kept, fanned out and
read by their toggles exactly as the marks are — the view draws the background
(`ground.py` paints it by name), the scene answers `snap()` — and a tab opened later wears
them. The background is the theme menu's shape: one choice of several, exactly one checked.

**What snaps is the gesture, never the write.** Before this the grid was invisible and every
coordinate was rounded to it on its way to disk, which would have made a snap *toggle* mean
nothing: a drag with snapping off would still have landed on the grid the moment the store
wrote it. So `positions.snapped(value)` rounds to a whole unit — short JSON, and still the
float every number on disk owes — and only the canvas passes `GRID`, only while snapping is
on, through the scene's one `snap()`: a node or region drag (`itemChange`), a resize, a
region being dragged out, and the seat of a placed step (a double-click, New, a paste, a
drop). A CLI verb has no gesture and stores what it was given; a sort's output is what the
algorithm computed, and the layered ones land on round pitches by construction.

**What is drawn is a coarsening of what snaps.** The ground shows every `pitch_for(zoom)`-th
line of the snap grid — the smallest power-of-two multiple of `GRID` that keeps the marks
`MIN_SCREEN_PITCH` device pixels apart — so a card's corner is always on a line the ground
*could* show, and zooming in reveals the finer ones rather than a grid that drifts against
the cards. Cosmetic pens keep a dot two device pixels and a line one at any zoom: the ground
is a texture, not a drawing that scales with the graph. Its ink is the palette's text at a
low alpha (DESIGN.md exception #1), read at paint time from the view's own palette so a
theme switch repaints it with the graph.

## Two writers, one folder

The scenario DPlanner is built for — an agent refining a plan *with* the user — means the
CLI writes while a window is open on the same folder. The framework's ordinary contract,
"memory is authoritative and disk follows", quietly loses data under those conditions: a
flush 1.5 seconds after the user's next keystroke rewrites nodes from a model that never saw
the agent's edit, and orphan removal deletes a directory the agent just created.

A lock would be the cheap fix and it is the wrong one, because both writers being live *is*
the feature. So the rule is instead:

> **Nothing writes over a file it has not seen.**

`LibraryStore` records what each project directory looked like when it last read or wrote
it and raises `StaleWorkspaceError` rather than flushing over anything that changed
underneath. The check is **per project** — flush verifies exactly the projects it is about
to write, so an agent editing project B never blocks saving project A, and the refusal
names the project. The library file is a third written thing with the same treatment under
its own stamp, because two instances can both add a project; membership reaches disk
through the ordinary flush, as a structure mark on the library root. Around that one check:

- A **CLI run** reports it as one line and writes nothing. A run is a transaction, so
  running it again picks up the change and is correct.
- A **window** takes the change into its live model, entry by entry — the next section —
  and a flush that was refused is retried once the folder has been seen.
- A **window that changed the very same entry** and has not flushed it stops on that
  entry: autosave keeps its marks and pauses itself, and a modal makes the choice the
  user's — an agent, theirs, ours, or later. Nobody else can make that call.

The same check is why **two CLI runs need no lock between them**: the second is refused for
exactly the same reason and can be run again. One mechanism, three cases.

### Adopting the other writer's changes in place

Every outside change used to cost the whole rebuild: `AppSession.reload()` built a second
window, showed it, and discarded the first. Correct, and visibly a close-and-reopen — the
undo history, the selection, the canvas viewport, the caret, split panes and open dialogs
all went with the old build, and an agent running five CLI verbs in a row rebuilt the
window once per two-second tick. The rule now is the one above with a second half:

> **Nothing writes over a file it has not seen — and nothing rebuilds over a model it can
> still reconcile.**

`LibraryStore.adopt_outside_changes` is the reconcile, and it is possible because of four
things the format and the model already were:

- **The stamp is per file, and a plan file is one entry of one node.** `project.dproj` is a
  project's title, summary and child order; `steps/<slug>/step.json` a step's title and
  edges; `modules/<id>.json` one module's data; `modules/<id>.md` one module's prose; a step
  directory a node. The diff between what was last seen and what is there is a set of paths,
  and `_classify` turns each into *which node, which entry*. Nothing else is compared, so a
  re-read of a fifty-step project touches the entries the agent wrote and no other.
- **Identity is the id.** A fresh read of the project is matched to the live one by uuid,
  through the same `_load_project` opening uses — on the record's own provider, so a tick is
  a file read and never a git subprocess.
- **Every mutator takes an origin, and every view treats an unknown one as "repaint".**
  Adoption calls `set_field`, `set_edges`, `set_module_data`, `apply_text_edit`,
  `add_child`, `remove_child` and `reorder_children` with `OUTSIDE_ORIGIN`; the canvas
  reconciles by key, the step panel drops a vanished step, the index rebuilds. No view
  learned anything.
- **A prose edit is positional.** A whole-document `describe set` arrives as
  `diff_hunks(live, fresh)` applied highest position first, so `TextBinding` splices each
  hunk through a `QTextCursor` around the user's caret. One replacement from position zero
  would have collapsed the caret to the start.

Three decisions inside it:

- **Mutators, not commands.** Adoption never pushes and never undoes; a command's only
  extra over the mutator is the before-state it keeps for undo, which nothing would use.
  Membership already applied the mutators directly with `LIBRARY_ORIGIN`; this is the same
  case. *Syncing an external fact* below is the third writer that bypasses the stack, and
  the reasoning there — the stack is the GUI user's journal — is the reasoning here.
- **Dirty is muted while adopting.** A change read off disk is not something to write back:
  forwarding it would have autosave rewrite the agent's file 1.5 s later and race the
  agent's next run into a `StaleWorkspaceError` of its own.
- **A conflict is per entry, and the store knows it.** Autosave's `(owner, aspect)` marks
  say a step's module data is dirty, not *which* module's — too coarse to tell a local
  estimate from the agent's status on the same step. So the store keeps `_unflushed`, fed
  from the typed signals (which carry the module id) and cleared per entry as flushes write.
  An outside change to an unflushed entry is reported as a `Conflict` and left alone, its
  stamp kept old so that project's flush is still refused; `take=` adopts it (theirs),
  `mark_seen` counts it seen (ours). A step with any unflushed entry that disappeared on
  disk is a conflict too, not a removal.

And the boundaries: a project whose read is inconsistent — a torn JSON, a snapshot that
moved during the read — is **deferred** to the next tick rather than adopted half-written,
which is what the strict read exists for (the tolerant one that opens a library would take
a torn file for an emptied node); a torn *library file* likewise, or every project would
read as departed. A pending format migration, or any failure halfway, sets
`rebuild_required`, and `SessionControl.refresh` falls back to `reload()`: the rebuild is
still correct by construction, it is just no longer the first move. The watcher no longer
holds off while this window owes a write — a flush re-stamps as it writes, so our own files
never read as foreign, and the conflict rule answers the case the guard existed for.

**The undo history survives an agent's edits and is dropped by a branch switch.** An entry
that names a step the agent removed, or prose whose positions moved under adopted hunks, is
refused by the model when undone; `UndoService` drops that entry and the redo tail after it
rather than leaving the pointer past a still-applied command. A checkout or a pull replaces
the tree wholesale, so its refresh passes `forget_history=True` and the stack is cleared —
only when something was actually taken, which is why New Branch, which changes no plan
file, keeps it.

**The conflict modal hands the merge to an agent** because the user asked for that over a
banner. `modules/library_watch/` names the entries and the agent module writes the window's
version of each into the run directory (`mine/<path>`) *before* the window yields to the
plan on disk — the run directory is the one place the unsaved version survives. The prompt
(`conflict_prompt`) points at both, asks for a merge written back through the owning verb,
and ends with `agent-state clear`; no worktree, because the agent must write to the
checkout the window shows. The launch is the ordinary one, so the run is tracked on the
step like any other — chip, ring, Agents browser — and the merge arrives as an outside
change. *Later* leaves a status-bar button that reopens the question; *Keep Mine* on a step
the agent deleted writes back only what this window changed, which is the honest reading of
"mine".

What the check *looks at* is the plan, not the directory. A project directory is often
the repository root itself — New Project's git-init flow makes exactly that — and then the
directory holds the user's source tree, `.git/` and the worktrees Run Agent keeps under
`.dplanner-worktrees/`. None of it is anything the store reads or writes, and a snapshot
that walked all of it made every source edit, every Save and every file an agent touched
read as "another writer" and reload the window. So `LibraryStore._snapshot` walks
`PLAN_ENTRIES` — `project.dproj`, `modules/`, `steps/` — which is exactly the set a flush
could overwrite, and therefore the only set the question is about.

### A branch switched underneath the window is taken in, and said

The window's own Switch Branch takes the tree in and drops the history (above). A switch
made *outside* it — `git checkout` in a terminal, an agent whose step runs in the checkout
itself — used to arrive as nothing in particular: the workspace watcher adopted whatever
plan files differed, "Took 3 changes from outside DPlanner" flashed in the status bar,
the branch label stayed stale until the next context change, and every edit from then on
was autosaved onto a branch nobody had named. An agent's feedback put it plainly: *a
window should warn when the checkout's branch changes underneath the plan.*

So the sync module polls. Every repository's branch is asked of git directly — not
through the service's second-long cache, since seeing a change is the point of asking —
at the workspace watcher's cadence (`framework/window_watch.POLL_MS`), one cadence for
"did something change underneath", and compared with the branch this window last saw. A
difference is handled exactly as the window's own switch is: `_take_worktree` reads the
tree into the model and, when anything was taken, clears the undo history and resumes
autosave; then a modal names the repository and both branches, once per switch. Three
things keep it honest. The poll stands down while an operation of the module's own is
running, and every such operation re-baselines when it ends — New Branch, Switch Branch,
a pull — so only a switch from outside is ever reported. A membership change re-baselines
too, since a project that just arrived was not "underneath" anything. And the history is
dropped by the refresh's own rule — only when something was actually taken — so a switch
the watcher's tick happened to adopt first keeps the stack, and the model's refusal of an
entry that no longer applies is what covers it (*The undo history survives an agent's
edits*, above). The cost is one `git branch --show-current` per repository every two
seconds on the GUI thread, a few milliseconds; `refresh_dirty` already pays the same
after every flush.

### Storage operations that rewrite the working tree are synchronous

CLAUDE.md's rule says blocking work runs through `TaskRunner`, and the sync module's own
Save and Update honour it. Four of its operations deliberately do not, and the exception is
a decision, not a leak:

- **Branch switch and create** (`SyncService.switch_branch_sync` / `create_branch_sync`,
  run through `_run_guarded` in `modules/sync/module.py`). A checkout rewrites the very
  files the application is showing; taking them into the model must follow *immediately*,
  not after an event-loop round trip during which a paint, a context change or an autosave
  could read a model that no longer matches the tree. `_run_guarded` pauses autosave around
  the body for the same reason, and resumes it once the tree is in the model.
- **The branch list** before the switch dialog opens: a subprocess, but a local one, and
  the dialog's contents must be current at the moment it appears.
- **Save at quit** (`service.save_sync()` in the close guard). The window is closing; there
  is no task centre left to watch a task in, and returning to the event loop mid-teardown
  is exactly the window a lost write needs.
- **Moving a plan** (`ProjectsModule.move_plan` over `domain/relocate.move_project`). The
  project's files leave one directory for another and the store is re-pointed; the reload
  that follows discards the build, so there is no runner to come back to. The publish that
  may follow a move or a New Project into a fresh GitHub repository rides the same
  exception, under a wait cursor: the repository was written a moment ago and the person
  is waiting on it.

The boundary to keep: an operation whose completion the *running* application must observe
before doing anything else at all may be synchronous; anything the user merely waits on goes
through the runner. A new storage verb defaults to the runner.

## Closing a window is not discarding it

A build is a window, its services and one instance of every module. Two places let one go: a
reload, which replaces it, and a test, which is finished with it. Both go through
`discard_build()` in `framework/session.py`, and the reason that is one function rather than
two similar blocks is that the second copy of it left out one line.

The line is `deleteLater()`. **A closed `QWidget` is still alive** — `close()` hides it and
runs its close hooks, and Qt goes on holding it in `topLevelWidgets()`. Everything hangs off
the window, so the entire build stays reachable: services, model, every module. In
the application that costs nothing worth noticing; a person reloads a library a handful of
times. In the test suite, which builds a whole application per test, each discarded build left
28 top-level widgets and about 2,700 objects behind, permanently.

That would be merely untidy if nothing walked the result. `tests/conftest.py` collects cyclic
garbage after every test — it has to: `framework/gc_policy.py` switches Python's automatic
collector off (left to itself it frees PySide wrappers on a worker thread or mid Qt event
dispatch, and the SIGSEGV moves whenever anything else changes), so the boundary is where the
suite's cycles die. A full collection costs what the live object graph costs. So the leak made
every test pay for every test before it, and a suite that should be linear was quadratic: early
tests ran in about 0.45 s, tests two thirds of the way through took over ten seconds each, and
`tests/modules` alone took 25 minutes. With the one line restored it takes 4m36s.

**`deleteLater` and not simply dropping the reference**, because `discard_build` is called with
the window's close hooks still unwinding on the stack; deleting it under them is a crash. The
deletion happens the next time the event loop runs — which is the second half of the rule:

> Anything that discards Qt objects without an event loop to follow must dispatch the deferred
> deletes itself.

A running DPlanner always has one, so the reload path is already correct — measured, not
assumed: reload a library nine times and the top-level widget count settles and stays flat.
A test suite has none, which is why `AppSession.close()` ends with
`sendPostedEvents(None, DeferredDelete)` and why that call is *there* rather than inside
`discard_build`: only a caller that is on no Qt stack at all can promise it is safe.
`processEvents()` will not do — Qt deliberately skips DeferredDelete in it, and that is exactly
the trap this closes.

`tests/framework/test_builder.py` asserts the property by counting top-level widgets across two
build-and-close cycles, rather than trusting that the line is still there.

## Syncing an external fact

The GitHub aspect stores each PR's *last-seen* state so a merged PR stays green offline —
which means something has to keep that cache current, and in a window that something is a
background refresher, not the user.

The refresher builds the same `SetModuleDataCommand` every other writer builds, but calls
`redo()` directly instead of pushing it onto the undo stack, with an origin of its own
(`REFRESH_ORIGIN` in `modules/github/refresh.py`). The reasoning:

- **Undo is for decisions.** The stored state is a cache of something GitHub decided; an
  undo entry here would make Ctrl+Z restore a *stale* state instead of undoing the user's
  last edit, and the user never asked for the refresh in the first place.
- **The stack is not what persists.** Autosave flushes on the store's dirty signal, which
  `Library` emits for every model change regardless of who applied it — so the write
  reaches disk without the stack's help.
- **There is precedent, not exception.** The CLI applies commands the same way (a run is a
  transaction; version control is the undo). The rule "every model change goes through a
  command" is about having one vocabulary of change, not about the stack: the stack is the
  *GUI user's* journal, and a background sync is not the GUI user. (The format migrations
  at open sit *below* the vocabulary: they run in `core/`, which may not import
  `domain/commands`, so they write through the `Repository` protocol directly — before any
  surface that could undo exists.)

The concurrent-writer story needs nothing new: the refresh dirties the project like any
edit, and *Two writers, one folder* above already covers an agent flushing underneath. The
store's own adoption of an outside change (*Adopting the other writer's changes in place*)
is the same shape one level down — a change nobody in this window decided, applied with an
origin no view claims, off the stack — with one difference: it is *read off disk*, so it
does not dirty anything.

## The skill is a projection, not a document

An agent has to be told what DPlanner is and what it can do. Writing that by hand means
writing every command twice, and the copy is wrong within a month — a skill that describes a
flag which no longer exists is worse than no skill, because it is believed.

So `dplanner skill install` **renders** `SKILL.md` and `reference.md` from the same
`CliRegistry` that `--help` renders. The hand-written half is only what a registry cannot
know: what a project is, and how to work with a person. Everything else — the command index,
every argument, the aspects, the edge kinds — comes from the objects themselves.

Two details make that safe. The parsers are built at a **fixed width** rather than the
terminal's, because the output goes into version control and a diff that depends on who ran
it is a diff nobody reads. And `build_tree()` hands back the verb parsers it built rather
than the skill digging them out of argparse afterwards, so one tree serves both.

MCP was considered and deferred. A CLI reaches every agent, including ones with no MCP
client; it is useful to people and to CI; and it needs no process lifecycle. If a
Claude-specific integration is wanted later, `dplanner mcp serve` is a thin adapter over the
same registry and introduces no second description of any command.

## Lint belongs to no feature

`dplanner project lint` asks whether a plan is complete enough to hand to an agent — and
completeness is a fact about *every* feature at once: an unestimated step is estimation's
concern, an unplaced feature is the feature module's, a dangling edge is the graph's. No module can
own that question without importing the others, so the verb lives in `cli/lint.py` beside
`cli/aspects.py`, whose rationale it repeats: a command that answers a question *about* the
features takes them as arguments.

The split is what makes it right rather than merely legal. `cli/lint.py` owns the shapes
(`LintFinding`, `LintCheck`), the report and the exit code; each owning module's Qt-free
`cli.py` exports `lint_checks()`, so the knowledge of *what missing looks like* — and which
verb closes the gap, which every message names — stays with the module that owns the aspect.
`default_cli_commands()` assembles the list, and its order is the report's order. The
alternative — a verb inside `projects/cli.py` with injected predicates — would put a
cross-feature report inside one feature and grow that module's signature with facts that are
not its business.

Two deliberate behaviours: findings exit 1, so an agent gates a handover on lint exactly as
it gates on a test suite; and the conditional checks (a topology only once a project has
steps, a start date only where estimates do) keep the report an obligation list rather than
noise about features a project never adopted.

A check is handed the store's file lookup as its third argument (`FilesFor`) alongside the
library and project, because some facts live *beside* a node rather than in it: whether a
feature's quote still anchors in its document's text layer, whether a description's
`![](assets/…)` resolves to a file actually attached. The check re-derives those answers on
every run rather than trusting anything stored at add time — `spec import` can replace a
document with no window open to notice, which is the same argument the ordering makes. The
quote check itself is the spec module's (`anchor_quote`), handed to the feature module's
`lint_checks(anchor=…)` by the composition root: the record is one module's and the
document another's, and neither imports the other.

## Authoring a step is one verb, many modules

A fully authored step needs a description, an instruction, an estimate, the feature it
realises and its figures — five modules' facts, and five commands when every module keeps to
its own verb. Measured against a real plan, that was most of the invocations. So `step add`
takes **authors**: each contributing module's Qt-free `cli.py` exports a `StepAuthor` — the
flags it registers on the verb's parser, and what it applies to the fresh step — and the
composition root assembles the list into `projects_cli.commands(step_authors=…)`, exactly
as it assembles lint's checks. The shape lives in `cli/authoring.py` for lint's reason: the
contributing modules may not import each other, and `cli/` sits below them all.

Two decisions carry the weight. **The transaction is the rollback**: an author that raises
aborts the whole run, and `open_library` flushes nothing — the step included — so no author
writes compensation code. Any future refactor that flushed eagerly mid-run would silently
break every author's atomicity; this paragraph is the guard. And **stdin is claimed before
it is read**: each author declares whether its parsed flags would consume stdin, so two
`--…-file -` on one call are refused before either swallows the other's document.

## Editing a spec in-app is a replace

The Specs tab can author a markdown document, not just import one, and the editor had to
answer the question every document editor faces here: spec bodies are content-addressed
blobs in a file area — outside the model, outside the undo stack, outside autosave. The
answer is that **an editing session is one replace**, the same operation `dplanner spec
import` performs on an existing name, so the CLI needed no new editing verb and the two
surfaces still speak one vocabulary.

Concretely: a markdown document has no read mode — picking its row opens it in the
editor, and that is the session's start; picking another row, or closing the tab, is its
end. The editor flushes on the autosave rhythm (a pause in typing) and at those boundaries,
and every flush writes a new blob and pushes the index update as a `SetModuleDataCommand`
with one label — command merging turns however many flushes into a single undo entry, and
`previous` stays pinned to the blob that was current when the row was picked, so `spec
diff` answers "what did this session change". Undo restores the pre-session index, and the
pre-session blob is still on disk — the same invariant every replace relies on. There was
a *Done* once, and an *Edit Spec Document* verb to reach the editor: a read mode nobody
wanted for text they came to write, and a button whose absence a reader took to mean
"unsaved". Both went; the idle flush was always what persisted. The one carve-out from "orphans are never pruned": a blob the session
itself wrote and then superseded is churn, not history, and is removed once nothing in the
index names it (`prune_blob`). Typing inside the editor is the widget's own undo stack;
the application stack holds only the session-level replaces — two stacks because they hold
two different kinds of fact, keystrokes and index states.

Three edges are decisions, not accidents. **Only markdown edits in-app**: a PDF is not
text, and plain text pushed through a rich-text round-trip would come back as markdown —
both render read-only. **Qt normalises the markdown it writes**, so the editor only saves a
document the user actually modified — opening one never reformats it — and says so inline
when the first save would. **A foreign change to the edited document ends the session** and
reopens the document as it now is: the model is the authority, unflushed keystrokes yield,
and anything already flushed survives as a recoverable blob. An agent replacing the document under an open window resolves through
*Two writers, one folder* like every other write.

## A spec source is a kind the spec module runs

The spec was always a file somebody put beside the project. Now it may live somewhere
else and change there — a Confluence page or folder first, other systems later — and the
question was where the machinery for that belongs. Two shapes were on the table: each
source module owns its own tree, task and index writes and the spec module hands it a
writer seam; or the spec module runs every source and a source module is nothing but a
*kind* — how to ask for a location, whether it is connected, how to connect, how to fetch
and how to check. The second won, for the reason the asset catalog and the report
sources did: the interesting logic (records, nesting, the write, the undo entry, the
freshness note, the strip) is the same for every source, and writing it once in the
consumer is what makes the second kind a fetcher and a dialog. The contract is a
`Protocol` in `modules/spec/source_kind.py`, consumer-owned like `CanvasDrop`; the
Confluence module satisfies it structurally and the composition root hands the kinds in
as `SpecDeps.kinds`. The Qt-free shapes they exchange — `Snapshot`, `FetchedDocument`,
`Freshness`, `SourceStatus`, `SourceUnavailableError` — sit in
`domain/document_source.py`, beside `AssetSource`, because the spec module's headless
core reads them and the kind's headless half constructs them and neither may import the
other.

**A fetched page is an ordinary spec document.** Its markdown is a content-addressed
blob under `documents/`, its images are `assets/<sha16><suffix>` in the same area, and
the index row carries what makes it a *sourced* one: `source` (the record), `key` (the
kind's own id for the page), `version` (the kind's stamp, compared and never
interpreted), `parent` (the document above it, by name) and `title`. Absence keeps its
old meaning — a row without `source` is project-owned and editable — so no existing
reader learned a key. The consequence is the one that mattered: `spec show`, `spec
diff`, citations, coverage and the briefing needed no change at all, because
`apply_snapshot` writes every page through the same `import_document` a replace uses, and
a refreshed page therefore keeps `previous`. A page's **name is minted once** from its
title and kept across refreshes even when the title changes — a citation keys on the
name, and a title is a thing people edit — with the page matched by `(source, key)`.

**Refresh lands on the undo stack; a check writes nothing.** A person pressed Refresh
(or added the source), so Ctrl+Z must put the documents back — the Compile Docs
precedent, not the PR refresher's off-stack write, and `break_coalescing()` runs first
because the toolbar's buttons take no focus and two refreshes would otherwise merge into
one entry. The check is the other half of "check, then ask": on the interval, while a
Specs tab shows the project, the kind compares versions (two or three requests for a tree,
no bodies) and the strip says "3 pages changed at the source — Refresh"; nothing is
downloaded until the person asks. Both run on `TaskRunner`s in `spec/refresh.py`, the
`github/refresh.py` shape; a refusal that names the credential (a 401) is remembered per
window as *needs reconnect* until the kind's `config_changed` says otherwise.

**Fetching is window-only.** The token could be read by the CLI too — it is in the OS
keychain, which a shell can reach — and the decision was that it must not be: an agent's
shell runs with the person's keychain but not the person's judgement, and a spec source
is the one place the plan touches a credential that opens something outside the plan.
So `spec list` shows the tree and its provenance, `spec show` and `spec diff` read the
snapshot, `spec import` and `spec remove` refuse a sourced page with a pointer to the
tab, and adding, refreshing and removing a source are window acts. The LLM service's
rule (*An LLM call is a task*) is the same rule from the other side.

**The credential is the person's, per site, per machine, and `status()` never touches
the keychain.** The token goes through `framework/secrets_store.py` under
`spec_confluence.token:<host>`; the site → email row in `user_config` is *the fact that
a site is connected*. That split is not tidiness: an action's `state` runs on every
context change, and `keyring.get_password` is a D-Bus round trip that can raise a
keychain prompt in the middle of a menu opening. So `status()` reads the row, and the
token is read only inside `fetch`, `check` and the Connect dialog's probe, handed to the
client as a value. The dialog stores nothing until its probe read the page, and refuses
up front when `backend_problem()` says this machine cannot keep a secret — a plaintext
file is never the fallback, which is the lesson `gh auth login` learned in public.
Tokens expire within a year, so *Reconnect* is the same dialog and a normal event.

**Read-only against Confluence by construction, and every byte from it is data.** The
client has one request method and it is GET; the fake transport the tests hand in has no
other verb to call. Requests go only to the source's `*.atlassian.net` origin — the
locator is re-validated on every read from disk, because a plan is shared and a
colleague's `spec.json` is input — and a download's one redirect is followed only to an
Atlassian host, without the credential when the host changes. Bodies, attachment sizes,
page counts, depth, retries and `Retry-After` are all capped. The storage XHTML is parsed
by `html.parser` (no entity or DTD expansion, no network) into a depth-capped tree, and
the markdown it becomes carries no raw HTML, links only `http(s)`/`mailto`, and names only
images the fetch sniffed as raster and content-addressed itself; dynamic macros, whose
content is not in storage, become a labelled placeholder. Every error a person sees is
composed here from the status code — a library's own message is where a credential would
leak into a log.

## A step has a number, and the letter in front of it is derived

A uuid is the right identity for files that link to each other across renames and
branches, and the wrong thing to say out loud, type into a verb, or put in a branch name.
So a step also carries a **number**, dealt per project and never reused: `Step.number`,
minted in the one place a step joins a project (`Library.add_child`) from the project's
`last_number` high-water mark. The mark is stored rather than derived from the steps
present, because a deleted step's number must stay retired — its branch `agent/s7-…` and
its PR titled `S7: …` may outlive it, and a new `S7` would inherit them. Undo restores a
step with its number; a paste and an import arrive numberless and are dealt the next ones
(an import keeps the document's numbers where they are whole and unique, so `S7` survives
a round trip). Format 2 of the project format is this: the first migration numbers an
old project's steps in the order its `children` list records — the order it always showed
them in — and sets the mark past the last.

**The letter is not stored.** `S7` becomes `F7` when the step is placed as a feature and
`M7` when it becomes a milestone, because the letter says what the step *is* and the
kind is a set of toggles (*A kind is what a node is*): a stored letter would go stale the
moment a toggle flipped, and renumbering on a kind change would break the branch. The
root's `_step_key` ranks the kinds the way the body tone does — milestone over feature
over check over step — and every reader takes the answer from there: the spine, every
CLI row, `find_step` (which accepts `S7`, `s7` and bare `7`, and refuses a bare number
that names a step in several projects the way it refuses a shared title), the run name,
and the briefing's verbs, which address the step by key because a key is unambiguous
where a title may not be. The one cost is that a branch named after `s7` is not renamed
when the step becomes `F7`; the next launch reuses the worktree by its recorded name only
if the name matches, so a kind change after work has started earns a second branch. That
is rare, visible in `git branch`, and cheaper than a branch that lies.

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

`domain/schedule.py` is the second reader of that same walk, and the one that shows what the
shape was for. "When does this land" is "in what order can this be done", carrying estimates
instead of counting hops — so it takes `ordering.placed()`'s answer and lays the days end to
end from a start date. The order table, `dplanner schedule show` and its `--json` are three
renderings of one function, and none of them can date a step differently from another.

**It is handed a function, not a schema.** An estimate is a module's `module_data`, and the
domain must not learn what key it lives under — so `schedule()` asks for `days_for(step)` and
the composition root closes over the estimation module's reader. That keeps the two
directions of the rule intact at once: whoever owns a piece of data owns its shape, and
whoever derives from it needs one implementation rather than one per surface. It is also why
the derivation works for a build with no estimation module at all: the honest empty answer is
the same function, asked a question with no answer.

The start date itself is the smallest case of the same rule. **A project nobody has dated
starts today**, and that answer is computed (`estimation.schedule.start_of`) rather than
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

## Status is an aspect, and step types are emergent

There is no `type` field on a step, and none is coming. A *milestone* is a step carrying the
`step_milestone` aspect; an *agent task* is one carrying `step_agent_instruction`; a step can
be both at once, which no exclusive type field could say. What a step "is" emerges from
which aspects have something to say about it — the same way its subtitle on the canvas
already does.

Status went the same way after being weighed as a model field. It is a stored fact, not a
derivation — the graph can say what is *ready*, but only a person or an agent can say what
is *finished* or *stuck* — yet storing it does not make it a field: `VALUE_FIELDS["step"]`
is still `("title",)`, and that is the central design decision of the model holding. As an
aspect it costs no project-format migration, absence encodes `pending`, both surfaces got
the verb from one declaration (`dplanner status set '<step>' done` is how an agent reports
back), and the derivation that wants it — the progression board's status-aware frontier —
is handed a `status_for(step)` function, exactly as `schedule()` is handed `days_for`.

The one enum also shows where an aspect's GUI does not have to be a tab: status registers a
*Status* submenu of checkable Step verbs instead, and the canvas right-click, the order
table, the menu bar and the palette all grew it from that single registration. The canvas
never learned the vocabulary either — it renders a neutral `NodeAccent(muted, badge)`, and
the composition root translates "done" into muted and a milestone label into the badge.

The *Type* submenu is the same idea one step further: one checkable toggle per type-ish
aspect (Milestone, Feature, Agent, Ticket), each independent, because a Type radio group
would reintroduce the exclusive type field this section rules out. Toggling Milestone on
generates the next label from the project's existing ones (`next_milestone_label` in
`step_milestone/aspect.py`, shared with `dplanner milestone set`); toggling any of them off
shelves what it held, so nothing asks and the next toggle-on brings it back.

**A tab follows its aspect.** An `InspectorSection` may carry a `shown_for(step_id)`
predicate; the step panel re-asks it on every target change and on model writes to the
shown step, and hides the tab (`QTabBar.setTabVisible` — indices stay stable, so the
tab-to-page mapping never re-shuffles) when the answer is no. Only on a change, and
followed by `updateGeometry()`: `setTabVisible` clears its own layout-dirty flag when
handed an unchanged value and lays nothing out itself, so a blanket loop leaves the strip
painting stale rects — `NOTES-FOR-APPFRAME.md` §10 has the trap. Milestone, Agent and Ticket
answer with "does this step carry the aspect", so toggling one off removes its tab and
toggling it on brings the tab back *with* whatever the toggle generated — which is the
answer to the earlier worry that a generated milestone label needs somewhere to be edited:
it has one from the moment it exists. This deliberately reverses an older decision that
every tab is always visible; seven tabs on a step that is neither a milestone, an agent
step nor tracked anywhere taught nothing and buried the four that mattered. Sections
without a predicate (Estimate, Description, Handoff, GitHub) behave exactly as before,
and the project panel's cards are exempt — the only card is the project's standing
instruction, a project-level fact no step toggle should touch.

### Every tab follows a toggle, and absence encodes the default

The rule above started with five aspects and three exceptions: Estimate and Description were
unconditional blocks, Handoff and GitHub unconditional tabs. A milestone therefore came with
an estimate field for work it does not do, a description editor and a GitHub tab it will
never use — and "seven tabs that taught nothing" was the same complaint, one layer in.

So all four became toggles, and the mechanism was already written down: `FORMAT.md`'s
**marker entry**, the `{"on": true}` shape `step_ticket` and `step_check` use. No new store,
no format bump, and a fifth injection style avoided.

The part worth arguing about is which way absence points, and the answer is not the same for
all four:

| Aspect | Absence means | Because |
|---|---|---|
| Ticket, Check, Feature, Milestone, Agent, Tests, Handoff, GitHub | **off** | most steps are none of these; the marker records the claim |
| Estimate, Description | **on** | most steps are work, and work has a size and a name; the marker records the *opt-out* |

That is not two rules, it is `FORMAT.md`'s one rule — *absence encodes the default* —
applied honestly in both directions. The alternative was writing a marker at every step
creation site, of which there are four (two CLI, two GUI), and a module reaching into four
files outside its own package is exactly what the layering forbids. The inverted default
needs none of them: **existing projects change not at all**, every step keeps its Details
tab, and a milestone loses its estimate the moment somebody says so.

The Details tab *is* its blocks — and since the name became its first block (see *The
aspect bar renders the registry* below), it always has one to show, so it no longer asks
whether it would open onto blank space.

### Turning an aspect off shelves it

Every Type toggle used to delete what the aspect held, after asking. That was honest — a
toggle that silently destroyed a milestone label would be worse — but it made every toggle a
small act of courage, cost a confirm dialog per aspect, and got in the way of the gesture
the toggles exist for: switching a step from one kind to another and back. So an aspect
turned off is **shelved**: its `module_data` entry and its `module_text` move to a per-node
entry under the domain's own id, `modules/shelf.json` beside the step, and `turn_on`
restores them before it would ever write a fresh entry.

The shelf is a *domain* concern, not a flag inside each module's entry, and that is the
decision worth recording. The alternative — every aspect storing `{"off": true, …its data}`
— would have put a new key in front of every reader: a briefing, a lint, the canvas subtitle,
`dplanner … show`, each learning to check the flag before believing the data, and each a
place to forget. With the shelf, the entry is genuinely absent (or, for the two aspects whose
default is on, replaced by their opt-out marker exactly as before), so *absence encodes the
default* still holds and not one `read()` changed. The shelf only remembers what absence
replaced. Two consequences follow and both are handled once: the migration pass reaches into
the shelf (`migrate_shelved`, beside `migrate_module_data` at both call sites), because
shelved data is a module's data at the version it was shelved; and the asset catalog counts
a shelved prose's links as uses, so `asset prune` never sweeps away a picture the next
toggle-on would bring back to. A module's file area was already left alone by a toggle.

Two builders are the whole vocabulary — `turn_off(step, module, leaving=…)` and
`turn_on(step, module, fresh=…)` in `domain/shelf.py` — and both surfaces use them: a GUI
toggle pushes the command, a CLI `clear` applies it, so `dplanner milestone clear` and Step
▸ Type ▸ Milestone are one behaviour. That in turn collapsed eleven near-identical toggle
implementations into one `framework/aspect_toggle.py` factory: a module hands over its
`enabled` predicate, a `fresh` entry (a marker, or a generated milestone label, or one blank
test) and — for estimate and description — what to leave behind, and gets back the
checkable Step ▸ Type verb. The one soft spot, named rather than engineered away: a CLI
`set` on a shelved aspect writes a live entry and leaves the shelf's copy stale until the
next turn-off overwrites it. The shelf is never read while the aspect is on, so nothing
misreads; it is a few stale bytes, not a wrong answer.

### The aspect bar renders the registry, never a copy of it

The toggles live in Step ▸ Type, which is a menu, and a menu is not somewhere a person looks
when the question is *what does this step carry*. So the step panel wears an **aspect bar**
across its top — and the bar lists no aspects of its own. It reads the same specs the *Type*
submenu renders (`framework/aspect_bar.py`), through a context the host hands over, and
every button runs the owning module's toggle through `ActionRegistry.run`. So each stays one
undoable command, an aspect a build does not ship has no button, and adding an aspect is
still one registration in one package.

What the bar adds to the submenu is a *reading*. Its **left** is every toggle as a glyph.
Its **right** is one dropdown wearing the name and glyph of the template the step amounts
to: a name and the set of toggles that are on — *Milestone* is milestone and description,
*Agent* is agent, description and estimate, *Step* is the estimate and description every
step is born with. One control rather than five, because only one of them is ever true at a
time: five worded buttons said the same thing five times and four of them were always
wrong. The selected template's **glyph** wears its body tone, so a feature's face and a
feature node are one identity (which is why the tones moved to `theme/tones.py`, where both
can reach them) — the glyph and not the ground, because a template is *always* selected and
a wash that is permanently on says nothing, which is also what let ten per-button
stylesheets go. Picking a template
runs whichever toggles differ, on for its set and off for everything else, inside one
`UndoService.gesture`, so *Make Milestone* is one Ctrl+Z however many aspects it moved and
each is still the owning module's own command — the gesture is the framework's answer to
"one gesture, several verbs", and it is what let the bar stay a presenter with no command
of its own. And it goes both ways: a template reads as selected exactly when the step
carries its set and nothing else, so a combination somebody built toggle by toggle lights
up the template it amounts to, and one extra aspect puts it out — onto *Step*, the
catch-all (`AspectTemplate.catch_all`), because a step with an unnamed combination of
aspects is still a step and a bar with nothing lit would be saying it is nothing. Nothing
stores which template is current; it is a set comparison on every refresh, which is the same *derived,
never stored* rule as the ordering. Which templates exist is `StepPropertiesDeps.templates`,
named by the composition root in the order the bar shows them, for the same reason the
scope kinds are wired rather than inferred.

The strip is `framework/toolbar.py`'s `Toolbar`, so what no longer fits is taken off from
the right and listed in a `…` menu as glyph **and words** — where Qt's own `»` pops the
hidden buttons up as glyphs again, which is no help to somebody who could not read the
glyph on the strip. It is **dense**, a mode the primitive offers: a strip of verbs folds
gracefully because losing a verb to a menu costs a click, but this row answers *what does
this step carry*, and a row that folds stops answering. The panel cannot be narrower than
479 px — its tab pages, not the bar — which leaves the strip about 356; at the verb strip's
45 px buttons that seats five of the ten toggles, and at the dense 29 px it seats all ten.

And the dropdown sits **beside** the strip rather than on it. A widget added to a `Toolbar`
hides when there is no room for it, so the one control naming what the step *is* would be
the first casualty of a narrow dock — the canvas's layout picker and the *Updating…*
indicator sit outside their strips for exactly that reason. Its width is fixed to its
widest name, because a face that reports what is on and changes size as it does re-folds
the strip beside it. That inverts what the two `QToolBar`s used to do, deliberately: the
old left bar took the slack so the facets kept their glyphs and the kinds folded first.
The kinds are the summary and the facets are the detail, and it is the summary a narrow
dock should keep.

It replaced the "+" beside the tabs and the dialog of checkboxes it opened, which was the
same registry-rendering rule with a worse reading — a list you had to summon to see what a
step already was. It settles the same question that dialog did: **"some step types can never
carry this aspect" needs no mechanism at all**. A toggle whose `state()` returns
`ActionState(enabled=False, label="Estimate — a milestone has no work of its own")` renders
as a greyed button carrying its reason in the tooltip, because *hidden means absent; disabled
means not now* already says so. Nothing was built for it; it is one predicate away when it is
wanted.

The context arrives as a function rather than a `ContextService`, which is what lets the
panel inside the details *dialog* — showing a step nobody selected — hand over one naming
its own step. The specs cannot tell the difference, and neither can they be made to care.

Two smaller things fell out of that rework. A toggle's `state()` **never returns
`visible=False`** — *hidden means absent; disabled means not now* already says a toggle
that cannot apply is greyed, and an aspect a build does not ship never reaches the registry
— so the bar's state triple lost its first third; a strip that re-shows whatever fits on
every reflow could not have honoured it anyway. And the bar **announces its refresh**
rather than leaving a host to listen to the model: the dialog's lead repeats the bar's
answer in words, and applying a template ends with the bar refreshing itself, which is
after the last write any model listener hears. A host that watched the model showed the
lead one gesture behind.
The panel re-reads the bar on every model write to the shown step, because one toggle can
change another's state.

The name moved with it. It used to sit above the tab bar as a field of the panel's own; it is
now the first block of the Details tab, registered by `step_properties` like any other block
at order 0, so the modal's control stack reads top-down from the one field every step has —
and the Details tab, having a block that always shows, no longer asks whether it has one.

### A kind is what a node is; a facet is what it carries

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

**Step ▸ New is one verb, and the dialog is where a fresh step is configured.** It used to be
a submenu — a plain step, then one entry per kind, each prompting for a title — and the kinds
were a `StepKind` list of their own with an `entry` function per kind. Once the bar could say
what a step is in one click, that submenu was a second, narrower way to say the same thing:
it offered four of eleven aspects, asked for a name in a `QInputDialog` that the details
dialog already has a field for, and needed its own list to stay in step with the toggles.
So New creates a plain step titled "New step" and opens `steps.details` on it — through the
`created` seam, where selecting the new step already lived — with the name field focused and
its text selected. Typing replaces the placeholder, the bar sets the kind, Escape closes.
The canvas double-click does the same at the point it was given. What went: `kinds.py`, the
toolbar's New dropdown, and the prompt.

The body colours follow the same ranking the model uses. Done outranks a kind — a shipped
milestone reads finished — and a milestone outranks a feature, because that is the coarser
claim, the same order `kind_of()` reads the markers in. What the body cannot say, the
medallion does: a node that is both keeps both glyphs.

Teal was chosen for the feature by where the hues already were, not by taste: 76° from the
milestone's violet so the two collectors never read as one, and 42° from the done green —
which additionally *mutes* its node, so that pair is separated by weight as well as by hue.
The nearest claimed hue is the agent-run chip's teal, and that is a labelled pill on the
bottom edge of a running step, never a body.

Every Type toggle carries its **medallion glyph** — a painter from `theme/icons.py`'s
`GLYPH_ICONS` vocabulary, the same one the canvas answers in — so one declaration puts the
same glyph on the Type submenu entry, on the aspect bar and on the node itself.

### A step placed by pointing at a spot earns a stored position

The ambient layout is never persisted (*An explicit sort persists; the ambient layout never
does*), and placing a node by pointing at the canvas is the same kind of act as dragging
one: somebody chose where it goes. So it is stored, and the choice arrives on the same
command as the node itself — a gesture is one undo, so New ▸ Feature at a point is one
`CompositeCommand` of add, mark and place rather than three entries on the stack.

That pushed the creation into one function. `StepVerbs.create()` is now the only place a
step is born on the canvas, and the double-click on empty space — which already placed a
node at a point — calls it too. The consolidation deleted a second implementation rather
than adding a first.

Where "the point" comes from is `GraphView.last_click`, recorded on **every** button press
*before* the mode stack is offered the event: "where I last clicked" is true whether or not
a mode claimed the press, and a mode-aware version would have to be right in five places
instead of one. A right-click records too, so the menu's own New lands where the menu was
raised — and the context handler records again for the keyboard menu key, which sends no
press at all and would otherwise reuse a stale point. A canvas nobody has clicked answers
`None`, and New falls back to the ambient layout, which is what it always did.

Three smaller things ride on the same seams, and all belong to the canvas rather than to
the verb, which is why `StepVerbs` takes callbacks rather than doing them itself. Through
`placed` — which a paste shares, handing over every step it added at once — the new step
becomes the **selection**, and the remembered point **steps one row down** —
`placement.below()`, the automatic layout's own row pitch — so pressing New twice leaves two
nodes where a stale point would have hidden one exactly under the other. Through `created`
— which only a birth calls, never a paste, because pasted steps arrive named — the details
dialog **opens on it**, the same `steps.details` a double-click on a node runs, so naming
the step and saying what it is are the gesture's second half. A double-click on empty space
gets all three too: it pointed at a spot in the same sense.


A **drop** is the third caller. Something dragged from a panel onto the canvas — a feature
from the Features panel — is a one-shot gesture exactly like the double-click on empty
space: Qt's drag events never reach the mouse handlers the mode stack reads, and a mode has
state to enter and leave where a drop has neither. So `GraphView` records the point and
hands the mime data up, `ProjectActivity` finds the `CanvasDrop` for its type, and the
handler — written in the composition root, because it reads one module's catalogue and
births through another module's `create` — places the step with its marker and its position
in the one undo step every placed step gets. What the canvas accepts is a tuple of
`CanvasDrop`s on its `Deps`, named by the root like the kinds; a refusal is a `CliError`
whose message is the status bar's, the same words the CLI would print.

## The description is the instructions

A step used to carry two prose fields — a description and an agent instruction — and the
distinction ("what it is" versus "how to do it") read well in a docstring and nowhere
else. In practice the two said the same thing twice, or an agent driving the CLI set one
when it meant the other, and a step with a rich description and no instruction could not
be briefed at all. The fix deleted the duplication instead of documenting it harder:
**an agent step is briefed with its own description.** Marking a step for agent execution
is the `step_agent_instruction` aspect's `module_data` entry (Step ▸ Type ▸ Agent,
`dplanner agent on`, `step add --agent`); the briefing's `## Instructions` block is the
description body and its images, and the separate `## Description` context section is
omitted so the text appears exactly once.

The *separate instruction* survives as the opt-out, not the default: the "Separate agent
instruction" checkbox in the Description tab (a `SeparateInstructionLink` of typed
callbacks — the description module never learns the agent module's name), `dplanner agent
set`, or `step add --agent-file`. Writing separate text implies both the mark and the
opt-out, which is what keeps plans authored before the mark existed working with no
migration. The opt-out itself is *stored* (`{"separate": true}`) rather than derived from
text-presence, because "opted in but not yet typed" is a real state that must survive a
selection change; the encodings cannot disagree because turning the aspect off clears
both. With a separate instruction present, the description returns to its own
`## Description` section and the separate text takes `## Instructions`.

The seam lives where the other cross-module prompt decisions do: `Briefing` carries an
`instruction(library, step, files) → PromptPart` member, defaulted module-locally to the
step's own text, overridden by the composition root's `_briefing_instruction` — the one
file allowed to read the description on the agent module's behalf. Run Agent, the Agent
tab's Prompt page and `dplanner agent prompt` all assemble through it, so no surface can
brief a step differently. One consequence worth naming for existing plans: a described,
uninstructed step that used to render `## Description` now renders that text as
`## Instructions` — the same words, under the heading the executing agent actually obeys.

## What reaches a step is derived at read time

A note (`modules/notes/`) stores only what was said: a label, a title, a body, the step it
was made on, the steps it is *for*, and — only as the exception — a reach. Who *sees* it
is never written down. `reach.reaching()` walks the cone behind a step and answers with
two sets — the notes addressed to it, and the rest that reach it — the same rule as
ordering, for the same reason: `dplanner step link` rewires the cone with no window running
to notice, and a stored answer would be wrong exactly when an agent is driving. The Agent
tab's Notes pane, `dplanner note index` and the assembled agent prompt are three readers of
that one function and one `briefing_blocks` rendering, so no surface can describe what a
step inherits another surface would dispute. *A note is a record with a label* below has
the shape and why the index is an index.

## Running an agent launches a peer, not a task

*Run Agent* writes the briefing to a per-run temp directory — never the project, which
would dirty it and end up in version control — and spawns a terminal detached
(`start_new_session`). Deliberately **not** through `TaskRunner`: a task promises progress,
cancellation and a completion that returns to the GUI thread, and none of those are honest
about a terminal the user owns from the moment it opens. The agent reports back through the
CLI instead (`status set`, `note add`), which the two-writers machinery already handles.

The briefing opens with the **project's standing instruction** — the same module's prose on
the project node, edited in the project panel's Agent card and in the Agent tab's Project
part (two bindings over one field, one undo stack) — ahead of the step's `## Instructions`
(its description, unless a separate instruction exists — see *The description is the
instructions*) and, after it, the notes index.

The briefing is deliberately **self-contained**: between the standing instruction and the
step's own sit the step's facts — its description as a section of its own only when a
separate instruction displaced it, the feature it realises or — on a work step — the
features it *flows into* (titles *and* the spec passages they were read from, so the agent
reads the obligation rather than chasing an id; the flows-into list is `scope.gatherers`,
the same walk the Covers tab reads), and the branch or PR the work lands on. The project's
topology sits ahead of all of these as a *project section*, right after the standing
instruction, because it frames every step the same way. The agent module renders these as opaque
blocks; the composition root words them, exactly as it words the preamble and epilogue,
because each names another module's vocabulary. Two block kinds, two framings: *parts* are
context handed forward from earlier steps (`### From "…"`), *sections* are facts about this
step (`## …`). One builder per kind lives in `modules/__init__.py` and both surfaces — Run
Agent and `dplanner agent prompt` — call the same two functions, so the window and the CLI
cannot brief a step two ways. An executing agent needs `agent prompt` and nothing else;
needing five verbs to reconstruct a briefing was the failure this replaces. Files attached at either level are **staged into the per-run
directory** beside `prompt.md` and referenced by their staged absolute paths: the agent runs
in the repository it opened at, so the prompt's file paths are absolute — anything else would point at
nothing it can reach. Asset names are content-addressed, so staging is a flat, collision-safe
copy; an unreadable path stays in the prompt as itself rather than vanishing.

Resolution is settings template first (`{script}`, `{prompt_file}`, `{workdir}`), then a
platform table, then `None` — and `None` is an answer: the fallback dialog delivers the
prompt itself, because the prompt is the deliverable and the terminal was only one way to hand
it over. `dplanner agent prompt` prints the same assembly (with the same absolute paths —
the run directory does not exist yet), and *Preview Agent Prompt* shows it in the window.

The assembly is also where the CLI grew the composition root's other seam:
`agent_cli.commands(prompt_parts=…, epilogue=…)` takes typed callables the way a module's
`Deps` does, supplied by `default_cli_commands()`. A `cli.py` never imports another module;
what crosses modules arrives as arguments — `skill_commands(specs, described)` made that
shape first, and this is its second use.

### One agent per chosen step, and why the limit is the last check

*Run Agent* reads `chosen_steps` — the framework's one reading of *which steps is this verb
about*, the same one Delete, Cut, Copy, Duplicate and Isolate act on — so a lasso over three
agent steps is *Run 3 Agents…*, and the verb needed no gesture of its own to learn it. Three
decisions came with that.

**Every chosen step must be launchable, or none is.** A step in the selection with no
briefing, no agent mark or no checkout greys the verb for the whole selection, and the label
names that step and its reason. Running the subset that qualifies is the tempting
alternative and the wrong one: it launches fewer agents than were asked for and says so
nowhere, and the person finds out by counting terminals. This is *hidden means absent;
disabled means not now* applied to a set — the precondition is still taught, it just now
names which member failed it.

**The graph gate asks once.** Prerequisites are checked per step, but the question is one
box for the gesture, listing each waiting step with what it waits on. A box per step would
ask four times about a single decision, and *Run Anyway* on the third of four would leave
the person unable to say what they had already agreed to. Cancel means none of them, which
is the only honest reading of one question.

**The count is a precondition, not a warning.** Four agents is four terminals, four
worktrees, four live sessions and four `dplanner` writers against one plan; a selection is
made with one flick of the wrist and can hold the whole graph. So *Settings ▸ Agent
profiles* carries **Max agents launched at once** — four by default — and a selection past
it greys the verb with the number rather than asking. A confirmation would be the wrong
shape here: the limit is not a risk to accept once, it is a standing statement about what
this desk can hold, so the way past it is to change it in the one place it lives. It sits
beside the agent command and the terminal template for that reason — per user, per
machine, never in the plan, because how many peers one machine can carry is not a fact
about the project.

`_run` re-checks the limit rather than trusting the state gate, on the same principle every
verb here follows: a presenter may run a stale state, and the guard that matters is the one
in the act.

### A launch says the work has started

The graph gates launching by *reading* status (`status_for`, the progression board's
seam); a launch also *writes* one. When a shell opens, the step is claimed `in-progress`
through `mark_started` — the writer half of the same seam, wired by the composition root
to `step_status`'s own `record_started`, so the agent module never learns the vocabulary
and the status module keeps the only place its words are spelled.

Three decisions sit in that one line.

**It is off the undo stack**, with an origin of its own, exactly like the launch stamp
beside it (*The peer reports back through its run directory* has that reasoning). The
claim rides on something Ctrl+Z cannot take back — a detached shell now exists — and an
undo entry would let the next Ctrl+Z file the step as pending while an agent is still
working in it. `record_started` answers False and writes nothing when the step already
claims to be in progress, so a second launch dirties no file; it *does* override `done`,
because launching an agent on a finished step means the work resumed and there is no
other honest reading.

**It is a switch, on by default** — *Agent profiles ▸ On launch*, beside *Max agents launched at
once* and per user like the rest of that page. On, for the reason the marks are on: the
agent's own first report is minutes away (the briefing's protocol has it setting
`agent-state`, not status), and a step somebody
is working on that still reads pending is a lie the plan was never asked to tell. A
switch rather than a rule, because a plan whose statuses a person keeps by hand should
not have the window writing into it — so switching it off is the deliberate act, and
nothing else about the launch changes.

**Only Run Agent makes it.** `_launch` — the one place a terminal opens — is shared with
the conflict hand-over and knows nothing of the claim; it is made one level up, in the
step loop, after `_launch` has answered that a shell exists. That placement buys two
things at once: a run over a selection claims each step as its own shell opens and stops
claiming where the shells stop, so three steps of which the third found no terminal leave
two marked and one not; and an agent handed two writers' versions of a plan file is never
marked as doing the step's work — it is merging, and marking that step in progress would
be the same lie in the other direction. The verb decides; the mechanism obeys.

Nothing un-claims it. Finishing is the agent's own `dplanner status set … done`, or the
person's from Step ▸ Status — the run ending clears the agent *chip* (that state is about
the shell) and deliberately says nothing about where the work stands, which is the same
line *A test result is not a step status* draws between two vocabularies that must not
be folded into one.

### The peer is a top-level session, and the briefing stays out of argv

Four agents died at once on 2026-09-05, and DPlanner had not crashed: it was killed, with
them, by one agent's `pkill -f "Web.Host"`. The chain had three links, and each is now a
rule.

**The briefing was the command line.** The wrapper ran `claude … "$(cat prompt.md)"`, so
every agent's argv was its whole briefing — and every briefing in that project mentioned
`Web.Host` in an inherited handoff. An agent restarting its own .NET host by pattern
matched every other agent on the machine. The opening prompt is now one line
(`launcher.opening_prompt`): *read your briefing in `<file>` in full, then follow it*. The
line carries a path and nothing the project is about, so no pattern drawn from the work can
match it; it also stays under the platform's argument limit, which a briefing with a long
handoff would not, and `ps` stays readable. The agent pays one file read.

That read is outside the checkout, and Claude Code asks before reading outside its
working directories — one approval per launch, on every platform, and again for each
staged asset. So the Claude preset hands the run directory over as an additional working
directory (`--add-dir {run_dir}`), which its documentation says makes reads there ask
nothing. Two facts shape the flag's place and its value. `--add-dir` takes a *list*, so
it sits before another option and never before `{prompt}`: probed, a prompt following
it was taken for a second directory and the session started with no prompt at all. And
the directory is resolved when it is made (`new_run_dir`): the permission check compares
a file's resolved path, macOS's temp directory sits under `/var`, a symlink to
`/private/var`, and Windows's Temp is often an 8.3 short name — the pointer line, the
staged asset paths and the flag all derive from that one path, so every spelling agrees.

**The window was an agent's process, and its agents were its children.** *The window is a
word* has that half. The launcher's own half is `scrubbed_environment()`: the terminal is
spawned without the session markers an agent CLI sets in its shells, so an agent DPlanner
launches is a top-level session with a transcript of its own, whatever started DPlanner.
The scrub is a list, not the prefix — what Claude Code sets in every shell it runs
(`CLAUDECODE`, the parent's session id, the child-session flag that turns transcript
persistence off, its pid, the effort, the agent flag) and what it scrubs itself before a
session that must stand on its own (its exec path, the trace id), read off the 2.1 binary
rather than guessed, plus any variable under its prefix naming a session, a parent, a
child or the messaging bridge (a 2.1.258 shell carries the parent's bridge socket and
token, which the list did not name and the rule now does) — because the same prefix
carries the person's configuration (`CLAUDE_CONFIG_DIR`,
`CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_MAX_OUTPUT_TOKENS`), and an agent launched without
that cannot sign in. The first version named two markers and a rule; the rule caught the
session id but not the pid, and a list read off the binary is the honest fix.

**Nothing said not to kill by pattern.** The skill's *Cutting agent steps* and the
briefing's preamble now both do: other agents work beside you in the same repository, their
processes carry the same names and paths as yours, kill only by a pid your own shell
started. The preamble is the one text every executing agent reads; the skill is where the
convention lives for an agent driving the plan by hand.

One more thing the incident cost was the way back. The Claude preset now names the run's
session up front (`--session-id {session}`, a UUID minted per launch by `prepare`), the
wrapper writes it into the shell facts beside `dir` (where the agent works, recorded once
it is in place — a worktree, usually) and `resume` (`cd "<dir>" && claude --resume <id>`,
composed from the preset's `resume` template, only for a preset's own command since a
custom command's resume syntax is unknown), and prints the same command above *Press
Enter* when a run ends badly. The Agents browser shows it under an ended row. A *Resume
Agent* verb that opens a terminal on it is the obvious next step and is deliberately not
built yet: the hint is what the recovery needed, and a second launch path is a feature to
ask for.

**A preset that changes carries the texts it replaced.** The settings page stores the
picked preset's *text* — the dropdown reflects the field, which is what lets a preset be
edited into a custom command — so a machine that picked Claude Code before `--session-id`
was added held `claude --permission-mode plan {prompt}` from then on: read as Custom,
launched without a session id, never resumable, and no later change to the preset
reached it. `AgentPreset.superseded` lists every command text the preset has shipped, and
`launcher.current_command` maps a stored one to the current — the settings page reads
through it, so the dropdown shows the preset again, and so do the wrapper and the resume
hint. The same idea as a `Takeover` for module data: the old spelling is the contract,
and the successor carries it.

### The peer reports back through its run directory

A detached terminal tells nobody when it is done, and the four platforms' terminals have
no shared way to ask. What every one of them does have is the wrapper script: the one
process that starts the agent and is still there when it exits. So the script reports,
beside the prompt it was launched with — the shell's facts on start (`shell`: tty, pid,
tmux pane, `$TERM_PROGRAM`, the window title it set) and the agent's exit status at the
end (`exit`; the word `closed` from a HUP trap when the terminal was shut on it). Two
plain files, no terminal-specific hook, so the report is the same for every row of the
terminal table and for an agent CLI nobody has heard of yet.

The other half is the window's, in `modules/step_agent_run/`. It remembers every run it
launched in the **user's store** (`user_config`) — a temp directory and a pid are facts
about this machine, and a per-user file is what a rebuilt window re-adopts from — and
polls them every two seconds *while one is live*. `runs.settle` reads the two files:
exit 0 is *finished*, anything else *failed*, the trap's word or a dead pid *closed*, a
vanished directory *lost*. An ended run clears the step's state the way the launch stamped
it — directly, off the undo stack, with the launch origin — because a chip on a step
nobody is working on is a lie, and the CLI's own `agent-state clear` is the protocol only
for the agent that remembered to send it.

One race is designed around. An agent's last `dplanner status set … done` and its exit
land within a tick of each other, and a window that wrote the exit over a plan it had not
re-read would trip the store's own refusal and leave the user with a conflict notice for
something no person did. So the tick asks the store first — `changed_underneath()`, the
same narrowed answer the library watcher reads — and stands down when it is true. It asks
**only once a run has ended**: the answer is a walk over every plan file, on the GUI
thread, and asked every two seconds for its own sake it stalled a large library's window
for as long as the walk took (300–500 ms, in the journal as `poll` spans) the whole time
an agent ran; settling a run is a handful of stats, so a tick with nothing ended costs
nothing. The
watcher's move is to adopt the change into the live model (*Adopting the other writer's
changes in place*), after which the same module, its runs intact, checks again on the next
tick over a plan it has seen; when the store cannot reconcile and the watcher falls back to
a rebuild, the new module re-adopts its runs from the per-user store and checks then. A
conflict the user has not yet answered keeps the store's answer true and the tick standing
down, which is the rule doing its job: *nothing writes over a file it has not seen* holds
for background writers too.

Finding the window again (*Show Agent Terminal*) is honestly best-effort, and the facts the
script recorded are chosen so the effort mostly succeeds even after the agent has retitled
the window: a tmux pane is selected wherever it is; Terminal and iTerm are asked, through
AppleScript, for the tab on the shell's tty; a Linux terminal that owns its windows (kitty,
Alacritty, xterm, Ghostty) is found by walking the shell's ancestors to the pid that owns
one, with the title as the fallback, through xdotool or wmctrl; Windows activates the
PowerShell pid, then the title. Where a desktop cannot — a Wayland session with neither
tool — the verb is *disabled with the reason*, never hidden: the rule from *Hidden means
absent*. Every provider answers a reason string, so one verb reads them all.

The offer to switch lives in three places, and the gate is the same question asked of the
same run. Tools ▸ Agent List is the quick switch — a data child menu (see *A child menu of
data is rebuilt when it opens*) listing every live run this window launched, one entry per
run raising its terminal, the browser under a rule at the bottom; the browser's rows and
*Show Agent Terminal* are the other two. All three ask `focus_reason`, which is **per run,
not per desktop**: it reads the shell's recorded facts in the same order `focus` tries
them, so a run inside a tmux pane stays offered on a Wayland session with no window tool —
tmux can select the pane wherever its client is — while the run in a bare window beside it
is greyed with what the desktop would need. Gating every row on the desktop's answer alone
was the first version, and it greyed switches that would have worked.

### A worktree is the step's decision, and the run is named after the step

Whether an agent works in a fresh git worktree was a global switch on the Agent settings
page. It is the agent aspect's own field now — `"worktree": false` is the opt-out, absence
is on — because the question is about the step, not the machine: nearly every step wants
isolation, and the few that do not (a release cut that must tag the checkout the window
shows, a conflict the window hands over, a step that only reads) are the same few on
every machine. A global switch is also one nobody dares turn off, since turning it off for
one step turns it off for the twenty launched after it. The Agent tab carries the checkbox
beside Run Agent, `dplanner agent worktree <step> off` and `step add --no-worktree` are the
CLI's word, and the skill tells an agent to leave it on unless the step genuinely must
share the working tree.

**The worktree is prepared by the wrapper script, and a worktree it cannot prepare stops
the run.** The first version put the worktrees under `.dplanner/worktrees/` and wrapped
every git call in `|| true`. Two things followed. A project kept in a subfolder of its
repository leaves a `.dplanner` pointer *file* at the root (FORMAT.md's pointer), so `git
worktree add` under that path failed with *Not a directory* on every such project; and the
script, having hidden the failure, carried on in the main checkout — so two agents
launched "into fresh worktrees" edited one checkout on one branch, which is the bug this
section exists for. The worktrees live in `.dplanner-worktrees/` now, and the script
prunes stale registrations, reuses the branch when it exists, verifies the tree is a
linked worktree (a `.git` *file*), and otherwise prints git's reason, waits for Enter and
writes `1` to the exit file — the window reports *failed (exit 1)*, the same way it reports
any agent that died. Never the main checkout by accident.

**The run is named after the step, once.** `launcher.run_name(key, ticket, title)` —
`f7-PROJ-12-build-the-modal`, made ref-safe — is the worktree's directory, the branch's
last component and the start of the terminal's title. The key first so `git branch` sorts
by step, the ticket so the branch answers the tracker too, the slug for the person reading
the list. The pieces are aspects the launcher never reads, so the root composes them
(`_step_key`, `_ticket_key`) and hands them to the module; the root's `_run_name` applies
the same launcher rule, because the **briefing names the worktree**: its preamble tells the
agent to confirm `git rev-parse --show-toplevel` ends in that directory and the branch is
`agent/<name>`, and to stop if either differs. The check costs the agent two commands and
closes the gap the silent script left — a run that somehow lands in the main checkout is
refused by the agent, not just by the script. A step whose worktree is off is told so
instead, and warned that it shares the developer's tree.

**Inside the worktree the plan of record is still the library's.** The plan is usually
versioned, so the walk `cli/discovery.py` makes from the agent's working directory finds
the *branch's copy* of `project.dproj` — a directory not in the library. Resolving that
copy would write the agent's status into a file nobody is looking at until the branch
merges. So a project found by the walk that is not in the library, but whose `project.dproj`
declares the id of one that is, resolves to the library's project — the one the window
shows and autosaves — and the repository match below it counts a linked worktree as its
main checkout (`core/storage/git.py::main_checkout`, which the skill's worktree warning
reads too). The agent's `dplanner` calls therefore land where the person is looking, and
the branch's copy of the plan is never touched, so a merge never has to reconcile it.

### Which terminal opens is a table, not a chain

The platform `if`-chain that used to resolve a terminal is one table now, `TERMINALS`:
a row per known terminal per platform — Terminal, iTerm and Ghostty on macOS; Windows
Terminal, the Command Prompt and Ghostty on Windows; Ghostty, kitty, Alacritty, foot,
GNOME Terminal, Konsole and xterm on Linux, with tmux *last* on the two platforms it runs
on — each with the command that opens it on the wrapper script and a probe (a binary on
PATH, an application bundle, an environment variable) saying whether it is installed.
*Automatic* is the first installed row, which is the platform's own default terminal, so
an untouched setting behaves the way the machine does; the settings dropdown lists the
same rows, marks the ones the probe cannot find, and pre-fills the editable template —
the agent presets' pattern, applied to the second choice on the same page. One table with
two readers is what keeps the dropdown from ever offering a terminal the launch would not
find, and a new terminal is a row rather than a branch.

**tmux was first, and that was the bug that looked like Ghostty's.** A DPlanner started
from a shell inside tmux inherits `$TMUX`, its probe answered yes, and Automatic opened
every agent with `tmux new-window` — a new window in whatever session tmux called current,
inside a Ghostty window the person was typing in, and a different one each time the
current session changed. It read as "the agent lands in a random split". Ghostty itself
never does that: its `-e` forces a fresh process (`gtk-single-instance=false`) with a
window of its own. So tmux is the last resort — what Automatic reaches for over ssh with
no terminal installed — and a desktop application's agent gets a desktop window.

### An agent CLI is a harness, and a harness is a module

The launcher used to carry a `PRESETS` table of three agent commands and a list of the
environment variables Claude Code sets in its shells, and every other fact about an agent
CLI — whether it can be resumed, where it keeps its transcripts — had nowhere to go. Codex
support was the second CLI to need such facts, and a second block of `if preset.id ==
"codex"` in the launcher was the shape to refuse.

So an agent CLI is a **harness** now (`domain/agents.py`), and each one is a module:
`modules/agent_claude/`, `agent_codex/`, `agent_opencode/`, each a Qt-free `harness.py`
exporting one `AgentHarness` — the command with its placeholders, the resume template,
the texts the command shipped earlier, the shell markers, and a `report` reader — and the
composition root's `agent_harnesses()` is the tuple every reader takes as an argument:
the launcher, the settings page, the run tracker, the `usage` verbs and the entry point's
shell guard. The contract lives in `domain/` beside `assets.py` and `aspects.py` for the
same reason those do: it must be importable without Qt, and it is what modules agree
on rather than what any one of them owns. Three consequences were decided deliberately.

**Capabilities are derived from the record, never declared beside it.** A settings page
wants to say *Codex — resumes, counts tokens*, and the temptation is a `capabilities`
tuple on the record. But a tuple beside the fields it describes is a second statement
that can disagree with the first — a harness whose `resume` template was removed and
whose tuple still said *resumes*. So `names_session` is *is `{session}` in the command*,
`counts_tokens` is *is there a reader*, `resumes` is *a resume template, and a way to the
id* — and `capabilities()` words them. Nothing to keep in step.

**A harness that mints its own id is found afterwards, by where and when.** Claude names
its session up front (`--session-id`, minted per launch), and that is the best case: the
id is known before the shell opens, the wrapper writes it into the facts, and the resume
command is printed on exit. Codex and OpenCode do not take an id; they mint one. Both,
though, record where a session started and when — Codex in a rollout file whose first
line carries the `cwd`, OpenCode in a database row with a `directory` — and the launcher
knows both facts about every run it started. So a harness's `report(RunFacts)` finds the
run by directory and launch time (the earliest record started there at or after the
launch, with two minutes' slack for a stamp taken after the shell) and answers the id
with the usage. A step's worktree is one directory per run, which makes the match exact;
a step that works in the checkout itself shares it with other runs, and the start time
tells them apart. The found id is written back onto the run, and *that* is what makes a
Codex run resumable in the Agents browser — parity with Claude by a different route,
without a flag Codex does not have.

**The reader is tolerant by construction.** Every one of these formats is the vendor's
own, undocumented (Claude Code says so in as many words) and free to change between
releases. A reader that raised on a changed field would take the whole run tracker down
on the day a vendor shipped; one that answers `None` leaves the run ended as before with
no tokens beside it, which is the honest report. The OpenTelemetry metrics Claude Code
exports are the supported channel — `claude_code.token.usage` with a `session.id` on
every point — and they need an OTLP collector listening on this machine, which is a
feature to build when a transcript reader has failed, not before. Its console exporter
writes to the agent's own stdout, so it cannot serve an interactive session.

### A launch profile is a name over the two choices

Run Agent has always asked two questions — which agent, which terminal — and the settings
page answered each once, for the whole machine. Two terminals of agents at once broke
that: a Claude run in a Ghostty window for the step under the cursor, and four Codex runs
side by side in a multiplexer for the four the lasso caught, are not one setting with a
different value; they are two ways of working a person switches between all day.

A **profile** (`step_agent_instruction/profiles.py`) is the two answers under a name,
and the list of them is the setting. The first is the default — what *Run Agent…* itself
runs, so the verb, the Agent tab's button and the palette need no picker — and the rest
are the entries of *Step ▸ Run Agent With*, a data child menu rebuilt on open so a profile
added in Settings is offered at once. Each entry is greyed with its own reason: the
profile's terminal is one probe (`launcher.template_refusal` — *herdr is not installed*,
*not inside a tmux session*), asked before any step is, because it is the profile's
refusal and not the selection's. Over a multi-selection every chosen step goes through
the one picked profile, one pane per step in a multiplexer — which is the gesture the
whole thing exists for: see four ready steps on the board, select them, pick *Codex in
herdr*, and they are running side by side.

A profile's name is derived until it is typed. A new profile is a copy of the picked one
named by what it does — *Claude Code in herdr* — and the usual next moves, changing the
terminal and then the agent, keep renaming it to match, so the list never holds a *Default
copy* that is actually Codex in tmux. The rule that makes this safe is one comparison in
`update_profile`: a name is *derived* while it still reads as what the profile's old
choices suggested (numbered or not), and a name that reads as anything else was a
person's and is kept. No flag is stored, so an old profile list needs no migration; a
typed name that happens to equal the suggestion behaves as derived, which is the right
answer for a name that says what the profile does. Names stay unique either way — *Run
Agent With* and the default lookup go by name — and a typed duplicate is numbered rather
than refused, since a settings field is no place for a modal.

The two single settings the profiles replaced are read as the default profile when no
list has been stored, so a machine configured before profiles existed keeps its choices
without anybody retyping them — the same idea as a harness carrying the command texts it
shipped earlier. Profiles are per user, per machine (`user_config`), never the plan.

### A multiplexer is a row, and a two-call one is one template

herdr — the multiplexer built for exactly this, a headless server the person's terminal
attaches to, with a workspace per repository and an agent-state sidebar — adds a shell in
two calls: `herdr workspace create` prints, as JSON, the pane it made, and `herdr pane run
<pane> <command…>` types a command into it. The terminal table's one template per row
cannot say that, and the honest alternatives were a Python opener per multiplexer (a
second table of callables beside the first) or a `sh -c` one-liner nobody could read in
a settings field.

The row is `herdr workspace create … && herdr pane run {pane} {script}`
instead: `launcher.spawn` splits a command at its `&&` tokens, runs the stages in turn to
completion, and fills `{pane}` in a later stage with what the earlier one printed (a
`pane_id` in its JSON, else its last line). It is what a person would type, it stays a
row a person can edit, and tmux's `new-window -P -F '#{pane_id}'` or `wezterm cli spawn`
would feed the same `{pane}` if a second call ever needed it. A stage that fails is a
reason string and no run: the fallback dialog hands the prompt over, exactly as when no
terminal exists, because a workspace that could not be created is not a shell somebody
is in. The wrapper script records each multiplexer's own name for the pane from the
variables it sets (`HERDR_WORKSPACE_ID`, `HERDR_TAB_ID`, `WEZTERM_PANE`, beside tmux's
`TMUX_PANE`), so *Show Agent Terminal* selects the pane through the multiplexer before
it asks the desktop for a window — `terminal.focus_reason`'s per-run rule, extended.

herdr, zellij and tmux sit last in every platform's list, marked `multiplexer`: Automatic
still opens a window, and a multiplexer is what a profile picks on purpose.

### What a run consumed is a ledger on the step

Which step cost how many tokens is the question a project's owner asks at the end of a
week, and nothing recorded it. The run tracker already knows the moment a shell ends and
which agent ran in it, so it asks the harness's `report` there and writes a row to the
step's `agent_usage` aspect — the second aspect id in `step_agent_run/`, beside the run
*state* that is cleared at exit: two different claims, and only this one outlives the
shell. The write goes directly, off the undo stack, with an origin of its own — the exit's
rule, for the exit's reason: the tokens were spent whether or not anybody presses Ctrl+Z.

**Rows, never a total.** A step is run more than once — a retry, a second agent picking
up after the first — and a stored total would hide which run cost what and disagree with
its rows the first time one was corrected. So the aspect holds one row per run (harness,
session, input, output, the vendor's own finer split under `details`, when), a row is
keyed by session so a record read twice is one row, and `usage.totals` sums on read.
`dplanner usage show` prints the rows, `usage list` a project's steps by cost, and
`usage record` writes a row for a run the window never saw — through the same harness
readers, or by hand with `--input`/`--output` for a CLI nothing here can read.

**One meaning of input and output.** Anthropic bills cache reads, cache writes and
uncached input at three prices and reports all three; OpenAI counts cached tokens as a
subset of input; OpenCode keeps reasoning apart from output. A ledger that copied each
vendor's shape could not be added across a step that ran under two of them. So `input`
is everything sent to the model and `output` everything it generated, whatever the CLI,
and the vendor's split rides along under `details` in the vendor's words — the sum is
honest and the breakdown is still there for whoever wants the price.

## Two repositories, two questions

A project answers two questions about repositories, and for a year the code let one
answer serve both. *Where does the plan live?* was the git repository enclosing the
project directory — derived, never stored, and still is. *Which code does it plan?* was
assumed to be the same repository, and that assumption is what field testing kept
reporting as "main drifting": *Save* committed plan files to the code repository's
`main`, every agent worktree carried a copy of the plan, and a `git checkout` in the code
repository swapped the plan under the window. A plan and the code it plans have different
rhythms — the plan changes on every `dplanner status set`, the code on every merge — and
one branch cannot carry both without each getting in the other's way.

So the second question became a stored fact. `Project.repository` is the **code
repository**, the remote URL as git prints it, in `project.dproj` where everyone who opens
the plan sees it; a repository with no remote is stored as its resolved path — the only
identity a repository that cannot be shared has. The **plan repository** stays derived:
`find_repo_root(project directory)`, exactly as before, so the plan's history is still the
repository's history and nothing stored can disagree with git. A third question — *where is
that code on this machine?* — is per user, per machine, and goes to the library file's
`checkout` column (`FORMAT.md`), written straight into the file rather than through the
flush, because the first `dplanner` call from a checkout records it and a read verb's
transaction must never be refused over a per-machine fact. `domain/repositories.py` is the
one derivation over the three — `RepositoryFacts`, with three states: **separated**, the
shape the application wants; **colocated**, the same remote or either checkout inside the
other; and **legacy**, no code repository recorded, read as colocated so nothing breaks on
the day the build updates. *Warns* is one predicate — not separated and not accepted —
asked by lint (`repo.unset`, `repo.colocated`, exit 1), by the briefing's preamble
(WARNING: leave the plan files alone), by the Project dialog and the Repositories card,
and by the opening status line; `colocation: "accepted"` silences all of them at once,
because it is the people on the project saying the shape is on purpose.

The readers are seams the composition root wires. The agent module is handed
`facts_for(step)` and decides *where an agent works*: the code checkout for a project
that records its code, the plan's own repository for one that does not, greyed with the
reason ("not checked out on this machine — Project ▸ Settings…") until a checkout is
recorded — and `store.checkout_changed` refreshes the context, since nothing in the
context graph changed. A conflict handed to an agent is about plan files and opens in the
plan repository whatever the code is. The github module's `repository_for` is the code
repository, the plan's origin only for the older shape. `dplanner project show`, `agent
prompt --json` and the Repositories card print the same facts. Discovery (`cli/discovery.py`)
gained one rule: a `dplanner` call from a checkout — or a worktree of it — whose `origin`
is a project's code repository finds that project, spelt however git spells it
(`canonical_remote`), so an agent in the code needs no configuration; the wrapper script
also exports `DPLANNER_PROJECT`, so nothing is even looked up.

### The Project dialog is two columns, not three fields

(`DESIGN.md`'s *Facts under the thing they are about* and the `⋯` rule under *Buttons* are
the standard this settled.)

The dialog stated three things above its logs: the plan repository, the code repository,
and the code's checkout. Nobody could say why there were three, and the reason is that the
code was allowed two facts — *which code* (shared, in `project.dproj`) and *where it is
here* (per machine, in the library file) — while the plan was allowed one. The count was
an artefact of which facts happened to be stored, not of what a reader is asking, and the
two log columns underneath were already saying the true thing: there are **two**
repositories.

So the facts moved under the columns they belong to. Each column now answers the same two
questions — `repos.code_lines` and `repos.plan_lines`, one derivation with two readers, so
the dialog and the Repositories card cannot word the same fact differently — printed small
under the well, with the vertical rule between them doing the work of saying which is
which. A line with nothing to name says what is missing (*not checked out on this
machine*) rather than standing blank, and `#RepoLineMissing` is what greys it: the shape
of the footer is then constant, and a reader learns where to look once.

What used to be four glyph buttons scattered across three rows is one ⋯ per column
(`RepoAction`, `RepositoryColumn.entries`). The menu is **built when it opens** — the same
reason `action_menu` builds one fresh: a glyph carries the colour it was painted in — and
an entry that cannot run right now is **greyed with its reason in its words**, never
dropped, so the list to learn is the same list whatever the project's state. These verbs
are dialog-local rather than registered actions, which is why `RepoAction` restates the
presenter policy in four lines instead of reaching for `append_action`; if a second
surface ever needs one, that is the moment it becomes a spec. *Move Plan…* is the
exception that proves it — it has a spec, and the dialog reaches it through the `move`
callback the module hands in, which is the very function `projects.move` runs, so the
menu and the card cannot mean different things by it.

Create mode keeps its form: with nothing on disk yet there is no log to read and no verb
to run, so the fields *are* the answer.

**A plan repository holds several projects for several people.** Its root carries the
`.dplanner` index (`FORMAT.md`), which is what lets *Open Projects…* and `dplanner library
browse` list what a clone holds, with who worked on each and when (`activity`, one git log
per project). It may be local-only — `git init` from New Project or Move Plan — or on
GitHub, published from the same dialogs through `gh`; clones land in one *repositories
folder*, asked for once from the likely candidates on disk and kept per user.

**Moving a plan is a storage operation that rewrites the working tree**, and so is
synchronous (below): `domain/relocate.move_project` copies the plan entries, rewrites the
meta with the code repository it left, maintains both indexes, removes the source,
re-points the store and commits on both sides, best-effort; the window pauses autosave
around it and reloads after, because every view that cached a directory is rebuilt rather
than patched. It is the one place colocation is *refused* rather than warned about: moving
a plan into its own code repository is the shape the move exists to end.

**Move Plan is offered on every project, because picking a plan repository is a choice
that can be got wrong.** It stood down once the plan was apart from its code — the verb
read as a one-time migration — and the first plan put on the wrong repository had no way
back but the CLI, which is the wrong answer for a mistake made in a dialog: the surface
that made a choice is the surface that has to be able to change it. Nothing in the move
was a special case of the first one; the only thing the second move must not do is
*inherit*. `move_project` used to fall back to the source repository's main checkout when
no checkout was recorded — true when the plan was leaving the code, and wrong the moment
the repository it leaves is a plan repository — so the fallback now asks
`_is_code_repository` first and a plan with no checkout here gains none by moving. The
card's button says which of the two offers this is (*Set up a plan repository…* while the
plan is inside its code, *Move Plan…* once it is out), and the skill still tells an agent
to run `dplanner project move` when the developer asks and never unasked.

The git requirement is **gating at membership, honest afterwards**: New Project initialises
or picks a plan repository, Open Projects lists only what is inside one (the plan's history
*is* the repository's history), but a project whose repository breaks later degrades to
disabled verbs, not a broken library.

## Save spans repositories; the exit dialog says what it records

One library can hold projects in several repositories, so *Save* (record a version) means:
**one commit per dirty repository, covering exactly that repository's project
directories**. The store owns the grouping (`LibraryStore.repo_groups()` — one provider
per distinct repo root, its git operations scoped to the member projects' paths), which is
what keeps two truths at once: several projects in one repo save as one commit, and a Save
can never sweep up the user's source code sitting beside the plan. Branch operations are
different — a branch belongs to one repository — so New/Switch Branch act on the focused
project's repo and are disabled, with the reason in the label, until a project is focused.

Quitting with uncommitted planning changes asks once, honestly: a dialog listing each dirty
repository (checked by default, with its file count and project titles) over one optional
commit message. *Commit & Quit* records the checked rows synchronously — the documented
save-at-quit exception to TaskRunner — and *Quit Without Committing* is a real choice, not
a scare: autosave already put the files on disk, so nothing is lost either way; only the
version history goes unrecorded until next time.

## Progression is the status-aware frontier

`ordering.ready()` answers what the *graph* allows — wave one, nothing waited on. During
execution that is the wrong question: a step deep in the graph whose prerequisites have all
been finished is launchable today, and no wave number says so. `domain/progression.py`
answers the execution question — every step in exactly one of *done / running / attention /
ready / upcoming / waiting* — and it is deliberately a **new derivation beside the old one,
not a refactor of it**: the frontier is a per-step check ("every `requires` target reads
done"), not wave membership, and the two only coincide in a project where nothing has been
finished yet. A test pins that equivalence; shared code would have pinned a coincidence.

The rules worth writing down, because each was a decision:

- **A stored claim beats the graph.** A step marked done whose prerequisites are not is
  honoured as done, and its dependents may become ready through it. The graph gates
  *launching*, not *recording* — an agent reporting `status set … done` out of order is
  reporting a fact, and a derivation that refused it would be arguing with reality.
- **Blocked is attention, not waiting.** A blocked step is stuck on a person, so it leads
  the running column wearing a warning rather than disappearing into the waited-on mass —
  it is the row that needs eyes, and the board exists to route eyes.
- **A blocked prerequisite still counts as "on the board"** for the one-move lookahead:
  its dependents stay in *upcoming*, pointing at it. The alternative — demoting them to
  waiting — would make the queue churn every time a prerequisite flips between in-progress
  and blocked, and would hide exactly the lane that stalled.
- **The lookahead is one move, not a forecast.** A step whose prerequisite is merely
  *upcoming* stays in waiting. Anything deeper is the order table's job.
- **The frontier ranks by unlocks** — the count of transitive not-done dependents — because
  all of the frontier is valid and the ranking is what makes some of it urgent. A done
  dependent is walked through but not counted: its own dependents still wait through it.

The seam is the one the schedule made: `status_for(step)` and `days_for(step)` are handed
in by the composition root from the aspects' Qt-free readers, so the domain never learns
what either is stored as, and the derivation is tested with a dict-backed function. Nothing
is persisted, for the ordering's reason — `dplanner status set` changes the answer with no
window running to notice. The tab (`modules/progression/`), `dplanner progression show` and
`--json` are three readers of the one function, so no surface can recommend a launch
another surface would dispute. The Run Agent button on a ready card is the same rule at the
module layer: it renders the real `agent.run` action's state — evaluated against a context
synthesised for exactly that card's step — so the gate's reason appears verbatim and no
second copy of "what launching needs" exists.

## Time estimates: two worker pools, one greedy simulation

`schedule()` and `critical_path()` print the honest brackets — one worker, unlimited
workers. The time estimates tab and `dplanner schedule matrix` answer what lands between
them: `domain/schedule.py`'s `parallel_finish` simulates the graph under a stated cap of
*humans* and *coding agents*, and a small grid of those simulations is the report. The
decisions worth writing down:

- **Two pools, pure.** An agent step waits for an agent slot, every other step for a human
  one, and neither pool takes the other's work — even an idle human never picks up an agent
  step. That is a modelling choice, not a scheduling inevitability: mixing pools would need
  a claim about who *may* do what that the model does not carry, and the clean partition is
  what makes the matrix's axes mean something. Which steps are agent work arrives as a
  predicate (`is_agent`), the same seam as `days_for` — the domain learns "two kinds of
  workers", never what marks a step.
- **Greedy list scheduling, not an optimum.** A free slot takes the ready step with the
  longest remaining `requires` chain, ties by project step order. Deterministic, honest
  ("the team picks the longest pole first"), and pinned at both ends: with ample workers it
  meets the critical path exactly, with one human on all-human work it meets the serial
  total. An ILP would be tighter in contrived graphs and impossible to explain in a cell.
- **Calendar time is the same walk over stretched estimates.** The focus factor — how much
  of a person's working day this project actually gets — divides human steps' days via a
  wrapped `days_for` (`time_estimates/schedule.py`'s `stretched`), so the domain never
  learns an efficiency exists. Agent steps are not stretched: their human-in-the-loop cost
  is already inside the quarter-day estimate convention, and the factor prices the person's
  divided week, not the agent's.
- **The factor is the only thing stored; the matrix never is.** Twelve cells are recomputed
  on every change for the ordering's reason — `dplanner estimate set` changes the answer
  with no window running to notice. The factor is an assumption a person chose, so it
  persists like the start date does: project-node module data, written through one command
  (the tab's spinbox and `dplanner schedule focus` push the same write).
- **The grid is a heatmap: more time is more ink.** Tiles carry one constant low-alpha
  hue scaled by the makespan (the diff tint's trick, so it reads on every theme), which
  makes the dependency floor visible as the flat, lightest region — "more capacity
  changes nothing" needs no legend. The printed number is the dependable channel; the
  tint only orients. The two units are a lens toggle over one grid, never two tables.
- **Milestones run in sequence, and a stretch is a cone.** A plan with milestones is not
  one simulation but one per milestone: its stretch is `scope.cone` truncated at the
  milestones before it — what is new since the last one — plus itself, and a step two
  milestones both reach belongs to the earlier. Each stretch is `parallel_finish` over its
  own steps (the `among` parameter; an edge out of the subset counts as met, because the
  sequence already put that work before), beginning the working day after the previous
  lands. Work no milestone gathers runs last, with no milestone; a project with none is
  that one stretch, which is the plain simulation it always was. The alternative — one
  simulation over the whole graph with per-milestone release dates — was rejected because
  it lets a later milestone's independent work run *during* an earlier one whenever a slot
  is free, which is what a team can do but not what "milestones in sequence" says, and it
  makes the calendar impossible to read as bands.
- **A milestone's own date is an assumption, so it is stored — and it is a floor, not a
  fact.** `schedule milestone --start` says when a stretch *begins*, not when it lands
  (the aspect that names a milestone is explicit that a landing date is the schedule's to
  answer, never stored). A date later than the previous landing opens a gap, which the
  calendar shows as one; a date earlier than it is **pushed** to the sequence's own day
  and reported (`Phase.pushed`, the ⚠ in the landing list, the sentence in the CLI) rather
  than honoured by overlapping — overlap would make the sequence a lie one milestone at a
  time. The first milestone is the exception: nothing lands before it, so its date wins
  over the project's start, which is only the default. Both writes — the date and the
  colour — live under this module's id on the *milestone's* step, `estimation`'s
  project-plus-step precedent; `FORMAT.md` has the shape.
- **Colour is a place on one map, unless somebody chose.** The first cut dealt eight
  distinct hues in order, and the first real project showed why that reads as chaos: a
  roadmap is a *sequence*, and eight unrelated hues say nothing about order. So the
  project picks a **colour map** — the legible interior of a published perceptual map
  (viridis, mako, rocket, …; `schedule.py`'s `PALETTES`), stored under the module's id
  on the project node beside the focus factor, absent for the default — and `shades`
  deals the milestones evenly along it, centred, so two milestones sit a quarter and
  three quarters in and eight fill it. Dealing by count means adding a milestone
  re-shades the others; that is accepted, because the shade's meaning is *place in the
  sequence*, which is exactly what changed. An override still pins one milestone without
  renumbering the rest, and the swatch's menu offers the map's own shades first so an
  override usually stays in the family. A project without milestones is one stretch in
  the report's own blue (`WHOLE_COLOR`), as it always was. The calendar and the list
  share the hex through `schedule.py` and never store a `QColor`, for the
  palette-snapshot reason in *The palette a painter is handed is a snapshot*.
- **And the map is the project's, which is what let the shade leave this tab.** For a
  while the shades lived only here: the calendar said *this is milestone 2 of 4* and the
  graph beside it said only *this is a milestone*, in the one violet every milestone wore.
  Joining them needed an answer to "what colour is this milestone" that any surface could
  ask, so `milestone_colors(library, project, is_milestone)` is the deal — `placed`'s
  sequence, an override over a dealt shade — and `phase_colors` is a lookup into it rather
  than a second deal beside it. The maps moved to `theme/palettes.py`, Qt-free and a leaf,
  because the appearance module lists them and modules never import each other; the
  composition root walks each project once and hands every consumer a typed callback, the
  `_milestone_stats` shape. `theme/tones.py`'s `toned(name, hex)` recolours a tone at its
  own alphas, so ten painters never re-derive one and a recoloured card is exactly as loud
  as the purple it replaced.

  **The choice stayed the project's rather than becoming the user's, and that decided the
  menu.** A per-user map was the obvious reading of "pick it in the theme menu", and it is
  wrong twice: Save publishes `reports/` into the plan repository, so two developers would
  churn the committed report's colours between them; and the Time tab's picker names the
  project's map, so a window painting a user's override would have a control that lied
  about what it was showing. So *View ▸ Milestone Colours* writes the same stored entry
  `dplanner schedule palette` and that picker write, through the same undoable command —
  one choice, three ways in, the *Two surfaces, one vocabulary* rule applied to a third.
  It sits **beside** Theme rather than inside it, because it is not a theme and an entry
  nested under one would read as a theme; and being a project fact in a window menu, it is
  greyed with its reason when no project is open rather than hidden. The tick follows a
  map changed from a terminal, from the Time tab or by an undo, because the module
  subscribes to `module_data_changed` for that one id — a state callback must never read a
  file (*The context is announced once per turn*).
- **The page is split at a seam, and the calendar takes the width.** What you set on the
  left — focus, the staffing picker — and what it answers on the right — the colour map
  and the month arrows on one strip, the calendar, then the milestones. The seam starts
  off-centre: the left holds nothing wider than the staffing grid, so the calendar gets
  the rest. The milestones were once two lists, the settable
  one on the left and the landing one on the right, painted alike so a reader could cross
  between them; the first real project showed nobody wants to cross. **One list now, one
  row per stretch, the date you set and the date it lands on the same line** — the one
  place on the page where a control sits on the answering side, and worth the exception
  because the answer is what you set the date *against*. The months view is the one
  drawing on the page that is not fixed-size: months across follow the width, cells grow
  with it, the last row fills out. Picking a milestone in the list emphasises its stretch
  in the calendar and fades the rest, which is how "the work leading up to it" is shown
  without a word. There is no headline and no explainer: the list's last row *is* the
  answer, and every number's meaning is in a tooltip.
- **A plan that cannot be dated says so.** The model refuses to create a cycle, but every
  walk here guards against one a hand-edited file carries — and until now guarded
  *silently*, placing the looped steps at depth zero and dating a plan that has no order.
  `ordering.cyclic()` names them (Kahn's peeling: whatever cannot be shed sits on or behind
  a loop), `time_report` returns a report with `cycle` set and empty grids, the tab shows
  the names in place of the calendar, and `schedule matrix` exits non-zero with them.
  A view that computes on every change has to be robust to every state the file can be
  in, or it is a view that sometimes shows a picture of nothing.
- **The team is an assumption, so it is stored — and a tile click is the write.** The
  matrix's selection used to be view state that reset on every open, which meant the
  calendar, the landing list and `schedule matrix` could each be dating the plan for a
  different team. It is the project's now — `{"team": [2, 3]}` beside the focus factor
  and the palette, one `Assumptions` record read and written whole so no control has to
  juggle the other two — pushed by the tile click as *Choose Team* and by `dplanner
  schedule team`, restored when the tab reopens, and the team every stretch, every row's
  percentage and every recorded day are computed for. When the agent columns collapse
  (no agent steps), a stored team the grid cannot show selects the nearest seat it can,
  and a sync is never a click.

### Progress against the plan: the promise is derived, the past is recorded

The calendar says when each milestone lands; a person working the plan wants the other
half — how far it has come, and whether it is on the curve it promised. The plots under
the calendar answer with the shape a trip planner's energy graph has: the plan's curve,
what actually landed, and the plan as it stood on the day you compare against. The
decisions that carry it:

- **One measure: estimated days.** The days of done steps over the days of all of them,
  `time_estimates/progress.py` over `status_for` — the status aspect's reader handed in
  like `days_for`, so this module never learns where a status lives — and "toward a
  milestone" is **cumulative through its stretch**, because a milestone lands when
  everything before it has, not only what is new since the last one. A share by count
  of steps was offered beside it for a while, as a toggle; it was dropped because
  nobody reading the plots wants it and it calls a two-hour step and a two-week one the
  same thing, which is the one comparison a plan priced in days must not make. The
  count is still tallied and printed in words (*2d of 7d estimated · 1 of 4 steps
  done*), never offered as the share.
- **The expected curve is the simulation's own.** A straight line from start to landing
  would be a guess wearing the plan's colour. `parallel_finish` already knows the
  working day each step lands on; it now says so (`ParallelFinish.landings`, carried on
  each `Phase`), and the curve is the cumulative share landed by date — exact for the
  stored team and focus, and free, because the simulation ran anyway.
- **The past is recorded, because it is the one thing that cannot be derived.** What the
  plan looked like last Tuesday — how many steps, how much done, when it said it would
  land — is gone the moment the plan changes, and a chart of expected against actual is
  nothing without it. So a snapshot is written: one row per day, the stretches in
  sequence with their tallies, starts and landings, under a module id of its own
  (`progress_history`) so the assumptions file stays byte-stable. Three rules keep it
  from being the stored-answer mistake `ordering.py` warns about. It is written **only
  on a day something in it changed** — a window open on an untouched plan writes
  nothing — and last-wins within the day. It is written **directly, with its own
  origin, never onto the undo stack** (`recorder.py`; the PR refresher's rule): a record
  of what the plan looked like is not a user decision, and Ctrl+Z after marking a step
  done must undo the status, after which the next settle simply re-records the day.
  And it is written by whoever is there: the window's recorder after every settled
  change to any project, `dplanner progress record` for a plan driven from the
  terminal — the skill says when. Each row also carries the stretch's **landing knots**
  — what the simulation landed on each date — so the plan as it stood on any recorded
  day is drawn *exactly*, never reconstructed from what the graph looks like now.
- **One baseline, and the delta is the band between it and the plan now.** The first
  cut drew every earlier promise as its own dashed segment; the walk that redesigned it
  wanted one question answered clearly: *how has the plan moved since we started?* So
  there is one **baseline** — the plan as recorded on the **basis** day, the project's
  start unless another plan is picked in the strip (`progress show --basis`) — chosen as
  the last row on or before the basis, or the earliest row for a project older than its
  history. That fallback stops at **today's own record**: a project whose history begins
  today has no earlier plan, and standing today's record in for one drew the plan now
  over itself and called the pair a comparison — two lines in one place under a heading
  saying *scope change*, which is a claim nobody recorded. `baseline()` takes `today` and
  all three surfaces pass it, so the window, the report and `progress show` agree on when
  there is nothing to compare with. The baseline is painted *last*, in a paler shade
  mixed opaque: a plan unchanged since the basis has a baseline that coincides with it,
  and a translucent dash of the same hue under the solid line was invisible — the first
  cut showed one line under a caption saying *unchanged*, and the reader took the other
  for a line that had failed to draw. Dashes riding on the solid line say *two lines in
  the same place*, which is the fact. A span the plan leaves empty (a milestone's own
  start date holding its work back past the previous landing) is dotted and pulled toward
  the surface, with a knot in the expected line at the day work resumes so the gap is flat
  rather than a slope through days nothing is planned for; `progress.idle` derives it
  from the snapshot's stretches, so `progress show` prints the same gaps. The change
  list behind the delta needed a fact nobody kept: **an estimate now remembers what it
  was** — every write of the aspect carries the value it replaced with the day, one row
  per day (the value that stood when the day began), format 2 so an older build refuses
  to rewrite rather than drop it; `dplanner estimate show` prints it, the Estimate
  block's field wears it as a tooltip. Both the delta and the change list are measured
  **from the baseline's recorded day**, not from the basis: the record is what the
  delta compares against, so what the list names is what moved it, and a change on the
  record's own day is inside that day's record (last-wins). The basis is a way of
  looking — view state, never stored.
- **The scope plot fills the area between the two plans, by direction.** Drawing both
  curves and washing the space between them in one hue said *something moved* and left
  the reader to work out which way. The fill now carries the answer: where the plan now
  runs **above** the plan at the basis day it promises the same work sooner — pulled in —
  and the area wears the attention amber; **below** it, work has slipped, and the area
  wears the bad red; where the two agree there is no area to fill at all, so that run is
  drawn as a line in the good green, which is also the only way "unchanged" can be a
  visible state on an area chart. Muted throughout (a region tint, DESIGN.md's exception
  #2) because the two curves are still what a reader measures against. The runs come from
  `domain/schedule.py`'s `change_runs`, which samples the two lines together and closes a
  run **at the day they cross** rather than at the next knot — so the colour changes
  exactly where the plan did — and both surfaces read it, because an area that changed
  colour a day apart on screen and on paper would be two answers to one question.
- **Three plots on one locked axis, not three lines on one plot.** The baseline, the
  plan now and what actually landed shared a plot for a while, and a reader had to
  untangle three curves and a legend to answer any one question. Each question now
  has a plot of its own, stacked (`chart.py`): *Progress* — the plan now against what
  landed, with *ahead 5 %* or *behind 12 %* in words beside today's dot, because the
  gap between two curves is the thing a reader was estimating by eye; *Scope change* —
  the baseline against the plan now, with the band between them; *Milestones* — a row
  per milestone, its landing then hollow, its landing now filled, an arrow between
  them saying which way it went, because a landing that moved was the hardest thing to
  read off the 100 % line. What makes three plots one chart is the **axis**: the same
  dates run under all three, the marks (`axis_ticks`: every day, every Monday or every
  month's first, the finest whose labels fit the width — a reader places a point by the
  nearest mark, and two labels at the ends of a span were not a scale) drop as
  hairlines through every plot, the labels are printed once under the last, and the
  edges are the earliest and latest date any of the three has to show — so a point
  placed in one plot is placed in all of them. The plan line runs in each stretch's
  shade, the calendar's colours on the curve, and **picking a milestone highlights, it
  never hides**: the whole project stays on every plot and everything outside the
  picked stretch fades to a third, which is what the calendar already did with its
  bands. Scoping the plots to the pick was tried first and lost the comparison the
  reader came for — where this milestone sits in the plan it is part of. The delta in
  words and the list of what moved it left the screen with that redesign: the plots say
  it, the rows say the percentages, and the sentence is the terminal's and the
  report's (`delta_words`, `changes_since`). **The report draws the same three plots**,
  from the same data: `cli/report/parts.py`'s `Chart` carries `Plot`s and the `Stretch`es
  all three read, `drawings.py` stacks them in one SVG, and what the two surfaces must
  agree on lives below both — `share_at` and `change_runs` in `domain/schedule.py`,
  `standing_words` and `shift_words` in `progress.py`. The renderer *slices* the plan
  polyline per stretch instead of clipping it: `clipPath` is not something QtSvg honours,
  and the PDF is rendered through it. The same pass moved the milestone list
  under the staffing grid with a **Start dates** table above it — the project's own
  start and each milestone's *Begin…* are what you set, and they now sit on the side of
  the seam that holds what you set — put the focus factor, the lens, the palette and
  Export in one control strip over the page, and gave the answer a banner: *n steps
  unestimated · counted as 0d*, with *Estimate missing* opening the Estimates tab on
  exactly those rows through a callback on the module's Deps, so the Time tab never
  names the estimation module.
- **The milestones are one list, not a table of names above a list of the same names.**
  *Start dates* and *Milestones* listed the same stretches one under the other: a reader
  had to match a name in the first against a name in the second, and the panel spent
  twice its height saying it. One row now carries the cause and the effect — *begins
  21 Jun · lands 3 Aug* — with the step's own title beside the label, so the list says
  which step each milestone is without a second column of names. The row that leads the
  list is the whole plan, and what *it* begins on is the project's own start (a row
  declares that with `MilestoneEntry.sets_project` rather than the list inferring it from
  the position). Under an undated row the caption says the day the sequence gives it, so
  every row says when its work runs and not only when it ends. **The list scrolls under
  the staffing grid**, which stays: the grid is the question the whole page answers, and
  a plan with thirty milestones would scroll it away exactly when the answers are being
  compared. That is why the left half is no longer a scroll area of its own — it is a
  pinned head and a scrolling list, and only the answer side scrolls whole.
- **A comparison is two snapshots, and both are picked where the reader can see them.**
  The first cut compared "the plan at the basis day" with "now", the basis a date field
  under the plots, and the day the record was actually taken on reported only by the
  terminal. Users read the plots without knowing what they were comparing: the concept
  of a snapshot was in the file and nowhere on the screen. So the strip now carries
  *Compare [then] with [now]* — two `SnapshotPicker`s (`snapshots.py`), each a button
  wearing the name of the plan it reads and dropping a menu built when it opens: the
  side's own default (the plan at the project's start; the live plan now), every
  snapshot somebody saved, and *Day…* for any recorded day. The choice is a `Pick`
  (`progress.py`), view state like the picked milestone, and `resolve` finds the record
  that stands for it: the start and a day through the baseline rule — the last record
  on or before the day, else the earliest, but **never today's own record** standing in
  for an earlier day, which would draw the plan over itself and call it a comparison —
  a saved snapshot by title, the live plan for *Now*. Two sides rather than one because
  the question at a review is as often *what did we think on 1 November against what we
  thought on 1 December* as *against now*, and read as of an earlier snapshot the
  curves stop at its day (`progress.until`). Three was considered and left: two answers
  every question anybody asked, and a third picker is a third thing to explain.
- **Every heading names the plan it is compared with — the record included.** The
  earlier rule named the day the reader asked for and hid which record stood in for it,
  because a control saying *1 June* under a heading saying *7 September* read as a
  contradiction. With the pick explicit that reasoning inverts: the pick *is* the thing
  compared, and hiding the record made the comparison untrustworthy. `pick_words`
  words a pick once — *the plan at start, recorded 9 September*, *Kickoff review
  (1 November)*, *the plan at 3 September* when a record fell on that very day, *now* —
  and the picker's tooltip, the scope plot's heading (`scope_words`), every milestone
  row's sentence (`shift_words`, *3 working days later than Kickoff review said*), the
  report and `progress show` all read that one sentence. A saved snapshot's day is a
  hairline through every plot with its title at the top, so the moments somebody chose
  to remember are on the axis every plot shares.
- **Saved snapshots are a second list, kept whole; automatic days stay last-wins.** A
  snapshot a person saves — *"What we thought on 1 November"*, with a note on the
  occasion — is a record of a decision, and it must mean the plan *at that moment*:
  riding it on the day's automatic row would let an afternoon's ten new steps rewrite
  what the morning's review had looked at. So `progress_history.json` (format 2) holds
  `days`, the automatic rows the recorder replaces within a day, and `saved`, rows with
  a `title` that nothing replaces and nothing expires; `saved_with` refuses a title
  already taken because a saved snapshot is found by its name. The save is a user
  decision, so it goes **through the undo stack** (*Save Snapshot*, *Forget Snapshot*;
  `dplanner progress save|list|remove`), unlike the recorder's automatic write; and
  every write of the entry — the recorder's included — carries the saved list along as
  stored, so a settle never loses one. The format bump exists for the `saved` key: an
  older build refuses to rewrite the entry rather than dropping what somebody saved.
- **A snapshot records the plan as simulated that day, not the graph.** The tempting
  alternative — store the graph and the estimates, re-simulate every old snapshot under
  whatever team the reader picks now — was weighed and left: it makes every snapshot a
  copy of the project, and the comparison it enables ("what would last month's plan
  have said with two more agents") is not the one the plots exist for. What a snapshot
  keeps is what the plan *promised* that day, for the team and focus of that day, and
  that is what a comparison against it must hold still. The volume plots are the part
  of a snapshot the team never touches — a total of estimated days is the same under
  any staffing — which is why they can be read across every snapshot without a
  re-simulation.
- **Volume is derived from the snapshots, so it costs the file nothing.** The scope
  over time — how much work the plan came to on each recorded day, and how much of it
  was still ahead — is the one question the progress and scope plots cannot answer,
  because both draw shares: a plan that doubled overnight and landed half of it reads as
  *50 %* on both days. Every automatic row already carries each stretch's tally, so
  `progress.volume` and `remaining` read the total and the total less the done days
  off the rows through *now* as **step curves** (a record is what the plan was until the
  next one; a slope between two records would claim a change on days nothing was
  recorded). The two plots share **one scale in days** (`volume_scale`, the largest value
  either reaches rounded up to 1, 2 or 5 times a power of ten, in the window and the
  report alike), so the gap between the total and the remaining is read by eye as what
  has landed; the remaining plot draws the total under it in a paler dash for the same
  reason the scope plot draws the plan then over the plan now.
- **The plots are read a page at a time, and the window of their own shows every page.**
  Five plots stacked under a calendar outran any screen, and the two that answer one
  question were rarely the two on it. `chart.py`'s `PAGES` — *Milestone shifts*,
  *Progress* (the plan against what landed, and the scope change), *Volume* — are three
  pages of one widget over one `ChartData`, toggled by the row over the plots where the
  measure toggle used to be, and the page decides the plots and the height while the
  data is one record whichever page is up. Progress is what the tab opens on, because
  it is where a reader almost always is; a milestone plot with nothing to row says *No
  milestones yet* in one row's height rather than leaving the page. `ChartDialog` is
  the same widget on the `all` page: where the tab has to choose, a window of its own
  has the room, and a reader comparing pages wants them under each other.
- **A change re-runs the page after a quiet spell, and the strip says so meanwhile.**
  The refresh is the heaviest reaction in the application — two dozen simulations, the
  matrix, the calendar, the list and every plot — and it was already coalesced
  (`REFRESH_DELAY_MS`, *A view refresh is coalesced*). What it lacked was a word: for
  half a second after an edit the page showed a plan that had since changed, with
  nothing to say it was stale. *Recalculating…* in the strip appears when a change
  arrives and leaves when the report has re-run. Moving the derivation to a worker
  thread was considered and rejected for the reason that section gives — pure Python
  competing for the GIL, and a thread alive at teardown is the suite's SIGSEGV shape —
  so the answer to "the recalculation must not lag the UI" stays the debounce, and the
  answer to "the user must see it is recalculating" is one label.
- **A plot is given the room the window has, up to a ceiling.** The two share plots were
  a fixed 112 px whatever the screen, so a tall window ran out of page and a laptop
  ran out of plot. They now take whatever height the host gives the chart over its
  minimum, in equal parts, and stop at twice their floor: past that a line stretches
  into a wall and says no more than it did. The milestone rows never grow — a row is a
  row. The bound is set from the *data* (`_bound_height`), never from a resize, because
  a widget that resizes itself inside its own resize event is what put a scroll area
  into the loop `months.py` documents. And a plot's name is set **bold** with air above
  it, so the three read as three headings rather than as captions under the plot above.
- **Expanding the plots is the same widget with more room.** *⤢* beside the page toggles
  opens `ChartDialog` — a second `ProgressChart` fed the same `ChartData` the tab feeds
  the inline one, so a plan that changes while the window is open redraws in both and
  there is no second rendering to drift. It holds no state, so closing it loses nothing: the
  text dialog's rule (*expanding an editor is a second binding, not a copy*) applied to
  a view that has nothing to bind.
- **A milestone row dates both its marks and drops a line to the axis.** The axis marks
  weeks or months, and the shift a row draws is often days: the size a reader wants is in
  figures, so each mark carries its own date — the landing now on the far side of the
  pair, the plan then's on its own, outside them where there is room and inside where
  there is not, and left out rather than squeezed (`row_dates`, the landing names' rule
  applied to a row). A hairline falls from the landing to the axis, so the day it lands
  can be read off the scale under the plot rather than estimated by eye. Both surfaces
  draw them: `drawings.py`'s shift plot does the same, with the report's own
  character-width estimate standing in for font metrics.
- **Every milestone landing is marked and named on the progress line.** The plan line
  already changes shade at each landing; what it could not say was *which* milestone
  that was, and a reader had to count rows in the plot below to find out. Each landing
  now carries a mark in its stretch's shade with the milestone's name in secondary ink
  a gap to its left, above the line where a rising curve leaves the room. A name is
  elided past 90 px and **dropped** when the name before it reaches that far: two names
  squeezed together say less than one, and the milestone plot below names every one of
  them anyway. Only the first plot carries them — the milestone plot's rows are its
  subject, and a name beside every mark there would be the row header said twice.

## A test belongs to a step, and a step carries several

A description says what a step *is*. An acceptance criterion says what would make it
finished — and is then consumed, because the step closes. A **test** is the third thing: it
says how you would prove the step works, and it *outlives* the step. That is the whole
reason it is an aspect of its own rather than a paragraph in the description, and the reason
the tab's note is the first thing a reader sees: *"How you would know this step works — kept
after the work is done."*

**A test is not a node.** It belongs to exactly one step, never appears on the canvas, and
the graph knows nothing about it. A step carries several, each with its own id, title,
markdown body and — the point of the whole feature — its own result in a run. Making tests
nodes would have been cheaper in code and wrong in the model: forty work steps with three
tests each is a hundred and sixty nodes in a graph that is meant to show *the plan*.

**The body is a markdown string inside the record, not a `.md` file.** `FORMAT.md` gives a
node exactly one prose document, and a step carries N tests, so the one-document rule does
not stretch to them; the nearest existing shape is `spec`'s requirement records, and this
follows it. The trade is real and worth stating: a body edit diffs as one changed JSON line
rather than line by line. Test bodies are a few lines, so the whole new body is legible in
the diff — and if that ever stops being true, storing the body as an array of lines is a
format-2 migration away. Images are the exception and go where a description's images go:
the step's file area, referenced as `![](assets/…)`.

**Ids are minted per project, not per step, and are meant to be read.** `T100, T101, …`
across the whole project (runs are `R100, R101, …`, so the two never look like one
vocabulary spelled two ways). Three digits from the start, so every id in a project is the
same width and nobody mistakes one for a count. That is what lets a run's results be a flat
map, lets a person say "T107 failed" out loud, and lets `dplanner test-run mark T107 failed`
name a test without naming its step. Renaming a test therefore never detaches its history,
which keying on the title would have done.

**The editor is master-detail, and the split follows the width.** A stack of equal cards
was the first attempt and it stops working at the third test: every body is cramped and
none is properly readable. So the tab is a line per test (id, name, how it last did) and an
editor for the one selected — side by side where there is room (the step dialog, a wide
panel), stacked in the 360 px dock, switching automatically on resize. Two columns is what
makes a step with a dozen tests usable: a tall list beside a tall editor, instead of either
starving the other. The list sizes itself to its rows until the user drags the splitter,
and a drag is respected until the orientation changes under it. The body editor is a plain
expanding text well with the framework's markdown highlighter over it — structure visible,
bytes untouched — and its expand is the sanctioned one: a second `TextBinding` over a
`TextField` implemented against the record (`testing/section.py`'s `TestBodyField`), never
text copied into a dialog and back.

## A check is a scope over the graph, and so is a milestone

A **check** is a step type that stands for everything behind it having been verified. What it
covers is not stored: it is the `requires` cone, filtered by which of those steps carry tests.
Storing that list would let `dplanner step link` leave a check claiming coverage it no longer
has, with no window running to notice; it is the same rule as the topological order and
progression, for the same reason.

The part worth noticing is that **a milestone is already the same scope**, and so is a
**feature**. The walk takes a step id and answers for any step at all, so the Tests tab's
scope selector, the *Covers* tab, `dplanner scope show` and `test-run start --scope` are four
readers of one function — and a run can be scoped to a milestone without a line of code that
knows what a milestone is. A check is a scope you *declare*; a milestone is one you already
had; a feature is the one people actually name and demo.

### The cone stops at the next collector

What separates the three is a single predicate. `domain/scope.py`'s `cone(origin, stops_at)`
walks `requires` backwards and refuses to pass **through** a step `stops_at` claims — it
records it as a *boundary* and stops there:

| Asked of | `stops_at` | Because |
|---|---|---|
| a check | nothing | it stands for everything behind it having passed |
| a milestone | milestones | it holds what is new since the last one |
| a feature | features and milestones | it holds its own work, up to the previous feature |

`ordering.upstream()` is that same function with nothing to stop it, which is why there is one
walk here and not two.

The alternative was a stored membership — a `feature` field, or a `belongs_to` edge kind. Both
were rejected for the reason the whole *Deriving rather than storing* section gives, and one
more specific to this shape: a `belongs_to` edge would draw the same relationship a second
time, beside `requires`, and the two would eventually disagree. The semantics wanted here —
everything upstream, minus what an earlier collector already took — *is* the `requires` cone.
There was nothing to add.

### `stops_at` and `gathers` are different questions

A milestone stops at milestones, and is *read* as a list of features. Those are not the same
fact and conflating them was the first attempt's bug: the boundaries are what the walk
deliberately excluded (an earlier milestone already accounts for them), while the group
headings are the finer collectors found **inside** the contents. So `ScopeKind` says both, and
`gathers` is empty for a feature — the finest grain, read flat.

Both are written literally in `modules/__init__.py::_scope_kinds()`, the one file allowed to
name every aspect at once. A rank integer was considered and dropped: three lines a reader can
check by eye beat an ordering abstraction over exactly three things, and the ordering would
have to be explained anyway.

### A step two features both wait on belongs to both

Neither is behind the other, so neither has a better claim, and any tie-break would be
arbitrary. `gatherers()` therefore returns *both* owners, the Tests tab files the step under
one joint heading rather than listing its tests twice — a test in two rows is a test marked
twice — and `dplanner project lint` reports it as `scope.shared` so the ambiguity is nameable
rather than merely visible. Two siblings came free from the same inversion:
`scope.ungathered` (a step carrying tests that no feature waits on — work that reaches no
milestone) and `scope.gathers-nothing`, which generalised the old `check.covers-nothing`.

### Both readings, and when the switch is worth showing

A milestone honestly wants two answers: *what does it add* (the truncated walk) and *what must
pass for it to ship* (the whole cone, regressions included). The Covers tab offers both — and
shows the switch **exactly when the truncated walk found a boundary**. That is a pure function
of the data rather than a property of the kind, which makes it right in two places at once: a
check never has a boundary, and neither does the first milestone in a project, and in both
cases the two readings are the same answer. A control with one outcome is noise.

### Who owns which half

`step_check` is a bare `{"on": true}` marker in its own package with a Type toggle and nothing
else; a feature step's marker names the catalogue record it realises (see *A feature is a
record, and a feature step is its instance*), and the walk reads only whether the marker is
there. The *Covers* tab that shows what any of them
gathers is registered by the **tests** module, because that tab is a list of tests, which is
testing's business. That keeps the wiring one-directional: `TestsDeps` takes the wired
`ScopeKind`s, and neither marker module needs anything from anybody.

The CLI made the same call one level up. `check show` would have become three near-identical
verbs the moment features arrived, so it became **`dplanner scope show`** in `cli/scopes.py` —
the cross-feature home `cli/lint.py` and `cli/authoring.py` already established, where the verb
owns the report and the composition root hands it the kinds and the coverage walk. `cli/` still
imports no module, and no module imports `cli/scopes.py`.

## Documentation is fragments, and a collector compiles them

A plan says what work will be done. It said nothing about what that work *produces for a
reader*, so release notes and user guides were written at the end by reading back over the
graph by hand. Two aspects close that, and the shape of them is the whole decision.

A **fragment** is what one step adds to the product's documentation — `docs`, prose beside
the step, written while the work is fresh. A **compiled document** is what a feature or a
milestone makes of everything it gathers — `docs_compiled`, prose beside the collector.

**Two aspect ids in one package, not one.** A node holds exactly one prose document per
module (`FORMAT.md`), and a feature legitimately has both: its own note, and the document
compiled from the four steps behind it. Putting the second in `module_data` as a string
would cost it the text stack — positional splicing, undo coalescing, a line-by-line diff —
which is the trade that section already refuses for prose.

### There is no step kind for compiling

The first attempt had one: a *Compose Docs* step you created, linked into the graph, and
ran. It worked, and it was wrong. A feature and a milestone **already are** the collectors
the graph defines — `domain/scope.py` has answered "what is behind this, up to the next one"
since checks arrived — so a second kind of collector, existing only to collect, was a node
somebody had to remember to create for a question the graph could already answer. Deleting
it removed a `StepKind`, a Type toggle, a medallion glyph, a mnemonic table the collision
had forced, and two CLI verbs. Every project that already has features and milestones now
gets documentation without adding anything.

Compile is therefore a verb on a collector, and the vocabulary is one predicate the
composition root already wires: *is this step a collector?* is `kind_of(scopes, step)`.

### A milestone reads its features' documents, not their notes again

`ScopeKind.gathers` says a milestone is read as a list of features. `collect.sources_for`
takes that literally: for each feature inside a milestone's cone it reads that feature's
**compiled** document — falling back to the feature's own fragments where it has none, so a
half-compiled project still produces something honest — plus the fragments of everything in
the cone no feature took. A feature has `gathers=""` and so reads flat.

Two things follow, and they are the reason for the shape. A milestone folds polished prose
rather than saying everything twice. And **recompiling a feature marks its milestone out of
date by itself**, because the milestone's sources are that feature's text — the cascade the
feature needed, with no notification plumbing at all.

### Staleness is a digest, not a timestamp

Nothing in the model records when a fragment was last edited, and adding that to support one
check would be storing a derivation. So a compile stores the **digest of what it read**
(sha256, sixteen hex, the convention `domain/assets.py` content-addresses blobs with) and
"is this out of date" is a comparison against the same walk run now.

That is exact where a timestamp is a heuristic, and it is right in a case a timestamp would
get wrong: `dplanner step link` changing what a feature gathers changes the digest, and the
document says it is out of date — which it is. It also gets the other direction right.
**Hand-editing a compiled document does not make it stale**, because the digest is over the
sources, not over the output; a person tidying the model's prose is finishing the job, not
invalidating it.

Three states fall out, and they are a pure function: no entry is *never compiled*, a
matching digest is *current*, anything else is *out of date*. The Docs view draws them as a
hollow ring, nothing at all, and a filled accent dot — nothing being the quiet common case.

### Who owns which half

`modules/docs/` owns both aspects, the fragment editor, the Docs folder and the Docs view;
`collect.py` is the one derivation, Qt-free, with four readers (the view, `docs collect`,
`docs status`, the compile prompt). The collector kinds arrive as an argument, exactly as
`TestsDeps` takes them — **nothing is added to `_scope_kinds()`**. A fourth kind there would
have put documentation in the Tests tab's scope selector and its Group by, and given every
collector a Covers tab it never asked for: four surfaces learning about documentation to
serve none of it.

## An LLM call is a task, and the service is GUI-bound

`framework/llm_service.py` shipped complete and dormant — no consumer, no tests, and no
mention in this file. Compile is its first, and these are the rules it established.

**`complete()` is blocking network I/O.** It runs inside a `TaskRunner` body, and because
the runner's body returns nothing, the answer comes back on the owner's own queued Qt
signal — the pattern `install/command_dialog.py` and `github/section.py` already use. A
timeout becomes `TaskTimeoutError` so the task centre shows a timed-out job rather than a
generic failure, and a delivery whose step has stopped collecting is dropped, exactly as a
stale PR refresh is.

**Nothing logs the call.** The service appends every one to a ring buffer *before* the
provider runs, which is what makes even a hung request visible in *Debug ▸ LLM Calls*.

**An AI-gated control is disabled, never hidden**, and carries `status().message` — which
already names *Settings ▸ LLM* — as the reason, on screen rather than only in a tooltip. The
service re-reads its provider on every call, so a control re-asks on `config_changed` and
configuring one ungreys the button where it stands.

**The result lands on the undo stack**, unlike `github/refresh.py`'s background sync. The
distinction is who asked: a person pressed a button, so undo must put back what was there.

**And the CLI cannot call it.** The service reads its preferred provider through QSettings
and its key through the OS keychain, so it is Qt-bound by construction while `cli.py` loads
no Qt by rule. That is not a gap to route around: the agent driving the CLI *is* a model, so
the headless loop is `docs status` → `docs collect` → the agent writes → `compiled set`,
which re-stamps the digest so the document it just wrote reads as current. Same reasoning as
*Running an agent launches a peer, not a task*.

## A test result is not a step status

Two vocabularies, deliberately sharing no words. A step's status is `pending`,
`in-progress`, `done`, `blocked` — where the *work* stands. A test's result is `ok`,
`failed`, `skipped`, or absent — what happened when somebody *ran* it. A test on a done step
is not "done"; it is a thing that passed last Tuesday and might not today.

**A failing test gates nothing.** It does not block a milestone, and it does not touch
`progression()`. Progression answers "what can be launched right now, given the graph and
the stored statuses"; folding results into it would quietly make `dplanner progression show`
answer a different question. A person deciding whether to ship reads both.

## One open run per project, and a run freezes its membership

A **test run** is one occasion of executing a scope: which tests were in it, and what each
one did. Two rules do most of the work.

**At most one run is open per project.** Starting a run closes whatever was open. That is
what makes "mark these twelve ok" a pure function of the context — there is no hidden
"which run" the user must have selected first, no verb carrying one, and the action state
can say *"Mark Ok — start a test run first"* rather than being mysteriously inert. The Tests
tab's Run selector can still *show* a closed run; it is read-only, because a record of an
occasion is not an editable list.

**A run freezes the tests it was opened over.** `tests` is a stored list of ids, not a live
query, so adding a test or relinking the graph afterwards cannot change what a closed run
means. The cost is that a test added mid-run does not join it — which is correct: it was not
there. A missing result reads as pending, so opening a run over two hundred tests writes two
hundred ids and no statuses, and the file grows as the work is actually done.

**The latest result is the newest run that recorded one**, not simply the newest run. A test
absent from yesterday's run has no answer from it, and reporting "not run" there would erase
what last week established.

## Pressure points, named before they hurt

A whole-codebase review (2026-08) found the architecture holding; these are the places
where growth has a known cost curve, written down so the feature that crosses the line
recognises the moment. None needs action today.

- **`_briefing_sections()` in the composition root grows one hand-rolled block per aspect**
  with a briefing presence — four blocks today, each with its own empty-check. The exit is
  the shape `cli/lint.py` and `cli/authoring.py` already use: each module exports a Qt-free
  block builder, the root assembles the list. When the function hits about six blocks, make
  that move rather than adding a seventh `if`.
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
- **`project_editor` accretes by construction.** *Modules never import each other* means a
  feature that lives *on* the canvas — regions, named layouts, sorts, the minimap — cannot
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
- **Rebindable keys.** `modules/project_editor/keymap.py` is the table a settings page would
  read; nothing reads it yet, which is the only reason it is a constant.
- **Reports** — new folders in the index tree, which is the shape the registry was built for.
  `dplanner schedule show` is the first of them, and it lives in the module that owns the
  numbers rather than in the one that owns the table. (The schedule that knows about
  parallelism, once listed here, landed as `parallel_finish` and the time estimates tab —
  see *Time estimates: two worker pools, one greedy simulation*.)

## A feature is a record, and a feature step is its instance

A specification used to be read into **requirements**: quoted obligations in the spec
module's index, linked N:M to steps, cited in briefings, checked by lint. It was honest and
it was the wrong grain. Nobody demos a requirement; people name, build and test *features*,
and the graph already knew that — a feature step gathers the work that flows into it, and
`dplanner scope show` reads it. What was missing was the feature *before* it is on the graph:
the thing a person reads out of the spec, adds by hand, drags into place.

So a feature is now a **record** in the project's catalogue (`modules/feature/catalogue.py`)
— title, description, where in the spec it was read from, images — and a feature step
carries only the record's id. The record is stored because an unplaced feature is a fact the
graph cannot derive; membership is still never stored, for every reason *Deriving rather than
storing* gives. Three consequences are the design:

- **A feature is implemented once.** One record, at most one step naming it. The drop, the
  Type toggle, `feature set` and `step add --feature` all refuse a second instance in the
  same words, and `feature.duplicate` names one that arrived by hand. That is what lets the
  Features panel say *placed* or *not placed* and mean it.
- **Records outlive their instances.** Toggling Feature off, deleting the step, `project
  clear-steps` — each clears the marker and leaves the record in the catalogue, unplaced.
  Undo has to restore either side independently, which is the rule an edge to a deleted
  step already follows; and a record somebody wrote is never lost to a gesture on the
  graph. Only the feature verbs create and remove records.
- **A work step reaches the spec through the feature it flows into.** No link on the step:
  its briefing lists the features `scope.gatherers` says own it, with the passages they were
  read from. A citation that was N:M on requirements is a walk on features, and it cannot
  go stale when `dplanner step link` rewires the graph with no window open.

The trace is therefore graph → feature step → record → spec passage. The quote is still
checked against the document — on `feature add`, and on every lint — through the spec
module's `anchor_quote`, handed across by the composition root: the record belongs to one
module and the document to another. Two things were deliberately not done. Requirements
were not converted into features: a requirement was a citation and a feature is a thing, and
only a person reading the spec again can say which citations were features — so the spec's
format 3 drops the key and the skill says how to read them out afresh. And the marker the
retired `step_feature` module wrote is not minted into a record at open: a per-entry
converter cannot see the project, so it passes through and reads as *unregistered* — still a
feature to the graph, named by lint, registered by the first `feature set`.

## A citation is a quote and a digest; its place is derived

A feature record says where in the spec it was read from, and the coverage view draws a
line from that passage to the feature. Two questions decided the shape: what to store,
and what happens when the spec changes underneath.

**A passage is stored as its quote, never as an offset.** The in-app editor flushes a new
blob on every pause in typing and `dplanner spec import` replaces a document with no
window running; an offset would be wrong within the hour, and a stored "found" would be
wrong the moment the file was replaced. So the quote is the anchor and `core/anchors.py`
finds it again on every read, exactly as the topological order is computed and not
written down. The match is exact first (case and whitespace aside, through an index map
that hands back raw offsets — what a viewer washes), then **fuzzy**: the quote's rarest
words seed windows the size of the quote, each end is tried a little either side, and the
best `SequenceMatcher` ratio wins if it reaches `DRIFT_RATIO`. That is the sentence
somebody reworded, offered back as the *drifted* candidate `feature reanchor
--accept-drift` takes. Nothing reaching the ratio is *lost*. The word-seeded search was
chosen over the longest-common-run seed it replaced because a heavily reworded sentence
keeps its nouns and little else.

**A passage carries the digest of the document it was read against**, the content-addressed
stem of the blob, so nothing new is hashed — `docs_compiled`'s digest for the same reason:
"did the spec move on since this was read" is a comparison, never a flag. But a
comparison alone would flag every citation in a document when somebody fixed a typo in
its last section. So *behind* is refined: the stamped blob is still on disk (blobs are
content-addressed and never pruned but for a session's own churn), and `diff_hunks`
between it and the current text says whether any change landed in the paragraph holding
the quote. Untouched is *anchored*; touched is *behind*; a stamp whose blob is gone is
*behind*, conservatively; no stamp — a passage migrated from format 1 — is judged by the
match alone, so an old project opens into no warnings. `feature reanchor` re-stamps what
still anchors, and lint names the three states with the verb that resolves each.

**Uncovered text is how new spec content surfaces, with no change tracking at all.**
`core/anchors.py::blocks` reads a document as paragraphs under their heading path; a
paragraph is covered when an anchored passage overlaps it. New text is simply uncovered
text, and `dplanner coverage spec <doc> --uncovered` is the agent's inbox after any
change — and the retrofit for a project that predates citations. It is a report, not a
lint, because it is perpetual by nature: a spec is never wholly claimed.

**The trace is one derived picture with two readers, and its path rule is feature
membership.** `modules/coverage/trace.py` arranges what four modules own — passages
(spec), records (feature), the gathering milestone and the tests in a cone (the graph and
testing), the compiled document's state (docs) — into four columns and links between
neighbours, reading each through a callable the composition root hands in
(`_coverage_trace`), so the coverage module imports no other module and the picture
cannot disagree with the verbs. Every item carries the features it serves: a passage the
features citing it, a feature itself, a milestone the features it gathers, a test the
feature whose cone holds its step (two features → both, honestly), a milestone's own docs
card all its features. What lights up on a pick is then one set intersection: a feature
lights exactly its chain, a milestone everything behind it, a passage two features cite
both — no case per kind. A milestone also carries a token of its own, so work it holds
directly belongs to it and to nothing else. The alternative — walking links upstream and
downstream — would have needed a rule per column pair to keep one feature's tests from
lighting another's, and it would have been wrong the first time a step sat in two cones.

**Four lanes, each scrolling on its own, and links only in the gutters.** The tab is one
scene: a lane is a clipped column with its own offset and a thumb only while it
overflows, a link runs from one lane's edge to the next at the height of the cards it
joins, and a card scrolled out of view carries its end past the gutter's clip, so the
line is cut at the gutter rather than drawn over a caption. A pick scrolls every lane
but the one it landed in — the card under the pointer stays under the pointer. Cards
paint with the primitives the canvas paints with (`theme/cards.py`, moved there so two
modules can share them without importing each other), and every colour is read from the
scene's palette at paint time, so a theme switch costs nothing.

## A note is a record with a label, and the briefing carries an index

A plan says what; what it does not say is everything a project learns as it goes — why it
went one way and not another, what a finished step's worker wants the next one to know,
where the work had to depart from the spec, what was noticed and put off. Two modules
used to hold two of those: a *decision log* beside the project, carried in full into every
briefing, and a *handoff* aspect on each step, inherited down the graph and carried in full
too. The first project to run forty agent steps showed what that costs: the briefing grew
with every step, an agent starting the thirtieth read twenty handoffs and a page of
decisions before its own instructions, and lost its focus in them — while the two record
kinds were the same thing wearing two shapes. Five decisions:

- **One log, and a closed list of labels.** A decision and a handoff are both *a note the
  project made along the way*; what differs is what the note *is*, and that is a word on
  the record — `decision`, `handoff`, `spec-change`, `later`, `post-project` — from a
  list this build owns (`log.LABELS`, a row each with its meaning, its default reach and
  the index's heading over it). Closed on purpose: an agent reading an index line must
  know what the line is without opening it, and a free tag vocabulary is what every agent
  invents differently. A new kind is a row, and `note add --help`, the skill and the
  index follow. The record is the decision log's shape kept — `N1, N2, …` minted per
  project and never reused, a title, markdown in the record, the day, the step it was made
  on, what it supersedes — with two fields the handoff needed: the steps it is *for*, and
  a *reach*. `modules/notes/` replaced both packages rather than sitting beside them,
  because two record kinds with one meaning is the entropy CLAUDE.md asks every pass to
  remove.
- **The briefing carries an index, and only what is addressed in full.** What the
  hundredth agent needs is to *find* what is relevant, not to read everything ever
  written. So a briefing's notes block is one line per standing note that reaches the
  step — id, title, when and where — grouped under the labels' headings, with the verb
  that opens one (`dplanner note show`); the bodies stay in the log. The exception is a
  note *addressed* to the step (`--for S12`, the editor's *For* field): that is one agent
  pointing the next at exactly what it must read, so it is printed in full, files and all,
  under *Notes for this step* ahead of the index. The block sits after the instructions,
  where the inherited context sat, because it is read once the work is understood. The
  title therefore carries the weight — the skill and the epilogue both say *title it as
  the fact it is* — and the agent that skims a line and does not open it has made a
  choice the old briefing never let it make.
- **Who sees a note is its label's business, with one stored exception.** A handoff
  reaches the steps *after* the one it was made on (the cone the old aspect walked, plus
  the step itself — a re-run is a pick-up too); every other label reaches the whole
  project, because a decision or a deferred item is the project's, not a branch's. A
  handoff everyone should see is `--reach project`, stored only when it differs from the
  label's default (`FORMAT.md`'s absence rule), and a note made on no step has nothing to
  be downstream of, so it reaches everyone whatever it wears. `reach.reaching()` is the
  one derivation.
- **Adding twice is one note, and reversing is a new one — on the same step.** The
  decision log's retry safety kept, narrowed: a title already in the log *on the same
  step* is that note, reported with the verb that revises it and never duplicated. The
  narrowing is the handoff's doing — two agents each ending their step with a note titled
  *Done* must not have the second silently discarded. A reversal is a new record
  `--supersedes` the old; the history stays, `note list` shows what stands and `--all`
  what did, and a superseded note leaves every index.
- **The retired modules reach the log at open, one by takeover and one by absorption.**
  The decision log was already a record list on the project, so it is a `Takeover`
  (`D<n>` becomes `N<n>` wearing `decision`, supersedes links with it). A handoff was prose
  and files on a *step*, and a per-entry converter never sees the project the record
  belongs on — so `ModuleDataFormat` grew an `absorb` pass, run once per open over the
  whole repository with the loaded aggregate (`core/module_data.py`; `NOTES-FOR-APPFRAME.md`
  §21), and `migrate.absorb_handoffs` turns each step's handoff into a `handoff` note on
  that step, moves its files into the project's notes area with links written into the
  body, and clears the step. Idempotent, so a second open finds nothing. A handoff a
  person had turned *off* stays on the step's shelf under the retired id, untouched: that
  is what turning it off meant. The Handoff tab, its Type toggle and its place in the
  *Agent* template went with the aspect; the window's surfaces are the *Implementation
  notes* tab (the log as rows newest first beside the buttonless live editor with a
  label, a step, addressees, the reach box and the body, *Add Note…* opening on the
  title, Remove in the `⋯`) and the Agent tab's Notes pane, which renders the same
  blocks the briefing carries. The view lived in the project panel as a card first, one
  widget per note; a plan whose agents had written 344 handoffs made every window
  relayout walk 688 word-wrapped labels, and the always-on panel was the wrong place for
  a log that grows with every run — see *The context is announced once per turn* below
  for the measurements. It was then a second reading inside the Docs tab behind a
  switch, which the index said nothing about; a tab of its own is what every other
  project surface is, and the row that opens it sits under the project in the Docs
  folder beside *Documentation*, because the notes are the project's other document. A
  tab page may carry a list of its own (DESIGN.md forbids one only inside a card, where
  the wheel would stop scrolling the stack), the rows are painted by the framework's
  two-line delegate, and the editor binds only the note that is picked. The notes module
  hands its row to the docs module through the root (`DocsDeps.more_rows`), the
  arrangement the order view and the estimation module's start-date bar already have;
  neither imports the other.

## The topology is read before the graph is edited

A project's **topology** is its own account of how its graph is shaped: what counts as a
feature here, what follows one, where the milestones fall. It is prose beside the project
(`modules/spec.md` — the spec module's one prose document, edited in the Specs tab as a
pinned first row and by `dplanner topology set`), and it reaches every briefing as a project
section. An agent that edits the graph without having read it produces a plan in the wrong
shape, and a wrong shape costs far more to correct than an empty one. So the CLI refuses.

The gate is a **declaration on the command**. A verb that reshapes a graph — adds or removes
steps, links them, places a feature — sets `CliCommand.edits_graph` to a resolver saying how
to find the project from its own arguments, and the composition root puts `cli/gate.py`'s
check in front of every declaring verb. No path table in the root, no wrapper reverse-
engineering argparse: the verb says what it is, the skill marks it (*reads the topology
first*), and a content verb — a title, a description, a feature's wording — declares
nothing and is never refused. The check runs before the handler, so a refusal is not a
half-applied run.

"Has read" is a **digest, not a flag**. `topology show` records the sha256 of the text it
printed, per project, in a per-user, per-machine file under `core/config_dir.py` (Qt-free,
because `cli/` must reach it) — never in the plan, which is shared. The gate compares that
with the text as it is now, so a topology that changed since it was read is unread again with
no version stamp and no migration: the comparison is the check, the same shape as a compiled
document's staleness. A project with no topology refuses too — the first thing to do with a
project is to say what shape it wants, and the refusal names the verb. The window is never
gated: the topology is the user's own text, and the gate exists for the agent driving the
CLI. `project import` is not gated either: it creates a project from an export that carries
the topology as `text.spec`, and `topology.missing` lint catches one without.

The test suite's shared registry runs behind a gate with no record file — one that refuses
nothing and writes nothing — so no test ever writes the real per-user file and every CLI test
adds steps freely; the gate itself is exercised over a record under `tmp_path`.

## A view refresh is coalesced, and hears one project

The window was choppy on edits, and the reason was structural rather than any one slow
function. Every model signal is delivered synchronously (`core/signals.py`), inside the
command that caused it, inside `UndoService.push`; every open tab rebuilt itself completely
on every signal; and no tab asked which project the signal was about. One keystroke in a
description therefore ran the canvas's full automatic layout (even with every node placed),
a topological sort and a schedule walk *per milestone step*, twenty-four schedule
simulations for the Time tab, a fresh `QTableWidget` for the order, every card of the
progression board, the docs and tests tables, and a directory listing for the Agent tab's
inherited context — for every open project, not only the one being edited — and then
re-evaluated all ninety-nine action states. Measured headless over an eighty-step project
with seven tabs open, that was **67 ms of synchronous work per keystroke**.

Four decisions, in the order they were applied, each measured with the journal below:

**The derivations stop scanning, and the canvas computes once per sync.** `Project.step()`
is a linear scan and every graph walk asked it once per edge; a set of ids per walk made
`depths`, `cone`, `progression` and the critical path linear again. `positions()` runs the
automatic layout only when some step lacks a stored one — on a settled plan, never — and the
accent seam became `step_accents(project_id)`, one dict per sync with one schedule walk for
every milestone, where `milestone_stat(step)` had walked it per milestone. Nothing about
these needed a timer; they were simply wrong, and the journal is what made them visible.

**A view of one project hears that project.** `follow_project(library, project_id,
changed)` in `framework/activity.py` asks the model's own `belongs_to` about the node each
signal names — the parent of a structure change, the step of an edge or a text edit, the
node of a field or module-data write — and `follow_target` does the same for a panel
section whose step moves under it. It sits beside `follow_entity_tabs` because it is the
same shape: feature-blind upkeep that seven modules had copied by hand. The filter is a
question for the model rather than for the view because a view that reads the parent index
itself is a second implementation of "which project is this node in", and there was
already one.

**A burst is one rebuild, and the newest state wins.** `framework/debounce.py` is the
timer `AutosaveService` and the assets tab had each hand-rolled: `Debounced.trigger()`
restarts a single-shot `QTimer`, so within a burst the older triggers never run, at most
one run is pending per view, and nothing queues. That is the answer to "does a new update
cancel the old one": it does not cancel it, it *replaces* it, because until the timer fires
there was nothing to cancel. Zero delay means "once this event-loop turn is over" — the
canvas uses it, so a composite command's forty signals become one sync and a typed title
still lands on its node as it is typed. A real delay means "after a quiet spell": 300 ms
for a table, a list or a board (the assets tab's number, below what reads as lag on a
rebuild nobody is waiting for), 500 ms for the Time tab, whose refresh is the heaviest
reaction in the application. After the conversion the same harness measured **5 ms of
synchronous work per keystroke**; the Time tab rebuilt once per burst (26 ms) instead of
ten times, the order table once (12 ms), the assets catalog once (15 ms). What was left was
the context refresh — every action's state, every toolbar and every panel re-asked — which
the app shell ran inline on every undo push; it is now the same 0 ms `Debounced` as the
canvas (the context service's own `announce`, since *The context is announced once per
turn* below), and the synchronous cost of a keystroke is **0.3 ms**, with the canvas sync
(8 ms) and the context refresh (3 ms) following once per event-loop turn.

**Why not a worker thread.** The off-thread design was drawn up — a derivation with a
generation counter, applying through a queued Qt signal, dropping any result a newer
request had superseded — and it is sound: the model is mutated only on the GUI thread, a
mutation and its signals and the handler's re-request all run in one synchronous turn, and
a queued apply cannot land before that turn ends. It was not built, for three reasons that
hold whatever the numbers say. The derivations are pure Python, so a worker competes for
the GIL and total CPU is unchanged; coalescing, not parallelism, is what removes the
N-times-per-burst cost. A worker still running when a build is discarded emits on a deleted
`QObject` — the exact widget-lifetime hazard the suite's SIGSEGV notes describe, in a suite
that builds hundreds of applications per process. And "an exception mid-read is a
superseded result" swallows real bugs. The one place a thread honestly helps is disk I/O,
and there the cheaper fix is a cache: the branch label's `git` query, asked twice per
keystroke, is remembered for a second. The disk poll (8 ms every two seconds at eighty
steps) and the minimap refresh (0.1 ms) were measured and left alone; a `poll` span appears
in the journal the day a slow disk makes the first one matter.

**Tests run in immediate mode, and that is the whole test strategy.** About a hundred and
fifty tests assert on a view the line after they push a command, and a deferred rebuild
would fail every one of them for no finding. `DebounceService` carries one switch, set by
the suite's `session` fixture: `trigger()` runs the action inline, which is exactly the
behaviour every view had before it was coalesced. The deferred path is tested once with
real timers (`tests/framework/test_debounce.py`) and once per converted view by switching
immediate mode off, pushing three times, and asserting one rebuild after `flush_all()`.
Sprinkling `qtbot.wait` over a hundred tests was the alternative, and it would have made
every one of them slower and none of them more honest.

## How the application scales

Measured on 2026-09-08, four days after the coalescing pass above and after the coverage
tab, the progress recorder, the notes log and the feature catalogue had landed on top of
it. Two sources, read together: the user's own journal — every stall the watchdog sampled
and every slot over `SLOW_MS` from four days of real sessions on a project of under a
hundred steps — and `scripts/measure_scaling.py`, which builds the application headless
over `scripts/synthetic_library.py` (three projects in one plan repository, two of them
*N* steps with the real aspect mix: statuses, estimates, a milestone every fifteen,
features, agent steps, tests with runs, notes, a description and a stored position on
every step) at *N* = 25, 50, 100, 200 and 400, and runs every gesture the window has in
the deferred regime, pumping the event loop until nothing is pending and the journal has
been silent for 150 ms. The numbers below are the *few tabs* regime — the graph, the
order table and the Time tab open, which is how the project that felt sluggish was being
used; the *all tabs* regime is at the end. The same sweep on the desktop platform
(wayland, by accident) agreed with the offscreen one within noise on every row but paint,
which is the honesty check on the harness.

**The graph math is not where the time goes.** Every domain derivation is linear and
cheap: at 400 steps `depths` is **0.7 ms**, `cone` **0.4 ms**, `progression` **0.6 ms**,
`link_refusal` **0.02 ms**, the automatic layout **3 ms** (and a project with a fifth of
its steps unplaced syncs its canvas in the same 11 ms per keystroke as a placed one). A
title keystroke's synchronous cost — the `command` span — is **0.4 ms at every size**,
exactly the number the section above ended on. What the journal and the harness agree on
is that the cost sits in the *reactions* to a change and to a click, and that most of it
does not scale with the project at all; it is a constant paid per gesture.

| per gesture, ms | 25 | 50 | 100 | 200 | 400 |
|---|---|---|---|---|---|
| **click on a step** — `PanelDock._on_context` | 42 | 43 | 51 | 59 | 80 |
| pick 20 cards on the canvas | 166 | 182 | 201 | 247 | 517 |
| **details dialog** — construct + first show | 108 | 98 | 113 | 115 | 157 |
| prose keystroke — canvas `_sync`, same turn | 3 | 6 | 11 | 24 | 58 |
| prose keystroke — context refresh, same turn | 4 | 4 | 4 | 5 | 6 |
| after a burst — Order table rebuild | 11 | 20 | 38 | 78 | 126 |
| after a burst — Time tab rebuild | 11 | 21 | 43 | 88 | 206 |
| estimate burst — recorder, per run (×2) | 4 | 6 | 9 | 16 | 37 |
| new step — one `AddNodeCommand` | 7 | 7 | 8 | 9 | 11 |
| paste of 20 steps — the command | 122 | 137 | 137 | 156 | 188 |
| **disk poll**, every 2 s | 18 | 26 | 43 | 78 | 151 |
| autosave flush after one edit | 17 | 27 | 49 | 86 | 159 |
| **full garbage collection** (gen 2) | 239 | 250 | 268 | 296 | 360 |
| keyring read, per call | 4.3 | 4.1 | 4.1 | 4.0 | 4.2 |
| cold open: Tests tab | 146 | 171 | 278 | 670 | 1637 |
| cold open: Coverage tab | 113 | 145 | 335 | 973 | 2672 |
| cold open: Estimates tab | 315 | 423 | 707 | 1281 | 2358 |
| session open | 1784* | 288 | 311 | 461 | 710 |

*the first open of the process pays the imports.

**What the click costs, and why it is flat.** A click publishes the selection, the dock
asks every context panel to `show_context`, and `StepPanel.show_step` calls `show_target`
on **all nine of its sections whether or not their tab is visible**
(`modules/step_properties/panel.py`, `_show_in_extensions`). The profile at 100 steps puts
the whole click in that loop: the Agent tab rebinds two editors (`TextBinding`, a
`setPlainText` of the whole document each) and assembles the inherited briefing **three
times per click** (`_mark_prompt_stale` from `show_target`, from `_refresh_derived` and
from the follow); the Covers tab runs two `cone` walks, parses the run history and
builds a card widget per gathered test — eighteen widgets per click on the synthetic
project; the GitHub tab starts a fetch; every prose tab rebinds. The user's journal has
the same slot at **30 to 105 ms** thirty times over four days, and the details dialog
is the same cost twice: `StepDetailsDialog` builds a second full panel (nine sections,
four Details blocks, about thirteen widget trees and fifteen subscriptions — 185
`addLayout` calls and sixteen thousand calls into the Python `styleHint` override of
`theme/style.py` per open) and then shows the step in it, while the docked panel keeps
listening beside it. Construction is **80 to 125 ms**, flat until the largest size; the
first show is 20 to 30 ms headless, and the journal's three `steps.details` stalls of
**~350 ms** are the same open with real painting behind it. Picking twenty cards costs
twenty publishes, because the scene announces `setSelected` one item at a time and every
announcement runs the whole chain.

**The second wave is real, and it is the recorder.** An estimate, a status, a link, a
birth or a deletion settles at ~1000 ms where a title settles at ~700 ms, and the journal
says why: `ProgressRecorder.record_all` runs 300 ms after the burst, simulates every
project in the library, writes `progress_history` on the project node — and that write is
a `module_data_changed` every `follow_project` view of the project hears, so the canvas,
the Order table and the Time tab rebuild a second time, and the recorder, which listens to
`module_data_changed` too, runs once more to find nothing changed. Two full simulations
and a second round of every rebuild, per burst, for a record that only has to be right
once a day. A title or a prose keystroke escapes it only because the snapshot compares
stretches, not titles. In immediate mode — the test suite's regime — the same ten
estimate edits ran the recorder **nineteen times** and every open view nineteen times,
which is the mechanism with no timer to hide behind.

**Two costs on the GUI thread scale with the plan on disk, not with the graph.** The
workspace poll is `LibraryStore.changed_underneath()` (`domain/store.py`), a `stat` of
every plan file of every open project every two seconds — **151 ms at 400 steps, 43 ms
at 100**, a hitch on a period. And a flush walks the same tree twice per dirty project,
once to check for a foreign change and once to re-stamp what it wrote
(`_snapshot` from `flush` and from `_remember_disk`), which is why saving one title
costs 159 ms at 400 steps. Neither is the graph; both are proportional to
*projects × steps × module files*.

**A full collection is a quarter of a second, whatever the project.** `gc_policy.py`
runs the interpreter's own generational policy from a 200 ms timer on the GUI thread; a
generation-2 pass over the application's **240 000 to 326 000 live objects** takes
**240 to 360 ms**, and the journal has one at 337 ms sampled inside `collect_if_due`.
The project is a small share of that graph — 25 steps and 400 steps differ by 90 000
objects and 120 ms; the rest is the application. Generation 0 is 0.01 ms.

**What does scale, and how.** The canvas sync is superlinear — 3 ms at 25 steps, 58 ms
at 400 — and half of it at the top is `step_accents` → `_milestone_stats` →
`project_schedule`, where `domain/schedule.py`'s `working_days_after` walks the calendar
**day by day from the project start for every step**: 0.7 ms at 25 steps, 28 ms at 400,
quadratic in the plan's length in days. The Time tab's `time_report` carries the same
walk through `phases` and `parallel_finish` (10 → 201 ms), and so does the recorder's
snapshot. The Order table is linear in rows (11 → 126 ms, a `QTableWidget` rebuilt whole).
Three tabs are expensive to open cold and get worse faster than the project grows: the
Tests tab and the Coverage tab (about *N*^1.2 and *N*^1.4, both walking every collector's
cone and building a widget per row), and the Estimates tab (linear, a `QWidget` editor
per row, **2.4 s at 400 steps** — the journal's 448 ms stall at `bulk.py:285` is the same
table at a hundred). Painting is small headless — 3 to 11 ms a frame at a 280 000-pixel
viewport, the dots and crosses grounds costing a few ms over a plain one — but a 4K
display has thirty times the pixels, and the journal sampled two `steps.details` stalls
of **314 and 324 ms** inside `paint_ground`, which draws every grid point of the visible
plane as an antialiased round-capped point on every repaint.

**Two subscribers answer signals that were never about them.** Every `structure_changed`
in the library — a step born, pasted or deleted in any project — reaches the sync
module's `_on_membership` (`modules/sync/module.py`), which rewires the repository
groups and asks git for every branch: **5 to 6 ms per signal**, twenty subprocesses for
a paste of twenty steps, and the largest single slot in the add, paste, delete and undo
scenarios. The notes card hears the same signal and refreshes per step (0.5 → 3.7 ms).
Membership is a change under the *library* node; a step is a change under a project. The
`foreign_edit` scenario — ten title edits on the sibling project — confirms that every
`follow_project` view is clean: not one refresh from the Big project's tabs at any size.

**And the action-state refresh reaches the keyring.** With a milestone or a feature
step selected, the docs module's `compile_state` asks `llm.status()`, which asks the
provider `is_configured()`, which is `keyring.get_password()` — a D-Bus round trip to the
Secret Service of **4 ms**, uncached, on every context refresh while that step is
selected (`modules/docs/module.py`, `framework/secrets_store.py`). Small per call; the
refresh runs on every push and every click. The spec-sources pass already states the rule
this breaks (*A spec source is a kind the spec module runs*: an action's `state` never
makes a keychain round trip — `status()` reads a `user_config` row, and the secret is read
only inside the act), so the fix has that shape too: a *configured* row the state reads,
the key read only when a call is made.

### All tabs open

With all eleven tabs open the same edits cost more only where a view has no project
filter or no timer, and there they cost a great deal. A title keystroke's synchronous
cost goes from 0.4 ms to **6 ms at 25 steps, 15 ms at 100 and 62 ms at 400**, and the
`foreign_edit` scenario — a title edit in the *sibling* project — costs exactly the same,
which names the view: *All tests* (`modules/testing/activity.py`, `AllTestsActivity`)
walks every project and rebuilds its whole table on any structure, field or module-data
change, synchronously, in the signal. The Estimates tab (`modules/estimation/bulk.py`) is
the other: its `_on_structure` rebuilds the table with an editor widget per row on any
`structure_changed`, so **one new step costs 121 ms at 25 steps, 368 ms at 100 and
1.4 s at 400** while that tab is open — the journal's 448 ms stall at `bulk.py:285` is
this, on the real project — and it rewrites every row's text on any `field_changed` in
the library (4 ms at 400). The Coverage tab is filtered and coalesced, and still costs
**690 ms at 400 steps** once per burst; a click on a step reaches 113 ms with every
section and context panel listening. Everything else in the all-tabs run is the few-tabs
number plus the debounced rebuild each tab already owed.

### What to change, in order

Each of these is a rule about the framework rather than a patch to a view; the numbers
above are what to re-measure after each.

1. **A section shows on demand, not on every selection.** The inspector host
   (`framework/inspector.py`, `StepPanel`) shows the *current* tab's extension on a
   selection change and marks the others stale; a tab switch shows the stale one.
   `AgentSection._refresh_prompt_if_shown` already hand-rolls this for one pane — the
   rule belongs in the host, once, and removes the per-section guards. This is the click
   (42–80 ms → the one visible section) and half the dialog.
2. **The recorder reads the settled state and never re-emits into it.** Record once per
   burst, for the project the burst was in (`belongs_to`), after the views' own settle,
   and write with an origin the `follow_project` views are told to ignore — or write to
   the per-user store, since the record is a fact about the day, not the plan. Ends the
   second wave: one simulation instead of two, one rebuild instead of two.
3. **A derived fact is cached per library revision.** One counter the mutators bump;
   `cone`, `depths`, `project_schedule`, `progression`, `runs.read` and the briefing
   memoise on it. *Computed, never stored* still holds — a cache keyed by the revision
   cannot disagree with its source — and it removes the "asked N times per refresh"
   class at once: the three briefings per click, the five run-history parses per context
   refresh, the schedule walk per canvas sync.
4. **`working_days_after` is arithmetic, not a loop.** Weeks times seven plus the
   remainder. Turns the schedule, the Time tab and the recorder linear.
5. **A structure signal under a project is not a membership change.** `_on_membership`
   checks `parent_id == library.id` before rewiring; the notes card follows its project.
   Removes twenty git subprocesses from a paste.
6. **An action state never leaves the process.** `LLMService.status()` caches until
   `config_changed` — the seam *An LLM call is a task* already names.
7. **Every subscriber follows a project and coalesces.** Convert `estimation/bulk.py`,
   `AllTestsActivity` and `framework/project_list_segment.py` to `follow_project` +
   `Debounced`, and add the rule to `tests/test_architecture.py`: a `library.*_changed
   .connect` outside `framework/activity.py` and the store is a finding.
8. **Full collections run when the window is idle.** `collect_if_due` keeps generations
   0 and 1 on the timer and defers generation 2 until nothing is pending and no input
   has arrived for a moment — the 240–360 ms pause moves to where nobody is waiting.
9. **The poll and the flush walk the tree once.** `changed_underneath` on a worker
   through `TaskRunner` (it is I/O, the one place a thread honestly helps), and the flush
   re-stamps with `_note_written` instead of a second walk.
10. **Then the smaller ones**: a scene that announces a multi-selection once; the
    Estimates and Tests tabs building rows lazily; `AspectBar.refresh` evaluating each
    toggle once; the ground cached as a pixmap tile per (rect, zoom, background).

Re-measure with `uv run python scripts/measure_scaling.py --sizes 25,100,400` after
each; the click, the second wave and the poll are the three rows to watch.

## The context is announced once per turn, and a panel that steps aside keeps its content

**The rule.** `ContextService` updates its snapshot synchronously and *announces* it
through a seam the builder routes into a 0 ms `Debounced`: every listener — the menu
bar's ~150 action states, six toolbars per canvas, the panel dock, the sync module's
branch label — hears one context per event-loop turn, the final one. A gesture that
changes the selection does so in one `GraphScene.select_steps`, which announces once; a
verb that needs a selection the user never made (`steps.link` after a connect or a drop)
is handed a constructed `Context` instead of the canvas selecting for it; a panel the
dock takes off screen keeps what it was showing; and nothing in an action state or a
structure listener spawns a process.

**What it replaced, measured.** On a real plan — 74 steps, 118 links, 344 notes, the
project tab open, one step selected — a connect (`c`, click, click) blocked the GUI thread
for **1.7 s** and a paste for **0.6 s**, while the link command, the paste command and
the canvas resync each cost under 10 ms. Two causes multiplied. The connect published the
selection *seven* times, synchronously, each publish re-evaluating every action state
(20 ms for the menu bar alone), and the re-selection cleared before it selected, so the
selection was empty between publishes: the step panel stepped aside and came back twice
per gesture, and each swap was `QSplitter.setSizes` at 33–66 ms over the whole widget
tree. The tree was that heavy because the project panel cleared every card when a step
was selected and rebound them when the selection emptied — the Notes card tore down and
rebuilt 344 rows of two word-wrapped labels each on every swap (`NoteRow.__init__` ran
1 032 times in one connect), and those 688 labels were what every relayout walked. With
the notes cut to five, the same connect took 0.19 s; with the fixes above, tens of
milliseconds. On top, 59 git subprocesses ran on the GUI thread in that one connect —
`origin_url` from `agent.run`'s and `sync.pull`'s states on every publish, and the sync
module re-asking status and branch of every repository on every `structure_changed`,
including a pasted step's — cheap on Linux and most of a second on macOS.

**Why the fix is the same shape as the view refresh.** The canvas already rebuilt once per
turn through `Debounced`, and the reason it was safe applies to the context verbatim:
nothing a listener does depends on an *intermediate* state, only on the latest, and
`current()` stays synchronous for the one reader that needs the truth right now — the verb
that runs after a publish. Coalescing at the source rather than at the four listeners is
what makes the rule hold for the next gesture somebody writes: a table that publishes
per row costs one fan-out too. The test suite runs the debounce service immediate, so
every existing test stays synchronous and deterministic; a test that asserts coalescing
switches it off and calls `flush_all()`, the pattern the view-refresh tests set.

**Why the selection bug was the same bug.** The canvas selected `[source, target]` so the
Link verb could read the pair from the context — deliberate, and it left two steps
selected, so `selected_step()` was None, the next Connect had no source, and the next
click on a card *selected* it instead of finishing a link. A constructed context is the
sanctioned way to hand a verb a selection (CLAUDE.md: a gesture can be tested by handing
it a `Context` with no widget in sight), and it leaves the user's selection where the
gesture found it, which is what the next `c` needs.

**Why the panel keeps its content.** "Off screen" and "showing nothing" are different
states, and the dock only ever asks for the first. A card bound to a project that is not
on screen costs nothing; a card torn down and rebuilt costs the whole widget tree, twice
per gesture, and throws away every text binding's caret. The step panel already had this
rule in its unchanged-id early return; the project panel now has it too.

**How it stays fixed.** `scripts/measure_scaling.py --scenarios connect,paste` drives
the two gestures over the synthetic library with a step selected and reports, beside
the usual spans, how long the GUI thread was held, how many times the context was
announced and how many times the dock relaid itself — the number to quote before
touching any of this.
`tests/modules/test_project_editor.py` asserts one announcement and no relayout per
connect and per paste in the window's deferred regime, and `tests/modules/test_sync.py`
that a step add asks git nothing.

## The journal: what ran, how long it took, and why it hung

Nothing in the application timed anything, configured logging, or caught a crash. A slot
that raised was logged through Python's last-resort handler and gone; a hang was a story
told afterwards. `core/telemetry.py` is the answer, and three decisions shape it.

**One journal per process, like `logging`.** `Signal.emit` is where a model change turns
into every view's work, synchronously, so it is where that work is measured — and it is
`core/`, with no service to be handed. So there is one `current()` instance: a default
that keeps a ring buffer and writes nothing, which every test sees, and the file-backed
one the entry point installs for both surfaces. The hot path is two `perf_counter` calls
per slot and an append under a lock per span; a slot under `SLOW_MS` is timed and
forgotten. `AppServices.telemetry` is the handle a module reads it through, never a way to
build a second one.

**Two stores, one policy, and failures through logging.** The ring holds the last two
thousand spans of every kind but a quick poll; the JSONL file under `config_dir()/telemetry/`
gets what is worth reading back after the fact — every `failure`, `stall`, `session` and
`cli` span, and anything that took `SLOW_MS` or longer — one `write()` per line, so the
window and a CLI run append to the same file and their rows interleave into one timeline,
which is how an agent lines its `status set` up against the window's `session refresh` a
second later. Failures are not caught at each site: `install()` puts a handler on the root
logger, and every `logger.exception` already in the tree — a raising slot, a failed task, a
refused open — becomes a `failure` span with its traceback and its parent. That handler
would silence the console (a root handler means no last-resort output), so `install()`
adds a stream handler when the root has none. The same fact is what lets the test suite
fail on a slot that raised: a collector on the root logger for the duration of each test,
and an opt-out marker for the two tests that raise in a slot on purpose. It caught its
first bug the day it landed — a callback the appshell still invoked by its old name, which
`Signal.emit` had been swallowing under every test that exercised a tab switch.

**A stall is sampled from another thread, and none of it lives in the builder.**
`framework/diagnostics.py`'s watchdog beats a 100 ms `QTimer` on the GUI thread; a daemon
thread that finds the beat 250 ms late samples the GUI thread's stack through
`sys._current_frames()` — which takes the GIL and snapshots each thread's frame, so a stall
inside C++ is sampled when the GIL is next released and shows the Python frame that made
the call — and opens a `stall` span carrying the sample and whatever spans were open on
that thread: "stall 1.2 s during action steps.delete", with the frames. A modal dialog
runs a nested event loop, so the beat continues through one and a dialog never reads as a
stall. With the crash log open, every beat re-arms `faulthandler.dump_traceback_later`, so
a hang that never releases the GIL still gets its stacks dumped by faulthandler's own C
thread. `sys.excepthook`, `threading.excepthook` and Qt's message handler are chained into
`failure` spans (PySide prints a slot's exception through `PyErr_Print`, which calls the
hook; installing a Qt message handler replaces the default one, so the console line is ours
to print); `faulthandler.enable` writes a native crash's Python stack to `crash.log`
beside the journal; a `session` start and end record bracket a run, so a session with no
end is visible afterwards. All of it starts in `app.main` and nowhere deeper, because a
test build has no event loop for a heartbeat to beat in, and pytest owns the hooks while
a test runs — the builder installing any of it would read as one long stall or bypass the
suite's own capture.

The readers are deliberately two: *Debug ▸ Telemetry* polls the ring once a second while
it is current (spans arrive from worker threads and the watchdog's thread, so polling is
what keeps every widget touch on the GUI thread), and `dplanner telemetry show` reads the
file — `--slow 50` for what took long, `--failures` for tracebacks and the crash log's tail,
`--json` for an agent. The generated skill points an agent at it before it reports a hang.

## A report is a publication, not a record

People with a stake in a project but no DPlanner — a sponsor, a product owner, a tester, a
colleague glancing at status — had nothing to look at. The answer is one HTML file per
project that reads like a page and needs no server: the graph as the window draws it, the
order, the time estimates, every step with everything the modules know about it, and a
last section that says what DPlanner is and how to open the plan. `CLAUDE.md` has the rule
in its short form (*A report is a publication, not a record*); this is why it is shaped
the way it is.

**Modules say, one renderer shows.** A report is a question about *every* feature at once,
and no module may import another, so no module can draw the page. The split that keeps
the layering honest: each participating module exports a Qt-free `report.py` with
`report_source()` — the `asset_source()` / `lint_checks()` shape — returning parts from a
small vocabulary (`cli/report/parts.py`: figures, tables, chart series, timeline spans,
prose, the graph, and per-step *facets*); the composition root assembles the tuple
(`_report_sources`); `cli/report/assemble.py` merges it into one `Report`; `page.py`
draws that, knowing only the vocabulary. The alternative — modules emitting their own
HTML — was rejected because it fragments one design system across a page and gives the
PDF and the spreadsheets nothing to read. The vocabulary lives under `cli/` for the reason
lint does: it is the highest layer that is still Qt-free and reachable from both surfaces.
`dplanner report html` and File ▸ Export write byte-identical pages from it.

**Drill-down is a shared key, not a shared import.** Every part about a step carries the
step's id, and the page keeps one selection — the window's one-context rule, rebuilt in
the browser. Clicking a card, a row, a milestone's hairline or a timeline bar highlights
the step everywhere and opens a drawer listing every module's facets for it. The graph
never learns about estimates; both key by id.

**Every part is plain data, and that is what makes the worker safe.** A contribution holds
strings, dates, floats and bytes — never a `Step`. The window builds the report on the GUI
thread (the read of the model) and renders and writes it on a worker the task centre
shows; the CLI does both inline. Plain data is also what makes the output deterministic:
the same plan gives the same bytes, and the "generated" stamp is a day, so an unchanged
plan re-renders to an unchanged file. A test walks every contribution to hold the line.
Measured on a synthetic plan: 300 steps read in ~90 ms on the GUI thread and render in
~17 ms; 1,000 steps read in ~580 ms and render in ~50 ms. The read is the cost, and it is
the same read the Time tab makes on its 500 ms debounce.

**Save publishes before it commits.** The sync module asks the reporting module for a
*publication* per dirty repository before its save task starts — the model is read then,
on the GUI thread — and runs it inside the task, before `commit(message, also=paths)`, so
the site lands in the same version as the plan and is never one commit behind. `also` is
on the storage *protocol* (`VersionedStorage.commit`) because the sync module may not name
`GitStorage`. The dirty count and the review diff stay scoped to the plan: a stale site is
never unsaved work, and a publication that raises is logged and the plan saved without it
— a report is never a reason to lose a save. The switch is per user and on by default.

**The site's index is a function of the project set, never of any project's state.** Under
`reports/` each project owns its own directory (`<slug>/index.html`, `<slug>/summary.js`);
`index.html` is rendered from the sorted set of `*/summary.js` present on disk as a static
page with one `<script src>` per project and a few lines of client-side rendering —
`<script src>` works from `file://` and GitHub Pages alike, where `fetch()` does not. Its
bytes change only when a project joins or leaves, so two people saving two projects in one
shared plan repository never both touch it, and a pull that brings a colleague's project
is picked up by the next run. The directory name is a constant, not a setting: the
window's preferences are QSettings, which `dplanner report site` cannot read, and a
per-user name would let the two surfaces write two sites into one repository.

**Paper is the same report, not a second one.** The PDF is `QTextDocument` printing to
`QPdfWriter` — pagination for free — with the chart, timeline and graph rendered from the
very SVG strings the page inlines, through `QSvgRenderer`. It is window-only by decision:
PySide6-Essentials has this and no Chromium, and adding a PDF library for the CLI was
judged against the dependency rule; the page carries print CSS for anyone at a terminal.
The XLSX writer and the markdown renderer are stdlib for the same rule (`core/xlsx.py`,
`core/markdown.py`, in the spirit of `core/png.py`).

## A theme is provided, never listed

`theme/themes.py` used to be the list: the three house themes and a hand-copied set of
Omarchy's, chosen from a flat View menu, and nothing followed the desktop. Now a **theme
provider** offers themes, and the application asks its providers rather than a table.

**The contract is a record of callables** (`theme/providers.py`), the shape
`domain/agents.py` set for an agent harness: an `id` the persisted choice carries, a
`label` the settings page shows, `refusal()` — why it does not apply on this machine, None
when it does — `groups()`, the themes it offers in the lists the Theme menu shows them as,
and for a provider that follows the desktop, `current()`. **Capabilities are derived,
never declared**: a provider follows the desktop exactly when it has a `current`. It lives
in `theme/` because it names `Theme`, which `domain/` may not import; `theme/` is a leaf
every layer above may read (`tests/test_architecture.py`, rule 9), and importing the
package loads no Qt — the Qt half is imported inside `apply_theme` — so a provider module
reads it without a graphics stack, which is what lets its file be a `HEADLESS_FILES` name.
The built-in provider is the fallback every build has: the house themes and every theme
Omarchy ships. `modules/theme_omarchy/` and `modules/theme_system/` each export one from a
Qt-free `themes.py` and have no window half, like the harness modules; the root's
`theme_providers()` is the tuple, built **once** in `app.main` and handed to both the
startup apply and the session, so every later reader takes it from `ThemeService`.

**Anchors from `colors.toml`, ramps derived.** Omarchy's file is a terminal palette, and
its own shades are not the ramp a window needs — `solitude` ships a `lighter_background`
equal to its `background`, and `catppuccin-latte`'s "lighter" one is darker than its base.
So `theme/omarchy.py::theme_from_colors` takes exactly the anchors a person tunes —
background, foreground, accent, the selection pair, blue and magenta for the links, the
mode — and derives every surface, border and secondary text with the proportions the
hand-tuned house themes use, which is what the contrast invariants in `tests/test_theme.py`
prove for all twenty-five at once. The selection pair is Omarchy's own (`selection` with
`bright_foreground`, as its terminals show), so the generated themes changed the selection
colour of sixteen hand-copied ones; the ANSI hues reach a `Theme` only as its links,
because status tints are constant tones by design (DESIGN.md's exception #2). The built-in
table (`theme/omarchy_themes.py`) is generated by `scripts/import_omarchy_themes.py` from
`$OMARCHY_PATH/themes` and holds the files' values, not themes: the mapping is code, so it
changes without regenerating, and a test reproduces the committed file byte for byte where
Omarchy is installed. The mapper raises on a missing anchor; tolerance lives in the reader,
because that is where the mid-switch window is.

**The persisted choice names the provider, and "system" names none on purpose.**
`appearance/theme` is `"system"`, or `"<provider id>/<theme name>"`; a bare name from
before providers existed reads as the built-in's, so no migration pass was needed.
`"system"` means *this machine's* desktop, served by the first following provider in the
root's order that applies here, so a profile keeps following when the desktop under it
changes — and **absence means system**: a fresh install picks the right variant for its
desktop by itself, and falls back to the built-in default where nothing follows. A choice
naming nothing here resolves to the default for this run and is never written back; only
`set_theme` writes, so a profile carried to another machine is still itself when it comes
home. What is honoured is a field on the service (`effective_choice`), so a check mark
costs two strings and no state callback ever reads a file.

**The service polls; providers stay Qt-free.** `ThemeService` re-reads the serving
provider's `current()` on a `QTimer` at the workspace watcher's cadence, only while a
following provider serves the choice, and applies on `!=` — never `is`, since a provider
rebuilds its `Theme` on every read, and an identity check re-applied a whole style on
every tick. One mechanism for every following provider: a `QFileSystemWatcher` on
Omarchy's theme directory would die with it (`omarchy-theme-set` removes and replaces it,
then writes `theme.name` in place), and Qt's `colorSchemeChanged` would hear the
application's own writes. A read that lands mid-switch answers None and the service keeps
what it has; a tomllib parse of a 600-byte file every two seconds is fifty microseconds.

**Following means no colour-scheme override.** Qt answers `colorScheme()` with the
application's own override once `setColorScheme` has run — `Unknown` does not clear it,
`unsetColorScheme()` does — so a desktop provider would read an echo. `apply_theme(...,
follow_system=True)` therefore clears the override, `set_theme("system")` clears it
*before* it asks, and availability is judged on the reading taken in `theme_providers()`,
before any theme is applied. Wherever following happens the desktop and the theme agree
by construction — Omarchy sets GNOME's scheme to its theme's mode on every switch, and the
desktop provider's polarity *is* the OS's — so the title bar never disagrees with the
window. A fixed theme sets the override to its polarity, as before.

**The menu entries are specs, and a child menu may nest.** Every theme is an
`ActionSpec` rather than a row of a `DataMenuSpec`, against the rule for data-driven
child menus and on purpose: the command palette lists a spec and never a data row, and
*Tokyo Night* one keystroke away is worth more than a list that refreshes while the window
runs — a theme added under `~/.config/omarchy/themes` meanwhile appears at the next start.
Long lists sit one level down: `submenu` accepts a path (`"Theme ▸ Omarchy"`), and both
presenters walk it, creating each level at the first spec's position — the bar computes a
nested child's visibility before its parent's, and the popup's group bookkeeping is per
container. View's `theme_system` and `theme` groups both feed the Theme child menu, so the
rule between *System theme* and the picked themes is drawn inside it. A provider that
does not apply here, or that the person switched off, contributes no entries: absent from
this machine is the one case *hidden* is for. `modules/appearance/` owns View ▸ Theme and
Settings ▸ Appearance, where every provider is a switch with its capabilities under it —
and its reason, greyed, where it does not apply — except the built-in, which is a line,
since a switch that cannot be turned off teaches nothing.

