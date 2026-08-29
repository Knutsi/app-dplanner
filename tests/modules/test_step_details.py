"""The Details tab: blocks other modules registered, stacked first in the panel.

The seam under test is the third registry instantiation — a module that wants its editor
on the first tab registers into ``services.step_details`` and never learns who renders it.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
from dplanner.modules.spec.aspect import SpecAttachment, write_step_entry
from dplanner.modules.step_properties.details import DetailsSection
from dplanner.modules.step_properties.module import PANEL_ID


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Read the spec")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


@pytest.fixture
def details(services, step):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),)
    )
    panel = services.window.dock.widget_for(PANEL_ID)
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    return panel._pages.widget(labels.index("Details"))


def block_holder(details, section_id):
    return next(b for b in details._blocks if b.section.id == section_id)


def test_blocks_come_in_registry_order_with_the_description_taking_the_stretch(details):
    assert [b.section.id for b in details._blocks] == [
        "estimation.details",
        "step_description.details",
        "spec.figures",
    ]
    assert [b.section.stretch for b in details._blocks] == [0, 1, 0]


def test_figures_follow_the_aspect_without_reselecting(services, step, details):
    """The block appears the moment an attachment is recorded and leaves when the last
    one goes — same rule as a toggleable aspect's tab."""
    figures = block_holder(details, "spec.figures")
    assert figures.isHidden()

    entry = write_step_entry([], [SpecAttachment(file="assets/one.png")])
    services.undo.push(SetModuleDataCommand(step.id, SPEC_ID, entry))
    assert not figures.isHidden()

    services.undo.push(SetModuleDataCommand(step.id, SPEC_ID, {}))
    assert figures.isHidden()


def test_an_estimate_written_through_a_block_is_undoable(services, step, details):
    editor = details.block("estimation.details")
    editor.days.setValue(3.0)
    editor.days.editingFinished.emit()
    assert services.document.step(step.id).module_data["estimation"]["days"] == 3.0
    services.undo.undo()
    assert "estimation" not in services.document.step(step.id).module_data


def test_show_target_reaches_hidden_blocks_and_dispose_detaches(services, step):
    """A hidden block is still shown every target, so it is current when it reappears;
    a disposed composite hears no further model signal."""
    shown: list[str | None] = []

    class Probe:
        @property
        def widget(self):
            from PySide6.QtWidgets import QWidget

            return QWidget()

        def show_target(self, target_id):
            shown.append(target_id)

        def dispose(self):
            shown.append("disposed")

    from dplanner.framework.inspector import InspectorSection

    section = InspectorSection(
        id="probe.block",
        label="Probe",
        factory=Probe,
        shown_for=lambda _sid: False,  # Never visible — and still driven.
    )
    composite = DetailsSection(services.document, [section])
    composite.show_target(step.id)
    assert shown == [step.id]
    assert block_holder(composite, "probe.block").isHidden()

    composite.dispose()
    assert shown[-1] == "disposed"
    entry = write_step_entry([], [SpecAttachment(file="assets/one.png")])
    services.undo.push(SetModuleDataCommand(step.id, SPEC_ID, entry))
    assert composite._blocks == []  # And the signal above reached nothing.
