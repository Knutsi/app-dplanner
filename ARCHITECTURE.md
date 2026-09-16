# DPlanner's shape, and why

`CLAUDE.md` and its area files under `.claude/rules/` carry these rules in their short,
imperative form — this file is where the reasoning lives, so the short form does not have to
be taken on faith.

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
is something Ctrl+Z could honestly reverse, so File ▸ New Project, Open Project and Remove
from Library apply their model change directly with their own origin — the same discipline
as syncing an external fact, below. The membership verbs live with the project verbs
(`modules/projects/`): New Project is the Project dialog in create mode and Open Project is
a wizard over the two ways in, and all of them start from the same question — *which plan
repository?* — answered by one picker. The library module keeps only the question of
*which library*.

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

### A checklist is a registry of probes, and every module owns its own

The three pieces above are not all a machine needs. DPlanner also wants git, the GitHub CLI
and a session on it, an agent CLI, a terminal to open one in, the OS keychain, a reachable
internet — and each of those was discovered at the moment it failed, by whichever feature
tripped over it first: a greyed verb here, a `QMessageBox` at launch there, and nothing
anywhere that answered *is this machine set up*. An agent could not verify a machine at all.

Whether a machine is ready is a fact about **every** feature at once, so it is `cli/lint.py`'s
problem again and it gets `cli/lint.py`'s answer. `cli/checklist.py` owns the shapes
(`MachineCheck`, `Reading`, `Remedy`), the group order, the report and the exit code; each
owning module exports `checks()` from its own Qt-free `checks.py`; and the composition root's
`_machine_checks()` assembles the tuple that *Tools ▸ Setup Checklist…* and `dplanner
checklist show` both read. A module names the fact it owns and the words for it; nothing
imports anything.

Five decisions carry it.

- **A probe answers two states, and the tone is derived.** `Reading` is `ok` and the words —
  not a five-valued state of its own. What the row *looks* like falls out of `required`: a
  failing required check is the error tone, a failing recommendation is information, an
  unanswered one is busy, and a well one is ok. Those are exactly `framework/signalling`'s
  four tones, so the checklist added none and DESIGN.md's *Signalling* did not change. It
  also stops the vocabulary lying: a stale skill is not "missing", and only the probe's own
  words know which it is.
- **`required` means two things, and they are the same thing.** The verb exits 1 while a
  required check fails — `install status` exits 0 whatever it finds, deliberately, so this is
  the verb that fails a machine — and a required check is the only kind probed at start. That
  is what keeps a launch honest: git's `which` and one `git --version`, plus the installer's
  reader, which runs no subprocess at all. No network request, no `gh auth status`, no `az`.
  Anything that cannot be afforded at every start is, by that fact, advice.
- **A remedy names an action id, not a widget.** A `Remedy` is words, optionally a command to
  type, optionally the id of a registered action. The modal runs that id through
  `ActionRegistry.run` and the terminal prints the command — so the install module offers
  *its own* dialog as the fix for its own three rows without the checklist importing it, and
  a module that grows a fix later needs no change here. It is the aspect bar's seam, one
  layer out.
- **The count in the menu entry is read, never probed.** *Tools ▸ Setup Checklist (2)…* comes
  from the last sweep the module kept; the module calls `context.refresh()` when a new one
  lands. A state callback runs on every context change and may not shell out — the same rule
  `origin_url`'s memoisation keeps.
- **The machine is greeted once, and after that only when asked.** The modal opens on a
  machine DPlanner has never met, whatever it has, because a setup surface nobody ever sees
  working is one nobody trusts; afterwards it opens only while the person left *"open this at
  start"* ticked **and** something required is missing. Everything else is said where it
  bites. That is what retired `github/notice.py`: DESIGN.md had already ruled that box out
  ("A machine without gh. No modal at launch"), and this is where those facts live now.

Three things the surface itself settled, after the first pass was seen.

**It is the one dialog that prints a heading.** Every other dialog in the application
starts at its content, because a gesture opened it and that gesture already said what it
is. This one can arrive unasked — at a first start, or when something required has gone
missing since — and a window somebody did not summon is the only one whose name they were
never told. `DialogFrame.set_heading` exists for that case and says so, and the rule is the
test: a dialog a menu entry opened must not call it.

**A remedy may name packages instead of a command**, and `install_line` turns them into the
line *this* machine would actually run: `yay -S github-cli` on an Arch box, `sudo apt
install gh` on Ubuntu, `brew install gh` on a Mac. Two small tables do it — `MANAGERS`, one
line per package manager, and `FAMILIES`, one entry per distribution family naming the
managers to try — and a manager is only offered when it is **on PATH**, because suggesting
`brew install` on a Mac without Homebrew is a second thing to go and install, said as if it
were the answer. The family comes from `/etc/os-release`'s `ID` and then its `ID_LIKE`,
which is why **a derivative needs no row of its own and must not get one**: Omarchy says
`ID_LIKE=arch` and is an Arch machine for this purpose, as every Ubuntu spin is a Debian
one. (Omarchy's own `omarchy-pkg-install` is an interactive picker, not a line to paste, so
it is deliberately absent from `MANAGERS`.) A check that cannot name a line it is *sure* of
names none and carries a `url` instead — `azure-cli` is a Microsoft repository or an install
script on most distributions, and `apt install azure-cli` on a stock machine simply fails. A
wrong install command is worse than a link.

**Muting changes what nags, never what is true.** A row's `⋮` carries *Don't warn me about
this again*, kept per user by id. The row still shows and still says what it found; what
muting takes away is the error tone, the footer's count, the count in the menu entry, and —
since a start-up sweep exists only to decide whether to speak — the probe itself. The CLI
never reads it: `dplanner checklist show` is the machine's truth, and an agent gating a
handover on it must not inherit somebody's decision to live with a gap. That is the same
split as *Where the user left off is remembered by key*: a preference is the person's, and
the plan — here, the machine — is not.

One thing had to move to make it possible. A file named in `HEADLESS_FILES` may import
`core/`, `domain/` and `cli/` and **not** `framework/`, and `cli/` may not import `framework/`
at all — so with the keychain wrapper under `framework/`, neither the verb nor any module's
`checks.py` could ask whether this machine can keep a credential. `secrets_store.py` is pure
stdlib and `keyring`; it is now `core/secrets.py`, for the reason `core/config_dir.py` gives
in its own docstring — the GUI keeps preferences in QSettings, and anything the headless
surfaces must also read cannot. `NOTES-FOR-APPFRAME.md` carries it as a divergence.

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

They are a top-level **Graph** menu now, in four groups: `arrange` (the Sort, Layout and
Divide child menus — moving cards, from the wholesale to one cut at a time), `regions`,
`look` (what is drawn without moving anything) and `panels` (what stands *beside* the
canvas inside the tab). View went back to being about the window — which is what decides
where the Features panel's switch sits: the panel is inside one project's tab, so it is
the graph's chrome and not the window's, and View ▸ Panels is about the areas around the
tabs.

**What did *not* move is the point of the split.** Connect, Link, Unlink, Isolate and the
Redirect pair stayed on **Step**, because a link is a fact about the steps it joins, and
because the canvas's right-click renders the Step menu (*A right-click renders a menu, never
a copy of one*) — moving them would have taken the graph's most-used verbs off the graph's
own context menu to file them more tidily. Lasso stayed in Step's `navigate` group for the
same reason: it selects steps. The test is not "which surface does this run on" — every one
of these runs on the canvas — but "what is it about": a step, or the drawing of them.

### A strip of verbs is cut into bands, and a band folds whole

The canvas strip carried nine words and eleven glyphs in six unlabelled groups, and read
as a sentence rather than as a tool palette. DESIGN.md's *Toolbars* had already said what a
strip of verbs is — a glyph with its words in the tooltip — and named this conversion as
owed: the strip was built on `ActionToolbar`, the presenter that predates the `Toolbar`
primitive and has no overflow of its own.

**The band is the structure a toolbar has, so it is named.** Nineteen glyphs in a row are
nineteen riddles; *Go · Step · Link · Arrange · History · Options* is a thing to learn
once, and the name under a band is structure rather than an explainer — it says what the
glyphs above it are *for*, where a word on each button would repeat the tooltip. The bands
are spelled out in `canvas_toolbar.py` rather than inferred from the menus, where these
verbs sit under four different headings: what a person reaches for together is not what a
menu bar files together.

**And the band is the unit that folds.** A canvas can always be dragged narrower than its
own strip. The old answer was Qt's `»`, which pops the hidden buttons up as glyphs again —
no help at all to somebody who could not read the glyph on the strip. The primitive takes
a whole band off from the right and lists it in the `…` menu as glyph **and** words, with a
rule where each band begins: half a band on the strip and half in a menu says less than
either, because the bands are how the strip is read.

**A band's buttons are squares, and only a band's.** A palette is a grid of targets of one
size, and a square is also what puts a glyph in the middle of its button rather than a few
pixels left of centre. It is the *banded* strip that gets it, not every dense one: the
aspect bar seats ten toggles in a 360 px dock, and squaring them costs it two — which for a
row that answers "what does this step carry" is the row not answering. The two strips want
opposite things from the same primitive, so the property says which.

**And a control that is not a verb goes in the band it is about.** The layout picker names
the arrangement the canvas is showing, so it sits at the end of *Arrange*, added as a
widget — which never enters the `…` menu and hides when there is no room, the way a filter
does. It stood *outside* the strip while the strip was one undifferentiated row and the
rule was "it must survive every width"; beside a row of named bands a lone worded button
past the end read as something that had fallen off, and the band it belongs to says what it
is better than its own isolation did.

**The glyphs come from the specs.** Every verb on the strip carries `ActionSpec.icon` now,
which is what let the module's own `ICONS` table — and the `_WORDED` map beside it — be
deleted rather than extended. A module that adds a verb to the strip adds its glyph where
the verb is registered, and the strip learns nothing.

**A checked glyph takes `$ON_ACCENT`.** The standing reason the mode switches and the marks
were *words* was that a checked button is filled with the accent and a glyph painted in the
quiet tone vanishes into it. The fix belongs in the primitive, not in an exception per
surface: `Toolbar` re-inks a verb's glyph on its toggle, taking the ink from the palette's
`BrightText`, which `theme/palette.py` now carries the theme's `on_accent` in (it held
`accent_hover`, which nothing ever read). A painter has no stylesheet, and the palette is
the only way it can learn a colour the stylesheet writes.

**The marks became a face.** Six worded switches on a strip of glyphs was a row half words,
and *how the graph is drawn* is a question asked rarely and answered best in a menu, where
each choice says what it means. *Options* is one glyph dropping the Graph menu's `look`
band — rendered through `fill_menu`'s new `group` filter, so it is the menu and never a
copy of it, and a mark added later appears under it having touched nothing. It is a face
and not a verb with an arrow: there is no verb under it, so it wears the layout picker's
look rather than the hairline that says two halves do different things.

### The glyphs are somebody else's, and they are copied in

Forty-odd hand-painted `QPainter` calls was the right answer at a handful and the wrong one
at forty: the strokes drifted between glyphs, nobody could draw a new one to match, and the
result was, in the developer's words, "ok, but not super nice". They are **Tabler Icons**
(MIT) now — the set is the largest permissive one, which matters because this application
needs glyphs a small set does not have: redirect to and from, isolate, divide, three kinds
of mark.

**Copied in, not depended on.** Fifty-two SVG files come to 212 KB, against a dependency
that would bring a package, a version to resolve and a release cadence to follow — and the
full set is over six thousand files, which no repository wants in order to use fifty.
`scripts/vendor_tabler_icons.py` holds the mapping from *what a glyph means here* to the
Tabler icon that says it, so the key is ours and outlives any set: changing icon sets is
changing that file's right-hand column and running it again. The tag is pinned in
`theme/icons.py`, because the application is what has to state the version — in Help ▸
About, which an MIT notice and a bug report both want.

**One painter, and the alpha is the painter's.** Qt's SVG renderer knows no
`currentColor`, so the ink is substituted into the source before rendering — the trick
`drop_arrow_url` already plays for the combo arrow — and the colour's *alpha* becomes the
painter's opacity, because an SVG stroke colour has none. A strip's glyphs are the text
colour at `SECONDARY_ALPHA`, so a painter that dropped the alpha would make every toolbar
in the application read a shade too loud. The canvas's medallions go through the same
`paint_glyph`, which is what retired the five `paint_*_glyph` functions and the if/elif
chain that chose between them: the kind *is* the glyph's name.

**What stayed hand-painted is what is a picture of state rather than of a thing**: the key
badge draws text, the colour strip is a gradient, the spinner is a frame per angle, and the
filter funnel is two states drawn to one width. No icon set has those, because they are not
icons.

### An acknowledgement is asked, not written

Help ▸ About was a `QMessageBox.about` naming the template's product, which is two faults in
one line: a platform dialog where every other surface is a `DialogFrame`, and a name nobody
had looked at since the fork. What replaced it answers the question a licence page is for.

**The list of components is ours; every fact beside it is the installation's.** A package
cannot say what it *does here* — "the OS keychain a source's token is kept in" is a sentence
about this application — so that line is written. The version and the licence are read from
`importlib.metadata`, in the order the answers got vaguer: `License-Expression` (an SPDX
expression, and the one to believe), then the free-text `License`, then the trove
classifiers, which say *MIT License* where the package itself says *MIT*. Asked the other
way round, two components under one licence read as two different ones.

A hand-kept licence table is a table that drifts, and the one thing an acknowledgement must
not do is claim the wrong licence: a dependency bumped to a version under different terms
would go on saying the old ones. And a component this build does not have — an optional
one, a source checkout missing a wheel — says so in its row rather than vanishing from the
list, because an acknowledgement that quietly shortens is worse than one that admits a gap.

### One picker, two lists

*Find Step…* wanted what the command palette already was: a field over rich rows, ranked by
what was typed, one pick. The palette's constructor had the registry and the context wired
into it, so the honest move was to lift the shape out — `framework/picker.py`'s
`PickerDialog` over plain `PickerRow`s — and rebuild the palette on it as the half that
knows what a verb is. A third picker is a list of rows, not a third dialog.

**A label match always wins.** A row is searched by its name first and by what it *also*
answers to second — the menu path for a verb, the key for a step — so a verb actually
called what was typed is never pushed under one merely filed there. `also` is deliberately
separate from what the row *shows*: a palette row's shortcut sits at its right, and folding
that into the haystack would make "ctrl" match every verb that has one.

**A picker over a long list opens on its landmarks.** Three hundred steps is not a list
anybody scrolls, so `PickerRow.landmark` says which rows are worth showing before anything
is typed: Find opens on the plan's milestones and features, and everything is in play
from the first keystroke. A list with no landmarks opens whole, which is what the palette
wants. One field on the row, and the rule is the same both ways.

**Landing is centring.** `steps.reveal` opened the project's tab and called `setSelected`,
which selects a step that may be a screen away — a reveal that reveals nothing. The canvas
grew `GraphView.centre_on_step`, and `ProjectActivity.select_step` calls it, so every view
that reaches a step through the registry — the order table, the progression board, the
Agents browser, `feature.reveal` — now lands on it. The zoom is untouched: Frame is the
verb that changes how much of the graph is in view, and a jump that also zoomed would lose
the scale somebody had chosen to work at.

### The Problems list lives in the graph, not in the window

