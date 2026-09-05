"""The stacked Agent tab and the project panel's Agent card.

Three parts over one briefing: the project's standing instruction (one field, two editors,
one undo stack), the inherited context (derived, read-only, rendered by the prompt's own
``part_lines``), and the step's instruction. The card is the same project field again.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID

# -- fixtures ----------------------------------------------------------------------------------


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def select(services, step):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))


@pytest.fixture
def section(services, step):
    spec = next(
        s for s in services.inspector_sections.sections() if s.id == "step_agent_instruction.tab"
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


# -- the Prompt tab ----------------------------------------------------------------------------


def test_the_section_opens_on_the_prompt_tab_showing_the_assembly(services, step, section):
    """The first thing shown is the thing to inspect: the exact text Run Agent sends."""
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    project = services.document.project_of(step.id)
    services.document.set_text(project.id, "step_agent_instruction", "House rules.")
    section.show_target(step.id)

    assert section.tab_bar.currentIndex() == 0
    text = section.prompt_view.toPlainText()
    assert text.startswith("# Step: Deploy")
    assert "## Project instructions" in text and "House rules." in text
    assert "Ship it." in text
    assert "## When you are done" in text  # the epilogue rides along — the full briefing


def test_the_prompt_is_tinted_by_origin_without_changing_the_text(services, step, section):
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    project = services.document.project_of(step.id)
    services.document.set_text(project.id, "step_agent_instruction", "House rules.")
    section.show_target(step.id)
    # The colouring renders segments; the characters must be exactly the assembly.
    assert section.prompt_view.toPlainText() == section._assembled_now.text
    legend = section.prompt_legend.text()
    assert section.prompt_legend.isVisibleTo(section)
    assert "Project" in legend and "This step" in legend


def test_the_prompt_tab_lists_every_referenced_image(services, step, section):
    from dplanner.domain.assets import attach

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    attach(services.repo.files(step.id, "step_agent_instruction"), b"png", "mock.png")
    attach(services.repo.files(step.id, "spec"), b"png", "figure.png")
    section.show_target(step.id)
    names = section.prompt_gallery._names
    assert len(names) == 2
    assert any("step_agent_instruction" in name for name in names)
    assert any("modules/spec" in name for name in names)


def test_the_prompt_refreshes_lazily_only_while_shown(services, step, section):
    section.show_target(step.id)
    section.tab_bar.setCurrentIndex(1)  # Components
    services.document.set_text(step.id, "step_description", "Now described.")
    assert "Now described." not in section.prompt_view.toPlainText()  # stale, offscreen
    section.tab_bar.setCurrentIndex(0)  # back to Prompt
    assert "Now described." in section.prompt_view.toPlainText()


def test_copy_prompt_fills_the_clipboard(services, step, section):
    from PySide6.QtGui import QGuiApplication

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    section.show_target(step.id)
    section.copy_button.click()
    assert QGuiApplication.clipboard().text() == section.prompt_view.toPlainText()


# -- the Components tab ------------------------------------------------------------------------


def test_this_step_opens_expanded_and_the_context_parts_collapsed(services, step, section):
    section.show_target(step.id)
    assert section.step_part.expanded()
    assert not section.project_part.expanded()
    assert not section.inherited_part.expanded()
    assert not section.context_part.expanded()


def test_the_step_context_part_shows_the_briefing_sections(services, step, section):
    """The step's facts — description, spec figures — appear in the tab, not only in the
    assembled prompt: the invisibility this part exists to end."""
    from dplanner.domain.assets import attach
    from dplanner.framework.asset_gallery import AssetGallery

    # With a separate instruction, the description stays a section of its own; without
    # one it becomes the ## Instructions block instead (tested below).
    services.document.set_text(step.id, MODULE_ID, "Ship it.")
    services.document.set_text(step.id, "step_description", "What the step is.")
    attach(services.repo.files(step.id, "spec"), b"png bytes", "fig.png")
    section.show_target(step.id)

    text = section.context_view.toPlainText()
    assert "## Description" in text and "What the step is." in text
    assert "## Figures from the spec" in text
    assert section.context_part.summary.text() == "2 sections"
    # One gallery: only the figures section carries files (the description has no images).
    galleries = section._context_galleries.findChildren(AssetGallery)
    assert len(galleries) == 1
    # Read-only: a context gallery never offers an Attach button.
    assert all(not g.attach_button.isVisibleTo(g) for g in galleries)


def test_an_edit_refreshes_the_step_context_without_a_reselect(services, step, section):
    services.document.set_text(step.id, MODULE_ID, "Ship it.")
    section.show_target(step.id)
    assert "## Description" not in section.context_view.toPlainText()
    services.document.set_text(step.id, "step_description", "Now described.")
    assert "Now described." in section.context_view.toPlainText()


def test_a_described_step_briefs_with_the_description_once(services, step, section):
    """No separate instruction: the description renders as ## Instructions and no
    ## Description section repeats it."""
    from dplanner.modules.step_agent_instruction.aspect import write_state

    services.document.set_module_data(step.id, MODULE_ID, write_state(True))
    services.document.set_text(step.id, "step_description", "The release step.")
    section.show_target(step.id)
    text = section.prompt_view.toPlainText()
    assert "## Instructions" in text and "The release step." in text
    assert "## Description" not in text
    assert text.count("The release step.") == 1


