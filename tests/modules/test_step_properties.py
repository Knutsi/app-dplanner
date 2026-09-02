"""THE step detail panel: what the context puts in it, and what it survives.

Every test reaches the panel the way the application does — one panel, anchored in the
window — because the point of that seam is that no *surface* constructs a second one. The
details dialog is the sanctioned exception: a transient second host of the same sections,
opened by the ``steps.details`` verb and disposed when it closes.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, RemoveNodeCommand, SetFieldCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.step_properties.module import PANEL_ID


def select(services, *step_ids):
    nodes = tuple(ContextNode(selection_uri("step", step_id)) for step_id in step_ids)
    services.context.set_scope(SCOPE_SELECTION, nodes)


@pytest.fixture
def project(services, make_project):
    library = services.document
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(library)
    AddNodeCommand(project.id, Step(title="Draft the model")).redo(library)
    return project


@pytest.fixture
def panel(services, project):
    return services.window.dock.widget_for(PANEL_ID)


def test_one_step_selected_is_something_to_edit(services, project, panel):
    """None or several is not — and the panel says so by going off screen rather than by
    showing a placeholder, which is what lets another panel have the area instead."""
    dock = services.window.dock
    select(services, project.steps[0].id)
    assert dock.is_panel_showing(PANEL_ID)
    assert panel.current_step_id() == project.steps[0].id

    select(services, *[step.id for step in project.steps])
    assert not dock.is_panel_showing(PANEL_ID)
    assert panel.current_step_id() is None


def visible_labels(panel):
    return [
        panel.tab_bar.tabText(i)
        for i in range(panel.tab_bar.count())
        if panel.tab_bar.isTabVisible(i)
    ]


def test_showing_a_step_reveals_the_aspect_tabs(services, project, panel):
    """A tab follows its aspect: a plain step shows only the always-on sections, and the
    toggleable ones (Ticket, Tests, Covers, Agent, Milestone) stay off screen until the step
    carries them."""
    select(services, project.steps[0].id)
    all_labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    expected = [
        "Details",
        "Ticket",
        "Docs",
        "Tests",
        "Covers",
        "Agent",
        "Feature",
        "Milestone",
        "Handoff",
        "GitHub",
    ]
    assert all_labels == expected
    # Every tab follows an aspect now, the Details tab included — it is its blocks. A
    # plain step keeps Details, because a description and an estimate default to on;
    # Handoff and GitHub are the exception and stay off until somebody asks.
    assert visible_labels(panel) == ["Details"]


def test_a_toggled_aspect_shows_its_tab_live(services, project, panel):
    """Toggling an aspect on brings its tab in without reselecting; toggling off removes
    it and the current tab falls back to the first visible one."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.docs.aspect import MODULE_ID as DOCS_ID
    from dplanner.modules.docs.aspect import write_state as docs_write
    from dplanner.modules.github.aspect import MODULE_ID as GITHUB_ID
    from dplanner.modules.github.aspect import write_state as github_write
    from dplanner.modules.step_agent_instruction.aspect import (
        MODULE_ID as AGENT_ID,
    )
    from dplanner.modules.step_agent_instruction.aspect import (
        write_state,
    )
    from dplanner.modules.step_check.aspect import MODULE_ID as CHECK_ID
    from dplanner.modules.step_check.aspect import write as check_write
    from dplanner.modules.step_handoff.aspect import MODULE_ID as HANDOFF_ID
    from dplanner.modules.step_handoff.aspect import write_state as handoff_write
    from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
    from dplanner.modules.step_milestone.aspect import write as milestone_write
    from dplanner.modules.step_ticket.aspect import MODULE_ID as TICKET_ID
    from dplanner.modules.step_ticket.aspect import enabled_entry
    from dplanner.modules.testing.aspect import MODULE_ID as TESTING_ID
    from dplanner.modules.testing.aspect import Test
    from dplanner.modules.testing.aspect import write as tests_write

    step = project.steps[0]
    select(services, step.id)
    services.undo.push(SetModuleDataCommand(step.id, MILESTONE_ID, milestone_write("v1")))
    services.undo.push(SetModuleDataCommand(step.id, AGENT_ID, write_state(True)))
    services.undo.push(SetModuleDataCommand(step.id, TICKET_ID, enabled_entry()))
    services.undo.push(
        SetModuleDataCommand(step.id, TESTING_ID, tests_write([Test("t1", "A test")]))
    )
    services.undo.push(SetModuleDataCommand(step.id, CHECK_ID, check_write(True)))
    services.undo.push(SetModuleDataCommand(step.id, HANDOFF_ID, handoff_write(True)))
    services.undo.push(SetModuleDataCommand(step.id, GITHUB_ID, github_write(True)))
    services.undo.push(SetModuleDataCommand(step.id, DOCS_ID, docs_write(True)))
    assert visible_labels(panel) == [
        "Details",
        "Ticket",
        "Docs",
        "Tests",
        "Covers",
        "Agent",
        "Milestone",
        "Handoff",
        "GitHub",
    ]

    # Land on the Milestone tab, then clear the aspect: the tab leaves and the current
    # tab is a visible one again.
    release_index = next(
        i for i in range(panel.tab_bar.count()) if panel.tab_bar.tabText(i) == "Milestone"
    )
    panel.tab_bar.setCurrentIndex(release_index)
    services.undo.push(SetModuleDataCommand(step.id, MILESTONE_ID, {}))
    assert "Milestone" not in visible_labels(panel)
    assert panel.tab_bar.isTabVisible(panel.tab_bar.currentIndex())


