"""The Features panel and the canvas drop: a record leaves the list as a drag and arrives on
the graph as the step that realises it — once.
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
from dplanner.modules.feature.module import PANEL_ID
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


def panel(services):
    return services.window.dock.widget_for(PANEL_ID)


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
    widget = panel(services)
    assert widget.current_project_id() == project.id
    assert rows(widget) == [("Bulk import", "f1"), ("Dark mode", "f2")]
    assert not widget.hint.isHidden()


def test_the_panel_says_what_is_placed(services, project, tab):
    """One line per feature, the layers glyph on each; a placed one is muted, says which
    step in its tooltip, and does not drag."""
    from PySide6.QtCore import Qt

    widget = panel(services)
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write("f1")))
    placed, unplaced = widget.list.item(0), widget.list.item(1)
    assert not placed.icon().isNull() and not unplaced.icon().isNull()
    assert "placed: 'Build the importer'" in placed.toolTip()
    secondary = services.theme.current.text_secondary
    assert placed.foreground().color().name() == secondary.lower()
    assert unplaced.foreground().color().name() != secondary.lower()
    assert not placed.flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert "not placed" in unplaced.toolTip() and "drag" in unplaced.toolTip()
    assert unplaced.flags() & Qt.ItemFlag.ItemIsDragEnabled


def test_the_buttons_are_glyphs_with_their_labels_as_tooltips(services, project, tab):
    """Words on four buttons would set the panel's width; the label lives in the tooltip."""
    from PySide6.QtCore import Qt

    widget = panel(services)
    for button in widget.buttons.values():
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        assert not button.icon().isNull()
        assert button.text() == ""
    assert widget.buttons["feature.add"].toolTip() == "Add Feature…"


def test_a_row_drags_as_its_id_and_project(services, project, tab):
    widget = panel(services)
    mime = widget.list.mimeData([widget.list.item(1)])
    assert mime.hasFormat(FEATURE_MIME)
    assert bytes(mime.data(FEATURE_MIME).data()) == drag_payload(project.id, "f2")
    assert mime.text() == "Dark mode"


def test_reveal_is_greyed_until_placed_and_then_selects_the_step(services, project, tab):
    widget = panel(services)
    widget.select_feature("f1")
    state = services.actions.spec("feature.reveal").state(widget.context())
    assert not state.enabled and "not placed" in (state.label or "")
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write("f1")))
    widget.select_feature("f1")
    assert widget.buttons["feature.reveal"].isEnabled()
    widget.buttons["feature.reveal"].click()
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

    widget = panel(services)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Search", True))
    widget.buttons["feature.add"].click()
    assert [r.title for r in read_catalogue(project)] == ["Bulk import", "Dark mode", "Search"]
    assert rows(widget)[-1] == ("Search", "f3")

    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write("f3")))
    monkeypatch.setattr(feature_module, "confirm", lambda *a, **k: True)
    widget.select_feature("f3")
    widget.buttons["feature.remove"].click()
    assert [r.id for r in read_catalogue(project)] == ["f1", "f2"]
    assert read(step) is None  # Its step is plain again, in the same undo step.
    services.undo.undo()
    assert read(step) == "f3" and len(read_catalogue(project)) == 3


def test_double_clicking_a_row_opens_the_editor(services, project, tab, monkeypatch):
    opened = []
    monkeypatch.setattr(FeatureDialog, "exec", lambda self: opened.append(self.editor.record()))
    widget = panel(services)
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
