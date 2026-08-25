"""The estimation aspect, in the running application.

There is no editor yet, and that is deliberate rather than unfinished: the ``data_format``
declaration alone is what makes the workspace forward-compatible, so the CLI can write
estimates today and a card can arrive later without a migration. What ``register()`` would
do is contribute that card.

The module still has to exist and be constructed, because declaring ``data_format`` is how
:class:`~dplanner.framework.builder.AppBuilder` learns to migrate this aspect's data when a
window opens an older workspace.
"""

from dataclasses import dataclass

from dplanner.modules.step_estimation.aspect import DATA_FORMAT, MODULE_ID


@dataclass(frozen=True)
class StepEstimationDeps:
    """Nothing yet. The card this module will contribute will want the product and the
    detail-card registry; adding them here is what that change looks like."""


class StepEstimationModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepEstimationDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        """No surface yet — see the module docstring."""
