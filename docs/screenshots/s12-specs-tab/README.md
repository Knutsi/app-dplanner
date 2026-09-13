# S12 — the Specs tab as a CRUD surface

Rendered by `uv run python scripts/render_specs_tab.py`, dark and light.

| Image | What it shows |
| --- | --- |
| `specs-tab-editor-*` | The tab on a document this project owns: the verbs as glyphs over the tree, the document's own strip, the markdown strip, the editor at a readable measure, and the figure it links to in the gallery under it. |
| `specs-tab-source-updates-*` | A source with updates: the count over the whole tree, this source's own line in the strip below its facts, and the mark the tab title wears. |
| `specs-rename-prompt-*` | Rename on `LinePrompt`, refusing a name another document already answers to — the reason under the field and the primary greyed. |
| `specs-expanded-editor-*` | The same document in a window of its own: the same `QTextDocument`, so it is one buffer and two views, with the same markdown strip. |
