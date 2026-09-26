# S15 — Tables and browsers, before and after

The surfaces the tables-and-browsers pass brought up to the design system, rendered offscreen
in the dark and the light theme by `scripts/render_tables_and_browsers.py`, over a synthetic
library of forty-eight steps (three milestones, a few dozen tests, a handful of notes), with
per-user settings in a throwaway directory:

```
uv run python scripts/render_tables_and_browsers.py --out docs/screenshots/s15-tables-and-browsers
```

`before-*` are the same script run with `--prefix before-` on the commit the pass started from;
the unprefixed images are the pass. A `-picked` image is the same surface with its second
selectable row picked, which is where a table's accent edge over the quiet ground is read.
Compare each against `docs/screenshots/f1-design-example/`; `DESIGN.md`'s *Bringing a surface
up* is the list of what to compare.

| Image | What it shows |
|---|---|
| `before-tests-*` | The Tests tab as it was: a hand-rolled table borrowing `#OrderTable`, 44 px rows, two strips of worded buttons and bare combo boxes. |
| `before-all-tests-*` | The roll call of every project's tests, on the same page with an empty strip. |
| `before-coverage-*` | The Coverage tab: the lanes, under a strip whose summary is a label rewritten by hand. |
| `before-assets-*` | The Assets tab: two unstyled lists, a strip of Fusion controls, three buttons under the detail pane. |
| `before-notes-*` | The Implementation notes tab: a frameless list borrowing `#OrderTable`, no strip. |
| `before-estimates-*` | The bulk Estimates tab: a raw `QTableWidget` with a spin box and nine chips embedded in every row. |
| `before-time-*` | The Time tab: a `control_bar` of labels, toggles and combos, and the milestone rows laid out by hand. |
| `before-tasks-*` | The task browser: a plain dialog, a well of hand-laid rows with indeterminate bars. |
| `before-agents-*` | The Agents browser: the task browser's copy, with no stylesheet for the copy. |
| `before-palette-*` | The command palette open, filtered to *mark*, and with nothing matching. |
| `tests-*`, `tests-picked-*` | The Tests tab on the table primitive: one strip of glyph verbs and selectors, results in their tone, headings in a milestone's shade at a plain row's height. |
| `all-tests-*`, `all-tests-picked-*` | The roll call across the library, debounced, with its indicator and *Show archived*. |
| `coverage-*` | The Coverage tab: its *Review* verb a glyph on a `Toolbar`, the facts beside it as a note. |
| `assets-*`, `assets-picked-*` | The Assets tab: two tables under one strip — attach, open, copy the path, delete, clean up — and a filter over *unused* and each source. |
| `notes-*`, `notes-picked-*` | The Implementation notes tab: a `RichList` under a strip with *Add Note…*, *Remove Note* and a label filter. |
| `estimates-*`, `estimates-picked-*` | The bulk Estimates tab: the quick sizes painted in the cell, one lit per row so the column reads as a grid; zero past a rule, a last chip that opens the number and shows one off the scale. |
| `time-*` | The Time tab (v5): four figures over one `Toolbar` — the pages as a `Segmented`, the plan compared with, the Budget — and the Milestones page, a row per milestone. |
| `tasks-*` | The task browser: a `RowWell` on the dialog frame, a busy line where no fraction is known and a 4 px bar where one is. |
| `agents-*` | The Agents browser: the same well, the run's mood as the status line's tone, the way back in as a note. |
| `palette-*`, `palette-filtered-*`, `palette-nothing-*` | The command palette, filtered, and saying so when nothing matches. |
