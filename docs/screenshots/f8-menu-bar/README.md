# The menu bar, sorted by subject (F8)

Rendered by `uv run python scripts/render_menu_bar.py --out docs/screenshots/f8-menu-bar`.
The script builds a whole application over the Importer plan that `render_graph_editor.py`
builds, with its graph tab open, and grabs each menu as it drops from the bar. Re-run it
after moving a group, and commit the result.

| Image | What it shows |
|---|---|
| `bar-*` | The bar, one subject per menu, with Go new between View and Project. Every title has its own Alt letter: Go took G, so Graph's is r. |
| `menu-go-*` | Go, the places: a project's surfaces in the index's order, then Estimate Steps and Preview Report (the two with no row there), then the library's Archive. |
| `menu-project-*` | Project, the verbs on a project: its settings and plan, whether it is in the library, Specs, Open Agent in Code, Compile Out of Date, and the test run. |
| `menu-project-specs-*` | Project ▸ Specs: the Add Spec child, then what acts on the document picked in the Specs tab, then on its source. Greyed here, because nothing is picked in a Specs tab. |
| `menu-graph-*` | Graph: its groups are unchanged. Go ▸ became Select Nearest ▸, and the clashing letters are re-dealt (Frame, Spotlight, Problems). |
| `menu-step-*` | Step with a feature picked. The nine show entries are now Step Details…, one Show in child, and Test Details. Type, Test, Test Category and Test Sort Key are gone: a step's kind is set with the aspect bar in Step Details, and its tests on its Tests tab there. |
| `menu-step-show-in-*` | Step ▸ Show in: what lands on this step (Coverage, Spec Passage, Documentation), then the rest a table reaches from a row (Graph, Order, Step Statuses, Tests). A card's right-click renders only the first three. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
