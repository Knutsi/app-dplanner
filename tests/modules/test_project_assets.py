"""The Assets tab: the catalog rendered, rename, the sweep, and where a use row goes.

Built over the real session so the tab, the sources and the store are production wiring;
the catalog derivation itself is tested in ``tests/domain/test_assets.py`` and each
source's "used" semantics in ``test_asset_sources.py``.
"""

import pytest

from dplanner.domain.assets import attach
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.modules.project_assets.activity import ASSETS_KIND, DETAIL_ROLE
from dplanner.modules.project_assets.cli import MODULE_ID, read_titles
from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID

PNG = b"\x89PNG-pretend"


@pytest.fixture
def project(make_project):
    return make_project("Widget")


@pytest.fixture
def step(services, project):
    step = Step(title="Fix list flicker")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def described_image(services, step, *, referenced):
    name = attach(services.repo.files(step.id, DESCRIPTION_ID), PNG, "shot.png")
    if referenced:
        step.module_text[DESCRIPTION_ID] = f"![shot]({name})"
    return name


def open_tab(services, project):
    return services.tabs.open(ASSETS_KIND, project.id)


def test_the_tab_shows_one_row_per_content_with_its_uses(services, project, step):
    name = described_image(services, step, referenced=True)
    attach(services.repo.files(step.id, "testing"), PNG, "shot.png")  # Same bytes, again.

    activity = open_tab(services, project)

    assert activity.lead.text() == "1 asset"
    assert activity.list.count() == 1
    row = activity.list.item(0)
    assert row.text() == name.removeprefix("assets/")
    assert "description" in row.data(DETAIL_ROLE)


def test_the_unused_filter_narrows_the_list(services, project, step):
    described_image(services, step, referenced=True)
    attach(services.repo.files(step.id, DESCRIPTION_ID), b"\x89PNG-other", "stray.png")

    activity = open_tab(services, project)
    assert activity.list.count() == 2
    assert "1 unused" in activity.lead.text()

    activity.unused_only.setChecked(True)
    assert activity.list.count() == 1


def test_renaming_pushes_an_undoable_command(services, project, step):
    described_image(services, step, referenced=True)
    activity = open_tab(services, project)

    activity.name_edit.setText("Login mock")
    activity._rename()

    assert list(read_titles(project).values()) == ["Login mock"]
    services.undo.undo()
    assert read_titles(project) == {}


def test_delete_is_disabled_with_the_using_surface_as_the_reason(services, project, step):
    described_image(services, step, referenced=True)
    activity = open_tab(services, project)

    assert not activity.delete_button.isEnabled()
    assert "Fix list flicker" in activity.delete_button.toolTip()
    assert "description" in activity.delete_button.toolTip()


def test_the_sweep_removes_only_the_unused_copies(services, project, step, monkeypatch):
    kept = described_image(services, step, referenced=True)
    stray = attach(services.repo.files(step.id, DESCRIPTION_ID), b"\x89PNG-other", "stray.png")
    monkeypatch.setattr("dplanner.modules.project_assets.activity.confirm", lambda *_a: True)

    activity = open_tab(services, project)
    activity._sweep()

    area = services.repo.files(step.id, DESCRIPTION_ID)
    assert area.read_bytes(kept) is not None
    assert area.read_bytes(stray) is None
    assert activity.list.count() == 1


def test_double_clicking_a_use_runs_steps_details(services, project, step, monkeypatch):
    """The one gesture across every table: a use row opens `steps.details` on its step."""
    described_image(services, step, referenced=True)
    opened: list[str] = []
    monkeypatch.setattr(
        services.actions,
        "run",
        lambda action_id, context: opened.append(f"{action_id}:{context.focus_entity('step')}"),
    )

    activity = open_tab(services, project)
    activity.uses.itemActivated.emit(activity.uses.item(0))

    assert opened == [f"steps.details:{step.id}"]


def test_opening_the_tab_does_not_dirty_the_project(services, project, step):
    """A browse must not write — the ambient-layout rule's cousin."""
    described_image(services, step, referenced=True)
    marks: list[tuple[str, str]] = []
    services.document.dirty.connect(lambda owner, aspect: marks.append((owner, aspect)))

    open_tab(services, project)

    assert marks == []


def test_attach_to_pool_lands_in_the_project_area(services, project, step, monkeypatch, tmp_path):
    source = tmp_path / "mock.png"
    source.write_bytes(PNG)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        staticmethod(lambda *_a, **_k: (str(source), "")),
    )

    activity = open_tab(services, project)
    activity._attach_to_pool()

    area = services.repo.files(project.id, MODULE_ID)
    (name,) = [f"assets/{found}" for found in area.names("assets")]
    assert area.read_bytes(name) == PNG
    assert activity.list.count() == 1
