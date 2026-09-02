"""The ticket aspect: the issue a step corresponds to in whatever tracks the work.

Three strings and no integration. DPlanner does not talk to a tracker and should not start
by accident — this records where the work is tracked so a person or an agent can follow the
link, and nothing more.
"""

from dataclasses import dataclass
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "step_ticket"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

FIELDS = ("system", "key", "url")


@dataclass(frozen=True)
class Ticket:
    system: str = ""
    key: str = ""
    url: str = ""

    def is_empty(self) -> bool:
        return not (self.system or self.key or self.url)


def read(step: Step) -> Ticket | None:
    """The ticket itself, or ``None`` — which an enabled-but-unfilled aspect also answers."""
    entry = step.module_data.get(MODULE_ID)
    if not entry:
        return None
    ticket = Ticket(**{field: str(entry.get(field, "")) for field in FIELDS})
    return None if ticket.is_empty() else ticket


def enabled(step: Step) -> bool:
    """Whether the step carries the aspect at all — presence of the entry, filled or not."""
    return bool(step.module_data.get(MODULE_ID))


def enabled_entry() -> dict[str, Any]:
    """The marker for "tracked, ticket not yet filled in" — what the Type toggle writes."""
    return stamped({"on": True}, DATA_FORMAT.version)


def write(ticket: Ticket | None) -> dict[str, Any]:
    """The entry to store. An empty ticket gives ``{}``, which removes the file."""
    if ticket is None or ticket.is_empty():
        return {}
    entry = {field: getattr(ticket, field) for field in FIELDS if getattr(ticket, field)}
    return stamped(entry, DATA_FORMAT.version)


def summary(step: Step) -> str:
    ticket = read(step)
    if ticket is None:
        return ""
    return ticket.key or ticket.system or ticket.url


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Ticket",
    summary="Where a step is tracked: which system, which key, and the link to it.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
