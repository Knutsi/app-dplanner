"""What a canvas accepts by drop, named by the composition root.

A drag arrives as a mime type and a payload; the root says which types mean anything here
and hands a ``place`` that turns one into steps — through ``StepVerbs.create``, so a
dropped thing is born the way New's step is, position and marker in one undo step. It
returns the ids it placed (the canvas selects them) and refuses with a ``CliError`` whose
message is the status bar's — the same words the CLI would print.

Qt-free, so the shape can be read and tested without a graphics stack — the same reason
``ScopeKind`` lives in the domain.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.domain.model import NodeId, StepId


@dataclass(frozen=True)
class CanvasDrop:
    mime_type: str
    place: Callable[[NodeId, bytes, tuple[float, float] | None], list[StepId]]
