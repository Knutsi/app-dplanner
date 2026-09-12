"""THE step detail panel: what the context puts in it, and what it survives.

Every test reaches the panel the way the application does — one panel, anchored in the
window — because the point of that seam is that no *surface* constructs a second one. The
details dialog is the sanctioned exception: a transient second host of the same sections,
opened by the ``steps.details`` verb and disposed when it closes.
"""

import pytest
from PySide6.QtWidgets import QDialogButtonBox, QLineEdit

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


def name_edit(panel):
    """The Name field: the first block of the Details tab, not a field of the panel's own."""
    return panel.findChild(QLineEdit, "InspectorTitle")


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
        "GitHub",
    ]
    assert all_labels == expected
    # Every other tab follows an aspect; Details always shows, because the name leads it
    # and a step always has one. GitHub stays off until somebody asks.
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


def test_the_name_is_shown_and_edited_undoably(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    assert name_edit(panel).text() == "Read the spec"

    name_edit(panel).setText("Read the whole spec")
    name_edit(panel).editingFinished.emit()
    assert step.title == "Read the whole spec"
    services.undo.undo()
    assert step.title == "Read the spec"


# -- the aspect bar ---------------------------------------------------------------------------


def type_toggle_ids(services):
    return [
        spec.id
        for spec in services.actions.all_specs()
        if spec.menu == "Step" and spec.submenu == "Type"
    ]


def test_the_bar_words_the_templates_left_and_glyphs_every_toggle_right(services, project, panel):
    """The right half renders the Step ▸ Type submenu and never keeps a list of its own;
    the left half is the composition root's templates, in its order."""
    select(services, project.steps[0].id)
    assert panel.bar.toggle_ids() == type_toggle_ids(services)
    assert panel.bar.template_labels() == ["Step", "Milestone", "Feature", "Agent", "Check"]


def test_a_plain_step_is_the_step_template_and_a_template_is_one_undo(services, project, panel):
    """A fresh step carries an estimate and a description, which is exactly the Step
    template; Make Milestone moves every toggle that differs as one undo step, and the
    step then lights Milestone instead — with its label generated, as the toggle does."""
    from dplanner.modules.estimation.aspect import enabled as estimate_on
    from dplanner.modules.step_milestone.aspect import read as milestone_label

    step = project.steps[0]
    select(services, step.id)
    assert panel.bar.template("Step").isChecked() is True
    assert panel.bar.template("Milestone").isChecked() is False

    panel.bar.template("Milestone").trigger()
    assert milestone_label(step) == "v1" and not estimate_on(step)
    assert panel.bar.template("Milestone").isChecked() is True
    assert panel.bar.template("Step").isChecked() is False
    assert "Milestone" in visible_labels(panel)
    assert services.undo.undo_text() == "Make Milestone"

    services.undo.undo()
    assert milestone_label(step) == "" and estimate_on(step)
    assert panel.bar.template("Step").isChecked() is True


def test_a_combination_built_by_hand_lights_its_template(services, project, panel):
    """It goes both ways: toggle Feature on and Estimate off by hand, and the Feature
    template reads as selected; add a Ticket, and it is just a Step again."""
    step = project.steps[0]
    select(services, step.id)
    panel.bar.action("feature.toggle").trigger()
    assert panel.bar.template("Feature").isChecked() is False  # Still carries an estimate.
    panel.bar.action("estimate.toggle").trigger()
    assert panel.bar.template("Feature").isChecked() is True
    panel.bar.action("ticket.toggle").trigger()
    assert panel.bar.template("Feature").isChecked() is False
    assert panel.bar.template("Step").isChecked() is True  # The catch-all.


def test_a_bar_action_runs_the_owning_modules_toggle_and_follows_the_model(
    services, project, panel
):
    """One undoable command, not a copy — and the check mark is re-read from the model,
    so an undo made elsewhere reaches the bar."""
    from dplanner.modules.step_check.aspect import read as check_read

    step = project.steps[0]
    select(services, step.id)
    action = panel.bar.action("check.toggle")
    assert action.isChecked() is False

    action.trigger()
    assert check_read(step) is True
    assert action.isChecked() is True
    assert "Covers" in visible_labels(panel)
    # Shown and *laid out*: QTabBar.setTabVisible only flags the layout dirty, and clears
    # that flag again when called with an unchanged value, so a tab can be "visible" with
    # an empty rect and never paint. The strip must have grown to hold it.
    covers = next(i for i in range(panel.tab_bar.count()) if panel.tab_bar.tabText(i) == "Covers")
    assert panel.tab_bar.tabRect(covers).width() > 0
    assert panel.tab_bar.sizeHint().width() > panel.tab_bar.tabRect(0).width()

    services.undo.undo()
    assert check_read(step) is False
    assert action.isChecked() is False


def test_the_bar_is_greyed_with_no_step(services, project, panel):
    select(services, project.steps[0].id)
    panel.show_step(None)
    assert not panel.bar.action("feature.toggle").isEnabled()


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


def test_a_change_made_elsewhere_reaches_the_name(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    services.undo.push(SetFieldCommand(step.id, "title", "Renamed elsewhere"))
    assert name_edit(panel).text() == "Renamed elsewhere"


def test_a_disposed_panel_hears_nothing(services, project, panel):
    step = project.steps[0]
    select(services, step.id)
    panel.dispose()
    services.undo.push(SetFieldCommand(step.id, "title", "After disposal"))
    assert name_edit(panel).text() == "Read the spec"


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
    one by construction — and stops hearing the model once closed. It carries no buttons:
    every edit is live and undoable, so there is nothing to confirm, and the Name field is
    focused with its text selected so a fresh step can be named by typing."""
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    step = project.steps[0]
    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    select(services, step.id)
    services.actions.run("steps.details", services.context.current())

    (dialog,) = opened
    assert dialog.panel.current_step_id() == step.id
    assert dialog.panel.tab_bar.count() > 0  # The aspect tabs arrived.
    assert dialog.findChild(QDialogButtonBox) is None
    assert dialog.name_edit().selectedText() == "Read the spec"
    assert dialog.windowTitle() == "Read the spec"
    # exec() returned, so run() has already disposed it: a model change must not reach it.
    services.undo.push(SetFieldCommand(step.id, "title", "After closing"))
    assert dialog.name_edit().text() == "Read the spec"


def test_the_dialogs_bar_acts_on_the_dialogs_own_step(services, project, monkeypatch):
    """A panel inside the dialog shows a step nobody selected, and its toggles must act on
    what is on screen, not on the window's selection."""
    from dplanner.modules.feature.aspect import is_feature as feature_read
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    shown, other = project.steps
    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    select(services, shown.id)
    services.actions.run("steps.details", services.context.current())
    (dialog,) = opened
    select(services, other.id)  # The window moves on; the dialog does not.

    dialog.panel.bar.action("feature.toggle").trigger()
    assert feature_read(shown) is True
    assert feature_read(other) is False


def test_an_edit_in_the_dialog_lands_on_the_undo_stack(services, project, monkeypatch):
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    step = project.steps[0]

    def edit_name(dialog):
        dialog.name_edit().setText("Read the whole spec")
        dialog.name_edit().editingFinished.emit()
        assert dialog.windowTitle() == "Read the whole spec"  # The title follows.

    monkeypatch.setattr(StepDetailsDialog, "exec", edit_name)
    select(services, step.id)
    services.actions.run("steps.details", services.context.current())

    assert step.title == "Read the whole spec"
    services.undo.undo()
    assert step.title == "Read the spec"


def test_the_details_dialog_never_outgrows_the_screen(services, project, monkeypatch):
    """It asks for 900x850 — room for the Tests tab's list beside its editor — but a laptop
    must still get a dialog it can show whole. The frame owns the clamp now, at SCREEN_SHARE
    of the screen; asserted against it, not the constant, because the offscreen platform
    reports an 800x800 screen and the constant never survives here."""
    from dplanner.modules.step_properties.dialog import (
        DIALOG_HEIGHT,
        DIALOG_WIDTH,
        StepDetailsDialog,
    )
    from dplanner.theme.tokens import SCREEN_SHARE

    step = project.steps[0]
    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    select(services, step.id)
    services.actions.run("steps.details", services.context.current())

    (dialog,) = opened
    available = dialog.screen().availableGeometry()
    assert dialog.width() == min(DIALOG_WIDTH, round(available.width() * SCREEN_SHARE))
    assert dialog.height() == min(DIALOG_HEIGHT, round(available.height() * SCREEN_SHARE))


def test_the_dialog_is_on_the_frame_with_no_footer_and_no_heading(services, project, monkeypatch):
    """F1's audit put this dialog on the frame; the frame prints no heading of its own, so
    what it shows is the panel and the window title is the step's own name."""
    from PySide6.QtWidgets import QLabel

    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    step = project.steps[0]
    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    select(services, step.id)
    services.actions.run("steps.details", services.context.current())
    (dialog,) = opened

    assert dialog.windowTitle() == "Read the spec"  # The step's, so a switcher can tell them apart.
    assert dialog.footer.isHidden()  # Every edit is live; there is nothing to confirm.
    assert dialog.footer_buttons() == []
    assert dialog.findChild(QLabel, "DialogTitle") is None
    assert dialog.findChild(QLabel, "DialogLead") is None
    dialog.dispose()
