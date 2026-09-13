"""Copy the Tabler icons this application uses into ``theme/glyphs/``.

    uv run python scripts/vendor_tabler_icons.py

Only the icons named in :data:`GLYPHS` are taken — the full set is over six thousand files,
and a repository does not want six thousand files to use fifty. Adding a glyph is adding a
line here and running this again; the files land verbatim, so what is committed is exactly
what Tabler published.

**Tabler Icons is MIT** (`tabler/tabler-icons`), which allows use, modification and sale
with one obligation: the copyright notice and licence text travel with the distribution.
That is why ``LICENSE`` comes down beside the SVGs and why Help ▸ About names the set —
see ``modules/appshell/about.py``.

The tag is pinned, and pinned in ``theme/icons.py`` rather than here — the application is
what has to say which version it uses, in Help ▸ About. A bump is a deliberate act: change
``TABLER_TAG`` there, run this again, look at the diff, and re-render the screenshots.
"""

import argparse
import sys
import urllib.request
from pathlib import Path

from dplanner.theme.icons import TABLER_TAG

TAG = TABLER_TAG
SOURCE = "https://raw.githubusercontent.com/tabler/tabler-icons"
GLYPH_DIR = Path("src/dplanner/theme/glyphs")

# What each glyph in this application *means*, and the Tabler icon that says it. The key is
# ours and outlives any set: a later change of icons is a change of the right-hand column.
GLYPHS: dict[str, str] = {
    # -- the canvas strip ------------------------------------------------------------
    "plus": "plus",
    "edit": "pencil",
    "trash": "trash",
    "lasso": "lasso",
    "link": "link",
    "connect": "link-plus",  # A chain with a plus: the mode that adds one.
    "unlink": "unlink",
    "isolate": "scissors",  # Cut loose: every link into or out of these steps, gone.
    #                        Not another crossed chain — beside Unlink's it was a riddle.
    "redirect-to": "arrow-ramp-right",  # One end of a bundle moving onto another step…
    "redirect-from": "arrow-ramp-left",  # …and the mirror of it, for the other end.
    "divide-vertical": "separator-vertical",  # A cut, with room being made either side.
    "divide-horizontal": "separator-horizontal",
    "sort": "hierarchy-2",  # Laying the graph out by what feeds what.
    "region": "rectangle",
    "grid": "grid-dots",
    "undo": "arrow-back-up",
    "redo": "arrow-forward-up",
    "frame": "maximize",
    "refresh": "refresh",
    "star": "star",  # The default — what a plain Run Agent… runs.
    "find": "search",  # Find a step by name or key; it is bound to Ctrl+F.
    #                   Not a focus frame: beside Frame's corners it was the same picture.
    "options": "adjustments-horizontal",  # How the graph is drawn, not what is drawn.
    "mark-starts": "arrow-bar-right",  # A bar with the flow leaving it.
    "mark-ends": "arrow-bar-to-right",  # The flow arriving at a bar.
    "mark-orphans": "circle-dotted",  # Joined to nothing.
    "list": "list-numbers",
    "close": "x",
    "info": "info-circle",
    # -- the index, and what a row is about -------------------------------------------
    "container": "folders",
    "leaf": "file-text",
    "project": "layout-board",
    "graph": "topology-star-3",
    "spec": "file-description",
    "folder": "folder",
    "branch": "git-branch",
    "external": "external-link",
    "typewriter": "file-pencil",  # A page being written: the agent's instructions.
    "coverage": "chart-dots-3",
    "read": "book",
    "gauge": "gauge",
    "clock": "clock",
    "image": "photo",
    "code": "code",
    "pull-request": "git-pull-request",
    "clone": "copy",
    "move": "file-export",
    "ticket": "ticket",
    # -- the markdown toolbar: what a mark *does* to the text it wraps -----------------
    # Tabler's own editor set. The pictures are the ones every writing tool uses, which is
    # the whole argument for them: a toolbar of markdown verbs is the one strip where the
    # glyph is already learned before anybody hovers it.
    "bold": "bold",
    "italic": "italic",
    "heading-1": "h-1",
    "heading-2": "h-2",
    "heading-3": "h-3",
    "bullet-list": "list",  # Dots and lines; `list` below is the numbered one.
    "quote": "blockquote",
    "table": "table",
    # -- what a step *is*: the medallion vocabulary the canvas paints -------------------
    "tag": "tag",  # A milestone.
    "layers": "stack-2",  # A feature: it collects the work behind it.
    "spark": "sparkles",  # There is machine guidance here.
    "beaker": "flask",  # This step keeps tests.
    "shield": "shield-check",  # A check: everything behind it passing.
    "step": "square-rounded",
    # -- what is wrong with the plan ---------------------------------------------------
    "problem": "alert-triangle",  # The Problems panel, and the count on its button.
    # -- the tables and browsers ------------------------------------------------------
    "check": "check",  # Record the picked tests as passing.
    "skip": "player-skip-forward",  # Record them as skipped: looked at, not run.
    "eraser": "eraser",  # Take a recorded result back.
    "play": "player-play",  # Open a test run over what is in scope.
    "stop": "player-stop",  # Close the open run.
    "archive": "archive",  # Show the tests taken off the roster beside it.
    "eye": "eye",  # Light what wants a look: the passages that no longer simply anchor.
    "attach": "paperclip",  # Attach a file to the project's own pool.
    "clipboard": "clipboard",  # Copy a path.
    "sweep": "clear-all",  # Clean up what nothing uses.
    "camera": "camera",  # Keep the plan as it stands, to compare against later.
    "calendar-off": "calendar-off",  # Take a milestone's own start date away.
    "palette": "palette",  # A milestone's colour.
}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return bytes(response.read())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=TAG, help=f"the Tabler release to take (default {TAG})")
    parser.add_argument("--into", type=Path, default=GLYPH_DIR, help="where the SVGs land")
    args = parser.parse_args(argv)
    args.into.mkdir(parents=True, exist_ok=True)

    (args.into / "LICENSE").write_bytes(fetch(f"{SOURCE}/{args.tag}/LICENSE"))
    for glyph, icon in sorted(GLYPHS.items()):
        (args.into / f"{glyph}.svg").write_bytes(
            fetch(f"{SOURCE}/{args.tag}/icons/outline/{icon}.svg")
        )
        print(f"{glyph:18} ← {icon}")
    stale = sorted(path.stem for path in args.into.glob("*.svg") if path.stem not in GLYPHS)
    if stale:
        print(f"\nno longer named here, delete by hand: {', '.join(stale)}")
    print(f"\n{len(GLYPHS)} glyphs from Tabler Icons {args.tag}, MIT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
