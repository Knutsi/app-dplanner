"""The Playbooks tab of *Project ▸ Settings…*: what a step that never chose runs.

Two dropdowns over the project's entry — the default, which starts as no playbook (Run Agent),
and the landing default, which starts as *Land* — the same entry ``dplanner playbook
set --project-default`` and ``--landing-default`` write.

Not a ``ModuleDataSection``: that base is aimed at a step, and teaching it a second kind of
node costs more than this tab's few lines of binding. Its echo rule does not arise either —
a dropdown commits only on a person's pick, and reloading it after its own write shows the
same row.
"""

from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import block, captioned
from dplanner.modules.step_playbook.aspect import (
    MODULE_ID,
    Defaults,
    read_project,
    write_project,
)
from dplanner.modules.step_playbook.presets import LANDING_DEFAULT, preset
from dplanner.modules.step_playbook.section import add_presets
from dplanner.theme.tokens import SECTION_GAP

DEFAULT_HINT = (
    "What a step that never chose a playbook runs when one is started on it. With none, such "
    "a step has Run Agent and nothing runs unattended."
)
LANDING_HINT = (
    "What a branch landing that never chose runs: the whole branch reviewed once, by "
    "default, before a person merges it."
)


class ProjectPlaybookSection(QWidget):
    def __init__(self, library: Library, undo: UndoService[Library]) -> None:
        super().__init__()
        self._library = library
        self._undo = undo
        self._project_id: str | None = None
        self.default = QComboBox(self)
        self.default.addItem("None — Run Agent", None)
        add_presets(self.default)
        self.landing = QComboBox(self)
        self.landing.addItem(f"{LANDING_DEFAULT.name} (default)", LANDING_DEFAULT.id)
        add_presets(self.landing, but=LANDING_DEFAULT.id)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # The dialog carries the margins.
        layout.setSpacing(SECTION_GAP)
        block(layout, captioned("Default playbook", self, DEFAULT_HINT), self.default)
        block(layout, captioned("Landing playbook", self, LANDING_HINT), self.landing)
        layout.addStretch(1)
        self.default.activated.connect(lambda _index: self._commit())
        self.landing.activated.connect(lambda _index: self._commit())
        self._unsubscribe = library.module_data_changed.connect(self._on_module_data)

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._project_id = target_id
        self.setEnabled(self._project() is not None)
        self._reload()

    def dispose(self) -> None:
        self._unsubscribe()

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project | None:
        project_id = self._project_id
        if project_id is None or not self._library.has(project_id):
            return None
        return self._library.project(project_id)

    def _reload(self) -> None:
        project = self._project()
        defaults = read_project(project) if project is not None else Defaults()
        self.default.setCurrentIndex(
            self.default.findData(defaults.default.id) if defaults.default else 0
        )
        self.landing.setCurrentIndex(self.landing.findData(defaults.landing.id))

    def _commit(self) -> None:
        project = self._project()
        if project is None:
            return
        entry = write_project(
            Defaults(
                default=preset(self.default.currentData() or ""),
                landing=preset(self.landing.currentData()) or LANDING_DEFAULT,
            )
        )
        if entry == project.module_data.get(MODULE_ID, {}):
            return
        self._undo.push(SetModuleDataCommand(project.id, MODULE_ID, entry, label="Set Playbooks"))

    def _on_module_data(self, node_id: NodeId, module_id: str, _origin: object) -> None:
        if node_id == self._project_id and module_id == MODULE_ID:
            self._reload()
