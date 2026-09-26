---
paths:
  - "src/dplanner/entry.py"
  - "src/dplanner/cli/**"
  - "src/dplanner/core/user_path.py"
  - "src/dplanner/modules/*/{cli,checks,report}.py"
  - "src/dplanner/modules/{install,checklist,reporting}/**"
  - "tests/cli/**"
  - "tests/modules/test_{install_dialog,checklist_dialog,module_checks,reporting}.py"
  - "scripts/{render_checklist,render_sample_report,render_topology}.py"
  - "plugins/**"
  - ".claude-plugin/**"
  - "tests/test_bootstrap_skill.py"
---

# CLI — the entry word, install, the checklist, the topology gate, the skill and reports

- **`dplanner` is the CLI; `dplanner window` is the application.** `entry.py` dispatches on
  the first command word — no terminal test, no environment variable — so an agent's bare or
  mistyped call gets the help and exit 2, never a window on the developer's desktop. Qt's
  `-style`/`-platform` follow the word; `spawn_instance` and `python -m dplanner` go through
  the same door; the word is not a noun and the skill never names it
  (`tests/cli/test_entry.py` reserves it). **And the word refuses inside an agent's
  shell** (`AGENT_SHELL_MARKERS`, one row per agent CLI known to mark its shell): a window
  that is an agent's background process ends with the agent's turn and makes every agent
  it launches a *child session* of the first — no transcript, ended with its parent — which
  is how one stray window took four agents down. Not a dispatch rule, a guard on who owns
  the window. **`dpw` is the word typed for you** — a `gui-scripts` entry
  (`entry.window_main`), so on Windows it is an executable with no console behind it — and
  `dplanner desktop install` writes the launcher an applications menu opens on it:
  `cli/desktop.py`, one class per platform (a `.desktop` entry named after `APP_ID`, an
  app bundle, a Start Menu shortcut through PowerShell) behind one contract, each testable
  on every other platform. Neither word reaches the skill. `ARCHITECTURE.md`'s *The window
  is a word* has the reasoning.
- **The window repairs its PATH; the CLI never does.** A window opened from a desktop
  launcher is started by the session launcher, not a shell, so it inherits launchd's
  `/usr/bin:/bin:/usr/sbin:/sbin` on macOS — and every one of the ~26 `shutil.which` call
  sites then answers `None` for `gh`, `uv`, `git` and every agent CLI, on a machine where all
  of them work from a terminal. `core/user_path.py`'s `repair()` puts the user's PATH back
  once, in `entry.py`'s window branch and nowhere else: a verb is always run from a shell
  that already has it, and a login-shell subprocess per invocation is a real cost to the
  agent driving the CLI. **The word is what tells the two apart** — one more thing the
  window-is-a-word dispatch is good for. Four rules keep the repair safe: it asks `$SHELL -lc`
  and never `-lic` (a login shell reads the `.zprofile` `brew shellenv` wrote itself into; an
  *interactive* one also sources nvm, pyenv and a prompt framework, seconds for an answer it
  already has); it **appends and never reorders or shortens**, so a path the process was
  given deliberately still wins and calling twice does nothing; a missing `$SHELL`, a
  non-zero exit and a timeout are all the same answer, falling through to `KNOWN_PREFIXES`
  rather than failing; and **the prefix list is an argument**, because half of it is absolute
  and exists on the machine running the suite. `cli/desktop.py`'s `bundle_script()` is the
  same fix one layer out and **quotes twice** — the hand-over is a `-c` argument inside a
  script, so a home directory with an apostrophe ends the inner string early when it is
  quoted once. The checklist's *PATH from your shell* row **reports the repair, never the
  tools**: `repair()` remembers what it did and the probe reads that (no subprocess, the
  Problems count's arrangement), because each tool that matters already has a row and a
  second list of the same names is two rows able to disagree about one fact. Its only
  failing state is the one worth a row — a launcher started the window and the login shell
  would not answer — and it **advises rather than requires**, since a thin PATH is a degraded
  window, not an unusable one, and `required` means exit 1 and a probe at every start.
- **Installing is one act, and the pieces stay.** The command, the desktop launcher and the
  agent skill go in together — `dplanner install all`, `install status`, `install remove`
  and *Tools ▸ Install DPlanner…*, all four over `cli/install.py`'s one reader (`items`,
  **no subprocess**: the dialog refreshes on it and the checklist will probe with it) and
  one writer (`apply`, which reports every piece rather than stopping at the first
  failure). `desktop …` and `skill …` remain as the pieces it is made of. The reader lives
  in `cli/` and not in the module because `cli/` may not import `modules/`. Two rules keep
  the command from shadowing somebody else's install, and both say so rather than acting:
  **a worktree build never repoints it** (which is what makes the verb safe for an agent to
  run in its own worktree) and **a `dplanner` uv did not install is left alone** (`uv tool
  dir --bin` against the resolved command's directory — uv's answer, never a guess at its
  layout, and **compared normalised**: uv spells it `~/.local/share/../bin` and `which`
  says `~/.local/bin`, one directory that `Path` equality calls two; `desktop.normalised`
  is the one place both spellings go through, and it stays lexical so the launcher keeps
  pointing at the symlink uv maintains). Removing takes out the launcher and the skill and names `uv tool uninstall` for
  the command rather than uninstalling the program that is running. The command's state is
  `installed` or `missing` and never `stale`: whether the one on PATH came from this build
  cannot be told without running it. `ARCHITECTURE.md`'s *Installing is one act* has the
  reasoning.
