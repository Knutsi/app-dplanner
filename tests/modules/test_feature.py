"""The feature module: the marker and the catalogue on disk, the Type toggle, New ▸
Feature, and the Feature tab. The CLI half is ``tests/cli/test_feature_verbs.py``; the
panel and the drop are ``test_feature_panel.py``.
"""

import json

import pytest

from dplanner.domain.commands import AddNodeCommand, RemoveNodeCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.feature.aspect import (
    MODULE_ID,
    RETIRED_STEP_FEATURE,
    clear,
    is_feature,
    read,
    summary,
    write,
)
from dplanner.modules.feature.catalogue import (
    FeatureRecord,
    FeatureSource,
    drag_payload,
    drop_marker_for_paste,
    instance_of,
    next_feature_id,
    parse_drag,
    placements,
    read_catalogue,
    registration,
    write_catalogue,
)

# -- the aspect, with no application at all ----------------------------------------------------


def test_absence_reads_as_not_a_feature():
    assert read(Step(title="A")) is None
    assert is_feature(Step(title="A")) is False
    assert summary(Step(title="A")) == ""


def test_the_marker_names_the_record():
    step = Step(title="A")
    step.module_data[MODULE_ID] = write("f3")
    assert read(step) == "f3" and is_feature(step)
    assert summary(step) == "feature f3"
    assert step.module_data[MODULE_ID] == {"feature": "f3", "format": 1}


def test_a_retired_marker_reads_as_unregistered():
    step = Step(title="A")
    step.module_data[MODULE_ID] = {"on": True}
    assert read(step) == "" and is_feature(step)
    assert summary(step) == "feature (unregistered)"
    assert RETIRED_STEP_FEATURE.module_id == "step_feature"


def test_clear_writes_nothing_and_an_empty_id_is_refused():
    assert clear() == {}
    with pytest.raises(ValueError):
        write("")


# -- the catalogue -----------------------------------------------------------------------------


def test_the_catalogue_round_trips_and_omits_what_is_empty():
    records = [
        FeatureRecord("f1", "Bulk import"),
        FeatureRecord(
            "f2",
            "Dark mode",
            description="Night.",
            source=FeatureSource("spec", "must be dark", 4),
            images=("assets/abc.png",),
        ),
    ]
    entry = write_catalogue(records)
    assert entry["features"][0] == {"id": "f1", "title": "Bulk import"}
    assert entry["features"][1]["source"] == {
        "document": "spec",
        "quote": "must be dark",
        "page": 4,
    }
    project = Project(title="P")
    project.module_data[MODULE_ID] = json.loads(json.dumps(entry))
    assert read_catalogue(project) == records
    assert write_catalogue([]) == {}
    assert next_feature_id(records) == "f3"


def bare_project():
    """A project in a library with no store behind it — enough for the catalogue."""
    library = Library()
    project = Project(title="P")
    library.add_child(library.id, project)
    return library, project


def test_placements_and_instance_read_the_markers():
    library, project = bare_project()
    one, two, three = Step(title="One"), Step(title="Two"), Step(title="Three")
    for step in (one, two, three):
        library.add_child(project.id, step)
    one.module_data[MODULE_ID] = write("f1")
    two.module_data[MODULE_ID] = write("f1")
    three.module_data[MODULE_ID] = {"on": True}
    assert placements(project) == {"f1": [one, two]}
    assert instance_of(project, "f1") is one
    assert instance_of(project, "f2") is None


def test_registration_is_a_record_and_a_marker_or_nothing():
    library, project = bare_project()
    step = Step(title="Search")
    library.add_child(project.id, step)
    for command in registration(project, step):
        command.redo(library)
    assert read(step) == "f1"
    assert [r.title for r in read_catalogue(project)] == ["Search"]
    # Already registered: nothing to do, so nothing to undo.
    assert registration(project, step) == []


def test_a_drag_payload_round_trips_and_garbage_is_nothing():
    assert parse_drag(drag_payload("p1", "f2")) == ("p1", "f2")
    assert parse_drag(b"not json") is None
    assert parse_drag(json.dumps({"project": "p1"}).encode()) is None
    assert parse_drag(json.dumps([1, 2]).encode()) is None


def test_a_pasted_feature_step_is_a_plain_copy():
    step = Step(title="Search")
    step.module_data[MODULE_ID] = write("f1")
    drop_marker_for_paste(Project(title="P"), [step])
    assert MODULE_ID not in step.module_data


