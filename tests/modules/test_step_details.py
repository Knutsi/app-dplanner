"""The Details tab: blocks other modules registered, stacked first in the panel.

The seam under test is the third registry instantiation — a module that wants its editor
on the first tab registers into ``services.step_details`` and never learns who renders it.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
from dplanner.modules.spec.aspect import SpecAttachment, write_step_entry
from dplanner.modules.step_properties.details import DetailsSection


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Read the spec")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


@pytest.fixture
def details(step_editor, step):
    panel = step_editor(step.id)
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    return panel._pages.widget(labels.index("Details"))


def block_holder(details, section_id):
    return next(b for b in details._blocks if b.section.id == section_id)


def test_blocks_come_in_registry_order_with_the_description_taking_the_stretch(details):
    assert [b.section.id for b in details._blocks] == [
        "step_properties.name",
        "estimation.details",
        "step_description.details",
        "spec.figures",
    ]
    assert [b.section.stretch for b in details._blocks] == [0, 0, 1, 0]


def test_figures_follow_the_aspect_without_reselecting(services, step, details):
    """The block appears the moment an attachment is recorded and leaves when the last
    one goes — same rule as a toggleable aspect's tab."""
    figures = block_holder(details, "spec.figures")
    assert figures.isHidden()

    entry = write_step_entry([SpecAttachment(file="assets/one.png")])
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
    entry = write_step_entry([SpecAttachment(file="assets/one.png")])
    services.undo.push(SetModuleDataCommand(step.id, SPEC_ID, entry))
    assert composite._blocks == []  # And the signal above reached nothing.


# -- blocks stack from the top, whatever is turned off ---------------------------------------


def _stack(services, step, *, prose_shown):
    """A Details tab of four blocks shaped like the real registrants, laid out at 360x700."""
    from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QWidget

    from dplanner.framework.inspector import InspectorSection

    def probe(widget_type):
        class Probe:
            def __init__(self):
                self._widget = widget_type()

            @property
            def widget(self):
                return self._widget

            def show_target(self, target_id):
                pass

            def dispose(self):
                pass

        return Probe

    sections = [
        InspectorSection(id="probe.name", label="Name", factory=probe(QLineEdit), order=0),
        InspectorSection(id="probe.estimate", label="Estimate", factory=probe(QLineEdit), order=10),
        InspectorSection(
            id="probe.prose",
            label="Description",
            factory=probe(QPlainTextEdit),
            order=20,
            stretch=1,  # The one block the leftover height is for.
            shown_for=lambda _sid: prose_shown,
        ),
        InspectorSection(
            id="probe.figures",
            label="Figures",
            factory=probe(QWidget),
            order=30,
            shown_for=lambda _sid: prose_shown,
        ),
    ]
    composite = DetailsSection(services.document, sections)
    composite.resize(360, 700)
    composite.show_target(step.id)
    composite.show()
    return composite


def test_blocks_stay_at_the_top_when_the_stretch_block_is_turned_off(app, services, step):
    """The bug this fix exists for: with Description off, nothing below it may grow.

    Before the trailing stretch and the cap, Qt found no stretch to honour, spread the
    surplus among the blocks that could grow, and the name field sank to the bottom of a
    block eight times taller than it needed.
    """
    from dplanner.theme.tokens import SECTION_GAP

    composite = _stack(services, step, prose_shown=False)
    app.processEvents()

    name = block_holder(composite, "probe.name")
    estimate = block_holder(composite, "probe.estimate")
    assert name.height() == name.sizeHint().height()
    assert estimate.height() == estimate.sizeHint().height()
    # And the next block sits directly under it rather than a third of the tab away.
    assert estimate.geometry().top() == name.geometry().bottom() + 1 + SECTION_GAP
    composite.deleteLater()


def test_the_description_still_takes_the_leftover_height_when_it_is_shown(app, services, step):
    """The converse, so the fix can never become "cap everything": a trailing stretch of 1
    would halve the prose editor, which is the regression this pins."""
    composite = _stack(services, step, prose_shown=True)
    app.processEvents()

    name = block_holder(composite, "probe.name")
    prose = block_holder(composite, "probe.prose")
    assert name.height() == name.sizeHint().height()
    assert prose.height() > 400  # The whole leftover, not a share of it.
    composite.deleteLater()
