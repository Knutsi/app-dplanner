"""What *kind* of step the New menu can create.

A **kind** is what a node *is*; a **facet** is what it carries. A milestone, a feature and a
check are kinds — a node exists in order to be one, and it wears its own body colour on the
canvas. An estimate, a description, a ticket are facets: things a step of any kind may hold.
That is why this list is not derived from the Step ▸ Type submenu, which offers both —
*New ▸ Description* would be nonsense.

The list itself is named by the composition root, the one place that may know every aspect,
and handed to this module on its ``Deps`` — the same seam ``ScopeKind`` uses one layer up.
Nothing here learns what a feature is: a kind is a label and a function returning the module
data a fresh step of that kind carries.

Qt-free, so the shape can be read and tested without a graphics stack.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dplanner.domain.model import Project


@dataclass(frozen=True)
class StepKind:
    """One entry in the New menu: what to call it, and what marks a step as it.

    ``entry`` is handed the project the step is being born into, because a milestone
    generates its label from the labels already there. It may return ``{}`` — a kind that
    marks nothing is simply a plain step under another name, and the creation skips the
    write rather than storing an empty entry.
    """

    id: str  # The module id whose data marks the step — where ``entry`` is written.
    name: str  # What a person calls it: "Feature", "Milestone", "Agent Step".
    entry: Callable[[Project], dict[str, Any]]

    @property
    def action_id(self) -> str:
        """``steps.new_agent_step`` — derived, so a kind is declared in exactly one place."""
        return f"steps.new_{self.name.lower().replace(' ', '_')}"

    @property
    def label(self) -> str:
        """``&Feature…`` — the first letters of the kinds do not collide, so the mnemonic
        needs no table."""
        return f"&{self.name}…"
