"""``framework/dictation_verb.py``: the microphone on the strip over a bound editor — what
it says, where the words land, and that a session is one undo step."""

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QTextCursor
from tests.framework.fake_recorder import wait_for
from tests.framework.test_dictation_service import (
    HERE,
    QUIET,
    Batch,
    Live,
    batch_provider,
    live_provider,
)

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Step
from dplanner.framework.dictation import NO_PROVIDER, DictationService
from dplanner.framework.dictation_verb import DICTATING, GESTURE, KEYS, WORDS
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.text_dialog import ExpandedTextDialog

MODULE_ID = "step_description"
FOUND = {"python-fake": "/usr/bin/x", "python-quiet": "/usr/bin/y"}


def service_of(services, *providers, recorders=(HERE,), which=FOUND.get):
    return DictationService(
        providers, services.tasks, recorders=recorders, which=which, platform="linux"
    )


@pytest.fixture
def steps(services, make_project):
    project = make_project("Discovery")
    first, second = Step(title="Deploy"), Step(title="Verify")
    AddNodeCommand(project.id, first).redo(services.document)
    AddNodeCommand(project.id, second).redo(services.document)
    return first, second


@pytest.fixture
def section_for(app, services, steps):
    made: list[ProseSection] = []

    def build(dictation):
        def field_for(target_id):
            if not services.document.has(target_id):
                return None
            return ModuleTextField(services.document, target_id, MODULE_ID)

        section = ProseSection(field_for, services.undo, "Say it.", dictation=dictation)
        section.show_target(steps[0].id)
        made.append(section)
        return section

    yield build
    for section in made:
        section.dispose()
        section.deleteLater()


def pump(app, seconds=0.05):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def recorded(app, verb):
    """Wait until the recorder has handed over some samples: a clip a stop can act on."""
    wait_for(app, lambda: verb.dictation.bytes_recorded() > 0, what="the clip")


def dictated(app, section):
    """Press, let the recorder run, press again, and wait for the words."""
    verb = section.tools.dictation
    verb.toggle()
    recorded(app, verb)
    verb.toggle()
    wait_for(app, lambda: verb.dictation.state() == "idle", what="the dictation")


# -- the face ----------------------------------------------------------------------------------


def test_a_strip_without_a_service_has_no_microphone(app, section_for):
    section = section_for(None)
    assert section.tools.dictation is None
    assert all(action.text() != WORDS for action in section.tools.verbs())


def test_the_verb_is_greyed_with_the_reason_when_nothing_is_ready(services, section_for):
    section = section_for(service_of(services))  # A build with no providers.

    verb = section.tools.dictation
    assert verb is not None and not verb.action.isEnabled()
    assert verb.action.text() == f"{WORDS} — {NO_PROVIDER}"
    verb.toggle()  # A greyed verb starts nothing.
    assert verb.dictation.state() == "idle"


def test_the_verb_ungreys_on_config_changed_and_greys_on_a_read_only_editor(services, section_for):
    engine = Batch()
    provider = batch_provider(engine)
    made = service_of(services, provider, which=lambda _name: None)
    section = section_for(made)
    verb = section.tools.dictation

    assert not verb.action.isEnabled()
    made._which = FOUND.get  # The recorder appeared (installed while running).
    made.config_changed.emit()
    assert verb.action.isEnabled() and verb.action.text() == WORDS
    section.edit.setReadOnly(True)
    verb.refresh()
    assert not verb.action.isEnabled()


def test_the_key_is_a_widget_shortcut_on_the_editor_and_only_printed_on_the_strip(
    services, section_for
):
    section = section_for(service_of(services, batch_provider()))

    keys = [s for s in section.edit.findChildren(QShortcut) if s.key().toString() == KEYS]
    assert len(keys) == 1 and keys[0].context() == Qt.ShortcutContext.WidgetShortcut
    assert section.tools.dictation.action.shortcut().isEmpty()
    assert KEYS in section.tools.dictation.action.toolTip()


# -- batch ------------------------------------------------------------------------------------


def test_the_transcript_lands_at_the_caret_as_one_undo_step(app, services, steps, section_for):
    section = section_for(service_of(services, batch_provider(Batch("hello world"))))
    section.edit.textCursor().insertText("Before ")
    services.undo.break_coalescing()

    dictated(app, section)

    assert services.document.text(steps[0].id, MODULE_ID) == "Before hello world"
    services.undo.undo()
    assert services.document.text(steps[0].id, MODULE_ID) == "Before "
    services.undo.redo()
    section.edit.textCursor().insertText(" after")  # Typing after starts its own step.
    services.undo.undo()
    assert services.document.text(steps[0].id, MODULE_ID) == "Before hello world"


