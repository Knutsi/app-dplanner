"""The feature module in the running application: the Type toggle, the Feature tab, the
Features panel and the Project ▸ Features verbs.

What a feature *gathers* is still rendered by the module that owns tests — a list of tests
is testing's business — and the canvas drop that places a feature is the project editor's
gesture, handed a ``CanvasDrop`` the composition root writes over this module's Qt-free
half, so neither module learns the other's name.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QWidget

from dplanner.domain.commands import Command, CompositeCommand, SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.panels import PanelArea, PanelRegistry, PanelSpec
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.feature.aspect import MODULE_ID, SPEC, clear, read
from dplanner.modules.feature.catalogue import (
    FeatureRecord,
    instance_of,
    next_feature_id,
    read_catalogue,
    registration,
    without_record,
    write_catalogue,
)
from dplanner.modules.feature.panel import (
    FEATURE_ENTITY,
    FeatureDialog,
    FeaturesPanel,
    parse_feature_ref,
)
from dplanner.modules.feature.section import FeatureSection

PANEL_ID = f"{MODULE_ID}.panel"


def _no_documents(_project_id: NodeId) -> list[str]:
    return []


@dataclass(frozen=True)
class FeatureDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    panels: PanelRegistry
    sections: InspectorSectionRegistry
    files: FilesFor
    parent: QWidget | None = None
    # The spec documents a record's source can name — the editor's dropdown. Spec's
    # business, handed in so this module never learns how documents are stored.
    documents_of: Callable[[NodeId], list[str]] = _no_documents


class FeatureModule:
    id = MODULE_ID

    def __init__(self, deps: FeatureDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.actions.register(
            ActionSpec(
                id="feature.toggle",
                label=SPEC.label,
                menu="Step",
                group="classify",
                submenu="Type",
                order=20,
                tip="Make this step the instance of a feature record; the work upstream "
                "of it flows into the feature",
                state=self._toggle_state,
                run=self._toggle,
            )
        )
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=45,
                factory=lambda: FeatureSection(
                    deps.library, deps.undo, deps.files, deps.documents_of, self.register_step
                ),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and read(deps.library.step(step_id)) is not None
                ),
            )
        )
        # Order 20: under the Index, which is 10 — the drag starts beside the tree and
        # ends on the canvas.
        deps.panels.register(
            PanelSpec(
                id=PANEL_ID,
                title="Features",
                factory=lambda: FeaturesPanel(deps.library, deps.actions),
                area=PanelArea.LEFT,
                order=20,
            )
        )
        for spec in self._verb_specs():
            deps.actions.register(spec)

    # -- the verbs ---------------------------------------------------------------------------

    def _verb_specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="feature.add",
                label="&Add Feature…",
                menu="Project",
                group="features",
                order=10,
                tip="Add a feature to this project's catalogue; drag it onto the canvas "
                "to place it",
                state=self._on_a_project,
                run=self._add,
            ),
            ActionSpec(
                id="feature.edit",
                label="&Edit Feature…",
                menu="Project",
                group="features",
                order=20,
                tip="The picked feature's title, description, source and images",
                state=self._on_a_feature,
                run=self._edit,
            ),
            ActionSpec(
                id="feature.remove",
                label="Remove &Feature",
                menu="Project",
                group="features",
                order=30,
                tip="Take the picked feature out of the catalogue; its step becomes plain",
                state=self._on_a_feature,
                run=self._remove,
            ),
            ActionSpec(
                id="feature.reveal",
                label="Reveal Feature's &Step",
                menu="Project",
                group="features",
                order=40,
                tip="Select the step that realises the picked feature",
                state=self._reveal_state,
                run=self._reveal,
            ),
        ]

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return DISABLED
        return ENABLED

    def _picked(self, context: Context) -> tuple[NodeId, FeatureRecord] | None:
        ref = context.selected_entity(FEATURE_ENTITY)
        parsed = parse_feature_ref(ref) if ref is not None else None
        if parsed is None or not self._deps.library.has(parsed[0]):
            return None
        project = self._deps.library.project(parsed[0])
        record = next((r for r in read_catalogue(project) if r.id == parsed[1]), None)
        return None if record is None else (project.id, record)

    def _on_a_feature(self, context: Context) -> ActionState:
        if self._picked(context) is None:
            return ActionState(enabled=False, label="— pick a feature in the Features panel")
        return ENABLED

    def _reveal_state(self, context: Context) -> ActionState:
        picked = self._picked(context)
        if picked is None:
            return ActionState(enabled=False, label="Reveal Feature's Step")
        project_id, record = picked
        if instance_of(self._deps.library.project(project_id), record.id) is None:
            return ActionState(enabled=False, label="Reveal Step — not placed")
        return ENABLED

    def _add(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return
        title, accepted = QInputDialog.getText(self._deps.parent, "Add Feature", "Feature:")
        if not accepted or not title.strip():
            return
        project = self._deps.library.project(project_id)
        records = read_catalogue(project)
        record = FeatureRecord(id=next_feature_id(records), title=title.strip())
        self._deps.undo.push(
            SetModuleDataCommand(
                project.id, MODULE_ID, write_catalogue([*records, record]), label="Add Feature"
            )
        )

    def _edit(self, context: Context) -> None:
        picked = self._picked(context)
        if picked is None:
            return
        project_id, record = picked
        dialog = FeatureDialog(
            self._deps.library,
            self._deps.undo,
            self._deps.files,
            self._deps.documents_of,
            project_id,
            record.id,
            parent=self._deps.parent,
        )
        dialog.exec()
        dialog.dispose()

    def _remove(self, context: Context) -> None:
        picked = self._picked(context)
        if picked is None:
            return
        project_id, record = picked
        project = self._deps.library.project(project_id)
        instance = instance_of(project, record.id)
        detail = f" {instance.title!r} becomes a plain step." if instance is not None else ""
        if not confirm(
            self._deps.parent,
            "Remove Feature",
            f"Remove {record.title!r} from the catalogue?{detail}",
        ):
            return
        commands: list[Command] = [
            SetModuleDataCommand(
                project.id,
                MODULE_ID,
                write_catalogue(without_record(read_catalogue(project), record.id)),
            )
        ]
        if instance is not None:
            commands.append(SetModuleDataCommand(instance.id, MODULE_ID, clear()))
        self._deps.undo.push(CompositeCommand("Remove Feature", commands))

    def _reveal(self, context: Context) -> None:
        picked = self._picked(context)
        if picked is None:
            return
        project_id, record = picked
        instance = instance_of(self._deps.library.project(project_id), record.id)
        if instance is None:
            return
        # The step's own verb, against a context naming exactly that step — the same
        # way a table row reveals itself.
        step_context = Context(
            {SCOPE_SELECTION: (ContextNode(selection_uri("step", instance.id)),)}
        )
        self._deps.actions.run("steps.reveal", step_context)

    # -- the toggle ----------------------------------------------------------------------------

    def _toggle_state(self, context: Context) -> ActionState:
        step = self._focused(context)
        if step is None:
            return DISABLED
        return ActionState(checked=read(step) is not None)

    def _toggle(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        if read(step):
            # Off clears the marker only: the record stays in the catalogue, unplaced, so
            # undo restores exactly and nothing a person wrote is lost.
            self._deps.undo.push(
                SetModuleDataCommand(step.id, MODULE_ID, clear(), label="Clear Feature")
            )
            return
        # A plain step becomes a new, registered feature; an unregistered one is registered.
        self.register_step(step.id)

    def register_step(self, step_id: StepId) -> None:
        """Mint a record titled like the step and mark the step as its instance — one
        undo step. What New ▸ Feature, the toggle and the tab's Register button do."""
        if not self._deps.library.has(step_id):
            return
        step = self._deps.library.step(step_id)
        commands = registration(self._deps.library.project_of(step_id), step)
        if commands:
            self._deps.undo.push(CompositeCommand("Mark as Feature", commands))

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return self._deps.library.step(step_id)
