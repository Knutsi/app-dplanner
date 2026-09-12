# S6 — the step detail panel and its dialog

Rendered by `scripts/render_step_details.py`, in both themes:

```
uv run python scripts/render_step_details.py --out docs/screenshots/s6-step-details
```

| image | what it shows |
|---|---|
| `panel-*` | the anchored panel: every Type toggle as a glyph on the left, the Template dropdown on the right |
| `panel-bare-*` | the same step with every aspect turned off — the blocks stay at the top, which is what S6 fixed |
| `templates-*` | the dropdown: the five templates, each glyph in its own body tone, the current one ticked |
| `dialog-*` | `StepDetailsDialog` on `DialogFrame`: no footer, and no heading — it starts at the panel |
