# F10 — The Control Centre: what needs a person in every project

Rendered offscreen in the dark and the light theme, over a synthetic library of two projects
(*Big* and *Sibling*), by `scripts/render_boards.py`:

```
uv run python scripts/render_boards.py --out docs/screenshots
```

| Image | What it shows |
|---|---|
| `control-centre-*` | both projects as one board: the Step statuses strip with the *Projects* filter after the groups, each row naming its project, ranked across projects by what finishing it unblocks, and a ⋮ at every row's end |
| `control-centre-filtered-*` | the filter on one project: its face names the pick and the rows narrow to it |
| `row-menu-*` | a review row's ⋮: Run Agent and its profiles, Show Agent Terminal, Open Terminal in Worktree and Open Pull Request — each greyed with its reason where it cannot run — then Step Details and Show in |

The one-project tab wears the same ⋮ and no Project column: `../f6-step-statuses/`. The ⋮ as a
primitive is Debug ▸ Design Examples ▸ Table: `../f1-design-example/table-*`.
