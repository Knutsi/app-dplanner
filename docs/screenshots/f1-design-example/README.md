# Debug ▸ Design Example, rendered

The design system's three reference surfaces (`src/dplanner/modules/debug/design_example.py`),
rendered offscreen in the dark and the light theme by `scripts/render_design_example.py`:

```
uv run python scripts/render_design_example.py --out docs/screenshots/f1-design-example
```

Re-render after changing a primitive or a rule; a pull request that touches a surface shows
its own screenshots beside these. `DESIGN.md`'s *Primitives* table says which image shows
which primitive.

| Image | What it shows |
|---|---|
| `dialog-*` | the modal on `DialogFrame`: title in the body, a lead, captions over fields, a validation note, a table, every signalling state, the footer band with the destructive verb far left and the accent primary |
| `dialog-refused-*` | the same, its primary refused: greyed, its name kept, the reason in the footer's status slot |
| `dialog-working-*` | the same with its demo work running: the *Change something* glyph turning, *Updating…* at the right |
| `table-*` | the table tab: the `Toolbar` of glyph verbs, the filter, a combo, the table with headings, two-line cells, a key badge on each milestone row |
| `table-selected-*` | a row picked: the accent edge over the quiet ground, a tinted row keeping its tint, the verbs reworded by the selection |
| `table-filtered-*` | a filter on: the funnel filled with its dot, the accent wash and border, the clear cross live, the rows narrowed |
| `filters-*` | the filter's popup: checkable entries that stay open while toggled |
| `dropdown-*` | the combo's list in the menu's look |
| `table-empty-*` | the empty state trading places with the table, its verb under the line |
| `toolbars-*` | the toolbars tab: a flat strip of verbs, a tool palette in named bands of squares, the same palette cut short so a band folds, and the dense strip that answers a question rather than offering verbs |
| `toolbars-folded-*` | what a folded band looks like in the `…` menu: glyph *and* words, a rule where each band begins |
