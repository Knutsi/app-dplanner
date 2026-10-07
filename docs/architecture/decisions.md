# Decisions — how the rules came to be

The area files beside this one state each rule as it stands. This file is what they replaced:
the earlier shape, the incident or the measurement that moved it, and when — oldest first,
dated by the commit that first wrote the passage. Each entry ends with the section that holds
the rule now. Nothing here binds an edit; read it when a rule looks arbitrary and you want to
know what it cost to learn.

A new entry goes at the end, under the date it was settled, whenever a rule in an area file is
rewritten rather than added to.

## 2026-08-26 — Edges diff by key, like nodes

Nodes and edges were two rules once: nodes diffed by key, edges rebuilt wholesale on every
sync. The second rule was exactly what made edges unselectable, so making them selectable
removed a rule rather than adding one. Now: `graph-model.md`'s *The graph, and what it stores*.

## 2026-08-29 — Estimate and description became blocks of one Details tab

The first things a step should show — what it is, how big it is, what it looks like — were
scattered across an Estimate tab and a Description tab, each one click away. They became
blocks of one Details tab, registered into `services.step_details`. Now: `step-panel.md`'s
*The step editor is a modal*.

## 2026-08-29 — A step's separate agent instruction became the opt-out

A step carried two prose fields, a description and an agent instruction. The two said the
same thing twice, an agent driving the CLI set one when it meant the other, and a step with
a rich description and no instruction could not be briefed. The duplication was deleted
rather than documented harder: an agent step is briefed with its own description, and a
described, uninstructed step that had rendered `## Description` renders the same text as
`## Instructions`. Now: `agents.md`'s *The description is the instructions*.

## 2026-08-31 — `scope.gathers-nothing` generalised `check.covers-nothing`

The lint check for a collector with nothing behind it was a check's own,
`check.covers-nothing`. When features and milestones became scopes too it was generalised to
`scope.gathers-nothing`. Now: `collectors.md`'s *A step two features both wait on belongs
to both*.

## 2026-09-01 — Selection stopped being a thicker border, and never became a wash

Selection used to be a one-pixel-wider border in the accent, and on a graph of twenty nodes
it was genuinely hard to see which one you had. A wash of the accent over the body was the
first replacement tried, and it was dropped because a selected milestone stopped being
purple, a selected feature teal, and a selected done step stopped looking done. Now:
`canvas.md`'s *A picked node is lifted, not recoloured*.

## 2026-09-01 — The Compose Docs step kind was deleted

Documentation was first compiled by a *Compose Docs* step you created, linked into the graph,
and ran. It worked, and it was wrong: a feature and a milestone already were the collectors the
graph defines, so a second kind existing only to collect was a node somebody had to remember to
create. Deleting it removed a `StepKind`, a Type toggle, a medallion glyph, a mnemonic table
the collision had forced, and two CLI verbs. Now: `collectors.md`'s *There is no step kind for
compiling*.

## 2026-09-02 — Step ▸ New stopped being a submenu of kinds

Step ▸ New used to be a submenu — a plain step, then one entry per kind, each prompting for a
title — and the kinds were a `StepKind` list of their own with an `entry` function per kind.
Once the aspect bar could say what a step is in one click, the submenu was a second, narrower
way to say the same thing: it offered four of eleven aspects, asked for a name in a
`QInputDialog` that the details dialog already has a field for, and needed its own list to
stay in step with the toggles. What went: `kinds.py`, the toolbar's New dropdown, and the
prompt. Now: `core.md`'s *A kind is what a node is; a facet is what it carries*.

## 2026-09-02 — Requirements gave way to feature records

A specification used to be read into **requirements**: quoted obligations in the spec module's
index, linked N:M to steps, cited in briefings, checked by lint. It was honest and the wrong
grain — nobody demos a requirement — so the next answer was a feature *record* in the
project's catalogue. Now: `collectors.md`'s *A feature is a step*.

## 2026-09-02 — A Type toggle shelves instead of deleting

Every Type toggle used to delete what the aspect held, after asking. Turning an aspect off now
shelves its entry in `modules/shelf.json`, and the two builders in `domain/shelf.py` collapsed
eleven near-identical toggle implementations into one `framework/aspect_toggle.py` factory.
Now: `step-panel.md`'s *Turning an aspect off shelves it*.

## 2026-09-02 — The aspect bar replaced the "+" and its dialog of checkboxes