What is wrong with a plan is fixed on the graph: you click a problem and the canvas moves
to the step it is about. So the panel stands inside the project tab, beside the canvas,
where that trip is a short one. (It took the slot the Features panel had, which went with
the feature catalogue — *A feature is a step*.)

**What it shows is the lint registry, not a second one.** `cli/lint.py` already owns the
shapes and every module already exports `lint_checks()` from its own Qt-free `cli.py`; the
composition root's `_lint_checks()` assembles them once and hands the same tuple to
`dplanner project lint` and to `ProblemsDeps.checks`. That is `_machine_checks`'s
arrangement exactly, and it is what makes the window and the terminal unable to disagree
about what is wrong with a plan. A second registry would have been the entropy: a gap in a
plan is one fact whoever is asking.

**The count on the strip is a reading, and a reading is read, never computed.** The panel
is built with the tab whether or not the frame is shown, so it keeps answering while it is
hidden, and the button beside the canvas reads the last answer. No action state ever runs a
lint pass — the checklist's rule, and the reason its own count sits in a menu label. The
panel says the reading through a `ReadingPanel`, one string and a signal, so
`project_editor` never learns what is being counted; that is also why the button is a
widget where every other seat on the strip is an action, since a `Toolbar` renders a verb
as a glyph with its words in the tooltip and a count has to be seen.

**A run that fixes a plan has no step, and is not recorded.** The panel hands its findings
to the agent module through two plain-data callbacks the root wires (the
`LibraryWatchDeps.hand_to_agent` arrangement); the launch has no worktree and opens in the
*plan's* own repository, because that agent changes the plan and not the code. `AgentRun`
is keyed by the step it is working on, so a plan-wide run gets no chip, no end-of-shell
watch and no usage row. That is a gap said out loud rather than a zero invented.

**A panel inside a tab is not a dock panel**, and the difference is which question it
follows. A dock panel follows *the window* — one instance, retargeted by the context on
every change (*Where a panel goes*). A panel inside a tab follows *that tab*: there is one
per project tab, and each is handed a context naming its own project, so a tab in the
background never follows the tab in front. That is the same rule as "only the active pane
speaks for the user", read from the other side.

**The seam belongs to the splitter and the module never learns whose widget it is.** The
canvas and the panel meet in a `QSplitter`, so the line between them is the one every
splitter in the application wears and the panel draws no edge of its own. What goes in it
is named by the composition root as a `SidePanel` — a title, a glyph and a way to build the
widget — and reached through `framework/panels.py`'s existing `ContextPanel` protocol,
which the features list already satisfied structurally. `project_editor` imports nothing
from `feature`; `feature` registers no panel and offers a `create_panel()` instead, the
arrangement `step_properties` already uses for the step panel.

**Whether it stands is a preference, so it is a field on `Look`.** The marks, the
spotlight, the ground and the snapping are one value kept per user and fanned to every
canvas; a panel beside the canvas says no more about the plan than a grid does, and the
plumbing — a key, a setter, a fan-out, a context refresh so the switch re-reads itself —
already exists. A second copy of it for one boolean is what `look.py` was written to
prevent.

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
rebuild is owed. Debug ▸ Design Examples is that, a page at a time over sample data,
and `docs/screenshots/f1-design-example/` keeps them rendered so a pull request can show the difference
it made. Every later step that touches a surface points at them; DESIGN.md's *Bringing a
surface up* is the list of what to compare.

**The dialogs pass put every dialog-shaped surface on the frame, and three rules came out
of it** (`.claude/rules/shell-ui.md` states them; the renders are `docs/screenshots/s16-dialogs/`).
**A settings page owns no outer margin.** Nine pages carried 20, 12 or no margin inside a
dialog that added its own, so no two pages started their first caption at the same x, and
one page was taller than the window with nothing to scroll it. The dialog is what knows
where its seam falls and how tall it is, so it insets and scrolls; a page is
`settings_page()` and `block()`s — the design example's form, which the pages would
otherwise hand-write fifteen times, getting the layout-item rule (a child layout joins its
parent before it is filled) wrong in one of them. **What a gesture came to after its dialog
closed is a `notice()`.** A dozen `QMessageBox.warning` and `.information` calls reported a
failed creation, a publish, the caveats of a move — each with a platform icon and the
platform's arrangement of its words, the second design `confirm()` was written to retire
for questions. A state the dialog is still showing is never one: a clone running, a
refusal, a copied path go in its footer's status slot, where the person is looking, and a
move that succeeded is recorded once, in the status bar. **A verb in a dialog's body is
`quiet()`.** The per-dialog list existed to give body and footer buttons one look, and the
tempting replacement, `#DialogBody QPushButton`, is specificity (1,0,1): it would outrank
every id-only button rule inside a body — the step panel's own buttons inside Step Details
among them — which is exactly the trap that grew the list. A property selector,
`QPushButton[quiet="true"]`, is (0,1,1): it gives a body verb the footer's look and loses to
any rule that names its widget, so `QPushButton#PrimaryButton` still wins and a quiet verb
restyled as the primary takes the accent. `GlyphButton` is quiet already, for a verb whose
glyph has to follow the theme on a page that outlives it.

**A dialog on screen never resizes itself.** The Open Project wizard first sized itself
per page — two rows for the chooser, room for a list after it — and on Hyprland the page
after the chooser drew clipped, its footer outside the window, until focus moved. On
Wayland the compositor owns a window's geometry: a client's resize of a shown window is a
request it takes up at its next configure, so Qt lays the new page out at the new size
while the surface stays at the old one. X11, Windows, macOS and the offscreen renders all
apply the resize at once, which is why nothing but a real session showed it. So a dialog's
size is `DialogFrame`'s `size=` and nothing later, and a wizard's pages share one — a short
page sits at the top of the room its longer siblings need.

## A roster has three shapes: a table sets values in the row, a list stays a list, a well keeps its widgets

`.claude/rules/shell-ui.md` has the rule; this is why. The tables-and-browsers pass (S15) took the last
hand-laid rosters onto the primitives, and each of them turned out to be one of three shapes.

**A value set in a table's row belongs to the column, not to a widget in the cell.** The
bulk Estimates tab planted a spin box and nine buttons in every row with `setCellWidget`, and
the Time tab laid its milestone rows out by hand, measuring strings. A widget in a cell
swallows the row's hover and pick, forces a height the font does not give, and costs a
widget tree per row — a plan of four hundred steps is four thousand buttons rebuilt on every
settled change. So a `Column` carries the editing: an `editor` (`NumberEditor`,
`DateEditor`) that Qt's delegate opens over the cell, and `chips` the delegate paints and
hit-tests from one layout, so what is clicked is what was drawn. A commit is announced once
through `Table.edited` and the host pushes its command. Two traps came with it: a fresh
`QTableWidgetItem` is editable by default, and the announcement runs inside Qt's
`commitData` — or inside the click — so a host may write a cell in its slot but must never
rebuild the table there.

**The chips are the Estimates tab's reason to exist.** The pass first made the estimate a
number typed into the cell, with the sizes as Step ▸ Estimate verbs. It read well and lost
the page's most valuable property, which the person using it named at once: one size lit on
every row, down every row, is a grid in which the small, the large and the unsized steps are
seen before a number is read. The chips came back, painted rather than planted. Zero stands
past a hairline because adding no time is a claim, not a size. The last chip opens the
editor and wears any value off the scale, because a four-day step lighting nothing would
read as unsized. The unit moved into the header, once, because it was being printed on
every chip.

**A roster whose rows carry verbs and outlive a tick is a well, not a table.** The task
browser and the Agents browser were one layout written twice. Their rows carry *Cancel*,
*Show Terminal*, *Reveal* and a dismiss, and the task centre refreshes every 250 ms: a row
rebuilt on a tick loses the button being pressed. `RowWell.reconcile(keys, build, update)`
keeps a row per key and updates it in place. A task's indeterminate bar became a busy
`StatusLine`, the rule every other surface already follows: an unknown fraction is busy.

**A list stays a list.** Standing note N28 said every `#OrderTable` borrower moves onto
`Table`, and DESIGN.md says a list when there is one column of things. The implementation
notes log is one column of things, and a one-column table would add a header nobody reads,
so it moved onto `RichList` instead: the table's well, hover and picked edge, on the
two-line delegate. The step panel's test roster compares an id, a name and a result down a
column, so it became a small `Table`.

**A strip has to remember what its host took off.** `Toolbar._reflow` set every item's
visibility from the room alone, so a control a view hid came back on the next resize — the
Documentation view's *Group by* had been doing it unnoticed. `set_shown` is the host's
statement, and the reflow counts only what is shown. Three surfaces in the pass needed it.

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

## A markdown toolbar is verbs over a selection, and one splice each

Every prose document here is markdown kept as plain text, which is the right trade for
the binding (*A pasted image is an attachment and a link*) and leaves the marks themselves
to be typed. Most are two characters and nobody minds. The ones people stop writing rather
than type are the ones that are tedious in proportion to what they mark: `**` around a
phrase already selected, a `- ` down eleven lines, a table's pipes and dashes. So those
become verbs, and `framework/markdown_toolbar.py` is the strip.

**Dense and un-banded**, against DESIGN.md's own mapping of a tool palette to
`Toolbar.add_group`. The measurement decided it: a banded strip's buttons are squares, so
twelve verbs in three bands come to roughly 450 px, and every `ProseSection` in the
application lives in a ~360 px dock — *Insert* would have folded into the `…` on every
surface, and often *Blocks* too. Dense seats them in about 330. It is the aspect bar's
argument with the same numbers: a strip that answers a question about the thing on screen
stops answering it when it folds, and a formatting palette that is never all there is not
a palette.

**A verb is one splice, and that is not a detail.** Qt reports `contentsChange` per edit
*block*, so two operations inside a `beginEditBlock` collapse into a single signal naming
the whole document — measured at `(0, 23, 26)` where one contiguous replacement reported
`(12, 6, 10)`. A `TextBinding` host would push an `EditTextCommand` carrying the entire
document twice for a bold. So every verb is a pure `Splice` — start, end, replacing text,
and what to leave selected — applied in one `insertText`, sealed either side the way
`ProseEdit._embed` seals a pasted link.

**Where the selection lands is the design**, and it is one rule: a verb leaves selected
whatever a second press of the same verb would act on. Bold leaves the bolded words, so
pressing it again unwraps them; Heading 2 leaves the lines; Link leaves `url`, because
typing the address is what you do next and a prompt for it is more ceremony than the two
brackets it saves. With nothing selected a wrap puts the caret between its fences, so
Ctrl+B and then typing works the way it does everywhere else.

**The keys belong to the editor, not the strip.** `Toolbar.add_verb` gained `keys=`
beside `shortcut=`: the first only prints the key in the tooltip, the second claims it.
A strip lives in a window, so a `QAction` shortcut on it fires wherever that window has
focus — the same fact as *A canvas key names action ids; it is never an
`ActionSpec.shortcut`*, from the other side. The verbs' keys are `QShortcut`s on the
editor at `WidgetShortcut`, which is what the spec editor was already doing for Ctrl+B
before any of this.

`ProseSection` builds one unconditionally rather than behind a flag. It is what a prose
editor *is* here, the same way the highlighter and the expand button are; a flag would be
a decision every host had to make again, and none of them has a reason to answer it
differently. The microphone arrives the same way — with the strip, wherever a host hands
the strip a `DictationService` (*Dictation is a provider, and capture is a peer process*).

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
way out, and a rule written for them now would be one more thing to retire. **The generated
skill no longer names their verbs either** — the five carry `in_skill=False`, and the
preamble's three lines telling an agent not to draw one went with them, since a skill that
does not offer something need not forbid it. That is not the same act as deleting the verbs:
the canvas still draws what a plan already has, and removing a verb an older script calls is
a decision somebody should make on purpose rather than as a side effect of tidying a
document.

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

*Mark Starts* and *Mark Ends* colour a node's unconnected sockets. Three decisions sit
behind two short functions — a third mark, *Orphans*, is covered at the end of this
section by the thing that replaced it.

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

There was a third mark, and it is gone. The orphan's ring was the refusal red at full
strength round a node nothing touched: the socket discs say *this is where the graph ends*,
which is often correct, while a ring said *nothing touches this at all*, which almost never
is. What retired it is the squiggle below — `graph.orphan` is a lint check like any other,
so the general mark covers the case the ring was invented for, and covers it better,
because the Problems panel then says *which* thing is wrong. A stored `orphans` is ignored
rather than refused, which is `from_json`'s tolerance doing its job.

### A problem is a squiggle, and the reading is shared

A plan can be wrong about a step — no description, no estimate, a dangling `requires`, a
feature nothing gathers — and until now the canvas could not say so. The Problems panel
lists every finding, but it is a panel: you have to be looking at it. The mark that says
*look here* without saying more is the squiggle every code editor draws under a line it
cannot make sense of, and it is the right shape for exactly the reason it is in editors:
it points, and something else explains.

**It stands for every check, which is what made it worth replacing the ring with.** The
canvas had one red mark already and it could only ever mean *orphan*; two reds a pixel
apart for "this step has a problem" and "this step has *that* problem" is the confusion
the seam rule exists to prevent. One mark, every check, and the panel for the rest.

**The canvas never learns what a problem is.** `NodeAccent.flagged` is a boolean the
composition root sets, the same translation every other accent gets — the editor does not
know what lint is, any more than it knows what a milestone is.

**Nothing runs lint on a canvas sync.** This is the load-bearing constraint, and it was
measured before anything was designed around it: the checks are super-linear in the size of
a plan — 1 ms at 40 steps, 9 ms at 120, **66 ms at 300** — and the canvas syncs once per
event-loop turn while a title is being typed. So `modules/problems/findings.py` is one
settled reading with two readers: `of()` hands back the last answer and asks for a fresh
one after a quiet spell, and a project asked about for the first time answers nothing and
arrives on the next settle. A squiggle appearing a moment after you delete a description is
the honest behaviour — the answer is a walk of the whole plan, and the plan is what moved.
Moving the derivation out of the panel is also what stops it being computed twice; the
panel reads the shared one now.

**Two signals, because the readers ask different questions.** Both name their project, so a
view of one project hears its own changes and no others — `follow_project`'s rule, kept by
hand because this is not a model signal. `changed` fires whenever the findings move, which
is what the panel lists; `flagged_changed` fires only when the set of flagged *ids* moves,
which is all the canvas draws. Without the second, renaming a step would change every
message about it and repaint the canvas one settle later, every time.

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

The painter is `theme/cards.py`'s, beside the other card primitives, and the status → shade
table is `theme/tones.py`'s `STEP_STATUS_TONES`, because the canvas is not the only surface
where a step is a card: the coverage lanes' milestones, features and steps wear the same
spine, so a key reads the same up every card that is a step.

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

### An agent at work says so, and the window says it back

Everything above makes the *mechanics* of two writers safe: the change lands, nothing is
overwritten, a collision is put to the user. What none of it does is make the other writer
**visible**. A developer with a window open sees a graph quietly rearranging itself and,
the first time they type into a step an agent is also rewriting, a modal asking them to
settle a collision they had no way to see coming. The mechanism was right and the
experience was of being ambushed by a tool that knew something it was not saying.

