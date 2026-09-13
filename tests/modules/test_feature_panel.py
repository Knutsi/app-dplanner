"""The Features panel and the canvas drop: a record leaves the list as a drag and arrives on
the graph as the step that realises it — once.

The panel stands inside the project tab, beside the canvas, where that drag is a short
one — so it is reached through the tab rather than through the window's dock.
"""

import pytest
from PySide6.QtCore import QMimeData, QPointF

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.feature.aspect import MODULE_ID, read, write
from dplanner.modules.feature.catalogue import (
    FEATURE_MIME,
    FeatureRecord,
    drag_payload,
    instance_of,
    read_catalogue,
    write_catalogue,
)
from dplanner.modules.feature.panel import ID_ROLE, FeatureDialog
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Build the importer")).redo(services.document)
    records = [FeatureRecord("f1", "Bulk import"), FeatureRecord("f2", "Dark mode")]
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, write_catalogue(records)))
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def panel(tab):
    """The features list the graph tab stands beside its canvas."""
    frame = tab._panel_frame
    assert frame is not None, "the tab was handed no side panel"
    return frame.content


def rows(widget):
    return [
        (widget.list.item(i).text(), widget.list.item(i).data(ID_ROLE))
        for i in range(widget.list.count())
    ]


def feature_mime(project_id, feature_id):
    mime = QMimeData()
    mime.setData(FEATURE_MIME, drag_payload(project_id, feature_id))
    return mime


# -- the panel ---------------------------------------------------------------------------------


def test_the_panel_follows_the_focused_project(services, project, tab):
    widget = panel(tab)
    assert widget.current_project_id() == project.id
    assert rows(widget) == [("Bulk import", "f1"), ("Dark mode", "f2")]
    assert widget.empty.isHidden() and not widget.list.isHidden()


def test_the_panel_says_what_is_placed(services, project, tab):
    """Two lines per feature, the layers glyph on the first: the name, and what became of
    it under it. A placed one is muted — dealt with — and does not drag."""
    from PySide6.QtCore import Qt

    from dplanner.framework.list_rows import DETAIL_ROLE, MUTED_ROLE

    widget = panel(tab)
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write("f1")))
    placed, unplaced = widget.list.item(0), widget.list.item(1)
    assert not placed.icon().isNull() and not unplaced.icon().isNull()
    # The second line, where it used to be a tooltip nobody goes looking for.
    assert "placed: 'Build the importer'" in placed.data(DETAIL_ROLE)
    assert "not placed" in unplaced.data(DETAIL_ROLE)
    assert placed.data(MUTED_ROLE) and not unplaced.data(MUTED_ROLE)
    assert not placed.flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert "Drag onto the canvas" in unplaced.toolTip()
    assert unplaced.flags() & Qt.ItemFlag.ItemIsDragEnabled


def test_an_empty_catalogue_says_so_and_offers_the_verb_that_fills_it(
    services, make_project, monkeypatch
):
    """The hint used to hide when the list was empty — the inverse of every other surface."""
    from PySide6.QtWidgets import QInputDialog

    bare = make_project("Nothing yet")
    tab = services.tabs.open("project", bare.id)
    widget = panel(tab)
    assert widget.list.isHidden() and not widget.empty.isHidden()
    assert "No features" in widget.empty.label.text()

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Search", True))
    assert widget.empty.button is not None
    widget.empty.button.click()
    assert [r.title for r in read_catalogue(bare)] == ["Search"]
    assert not widget.list.isHidden() and widget.empty.isHidden()


def test_the_verbs_are_a_strip_of_glyphs_with_their_words_in_the_tooltip(services, project, tab):
    """Words on four buttons would set the panel's width; the strip folds instead."""
    widget = panel(tab)
    for verb in widget.verbs.values():
        assert not verb.icon().isNull()
    assert widget.verbs["feature.add"].toolTip().startswith("Add Feature…")
    assert widget.verbs["feature.add"] in widget.tools.verbs()


def test_a_row_drags_as_its_id_and_project(services, project, tab):
    widget = panel(tab)
    mime = widget.list.mimeData([widget.list.item(1)])
    assert mime.hasFormat(FEATURE_MIME)
    assert bytes(mime.data(FEATURE_MIME).data()) == drag_payload(project.id, "f2")
    assert mime.text() == "Dark mode"