- **A checklist is a registry of probes, and every module owns its own.** Whether this
  machine can run DPlanner is a fact about every feature at once, so `cli/checklist.py` owns
  the shapes (`MachineCheck`, `Reading`, `Remedy`), the `GROUPS` order, the report and the
  exit code; each owning module exports `checks()` from its own Qt-free `checks.py`; and
  `_machine_checks()` in the root assembles the tuple *Tools ▸ Setup Checklist…* and
  `dplanner checklist show` both read — `cli/lint.py`'s arrangement exactly. **A probe
  answers two states and the tone is derived**: `Reading` is ok-or-not plus the words, and a
  failure is the error tone when `required` and information otherwise, which is
  `signalling`'s four tones with none added. **`required` means the verb exits 1 and the
  check runs at every start** — the same thing said twice, which is why a required probe may
  not touch the network or shell out for long, and why git, the command and the skill are
  the only three. **A remedy names an action id**, never a widget: the modal runs it through
  `ActionRegistry.run` and the terminal prints the command instead, so a module offers its
  own fix without being imported. **The count in the menu label is read, never probed** —
  a state callback may not shell out — and **the machine is greeted once**, then only while
  the person left the switch on and something required is missing. **A remedy may name
  `packages` instead of a `command`** and `install_line` makes the line *this* machine
  would run — two tables (`MANAGERS`, `FAMILIES`), a manager offered only when it is on
  PATH, and the family read from `/etc/os-release`'s `ID` then `ID_LIKE`, so **a
  derivative needs no row of its own**: Omarchy is an Arch machine because it says so. A
  check that cannot name a line it is sure of names none and carries a `url` instead.
  **Muting a row changes what nags, never what is true** — the `⋮` keeps it per user, the
  row still says what it found, and the CLI never reads it, because an agent gating on
  `checklist show` must not inherit somebody's decision to live with a gap. And **it is
  the one dialog that prints a heading** (`DialogFrame.set_heading`), because it is the
  one that opens itself; a dialog a gesture opened must not call it.
  `ARCHITECTURE.md`'s *A checklist is a registry of probes* has the reasoning, including
  why `framework/secrets_store.py` had to become `core/secrets.py`.
