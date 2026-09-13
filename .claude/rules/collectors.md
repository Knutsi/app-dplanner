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

- **Tests can be read grouped by what collects them.** The Tests tab's third selector groups
  rows by feature, milestone or check, filled by `scope.gatherers()` in the one place rows
  are ordered (`TestsActivity._rows`); `TestsTable` draws a spanned heading wherever the key
  changes, and a step nothing gathers lands under *Not in any feature* — the same steps
  `dplanner project lint` reports as `scope.ungathered`. A step two features both wait on
  gets one **joint** heading rather than two rows: a test listed twice is a test marked
  twice.
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
  *behind* only when the diff touched its paragraph. `coverage/trace.py` arranges
  passages → features → milestones → tests and docs from every module's Qt-free half
  (assembled in the root's `_coverage_trace`), and **the path rule is feature
  membership**: every item carries the features it serves, so what lights up on a pick
  is one set intersection with no case per kind. `dplanner coverage show|spec|review`
  print it; the Coverage tab draws it as four lanes with links in the gutters; the Specs
  tab washes passages (`show_passages`) and offers *Cited*, *Coverage* and *Cite…*;
  `steps.details` lands on a test or a feature through `FocusableExtension`. Uncovered
  text is a report (`coverage spec --uncovered`), never a lint; it is also how an old
  project is retrofitted. `ARCHITECTURE.md`'s *A citation is a quote and a digest* has
  the reasoning.
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
