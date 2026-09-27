# Contract: closing up space the way Divide opens it (F15)

Rendered by `uv run python scripts/render_graph_editor.py --contract --out docs/screenshots/f15-contract`,
which builds a whole application over a throwaway library. The drag is driven with real mouse
events, as a person's would be. Re-run it after changing the cut modes in
`project_editor/modes.py` or the Divide family in `canvas_verbs.py`, and commit the result.

| Image | What it shows |
|---|---|
| `dropdown-*` | The Divide button's arrow. Divide's pair opens room; Contract's pair, under a rule of its own, takes it back. |
| `closing-*` | A contract held mid-drag across an upright cut. The feature and the milestone had been pushed two columns out. Dragged far past where they belong, they stop one gap from *Write the parser*, the first card in their row. The dashed band is how far the side has been pulled, and the status line names the pair that stopped it. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
