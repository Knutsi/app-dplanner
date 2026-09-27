# F6 — Ready for review and Ready to merge, and the Step statuses tab

Rendered offscreen in the dark and the light theme. The tab by `scripts/render_boards.py`:

```
uv run python scripts/render_boards.py --out docs/screenshots/f6-step-statuses
```

| Image | What it shows |
|---|---|
| `step-statuses-*` | the Step statuses tab: the strip (Run Agent with its profiles, Ready to Merge, Done), the group filter, the table grouped Ready to merge · Ready for review · Ready to start · Waiting, a box on every row |
| `step-statuses-ticked-*` | the two reviews ticked: the box is the selection, and the strip's verbs act on it |
| `step-statuses-review-*` | the filter on one group: its heading stands down, because the lit segment says it |
| `canvas-spines-*` | a card per status: in progress blue, ready for review amber, ready to merge green, done green all over, blocked red — and a wait beside them |
| `report-graph-*` | the published report's graph: the same spines, and a pill saying the word |
