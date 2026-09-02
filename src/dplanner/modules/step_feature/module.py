"""The feature aspect, in the running application: a Type toggle, and nothing else.

The tab that shows what a feature gathers belongs to the module that owns tests — it is a
list of tests, and a tab that renders one is testing's business, not this package's. That is
the same wiring the check aspect uses: ``testing`` is handed predicates that read this
aspect, and nothing here has to know that module exists.
"""

from dataclasses import dataclass

from dplanner.domain.model import Library
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.undo import UndoService
from dplanner.modules.step_feature.aspect import DATA_FORMAT, MODULE_ID, SPEC, read, write
from dplanner.theme.icons import layers_icon


@dataclass(frozen=True)
class StepFeatureDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry


class StepFeatureModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepFeatureDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        self._deps.actions.register(
            aspect_toggle(
                id="feature.toggle",
                label=SPEC.label,
                order=20,
                module_id=MODULE_ID,
                library=self._deps.library,
                undo=self._deps.undo,
                enabled=read,
                fresh=lambda _step, _project: write(True),
                icon=layers_icon,
                tip="Collect the work and tests behind this step, up to the previous feature",
            )
        )