So the agent says it. `dplanner agent-work start '<what I am doing>'` writes a **claim** —
project, optionally a step, one line of prose, optionally the agent's own count of what it
is working through, when it started and when it was last heard from — and
`modules/agent_at_work/` stands one notice per claim over the window's content until it is
gone. Four decisions carry it.

**Liveness is reported, never guessed.** This was the whole design question, and every
version that tried to *decide* whether an agent was still there was worse than the one
that refused to. A heartbeat the agent must remember is a heartbeat it will forget mid-task;
a lease is a number that is either too short (the banner vanishes while the agent thinks for
twenty minutes on one tool call) or too long (a crashed agent holds the screen for an hour);
a pid is a process the announcing `dplanner` run does not own — its parent may be a shell
that lives for the session or one that exits with the call, and nothing can tell which. So
`domain/at_work.py` stores facts and derives readings: the claim carries `seen`, every
reader prints how long ago that was, and `is_fresh` decides only whether the words read
*is at work* or *was at work*. A quiet claim keeps its place and changes tense. It goes
away three ways and no others — the agent ends it, a person clears it from the banner, or
a claim made a day later sweeps one nobody has renewed since — and each of those is
somebody actually knowing something, which no timeout is.

**Every `dplanner` run is the sign of life, and only an agent's is.** An agent that is
working is already running verbs — a status, a note, a link — so `cli/main.py` renews the
project's standing claims on every invocation and the agent never carries a heartbeat of
its own. It never *makes* a claim: running a verb is evidence for a claim somebody made,
not a claim of its own. And the renewal is handed to the run only from inside an agent's
shell — `entry.py` passes the board when `agent_shell_marker()` says so, the same fact the
window word is refused on, read from the other side — because a developer running
`dplanner step list` in their own terminal would otherwise be vouching for an agent that
died an hour ago.

**A claim is this machine's, never the plan's.** It goes under `config_dir()/at-work/`
beside the telemetry journal, for the reason FORMAT.md gives: a record that changes every
few seconds and means "a process is running here, now" would, in a project directory, be
committed into everybody's history, arrive at every collaborator as an outside change, and
make the window adopt an edit every two seconds. One file per claim rather than one per
project, so several agents on one plan — the four Run Agent will launch at once — never
lose each other's updates to a read-modify-write race, and a reader is a directory listing.

**The window makes no claim, ever.** Its only write is the clear. A window that could say
"an agent is at work" would be a surface asserting something only the other process knows,
and the first time it was wrong the banner would stop meaning anything. That is also why
there is no window verb to start one and why `agent_at_work` registers no action beyond the
row's own *Clear*.

The payoff is the collision. `library_watch` now asks one question of this module — is an
agent at work on the project this conflict is in? — and while the answer is yes it leaves
its question in the notice bar and the status bar instead of raising the modal. The
question is deferred, never dropped: the person presses *Settle…* when they are ready, the
next collision after the agent goes quiet raises it as before, and the dialog names the
agent in its own words, because *Take Theirs* means taking that agent's work and a dialog
that did not say whose would be asking the developer to guess. The notice also replaced the
status-bar button *Later* used to leave: with the question standing over the content there
were two surfaces saying one thing, and the one that went is the one a person can look away
from.

