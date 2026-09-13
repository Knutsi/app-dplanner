# The Windows check (S17)

Rendered by `uv run python scripts/render_windows_check.py --out docs/screenshots/s17-windows`.

| Image | What it shows |
|---|---|
| `debug-menu-*` | The Debug menu's Windows band on a machine that can run it — Omarchy, from a source checkout. **Windows Check** runs the suite, the lint, the types and the frozen build in the VM as a task, because it is minutes of blocking work. **Windows Desktop** opens an RDP session through `omarchy-windows-vm launch --keep-alive` — Omarchy's own launcher, which knows the credentials file, the HiDPI scale and the client; `--keep-alive` is what stops it shutting the developer's VM down when the window closes. |
| `debug-menu-refused-*` | The same two anywhere else: **disabled, never hidden, with the reason in each one's own label**. They derive different refusals from the same two facts — watching needs only the VM, running needs the harness as well — because refusing to open a session that would work is refusing something that works. |

Dark and light (`-dark`, `-light`).

The machine is chosen by swapping `debug/module.py`'s bound `probe` before the session is
built, never by reaching into the module afterwards — the module asks once, at construction,
because an action state may not walk PATH.

## Rendered on Windows

`on-windows/` holds six of the seventy-eight PNGs the screenshot scripts produced when
`windows_check.py render` ran them on the throwaway box (Windows 11 build 26200, offscreen):
the Checklist, the design system's table and the graph editor's Find picker, dark and light.
Every screenshot script in `scripts/` builds a whole application over a throwaway library,
so each of these is the store, git, the theme and the canvas working on Windows — the same
scripts, the same sizes, only the platform's text rendering to tell them apart.
