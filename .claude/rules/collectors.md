---
paths:
  - "src/dplanner/modules/{testing,docs,notes,feature,coverage,step_check}/**"
  - "src/dplanner/domain/scope.py"
  - "src/dplanner/core/anchors.py"
  - "src/dplanner/cli/scopes.py"
  - "tests/domain/test_scope.py"
  - "tests/core/test_anchors.py"
  - "tests/modules/test_{testing,docs,notes,feature,coverage,spec_passages,focus_seams}*.py"
  - "tests/cli/test_{scopes,feature_verbs,coverage_verbs,note_verbs}.py"
  - "scripts/render_documentation.py"
---

# Collectors — scopes, features, citations, tests, documentation and notes

- **How a test body is written is a house document, read through a gate.**
  `modules/testing/format.md` — preconditions as bullets, then numbered steps, a screenshot
  on the step it belongs to with the alt text as its annotation, and the four shapes a
  concurrent test takes — is printed by `dplanner test format` and never stored in a plan,
  because a plan's prose reaches every briefing. `test add` and `test set` declare
  `reads_guide` and refuse until it has been read on this machine (`cli/gate.py`, and
  `.claude/rules/cli.md` for the mechanism); nothing that reads, files, exports or marks a
  test is gated, and `step add --test` names a test without writing a body. **Concurrency is
  asked, never enforced**: no aspect says whether a product has concurrent users, so the
  document tells the agent to raise it and propose — a lint check would fire on plans that
  are right. Edit the document, not a copy: the skill carries the concern in two lines and
  the shape in none. `ARCHITECTURE.md`'s *The test format is read before a test is written*
  has the reasoning.
- **Tests can be read grouped, and one selector holds every way of grouping them.** By
  category, by feature, by milestone or by check are four answers to *what is this test one
  of*, so they are four entries in one box. `_Grouping` (`TestsActivity`) is two functions
  over `(step, test)` — where a row sorts, what heading it lands under — because the
  collectors are a fact about a test's **step** and the category is a fact about the
  **test**; the collector half is filled by `scope.gatherers()`, and a step nothing gathers
  lands under *Not in any feature*, the same steps `dplanner project lint` reports as
  `scope.ungathered`. A step two features both wait on gets one **joint** heading rather
  than two rows: a test listed twice is a test marked twice. **Category leads and is the
  default while the project has one** — a flat roster of two hundred is unreadable, and a
  project with no categories would open on one heading saying *Uncategorised* — until the
  reader picks a grouping, after which their answer stands. `TestsTable` draws a spanned
  heading wherever the group changes; **a category heading folds** (`Table.add_heading`'s
  `key`, the whole row the target) and the collector headings do not.
- **A test is filed under a category, and ordered inside it by a sort key.** The sort key
  (`modules/testing/filing.py`) is free text with **no catalogue and no editor**, because
  it is an ergonomic rather than a vocabulary: tests sharing one are executed together, so
  somebody working down a roster stays in one place at a time. It **always sorts**, inside
  whatever group is current — *Ergonomic order* on the Tests strip is on by default and is
  there to turn **off**, and a project with no sort keys is ordered identically either way
  (`ergonomic_order`: alphabetical, keyless last). It is a **column**, never a second layer
  of headings: the rows are already adjacent once sorted, and `Table` groups flat. Verbs:
  `test add|set --sort-key`, `test list --sort-key|--flat`, and **`dplanner test file`** —
  many tests, both filing fields, one call, which is what reorganising a roster is made of
  and which replaced `test-category assign` (`test set` is one test with many fields).
  In the window: the step panel's editable combo (offering the keys in use, so one view is
  not spelled three ways) and `Step ▸ Test Sort Key ▸ …`, whose last entry mints a new key
  because there is no editor to send anybody to. `ARCHITECTURE.md`'s *The sort key is an
  ergonomic* has the reasoning.
