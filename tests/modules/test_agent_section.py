"""The stacked Agent tab, and the Agent tab of *Project ▸ Settings…*.

Three parts over one briefing: the project's standing instruction (one field, two editors,
one undo stack), the inherited context (derived, read-only, rendered by the prompt's own
``section_lines``), and the step's instruction. The Settings tab is the same project field
again.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.planning.agent import MODULE_ID

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
def project_tab(services):
    spec = next(
        s for s in services.project_settings.sections() if s.id == "step_agent_instruction.project"
    )
    tab = spec.factory()
    yield tab
    tab.dispose()


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
    # And what it comes to, beside the colours: the size is the question the tab is for.
    assert f"{len(section._assembled_now.text)} chars" in legend


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
    from dplanner.planning.agent import write_state

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
    from dplanner.planning.agent import write_state

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


def test_the_notes_part_shows_the_index_of_what_reaches_the_step(services, step, section):
    from dplanner.modules.notes.log import MODULE_ID as NOTES_ID
    from dplanner.modules.notes.log import Note, write_log

    library = services.document
    project = library.project_of(step.id)
    earlier = Step(title="Set up CI", edges={"requires": []})
    AddNodeCommand(project.id, earlier).redo(library)
    library.set_edges(step.id, "requires", [earlier.id])
    keys = Note("N1", "handoff", "Keys in vault", body="Ask ops.", step=earlier.id)
    library.set_module_data(project.id, NOTES_ID, write_log([keys]))

    section.show_target(step.id)
    text = section.inherited_view.toPlainText()
    assert "## Notes so far" in text and "N1 · Keys in vault" in text
    assert "1 block" in section.inherited_part.summary.text()

    # A note edited while the tab is open reaches the pane without a reselect — and one
    # addressed to this step arrives in full.
    moved = Note(
        "N2", "handoff", "Keys moved", body="1Password.", step=earlier.id, for_steps=(step.id,)
    )
    library.set_module_data(project.id, NOTES_ID, write_log([keys, moved]))
    text = section.inherited_view.toPlainText()
    assert "## Notes for this step" in text and "1Password." in text
    assert "2 blocks" in section.inherited_part.summary.text()


def test_the_summaries_follow_the_text(services, step, section):
    section.show_target(step.id)
    assert section.step_part.summary.text() == "empty"
    section.edit.setPlainText("Ship it.")
    assert "chars" in section.step_part.summary.text()


# -- one field, two editors --------------------------------------------------------------------


def test_the_settings_tab_and_the_step_tab_edit_one_field_over_one_undo_stack(
    services, step, section, project_tab
):
    project = services.document.project_of(step.id)
    section.show_target(step.id)
    project_tab.show_target(project.id)

    project_tab.edit.setPlainText("House rules.")
    assert section.project_edit.toPlainText() == "House rules."

    services.undo.break_coalescing()  # Two bursts, two commands — the undo test needs both.
    cursor = section.project_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(" Amended.")
    assert project_tab.edit.toPlainText() == "House rules. Amended."

    services.undo.undo()
    assert project.module_text[MODULE_ID] == "House rules."
    assert project_tab.edit.toPlainText() == "House rules."


def test_the_project_tab_registers_into_project_settings(services):
    sections = services.project_settings.sections()
    assert any(s.id == "step_agent_instruction.project" for s in sections)


def settings_for(services, project):
    """*Project ▸ Settings…* on ``project``, the application's way: the module's one dialog."""
    module = next(m for m in services.modules if m.id == "projects")
    on = Context({SCOPE_SELECTION: (ContextNode(selection_uri("project", project.id)),)})
    services.actions.run("projects.settings", on)
    return module._dialog


def instruction_tab(dialog):
    from dplanner.modules.step_agent_instruction.section import ProjectInstructionSection

    return next(e for e in dialog.extensions if isinstance(e, ProjectInstructionSection))


def test_the_standing_instruction_typed_in_settings_is_one_undo_and_reaches_the_agent_tab(
    services, step, section
):
    from PySide6.QtTest import QTest

    from dplanner.planning.agent import write_state

    services.document.set_module_data(step.id, MODULE_ID, write_state(True))
    project = services.document.project_of(step.id)
    dialog = settings_for(services, project)
    tab = instruction_tab(dialog)
    QTest.keyClicks(tab.edit, "House rules.")
    assert project.module_text[MODULE_ID] == "House rules."
    section.show_target(step.id)
    assert section.project_edit.toPlainText() == "House rules."

    dialog.hide()  # Leaving the dialog seals the step the typing grew…
    dialog.show()
    QTest.keyClicks(tab.edit, " Amended.")  # …so the next visit's typing is a step of its own.
    services.undo.undo()
    assert section.project_edit.toPlainText() == "House rules."
    services.undo.undo()
    assert project.module_text.get(MODULE_ID, "") == ""
    assert section.project_edit.toPlainText() == ""


def test_typing_in_the_settings_agent_tab_survives_republishes_and_settings_again(services, step):
    """A model edit can republish the context mid-typing, and *Settings…* can be asked for
    again; neither re-aims the tab at the project it already shows, so the cursor stays."""
    from PySide6.QtTest import QTest

    project = services.document.project_of(step.id)
    tab = instruction_tab(settings_for(services, project))

    QTest.keyClicks(tab.edit, "hello world")
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    services.context.refresh()
    settings_for(services, project)
    assert tab.edit.toPlainText() == "hello world"
    assert project.module_text[MODULE_ID] == "hello world"
    assert tab.edit.textCursor().position() == len("hello world")


# -- the preview -------------------------------------------------------------------------------


def test_preview_is_enabled_on_an_agent_step_and_greyed_with_the_reason_off_one(
    services, step, section
):
    from dplanner.planning.agent import write_state

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


def test_the_settings_tab_pastes_into_the_project(services, step, project_tab):
    from dplanner.domain.assets import assets

    project_id = services.document.project_of(step.id).id
    project_tab.show_target(project_id)
    paste_image(project_tab.edit)
    names = assets(services.repo.files(project_id, "step_agent_instruction"))
    assert len(names) == 1
    assert project_tab.gallery is not None and project_tab.gallery._names == names