def test_reveal_is_greyed_until_placed_and_then_selects_the_step(services, project, tab):
    widget = panel(tab)
    widget.select_feature("f1")
    state = services.actions.spec("feature.reveal").state(widget.context())
    assert not state.enabled and "not placed" in (state.label or "")
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write("f1")))
    widget.select_feature("f1")
    assert widget.verbs["feature.reveal"].isEnabled()
    widget.verbs["feature.reveal"].trigger()
    assert services.context.current().selected_entity("step") == step.id


def test_the_menu_bar_copy_is_greyed_with_the_reason(services, project, tab):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    state = services.actions.spec("feature.edit").state(services.context.current())
    assert not state.enabled and "Features panel" in (state.label or "")
    assert services.actions.spec("feature.add").state(services.context.current()).enabled


def test_add_and_remove_through_the_panel(services, project, tab, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from dplanner.modules.feature import module as feature_module

    widget = panel(tab)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Search", True))
    widget.verbs["feature.add"].trigger()
    assert [r.title for r in read_catalogue(project)] == ["Bulk import", "Dark mode", "Search"]
    assert rows(widget)[-1] == ("Search", "f3")

    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write("f3")))
    monkeypatch.setattr(feature_module, "confirm", lambda *a, **k: True)
    widget.select_feature("f3")
    widget.verbs["feature.remove"].trigger()
    assert [r.id for r in read_catalogue(project)] == ["f1", "f2"]
    assert read(step) is None  # Its step is plain again, in the same undo step.
    services.undo.undo()
    assert read(step) == "f3" and len(read_catalogue(project)) == 3


def test_double_clicking_a_row_opens_the_editor(services, project, tab, monkeypatch):
    opened = []
    monkeypatch.setattr(FeatureDialog, "exec", lambda self: opened.append(self.editor.record()))
    widget = panel(tab)
    widget.select_feature("f2")
    widget.list.itemDoubleClicked.emit(widget.list.item(1))
    assert [record.id for record in opened] == ["f2"]


# -- the drop ----------------------------------------------------------------------------------


def test_dropping_a_feature_places_its_step_in_one_undo_step(services, project, tab):
    tab._on_drop(feature_mime(project.id, "f1"), QPointF(400.0, 200.0))
    created = project.steps[-1]
    assert created.title == "Bulk import" and read(created) == "f1"
    placed = instance_of(project, "f1")
    assert placed is not None and placed.id == created.id
    assert POSITION_KEY in created.module_data  # A drop points at a spot, like a click.
    assert services.undo.undo_text() == "Place Feature"
    # Born as the Feature template: a collector carries no estimate of its own.
    from dplanner.modules.estimation.aspect import enabled as estimate_enabled

    assert estimate_enabled(created) is False
    assert services.context.current().selected_entity("step") == created.id
    services.undo.undo()
    assert len(project.steps) == 1 and instance_of(project, "f1") is None


def test_a_dropped_feature_lights_the_feature_template(services, project, tab, monkeypatch):
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    tab._on_drop(feature_mime(project.id, "f1"), QPointF(400.0, 200.0))
    created = project.steps[-1]
    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", created.id)),))
    services.actions.run("steps.details", services.context.current())
    (dialog,) = opened
    assert dialog.panel.bar.template("Feature").isChecked() is True
    assert dialog.panel.bar.template("Step").isChecked() is False
    dialog.dispose()


def test_dropping_a_placed_feature_is_refused_in_the_status_bar(services, project, tab):
    tab._on_drop(feature_mime(project.id, "f1"), QPointF(400.0, 200.0))
    before = len(project.steps)
    tab._on_drop(feature_mime(project.id, "f1"), QPointF(600.0, 200.0))
    assert len(project.steps) == before
    assert "already placed" in services.window.statusBar().currentMessage()


def test_a_foreign_projects_feature_is_refused(services, project, tab, make_project):
    other = make_project("Other")
    tab._on_drop(feature_mime(other.id, "f1"), QPointF(400.0, 200.0))
    assert len(project.steps) == 1
    assert "another project" in services.window.statusBar().currentMessage()


def test_the_view_accepts_only_a_feature_drag(services, project, tab):
    plain = QMimeData()
    plain.setText("hello")
    assert tab._accepts_drop(plain) is False
    assert tab._accepts_drop(feature_mime(project.id, "f1")) is True
