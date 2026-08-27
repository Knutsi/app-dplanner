"""The stacked Agent tab and the project panel's Agent card.

Three parts over one briefing: the project's standing instruction (one field, two editors,
one undo stack), the inherited context (derived, read-only, rendered by the prompt's own
``part_lines``), and the step's instruction. The card is the same project field again.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Project, Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID

# -- fixtures ----------------------------------------------------------------------------------


@pytest.fixture
def step(services):
    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(product)
    return step


def select(services, step):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),)
    )


@pytest.fixture
def section(services, step):
    spec = next(
        s
        for s in services.inspector_sections.sections()
        if s.id == "step_agent_instruction.tab"
    )
    section = spec.factory()
    yield section
    section.dispose()


@pytest.fixture
def card(services):
    spec = next(
        s for s in services.detail_cards.sections() if s.id == "step_agent_instruction.card"
    )
    card = spec.factory()
    yield card
    card.dispose()


# -- the three parts ---------------------------------------------------------------------------


def test_this_step_opens_expanded_and_the_context_parts_collapsed(services, step, section):
    section.show_target(step.id)
    assert section.step_part.expanded()
    assert not section.project_part.expanded()
    assert not section.inherited_part.expanded()


def test_the_chevron_toggles_a_part(services, step, section):
    section.show_target(step.id)
    section.project_part.chevron.click()
    assert section.project_part.expanded()
    section.project_part.chevron.click()
    assert not section.project_part.expanded()


def test_the_project_part_edits_the_projects_own_text(services, step, section):
    section.show_target(step.id)
    section.project_edit.setPlainText("House rules.")
    project = services.document.project_of(step.id)
    assert project.module_text[MODULE_ID] == "House rules."


def test_the_inherited_part_shows_what_earlier_steps_handed_forward(services, step, section):
    product = services.document
    project = product.project_of(step.id)
    earlier = Step(title="Set up CI", edges={"requires": []})
    AddNodeCommand(project.id, earlier).redo(product)
    product.set_edges(step.id, "requires", [earlier.id])
    product.set_text(earlier.id, "step_handoff", "Keys in vault.")

    section.show_target(step.id)
    text = section.inherited_view.toPlainText()
    assert 'From "Set up CI"' in text and "Keys in vault." in text
    assert "1 block" in section.inherited_part.summary.text()

    # A handoff edited while the tab is open reaches the pane without a reselect.
    product.set_text(earlier.id, "step_handoff", "Keys moved to 1Password.")
    assert "1Password" in section.inherited_view.toPlainText()


def test_the_summaries_follow_the_text(services, step, section):
    section.show_target(step.id)
    assert section.step_part.summary.text() == "empty"
    section.edit.setPlainText("Ship it.")
    assert "chars" in section.step_part.summary.text()


# -- one field, two editors --------------------------------------------------------------------


def test_the_card_and_the_tab_edit_one_field_over_one_undo_stack(services, step, section, card):
    project = services.document.project_of(step.id)
    section.show_target(step.id)
    card.show_target(project.id)

    card.edit.setPlainText("House rules.")
    assert section.project_edit.toPlainText() == "House rules."

    services.undo.break_coalescing()  # Two bursts, two commands — the undo test needs both.
    cursor = section.project_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(" Amended.")
    assert card.edit.toPlainText() == "House rules. Amended."

    services.undo.undo()
    assert project.module_text[MODULE_ID] == "House rules."
    assert card.edit.toPlainText() == "House rules."


def test_the_card_registers_into_detail_cards(services):
    assert any(
        s.id == "step_agent_instruction.card" for s in services.detail_cards.sections()
    )


def test_the_project_panel_shows_the_agent_card(services, step):
    project = services.document.project_of(step.id)
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    panel = services.window.dock.widget_for("project_editor.project")
    titles = [c.title.text() for c in panel._cards]
    assert "Agent" in titles and "Repository" in titles


# -- the preview -------------------------------------------------------------------------------


def test_preview_is_enabled_with_a_step_and_shows_the_assembly(services, step, section):
    select(services, step)
    state = services.actions.spec("agent.preview").state(services.context.current())
    assert state.visible and state.enabled

    section.show_target(step.id)
    assert section.preview_button.isEnabled()


def test_preview_shows_the_exact_assembled_prompt(services, step, monkeypatch):
    from dplanner.modules.step_agent_instruction import module as module_module

    services.document.set_text(step.id, MODULE_ID, "Ship it.")
    project = services.document.project_of(step.id)
    services.document.set_text(project.id, MODULE_ID, "House rules.")
    select(services, step)

    shown = {}

    class FakeDialog:
        def __init__(self, text, _path, _parent, **kwargs):
            shown["text"] = text
            shown.update(kwargs)

        def exec(self):
            return 0

    monkeypatch.setattr(module_module, "PromptFallbackDialog", FakeDialog)
    services.actions.run("agent.preview", services.context.current())
    assert "House rules." in shown["text"] and "Ship it." in shown["text"]
    assert shown["title"] == "Prompt Preview"
