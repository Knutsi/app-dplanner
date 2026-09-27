---
paths:
  - "src/dplanner/domain/{model,commands,ids}.py"
  - "src/dplanner/cli/lookup.py"
  - "src/dplanner/modules/auto_progress/**"
  - "tests/domain/test_{model,ids}.py"
  - "tests/modules/test_auto_progress*.py"
  - "tests/cli/test_auto_progress_verbs.py"
---

# Graph model — edges, auto-progress links, step numbers and isolation

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
- **A step has a number, and the key is how it is named everywhere.** `Step.number` is
  dealt by `Library.add_child` from the project's `last_number` high-water mark — one
  sequence per project, never reused (a deleted step's branch may live on), kept through
  undo, a paste and an import — and written to `step.json` / `project.dproj` (format 2;
  the migration numbers an old project's steps in `children` order). The **letter is
  presentation**: `_step_key` in the root reads the kind — `M` milestone, `F` feature,
  `C` check, `S` otherwise, the coarser claim first — so a step keeps its number when its
  kind changes and the letter follows. One rule, four readers: the card's key block, every
  CLI row and `find_step` (`S7`, `s7` and `7` all resolve; several projects' `7` is
  refused), the run name a worktree and branch carry, and the briefing's verbs. Never
  store the letter, and never mint a number anywhere but `add_child`.
- **An auto-progress link is an aspect on the step that waits, read through the edge.**
  `modules/auto_progress/` stores `{"from": [source ids]}` on the waiter, and an id counts
  only while the waiter's own `requires` lists it (`flagged`) — so no verb that rewrites an
  edge list learns the aspect exists, a redirected link arrives plain, and undoing a removal
  restores the flag with the link. **Never repair the list from an edge verb**; the one
  place ids change is a paste, which hands every `PastePolicy` the old→new map
  (`remap_for_paste`). **Whether a link frees its waiter from review on** is the root's one
  `_auto_progresses`, handed as `auto_progresses(waiter, source)` to the progression walk,
  Run Agent's gate, `project graph`/`step show` and the canvas's `edge_accents`, so every
  surface agrees with the frontier — **and a link into a review always auto-progresses**, by
  the review's rule ORed in there rather than by a flag written onto it; the Edge menu shows
  such a link checked and greyed with that reason (`AutoProgressDeps.always`). **Whether a
  step must land its sources' work** is the flag alone — the aspect's `sources` and
  `collectors`, read by *Work you collect*, the source's epilogue, `auto-progress list` and
  lint — because that duty is only ever given by flagging. Only an agent step collects: the
  Edge menu's *Auto-progress* greys on any other waiter, and lint `auto-progress.waiter`
  names one the CLI or a hand edit made.
  `ARCHITECTURE.md`'s *An auto-progress link is an aspect on the step that waits* weighs
  it against data on the edge and a new edge kind.