def test_the_editor_appears_only_with_a_separate_instruction(services, step, section):
    """The description is the instructions by default, so the This-step editor stays off
    screen and a note says where the text lives; separate text brings it back."""
    from dplanner.modules.step_agent_instruction.aspect import write_state

    services.document.set_module_data(step.id, MODULE_ID, write_state(True))
    section.show_target(step.id)
    section.tab_bar.setCurrentIndex(1)  # Components — the page the editor lives on.
    assert not section.step_part.isVisibleTo(section)
    assert section.step_note.isVisibleTo(section)

    services.document.set_module_data(step.id, MODULE_ID, write_state(True, separate=True))
    assert section.step_part.isVisibleTo(section)
    assert not section.step_note.isVisibleTo(section)


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
    library = services.document
    project = library.project_of(step.id)
    earlier = Step(title="Set up CI", edges={"requires": []})
    AddNodeCommand(project.id, earlier).redo(library)
    library.set_edges(step.id, "requires", [earlier.id])
    library.set_text(earlier.id, "step_handoff", "Keys in vault.")

    section.show_target(step.id)
    text = section.inherited_view.toPlainText()
    assert 'From "Set up CI"' in text and "Keys in vault." in text
    assert "1 block" in section.inherited_part.summary.text()

    # A handoff edited while the tab is open reaches the pane without a reselect.
    library.set_text(earlier.id, "step_handoff", "Keys moved to 1Password.")
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
    assert any(s.id == "step_agent_instruction.card" for s in services.detail_cards.sections())


def test_typing_in_the_panels_card_survives_context_republishes(services, step):
    """A model edit can republish the context mid-typing; the panel must not re-target its
    cards then — a rebind resets the editor's cursor and typing comes out scrambled."""
    from PySide6.QtTest import QTest

    from dplanner.modules.step_agent_instruction.section import ProjectInstructionCard

    project = services.document.project_of(step.id)
    services.tabs.open("project", project.id)
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    panel = services.window.dock.widget_for("project_editor.project")
    card = next(e for e in panel._extensions if isinstance(e, ProjectInstructionCard))

    QTest.keyClicks(card.edit, "hello world")
    assert card.edit.toPlainText() == "hello world"
    assert project.module_text[MODULE_ID] == "hello world"
    assert card.edit.textCursor().position() == len("hello world")


def test_the_project_panel_shows_the_agent_card(services, step):
    project = services.document.project_of(step.id)
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    panel = services.window.dock.widget_for("project_editor.project")
    titles = [c.title.text() for c in panel._cards]
    assert "Agent" in titles


# -- the preview -------------------------------------------------------------------------------


def test_preview_is_enabled_on_an_agent_step_and_greyed_with_the_reason_off_one(
    services, step, section
):
    from dplanner.modules.step_agent_instruction.aspect import write_state

    select(services, step)
    state = services.actions.spec("agent.preview").state(services.context.current())
    assert state.visible and not state.enabled  # Not an agent step: nothing to preview.
    assert state.label is not None and "agent step" in state.label

    services.document.set_module_data(step.id, MODULE_ID, write_state(True))
    state = services.actions.spec("agent.preview").state(services.context.current())
    assert state.enabled

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


# -- pasting an image into either instruction ----------------------------------------------------


def paste_image(edit):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    from dplanner.core.png import encode_rgb

    mime = QMimeData()
    mime.setImageData(QImage.fromData(encode_rgb(2, 2, 6, b"\x00" * 12)))
    edit.insertFromMimeData(mime)


def test_each_editor_pastes_into_its_own_level(services, step, section):
    """One module id, two areas — the step's instruction and the project's standing one.
    An editor aimed at the wrong one is a mistake that only shows up in somebody's diff."""
    from dplanner.domain.assets import assets

    project_id = services.document.project_of(step.id).id
    section.show_target(step.id)
    paste_image(section.edit)
    paste_image(section.project_edit)

    # Both areas hold one file. Content addressing means the same bytes get the same
    # *name* in either, so this is the assertion that separates them: had both editors
    # written to the step, the project's area would be empty.
    module = "step_agent_instruction"
    assert len(assets(services.repo.files(step.id, module))) == 1
    assert len(assets(services.repo.files(project_id, module))) == 1
    assert len(section.step_assets._names) == 1
    assert len(section.project_assets._names) == 1


def test_the_project_card_pastes_into_the_project(services, step, card):
    from dplanner.domain.assets import assets

    project_id = services.document.project_of(step.id).id
    card.show_target(project_id)
    paste_image(card.edit)
    names = assets(services.repo.files(project_id, "step_agent_instruction"))
    assert len(names) == 1
    assert card.gallery is not None and card.gallery._names == names
