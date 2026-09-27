# The canvas's right-click, by what is under it (F7)

Rendered by `uv run python scripts/render_graph_editor.py --menus --out docs/screenshots/f7-canvas-menus`,
which builds a whole application over a throwaway library. Each shot is right-clicked the way
a person would: the click makes its subject current, and the pop-up is what the handler would
show. Re-run it after changing `project_editor/canvas_menus.py` or a band it names, and commit
the result.

| Image | What it shows |
|---|---|
| `menu-card-*` | A card: the Step menu, whole, and nothing about the canvas. No Find, Go, Lasso, New or Redirect. |
| `menu-arrow-*` | An arrow, now picked by the click: Remove Link and Redirect ▸, and nothing else. |
| `menu-mixed-*` | Two steps and an arrow picked together, right-clicked on one of the steps. It leads with narrowing the pick, then the clipboard verbs over all of it (*Delete 3 Items*), then each kind's own verbs one level down. |
| `menu-background-*` | Empty canvas, where the click let go of the pick. It offers making something where the click was, finding and picking steps, Select All, and the project's views. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