# -- the Type toggle and New ▸ Feature ----------------------------------------------------------


def select(services, step):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))


@pytest.fixture
def project(make_project):
    return make_project("Discovery")


@pytest.fixture
def step(services, project):
    step = Step(title="Bulk import")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def test_the_feature_toggle_sits_in_the_type_submenu(services):
    spec = services.actions.spec("feature.toggle")
    assert spec.menu == "Step" and spec.group == "classify" and spec.submenu == "Type"


def test_toggling_on_mints_a_record_and_off_keeps_it(services, project, step):
    select(services, step)
    services.actions.run("feature.toggle", services.context.current())
    assert read(step) == "f1"
    assert [r.title for r in read_catalogue(project)] == ["Bulk import"]
    assert services.undo.undo_text() == "Mark as Feature"

    services.actions.run("feature.toggle", services.context.current())
    assert read(step) is None
    # The record stays, unplaced: nothing a person wrote is lost, and undo is exact.
    assert [r.id for r in read_catalogue(project)] == ["f1"]
    assert instance_of(project, "f1") is None
    services.undo.undo()
    assert read(step) == "f1"
    services.undo.undo()
    assert read(step) is None and read_catalogue(project) == []


def test_toggling_an_unregistered_step_registers_it(services, project, step):
    services.document.set_module_data(step.id, MODULE_ID, {"on": True})
    select(services, step)
    assert services.actions.spec("feature.toggle").state(services.context.current()).checked
    services.actions.run("feature.toggle", services.context.current())
    assert read(step) == "f1" and read_catalogue(project)[0].title == "Bulk import"


def test_deleting_the_instance_leaves_the_record_unplaced(services, project, step):
    select(services, step)
    services.actions.run("feature.toggle", services.context.current())
    services.undo.push(RemoveNodeCommand(step.id))
    assert instance_of(project, "f1") is None
    assert [r.id for r in read_catalogue(project)] == ["f1"]
    services.undo.undo()
    assert instance_of(project, "f1") is not None


def test_new_feature_is_born_with_its_record(services, project, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    services.tabs.open("project", project.id)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Search", True))
    services.actions.run("steps.new_feature", services.context.current())
    created = project.steps[-1]
    assert created.title == "Search" and read(created) == "f1"
    assert [r.title for r in read_catalogue(project)] == ["Search"]
    assert services.undo.undo_text() == "New Feature"
    services.undo.undo()
    assert read_catalogue(project) == [] and len(project.steps) == 0


# -- the Feature tab ---------------------------------------------------------------------------


def step_panel(services):
    from dplanner.modules.step_properties.module import PANEL_ID

    return services.window.dock.widget_for(PANEL_ID)


def tab_labels(panel):
    return [
        panel.tab_bar.tabText(i)
        for i in range(panel.tab_bar.count())
        if panel.tab_bar.isTabVisible(i)
    ]


def test_the_feature_tab_follows_the_marker(services, project, step):
    select(services, step)
    panel = step_panel(services)
    assert "Feature" not in tab_labels(panel)
    services.actions.run("feature.toggle", services.context.current())
    assert "Feature" in tab_labels(panel)
    services.actions.run("feature.toggle", services.context.current())
    assert "Feature" not in tab_labels(panel)


def test_the_feature_tab_edits_the_record(services, project, step):
    from dplanner.modules.feature.section import FeatureSection

    select(services, step)
    services.actions.run("feature.toggle", services.context.current())
    panel = step_panel(services)
    section = next(e for e in panel._extensions if isinstance(e, FeatureSection))
    assert section.editor.title.text() == "Bulk import"
    section.editor.title.setText("CSV import")
    section.editor.title.editingFinished.emit()
    assert read_catalogue(project)[0].title == "CSV import"
    assert services.undo.undo_text() == "Edit Feature f1"


def test_an_unregistered_step_offers_to_register(services, project, step):
    from dplanner.modules.feature.section import FeatureSection

    services.document.set_module_data(step.id, MODULE_ID, {"on": True})
    select(services, step)
    panel = step_panel(services)
    section = next(e for e in panel._extensions if isinstance(e, FeatureSection))
    assert section._pages.currentWidget() is section.unregistered
    section.register_button.click()
    assert read(step) == "f1"
    assert section._pages.currentWidget() is section.editor
