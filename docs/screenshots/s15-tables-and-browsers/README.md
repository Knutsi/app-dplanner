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
