# F6 — Ready for review and Ready to merge, and the Step statuses tab

Rendered offscreen in the dark and the light theme. The tab by `scripts/render_boards.py`:

```
uv run python scripts/render_boards.py --out docs/screenshots
```

| Image | What it shows |
|---|---|
| `step-statuses-*` | the Step statuses tab: the strip (Run Agents, in words, with its profiles; Ready to Merge and Done as glyphs), the group filter, the table grouped Ready to merge · Ready for review · Ready to start · Waiting, a box on every row and a ⋮ at its end (F10) |
| `step-statuses-ticked-*` | the two reviews ticked: the box is the selection, and the strip's verbs act on it |
| `step-statuses-review-*` | the filter on one group: its heading stands down, because the lit segment says it |

The two new words on a card — the key block washed amber for ready for review and green for
ready to merge, a pill saying each — are in `../f5-key-block/`: `cards-*` on the canvas and
`report-page-*` in the published report. They were first drawn here on the 26 px spine the
key block replaced, and landed on the block when the two changes were merged.