- **The topology is read before the graph is edited.** A project's topology (`dplanner
  topology set|show`; the Specs tab's pinned first row; `modules/spec.md`) says how its
  graph is shaped, and every CLI verb that reshapes a graph declares `edits_graph` on its
  `CliCommand` — `cli/gate.py` then refuses until `topology show` has recorded the current
  text's digest in the per-user `config_dir()/reads.json`, and refuses again when the text
  changes or when there is none. The skill marks those verbs; the window is never
  gated; the test suite's registry runs behind a gate with no record file. Declare it on a
  verb that changes shape, never on one that changes content.
  **And `topology show` prints the house default beside the project's text** — one start,
  milestones in a chain, work branching out of one and collecting into the next
  (`cli/shaping.md`, read by `cli/shaping.py`'s `guide()`). The gate made that verb the one
  door every shaping agent goes through and no executing agent does, which is why the
  default is delivered there rather than in the skill — the skill is Claude's alone, and
  Codex and OpenCode shape graphs too. **It is printed, never stored**: a topology reaches
  every briefing, so a house document seeded into one would be paid for again on every step
  anybody ever executes. The project's own text wins wherever the two differ, `--brief`
  prints it alone, and the recorded digest stays the project's text — hashing the default
  would un-read every project on the day `shaping.md` gained a comma.
  `ARCHITECTURE.md`'s *The topology is read before the graph is edited* has the reasoning.
- **A house document is read before what it governs is written, through the same record.**
  The second door `cli/gate.py` holds: a verb that writes in a document's shape declares
  `reads_guide` naming the `<noun> <verb>` that prints it — `test add` and `test set` name
  `test format` (`modules/testing/format.md`), and the skill marks them `‡` — and the
  composition root builds the `GuideGate` and hands the printing verb `note_read`, exactly
  as it hands `topology show` the topology gate's ear. `ReadRecord` is the one per-user
  file both doors stand on (`reads.json`, keys namespaced `topology:<project id>` and
  `guide:<verb>`); a record with no file refuses nothing, which is what the suite runs
  behind. The difference from the topology is what the digest is *of*: a project's own text
  is read per project, a build's own document once per machine. Declare it on a verb that
  writes prose somebody else must follow, never on one that reads, files or records a
  result. `ARCHITECTURE.md`'s *The test format is read before a test is written* has the
  reasoning, including why screenshots stayed a markdown convention.
- **The skill is generated, never written.** `dplanner skill install` renders `SKILL.md` and
  `reference.md` from the command registry, so they cannot describe a command that does not
  exist. Edit `cli/skill_preamble.md` for the hand-written half; never the output.
  **The skill says what every agent must know; how to shape a graph is what the door to
  shaping says** — the spec loop, cutting steps, linking, sizing and the spatial loop live
  in `cli/shaping.md` and reach an agent through `topology show`, not through the skill.
  What stays is an executing agent's, safety rules included.
  **Its command list is an index: one line per noun naming its verbs**, a `†` on the ones
  that read the topology first, a `‡` on the ones that read a house format first, and a
  legend line per mark — all three projected from the registry — because a summary per verb
  was a third of a file loaded every session and said what `reference.md` and `--help` both
  already say.
  A verb the skill must not teach carries **`in_skill=False`**, the CLI twin of
  `ActionSpec.in_menus`: registered, runnable, described by `--help` like any other, named
  by no generated file. The region verbs are what it exists for. `ARCHITECTURE.md`'s *The
  skill's command list is an index, not a manual* has the reasoning and the measurement.
- **The skill is written to every home an agent reads, and the one that installs DPlanner
  is hand-written.** `SKILL.md` is an open format, so one generated skill serves Claude
  Code, Codex and OpenCode; `cli/skill.py`'s `SKILL_HOMES` names the directories they read
  (`.claude/skills`, `.agents/skills`), and install, status and uninstall run over all of
  them — *installed* means every agent on the machine reads this build. Add a home to the
  tuple, never a per-agent flag. The bootstrap skill
  (`plugins/dplanner/skills/dplanner-install/SKILL.md`) is the one exception to *generated,
  never written*: it runs before DPlanner exists, so it is written by hand, held to the
  installer by `tests/test_bootstrap_skill.py`, and lives in the Claude Code plugin at
  `plugins/dplanner` — the one path a marketplace install, Codex's `$skill-installer` and a
  raw URL all reach. It warns that DPlanner is a work in progress *before* it installs, and
  the plugin carries nothing else; its `version` is `APP_VERSION`. `ARCHITECTURE.md`'s *The
  skill is written where every agent looks* has the reasoning.
- **A cross-feature verb lives in `cli/`, fed by the composition root.** `cli/aspects.py`,
  `cli/lint.py` and `cli/authoring.py` are the examples: the verb owns the shapes and the
  report; a module contributes by exporting Qt-free pieces (an `AspectSpec`, a
  `lint_checks()`, a `step_author()`) from its own package, and `default_cli_commands()`
  assembles the list. `cli/` never imports a module. `ARCHITECTURE.md`'s *Lint belongs to
  no feature* and *Authoring a step is one verb, many modules* have the reasoning — the
  latter includes why the CLI transaction, not per-author rollback, is what makes a
  multi-module `step add` safe.
- **A report is a publication, not a record.** `cli/report/` is the plan as one HTML page
  for people with no DPlanner: **modules say, one renderer shows.** A module that has
  something to say exports a Qt-free `report_source()` from `modules/<m>/report.py`,
  returning parts from `cli/report/parts.py`'s vocabulary — figures, tables, chart series,
  timeline spans, prose, the graph, per-step *facets* — and the root assembles the tuple
  (`_report_sources`) for both `dplanner report` and the window. **Every part is plain
  data** (a test walks it): the window builds on the GUI thread and renders on a worker,
  the CLI inline, and the same plan gives the same bytes. **A chart part is the Time tab's
  page said as data** — a `Chart` of `Plot`s (`shift`, `scope`, `done`) over one axis, with
  the `Stretch`es they read, built from the tab's own `present.py` — so the page and the
  paper draw what the tab draws; `drawings.py` draws with no `clipPath`, because the PDF
  goes through a renderer that honours none. **Drill-down is the step id**:
  the page has one selection, and a facet carries the id rather than the module knowing
  the graph. **Save publishes before it commits**: the sync module asks the reporting
  module for a publication per dirty repository, runs it inside the save task and commits
  with `also=paths`, so `reports/` lands in the plan's own version; a project naming a
  **reporting location** publishes there instead — `website.SiteTarget`, an
  `ExtraPublication` committed scoped to the site in that repository, `dplanner report
  site` writing to the same target and `--out DIR` anywhere; a publication that
  raises is logged and the plan is saved without it; the switch (Settings ▸ Reports) is per
  user and on by default. **The site index depends only on the project set** (one
  `<script src>` per `reports/<slug>/summary.js`), never on a project's state, so two
  writers never conflict over it; the directory is a constant because QSettings cannot
  reach the CLI. PDF is `modules/reporting/paper.py`, window-only, over the same SVG.
  `ARCHITECTURE.md`'s *A report is a publication, not a record* has the reasoning and
  the measurements.
