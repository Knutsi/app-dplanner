"""What *kind* of step the New menu can create.

A **kind** is what a node *is*; a **facet** is what it carries. A milestone, a feature and a
check are kinds — a node exists in order to be one, and it wears its own body colour on the
canvas. An estimate, a description, a ticket are facets: things a step of any kind may hold.
That is why this list is not derived from the Step ▸ Type submenu, which offers both —
*New ▸ Description* would be nonsense.

The list itself is named by the composition root, the one place that may know every aspect,
and handed to this module on its ``Deps`` — the same seam ``ScopeKind`` uses one layer up.
Nothing here learns what a feature is: a kind is a label and a function returning the
commands that make a fresh step one.

Qt-free, so the shape can be read and tested without a graphics stack.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.domain.commands import Command
from dplanner.domain.model import NodeId, Project, Step, StepId


@dataclass(frozen=True)
class StepKind:
    """One entry in the New menu: what to call it, and what marks a step as it.

    ``commands`` is handed the project the step is being born into and the step itself —
    not yet added — and answers with the commands that make it this kind, which ride in
    the same undo step as the node. Usually one: the marker on the step. A milestone
    generates its label from the labels already in the project; a feature also writes a
    catalogue record titled like the step, beside the marker, because a feature step is
    the instance of a record and one gesture is one undo. An empty list is a plain step
    under another name.

    ``icon`` is a **name** in the canvas's medallion vocabulary rather than a painter, so
    this file stays Qt-free and a kind still says only what it is: the New menu and the
    toolbar's dropdown then wear the very glyph the node will wear.
    """

    id: str  # The module id whose data marks the step.
    name: str  # What a person calls it: "Feature", "Milestone", "Agent Step".
    commands: Callable[[Project, Step], list[Command]]
    icon: str = ""  # "tag" | "layers" | "spark" | "shield" | … ; "" draws none.

    @property
    def action_id(self) -> str:
        """``steps.new_agent_step`` — derived, so a kind is declared in exactly one place."""
        return f"steps.new_{self.name.lower().replace(' ', '_')}"

    @property
    def label(self) -> str:
        """``&Feature…`` — the first letters of the kinds do not collide, so the mnemonic
        needs no table."""
        return f"&{self.name}…"


@dataclass(frozen=True)
class CanvasDrop:
    """Something a canvas accepts by drop, and what placing it does.

    A drag arrives as a mime type and a payload; the composition root says which types
    mean anything here and hands a ``place`` that turns one into steps — through
    ``StepVerbs.create``, so a dropped thing is born the way a New verb's step is. It
    returns the ids it placed (the canvas selects them) and refuses with a ``CliError``
    whose message is the status bar's — the same one the CLI would print.
    """

    mime_type: str
    place: Callable[[NodeId, bytes, tuple[float, float] | None], list[StepId]]
