---
paths:
  - "src/dplanner/domain/{model,commands,ids}.py"
  - "src/dplanner/cli/lookup.py"
  - "src/dplanner/modules/steps/**"
  - "{src/dplanner,tests}/modules/branches/**"
  - "src/dplanner/domain/branches.py"
  - "tests/domain/test_{model,ids}.py"
  - "tests/modules/canvas/test_stack_edits.py"
  - "tests/domain/test_branches.py"
  - "tests/cli/test_branch_verbs.py"
---

# Graph model — edges, step numbers and isolation

- **Every model change goes through a command** on the single undo stack, and carries an
  `origin` so the view that made the edit can ignore its own echo. Two kinds of change
  bypass the stack, never the vocabulary: an external fact (`persistence.md`'s sync bullet) and
  **reading disk** — `load`, membership, and the store adopting another writer's change —
  which apply the library's mutators directly with an origin of their own.
- **`Library.link_refusal()` is the only authority on a legal edge.** `set_edges` asks it
  before writing, and `steps.link`'s state asks it to decide whether the menu entry is enabled
  and what a greyed one says. Never write a second reachability check in a view
  (`docs/architecture/graph-model.md`'s *The graph, and what it stores* has why).
- **Isolate is one domain question and one domain command.** `Library.boundary_edges()`
  names every edge with exactly one end in a set (both kinds, skipping edges to a deleted
  step, as the canvas skips them) and `remove_edges_command()` turns edges into one
  `CompositeCommand` of per-`(waiter, kind)` replacements — Unlink, `steps.isolate` and
  `dplanner step isolate` all build from those two, so the surfaces cannot drift.
- **An edge lives on the step that waits**, is validated against the project, and the
  model deliberately does *not* rewrite it when a step is deleted — undo has to restore the
  graph exactly. `Library.requires()` skips ids it cannot resolve. Edge kinds this build does
  not know are loaded and written back untouched. **`set_edges` judges only what a write
  adds**: an id already in the list — a ghost an outside edit or a merge left — is carried,
  never re-judged, because re-judging the whole list froze every survivor of a deleted step
  (Link, Unlink, Redirect and Isolate all replace that list; 2026-09-08). **And every verb
  that deletes a step takes the links into it along**: Delete, Cut, `dplanner step remove`
  and `project clear-steps` are one `remove_steps_command`, a composite that undoes in
  reverse — steps back first, then the lists that named them — so nothing writes a ghost.
  Delete hands it the arrows picked beside the steps as well (`links=`); they join the same
  per-list removal, so a list losing both is rewritten once.
  `graph.requires-dangling` in lint is what names one that arrived from outside.
- **What may link to what is the graph's four refusals, then the rules a module adds.**
  `Library.link_rules` is a tuple the composition root installs — `default_link_rules()`,
  on the window's library in `default_modules` and on the CLI's through `entry.py → run →
  open_library` — and `link_refusal` asks each after its own four, so the canvas under the
  cursor, `steps.link`'s state, Redirect and `step link` still ask one question. The stack's
  "one in, one out" (`canvas/stacks/stack.link_rule`) is the first. **A rule judges only
  the first redo of a link a person chose**: `SetEdgesCommand` asks with `rules` and on its
  first redo alone, and an undo, a replayed redo, the store adopting another writer's list,
  `project import`, a paste's clones and every rewire pass `rules=False` and meet only the
  four — each carries links that already exist, and judged again one could refuse halfway
  through a composite over a stack somebody broke. **An edit whose links depend on
  something else it changes is a `rewire_command`**: every removal, then `between` (a
  membership, a seat, a node born or removed), then every addition, so each graph on the
  way is a part of the one before or the one after and the cycle check cannot trip
  halfway; `remove_edges_command` and `remove_steps_command` are built on it. Never judge a
  rule anywhere but `link_refusal`. `docs/architecture/canvas.md`'s *One in, one out is a rule the
  domain asks* has the reasoning and the proof.
- **A step has a number, and the key is how it is named everywhere.** `Step.number` is
  dealt by `Library.add_child` from the project's `last_number` high-water mark — one
  sequence per project, never reused (a deleted step's branch may live on), kept through
  undo, a paste and an import — and written to `step.json` / `project.dproj` (format 2;
  the migration numbers an old project's steps in `children` order). The **letter is
  presentation**: `planning.kinds.key_of` reads the kind off the one `RANKING` — `M`
  milestone, `F` feature, `C` check, `W` wait, `B` cut, `S` otherwise, the
  coarser claim first — so a step keeps its number when its
  kind changes and the letter follows. One rule, four readers: the card's key block, every
  CLI row and `find_step` (`S7`, `s7` and `7` all resolve; several projects' `7` is
  refused; **with a current project a key, folder name or title resolves there or not at
  all** — only an id of eight characters or more names another project's step), the run
  name a worktree and branch carry, and the briefing's verbs. Never store the letter, and
  never mint a number anywhere but `add_child`. `docs/architecture/graph-model.md`'s *A key
  is the current project's, an id the library's* has the reasoning.
- **A branch stretch is a cut and a landing, and what is on it is derived.**
  `modules/branches/` holds two aspects: `branch_cut` (`{"branch": …}`) on a step nobody
  works — no status of its own, done once what it waits on is (a wait of no days, composed
  in `schedule.status_on`, never through the schedule's `wait_of`) — and `branch_land`
  (`{"cut": id}`) on the agent step that merges it back, counted only while that cut is
  upstream (a stored id read through the graph, never repaired by an edge verb). **Membership is
  never stored**: `domain/branches.py` reads it forwards — everything after the cut, until
  the landing — and nesting is derived (a stretch whose cut and landing are both members of
  another is a branch off it; a step's base is the innermost *open* stretch holding it).
  One reading, cached by the branches module and forgotten on every change, feeds Run
  Agent's plan, the canvas's lanes and strips and the briefing; the CLI reads afresh.
  **Put on a Branch** (`edits.put_command`) and **Remove Branch** (`remove_command`) are
  one rewire each — outside inputs move to the cut and outside dependents to the landing,
  and back — refused by `ordering.left_between`, the walk `stack make` shares, by a pick
  that crosses another stretch, and by one that splits a stack (`stack.stack_split`, the
  graph editor's fact handed in). Remove is never partial, so the window asks first.
  `planning.kinds.works_nobody` is what a wait and a cut share — "a wait", "a branch cut" — and
  every module refusing such a step a status, an agent or a test words its
  refusal from it. `docs/architecture/graph-model.md`'s *A branch stretch is bracketed by a cut and
  a landing* has the reasoning.
