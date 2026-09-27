# Parallel work handed to a step that collects it (F11)

Rendered by `uv run python scripts/render_graph_editor.py --auto-progress --out docs/screenshots/f11-auto-progress`.
The script builds a whole application over a throwaway library. The plan is one round:
- three agent steps in parallel: one ready for review, one being worked by a live agent, one
  still in progress;
- a plain prerequisite that is already done;
- the step that collects the three.

Re-run it after changing how `EdgeItem` draws an `EdgeAccent`, and commit the result.

| Image | What it shows |
|---|---|
| `round-*` | The three links into the collector auto-progress. Each is drawn as two rails with chevrons running between them towards the step that waits. The link out of the step being worked carries the live ring's motion: its chevrons move on the same clock (this is a still, taken two ticks in). The link from the done prerequisite is plain and single. |
| `menu-arrow-*` | An auto-progress arrow right-clicked: *Auto-progress* stands between Remove Link and Redirect ▸, ticked. The entry has no glyph, because a ticked entry that wears one shows no tick in these menus. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
