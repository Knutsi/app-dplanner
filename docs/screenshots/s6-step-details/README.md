# S6 — the step detail dialog

Rendered by `scripts/render_step_details.py`, in both themes:

```
uv run python scripts/render_step_details.py --out docs/screenshots/s6-step-details
```

The panel has one host — the modal `steps.details` opens — so every image here is of that.
It was anchored in the window's right area as well until the Tests roster made the cost
plain; `ARCHITECTURE.md`'s *The step editor is a modal* has the reasoning.

| image | what it shows |
|---|---|
| `dialog-*` | `StepDetailsDialog` on `DialogFrame`: every Type toggle as a glyph on the left of the aspect bar, the Template dropdown on the right, one Close in the footer and no heading — it starts at the panel. Every edit in it is live, so there is nothing to confirm; the button is there because a window manager that draws no title bar leaves Escape as the only way out. |
| `dialog-bare-*` | the same step with every aspect turned off — the blocks stay at the top, which is what S6 fixed |
| `templates-*` | the dropdown: the five templates, each glyph in its own body tone, the current one ticked |