What the banner is made of is the existing vocabulary and nothing new. DESIGN.md allows
three motions in the whole application; the arc that says *something is running here* is
one of them, and it leads a fresh claim. The tone is the reading — a warning while the
agent is at work, plain information once it has gone quiet. The count is the one amendment:
a bar is for work whose end the application knows, and "never for an agent" was written
when an agent's progress was unknowable. An agent that runs `agent-work set --done 8 --of
20` has declared a count, and a declared count is a count; a claim that declares none still
gets the arc and no promise.

#### The banner is a band, and the band is the meter

The first build said all of that in a dot beside secondary words with a 4 px strip under
them, and it was too quiet for what it means. Two things were wrong and both are about
where a fact of this kind is read. The tone was *busy*, which is the blue this application
says "a piece of work is running" in — true of the agent and beside the point for the
reader, whose problem is that **somebody else is writing this plan and they should keep
their hands still**. That is a caution, not a report, and the vocabulary had no word for
it: `warn` is the fifth tone, the amber the canvas chips already wear, and it is not a
weaker error — an error is this work failing and carries its remedy, where a warning is
something nobody can fix and everybody must see. And a tone said in a dot is a tone for a
surface somebody has chosen to look at; a standing notice is the opposite, so it wears the
tone as a **band across the whole row**. It is the one surface in the application where
that is right, and the reason is exactly that it is the one surface a person must not read
past.

The 4 px strip went the same way, for a reason that generalises past this banner: **a meter
has to be legible as a meter before anything has happened.** At nought per cent the strip
was a hairline under the words, indistinguishable from the seam above it, so the first
thing a reader learned about the agent's progress was learned only once the agent had made
some. The band fills instead — the same hue at a greater weight, from the left — and the
percentage stands at the right, next to the verb, where the eye is already going. An amber
row saying *0%* is plainly something that fills; a hairline is not. The strip keeps every
other job it had (a fetch, a save over three repositories, always under the fact that leads
it), because those are read inside a surface the person came to, and the notice is the
surface that came to them.

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
Save and Update honour it. Three of its operations deliberately do not, and the exception is
a decision, not a leak:

- **Branch switch and create** (`SyncService.switch_branch_sync` / `create_branch_sync`,
  run through `_run_guarded` in `modules/sync/module.py`). A checkout rewrites the very
  files the application is showing; taking them into the model must follow *immediately*,
  not after an event-loop round trip during which a paint, a context change or an autosave
  could read a model that no longer matches the tree. `_run_guarded` pauses autosave around
  the body for the same reason, and resumes it once the tree is in the model.
- **The branch list** before the switch dialog opens: a subprocess, but a local one, and
  the dialog's contents must be current at the moment it appears.
- **Moving a plan** (`ProjectsModule.move_plan` over `domain/relocate.move_project`). The
  project's files leave one directory for another and the store is re-pointed; the reload
  that follows discards the build, so there is no runner to come back to. The publish that
  may follow a move or a New Project into a fresh GitHub repository rides the same
  exception, under a wait cursor: the repository was written a moment ago and the person
  is waiting on it.

**Save at quit was the fourth, and it is not any more** — not because the rule bent, but
because its reason lapsed. It read: *the window is closing; there is no task centre left to
watch a task in, and returning to the event loop mid-teardown is exactly the window a lost
write needs.* Both halves turn on the window closing, and the close is **deferred** now: the
guard starts the save and answers "not yet", so nothing is tearing down while it runs, and
the progress dialog is the watcher the task centre could not be. The cost of the old answer
was the thing the exception never mentioned — a frozen window, for as long as publishing,
committing and pushing several repositories takes, with no way to tell it from a hang.

The boundary to keep: an operation whose completion the *running* application must observe
before doing anything else at all may be synchronous; anything the user merely waits on goes
through the runner. A new storage verb defaults to the runner. And the lesson of the fourth
one is worth keeping beside it: **before granting the exception, ask whether the constraint
that forces it is itself a choice.** "The window is closing" was.

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
a directory — the canvas spans `project_editor`, `framework` and `theme` — and a hook rebuilds
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

### The command list is an index, not a manual

SKILL.md's command section was a heading per noun and a bullet per verb carrying that verb's
summary: 176 bullets, 19,793 of the file's 58,603 characters, **a third of a document every
session loads**. And every one of those summaries was already carried twice more — as
reference.md's own heading for that command, and again inside reference.md's fenced argparse
help, which prints the same sentence under `usage:`. Three copies of one string, one of them
in the file nobody gets to choose not to read.

So the section is now one line per noun naming its verbs — `` `dplanner note` — add · attach
· index · list · remove · set · show`` — with a `†` on the verbs that read the topology first
and one legend line for it. 2,355 characters.

The trade is deliberate and it is not "an agent can look it up in reference.md". That file is
152 KB; sending an agent there to learn what `note index` does would cost more than the
bullets saved. The answer is `dplanner note index --help`, which is a subprocess that starts
in milliseconds, prints the arguments *and* the examples, and cannot be stale — the same
parser the skill was generated from. An index's job is to tell you a verb **exists** and how
it is spelled; `--help` tells you what it does; reference.md is for reading every flag of
everything at once. Each of the three is now used for what it is good at.

**A verb the skill must not teach carries `in_skill=False`.** It is the CLI twin of
`ActionSpec.in_menus=False`, and for the same reason: a thing can be legitimately available
and legitimately not offered. The region verbs are what it exists for — registered, runnable,
in `--help`, in neither generated file. The alternative was a noun denylist in the generator,
which puts knowledge of one module's retirement into `cli/skill.py`; the flag keeps it on the
command, where the module that owns it says so. A noun whose every verb is kept out is not a
noun in the index at all, so `region` simply does not appear.

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

**The editor is the prose stack's, and two of those three edges went with the widget.**
It was a `QTextEdit` over `setMarkdown`/`toMarkdown` — the one prose surface in the
application that edited a document *tree* and wrote back a normalised serialisation, which
is precisely what `framework/markdown_highlight.py` says a markdown editor here must not
do. It is a `ProseEdit` now, with the highlighter, the markdown strip, and the figures it
links to in a gallery under it, because a plain-text editor cannot draw a picture and
should not pretend to. What that deleted: the standing warning that editing would reformat
the document (plain text never reformats, so an untouched save is byte-identical by
construction rather than by a guard), the `![](` → `![image](` rewrite on open (Qt's
exporter dropped an empty alt; there is no exporter), and the carve-out that made a `.txt`
read-only — its whole reason was the round-trip handing it back as markdown. A PDF is the
one document that is not text, and renders.

There was a correctness fix hiding in that swap. `document_text()` — what `feature cite`,
lint, coverage and `anchor_in` all read — is the raw markdown **source**, while the
rich-text editor's `toPlainText()` was the **rendered** text. So citing a heading, or any
passage with inline markup in it, stored one string while every other reader checked
another; they agreed for plain paragraphs and disagreed silently everywhere else. The
editor's string is now the string every reader uses.

**A foreign change to the edited document ends the session** and reopens the document as
it now is: the model is the authority, unflushed keystrokes yield, and anything already
flushed survives as a recoverable blob. An agent replacing the document under an open
window resolves through *Two writers, one folder* like every other write.

**Expanding it is the same buffer, not a second binding.** The dialog's other path
(*Expanding an editor is a second binding, not a copy*) opens a `TextField` twice, because
there the model is the authority and each view hears the other's commands as foreign. Here
the *buffer* is the authority until the flush, so `over_document` hands the dialog the
inline editor's own `QTextDocument`: one buffer, two views, one undo history, in step by
construction. That is the base case of "never copy text out and back", and the binding pair
is the derived one. The alternative — a `TextField` adapter over the session buffer — would
have had to push a command per keystroke onto the application's undo stack, which is the
one thing the two-stacks rule above exists to prevent. The price is a Qt fact worth
knowing: when the borrowing view dies, the owner's *Python wrapper* for the document is
invalidated even though the C++ document and its text survive, so nothing may hold
`editor.document()` in a field. `NOTES-FOR-APPFRAME.md` §36 has the measurements.

**A rename moves the name, and everything that points at it.** There was no rename at all,
and a name is the one thing an agent types: `spec show`, `spec diff`, `feature cite
--document`, the `document` key on every passage a feature cites. Two shapes were on the
table. Rename only a *display title* and leave the key alone — which is what a sourced page
already does, and which cannot break anything — or move the key and carry its references.
The first was rejected for the reason the step existed: a key that no longer describes the
document is exactly what misleads the next agent, and a title beside a stale key leaves the
misleading thing in place and adds a second name to learn. So the key moves, and with it
the pages that name it as their parent, the asset rows that record where a figure came
from, and every feature step's citations — the last of which is another module's data, so
the composition root walks the steps, composes the commands, and both surfaces push them
inside one `CompositeCommand`. The filename's stem follows too, keeping its suffix: it is a historical
fact, but `matching_documents` resolves a needle against it, so leaving it behind would let
the old name go on addressing a document somebody had just renamed. What does *not* move is
the blob, which is content-addressed and never carried the name.

The honest cost is written down here because nothing can fix it: prose cannot be carried.
A note, a description or an agent's own memory that named the old key is stale after a
rename, and no command can find those. That is the trade the decision accepts — a stale
sentence is a thing a person reads and corrects, where a stale *key* is a citation that
silently stops resolving.

**Delete takes the index row and never the blob.** Four reasons, any one sufficient: undo
would restore a row pointing at nothing; blobs are content-addressed and therefore shared,
so deleting "the file" can pull the bytes out from under a second document with identical
content; `previous` is a second pointer at the same place, and `spec diff` reads it; and
`FORMAT.md`'s rule is that an orphaned blob is recoverable where a dangling link is not,
with the editing session's own churn as the single named carve-out. The workspace's git is
the history that makes leaving it cheap.

**The mark on the tab title is what this window has found.** `updates_words` — written and
tested when the sources landed, and uncalled until now — is the line over the whole tree,
where it is true whatever row is picked; its short form marks the tab's title and the Specs
row in the index, so there is something to see before the tab is opened. One `stale`
derivation, three readings. It rides a **set-diff** signal rather than the refresher's own
`changed`, which also fires on every busy flip and would redraw the index folder on each
spinner tick. And checking follows whether a Specs tab is **open**, not whether it is the
pane in front — the active-pane rule is about publishing a selection, and a mark that only
lit while you were already looking at it would say nothing. The scope that stays is the
honest one: a project whose Specs tab nobody has opened is not being checked, and wears no
mark. Checking every source of every project on a timer would mean a `git ls-remote`
subprocess per source per interval on a machine nobody asked, for a dot on a row.

## A spec source is a kind the spec module runs

The spec was always a file somebody put beside the project. Now it may live somewhere
else and change there — a folder on this computer, a git repository, a Confluence page, a
Confluence folder — and the question was where the machinery for that belongs. Two shapes were on the table: each
source module owns its own tree, task and index writes and the spec module hands it a
writer seam; or the spec module runs every source and a source module is nothing but a
*kind* — how to ask for a location, whether it is connected, how to connect, how to fetch
and how to check. The second won, for the reason the asset catalog and the report
sources did: the interesting logic (records, nesting, the write, the undo entry, the
freshness note, the strip) is the same for every source, and writing it once in the
consumer is what makes the second kind a fetcher and a dialog. The contract is a
`Protocol` in `modules/spec/source_kind.py`, consumer-owned like `CanvasDrop`; each kind
module satisfies it structurally and the composition root hands the kinds in as
`SpecDeps.kinds`. The four that shipped are the proof it was the right split: the folder
kind is a hundred lines over a shared walk, and the git kind — by far the largest — adds
a subprocess door and a dialog and changes nothing in `modules/spec/`. The Qt-free shapes they exchange — `Snapshot`, `FetchedDocument`,
`Freshness`, `SourceStatus`, `SourceUnavailableError` — sit in
`domain/document_source.py`, beside `AssetSource`, because the spec module's headless
core reads them and the kind's headless half constructs them and neither may import the
other.

**A fetched document is an ordinary spec document.** It arrives as **bytes and the
filename it had where it came from** — markdown, plain text or a PDF — and lands as a
content-addressed blob under `documents/` whose *stem is the name the spec module minted*
and whose *suffix is the kind's*, which is what decides how it is read and what stops a
kind renaming every row of an existing plan by changing its mind about filenames. Its
images are `assets/<sha16><suffix>` in the same area, and
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
Specs tab shows the project, `check_all` compares versions (two or three requests for a
tree, no bodies) and the strip says "3 documents changed at the source — Refresh"; nothing
is downloaded until the person asks. Both run on `TaskRunner`s in `spec/refresh.py`, the
`github/refresh.py` shape; a refusal that names the credential (a 401) is remembered per
window as *needs reconnect* until the kind's `config_changed` says otherwise. Both
memories are keyed by **(project, source)**: a source id is minted per project, so two
open projects both have a `src1`, and a dict keyed on the id alone had one project's
freshness answering for the other's — invisible while only the selected source was ever
asked, and a wrong number the moment something counts them.

**One kind, one thing — and a kind is a record, not a code path.** The Confluence module
shipped as a single kind whose locator carried `type: page | folder`, so the Add Spec menu
offered one entry for two different acts and a person pasting a folder address into it got
whatever the walk made of it. They are two kinds now, and the interesting part is what did
*not* fork: the walk is still one function, because the only difference between a page
source and a folder source is where the queue is seeded, and that is a branch on a value
the kind has just validated. What forked is data — a frozen `ContentType` with the id, the
words and the content type each kind accepts — and one `ConfluenceKind` class constructed
twice over it, on a module that keeps the client, the credential, the Connect dialog and
the settings page, because connecting to a site serves whichever of the two a source is.
The payoff is a sentence that could not exist before: *that is a folder address — add it
with Add Spec ▸ Confluence Folder*. The same `expected` argument is what stops a
hand-edited plan aiming one kind at the other's locator, which is the reason it is checked
on every read and not only at the door.

**A folder walk is domain's, because two kinds read it and modules never import each
other.** `domain/document_folder.py` sits beside `document_source.py` for the reason
`AssetSource` sits beside the asset catalog. Two decisions inside it are worth the ink. A
**version is a digest over the body and the pictures it links**: the body alone leaves a
document unchanged when a diagram beside it is redrawn, so the row is kept, and the page
goes on showing a blob that is no longer what the author drew — silent, and only visible
to somebody who looks at the picture. And `is_document` is **exported**, because the git
kind's `check` derives the same key set from a git tree without reading a byte; two rules
for what a document is would make a check lie about every file in the gap between them.
The nesting rule — a directory's `README.md` is the parent of its siblings, a directory
without one is transparent — was chosen because it can only *add* structure where somebody
already wrote the page that means it, and degrades to exactly flat otherwise.

**A git source's checkout is the person's cache, and the guard runs before the download.**
The plan is committed and shared, so megabytes of somebody else's repository cannot live
in it; the checkout goes under `config_dir()`, keyed on url + ref + path, one directory
per source — sharing one checkout between two sources would mean one fetch's sparse
pattern applied to the other's tree, which imports the wrong folder and says nothing. The
harder question was the size guard. A person pointing at a monorepo must be steered to a
subdirectory *before* they wait for it, and git will not report a blob's size without
fetching the blob — so the guard counts, it does not weigh: `--filter=blob:none` brings
the commit and all its trees and no content, the listing says how many files and how many
documents each folder holds, and an oversized one is refused in the dialog, beside the
folder, while it is being chosen. `GIT_NO_LAZY_FETCH` is set on the listing so an
accidental content read fails loudly instead of quietly downloading the repository behind
the guard's back, and the sparse pattern is written non-cone because cone mode also
materialises every file at the levels *above* the chosen folder — which would make the
guard have measured the wrong thing.

**A git document's version is its blob oid, not the commit.** `Freshness` is per document,
and a commit id moves for every file in the repository: using it would make the tab say
*everything changed* every ten minutes after anybody touched anything. A blob oid is a
content digest git has already computed and hands back from a tree for free, so `check` is
one `ls-remote` and, only when that moved, one blobless tree fetch and a comparison — no
bodies, and an honest answer. What the cache remembers is the last commit taken in, as a
ref inside itself: not the locator (which is shared and would drift per machine), not a
field on the source record (the plan would carry a fact about one person's disk), and not
per-window memory (that is what the last *check* found, which is a different thing). Its
disposability is the point: wipe the cache and the next check pays one tree fetch.

**`locate` may reach the network; what it may not do is block the GUI thread.** The
contract said *no network*, which was the shape that rule took for Confluence, whose
locate is a URL parse and whose network needs a credential only `connect` can obtain. The
git kind's whole reason is *which folder?*, and that cannot be answered without asking the
remote. The alternatives were worse in ways this step was meant to avoid: moving the probe
into `connect()` makes adding a source two gestures, the first of which adds something
that does not work and trips the `spec.source.unfetched` lint; and typing the subdirectory
blind means meeting the size guard as a failed fetch. So the docstring says the rule it
always meant — never block the GUI thread — and the git dialog probes on a `TaskRunner`,
the way the Connect dialog already did.

**One gesture is one undo entry, and the one-source case is not a special case.**
*Refresh All Sources* had two honest shapes: land each source as it arrives (N entries, N
Ctrl+Zs to undo one press) or collect and land together. The second is what a person means
by pressing one button, and `UndoService.gesture` already does it — with the detail that
makes the design cheap: a gesture holding exactly *one* push places that push itself, with
its own label. So `refresh` is `refresh_all` over a list of one, refreshing a single source
writes precisely what it wrote before, and no `if len(...) == 1` appears anywhere. A
source that refuses is skipped inside the gesture and reported after it closes, because a
failure must never cost the sources that succeeded.

**Fetching stays window-only, and the reason changed.** It used to be the credential: the
token is in the keychain, a shell could reach it, and an agent's shell runs with the
person's keychain but not their judgement. A folder source has no credential at all, so
that argument does not reach it. The one that does is simpler and covers all four: a fetch
pulls bytes from outside the plan *into* it, and choosing to do that is a person's act.
`spec list` shows the tree, its kinds and its locators, `spec show` and `spec diff` read
the snapshot, `spec import` and `spec remove` refuse a sourced document with a pointer to
the tab, and adding, refreshing and removing a source are window acts. The LLM service's
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
Its **right** is one dropdown named *Template*, offering the named combinations: *Milestone*
is milestone and description, *Agent* is agent, description and estimate, *Step* is the
estimate and description every step is born with. One control rather than five, because only
one of them is ever true at a time: five worded buttons said the same thing five times and
four of them were always wrong. The face is named for what it **offers**, not for what is
on — which one the step amounts to is the ticked entry — so the bar makes one claim about
the step (the lit toggles) and offers one way to change it, rather than saying the same
thing twice in two vocabularies. Each entry's **glyph** wears its body tone, so a feature's
entry and a feature node are one identity (which is why the tones moved to `theme/tones.py`,
where both can reach them) — the glyph and not a ground, because a template is *always*
selected and a wash that is permanently on says nothing, which is also what let ten
per-button stylesheets go. Picking a template
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
indicator sit outside their strips for exactly that reason. It is also why the face is
named once and left alone: a face whose words changed with the step would re-fold the strip
beside it every time a toggle moved. That inverts what the two `QToolBar`s used to do,
deliberately: the
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
the shape, why the index is an index, and why the graph decides who a note is for.

**And the index has a ceiling, which the first version did not.** A briefing is read once,
from the top, and an index nobody finishes costs what a log costs: on a 74-step plan with
320 standing notes the index came to 33,131 chars of a 47,157-char briefing, and the step's
own instructions sat after it. So `index_lines` keeps at most `INDEX_LIMIT` (20) notes per
label, the most recent, and **says what it left out** — `Decisions standing (20 of 64):`
and a closing line naming the rest and the `note list --label` that reads them. Three
decisions in that one sentence. *Per label* rather than one budget, because a label is what
an agent scans by and a flood of deferred items must not starve the decisions. *The most
recent*, because a plan's newest decisions are the ones its current work was shaped by, and
a superseded one has already left the index. And *a verb, not a count*: a line that said
only "44 more" would tell an agent it is missing something and not how to look. The cap
lives in `index_lines` and not in the composition root because `briefing_blocks` is the one
function the briefing, `dplanner note index` and the Agent tab's Notes pane share — put it
in the root and the window would stop showing what the agent was actually handed, which is
the whole point of that pane. `note index --all` drops it, because *does this note reach
this step?* is a question the narrower reach makes somebody ask, and no other verb answers
it: `note list` is the log, not what reaches a step.

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
because each names another module's vocabulary. Two block kinds, one framing: *parts* are
context handed forward from earlier steps, *sections* are facts about this step, and
`section_lines` renders both as `## …` — what differs is where they sit, not how they read.
One builder per kind lives in `modules/__init__.py` and both surfaces — Run
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
and the list of them is the setting. The first is the default — what `agent.run` itself
runs, so the Agent tab's button and the palette need no picker — and the whole list is
*Step ▸ Run Agent*, a data child menu rebuilt on open so a profile added in Settings is
offered at once, the default marked. Each entry is greyed with its own reason: the
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

**The verb has one seat, and it is the child menu.** *Run Agent…* used to sit flat beside
*Run Agent With ▸*, two entries for one act, and the flat one hid the choice the other
offered. Now the child menu *is* Run Agent: the profiles, a rule, and *Manage Agent
Profiles…* — the way to the settings page from the menu that needs it, through the
settings module's `open(section)` handed over by the root. The verb `agent.run` still
exists — every button and the palette run it — but it is registered `in_menus=False`:
the menu bar seats no QAction for it and the pop-ups skip it, while it keeps its menu and
its submenu (the child's title) so the palette can say *Step ▸ Run Agent* under it. A
verb whose seat is a data menu's own entries is a new shape for the registry; it owns
no shortcut, because only a seated QAction fires one, and the registry refuses the pair.

**The list is seeded once, and a removal stands.** A person should not have to build
*Codex in herdr* by hand to find out it exists, and a dropdown that offers one choice
teaches nothing. `seed_profiles` runs when the window is built and appends every harness
in Ghostty, herdr and Automatic (the platform's own terminal) after what is stored — the
stored default keeps its place, and a pairing a stored profile already *means* is skipped
by its choices rather than its name, so a hand-named *Claude in Ghostty* is never doubled.
The `profiles_seeded` flag is written with the list: a seeded profile the person removes
is not put back on the next start, which is what makes the seed a migration and not a
default the list keeps falling back to.

**Detection is the same question asked on purpose.** *Add Detected…* on the settings page
opens a fit dialog listing every harness in every terminal row of this platform, and
Automatic, with what the machine has of each — the agent's command on PATH, the terminal
by its row's probe (`detect_pairings`, Qt-free; the dialog is `detect_dialog.py`). A
pairing both halves of which are installed and which the list does not hold is ticked;
the rest are listed with the reason (*codex not found*, *already in the list*) rather than
dropped, so the person sees what installing a tool would unlock. The dialog only answers
— `chosen()` — and the page writes through `add_profiles`, the seed's own appender, so a
pairing already meant is never doubled whichever door it came in by. That split is
deliberate: the first-start checklist that is coming hosts the same rows, and it should
need the detection and the appender, not the dialog.

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

### What a run was handed

A ledger of what runs *cost* left the other half unrecorded: how big the briefing was that
each one opened with. It is the number somebody wants the moment a step looks expensive, and
it is the only one DPlanner itself is responsible for — the tokens are the model's doing, the
briefing is ours. Nothing kept it, which is why a whole pass had to be measured with a
throwaway script before anything could be fixed.

It is measured once, in `launcher.prepare` — the one function that knows what actually
reached `prompt.md`, rather than what some caller believed it was sending — and carried on
`LaunchFiles`, which `record_launch` already hands to the tracker, so no signature between
the two moved.

**The run is its home, and the usage row is a copy.** `AgentRun.prompt_chars` is what the
Agents browser reads, because the two cases a row cannot cover are the two that matter most:
a run still going has no usage row yet, and a harness with no token reader never gets one.
The tempting fix — write a usage row at launch with zero tokens — is worse than it looks:
`usage.totals` would then return `Usage(0, 0)` and the step would *claim it spent nothing*
where it currently and correctly says nothing at all. A size is a fact about the run; tokens
are a fact about the plan's cost. Keeping them in the stores that own each is what lets a
live run say one without lying about the other.

**No format bump, and the precedent that looks like it applies does not.** `progress_history`
went to format 2 for its `saved` key so an older build would refuse to rewrite the entry
rather than drop what somebody had authored. Here `usage.with_row` copies every kept row
**verbatim** and `rows()` filters without rebuilding, so an older build cannot lose
`prompt_chars` — and it re-stamps the entry to its own version on the next write anyway, so
the guard would not even guard. `ModuleDataFormat` requires one migration function per
version, so the bump would have put an identity function in the tree for no reader. The rule
worth keeping from this: **bump when an older writer would destroy the new key, not when one
merely would not write it.**

**A size does not total.** Two briefings added together is not a quantity anybody spends, so
`usage list`, `usage.totals` and the step's own phrase stay tokens-only, and `brief_words`
says its unit out loud — *briefed 18.4k chars* — because the number beside it on the same
line is tokens and two magnitudes in one row must not be readable as the same quantity.

**And the launch became a span.** There was none: Run Agent was timed only by the `action`
span `ActionRegistry.run` opens. A detail on that span is not available to a verb body —
`Telemetry.recent()` and `open_spans()` hand out **copies** by deliberate design, which
`tests/core/test_telemetry.py` pins — and adding an accessor for the live span would be a
write path into shared state, in `core/`, for one caller. It would also be wrong: one gesture
launches a shell per chosen step, so three launches are three sizes and could never be one
key on the parent. A child `action` span per launch nests under the gesture for free, renders
in *Debug ▸ Telemetry* with no UI work, and is the shape the rest of the application already
uses. The cost, named: a launch under the 20 ms journal floor is absent from the file — which
only happens where a test monkeypatches the spawn, and the durable record is the run and the
row in any case.

### The briefing says what each block cost

`agent prompt --json` returned the briefing as one opaque string, and `PromptSegment` carried
only a coarse `origin` — so the two `protocol` blocks were indistinguishable from each other,
as were the two `project` blocks, and both notes blocks fused into a single `inherited`
segment. Finding out where 47,000 characters went therefore meant monkeypatching `assemble`
from a script. A measurement that has to be re-invented is one nobody repeats, and "is the
briefing too big?" is now a question with a standing answer: one segment per block, each
carrying its own heading, and `segments` (origin, heading, chars) plus `chars` on the JSON.
The join invariant is untouched — the segment texts still concatenate to exactly the text
that is sent, which is what lets the Agent tab colour it without ever showing something else.

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
`.dplanner` index (`FORMAT.md`), which is what lets *Open Project…* and `dplanner library
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
or picks a plan repository, Open Project's browse page lists only what is inside one (the plan's history
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
commit message. *Quit Without Committing* is a real choice, not a scare: autosave already
put the files on disk, so nothing is lost either way; only the version history goes
unrecorded until next time.

*Commit & Quit* runs the save as an ordinary task under a modal progress dialog — one
`StatusLine` per repository, publishing then committing, over a determinate bar — and the
**close is deferred until it ends**: the guard starts the save and returns False, and the
dialog's own end closes the window. Three things follow, and each was a decision:

- **"Not yet" is a third answer a boolean guard can give.** `UnsavedChangesHost`'s guard
  returns whether the close may proceed, and False has always meant "the user cancelled".
  It now also means "ask me again in a moment", which needs no protocol change because the
  thing that asks again is ours: the dialog closes the window itself. A guard that could
  answer asynchronously would have been a framework contract change for one caller.
- **`show()`, never `exec()`.** The guards run inside `closeEvent`, so a nested modal loop
  there is re-entrant by construction — and this codebase already carries the scar
  (`modules/github/notice.py`: a nested modal loop deadlocks headless tests). The dialog is
  modal and shown; the event loop that was already running is the one that delivers the
  task's completion.
- **The bar reads a fact and an estimate, and the fact leads.** How many repositories are
  recorded is known, and it is the bar's floor. Between those steps it is filled by how
  long the last save took — `TaskService`'s duration memory, which the application now keeps
  across sessions (`remember=True`), because the estimate that matters most is for the save
  a window has not run yet: quitting a session in which nobody pressed Ctrl+S. A guess that
  could *contradict* what has landed would be worse than no guess, so `max(landed,
  estimated)` is the whole rule, and an estimate that runs out holds at `ESTIMATE_CAP`
  rather than reading complete. With nothing remembered the bar is the count alone.
- **The progress is reported by the service, not inferred by the dialog.** `SyncService`
  emits `saving(index, phase)` from inside the per-repository loop — a Qt signal, so it
  crosses from the worker thread exactly as `notice` does, and inert when nobody is
  listening, which is why File ▸ Save needed no change at all. The dialog tracks the index
  it is told rather than counting its own rows, because a repository that turns out clean
  skips a phase.

A failure stands **in that dialog**, with *Close Anyway* and *Stay*, rather than being
reported into a window that is about to go; the module's ordinary failure→`QMessageBox` hop
stands down while the dialog is up, so it is said once, where the person is looking. One
ordering trap is worth naming: `TaskRunner` emits `busy_changed(False)` *before*
`failed(...)` — deliberately, so a failure handler's modal cannot delay the autosave resume
— so the outcome is settled one event-loop turn later, by which time the error has arrived.

## Progression is the status-aware frontier

**The surface is named for the question; the derivation keeps the answer's name.** A person
opens this tab to find out what to start next, so it is called *Ready to start* — in the tab
title, the two menu entries and the index row. Everything underneath stays `progression`:
the walk, the module id, the activity kind, the action ids and `dplanner progression show`.
That split is deliberate three ways. The derivation puts every step into one of six
partitions and the frontier is only one of them, so *Ready to start* would be the wrong name
for the function. The kind and the ids are the contract the per-user store remembers tabs by
and the registry resolves verbs by, and renaming them would silently drop somebody's open
tabs. And the verb is in every agent's generated skill, so renaming it moves the ground under
an agent mid-plan for a word — a `later` note carries the question rather than this step.

The board's header is the percent and the bar. It carried two more lines under the bar — the
same counts in words (*12 done · 2 running · 5 ready*), then the same progress again in
estimated days — and a bar drawn to scale already says both, in the one place the eye
goes first. The terminal keeps them, because `dplanner progression show` has no bar and a
line there costs nothing.

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
another surface would dispute. The Ready lane's *Run N Agents* button is the same rule at
the module layer: each ready card carries a tick, and the button renders the real
`agent.run` action's state — evaluated against a context synthesised for exactly the ticked
steps — so the gate's reason appears verbatim and no second copy of "what launching needs"
exists. What it drops down is the Step menu's own Run Agent child (`agent_menu`, the data
menu's fill handed over by the root), never a copy: the board offers exactly what the
right-click offers. Opening the menu publishes the ticked steps first, because a menu
entry — like every presenter — acts on the context the user has now, and the face counts
what is ticked whatever the window's selection was.

**A launch from that lane never raises the prerequisite confirmation, and that is the two
rules agreeing rather than a gap.** `agent.run` asks before launching a step whose `requires`
do not all read done; a step is in the Ready lane precisely because they do. The board and
the gate are asking one question — "is anything this waits on unfinished?" — so the box can
only appear where the question can still be answered yes: the canvas, the order table, the
palette. A test pins the silence, because a confirmation that never fires in the place people
launch from is the kind of thing a later change removes by accident.

## The order says what order, and how much — never when

The Order tab ran the plan out as a calendar once: an *Accumulated* column, a *Since
milestone* column and a *Date* per row, from a start date set on that page, one step after
another with a single worker and weekends skipped. Every number in it was true and none of
it was useful. Nobody works that way, and the application itself does not believe it —
`time_estimates` simulates two pools of workers against milestone dates, and that is what
the plan is scheduled on. Two surfaces answering *when* with different arithmetic is one
surface too many, and the one to drop is the one nobody schedules on.

What an order *can* say without claiming to know who does the work is how much work it
holds. That is `domain/schedule.py`'s `volume_words` — *62 days over 24 steps, 2
unestimated* — beside `format_days` and `format_day_count` for their reason: it has four
readers (the tab, `dplanner order show`, `dplanner estimate rollup` and the Estimates tab's
strip) and a total read in one place must not disagree with the same total read in another.
The unestimated steps are named rather than folded in, because a total that counted them as
nothing would read as a smaller project.

Three consequences worth writing down:

- **The start-date bar left with the columns.** It was the estimation module's widget lent
  to this tab through a consumer-owned `StartBar` protocol, and this tab was its only
  caller. The value it wrote is still the project's, still read by `schedule show` and the
  report, and still set — from the Time tab's *Milestones ▸ Begin…*, which is where the
  dates that matter are chosen. A protocol with no implementor and a widget with no host
  are entropy, so both went.
- **Wave 1 is called *Wave 1*.** It was *Ready to start*, on the argument that "wave 1" makes
  the reader work out what it means. But the execution board now carries those words, and
  they would name two different things: the graph's first wave (nothing before it) and the
  status-aware frontier (nothing it waits on is left undone). Those coincide only in a
  project where nothing has been finished — the very coincidence this document warns against
  reading as sameness one section up. One phrase, one meaning.
- **The CSV export and the published report keep the day counts and the dates.** A
  spreadsheet is opened to sort, sum and chart, and a column of ISO dates is data rather
  than a claim the window makes. The tab and its own Export button therefore disagree about
  three columns, which is recorded as a `later` note rather than settled by making the
  export worse.

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

## A test says who it is for

A plan's roster of tests is not one list. The tests somebody sits down and executes by hand
are a different reading from the ones an engineer writes to prove a mechanism, and the
useful artefact is usually one of the two rather than the union. So a test carries an
**audience**, and the feature is that word appearing as a label wherever a test is shown and
as a filter wherever a list of tests is produced.

**The list is closed, and testing owns it.** `AUDIENCES` in `modules/testing/aspect.py` —
`qa`, `technical`, `other` — each an id, a label and a line of meaning, the same shape
`modules/notes/log.py` gives its `LABELS`. Free-form tags were the obvious alternative and
were rejected for the reason free-form tags always lose: `QA` and `qa` become two audiences,
and a filter over a vocabulary nobody agreed on is a search box with extra steps. It is
**not** wired in the composition root beside `_scope_kinds()`, and that is a deliberate
difference: the scope kinds live there because they name *other modules'* aspects — a check,
a feature, a milestone — and testing may not import them. Nothing outside testing has an
opinion about who a test is for, so handing the vocabulary in would have bought three
injection points (`TestsDeps`, `commands()`, `report_source()`) for a three-line tuple, and
`aspect.py` could no longer check a value on the way in. Widening the list is a line in that
tuple; making it configurable, when somebody asks, is a change in one file.

**A test carries several.** One thing can be worth proving by hand *and* worth proving
mechanically, and forcing a choice would put the same test in the wrong list half the time.
The cost is that a filter is a set intersection rather than an equality, which is four
characters, and that a cell may name two — which is the one thing the published page's
picks had to be taught (see below).

### Absence reads as *other*, and the lint asks anyway

This is the part worth writing down, because the two halves look like they contradict each
other and do not.

`audiences_of(test)` returns what the test stored, or `("other",)` when it stored nothing.
Every view, filter and export reads it, so a plan written before audiences existed changed
meaning nowhere and needed no migration pass guessing at answers: its tests simply read as
*Other*, appear under the *Other* pick, and print as *Other*. Absence encoding a default is
the ordinary `FORMAT.md` rule, applied in the direction the fact points.

But *other* as a fallback is not a classification, and the point of the feature is that
somebody says. So `project lint` gained `test.audience`, and it is the **one** reader that
looks at the raw `test.audiences` instead — because its question is not *what does this test
count as* but *has anybody actually said*. The lint is the migration, applied a test at a
time by the person who knows the answer, which is the only place that answer exists.

The step panel's three checkboxes are the second raw reader, and the first attempt got this
wrong in a way worth recording. Driving them from `audiences_of` renders *Other* ticked on
an unclassified test — and then it cannot be unticked, because unticking stores `()` and
`()` reads back as `("other",)`. A checkbox that refuses to come off is a bug the model
caused, not the widget. So the boxes say what is **stored**, three empty boxes on a test
nobody has classified, and the line under them — the one already carrying *Archived* and the
last run — says *"No audience set — reads as Other"*. That line is also, word for word, what
the lint asks for, in the place you would fix it.

### Every writer of a record is a chance to lose a field

Adding a field to `Test` meant finding six places that rebuilt one positionally from its
four fields — `test set`, `test archive`, the panel's archive, the bulk archive, the title
commit, and `TestBodyField.command`, which runs on **every keystroke in a test body**. Each
would have silently dropped the new field. They are all `dataclasses.replace` now, and the
rule generalises past this change: *a record with more than two fields is amended, never
rebuilt* — `remint_for_paste` already knew, which is why a pasted test keeps its audience
and loses only its id.

The same shape decided the format bump. `FORMAT.md`'s rule is *bump when an older writer
would destroy the new key, not when it merely would not write it*, and `write()` rebuilding
every record is exactly the destroying case, so `testing` is format 2 with a pass-through
migration. What the stamp actually buys is narrower than the two existing pass-throughs
claim, and the migration's docstring says so: `migrated()` only makes the **migration pass**
leave newer data alone with a warning. `set_module_data` checks no version and `read()`
never looks at the stamp, so an older build still reads these tests and still rewrites them
without their audiences. The stamp records that the entry may carry keys an older build does
not know; it does not enforce it.

### The filter on a published page belongs to the column, not to the verb

`dplanner report html --audience qa` would have been the obvious way to hand somebody a
QA-only page, and it is the one thing this feature deliberately does not have: `cli/report/`
never imports a module, and a flag spelled `--audience` would put a testing word inside it
anyway. What the report layer *can* own is "this column is worth picking from", so
`parts.Column` gained `filter`, `page.py` renders a `<select>` per filterable column, and
`report.js` applies them per table. One published page any reader narrows for themselves
beats an edition per audience, and it is what `page.py` had already decided for the steps
table's status.

That existing status filter folded into the new mechanism rather than sitting beside it, and
folding it taught the one thing a generic version has to get right. The old predicate read
the *class* off the rendered cell, because `_cell` prettifies what it prints — a status
loses its hyphen, a date becomes "in three weeks" — and an audience cell names several at
once, `", "`-joined. So a filterable cell carries its values in `data-values`, apart from
its words, and a pick matches one value at a time. The options are built from the rows, so
a plan with nothing blocked no longer offers *Blocked* — which the hard-coded four always
did.

## A test is filed under a category, and its words are the key

The audience above is one axis and it is closed. The axis a roster of two hundred tests
actually needs is the other one — *what kind of thing is this test* — and it cannot be
closed, because *Import*, *Permissions*, *Print layout* and *Rate limiting* are this
project's words and the next project's are different ones. So a test carries a **category**:
one line of free text, catalogued beside the project.

**The words are the key.** There is no minted id. `dplanner test set T100 --category
'Import'` is the whole story; a diff says which group a test moved to; an agent that has
never seen this plan can file a test from the catalogue it just printed. The alternative —
a stable `c3` with a label beside it — buys exactly one thing, a free rename, and charges
for it in every other place: a CLI nobody can type, a JSON nobody can read, and a label that
drifts from its id the first time two agents disagree. The price of the choice is that a
rename **is** a rewrite of every test carrying the old words, and that price is paid where
it is visible: `test-category set --rename` and the editor's Save both do it in one undoable
step, and the editor's row says how many tests it is about to move before it moves them.

**The catalogue is stored; membership is derived.** `{"categories": [{"name": …, "icon": …}]}`
beside the project, in the order somebody wrote them. It is stored for one reason that
matters: an agent reading a spec can lay the groups out *before* the tests that will fill
them, which is what makes the tests arrive filed instead of arriving and then being sorted.
What is *in* a category is never stored — `counts()` walks the tests, the same rule the
topological order keeps. And a category a test names that the catalogue does not is still a
real category: `catalog()` appends it, unglyphed, after the ones that were written down. A
typo therefore shows up as a group of one rather than as a test that has quietly fallen out
of every list, and the editor is where it gets merged.

**Absence reads as *Uncategorised*, and the lint asks anyway** — the audience's rule, one
vocabulary over, with one difference: `test.category` stays quiet until the project has any
categories at all. A plan that has not started filing its tests is not behind on anything;
the check exists to catch the test added *after* the filing was laid out, which is the one
an agent's next `test add` forgets.

### Two writers, one project entry

`runs` and `categories` are both project-level keys under the module id `testing`, and
`SetModuleDataCommand` stores an entry **whole**. Each writer returning a dict built from
its own half would therefore have silently deleted the other's key — a run started after
the categories were laid out would have taken them with it. `aspect.project_entry()` is the
one composer, both writers go through it, and `runs.write()` grew a `project` parameter so
it could. The generalisation is worth stating, because the module system invites the bug:
*one module id may name several shapes, and every writer of a shared entry must compose it
from what is on disk.* `FORMAT.md`'s "one module id, two shapes" paragraph is the same fact
seen from the data's side.

### The sort key is an ergonomic, not a second layer of filing

The category answers *what kind of test is this*. The question left over is the one
somebody **executing** a roster has: within *Set up new customer*, which twenty of these
can I do without switching screens? That is not a second category — filing it twice would
double the headings and halve the page — it is an **order**. So a test carries a `sort_key`:
free text, no catalogue, no editor, and no meaning beyond *tests sharing one belong
together*.

Three decisions make it worth having rather than clever.

**It always sorts, inside whatever group is current.** *Ergonomic order* on the Tests strip
is on by default and the switch is there to turn it **off**, not on. A sort key that only
sometimes sorts is one nobody can rely on halfway down a list with a device in the other
hand — and a project that uses no sort keys is ordered identically either way, because the
sort is stable and a keyless test keeps its place. Unticking it gives back the plan's own
order, which is the reading somebody following the *work* wants.

**Alphabetical, keyless last.** Adjacency is the whole win, so any consistent order would
do; alphabetical is the one a reader can predict without opening anything, and it is what
somebody who numbers their keys (*1. Sign in*, *2. Import*) already expects to happen. The
alternative — first appearance in project order — is invisible, and an agent that wanted a
particular sequence would have no way to ask for one.

**It is a column, not a heading.** `Table` groups flat: rows belong to the heading above
them until the next one, so a second level would have needed nesting in the primitive and
would have made folding a category ambiguous. It is also the wrong shape for the fact — the
rows are *already adjacent* once they are sorted, which is what a reader sees, and the
column is there to say what the run of rows has in common. So the Sort key column follows
the ordinary blank-column rule and appears the day a project starts using one.

The CLI half is `test add|set --sort-key`, `test list --sort-key` and `--flat`, and — the
one an agent reorganising a roster actually runs — **`dplanner test file`**, which takes
many tests and both filing fields in one call. That verb replaced `test-category assign`:
`test set` is one test with many fields, `test file` is many tests with the two fields that
say where a test goes, and having one verb per axis would have been two verbs for one
gesture. In the window it is the step panel's field (an editable combo, offering the keys
already in use so one view is not spelled three ways) and `Step ▸ Test Sort Key ▸ …`, whose
last entry mints a new key — because with no catalogue there is no editor to send anybody
to.

### Grouping is one selector, and the tests' own vocabulary leads it

The Tests tab already grouped by feature, milestone or check. Category could have been a
second control beside that one — and would have been wrong: *by feature*, *by milestone*,
*by check* and *by category* are four answers to one question, so they are four entries in
one box. Making that true meant generalising what grouped the rows, because the three that
existed are facts about a test's **step** and the new one is a fact about the **test** — a
step's three tests are often three different kinds of thing, which is most of why the
category exists at all. `_Grouping` is two functions, *where does this row sort* and *what
heading does it land under*, both taking `(step, test)`; the collector grouping ignores the
test and the category grouping ignores the step. One shape asked twice, rather than two
mechanisms that will one day disagree about what a heading is.

Category leads the list and is the default *while the project has one*, because filing by
what a test is beats a flat roster and a project with no categories would otherwise open on
a single heading saying *Uncategorised*. The default stands only until the reader picks a
grouping themselves; after that their answer is the answer.

### The category headings fold, and the table remembers by key

Grouping two hundred tests is only half the reading. The other half is folding twelve of
the thirteen groups shut, which is what turns the roster into a page. So `Table.add_heading`
takes a `key`, and a keyed heading wears a disclosure chevron and swallows the click that
toggles it — the **whole row** is the target, because a heading selects nothing and runs
nothing else, so there is no second thing a click there could have meant and a seven-pixel
triangle is not a target.

What is folded is remembered **by key, inside the table, across `clear_rows`**. That is the
part that had to be got right: a host rebuilds a grouped table wholesale on every refresh,
and a fold remembered by row number would spring every group open on the next keystroke
anywhere in the project. The key is the host's own word — a category's name — so folding
*Smoke* folds the same group after a rebuild, after a rename that kept the name, and after
the tab is reopened over the same rows. The collector groupings pass no key and so do not
fold: a feature's tests are already few, and a reader who asked to see them beside each
other did not ask to unfold them one at a time.

### Export is what the tab is showing

"Narrow it to QA, then hand that to the QA team" is one gesture, so `File ▸ Export ▸ Tests`
writes what the project's Tests tab is *currently showing* — its scope, its audience filter,
whether the archived are in — rather than opening a second dialog asking the same three
questions the strip has already been answering. `TestsActivity.showing()` is the one reader
of that, and `New Test Run` uses it too: the old `_narrowed_to` was the same walk for the
scope alone, and generalising it was cheaper than a near-copy beside it. With no tab open
the verb exports the project's whole roster, which is the honest reading of "no narrowing".
The CLI takes the narrowing as flags, because a terminal has no tab to read.

The two formats are deliberate and neither is the report. `cli/report/` publishes *the plan*
and names each test in one line; this writes *the tests*, filed under their categories, with
every body in full. Markdown is what a repository keeps and what the next agent converts
into whatever TestRail wants; HTML is one self-contained page whose every test is a
`<details>` that opens on its body, which is what makes a hundred of them scannable. Neither
inlines pictures: a test body's images live in the step's file area, and embedding them
would make this a publication, which is the report's job.

## A test is run from a panel, and a double-click there opens the test

A roster is not read, it is *worked down*. The gesture that was missing is the one between
two tests: mark this, look at the next. Doing it from the table alone means the body is a
one-line preview and the only way to read a test in full was to open its **step** — which
is the wrong thing twice over, because it is a page about the work rather than about what
you are checking, and because it is a modal that takes the list away every time.

So there is a **Test panel**, in the window's right area beside Project and Step: the test's
id and title, where it is filed, its last result, the four result verbs, *Show Step*, and
Previous/Next. Three things about it are the design.

**It renders the body rather than editing it.** A numbered list is a numbered list here,
not `1.` and a full stop. Authoring stays in the step panel's Tests tab, where the editor,
the images and the audience boxes already are, and *Show Step* is the door — one click, and
a door somebody executing a test wants anyway when what they find contradicts the step.
Rendering is also why the panel resolves `![](assets/…)` against the step's own file area:
the link the editor stores is relative to a directory nothing outside the plan can follow.

**Double-clicking a row in a Tests tab opens the test, not its step.** That is the one
deliberate exception to *double-clicking a step anywhere runs `steps.details`*, and the
reason is that in this table a row **is** a test — its step is a column. The roll call does
the same, and because it spans projects and publishes no selection of its own, it hands the
verb a constructed context naming exactly that row. The verb (`test.details`) only
*reveals* the panel; the panel was already following the context, so a single click updates
it and a double-click is what puts it on screen. That is also why there is no preference
for any of this: a panel is already something the user switches on and off, in one place,
for every panel there is.

**Next and Previous move the table's selection, never the panel's own.** A panel may not
publish a selection — it follows the context, and writing to it would fight whatever else
is showing. So the panel asks the Tests tab to pick the neighbouring row, the table
publishes as it always does, and the panel follows like any other change. It is the *tab's*
order that "next" means, not the project's: the reader's scope, their audience filter and
their ergonomic order are what put the next test where they are looking. With no Tests tab
open there is nothing to walk, and both verbs are greyed saying so — which is honest rather
than defensive, because "next" has no meaning without a list.

## A test goes stale when the step under it moves

Eleven tests on one real plan contradicted the product and lint said nothing about any of
them. Nothing was broken: three decision notes had changed what the work should do, months
after the steps carrying those tests were marked done, and a test is exactly the thing that
does not notice. `dplanner test review` is the report that notices — `coverage review`'s
shape, because it answers the same kind of question: *what needs a person after something
underneath it changed?*

**The comparison is against the test's last run, because there is no other date to use.**
The obvious reading of "a done step with a later note" wants the day the step became done,
and `step_status` stores `{"status": "done"}` and nothing else — no stamp, anywhere. Adding
one was the wrong fix twice over: it is a stored fact where this codebase derives, and it
would answer for nothing that happened before the day it shipped, which is precisely the
eleven tests that prompted the feature.

So the verb asks the question the data can answer, which turns out to be the better one:
**has this test been run since the note landed?** `runs.latest_results` already gives every
test's last outcome in one pass, and a run carries the day it was closed — or opened, for a
run still open, because a result recorded in it was recorded then and not whenever the run
eventually ends. A test nobody has ever run is behind *every* note on its step, which is the
honest reading: nothing has established it against any of them. A note nobody dated is the
mirror case — it cannot be *shown* to postdate a run, so it counts only against a test that
never ran, rather than putting a row in front of somebody that they cannot act on.

**Only a done step is asked.** Work in progress is meant to be ahead of its tests; reporting
it would bury the real findings under every step anybody is currently working on.

**Which labels unsettle a test is named in the composition root**, `_unsettling_notes()`,
and the reason is the one `_scope_kinds()` gives: the root is the single place allowed to
know every aspect at once, and `modules/testing/` may not learn the notes module's
vocabulary. A `decision` changes what the work should do and a `spec-change` records where
it departed from the spec — either can leave a test proving last month's answer. A
`handoff` says where the code lives, a `later` defers work, a `post-project` note is for
afterwards; none of them makes a claim about what a test should assert, so none should put
one in front of anybody. Notes reach testing as a neutral `(id, label, title, made)` keyed
by step — `cli/scopes.py`'s `CoveredTest` hand-over, one layer down — so testing learns
nothing about what else a note carries.

Superseded notes are dropped on the way. The note that replaced one is itself a decision,
made later, so it already stands for the doubt; keeping both would name one test twice for
what is one thing to do. For the same reason a row is **per test, not per note**: a test
behind three decisions is one piece of work, and the newest note is the one that says what
it now has to prove.

**A verb, not a lint check.** Lint is for findings with a crisp fix — a missing body, a
dangling edge. Whether a test still proves the right thing needs somebody to read the note
and decide, and the two ways out (re-run it, or rewrite what it asserts) are a judgement
rather than a remedy. `coverage review` drew that line first, and this follows it.

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

A **documentation fragment** is what one step adds to the product's documentation — `docs`,
prose beside the step, written while the work is fresh. A collector's **documentation** is
what a feature or a milestone makes of everything it gathers — `docs_compiled`, prose beside
the collector. Those are the words on every surface; the two on-disk ids are the older ones
and stay, because an id is a contract and a label is a sentence.

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

### Compiling launches a peer, and the window writes no document

The first version compiled with an in-app LLM call: a `TaskRunner` body around
`framework/llm_service.py`, the answer home on a queued Qt signal, the document and its stamp
landed as one undo entry. It worked, needed a provider key in *Settings ▸ LLM* to do anything
at all, and nobody used it — while the agents actually doing the work were already writing to
the plan through the CLI all day. So *Compile with Agent…* launches one, with a briefing built
from the fragments, the project's compilation instructions and the verb to finish with, and
the window's own compiler is gone. Five things follow.

**The docs module words the briefing; the launcher wraps it.** What a fragment is, which verb
lands a document and that `assets/…` links must survive are this module's vocabulary
(`modules/docs/prompt.py`, Qt-free); the header and the preflight every hand-over gets are the
agent module's (`prompt.handover_prompt`, shared with the conflict hand-over). The two meet at
two typed callbacks on `DocsDeps` — `compile_profiles` and `compile_with_agent` — wired by the
composition root, which is `library_watch`'s `hand_to_agent`/`agent_refusal` shape exactly. A
third module wanting a launch copies that; nothing imports the agent module.

**Nothing lands on the undo stack any more.** The document arrives minutes later from another
process and the store adopts it entry by entry, like any outside change — so *An LLM call is a
task*'s "the result lands on the undo stack, because a person pressed a button" stops applying
here. Ctrl+Z cannot put back a document an agent replaced, which is why the one gesture that
would overwrite a document that has text **asks first**, once for the whole gesture, and says
that there is no undo. Everywhere else in this application the confirmation was deleted and
undo made the case for it; here the safety net genuinely is not there.

**The run is the collector's, and it claims nothing about the work.** `_launch` hands the
shell to the run tracker as it does for Run Agent, so a compiling agent wears the chip and the
marching ring, appears in the Agents browser, is reachable through *Show Agent Terminal* and
leaves a usage row when it ends — for nothing, because the collector is a step. What it does
**not** do is `mark_started`: an agent writing a feature's documentation is not doing that
feature's work, and the claim is made in Run Agent's own step loop rather than in `_launch`
for exactly this reason. Two runs on one step are told apart by their terminal windows —
`_launch` takes a `note` the window title carries (`F7 Auth (documentation)`) — and by nothing
else, which is the pre-existing shape for two Run Agent launches on one step.

**Who compiled a document is the launching window's record, not the plan's.** The stamp in the
plan says *when* and *from what*; `provider` and `model` left it (`docs_compiled` format 2),
because with the CLI as the only writer they would hold one value each forever. Attribution is
the worded launch `compile_with_agent` returns, kept per collector in the docs module's own
`user_config` — exact, where reading the step's newest `AgentRun` back would credit a feature's
document to whichever agent happened to be working on that feature. The cost is stated rather
than hidden: a plan opened on another machine says when a document was compiled and not by
whom, and a compile nobody launched from a window is attributed to nothing. It is also why the
panel's live line says *an agent is working on this step* and never *compiling this now* — the
window cannot tell one run on a step from another, and the point of the line is to stop a
second launch.

**Compiling a whole project takes the frontier.** *Compile Out of Date…* launches one agent
per collector whose fragments have moved on — except a collector whose own sub-collectors are
also due, because a milestone reads its features' *compiled* documents and one launched beside
them would read documents about to change. `collect.sub_collectors` is that question, the same
two calls `sources_for` makes; the verb says how many are waiting, and the next gesture takes
them. Past *Max agents launched at once* the count itself refuses, as it does for a selection
of agent steps.

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
matching digest is *current*, anything else is *out of date*. The Documentation view says them
in words, in the row's trailing slot — and **nothing at all when a document is current**,
which is what the hollow ring and the filled dot bought before the row had words to spare.
What the last compile *was* — how much it read, when, and which agent this desk handed it to —
is the line underneath.

The digest covers the **sources**, not the compilation instructions: rewording how every
document should read does not mark every document out of date, exactly as hand-editing one
does not. Both are the same rule — the digest is over what a compile *read* — and the second
is a surface a person edits now, so it is worth saying out loud.

### Who owns which half

`modules/docs/` owns both aspects, the fragment editor, the Docs folder and the Documentation
view; `collect.py` is the one derivation, Qt-free, with four readers (the view, `docs collect`,
`docs status`, the compile briefing). The collector kinds arrive as an argument, exactly as
`TestsDeps` takes them — **nothing is added to `_scope_kinds()`**. A fourth kind there would
have put documentation in the Tests tab's scope selector and its Group by, and given every
collector a Covers tab it never asked for: four surfaces learning about documentation to
serve none of it.

The project's **compilation instructions** are `modules/docs.md` beside the project — the
`docs` id spanning node kinds, which `FORMAT.md` sanctions and `step_agent_instruction`
already does. They have three presenters over one field: the project panel's card, a tab in
the Documentation view (two bindings, one undo stack, the standing agent instruction's shape),
and `dplanner docs set/show --for-project`. The CLI half is not a convenience: every compile
briefing opens with them, so an agent compiling without a window launch must be able to read
what its document is meant to follow.

## An LLM call is a task, and the service is GUI-bound

`framework/llm_service.py` shipped complete and dormant — no consumer, no tests, and no
mention in this file. Compiling documentation was its first and, for one milestone, its only
one; compiling launches an agent now (*Compiling launches a peer*), so the service is dormant
again — **deliberately, and with its rules written down here rather than lost with its
caller**. They cost nothing to keep and they are what the next AI-gated control in this
application is owed. Read them as the contract they are, not as a description of something
running today. (The checklist's `llm.key` row stays for the same reason and says as much.)

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

**A result a person asked for lands on the undo stack**, unlike `github/refresh.py`'s
background sync. The distinction is who asked: a person pressed a button, so undo must put
back what was there. Note what that rule does *not* reach — a result that arrives from another
process, minutes later, through the CLI, as a compiled document now does; there undo is not
the safety net and a confirmation has to be.

**And the CLI cannot call it.** The service reads its preferred provider through QSettings
and its key through the OS keychain, so it is Qt-bound by construction while `cli.py` loads
no Qt by rule. That is not a gap to route around, and documentation is the proof: the agent
driving the CLI *is* a model, so the loop is `docs status` → `docs collect` → the agent writes
→ `compiled set`, which re-stamps the digest so what it just wrote reads as current — and the
window's part is to *launch* that loop rather than to reimplement it. Same reasoning as
*Running an agent launches a peer, not a task*, which is where that argument ended up.

## Dictation is a provider, and capture is a peer process

Descriptions, notes, tests, fragments, instructions and specs are prose, and most people
speak faster than they type. The step that added dictation asked for it as a *provider
kind* — the way agent CLIs are harnesses and themes are provided — so the application
never depends on one engine. Five decisions fell out of building it.

**The contract is a Qt-free record in `domain/`, not a Protocol in `framework/`.** The
checklist reaches the providers at CLI time (*is any engine ready on this machine*), and a
module's Qt-free half may import `core` and `domain` and never `framework`; so
`domain/dictation.py` holds `DictationProvider` — id, label, the caption of its one
editable text, the default, a `refusal(text)`, and either `transcribe` or `listen` — with
the recorder table beside it, exactly where `domain/agents.py` holds `AgentHarness`. The
capabilities are derived: a provider that carries `listen` is live, one that names a
`setup_action` can be mended from where its refusal is shown. `LLMProvider` stayed a
Protocol in `framework/llm.py` because nothing headless reads it; the two shapes are the
same lineage one layer apart.

**Capture is a peer process, because there is no QtMultimedia.** PySide6-Essentials ships
the stub and not the binary; the Addons package that has it is the hundreds-of-megabyte
choice `pyproject.toml` already refused for QtPdf. Every command-line recorder this
application could meet — PipeWire's `pw-record`, PulseAudio's `parecord`, ALSA's
`arecord`, `ffmpeg`, `sox` — streams raw signed 16-bit mono samples to a pipe, and a
`QProcess` on the GUI thread reads that pipe as it fills: no worker, no lock, every signal
delivered by the event loop. Raw output is what makes stopping simple — a WAV would need
its header patched by a process that may be dead, raw samples have no trailer — so the
stop is one sequence for every row: `q` on stdin (ffmpeg on POSIX takes it), then
`terminate()`, then `kill()` after a grace, which on Windows is the only one that reaches a
console process; the bytes already read survive it, and the ffmpeg rows carry
`-flush_packets 1` so at most a packet is lost. A recorder is a row with a probe, like a
terminal; *Automatic* is the first installed; the rate is the provider's (`{rate}`),
because the whisper family wants 16 kHz and the Realtime API 24 kHz. The alternatives —
a `sounddevice` wheel, a hand-rolled `ctypes` binding per platform — were weighed with the
developer and declined: a table of commands adds no dependency, matches the launcher's
doctrine, and on the two platforms where the table is thin the OS has dictation of its own,
which the page and the checklist say.

**Batch and live are two shapes of one state machine, and live is one undo step.** A
batch provider gets the WAV once the microphone is off and its transcript lands through
`ProseEdit.insert_at_caret` — the dropped-file insert, sealed on both sides. A live
provider is fed the samples as the recorder emits them and its deltas land at a cursor the
verb took where the caret stood when the session began, so the person can read on while
speaking; an utterance's completed transcript replaces the deltas that led to it. Typing
merges within a one-second window and a spoken pause is longer than that, so coalescing
could not make a session one step; `UndoService` grew `begin_gesture`/`end_gesture`, the
context manager's halves as calls, and the verb holds one open from the first word to
the stop. While a gesture is open nothing can be undone or redone — a Ctrl+Z pulling the
step before it out from under commands not yet placed is worse than a refused key.
`Dictation` (`framework/dictation.py`) is the one machine — idle → recording →
transcribing, or idle → listening → finishing — and the strip's verb and the settings
page's *Try it* are two faces of it, so what the page hears is what an editor would get.

**The service owns the one task runner, and a late transcript is dropped.** A
transcription outlives the editor that asked for it — a tab closed mid-sentence must not
strand a *Transcribing…* row in the task centre — so `DictationService` is on the bundle
with a runner parented to the window, every body captures only plain values and a signal
instance, and a delivery to a deleted receiver is suppressed. One microphone, one
provider, one transcription at a time: a second editor's press while one runs is refused
in words. And a dictation belongs to the document it was started over: `ProseSection`
abandons on every re-bind and `ExpandedTextDialog` on dispose, a generation counter drops
whatever the run still delivers, and the two agent-instruction fields that had no strip
got one rather than a second corner button, because *every prose editor wears the strip*
was already the rule and the exception was the entropy. `status()` is memoised between
`config_changed`s — thirteen strips ask at every build, and one provider's refusal is a
keychain round trip — and the builder bridges `llm.config_changed` into it, since the
OpenAI providers run on the key the vendor module keeps.

**Nothing meters the level, and silence is refused before anybody is paid.** DESIGN.md
allows three motions — the agent ring, the Updating indicator, a working button's glyph —
and a level meter at ten frames a second would be a fourth vocabulary. Recording is the
verb checked and the editor's edge in the accent (`#InspectorNotes[dictating="true"]`);
transcribing is the Spinner in the glyph. The check the meter was for happens once: the
clip's RMS is read after a batch stop, and a silent clip is refused with *Nothing was
heard* rather than sent to a provider that bills by the minute.

**Setting it up is presets, and a refusal names its mend.** Settings ▸ Dictation is the
Agent profiles page's shape twice — a dropdown of providers over the provider's one text,
a dropdown of recorders over the command — with a status line under each saying what
stands in the way and, beside it, what fixes it: a link to where the program comes from, or
*Add API key…*, which runs the provider's `setup_action` through the registry. That action
is the vendor module's: `ApiKeyDialog` (`framework/key_dialog.py`) walks through where a
key is made, tests it on a task runner with the vendor's own probe, and stores it in the
keychain only once it worked — the Confluence Connect dialog's shape with the site and the
email taken away, so every vendor can offer the same act. The checklist's two rows name
the same `dictation.settings` action, which is how *Set Up…* on a row lands on the page
without the checklist importing anything.

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

## A feature is a step

A specification used to be read into **requirements**: quoted obligations in the spec
module's index, linked N:M to steps, cited in briefings, checked by lint. It was honest and
it was the wrong grain. Nobody demos a requirement; people name, build and test *features*,
and the graph already knew that — a feature step gathers the work that flows into it, and
`dplanner scope show` reads it.

The next answer was a **record**: a feature in the project's catalogue whether or not it
was on the graph, which a step later became the instance of. That bought one thing — the
feature *before* somebody cuts a step for it — and it cost a parallel store. With steps as
cheap as they are, the trade stopped paying:

- the record's `title` was the step's title and its `description` the step's description,
  so a feature had two of each and they drifted;
- *placed*, *unplaced*, *duplicate* and *unregistered* were four half-states, each with a
  lint check, a refusal and a phrase in the panel;
- undo had to restore either side independently, because the record outlived its step.

**So a feature is simply a step that carries the feature aspect.** Its name is the step's
title, its description the step's prose, its pictures the step's file area, and the only
fact that was ever the record's own — the specification passages it was read out of — is
the aspect's own data (`{"on": true, "cites": […]}`, format 3). Three consequences are the
design:

- **There is no verb that creates a feature.** `step add --feature` is the door in and
  `step remove` the door out, which is what keeps a feature on the graph *by
  construction* rather than by a check that notices when it is not. The passage flags
  (`--document`, `--quote`, `--page`, `--strict`) live on that same author, because
  *authoring a step is one verb, many modules* and creating a feature is creating its step.
  Two steps may both be features; the one-instance rule went with the thing there was one
  instance of.
- **Four lint checks ceased to exist.** `feature.unplaced`, `feature.duplicate`,
  `feature.dangling` and `feature.unregistered` each named a state the model can no longer
  be in. What survives is the passage checks — a quote that no longer anchors — which are
  about the *spec* moving, not about the plan being half-made.
- **A work step still reaches the spec through the feature it flows into.** No link on the
  step: its briefing lists the features `scope.gatherers` says own it, with the passages
  they were read from. A citation that was N:M on requirements is a walk on features, and
  it cannot go stale when `dplanner step link` rewires the graph with no window open.

The trace is therefore graph → feature step → spec passage, one hop shorter than it was.
The quote is still checked against the document — on `step add --feature`, on `feature
cite`, and on every lint — through the spec module's `anchor_quote`, handed across by the
composition root: the aspect belongs to one module and the document to another.

**The catalogue moves onto the steps at open, and that needs an `absorb`.** One module id
served both the project's catalogue and the step's marker, and a per-entry converter never
sees the project — so `modules/feature/migrate.py` is the format's `absorb` pass
(`modules/notes/migrate.py` is the other one). A placed record's passages go onto its step;
its description joins the step's prose, with a *Catalogued as "…"* line above it where the
two titles differed, so nothing a person wrote is dropped and nothing is invented; an
unplaced record becomes the step it always meant to be. Three things are worth knowing
before touching it: **a created step's data goes on the `Step` before `add_child` and its
id is never returned** (the builder flushes a returned id with the `module_data` and
`module_text` aspects only, and a step that did not exist a moment ago has no directory
recorded yet — the project's *structure* mark is what writes the subtree); **the shelf is
reached from here**, because `migrate_shelved` runs afterwards and would stamp a shelved
marker to format 3 with its record id still in it; and **it writes into a living module's
namespace** (`step_description`'s prose, opt-out and file area, named as a string constant
and never imported) — the alternative, a `description` inside the feature entry, would
re-create exactly the duplication this removes.

One pleasing consequence: the retired `step_feature` module wrote a bare `{"on": true}`,
and FORMAT.md used to call its converter "the one that cannot finish the job" because it
could not mint a record. With no catalogue left to be missing from, `{"on": true}` is now
a whole answer — a feature that cites nothing.

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
directly belongs to it and to nothing else; that same token is what the lanes' drill-down
reads (below). The alternative — walking links upstream and
downstream — would have needed a rule per column pair to keep one feature's tests from
lighting another's, and it would have been wrong the first time a step sat in two cones.

**Lanes, each scrolling on its own, and links only in the gutters.** The tab is one
scene: a lane is a clipped column with its own offset and a thumb only while it
overflows, a link runs from one lane's edge to the next at the height of the cards it
joins, and a card scrolled out of view carries its end past the gutter's clip, so the
line is cut at the gutter rather than drawn over a caption. Cards paint with the
primitives the canvas paints with (`theme/cards.py`, moved there so two modules can share
them without importing each other), and every colour is read from the scene's palette at
paint time, so a theme switch costs nothing.

**The lanes are a drill-down, and the plan leads it.** They read *Milestones · Features ·
Spec · Tests & Docs*, and a lane stands only what the picks stand up: every milestone
always, the features the picked milestones gather (every feature while none is picked),
and — in the last two — what the picks *themselves* stand for. The first arrangement drew
the derivation's own order, spec first, with everything standing at once and everything
off the picked path faded to a fraction: a plan with a real specification opened as a wall
of passages and test cards, four fifths of it dimmed, and the question it answered ("what
became of this paragraph?") is the one a person asks *last*. A person opens this tab
holding a milestone or a feature in their head, which is why those two lead and why the
answers wait to be asked for. The rule that makes it one rule rather than four: an item
that can be picked carries its own `token` beside the features it serves, and a lane to
the right stands an item whose features meet the picked tokens. So a picked milestone
stands up the work it holds *directly* and never its features' whole spec — and a lane
with nothing in it says which pick would fill it, which is where the reader learns that
Ctrl-click adds another.

**The steps lane is asked for, and a lane that comes and goes reroutes the lines.** Between
the spec and its proof sits the work: the steps each pick holds, a feature's own step among
them, since that is where its tests and its document sit. *Show steps* on the strip stands
that lane there, so the picture reads requirement, work, proof from left to right. It is off
by default because the question the tab opens on is what became of the spec, and a lane of
every step behind every feature is the long way round to that answer. A line may only cross
the gutter between two lanes, so the trace records every pair that can stand side by side
— a document joins its features' tests directly *and* joins the steps they sit on, and each
step joins its tests — and the scene draws the pairs that are neighbours in the lanes
standing. That is the whole of the switch: no rule per arrangement, and nothing rebuilt but
the lines.

**A drill-down needs a selection, so a pick is a set.** A click picks within its own lane
and clears the lanes to its right; Ctrl (or Shift) adds to that lane, and picking a card
that lane already holds takes it back out; the ground and Escape clear. Picks the lanes
to their left no longer stand are dropped as the picks settle, so the feature you picked
under one milestone cannot survive picking another — and every picked card's step is
published, because picking three features is picking three steps and the Step verbs act
on all of them. Nothing is dimmed any more: a card that is not on the picture is not on
the picture. What lights is the *lines* into and out of a picked card, and the picture
carries fewer of them for it — the spec lane's document card is the hub on its right, so
a feature's tests hang off the document it was read from rather than off every passage
of it separately, which is the same claim drawn a dozen times.

**A view whose extent is laid out to its viewport must not report that extent as its size
hint.** `QGraphicsView.sizeHint()` *is* the scene rect mapped to the viewport, and this
scene's rect is laid to the viewport — so a splitter honouring the hint widens the view,
which widens the scene, which widens the hint: opening the tab pushed the index panel off
the left of the window and dragging the seam jumped. `CoverageView` returns a constant
instead. Two rules keep the rest of it still: the lane width is a whole number, so at any
width wider than the lanes at their narrowest the picture fits its viewport *exactly*
rather than by a rounding error that flickers the scroll bar on and off through a drag;
and a relayout for a viewport size the scene already has returns at once, because the
scroll bar coming and going resizes the viewport and would otherwise re-enter the layout.
When the lanes at their narrowest genuinely do not fit, the bar is honest and a pick
brings the lane it fills into view — a feature that filled a lane off the right of the
pane would look like a pick that did nothing.

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
  list this build owns (`log.LABELS`, a row each with its meaning and the index's heading
  over it — and nothing about who sees it, which is the graph's to say). Closed on purpose: an agent reading an index line must
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
- **Who sees a note is where it was made, with one stored exception.** Every label reaches
  the steps *after* the one it was made on — the cone the old handoff aspect walked, plus
  the step itself, since a re-run is a pick-up too. A note made on no step has nothing to be
  downstream of and reaches everyone whatever it wears; **so does one whose step is gone**,
  because a decision does not stop standing when the step that made it is deleted, and that
  is the same sentence generalised (`reaching()` is the only place that can know, so the
  live-id check lives there). `--reach project` lifts the one note that binds the whole plan
  and is stored only then (`FORMAT.md`'s absence rule). `reach.reaching()` is the one
  derivation.

  **This was settled twice, and the second time reversed the first.** Originally only a
  handoff used the graph: a decision, a spec change and a deferred item reached the whole
  project, on the argument that each is the project's and not a branch's. Then a 74-step
  plan with 320 standing notes was measured. The notes index was **73% of every briefing**
  — and 267 of its ~285 lines were *byte-identical on all 57 agent steps*, because four of
  the five labels bypassed the cone. An agent starting the fiftieth step read 171 decisions
  and 82 deferred items, almost none of them about its work, before reaching its own
  instructions. The argument was not wrong about what a decision *is*; it was wrong about
  what a briefing is *for*. The graph already answers "which earlier work does this step
  build on", and a project whose topology orders two steps that would touch the same file —
  which is the shape DPlanner's own plans declare — has already said that a decision binding
  you is a decision upstream of you. So the `reach` column came off `Label` entirely rather
  than keeping one value in five rows: a one-value column is an invitation for a future row
  to differ, and the point is that it cannot. Index 33,131 → 2,715 chars median, whole
  briefing 47,157 → 17,497.

  **Two pieces of prose had to follow, or the change would have quietly taken something
  away.** The briefing's epilogue tells an agent to record a `decision --step <key>`, which
  now reaches only the work after it — so the epilogue says what the reach is and when to
  add `--reach project`. And the index's own lead-in names `note list` as the whole log,
  because with reach narrowed *and* the index capped, an agent that suspects it is missing
  something needs a verb. A rule that removes what somebody could read owes them the way
  back to it.

  One thing deliberately left alone: `dplanner report` carries every standing note,
  uncapped. A publication is read by a person with a page and a scrollbar, not by an agent
  with a budget.
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

### The default shape rides through the same door

A project's topology says how *its* graph is shaped. Nothing said how a graph is shaped at
all — no template, no seed, no notion of a morphology anywhere in the tree — so every project
invented one, and an agent handed a spec produced whatever DAG it felt like. That is now
`cli/shaping.md`: one start, milestones in a chain, each release's work branching out of the
milestone before it and collecting into its own, sequential milestones and parallel steps.
The project's own text wins wherever the two differ; where it is silent, the default applies.

**The gate had already built the door.** `topology show` is the verb the graph-editing verbs
refuse until, so it is run by every agent about to shape a graph and by no agent that is not
— which is exactly the audience a shaping document has. Printing the default there costs an
executing agent nothing and needs no new mechanism, no new verb and no new flag on the ones
that shape. `--brief` is the opt-out, for a person or a script that wants the project's text
alone; the flag chooses what is printed, never what is recorded.

Three alternatives were considered and each is worth knowing about, because each looks
right until you follow it through.

**A third file bundled with the skill**, pointed at from `SKILL.md` the way `reference.md`
is. It fails on reach: the skill installs to `~/.claude/skills/dplanner`, and this build
runs Codex and OpenCode as readily as Claude. A shaping rule those two never see is a rule
half the harnesses do not have. It also puts the same bytes on two channels, and
`generate()`'s contract — two files, because they are read differently — stops being true.

**Seeding a starter topology at `project create`.** The obvious move, and the trap: the
topology reaches *every agent briefing* as a project section, so a 17 KB house document
written into `module_text["spec"]` would be paid for again on every step anybody ever
executes, forever. `domain/seed.py` already argues against seeding anything; this is the
sharpest instance of why. The default is read beside the project's text, never written into
it, and the guide's own last section tells an agent the same thing in the same words.

**Hashing what was printed.** The gate records the digest of the topology it read. It would
be natural to record what `topology show` *printed*, and it would mean the day `shaping.md`
gained a comma, every project on the machine became unread and every agent's next graph edit
was refused. What is recorded is the project's own text, and `--brief` records it too.

**The premise's one soft edge**, stated here rather than discovered later: `spec import`,
`spec show`, `spec diff` and the `coverage` verbs are not gated, so an agent asked only to
import and cite a spec never passes the door and never reads *From a spec to a graph*. That
is the right call — citing is not shaping, and the verbs that turn citations into steps are
all gated — but it is the assumption the whole delivery rests on, and if a future verb makes
a graph without declaring `edits_graph`, this is what breaks.

The window reads the same asset under the Specs tab's topology editor, so the person writing
the topology and the agent reading it can never be looking at two different documents.

### Two shape checks, and only one of them earned lint

The default says a graph has one beginning and that releases are a chain, and the obvious
next move is to have `project lint` enforce it. Two candidates were built and measured
against DPlanner's own plan and a real 74-step one, because lint exits 1 and gates a
handover: a check that fires on a shape somebody meant is worse than no check.

`scope.crosses-milestones` kept its place. It is `scope.shared` asked of what *partitions*
the graph rather than what *groups* it — one walk, two stopping rules, one report shape —
and because a release's cone stops at releases, two gatherers can only mean two of them
reach the step without passing a third. On the 74-step plan, whose milestones are a chain,
it said nothing. On DPlanner's own plan it found four steps each counted whole by two
releases at once, which `progress show` was double-counting in days. It is guarded on the
project having chained its releases at all — `scope.ungathered`'s rule, that a project
which never made the claim cannot fall short of it — so two releases run side by side on
purpose are never nagged.

`graph.unrooted` did not. It fired seven times on a plan its author is content with, and
the half of it that was worth having — work of a later release starting from nothing
instead of from the release before it — is what `scope.crosses-milestones` already reports.
The bare fact, which steps wait on nothing, is `order show`'s first wave. So the rule lives
in the guide, where a recommendation belongs, and lint says nothing about it: the same
judgement `.claude/rules/collectors.md` records for uncovered spec text, which is a report and never a lint.

`graph.orphan` is not part of that bet and was never in doubt. A step with no edge in
either direction is on no graph, the canvas already rings it in the refusal red — the one
mark that says *something is wrong here* — and lint saying so is the two surfaces agreeing.
It is silent on both real plans. Its derivation, `ports()`, moved from the canvas's
`marks.py` into `domain/ordering.py` for it: `modules/projects/cli.py` may not import
another module, and a second copy of a derivation is the thing that goes stale.

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

**A coalesced rebuild owes the user the fact that it is owed.** The delay buys the
keystroke its speed by *deliberately* showing a stale picture for 300 to 500 ms, and a
surface that shows one in silence is indistinguishable from one that is wrong. So every
debounced view carries an `UpdatingIndicator` at the right end of its strip
(DESIGN.md's *Signalling*), and the thing it follows is the `Debounced` itself:
`pending_changed` goes True on the first trigger of a burst and False when the action has
run — *or raised, or been cancelled*. That last clause is why it is a signal on the
mechanism rather than two statements in the view. The Time tab had those two statements
for a year — `show()` in a wrapper around `trigger()`, `hide()` as the first line of the
rebuild — and they were correct only by inspection: nothing paired them, a rebuild that
raised would have left the label up, and the wrapper existed for no other reason. One
parametrized test now asserts the property for every view at once, which is the shape a
rule wants; per-view wiring is three lines and a rule followed by whoever remembers it is
what the primitive replaced.

The canvas is the deliberate exception: at 0 ms it settles once per event-loop turn, so
there is no span for a person to read and an indicator would only flicker.

**Prose reaches the canvas after a settle.** A card shows no prose but whether an agent
instruction exists — the spark — yet every keystroke in a description ran the whole sync,
each card's accents derived before the scene could find that nothing had changed. So
`text_edited` reaches the canvas through a settle of its own and every other signal through
the 0 ms one: a title still lands as it is typed, the spark appears one settle after an
instruction's first character, and behind Step Details, where a settle waits for the modal,
typing costs the canvas nothing until the dialog closes. The settle carries no indicator —
it almost never changes a card, and a spinner over the graph at every pause would announce a
redraw that is not coming. Filtering *which* prose a card reads was the alternative and was
not built: the composition root would have to keep a list of text keys in step with
`step_accent`, a second answer that drifts the day an accent reads prose nobody named.

**And the indicator is a motion, not a word.** It carried *Updating…* for one step. A word
at the end of a control strip is the only prose on a row of glyphs, it is four times the
width of what it replaced, and it is the one thing on that strip a translation would have
to reach; so it is the same three-quarter arc a working button turns, with the words in its
tooltip. The point is not the pixels saved — it is that *something is running here* becomes
**one** thing to recognise wherever it appears, rather than a word in one place and a
turning glyph in another. `Spinner` therefore drives either: a button or toolbar verb, whose
glyph it borrows and gives back, or a bare `QLabel` that *is* the slot and shows nothing when
idle. `UpdatingIndicator` is the second of those with a `Debounced` attached, which is why
wiring a view stayed three lines when the look changed.

**A settle behind a modal waits for it.** Step details moved out of the side panel into a
modal dialog (`steps.details`), and coalescing still let every pause in typing rebuild the
window behind it. Measured on a real plan of 80 steps and 262 spec citations, typing a
sentence into the dialog froze the window for **630 ms** at every pause with the graph, the
Order table and the Time tab open, and for **1.25 s** with every tab open — the Problems
reading (545 ms) and the Coverage tab (573 ms) each re-judging every citation, for views
nobody could see past the dialog or act on until it closed. So a `Debounced` asks, when its
timer falls due, whether a modal dialog is up with its owner outside it, and if so starts
the timer again instead of running. Three choices make that one rule rather than a flag per
view. **The owner is the parent chain** — the first `QWidget` above the `Debounced` — so the
dialog's own sections (its Agent tab's briefing, its Tests tab) go on settling, the docked
panel's copies behind it wait, and an owner that is no widget at all, a service like the
Problems reading, stands behind every dialog. **Only a settle waits**: a 0 ms run promises
the next frame, and the context's announcement is one — holding it would leave the dialog's
own action states a keystroke behind. **Nothing is dropped**: the run stays pending, so the
view's indicator stays up and `flush_all` still settles it, and it runs within one quiet
spell of the dialog closing — once, 20 to 36 ms a view on the same plan. It is a re-armed
timer rather than a close hook because a hook would need every modal to call it —
confirmations, file pickers, the expanded editor — where the check is one
`activeModalWidget()` per due settle. With the citation walk fixed too
(`NOTES-FOR-APPFRAME.md` §46), the longest block while typing in the dialog on that plan is
**28 ms**, with three tabs open or all of them. `scripts/synthetic_library.py` now gives
every project a spec its features quote, because a citation of a missing document costs
nothing, and that is how the scaling harness missed all of this.

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

**An action's state is read on every announce, so it may not derive anything over the
project.** The day compiling documentation moved to a launched agent (2026-09-13), the
*Compile Out of Date* entry gained a label that counts what is due — and its state
callback computed that count by walking every collector's cone and digesting its sources,
on every announce. A title keystroke announces once, so the context refresh went from a
flat 4–6 ms to 198 ms at 400 steps in one commit; the menu bar re-evaluates every state
per announce, and one slow state taxes every gesture in the window. The same rule as the
keyring and the subprocess above, broken by a pure derivation, which is the version
nobody notices until the plan is large.

The fix is the shape the Problems count already has: the module keeps the frontier per
project as last *settled* — a `Debounced` at `SETTLE_MS` recomputes it for the projects
somebody asked about, every library signal forgets what was settled, and the state reads
the last answer (`DocsModule._frontier_of`). A settle that changed an answer announces the
context, so the label catches up one settle after the burst; a project never asked about
reads *checking…*, disabled, for that one settle. The gesture (`_compile_stale`) computes
fresh — it is one click and may pay the walk. In the suite's immediate regime the trigger
runs inline, so the answer a test reads is always current and the settle never re-enters
the announce it was read from (`_reading`). `collect.frontier` is the derivation, one
walk per collector where the state made three; `docs status` reads `compiled_state` over
sources it already holds for the same reason.
`tests/modules/test_docs_compile.py` asserts, in the deferred regime, that ten reads walk
nothing, that a change leaves the label as it was until the settle, and that the settle
announces.

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
last section that says what DPlanner is and how to open the plan. `.claude/rules/cli.md` has
the rule in its short form (*A report is a publication, not a record*); this is why it is
shaped the way it is.

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


## The Windows check is a disposable target, not a pipeline

DPlanner has sixteen files with a platform branch and, until this step, no machine that ran
them. Two of those branches — `_windows_process_alive` and the PowerShell `.lnk` writer —
could not be reached by any test on Linux at all. The question was never *whether* to test
Windows; it was what shape the answer takes.

**It is a capability, not a pipeline.** Windows is checked rarely and on purpose: bringing a
VM up costs RAM, disk and a person's attention, and a three-platform CI matrix would run it on
every push to buy a signal nobody reads between releases. So `scripts/windows_check.py` is a
thing you *run*, with every verb standing alone — the fix loop is `sync`, one check, read it,
repeat, and a harness that re-boots or re-syncs each time round is one nobody uses twice.

**The cheap guard runs everywhere, every time.** `uv run mypy --platform win32` is the fourth
check in CLAUDE.md because it is the only reader of the Windows half that costs thirty seconds
and needs no VM: mypy skips a `sys.platform == "win32"` branch entirely on the host platform,
so that code is otherwise read by nobody. It found four real errors the first time it ran.
That is the trade the missing CI is paying for — a fast, partial signal on every machine
instead of a slow, complete one on a schedule.

**The default target is the developer's own VM, and the harness never recreates it.** Omarchy
ships `omarchy-windows-vm`: an installed, persistent Windows 11 with the developer's account
and a 512 GB disk. Building a second box beside it would cost a 20–30 minute install, ~12 GB
of RAM and tens of GB of disk to answer the same questions. What it lacks is an SSH port, and
adding one means recreating a container that belongs to the developer rather than to this
check — so the transport is the shared folder that container already binds. `runner.ps1`
watches an inbox, runs each job, writes the log and exit code back. Crude, and it buys three
things nothing else does: no new ports, no recreation, and **every job already inside the
interactive session** — which is the whole interactive half, free. A process started over
Windows OpenSSH lands in the SSH logon session, where a window it opens paints to a desktop
nobody is looking at and `CopyFromScreen` returns black. The `--target box` transport is SSH
against a throwaway container, and it exists because a check that can only run on one person's
machine is not a check.

### Bytes on disk are stated, never inherited

`write_atomic` passed no `newline` and no platform ever complained, because every platform
that had run it agreed. On Windows `write_text` translates `\n` to `\r\n`, so the same plan
saved there came back as a whole-file diff against the same plan saved anywhere else — a
format built to be shared and merged, quietly rewritten line by line by one platform. The
same class of bug, opposite direction, had already shipped in the agent launcher: a CRLF-joined
`run.cmd` written through a translating write produced `\r\r\n`, and the test that should have
caught it could not, because `read_text` normalises every line ending it reads. **A test about
bytes reads bytes.** FORMAT.md's *Bytes on disk* is the rule; `encoding="utf-8"` belongs beside
every `newline` for the same reason — Windows decodes text as the console code page, and this
project's prose is full of em dashes.

### A frozen build is onedir because Qt is LGPL

`dplanner.spec` builds a directory, never a single file, and that is a licence decision rather
than a preference. Qt for Python is LGPL v3, whose section 4 permits conveying a combined work
only if the user can relink it against a modified library. A onefile build unpacks into a
private temporary directory that is deleted on exit, so somebody who builds their own Qt has
nowhere to put it. onedir keeps the Qt libraries on disk where they can be swapped, and
`upx=False`/`strip=False` serve the same clause — a packed or stripped library is not a
drop-in replacement target. PyInstaller itself is GPL-2.0 *with an exception permitting closed
and commercial builds*, so the frozen output carries whatever licence we choose.

**Three things the import graph cannot see, and each fails silently.** Distribution metadata
(Help ▸ About reads every component's licence from it, and the LGPL row is the one row an
acknowledgement must never get wrong), keyring's entry-point backends (without them
`backend_problem()` reports no keychain on a machine whose Credential Manager works perfectly
well), and pdfium's native library, which is loaded by path from beside its own bindings
module. None of them is a build error; all three are a working-looking build that is wrong at
run time. So the proof is a run — `dplanner checklist show` from the frozen executable — and
`pyinstaller` is a dev dependency on every platform precisely so a Linux developer validates
the spec between the rare Windows builds. `tests/test_freeze.py` holds the manifest to one
rule — *a data file lands at its own package path* — because that is the single thing that
makes `importlib.resources.files` and `Path(__file__).parent` agree inside a bundle.