def test_the_title_is_shown_and_edited_undoably(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    assert panel.title_edit.text() == "Read the spec"

    panel.title_edit.setText("Read the whole spec")
    panel.title_edit.editingFinished.emit()
    assert step.title == "Read the whole spec"
    services.undo.undo()
    assert step.title == "Read the spec"


def test_the_plus_button_opens_the_type_toggles_over_this_panels_step(services, project, panel):
    """The chooser renders the Step ▸ Type submenu; it never keeps a list of its own.

    And it reads the *panel's* step, not the window's selection — a panel inside the
    details dialog is showing a step nobody selected.
    """
    from dplanner.framework.action_dialog import TogglesDialog
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
    from dplanner.modules.step_check.aspect import read as check_read

    step = project.steps[0]
    select(services, step.id)
    assert panel.add_aspect.isVisibleTo(panel) is True

    node = ContextNode(selection_uri("step", step.id))
    dialog = TogglesDialog(
        services.actions,
        lambda: Context({SCOPE_SELECTION: (node,)}),
        menu="Step",
        submenu="Type",
        title="Aspects",
    )
    assert list(dialog.rows) == [
        spec.id
        for spec in services.actions.all_specs()
        if spec.menu == "Step" and spec.submenu == "Type"
    ]
    # Every row runs the owning module's own toggle: one undoable command, not a copy.
    dialog.rows["check.toggle"].box.click()
    assert check_read(step) is True
    services.undo.undo()
    assert check_read(step) is False
    dialog.deleteLater()


def test_the_plus_button_is_hidden_when_no_step_is_shown(services, project, panel):
    select(services, project.steps[0].id)
    panel.show_step(None)
    assert panel.add_aspect.isVisibleTo(panel) is False


def test_deselecting_gets_through_the_unchanged_id_gate(services, project, panel):
    """`show_step` early-returns on an unchanged id, but "nothing" has to get through every
    time or the last step stays on screen after the user clicks away."""
    step = project.steps[0]
    panel.show_step(step.id)
    panel.show_step(None)
    assert panel.current_step_id() is None
    panel.show_step(step.id)
    assert panel.current_step_id() == step.id


def test_a_deleted_step_takes_the_panel_back_to_empty(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    services.undo.push(RemoveNodeCommand(step.id))
    assert panel.current_step_id() is None


def test_a_change_made_elsewhere_reaches_the_title(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    services.undo.push(SetFieldCommand(step.id, "title", "Renamed elsewhere"))
    assert panel.title_edit.text() == "Renamed elsewhere"


def test_a_disposed_panel_hears_nothing(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    panel.dispose()
    services.undo.push(SetFieldCommand(step.id, "title", "After disposal"))
    assert panel.title_edit.text() == "Read the spec"


# -- the details dialog ----------------------------------------------------------------------


def test_details_needs_exactly_one_selected_step(services, project):
    """Disabled, never hidden: none or several selected teaches the precondition."""
    spec = services.actions.spec("steps.details")
    select(services)
    assert not spec.state(services.context.current()).enabled
    select(services, *[step.id for step in project.steps])
    assert not spec.state(services.context.current()).enabled
    select(services, project.steps[0].id)
    assert spec.state(services.context.current()).enabled


def test_details_opens_a_dialog_that_is_the_panel_and_disposes_it(services, project, monkeypatch):
    """The dialog hosts a second StepPanel over the same sections — 1:1 with the anchored
    one by construction — and stops hearing the model once closed."""
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    step = project.steps[0]
    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    select(services, step.id)
    services.actions.run("steps.details", services.context.current())

    (dialog,) = opened
    assert dialog.panel.current_step_id() == step.id
    assert dialog.panel.tab_bar.count() > 0  # The aspect tabs arrived.
    # exec() returned, so run() has already disposed it: a model change must not reach it.
    services.undo.push(SetFieldCommand(step.id, "title", "After closing"))
    assert dialog.panel.title_edit.text() == "Read the spec"


def test_an_edit_in_the_dialog_lands_on_the_undo_stack(services, project, monkeypatch):
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    step = project.steps[0]

    def edit_title(dialog):
        dialog.panel.title_edit.setText("Read the whole spec")
        dialog.panel.title_edit.editingFinished.emit()

    monkeypatch.setattr(StepDetailsDialog, "exec", edit_title)
    select(services, step.id)
    services.actions.run("steps.details", services.context.current())

    assert step.title == "Read the whole spec"
    services.undo.undo()
    assert step.title == "Read the spec"


def test_the_details_dialog_never_outgrows_the_screen(services, project, monkeypatch):
    """It asks for 900x850 — room for the Tests tab's list beside its editor — but a laptop
    must still get a dialog it can show whole. Asserted against the clamp, not the constant:
    the offscreen platform reports an 800x800 screen, so the constant never survives here."""
    from dplanner.modules.step_properties.dialog import (
        DIALOG_HEIGHT,
        DIALOG_WIDTH,
        SCREEN_CLEARANCE,
        StepDetailsDialog,
    )

    step = project.steps[0]
    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    select(services, step.id)
    services.actions.run("steps.details", services.context.current())

    (dialog,) = opened
    available = dialog.screen().availableGeometry()
    assert dialog.width() == min(DIALOG_WIDTH, available.width() - SCREEN_CLEARANCE)
    assert dialog.height() == min(DIALOG_HEIGHT, available.height() - SCREEN_CLEARANCE)
