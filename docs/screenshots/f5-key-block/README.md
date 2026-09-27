# The key block: who works a step, beside its key (F5)

A card's left edge used to be a 26 px spine with the key rotated up it. It is now a 56 px
key block: a glyph for who works the step, over the key set level. The glyph is a sparkle
for an agent, a person otherwise, and an amber clock for a wait. The block is washed by
status as the spine was. The graph editor's earlier shots, before this change, are in
`s7-graph-editor/`.

| Image | What it shows | Made by |
|---|---|---|
| `cards-*` | Each card shape in one of three rows. The first row is who works it: a person, an agent, a wait. The second is what it is: a feature, a check, a milestone. The third is where it stands: in progress (an agent's), blocked, done. The narrowest card is at the bottom right. The top edge's medallions carry no spark and no clock. | `uv run python scripts/render_graph_editor.py --out docs/screenshots/f5-key-block`. The script also writes S7's `strip`, `overflow` and `problems` shots, which are not kept here. |
| `find-*` | *Find Step…*: every row but a milestone's wears the key block's glyph, with the kind in words under the title. | the same run |
| `coverage-*` | The Coverage tab, where a milestone's or feature's card wears the same block. | `scripts/render_tables_and_browsers.py`'s Coverage tab, at its 1180 px |
| `coverage-narrow-*` | The same tab dragged to 760 px, where each lane stands at `LANE_MIN_W`. That minimum grew to 198 px so a title still shows two words past the wider block. | the same tab, resized |
| `report-page-*` | The report's *Plan* graph in a browser, in both themes. The page carries one light drawing and restyles it by class, so the block's quiet wash and its ink glyph each have a dark rule. | `env -u DPLANNER_PROJECT uv run python scripts/render_sample_report.py --out DIR`, then headless Chromium with `--blink-settings=preferredColorScheme=0` (dark) or `1` (light) |
| `report-paper-light` | The right end of the same graph through QtSvg, the renderer the window's PDF uses. The wait `W12` wears the amber clock and `S13` the spark. | `graph_svg(graph, LIGHT)` rendered by `QSvgRenderer`, as `modules/reporting/paper.py` does |
