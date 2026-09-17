# The Tests view, rendered

The surfaces a test roster is read and run from, rendered offscreen in the dark and the
light theme by `scripts/render_tests_view.py` over `scripts/synthetic_library.py`'s plan:

```
uv run python scripts/render_tests_view.py --out docs/screenshots/s16-tests-view
```

Every one is the real surface, built by a whole application — nothing here hand-wires a view
the window would build differently. Re-render after changing the Tests tab, the Test panel,
the reference preview or the category editor.

| Image | What it shows |
|---|---|
| `tests-filed-*` | the Tests tab filed by category: the catalogue's own order, a category's glyph beside its heading, the Sort key column, and the rows sharing a key adjacent because *Ergonomic order* (the lit verb at the right of the strip) is on |
| `tests-folded-*` | the same tab with a category shut: the chevron turned, its rows gone, the next heading up where you can reach it — what folding is for on a roster of two hundred |
| `test-panel-*` | the Test panel a run is worked down from: what the test is filed under, its last result, the four result verbs, *Show Step*, and Previous/Next — with the body **rendered**, because a numbered list is a numbered list on a surface you execute from, and beside the roster, inside the Tests tab, because the tab is what feeds it and a tab in the background must never follow the tab in front |
| `test-preview-*` | the preview a reference in a body opens: the referenced test read over what you were reading, **Back** for the trail when it references another, *Close* putting you back where you were, and *Show in Tests* as the one deliberate move |
| `category-editor-*` | the modal that renames, re-icons and reorganises: a count on every row saying how many tests a rename is about to move, *Uncategorised* last and never editable, and nothing written until Save |

`ARCHITECTURE.md`'s *A test is filed under a category*, *The sort key is an ergonomic* and
*A test is run from a panel* — and *A reference is a link, and a link is a preview* — have
the reasoning behind each.
