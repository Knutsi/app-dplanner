# The graph editor's chrome (S7)

Rendered by `uv run python scripts/render_graph_editor.py --out docs/screenshots/s7-graph-editor`,
which builds a whole application over a throwaway library and grabs the project tab the
window itself builds. Re-run it after changing the strip, the picker or the side panel, and
commit the result.

| Image | What it shows |
|---|---|
| `strip-*` | The strip of verbs as glyphs in named bands — Go, Step, Link, Arrange, History, Options — with the layout picker outside it at the right, where it never folds. |
| `overflow-*` | A canvas dragged narrow: whole bands leave the strip from the right and are listed in the `…` menu as glyph **and** words, a rule where each band begins, with the Options face as a child menu of the same entries. |
| `jump-*` | *Jump to* (`/` on the canvas): the plan's landmarks — its milestones and features — before anything is typed, each wearing the badge or the glyph it wears on the graph. Typing searches every step, by name or by key. |
| `features-*` | The Features list beside the canvas inside the project tab, where the drag onto the graph is a short one: a panel header with its way out, a strip of verbs, and two-line rows saying what became of each feature. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
