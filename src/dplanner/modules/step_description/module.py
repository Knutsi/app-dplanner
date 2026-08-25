"""The description aspect, in the running application.

No editor yet — see ``step_estimation/module.py`` for why an aspect module exists before it
has a surface. When one arrives it binds a ``QPlainTextEdit`` to
``ModuleTextField(product, step_id, MODULE_ID)`` and gets positional editing, undo
coalescing and echo suppression without writing any of them.
"""

from dataclasses import dataclass

from dplanner.modules.step_description.aspect import DATA_FORMAT, MODULE_ID


@dataclass(frozen=True)
class StepDescriptionDeps:
    """Nothing yet. The editor this module will contribute will want the product and the
    undo service; adding them here is what that change looks like."""


class StepDescriptionModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepDescriptionDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        """No surface yet — see the module docstring."""