Aspects were added from a "+" beside the tabs, which opened a dialog of checkboxes — the same
registry-rendering rule with a worse reading, a list you had to summon to see what a step
already was. The aspect bar replaced both. Now: `step-panel.md`'s *The aspect bar renders the
registry, never a copy of it*.

## 2026-09-02 — The step's name became the first Details block

The name used to sit above the tab bar as a field of the panel's own. It moved into the Details
tab as its first block, so the tab always has one to show. Now: `step-panel.md`'s *The aspect
bar renders the registry, never a copy of it*.

## 2026-09-02 — A cycle in a hand-edited file stopped being dated silently

Every schedule walk guarded against a cycle silently, placing the looped steps at depth
zero and dating a plan that has no order. `ordering.cyclic()` now names them and every
surface says so. Now: `schedule.md`'s *Time estimates: two worker pools, one greedy
simulation*.

## 2026-09-02 — The terminal is a table, not a platform `if`-chain

A platform `if`-chain resolved the terminal; it became the `TERMINALS` table both the launch
and the settings dropdown read. Gating every Agent List row on the desktop's answer alone
was the first version of the switch's gate, and it greyed switches that would have worked;
the gate became `focus_reason`, per run. Now: `agents.md`'s *Which terminal opens is a
table, not a chain*.

## 2026-09-03 — Outside changes are adopted in place instead of rebuilding the window

Every outside change cost the whole rebuild: `AppSession.reload()` built a second window and
discarded the first, losing undo history, selection, viewport, caret, split panes and open
dialogs, and an agent running five CLI verbs rebuilt the window once per two-second tick.
`LibraryStore.adopt_outside_changes` replaced it; the rebuild is the fallback. Now:
`persistence.md`'s *Adopting the other writer's changes in place*.

## 2026-09-05 — Citations are re-found by a word-seeded search

The fuzzy match for a drifted quote was first seeded by the longest common run. It was replaced
by a search seeded by the quote's rarest words, because a heavily reworded sentence keeps its
nouns and little else. Now: `collectors.md`'s *A citation is a quote and a digest; its place
is derived*.

## 2026-09-05 — Four agents killed by one `pkill`; the briefing left argv

Four agents died at once on 2026-09-05, with DPlanner, killed by one agent's
`pkill -f "Web.Host"`: every agent's argv was its whole briefing, the window was an agent's
child process, and nothing said not to kill by pattern. The first scrub of the session
markers named two markers and a prefix rule, which caught the session id but not the pid;
it became a list read off the binary. The incident section keeps the reasoning. Now:
`agents.md`'s *The peer is a top-level session, and the briefing stays out of argv*.

## 2026-09-05 — `dplanner` with no word became the CLI; the window is `dplanner window`

The window was the default and the CLI ran only when the first word was a registered noun,
until agents ran `dplanner` bare or mistyped a noun and a window opened on the developer's
desktop each time, hanging the agent's shell. A second incident followed from the first: an
agent ran `dplanner show F3`, Claude Code kept the window it opened as a background task,
the developer launched three more agents from it, each became a child session, and all died
when the first agent was killed. The default flipped, and the word refuses inside an agent's
shell. Now: `cli.md`'s *The window is a word, and everything else is the CLI*.

## 2026-09-05 — A branch switched outside the window is noticed and said

A switch made outside the window arrived as nothing in particular: the watcher adopted the
differing files, "Took 3 changes from outside DPlanner" flashed in the status bar, the branch
label stayed stale, and every edit was autosaved onto a branch nobody had named. An agent's
feedback: *a window should warn when the checkout's branch changes underneath the plan.* The
sync module now polls. Now: `persistence.md`'s *A branch switched underneath the window is
taken in, and said*.

## 2026-09-05 — The worktree switch moved from settings onto the step

Whether an agent works in a worktree was a global switch on the Agent settings page; it
became the agent aspect's `"worktree": false` opt-out. The first version put worktrees under
`.dplanner/worktrees/` and wrapped every git call in `|| true`, so a project with a
`.dplanner` pointer file failed with *Not a directory* and two agents launched "into fresh
worktrees" edited one checkout; worktrees moved to `.dplanner-worktrees/` and a failure stops
the run. tmux, first in the Automatic order, opened agents in a random split of whatever tmux
session was current; it moved to last. Now: `agents.md`'s *A worktree is the step's
decision, and the run is named after the step* and *Which terminal opens is a table, not a
chain*.

## 2026-09-05 — The team became a stored project assumption

