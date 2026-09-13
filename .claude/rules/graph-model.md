---
paths:
  - "src/dplanner/domain/{model,commands,ids}.py"
  - "src/dplanner/cli/lookup.py"
  - "tests/domain/test_{model,ids}.py"
---

# Graph model — edges, step numbers and isolation

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
  `graph.requires-dangling` in lint is what names one that arrived from outside.
- **A step has a number, and the key is how it is named everywhere.** `Step.number` is
  dealt by `Library.add_child` from the project's `last_number` high-water mark — one
  sequence per project, never reused (a deleted step's branch may live on), kept through
  undo, a paste and an import — and written to `step.json` / `project.dproj` (format 2;
  the migration numbers an old project's steps in `children` order). The **letter is
  presentation**: `_step_key` in the root reads the kind — `M` milestone, `F` feature,
  `C` check, `S` otherwise, the coarser claim first — so a step keeps its number when its
  kind changes and the letter follows. One rule, four readers: the canvas spine, every
  CLI row and `find_step` (`S7`, `s7` and `7` all resolve; several projects' `7` is
  refused), the run name a worktree and branch carry, and the briefing's verbs. Never
  store the letter, and never mint a number anywhere but `add_child`.
