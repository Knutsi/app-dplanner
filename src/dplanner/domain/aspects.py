"""What an aspect is.

An **aspect** is a fact about a step that the graph knows nothing about: an estimate, a
ticket, a description. It is a module's entry in ``step.module_data`` (structured JSON) or
``step.module_text`` (prose), namespaced by module id and versioned by the module that
writes it — so a feature can be added, changed or retired without the model learning
anything about it.

This file holds only the description of one: id, what to call it, one line about what it
means, and the format its data is stored in. There is no registry class, because there is
nobody to arbitrate — each aspect package exports a module-level ``SPEC`` and the two
composition roots name the packages they include.

What reads a ``SPEC``: ``dplanner aspect list`` (so an agent can discover what a step can
carry), the generated skill, the module's own ``data_format`` declaration, and every
surface that renders a step row (through ``phrase``).
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.core.module_data import ModuleDataFormat
from dplanner.domain.model import Step


@dataclass(frozen=True)
class AspectSpec:
    id: str  # == the module id == the key in module_data and module_text.
    label: str  # What a person calls it.
    summary: str  # One line about the aspect. It reaches the generated skill verbatim.
    data_format: ModuleDataFormat
    # One short phrase about *this step's* value, or "" when there is nothing to say —
    # what a step row renders. On the SPEC so an aspect declared once appears on every
    # surface; a second parallel list of these is exactly what this field replaced.
    phrase: Callable[[Step], str]

    def __post_init__(self) -> None:
        if self.data_format.module_id != self.id:
            raise ValueError(
                f"aspect {self.id!r} declares data for {self.data_format.module_id!r} — "
                "an aspect's id, its module id and its data namespace are one name"
            )