The matrix's team selection was view state that reset on every open, so the calendar, the
landing list and `schedule matrix` could each date the plan for a different team. It became
the project's `{"team": […]}`, written by *Set Budget*. Now: `schedule.md`'s *Time
estimates: two worker pools, one greedy simulation*.

## 2026-09-06 — Repository verbs became one ⋯ per column; `move_project` stopped inheriting

Four glyph buttons scattered across three rows became one ⋯ per column. `move_project` fell
back to the source repository's main checkout when none was recorded — wrong once the
repository it leaves is a plan repository — and now asks `_is_code_repository` first. Now:
`persistence.md`'s *A project names its locations*.

## 2026-09-07 — The graph editor's verbs left View for a Graph menu

The graph editor's own verbs — Sort, Layout, Divide, Frame, the marks, Snap to Grid and the
Background — used to be a `canvas` group inside **View** (and regions had one inside
**Project**). That made View half a window menu and half a drawing-surface menu, and left the
canvas with no heading of its own: the fastest way to a divide was the command palette, which
then said only *Vertical*. Now: `shell-ui.md`'s *View is the window; Graph is the canvas*.

## 2026-09-07 — A palette row stopped being a label and a shortcut

A palette row used to be the spec's label and its shortcut, which failed for *Vertical* and
*Horizontal*, written to be read under *Divide*. The row now carries the menu path. Now:
`shell-ui.md`'s *The command palette says where a verb lives*.

## 2026-09-07 — One notes log replaced the decision log and the handoff aspect

Two modules used to hold what a project learns as it goes: a *decision log* beside the
project, carried in full into every briefing, and a *handoff* aspect on each step, inherited
down the graph and carried in full too. The first project to run forty agent steps showed the
cost: the briefing grew with every step, and an agent starting the thirtieth read twenty
handoffs and a page of decisions before its own instructions. `modules/notes/` replaced both.
Now: `collectors.md`'s *A note is a record with a label, and the briefing carries an index*.

## 2026-09-08 — `set_edges` stopped re-judging the entries it carries

`set_edges` replaces a whole list, and the first version judged every entry in it. After any
delete of a step others waited on, every survivor's list held an id that could no longer pass
"no such step", and Link, Unlink, Redirect and Isolate were dead on those steps for the life of
the project. On 2026-09-08 that surfaced two seconds after a Delete as a `ValueError` out of
Connect, and the ghost was on disk by the next autosave. Now: `graph-model.md`'s *The graph,
and what it stores*.

## 2026-09-11 — Agent CLIs became harness modules

The launcher carried a `PRESETS` table of three commands and a list of Claude Code's shell
variables, and every other fact about an agent CLI had nowhere to go. Codex support would
have been a second `if preset.id == "codex"` block; instead each CLI became a harness module.
Now: `agents.md`'s *An agent CLI is a harness, and a harness is a module*.

## 2026-09-12 — Themes stopped being a list in `theme/themes.py`

`theme/themes.py` used to be the list: the three house themes and a hand-copied set of
Omarchy's, chosen from a flat View menu, and nothing followed the desktop. Theme providers
replaced it. Now: `shell-ui.md`'s *A theme is provided, never listed*.

## 2026-09-12 — The notes view left the Docs tab's switch for a tab of its own

The notes view was a second reading inside the Docs tab behind a switch, which the index said
nothing about. It became the *Implementation notes* tab, with a row under the project in the
Docs folder. Now: `collectors.md`'s *A note is a record with a label, and the briefing
carries an index*.

## 2026-09-12 — The aspect bar's strip keeps the kinds and folds the facets

Two `QToolBar`s used to carry the bar: the left took the slack so the facets kept their glyphs
and the kinds folded first. One dense strip with the template dropdown beside it inverted
that, deliberately, and the bar's state triple lost its `visible` third. Now:
`step-panel.md`'s *The aspect bar renders the registry, never a copy of it*.

## 2026-09-12 — Save at quit stopped being synchronous; Run Agent got one seat

Save at quit was the fourth synchronous storage operation, because the window was closing
and no task centre could watch it. The close became deferred, so the exception lapsed — its
cost had been a frozen window indistinguishable from a hang. *Run Agent…* sat flat beside
*Run Agent With ▸*; the child menu became the one seat. Now: `persistence.md`'s *Storage
operations that rewrite the working tree are synchronous*; `agents.md`'s *A launch profile
is a name over the two choices*.

## 2026-09-13 — The orphan ring was retired for the problem squiggle

