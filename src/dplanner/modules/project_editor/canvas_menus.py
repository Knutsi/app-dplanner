"""What a right-click on the canvas renders, by what it landed on.

The click first makes the thing under it current — a card or an arrow becomes the pick unless
it is already in it, a stack's frame picks its members, empty canvas clears the pick — and the
menu is then a function of the selection alone: steps are a **card**, one stack's members
exactly a **stack**, arrows an **arrow**, both a **mixed** pick, nothing the **background**.
So the menu cannot offer verbs about something other than what they act on.

Each target is a row of bands, rendered in order by ``fill_bands``, never an entry
written here: a verb registered into a band appears in every menu that renders it, which is
how Auto-progress (``modules/auto_progress/``) reaches the arrow and the mixed pick's
*Links* by registering into Graph ▸ ``links``. It is a table rather than an entry of its own
in ``MENU_STRUCTURE`` because an entry there is a place verbs are *registered into*, and
nothing registers here.
``ARCHITECTURE.md``'s *A right-click is composed by what is under it* has the reasoning.
"""

from collections.abc import Sequence
from typing import Final

from dplanner.framework.action_menu import Band
from dplanner.modules.project_editor.selection import CanvasSelection
from dplanner.modules.project_editor.stacks import Stack

CARD = "card"
STACK = "stack"
ARROW = "arrow"
MIXED = "mixed"
BACKGROUND = "background"

# The Step menu's bands about a stack: making one, and what acts on the one a step is in.
STACK_BANDS: Final = ("stack", "stacked")
# The Step menu's bands about the step itself. What a table adds — its type and tests, set
# in Step Details; compiling, the Docs tab's; the project's views, rows in the index beside
# the canvas — a card leaves out.
STEP_ITSELF: Final = ("edit", "link", *STACK_BANDS, "track", "agent", "open")

BANDS: Final[dict[str, tuple[Band, ...]]] = {
    CARD: (Band("Step", STEP_ITSELF),),
    # What the frame is for leads — the stack's own verbs, flat — and what a card offers
    # comes one level down, for every member at once.
    STACK: (
        Band("Step", "stacked", submenu="Stack"),
        Band("Step", tuple(g for g in STEP_ITSELF if g not in STACK_BANDS), child="Step"),
    ),
    # What an arrow is: removed, or one of its ends moved.
    ARROW: (Band("Graph", "links"),),
    # Nothing is about both, so it leads with narrowing the pick and what acts on any of it,
    # and offers each kind's own verbs one level down.
    MIXED: (
        Band("Graph", "narrow"),
        Band("Edit", "clipboard"),
        Band("Step", STEP_ITSELF, child="Step"),
        Band("Graph", "links", child="Links"),
    ),
    # Making something where the click was, picking what is there, and the looks over the
    # whole plan the index has no row for — the rest of Go's views are rows there.
    BACKGROUND: (
        Band("Graph", "new"),
        Band("Graph", "select"),
        Band("Edit", "selection"),
        Band("Go", "survey"),
    ),
}


def target_of(selection: CanvasSelection, stacks: Sequence[Stack] = ()) -> str:
    """Which row of :data:`BANDS` a pick renders — a stack when it is exactly one stack's
    members, which is what a click on its frame picks."""
    if selection.steps and selection.edges:
        return MIXED
    if selection.edges:
        return ARROW
    if any(set(selection.steps) == set(stack.members) for stack in stacks):
        return STACK
    if selection.steps:
        return CARD
    return BACKGROUND
