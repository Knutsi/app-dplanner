# The graph editor's chrome (S7)

Rendered by `uv run python scripts/render_graph_editor.py --out docs/screenshots/s7-graph-editor`,
which builds a whole application over a throwaway library and grabs the project tab the
window itself builds. Re-run it after changing the strip, the picker or the side panel, and
commit the result.

| Image | What it shows |
|---|---|
| `strip-*` | The strip of verbs as glyphs in named bands — Go, Step, Link, Arrange, History, Options — with the layout picker outside it at the right, where it never folds. |
| `overflow-*` | A canvas dragged narrow: whole bands leave the strip from the right and are listed in the `…` menu as glyph **and** words, a rule where each band begins, with the Options face as a child menu of the same entries. |
| `find-*` | *Find Step…* (`Ctrl+F`, or `/` on the canvas): the plan's landmarks — its milestones and features — before anything is typed, each wearing the badge or the glyph it wears on the graph. Typing searches every step, by name or by key. |
| `problems-*` | The Problems list beside the canvas inside the project tab, where what is wrong with the plan is fixed: a panel header with its way out, one worded face dropping the launch profiles, and two-line rows naming the verb that closes each finding. Its count leads the strip, in a band of its own. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
