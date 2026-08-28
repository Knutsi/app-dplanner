"""The Description tab: prose binding plus the gallery that finally shows its images."""

import pytest

from dplanner.domain.assets import attach
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Project, Step
from dplanner.modules.step_description.aspect import MODULE_ID


@pytest.fixture
def step(services):
    library = services.document
    project = Project(title="Discovery")
    AddNodeCommand(library.id, project).redo(library)
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(library)
    return step


@pytest.fixture
def section(services, step):
    spec = next(
        s for s in services.inspector_sections.sections() if s.id == "step_description.tab"
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
