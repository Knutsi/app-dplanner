"""Reading the generated skill's command index back, for the tests that check it.

The index is one line per noun — ``- `dplanner note` — add · index · list`` — so a test
asks "which verbs does the skill offer under this noun, and which wear the gate's dagger?"
rather than matching a line by hand in two files.
"""

from dplanner.cli.main import PROG

BULLET = f"- `{PROG} "
JOIN = "` — "


def noun_verbs(skill: str) -> dict[str, list[str]]:
    """The command index as noun → its verbs, the dagger kept on the ones that wear it.

    Only lines of the index shape count: the prose above it has bullets naming whole
    commands (``- `dplanner github refresh` updates…``), which is why the split is on the
    backtick before the dash and not on the dash alone.
    """
    found: dict[str, list[str]] = {}
    for line in skill.splitlines():
        if not line.startswith(BULLET) or JOIN not in line:
            continue
        noun, verbs = line.removeprefix(BULLET).split(JOIN, 1)
        if " " in noun:  # `dplanner github refresh` — a command, not a noun.
            continue
        found[noun] = verbs.split(" · ")
    return found
