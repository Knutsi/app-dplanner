# Home, where a window starts (F9)

Rendered by `uv run python scripts/render_home.py --out docs/screenshots/f9-home`. The script
builds a whole application over a throwaway library of two projects, with nothing
remembered, and grabs the window. Re-run it after changing the guide or the page, and commit
the result.

| Image | What it shows |
|---|---|
| `home-first-*` | The program's start with no tabs to reopen: the Home tab, Home at the top of the index, the guide — each step's button is the verb itself, *Open Agent in Code* greyed with its own reason until a project is picked — beside Recent's empty state. |
| `home-*` | Home opened from *Go ▸ Home* once four views of Importer were kept and closed: Recent lists them newest first, each with when it was last in front, and one click reopens one. |
| `projects-menu-*` | A right-click on the Projects folder: the File menu's project group, *Share Project…* greyed because no project is picked. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