def test_the_verb_is_checked_while_recording_and_spins_while_transcribing(
    app, services, section_for
):
    engine = Batch("said", delay=0.3)
    section = section_for(service_of(services, batch_provider(engine)))
    verb = section.tools.dictation

    verb.toggle()
    assert verb.action.isChecked() and section.edit.property(DICTATING) is True
    recorded(app, verb)
    verb.toggle()
    assert not verb.action.isChecked() and verb._spinner.is_spinning()
    assert section.edit.property(DICTATING) is True
    wait_for(app, lambda: verb.dictation.state() == "idle")

    assert not verb._spinner.is_spinning() and section.edit.property(DICTATING) is False
    assert verb.action.isEnabled()


def test_a_silent_clip_lands_nothing_and_says_so(app, services, steps, section_for):
    section = section_for(service_of(services, batch_provider(), recorders=(QUIET,)))

    dictated(app, section)

    assert services.document.text(steps[0].id, MODULE_ID) == ""


def test_a_retargeted_section_drops_a_transcript_in_flight(app, services, steps, section_for):
    engine = Batch("late words", delay=0.3)
    section = section_for(service_of(services, batch_provider(engine)))
    verb = section.tools.dictation

    verb.toggle()
    recorded(app, verb)
    verb.toggle()
    section.show_target(steps[1].id)  # The panel moved on mid-transcription.
    wait_for(app, lambda: not verb.dictation.service.is_busy(), what="the abandoned task")
    pump(app)

    assert services.document.text(steps[0].id, MODULE_ID) == ""
    assert services.document.text(steps[1].id, MODULE_ID) == ""
    assert verb.dictation.state() == "idle" and verb.action.isEnabled()


def test_a_disposed_dialog_abandons_its_dictation(app, services, steps):
    made = service_of(services, batch_provider(Batch("late", delay=0.3)))
    dialog = ExpandedTextDialog.over_field(
        ModuleTextField(services.document, steps[0].id, MODULE_ID),
        services.undo,
        title="Description",
        dictation=made,
    )
    verb = dialog.tools.dictation
    assert verb is not None

    verb.toggle()
    recorded(app, verb)
    verb.toggle()
    dialog.dispose()
    wait_for(app, lambda: not made.is_busy(), what="the abandoned task")
    pump(app)

    assert services.document.text(steps[0].id, MODULE_ID) == ""
    dialog.deleteLater()


# -- live -------------------------------------------------------------------------------------


def test_live_words_land_as_spoken_and_the_session_is_one_undo_step(
    app, services, steps, section_for
):
    engine = Live()
    section = section_for(service_of(services, live_provider(engine)))
    section.edit.textCursor().insertText("Lead: ")
    services.undo.break_coalescing()
    verb = section.tools.dictation

    verb.toggle()
    wait_for(app, lambda: "word3" in section.edit.toPlainText(), what="the deltas")
    assert services.document.text(steps[0].id, MODULE_ID) == "Lead: word1 word2 word3 "
    assert services.undo.gesture_open() and not services.undo.can_undo()
    verb.toggle()
    wait_for(app, lambda: verb.dictation.state() == "idle", what="the finish")

    # The completed transcript replaced the deltas that led to it, with a space after.
    assert services.document.text(steps[0].id, MODULE_ID) == "Lead: the final words "
    assert not services.undo.gesture_open()
    assert services.undo.undo_text() == GESTURE
    services.undo.undo()
    assert services.document.text(steps[0].id, MODULE_ID) == "Lead: "
    services.undo.redo()
    assert services.document.text(steps[0].id, MODULE_ID) == "Lead: the final words "


def test_live_words_follow_their_own_cursor_not_the_moved_caret(app, services, steps, section_for):
    engine = Live()
    section = section_for(service_of(services, live_provider(engine)))
    section.edit.setPlainText("one two")
    cursor = section.edit.textCursor()
    cursor.setPosition(3)  # After "one".
    section.edit.setTextCursor(cursor)
    services.undo.break_coalescing()
    verb = section.tools.dictation

    verb.toggle()
    wait_for(app, lambda: "word1" in section.edit.toPlainText())
    moved = section.edit.textCursor()
    moved.movePosition(QTextCursor.MoveOperation.Start)
    section.edit.setTextCursor(moved)  # The person clicked away to read the top.
    wait_for(app, lambda: "word3" in section.edit.toPlainText())
    verb.toggle()
    wait_for(app, lambda: verb.dictation.state() == "idle")

    assert section.edit.toPlainText() == "onethe final words  two"


def test_abandoning_a_live_session_closes_the_gesture(app, services, steps, section_for):
    engine = Live()
    section = section_for(service_of(services, live_provider(engine)))
    verb = section.tools.dictation

    verb.toggle()
    wait_for(app, lambda: "word2" in section.edit.toPlainText())
    assert services.undo.gesture_open()
    section.show_target(steps[1].id)
    pump(app)

    assert not services.undo.gesture_open()
    assert services.undo.undo_text() == GESTURE  # What landed before the move stays a step.
