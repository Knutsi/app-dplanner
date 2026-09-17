"""The feature module: the aspect on disk, the migration off the catalogue, the Type
toggle and the Feature tab. The CLI half is ``tests/cli/test_feature_verbs.py``.
"""

import json

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Project, Step
from dplanner.modules.feature.aspect import (
    MODULE_ID,
    RETIRED_STEP_FEATURE,
    FeatureSource,
    cited_at,
    clear,
    drop_cites_for_paste,
    is_feature,
    passages_phrase,
    read,
    summary,
    write,
)

# -- the aspect, with no application at all ----------------------------------------------------


def test_absence_reads_as_not_a_feature():
    assert read(Step(title="A")) is None
    assert is_feature(Step(title="A")) is False
    assert summary(Step(title="A")) == ""


def test_a_bare_marker_is_a_whole_feature():
    step = Step(title="A")
    step.module_data[MODULE_ID] = write()
    assert read(step) == () and is_feature(step)
    assert summary(step) == "feature"
    assert step.module_data[MODULE_ID] == {"on": True, "format": 3}


def test_the_passages_round_trip_and_what_is_empty_is_left_out():
    cites = (
        FeatureSource("spec", "must be dark", 4, "abcdef0123456789"),
        FeatureSource("spec"),
    )
    entry = write(cites)
    assert entry["cites"] == [
        {"document": "spec", "quote": "must be dark", "page": 4, "digest": "abcdef0123456789"},
        {"document": "spec"},
    ]
    step = Step(title="A")
    step.module_data[MODULE_ID] = json.loads(json.dumps(entry))
    assert read(step) == cites
    assert summary(step) == "feature · spec p.4 +1"
    assert passages_phrase(()) == "cites nothing"


def test_a_passage_is_matched_by_its_document_and_its_wording():
    cites = (FeatureSource("spec", "Must be\n dark"),)
    assert cited_at(cites, "spec", "must  BE dark") == 0
    assert cited_at(cites, "other", "Must be dark") is None
    assert cited_at((), "spec", "anything") is None


def test_clear_writes_nothing_and_the_retired_module_is_named():
    assert clear() == {}
    assert RETIRED_STEP_FEATURE.module_id == "step_feature"


def test_a_retired_marker_converts_to_a_whole_feature():
    from dplanner.modules.feature.aspect import _from_step_feature

    assert _from_step_feature({"on": True}, {}) == {"on": True, "format": 3}
    # An entry this build already wrote wins: a project half-written by both keeps it.
    already = {"on": True, "cites": [{"document": "spec"}], "format": 3}
    assert _from_step_feature({"on": True}, already) == already


def test_format_1_wraps_the_one_source_and_leaves_the_rest_to_the_absorption():
    from dplanner.core.module_data import migrated
    from dplanner.modules.feature.aspect import DATA_FORMAT

    old = {
        "format": 1,
        "features": [
            {"id": "f1", "title": "A", "source": {"document": "spec", "quote": "q", "page": 2}},
            {"id": "f2", "title": "B"},
        ],
    }
    new = migrated(old, DATA_FORMAT)
    assert new is not None and new["format"] == 3
    # Format 2's shape is reached on the way, and format 3 carries both old shapes
    # through untouched — the absorption is what reads them, once it can see the project.
    assert new["features"][0]["sources"] == [{"document": "spec", "quote": "q", "page": 2}]
    assert "source" not in new["features"][0] and "sources" not in new["features"][1]
    marker = migrated({"feature": "f1", "format": 1}, DATA_FORMAT)
    assert marker is not None and marker["feature"] == "f1" and marker["format"] == 3


def test_a_pasted_feature_step_is_a_feature_citing_nothing():
    step = Step(title="Search")
    step.module_data[MODULE_ID] = write((FeatureSource("spec", "a quote"),))
    plain = Step(title="Plain")
    drop_cites_for_paste(Project(title="P"), [step, plain])
    assert read(step) == () and is_feature(step)
    assert MODULE_ID not in plain.module_data


# -- the Type toggle and the Feature template ---------------------------------------------------


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


def test_toggling_off_shelves_the_passages_and_on_brings_them_back(services, step):
    select(services, step)
    services.actions.run("feature.toggle", services.context.current())
    assert read(step) == ()
    assert services.undo.undo_text() == "Add Feature"
    services.document.set_module_data(
        step.id, MODULE_ID, write((FeatureSource("spec", "a quote"),))
    )

    services.actions.run("feature.toggle", services.context.current())
    assert read(step) is None
    services.actions.run("feature.toggle", services.context.current())
    assert read(step) == (FeatureSource("spec", "a quote"),)
    services.undo.undo()
    assert read(step) is None
    services.undo.undo()
    assert read(step) == (FeatureSource("spec", "a quote"),)


def test_the_feature_template_makes_the_step_a_feature(services, project, monkeypatch):
    """New births a plain step and opens its details; the Feature template there runs
    the toggle."""
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    services.tabs.open("project", project.id)
    services.actions.run("steps.new", services.context.current())
    created = project.steps[-1]
    (dialog,) = opened
    dialog.panel.bar.template("Feature").trigger()
    assert read(created) == ()
    dialog.dispose()


# -- the Feature tab ---------------------------------------------------------------------------


def tab_labels(panel):
    return [
        panel.tab_bar.tabText(i)
        for i in range(panel.tab_bar.count())
        if panel.tab_bar.isTabVisible(i)
    ]


def test_the_feature_tab_follows_the_marker(services, step, step_editor):
    select(services, step)
    panel = step_editor(step.id)
    assert "Feature" not in tab_labels(panel)
    services.actions.run("feature.toggle", services.context.current())
    assert "Feature" in tab_labels(panel)
    services.actions.run("feature.toggle", services.context.current())
    assert "Feature" not in tab_labels(panel)


def test_the_feature_tab_edits_the_steps_own_passages(services, step, step_editor):
    from dplanner.modules.feature.editor import FeatureEditor

    select(services, step)
    services.actions.run("feature.toggle", services.context.current())
    panel = step_editor(step.id)
    editor = next(e for e in panel._extensions if isinstance(e, FeatureEditor))
    assert editor.cites() == ()
    editor.add_passage.click()
    assert len(read(step) or ()) == 1
    editor.quote.setPlainText("must be dark")
    editor.quote.editing_finished.emit()
    assert (read(step) or ())[0].quote == "must be dark"
    assert services.undo.undo_text() == "Edit Passages"