There was a third mark. The orphan's ring was the refusal red at full strength round a node
nothing touched: the socket discs say *this is where the graph ends*, which is often correct,
while a ring said *nothing touches this at all*, which almost never is. What retired it is the
problem squiggle — `graph.orphan` is a lint check like any other, so the general mark covers
the case the ring was invented for, and covers it better, because the Problems panel says
*which* thing is wrong. Now: `canvas.md`'s *Marks are a way of looking*.

## 2026-09-13 — The spec editor became a `ProseEdit`

The spec editor was a `QTextEdit` over `setMarkdown`/`toMarkdown`. The swap deleted the
standing warning that editing would reformat the document, the `![](` → `![image](` rewrite on
open (Qt's exporter dropped an empty alt), and the carve-out that made a `.txt` read-only. It
also fixed citations: the rich-text editor's `toPlainText()` was the *rendered* text while
every other reader used the source, so a cited heading or any passage with inline markup
stored one string while every other reader checked another. Now: `specs.md`'s *Editing a
spec in-app is a replace*.

## 2026-09-13 — A spec document can be renamed

There was no rename at all. Renaming only a display title was weighed and rejected; the key
moves, and carries its references. Now: `specs.md`'s *Editing a spec in-app is a replace*.

## 2026-09-13 — The tab title's mark calls `updates_words`

`updates_words` was written and tested when the spec sources landed and went uncalled until
the Specs tab's title and index row were marked with it. Now: `specs.md`'s *Editing a spec
in-app is a replace*.

## 2026-09-13 — Fetching a spec is window-only for a new reason

Fetching was window-only because of the credential: the token is in the keychain, a shell
could reach it, and an agent's shell runs with the person's keychain but not their judgement.
A folder source has no credential, so the reason became that pulling bytes from outside the
plan into it is a person's act. Now: `specs.md`'s *A spec source is a kind the spec module
runs*.

## 2026-09-13 — Confluence page and folder became two kinds

The Confluence module shipped as a single kind whose locator carried `type: page | folder`,
so the Add Spec menu offered one entry for two acts. It became two kinds over one walk. Now:
`specs.md`'s *A spec source is a kind the spec module runs*.

## 2026-09-13 — Documentation is compiled by an agent, not an in-app LLM call

The first version compiled with an in-app LLM call: a `TaskRunner` body around
`framework/llm_service.py`, the document and its stamp landed as one undo entry. It worked,
needed a provider key in *Settings ▸ LLM*, and nobody used it — while the agents doing the work
were writing to the plan through the CLI all day. *Compile with Agent…* replaced it, and
`provider` and `model` left the stamp (`docs_compiled` format 2). Now: `collectors.md`'s
*Compiling launches a peer, and the window writes no document*.

## 2026-09-13 — A feature became a step

The feature record — in the project's catalogue whether or not it was on the graph — bought the
feature *before* somebody cut a step for it, at the cost of a parallel store: two titles and
two descriptions that drifted, four half-states (*placed*, *unplaced*, *duplicate*,
*unregistered*) each with a lint check, and an undo that restored either side independently.
A feature became a step carrying the feature aspect. Four lint checks ceased to exist
(`feature.unplaced`, `feature.duplicate`, `feature.dangling`, `feature.unregistered`), and
the trace became one hop shorter. FORMAT.md had called the retired `step_feature` module's
converter "the one that cannot finish the job" because it could not mint a record; with no
catalogue, its bare `{"on": true}` became a whole answer. Now: `collectors.md`'s *A feature
is a step*.

## 2026-09-13 — Every note label reaches by the graph

This was settled twice, and the second time reversed the first. Originally only a handoff used
the graph: a decision, a spec change and a deferred item reached the whole project. Measured on
a 74-step plan with 320 standing notes, the notes index was 73% of every briefing, and 267 of
its ~285 lines were byte-identical on all 57 agent steps. The `reach` column came off `Label`
entirely: index 33,131 → 2,715 chars median, whole briefing 47,157 → 17,497. Now:
`collectors.md`'s *A note is a record with a label, and the briefing carries an index*.

## 2026-09-13 — The checklist retired `github/notice.py`; the keychain moved to `core/`

The GitHub module's own startup box was retired in favour of the machine checklist.
`framework/secrets_store.py` moved to `core/secrets.py` so headless `checks.py` files could
ask about the keychain. SKILL.md's command section was a heading per noun and a bullet per
verb — 176 bullets, a third of the file — and became one line per noun. Now: `cli.md`'s *A
checklist is a registry of probes, and every module owns its own* and *The command list is
an index, not a manual*.

## 2026-09-14 — The coverage view stopped dimming

Cards off the picked path used to be dimmed. They no longer are; what lights is the lines into
and out of a picked card. Now: `collectors.md`'s *A citation is a quote and a digest; its
place is derived*.

## 2026-09-14 — The at-work notice replaced the status-bar *Later* button

A deferred collision left a *Later* button in the status bar; the standing notice replaced
it, so one surface says it. Now: `persistence.md`'s *An agent at work says so, and the window
says it back*.

## 2026-09-15 — The steps table's status filter folded into column filters

The published page's steps table had a hard-coded status filter of four options whose
predicate read the class off the rendered cell. It folded into `parts.Column.filter`, which
carries values in `data-values` and builds its options from the rows. Now:
`collectors.md`'s *The filter on a published page belongs to the column, not to the verb*.

## 2026-09-16 — `TestsActivity.showing()` replaced `_narrowed_to`

`_narrowed_to` was `New Test Run`'s walk for the scope alone; generalising it into
`showing()` — scope, audience filter and archived — was cheaper than a near-copy beside it.
Now: `collectors.md`'s *Export is what the tab is showing*.

## 2026-09-17 — Screenshots were a convention, not a feature

The ask was for screenshots in a test with a sequence and annotations, and the honest answer
is that the mechanism already shipped: `dplanner test attach` copies an image into the
step's file area and prints the `assets/…` link, content-addressed like every other asset,
and a test body is markdown. What was missing was only what nobody had written down.

The feature that was *not* built is worth recording, because it looks right. A structured
list on the test record — an ordered array of `{asset, caption}` — would give a renderer a
real sequence to draw and a place to hang a caption. It would also mean a schema migration,
a second way to put an image in a body beside the markdown link that already works, an
editor in the step panel to maintain it, and a decision in every renderer (the tab, the Test
panel, the export, the report) about what to do when the two disagree. That is a feature's
worth of surface for something the body already expresses: **the step number is the
sequence, and the alt text is the annotation.** `![2 — the signing dialog; Sign stays
disabled until a name is typed](assets/…)` sorts itself, renders everywhere markdown
renders, survives an export that carries no images, and needs no format bump. The rule the
document adds is that a picture goes on its step's line rather than in a gallery at the end,
which is what makes a body read as a sequence at all.

Now: `collectors.md`'s *The test format is read before a test is written*.

## 2026-09-17 — The step editor stopped being a panel

The step detail panel was a *consumer-owned Protocol* before the dock existed — `canvas`
declared `widget`/`show_step`/`dispose` and the composition root handed it a factory, which
cost a panel per tab. Anchoring it in the dock deleted the Protocol and the `detail_panel`
dependency; for a while it was both an anchored panel following the selection and the
`steps.details` dialog, until the Tests roster made it plain one seat was wrong, and the
anchored one went — one spec deleted from `services.panels`. The project form, which had
returned False from `show_context` whenever one step was selected and later yielded only to
a `narrower_kinds` tuple (`("test",)`), had nothing left to yield to. Now:
`step-panel.md`'s *How a panel gets editors it has never heard of* and *The step editor is a
modal*.

## 2026-09-17 — The Test panel moved inside the Tests tab

The Test panel began as a dock panel in the right area, under the project form, with the form
yielding to it while a test was picked. It moved inside the Tests tab as a side panel. Now:
`collectors.md`'s *A test is run from a panel, and a double-click there opens the test*.

## 2026-09-17 — A picked test publishes its step too

The Test panel spent its first week looking a test up by id across the whole library, which
answered with whichever project sorted first. The roll call then joined the project tab in
publishing `selection/step/<id>` beside `selection/test/<id>`. Now: `collectors.md`'s *A test
is run from a panel, and a double-click there opens the test*.

## 2026-09-17 — The notes view left the project form

The notes view lived in the project form as a card first, one widget per note; a plan whose
agents had written 344 handoffs made every window relayout walk 688 word-wrapped labels. Now:
`collectors.md`'s *A note is a record with a label, and the briefing carries an index*.

## 2026-09-18 — The *not checked out on this machine* dead end was retired

Verbs needing a checkout refused on a machine without one; the checkout service and clone
policy replaced the refusal with a clone. Now: `persistence.md`'s *A project names its
locations*.

## 2026-09-26 — Work in flight keeps its worker when re-dated

Re-dated, a later stretch's work in flight waited for the stretches before it, counting its
person free. It now keeps its worker beside the stretch being worked. The Milestones page's
rows carried a sentence that became the row's tooltip. Now: `schedule.md`'s *The plan
re-dates itself from what has happened* and *Progress against the plan: the promise is
derived, the past is recorded*.

## 2026-09-27 — A folder row stopped swallowing gestures

The index panel used to swallow every gesture on a folder row, on the reasoning that a folder
is furniture. Two requests broke that: Home wanted a row at the top of the index with nothing
under it, and a right-click on *Projects* offered nothing where a person reaches to add one.
Now: `shell-ui.md`'s *The index tree*.

## 2026-09-27 — Home replaced the empty start, and stopped being a backdrop

After the Dashboard retired, a program that started with no tabs to reopen showed an empty tab
bar over nothing. Home filled it. The first build stood Home behind the tabs as a backdrop
whenever none was open; the developer's call was the simpler one, an ordinary tab opened only
at the program's start. Now: `shell-ui.md`'s *Home is where a window starts*.

## 2026-09-27 — Canvas verbs left the Step menu once the right-click was composed

The first Graph-menu split kept Connect, Link, Unlink, Isolate, the Redirect pair, Lasso,
Find, Go and New on **Step**, because the canvas's right-click rendered the Step menu whole and
moving them would have taken the graph's most-used verbs off its own context menu. That held
only while one menu was all a right-click could be. Once the right-click was composed by what
is under it, the old filing showed its cost: every table that renders Step by name carried
New, Find, Go, Lasso and Redirect greyed, and an arrow's right-click offered Rename. Reveal in
Graph became *Show in ▸ Graph* and moved from the retired `navigate` group to `surfaces`. Now:
`shell-ui.md`'s *View is the window; Graph is the canvas*.

## 2026-09-27 — The key block replaced the 26 px spine

The card's key used to sit on a 26 px *spine*, rotated a quarter turn up it the way a book's
spine reads. The spec asked for the primary icon "in the same place as the step id", and an
icon cannot be read sideways, so the strip widened to 56 px to hold both level. The minimum
card (`MIN_NODE_W`) grew from 144 to 176 and the coverage lanes' minimum (`LANE_MIN_W`) from
168 to 198. Now: `canvas.md`'s *The key block names the card and says who works it*.

## 2026-09-27 — A test row's right-click became its step's

For a while a Tests row's right-click led with the result: the *Test* child menu's
`test_result` band flat, then the whole Step menu one level down as a `Step` child — two
renders of the registry through `fill_bands`. It was the reason `fill_menu` learned to take a
`group` with a `submenu`. It went when the menu bar was sorted by subject and Type and Test
left the menus for Step Details. Now: `collectors.md`'s *A right-click on a test is its
step's*.

## 2026-09-27 — The start left every feature's reading

When the start stopped being gathered by features, a collector compiled with the start's
fragment read `docs.compiled-stale` once, and the two walks that wrote the feature stopping
rule by hand (the briefing's *Flows into*, the coverage trace) moved to the wired kinds — which
is how the Steps lane stopped drawing the origin under every feature. Now: `collectors.md`'s
*The origin is nobody's*.

## 2026-09-27 — A flowing arrow's chevrons walk a cached polyline

A doubled arrow first cost 1.5 ms to lay out on every sync, placing each chevron with
`QPainterPath.percentAtLength` at about 40 µs a call. `follow()` was changed to flatten the
curve once and walk the polyline (0.2 ms). The doubled arrow left with auto-progress on
2026-10-07 (below).

## 2026-09-27 — The project's forms left the card stack

The project's forms sat in a card stack, which had a trailing spacer from the start and never
hit the block-stretch bug because no card asked for stretch. Now: `step-panel.md`'s *The step
editor is a modal*.

## 2026-09-27 — The Dashboard tab retired into *Project ▸ Settings…*

A project's forms were a dock panel in the right area, then a Dashboard tab
(`project_dashboard`), then the tabs of the Project dialog. The tab said everything twice:
its name and summary were the dialog's fields, its Repositories card the Locations table
re-worded (which is why `repos.location_words` had to be shared). The `project_settings`
registry had already retired `project_repo`'s `RepoFields` + `repo_fields` handover. A click
on a project row stopped opening the Dashboard as a preview. Now: `persistence.md`'s *A
project's forms live in its dialog*.

## 2026-09-27 — At-work claims lapse after three minutes of silence

The first at-work design decided nothing: a quiet claim changed tense (*was at work … last
heard 40 minutes ago*) and stood until somebody ended it, so the window collected bands
from agents long gone. Claims now lapse after `FRESH_MINUTES`. Now: `persistence.md`'s
*An agent at work says so, and the window says it back*.

## 2026-09-27 — The Control Centre: same groups, two tabs on one base

The step that asked for the Control Centre named running and upcoming lanes, written before
the board stopped being lanes; the developer kept the table's rule on 27 September. One
class with a *None-means-every-project* scope was the first sketch, which
`follow_project_tabs` would have closed. *Show in ▸ Order* and *Step Statuses* were greyed
with no reason on every row until `focused_project` moved to `framework/step_selection.py`.
A window left open overnight showed yesterday's board until the tabs re-ran on
`clock.day_changed`. Now: `schedule.md`'s *Progression is the status-aware frontier*.

## 2026-09-29 — Every worktree starts from the remote

Every agent step used to land on main by accident rather than by design: the wrapper script
forked each worktree from whatever the code checkout had checked out, and the agent opened its
PR with no base, so it went to the repository's default. Branch stretches made the plan decide
the branches, and every worktree started from the remote — a change in behaviour for every
run, and the honest one. The GitHub aspect began recording the base a PR merges into (format
2). Now: `graph-model.md`'s *A branch stretch is bracketed by a cut and a landing*.

## 2026-09-29 — *Not Pushed* says it in a dialog

A diverged push surfaced git's own words as the footer status, which did not fit one line;
`not_pushed_dialog.py` replaced it. Now: `persistence.md`'s *Save spans repositories; the
exit dialog says what it records*.

## 2026-10-02 — Reports left Save; the bootstrap skill was removed

Save published before it committed: the sync module asked for a publication per dirty
repository, committed `reports/` with the plan, and cloned a missing reporting repository to
commit the site there. Two people saving one plan repository conflicted on every pair of
saves over the generated pages. Save now records the plan alone; the site is written on
request. A hand-written bootstrap skill (a Claude Code plugin installing git, uv and
DPlanner) did not get the program onto Windows and nothing could test the act; it was
removed for the README's `uv tool install` route, whose own bug — `install all` rewriting
uv's receipt to a bare `dplanner` — was fixed by `_install_command_piece`. Now: `cli.md`'s
*A report is a publication, not a record* and *Installing is one act, and the pieces stay*.

## 2026-10-04 — Qt file names were given one meaning each

By 4 October `view.py` meant four things in four packages: a tab's body (the Order table), a
status-bar widget with a diff dialog beside it (sync), a modal list (the Agents and task
browsers) and a modal (the outside-change conflict). Five tabs lived inside `module.py`, and
two `editor.py` files were a Step Details section and a tab's sub-widget. The dialogs of
`repo_picker.py` and `repositories_folder.py` moved out beside them, and the design example's
sample rows became `design_sample.py`. `HEADLESS_FILES` went package-relative after the
`time_estimates` → `schedule` rename renamed its `schedule.py` to `assumptions.py` and the
bare-name entry silently matched nothing. Now: `core.md`'s *A file name has one meaning*.

## 2026-10-04 — Undo refuses over another writer's value; a launch writes its intent first

Undoing a rename restored the old title over the agent's newer one, and nothing said so;
commands now remember what their redo left and refuse otherwise. The first auto-launch
spawned, claimed in memory and flushed afterwards, so a window that died in between launched
the step again; `launch_due` now writes an intent before it spawns. Now: `persistence.md`'s
*Adopting the other writer's changes in place*; `agents.md`'s *A launch writes its intent
before its shell*.

## 2026-10-04 — Effects wait for the save in the window too; intents outlive a refusal

R26's review of the landing found three seams the revision had left open. The window's Set
Status ended an agent's claim the moment the command was pushed, before autosave wrote it;
it now waits for `AutosaveService.saved()`, as the CLI waits for its flush. Every launch
intent was cleared after any successful flush, including an interrupted one that had only
been refused in memory, so a new window launched the step again; an intent now goes only when
its step no longer reads due. Coalescing merged a value command across another writer's edit,
so undo restored the older value over theirs; a merge now requires continuity. Now:
`core.md`'s *A workflow is one function under both surfaces*; `persistence.md`'s *Adopting
the other writer's changes in place*; `agents.md`'s *A launch writes its intent before its
shell*.

## 2026-10-07 — The ledger record becomes the run; at-work is kept beside claims

Before headless runs were built, their records were settled as one design (S3 of
*Playbooks and autonomous work*). The ledger record, which said only what a launch
consumed, becomes the run record at format 2 — turns, how each ended, the playbook stage —
and the playbook ledger is its runs rather than a record of its own. A run's working files
leave `tempfile.mkdtemp` in `/tmp`, which a reboot empties and which was a nearly full RAM
disk in the 10-04 run, for `config_dir()/runs/`. Questions and claims are new files in the
project. The machine-local at-work claim was weighed for absorbing into the committed claim
and kept: its three-minute clock cannot be committed. Now: `agents.md`'s *Runs, questions
and claims are three records in the plan*.

## 2026-10-07 — A key resolves in the current project, or not at all

`find_step` resolved a key or title in the current project when it could, and otherwise fell
back to the whole library — so in the 10-04 run `DPLANNER_PROJECT=A dplanner review set R26`
rewrote project B's S26. Now only an id of at least eight characters reaches past the current
project (S7 of *Playbooks and autonomous work*). Now: `graph-model.md`'s *A key is the
current project's, an id the library's*.

## 2026-10-07 — Auto-progress and the window's auto-launch were removed

An auto-progress link let a step start once a step it waited on read ready for review, so a
collector could land three agents' branches and a review could start on its subject; the
window then launched what that made due, on its own, from one window per library. Playbooks
replace both (S5 of *Playbooks and autonomous work*): what used to be a second card and a
flagged arrow is a stage on the one step, and DPlanner never starts the next step itself —
the coordinator or a person does. Gone with it: the `auto_progress` aspect, its verbs and
lint, `step add --auto-progress`, the Edge menu's toggle, `progression`'s `due` and `taken`
(Ready for review is a person's turn whatever waits on it), *Now due*, `project graph`'s
`==>`, the briefing's *Work you collect*, and the canvas's doubled, flowing and medallion
arrows, so `EdgeAccent` is a lane alone. Review steps fall back to plain links until S6
removes them. Kept: the unattended launch's intent and claim, as `launch_unattended`, for
`dplanner agent run`. The stored `auto_progress.json` is retired with no successor: it is
left as data nobody declares, and the id is in `RETIRED_IDS`, which no module may declare
again. A machine's old `config_dir()/auto-launch/` and the `auto_launch` setting are left
behind, read by nothing. Now: `agents.md`'s *A launch writes its intent before its shell*;
FORMAT.md's *Retiring a module*.

## 2026-10-07 — Review steps were removed

A review was a step: an agent step carrying `step_review` (keyed `R`; agent, lenses and a cap
of rounds) whose subject was the step it `requires`, holding a conversation with that subject
in `review_rounds` on itself — rounds of texts and stamps whose state was derived, never
stored — through `dplanner review start|post|take|reply|approve|escalate|wait`. Both sides were
briefed with the protocol, the review got a generated `## Instructions` and no worktree, and
the window showed it read-only in a Review tab and *Review Conversation…*. Playbooks replace it
(S6 of *Playbooks and autonomous work*): a review is a gate stage on the one step, its findings
a typed verdict on a run, its round cap a question — what made a second card per step and an
agent pair waiting on each other in two terminals. Gone with it: the aspect, the verbs, `step
add --review`, the lint (`review.subject`, `review.bypassed`), the toggle, tab, template,
medallion and glyph, `Kind.REVIEW`, the briefing's review instruction, epilogue, *Work you
review* and *Review rounds with …*, `due_turns`, and the rule that a review runs in no worktree
(`no_worktree`; every surface now reads `uses_worktree`). Kept: what its ledger taught —
`playbooks.md`'s *What of the review rounds ledger survives* — and the profile lookup by
harness, as `launch_unattended(harness=)` for a playbook role. `step_review` and
`review_rounds` are retired with no successor: a plan's files stay as data nobody declares and
the ids are in `RETIRED_IDS`; a step that carried `step_review` reads as the agent step it also
was. The full reasoning as it stood is the review section of `agents.md` at `dfc0de0` (`git
show dfc0de0:docs/architecture/agents.md`). Now: `playbooks.md`; FORMAT.md's *Retiring a
module*.

## 2026-10-07 — A turn's usage is counted from its own stream, not from cursors

FORMAT.md's format 2 was designed with each turn's usage read between two cursors into the
vendor's session records, a reader per harness, so that runs sharing a session would count
only their own turns. Building the supervisor showed the stream it already tees is exactly
one turn's window: the counts are read from it as the turn ends, the harvest leaves a
headless record to its supervisor, and no cursor API was built. The cost is subagents the
stream does not report. Now: `agents.md`'s *A headless run is driven by its supervisor*.
