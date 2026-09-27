# Home, where a window starts (F9)

Rendered by `uv run python scripts/render_home.py --out docs/screenshots/f9-home`. The script
builds a whole application over a throwaway library of two projects, with nothing
remembered, and stops the garden's clock to step it by hand, so every run draws the same
moments. Add `--video DIR` to film one season at sixty frames a second into an MP4 per theme
(it needs ffmpeg; the films are for looking at, not committing). Re-run it after changing
the guide, the page or the garden, and commit the pictures.

| Image | What it shows |
|---|---|
| `home-*` | The program's start with no tabs to reopen: the Home tab, Home at the top of the index, the guide centred — each step's button is the verb itself, *Open Agent in Code* greyed with its own reason until a project is picked — over the garden twenty-two seconds into a season. |
| `garden-*` | The garden alone at six moments of one season, top to bottom: the first seed sprouts; both agents at work, sprinkling; a bloom's pulse running down the roots to what it unblocks; most of the plan in bloom; the milestone opening last; the petals let go before the next season is sown. |
| `projects-menu-*` | A right-click on the Projects folder: the File menu's project group, *Share Project…* greyed because no project is picked. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
