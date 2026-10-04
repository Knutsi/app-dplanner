# CLI — the entry word, install, the checklist, the topology gate, the skill and reports

The reasoning behind `.claude/rules/cli.md`: the rules there are the short, imperative form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## The window is a word, and everything else is the CLI

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
too. So `entry.py` checks the shell's markers (`domain/agents.py`'s `shell_marker`, each
harness's first) before it opens a window and refuses with the reason. This *is* the vendor-variable check the list above declined — but for a
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

## Installing is one act, and the pieces stay

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

**The skill is written where every agent looks.** `SKILL.md` is an open format
(agentskills.io) that Claude Code, Codex, OpenCode, Cursor and Gemini CLI all read; what
differs is only the directory each one looks in — Claude Code and OpenCode `.claude/skills`,
Codex and OpenCode `.agents/skills`. So the generated skill is one file and
`cli/skill.py`'s `SKILL_HOMES` is one tuple of where it goes, and install, status and
uninstall run over all of them: the skill is *installed* only when every agent on the
machine would read this build, because one home current and the other three weeks old is
exactly the drift the one act exists to make visible. A per-agent flag would have been a
second question no surface asked.

**DPlanner is installed by a person through uv, not by a skill.** A hand-written bootstrap
skill once did it: a Claude Code plugin an agent read and followed, installing git and uv,
cloning, and running `install all`. On Windows it did not get the program onto the machine,
and nothing here could catch that. The suite held the skill's *text* to the installer, but
only an agent following it on a real machine tested the *act*. It was removed. The README
now gives the route a person runs, `uv tool install git+https://github.com/Knutsi/app-dplanner`
and then `dplanner install all`, which needs no checkout and updates with `uv tool upgrade`.
That route had a bug of its own. `install all` from a build that is not a checkout reinstalled
the command by name, which rewrote uv's receipt from the git URL to a bare `dplanner` that
PyPI does not have, so an upgrade then followed nothing. An installed build now leaves its
command alone and names the upgrade (`cli/install.py`'s `_install_command_piece`). A packaged
installer that updates itself from GitHub releases is the next step, and it needs the CI
this repository deliberately does not have.

## A checklist is a registry of probes, and every module owns its own

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
alternative — a verb inside `steps/cli.py` with injected predicates — would put a
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
composition root assembles the list into `steps_cli.commands(step_authors=…)`, exactly
as it assembles lint's checks. The shape lives in `cli/authoring.py` for lint's reason: the
contributing modules may not import each other, and `cli/` sits below them all.

Two decisions carry the weight. **The transaction is the rollback**: an author that raises
aborts the whole run, and `open_library` flushes nothing — the step included — so no author
writes compensation code. Any future refactor that flushed eagerly mid-run would silently
break every author's atomicity; this paragraph is the guard. And **stdin is claimed before
it is read**: each author declares whether its parsed flags would consume stdin, so two
`--…-file -` on one call are refused before either swallows the other's document.

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
because `cli/` must reach it) — never in the plan, which is shared. That file is
`reads.json`, and it holds more than topologies now: the house format of a test body is read
through the same record under a key of its own (*The test format is read before a test is
written*), which is why `ReadRecord` is a shape separate from the gate written over it. The gate compares that
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
`marks.py` into `domain/ordering.py` for it: `modules/steps/cli.py` may not import
another module, and a second copy of a derivation is the thing that goes stale.

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

**Reports are written on request, never on Save.** Save used to publish before it committed:
the sync module asked the reporting module for a publication per dirty repository and
committed `reports/` in the same version as the plan, and a project's reporting location
got a scoped commit of its own. Two people saving one shared plan repository then
conflicted on every pair of concurrent saves — not over the plan, which merged cleanly, but
over the generated pages: each Save re-renders a project's page with that day's schedule,
so both sides rewrite the same lines of `<slug>/index.html` and `summary.js`. A rebase
could only regenerate them, so they were never worth committing. Now Save records the plan
alone (`commit(message, also=(POINTER_FILE,))`), and the site is written when someone
wants it: *File ▸ Export ▸ Report Site (Folder)…* writes every project of the focused
project's plan repository into a picked folder, on the reporting module's worker like any
export, and `dplanner report site` writes it from a terminal. Neither commits. A shared plan
repository is best off with `reports/` in its `.gitignore`; publishing the site for
readers, for example to GitHub Pages, is a job for CI running `dplanner report site`, not
for every person's Save.

**The site's index is a function of the project set, never of any project's state.** Under
`reports/` each project owns its own directory (`<slug>/index.html`, `<slug>/summary.js`);
`index.html` is rendered from the sorted set of `*/summary.js` present on disk as a static
page with one `<script src>` per project and a few lines of client-side rendering —
`<script src>` works from `file://` and GitHub Pages alike, where `fetch()` does not. Its
bytes change only when a project joins or leaves, so two writers of two projects never
both touch it, and a pull that brings a colleague's project is picked up by the next run. The directory name is a constant, not a setting: the
window's preferences are QSettings, which `dplanner report site` cannot read, and a
per-user name would let the two surfaces write two sites into one repository.

**Paper is the same report, not a second one.** The PDF is `QTextDocument` printing to
`QPdfWriter` — pagination for free — with the chart, timeline and graph rendered from the
very SVG strings the page inlines, through `QSvgRenderer`. It is window-only by decision:
PySide6-Essentials has this and no Chromium, and adding a PDF library for the CLI was
judged against the dependency rule; the page carries print CSS for anyone at a terminal.
The XLSX writer and the markdown renderer are stdlib for the same rule (`core/xlsx.py`,
`core/markdown.py`, in the spirit of `core/png.py`).

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