- **A test is run from the Test panel, and a double-click in a Tests tab opens the test.**
  `modules/testing/panel.py`, a `PanelSpec` in the right area under the project form: the
  test rendered (not edited — authoring is the step panel's Tests tab, and *Show Step* is
  the door), its last result, the four result verbs from the registry, and Previous/Next.
  It is the only thing in that area while a test is picked — the project form yields to it
  (`narrower_kinds`, wired in the root) and the step editor is a modal with no seat there at
  all. **The double-click is the one deliberate exception to *double-clicking a step anywhere
  runs `steps.details`*** — in this table a row *is* a test, and the step is not even a
  column any more — and `test.details` only *reveals* the panel, which was already
  following the context. **Next
  and Previous move the table's selection**, never the panel's own (a panel publishes no
  selection), and it is the *tab's* order they walk, greyed with the reason when no tab is
  open. Register the panel **after** the action specs: the dock builds it on registration
  and its strip asks the registry for the result verbs. `ARCHITECTURE.md`'s *A test is run
  from a panel* has the reasoning.
- **A test body's reference to another test is a link, and a link opens a preview.** A body
  that says *after T101 passes* is pointing somewhere, and picking that test in the table
  loses the one being read with nothing to go back to. So `modules/testing/references.py`
  (Qt-free) links every bare `T<n>` the **same project** has minted — never one it has not
  (a dead link is worse than none) and never inside `<a>`, `<code>` or `<pre>`, since code
  quotes the shape of an id rather than uses one — and it does that to the **rendered
  HTML**, where `core/markdown.py` has already escaped every piece of user text, so the only
  `<` left opens one of our own tags. A click opens `preview_dialog.py`: the test read over
  what you were reading, its own references linked with **Back** walking the trail, *Close*
  putting you back where you were, and *Show in Tests* the one deliberate move —
  `TestsActivity.reveal`, which widens the tab's scope, audience filter and archived switch
  **only** when they are what is hiding the test, and opens the category it is folded under.
  The preview and the panel are the same two widgets (`view.py`'s `TestHead` and
  `TestBody`), so a test read in one reads as it does in the other. `ARCHITECTURE.md`'s
  *A reference is a link, and a link is a preview* has the reasoning.
- **A test is always named with its step, never on its own.** Ids are minted per *project*
  (`aspect.py`), so `T101` names a different test in every project in the library and a
  lookup by id alone answers with whichever project sorts first — which is exactly what the
  Test panel did until it was fixed, showing a namesake whatever the reader double-clicked.
  So every view that picks a test publishes `selection/step/<id>` beside
  `selection/test/<id>` — both Tests tabs, and the roll call in particular, which is the one
  view holding several projects at once — `test.details` is greyed without the pair, and
  `TestPanel` resolves the test inside that one step. `TestsModule._selected_tests` is the
  same rule one step along: it narrows to the context's project before matching ids.
