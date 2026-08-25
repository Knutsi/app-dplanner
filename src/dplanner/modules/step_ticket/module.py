"""The ticket aspect, in the running application.

No editor yet — see ``step_estimation/module.py`` for why an aspect module exists before it
has a surface: declaring ``data_format`` is how the builder learns to migrate this aspect's
data when a window opens an older workspace.
"""

from dataclasses import dataclass

from dplanner.modules.step_ticket.aspect import DATA_FORMAT, MODULE_ID


@dataclass(frozen=True)
class StepTicketDeps:
    """Nothing yet. The card this module will contribute will want the product and the
    detail-card registry; adding them here is what that change looks like."""


class StepTicketModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepTicketDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        """No surface yet — see the module docstring."""
