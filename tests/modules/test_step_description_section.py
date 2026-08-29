"""The Description block on the Details tab: prose binding plus the gallery."""

import pytest

from dplanner.domain.assets import attach
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.modules.step_description.aspect import MODULE_ID


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


@pytest.fixture
def section(services, step):
    spec = next(
        s for s in services.step_details.sections() if s.id == "step_description.details"
    )
    section = spec.factory()
    yield section
    section.dispose()


def test_the_tab_shows_attached_images_with_a_working_attach(services, step, section):
    attach(services.repo.files(step.id, MODULE_ID), b"png bytes", "diagram.png")
    section.show_target(step.id)
    assert section.gallery._names  # the attached file is listed
    assert section.gallery.attach_button.isVisibleTo(section.gallery)
    # Attaching through the gallery writes the step's own description area.
    section.gallery._attach_bytes(b"more bytes", "second.png")
    assert len(section.gallery._names) == 2
    assert section.gallery._grid.count() == 2


def test_typing_still_writes_the_description(services, step, section):
    section.show_target(step.id)
    section.edit.setPlainText("The release step.")
    assert services.document.step(step.id).module_text[MODULE_ID] == "The release step."


def test_showing_nothing_disables_and_clears(services, step, section):
    section.show_target(step.id)
    section.show_target(None)
    assert not section.isEnabled()
    assert section.gallery._names == []


# -- the "Separate agent instruction" checkbox -------------------------------------------------


def agent_on(services, step, separate=False):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_agent_instruction.aspect import (
        MODULE_ID as AGENT_ID,
    )
    from dplanner.modules.step_agent_instruction.aspect import (
        write_state,
    )

    services.undo.push(
        SetModuleDataCommand(step.id, AGENT_ID, write_state(True, separate=separate))
    )


def test_the_checkbox_appears_only_on_agent_steps_and_follows_the_model(
    services, step, section
):
    section.show_target(step.id)
    assert not section.separate_check.isVisibleTo(section)
    agent_on(services, step)  # No reselect: the checkbox follows the model.
    assert section.separate_check.isVisibleTo(section)
    assert not section.separate_check.isChecked()


def test_checking_stores_the_separate_flag_undoably(services, step, section):
    from dplanner.modules.step_agent_instruction.aspect import separate_instruction

    agent_on(services, step)
    section.show_target(step.id)
    section.separate_check.setChecked(True)
    assert separate_instruction(services.document.step(step.id))
    services.undo.undo()
    assert not separate_instruction(services.document.step(step.id))


def test_unchecking_confirms_and_drops_the_text_as_one_undo_step(
    services, step, section, monkeypatch
):
    import dplanner.modules.step_description.section as description_section
    from dplanner.modules.step_agent_instruction.aspect import (
        MODULE_ID as AGENT_ID,
    )
    from dplanner.modules.step_agent_instruction.aspect import (
        separate_instruction,
    )

    agent_on(services, step)
    services.document.set_text(step.id, AGENT_ID, "Ship it.")  # Implies separate.
    monkeypatch.setattr(description_section, "confirm", lambda *_args: True)
    section.show_target(step.id)
    assert section.separate_check.isChecked()

    section.separate_check.setChecked(False)
    assert services.document.step(step.id).module_text.get(AGENT_ID, "") == ""
    assert not separate_instruction(services.document.step(step.id))
    services.undo.undo()  # One step restores the text and the flag together.
    assert services.document.step(step.id).module_text[AGENT_ID] == "Ship it."
    assert separate_instruction(services.document.step(step.id))


def test_a_declined_confirm_keeps_the_separate_instruction(
    services, step, section, monkeypatch
):
    import dplanner.modules.step_description.section as description_section
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID

    agent_on(services, step)
    services.document.set_text(step.id, AGENT_ID, "Ship it.")
    monkeypatch.setattr(description_section, "confirm", lambda *_args: False)
    section.show_target(step.id)
    section.separate_check.setChecked(False)
    assert section.separate_check.isChecked()  # Reverted, nothing written.
    assert services.document.step(step.id).module_text[AGENT_ID] == "Ship it."