- **A test is filed under a category, and its words are the key.** Free text, open
  vocabulary, catalogued beside the *project* (`modules/testing/filing.py`: a `name` and
  an `icon` from the curated `ICONS`), and a test stores the category's **words** — there is
  no minted id, so `test set T100 --category Import` is the whole story and renaming is a
  **refactor** that rewrites every test carrying the old words, in one undoable step
  (`test-category set --rename`, and the editor's Save). **The catalogue is stored so it can
  be laid out before the tests** — the agent reading a spec files the groups the tests will
  arrive into — and **membership is never stored**: `counts()` walks them, and a category a
  test names that the catalogue does not is appended by `catalog()`, unglyphed and last, so
  a typo is a group of one rather than a test that fell out of every list. `category_of` is
  the one derivation (what it stored, or *Uncategorised*); `lint`'s `test.category` is the
  one raw reader, and it stays quiet until the project has categories at all. Verbs:
  `test-category list|add|set|remove`, `test add|set --category`, `test file` for a batch,
  `step add --test-category`.
  In the window: `Project ▸ Test Categories…` (the modal editor, also on the Tests strip and
  in the index's right-click, which renders the Project menu), `Step ▸ Test Category ▸ …` (a
  `DataMenuSpec`, so the categories are data rebuilt on open — and what a right-click on a
  category heading acts on, because the heading selects its whole group first; a right-click
  in a Tests tab renders the result band and the Step menu as a `Step` child, so that path
  is the same one the menu bar prints), and the step panel's picker beside the audience
  boxes. `ARCHITECTURE.md`'s *A test is filed under a
  category* has the reasoning, including why two writers share one project entry.
- **The category editor is a modal that writes on Save.** `categories_dialog.py` edits a
  copy — each row remembering the name it started with — and lands the whole refactor as one
  undo step when it closes, because renaming per keystroke would rebuild the Tests tab under
  the reader's hands. Every row carries its **count**, which is what makes a blind rename
  safe: it says how many tests are about to move. Removing a category unfiles its tests
  rather than deleting them, and says so. The icon is **picked from a grid**, never typed;
  the same `ICONS` tuple is what `--icon` refuses against.
- **The tests table has seven columns, and three were taken out rather than narrowed.**
  *Covered by* is the Covers tab's whole subject and was a comma-separated list nobody
  compared down the page; *When* dated the last run, which is exactly the fact a test
  outlives; and *Step* gave its seat to the **Id**, because a body that says *after T101
  passes* is pointing at a test the roster never named, and a reader with no id column opens
  tests until they find the one meant. The step is still the Test panel's filed line and its
  *Show Step*, and all three are in `dplanner test show`. The Category column stands down
  while the rows are already grouped by category — a column repeating its own heading is
  noise twice — and, like Audience and Sort key, while no test in scope names one.
- **Exporting the tests is what the tab is showing.** `File ▸ Export ▸ Tests…` writes the
  project's Tests tab's current scope, audience filter and archived switch, read back
  through `TestsActivity.showing()` — which `New Test Run` reads too, so "narrow it, then
  act on it" is one gesture and not a second dialog asking the same questions. `dplanner
  test export --format md|html --audience … --scope …` is the terminal's half, which has no
  tab to read. `modules/testing/export.py` is Qt-free and is **not** the report: `cli/report/`
  publishes the plan and names each test in a line, this writes the tests filed by category
  with every body in full, HTML as one self-contained page of `<details>`. Neither inlines
  pictures.
- **What reaches a step is computed, never stored** — `notes/reach.py` is one function
  with three readers (the Agent tab's Notes pane, `dplanner note index`, the briefing).
  Same rule as the ordering, and the reasoning is in `ARCHITECTURE.md`'s *What reaches a
  step is derived at read time*. **The graph says who a note is for**: every label reaches
  the steps after the one it was made on, so reach is not a column on `Label`; a note made
  on no step, or on one since deleted, has nothing to be downstream of and reaches the
  project, and `--reach project` is the one stored exception. **And the index has a
  ceiling** — `INDEX_LIMIT` (20) per label, newest kept, a truncated group saying how many
  it left and the `note list --label` that reads them. The cap lives in `index_lines`, so
  all three readers get it by construction and the window shows what the agent was handed.
  A briefing is read once, from the top: an index nobody finishes costs what a log costs.
- **A note is a record beside the project with a label, and every briefing carries an
  index.** `modules/notes/` — `log.py` (Qt-free; `N1, N2, …` minted per project, a
  **label** from the closed `LABELS` list — `decision`, `handoff`, `spec-change`, `later`,
  `post-project` — a title, markdown body, the day, the step it was made on, the steps it
  is `for`, what it supersedes), `dplanner note add|set|remove|list|show|attach|index`,
  and the **Implementation notes** tab (`activity.py` around `view.py`: the log as
  delegate-painted rows, newest first, beside the picked note's editor, never a widget
  per note), opened from the row the notes module puts under each project in the index's
  Docs folder beside *Documentation* (`index_row`, handed to the docs module as
  `DocsDeps.more_rows` by the root — neither imports the other). It
  replaced the decision log and the handoff aspect (both reach it at open — `migrate.py`). **The briefing's notes block is an index**: one
  line per standing note that reaches the step, grouped by label, with `note show` to
  open one — and a note **addressed** to the step (`--for S12`) in full ahead of it, which
  is how one agent points the next at what it must read. Who a note reaches is the graph's
  — the bullet above — and the index stops at twenty a label and says so. **Adding a title
  already on the same step is that
  note**, reported and not duplicated, so an agent's retry never leaves two; a reversal is
  a new record `--supersedes` the old, never an edit. `ARCHITECTURE.md`'s *A note is a
  record with a label, and the briefing carries an index* has the reasoning.
- **A test belongs to a step, and a step carries several.** A description says what a step
  *is*; a test says how you would prove it, and it outlives the step. A test is **not a
  node** — it is a record in the step's `testing` aspect with its own id, title, markdown
  body and per-run result, so forty steps with three tests each do not become a hundred and
  sixty nodes. The body is a **string in the record**, not a `.md`: a node holds one prose
  document and a step holds N tests. Ids are minted **per project** and meant to be read
  (`T100, T101, …`; runs are `R100, …`), which is what lets a run's results be flat, an id be
  quotable, and a rename never detach a test's history. The tab is **master-detail** — a list of tests
  and an editor for the selected one, side by side where the width allows and stacked in the
  narrow dock — because a stack of equal cards stops working at the third test.
  `ARCHITECTURE.md`'s *A test belongs to a step, and a step carries several* has the
  reasoning, including the diff trade the string body accepts.
- **A test says who it is for, and the list is closed.** `qa`, `technical`, `other` —
  `AUDIENCES` in `modules/testing/aspect.py`, owned there rather than by the composition
  root because nothing outside testing has an opinion about the word (`notes`' `LABELS` is
  the same shape, and `check_audience` the same refusal). A test carries **several**:
  one thing can be worth proving by hand *and* worth proving mechanically. **`audiences_of`
  is the one derivation** — what it stored, or `other` — and everything that shows or filters
  a test reads it, so a plan written before audiences existed changed meaning nowhere. Two
  readers ask the **raw** field instead, and both are asking *has anybody said?*: the
  `test.audience` lint, and the step panel's three checkboxes, which would otherwise render
  an `Other` nobody could untick. That pairing is the whole design — the requirement is real
  without a migration guessing an answer, and the lint is what carries an old plan over a
  test at a time. It is a **label** everywhere (the tab's Audience column — hidden while no
  test in scope names one — the Covers row, the report table and its per-step block, `test
  list`, `test show`) and a **filter** everywhere (the `FilterButton` on both Tests tabs,
  `test list --audience`, `test-run start --audience`, and a pick on the published page). A
  run records only the ids it was opened over, so it needs no audience of its own.
  `ARCHITECTURE.md`'s *A test says who it is for* has the reasoning.
- **A test goes stale when the step under it settles and then moves.** `dplanner test
  review` reports a live test on a **done** step that has not been run since a standing
  `decision` or `spec-change` note landed on that step — the shape `coverage review` has
  (rows of subject/what/advice, one table of remedies so the text and the `--json` agree).
  **There is no record of when a step became done**, so the comparison is against the
  test's **own last run** (`runs.latest_results`, the run's `closed` or `opened` day):
  that is the fact that exists, and it is the better question anyway — *is this result
  still worth trusting?* A test nobody ever ran is behind every note on its step. **Which
  labels unsettle a test is wired in `modules/__init__.py::_unsettling_notes()`**, not in
  `modules/testing/`: a decision and a spec-change change what the work should do, a
  handoff does not, and testing may not learn the notes module's vocabulary — the same
  reason `_scope_kinds()` names its predicates in the root. Notes arrive as a neutral
  `(id, label, title, made)` by step (`cli/scopes.py`'s `CoveredTest` hand-over, one
  layer down), superseded ones dropped so a reversal names a test once rather than twice.
  `ARCHITECTURE.md`'s *A test goes stale when the step under it moves* has the reasoning.
- **Documentation is a fragment per step and a document per collector, and an agent
  compiles it.** The `docs` aspect is a step's **documentation fragment**; `docs_compiled` is
  a collector's **documentation**, made of everything it gathers — the words on every
  surface, while the two on-disk ids stay as they are. Two aspect ids in one package, because
  a node holds one prose document per module and a feature legitimately has both. **There is
  no step kind for compiling** — a feature and a milestone already *are* the collectors, so
  compiling is a verb on them. A milestone reads its features' *compiled* documents, not
  their fragments again (`ScopeKind.gathers` says so), which is also what makes recompiling a
  feature mark its milestone out of date. **Staleness is a digest, never a timestamp**: a
  compile stores the digest of what it *read*, so a relink says so by itself, while
  hand-editing a document — or rewording the compilation instructions — does not.
  **There is no Compile button.** *Compile with Agent…* launches the chosen profile on a
  briefing of the fragments, the project's **compilation instructions** (`modules/docs.md`
  beside the project; the panel card, a tab in the view, and `docs set/show --for-project`
  are three presenters of one field) and the verb that finishes it — `dplanner compiled set
  <key> --file -`. Two typed callbacks on `DocsDeps`, the `hand_to_agent` shape, so nothing
  imports the agent module; the run is tracked on the collector like any other, and
  **claims nothing about the step's status**. What the agent writes arrives from another
  process, so **it is not undoable** and replacing a document that has text asks once.
  *Compile Out of Date…* takes the **frontier** — never a milestone beside the features whose
  documents it reads. Who compiled a document is the launching window's record, per user; the
  plan's stamp says when and from what (`docs_compiled` format 2 dropped `provider`/`model`
  with the LLM call). `ARCHITECTURE.md`'s *Documentation is fragments, and a collector
  compiles them* has the reasoning.
- **A collector is a cone truncated at the next collector.** `domain/scope.py`'s `cone()`
  walks `requires` backwards and refuses to pass through a step the `stops_at` predicate
  claims — so a **check** stops at nothing and stands for everything behind it, a
  **milestone** stops at milestones and holds what is new since the last one, and a
  **feature** stops at features and milestones and holds its own work. One walk, six
  readers: the Covers tab, the Tests tab's scope selector and its Group by, `dplanner scope
  show`, `test-run start --scope`, and three lint checks. `ordering.upstream()` is the same
  function with nothing to stop it. Never store what a collector holds — `dplanner step
  link` relinks a graph with no window running to notice.
- **A `ScopeKind` is wired, never inferred.** `modules/__init__.py::_scope_kinds()` writes
  the three predicates literally: what carries a kind, where its cone stops, and — a
  separate question — which kind it is *read as a list of* (`gathers`). A milestone is read
  as its features; a feature is the finest grain and reads flat. `step_check` is a bare
  marker with no tab of its own; a feature step's tab edits the spec passages it was read
  from; `modules/testing/` renders what any of them gathers, because a
  list of tests is testing's business. That keeps the wiring one-directional. `ARCHITECTURE.md`'s *A check is a scope over the graph* has the
  reasoning, including why exclusivity is a predicate rather than a stored list.
- **A feature is a step.** There is no catalogue and no verb that creates one: `step add
  --feature` is the door in — carrying `--document`/`--quote`/`--page`/`--strict` for a
  feature read straight out of a spec, the quote checked through the spec module's
  `anchor_quote` — and `step remove` the door out, which is what keeps a feature on the
  graph *by construction*. Its name is the step's title, its prose the step's description,
  its pictures the step's file area; what the aspect stores is only the passages it cites
  (`{"on": true, "cites": […]}`, format 3). Two steps may both be features. Toggling off
  shelves the passages like any aspect; `feature set`/`clear` are the toggle's CLI half.
  A work step's briefing names the features it *flows into* (`scope.gatherers`); it
  carries no link of its own. The project's old catalogue moves onto its steps at open
  (`modules/feature/migrate.py`, an `absorb` pass) — **a step it creates gets its data
  before `add_child` and its id is never returned**, or the flush raises inside the store.
  `ARCHITECTURE.md`'s *A feature is a step* has the reasoning.
- **A citation is a quote and a digest; its place is derived, and the trace is feature
  membership.** A feature cites N passages (`FeatureSource`: document, quote, page,
  digest — on the step, feature format 3), maintained by `feature cite`/`uncite`/`reanchor`
  and the Feature tab's passage list. Nothing stores where a quote sits: `core/anchors.py` finds it
  again on every read — exact, then fuzzy (seeded by the quote's rarest words, kept at
  `DRIFT_RATIO`), then lost — and a stamped passage in a document that changed since is
  *behind* only when the diff touched its paragraph. **Judging a passage is a walk of its
  whole document**, so a reader of many makes one `anchor_sources` call for the project —
  never one per feature, never `anchor_in` in a loop — and that pass normalises each
  document once (`fold`); the lint asking per feature cost the Problems panel 570 ms after
  every pause in typing on a 262-citation plan (`NOTES-FOR-APPFRAME.md` §46). `coverage/trace.py` arranges
  milestones → features → passages → tests and docs from every module's Qt-free half
  (assembled in the root's `_coverage_trace`), and **the path rule is feature
  membership**: every item carries the features it serves, so what an item reaches is
  one set intersection with no case per kind. `dplanner coverage show|spec|review`
  print it, walking it the other way — from the spec down; the Specs
  tab washes passages (`show_passages`) and offers *Cited*, *Coverage* and *Cite…*;
  `steps.details` lands on a test or a feature through `FocusableExtension`. Uncovered
  text is a report (`coverage spec --uncovered`), never a lint; it is also how an old
  project is retrofitted. `ARCHITECTURE.md`'s *A citation is a quote and a digest* has
  the reasoning.
- **The Coverage tab is a drill-down, and its lanes stand only what the picks stand up.**
  *Milestones · Features · Spec · Tests & Docs*, with *Steps* before the last while the
  strip's *Show steps* is on: every milestone always, the features the picked milestones
  gather (all of them while none is picked), and right of the features what the picks
  *themselves* stand for — `Trace.shown`, off each item's own `token` beside the features
  it serves, so a picked milestone stands up the work it holds **directly** and never its
  features' whole spec. Drawing the derivation's own order instead, everything at once
  with the unpicked faded, opened a real plan as a wall of passages. **A lane that comes
  and goes reroutes the lines, never the trace**: the trace records every pair that can
  stand side by side — a document to its features' tests *and* to the steps they sit on —
  and the scene draws a line only between two lanes standing next to each other. A click
  picks within its lane and clears the lanes to its right, Ctrl (or Shift) adds, the
  ground and Escape clear; every picked card's step is published; an empty lane says which
  pick would fill it. A card that is a step — a milestone, a feature, a step — wears the
  canvas's spine, its key up the left edge washed by status. **A view whose extent is laid out to its viewport never reports that extent as
  its size hint** — `QGraphicsView.sizeHint()` *is* the scene rect, so honouring it widened
  the view, the scene and then the hint again, which is what pushed the index panel off the
  window and made the seam jump. Lane widths are whole numbers (a rounding error flickers
  the scroll bar through a drag) and a relayout for a size the scene already has returns at
  once. `ARCHITECTURE.md`'s *A citation is a quote and a digest* has the reasoning.
- **What a collector gathers is one verb: `dplanner scope show`.** In `cli/scopes.py`, the
  cross-feature home — a check, a feature and a milestone are one derivation asked three
  ways, so three near-copies of the report is exactly what that file prevents. It also owns
  `scope.gathers-nothing`, `scope.shared` and `scope.ungathered`. The marker modules keep
  only `set`/`clear`.
- **A test result is not a step status, and it gates nothing.** `pending/in-progress/done/
  blocked` is where the *work* stands; `ok/failed/skipped`/absent is what happened when
  somebody *ran* a test. No word is shared, on purpose. A failing test does not block a
  milestone and does not reach `progression()` — folding it in would make `dplanner
  progression show` answer a different question. `ARCHITECTURE.md`'s *A test result is not a
  step status* has the why.
- **A project has at most one open test run, and a run freezes its membership.** Starting one
  closes the last, which is what makes "mark these twelve ok" a pure function of the context
  — no hidden "which run", and a greyed verb that says *"start a test run first"*. A run
  stores the ids it was opened over, so a closed run cannot change meaning when the graph
  does; a missing result reads as pending, and the latest result is the newest run that
  actually recorded one. `ARCHITECTURE.md`'s *One open run per project* has the reasoning.
