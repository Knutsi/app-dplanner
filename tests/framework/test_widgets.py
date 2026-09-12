"""The shared widget helpers: an empty state trades places with what it stands in for, and
the caption and the note wear the panel's names."""

import pytest
from PySide6.QtWidgets import QLabel, QWidget

from dplanner.framework.widgets import EmptyState, caption, note


@pytest.fixture
def host(app):
    widget = QWidget()
    yield widget
    widget.deleteLater()


def test_say_trades_places_with_what_it_stands_in_for(host):
    content = QLabel("rows", host)
    empty = EmptyState(parent=host, stands_in_for=content)
    assert empty.isHidden() and not content.isHidden()
    empty.say("Nothing here yet")
    assert not empty.isHidden() and content.isHidden() and empty.text() == "Nothing here yet"
    empty.say("")
    assert empty.isHidden() and not content.isHidden()


def test_a_state_born_with_words_hides_its_content_from_the_start(host):
    content = QLabel("rows", host)
    empty = EmptyState("No rows", host, stands_in_for=content)
    assert not empty.isHidden() and content.isHidden()


def test_a_state_standing_in_for_nothing_only_shows_and_hides_itself(host):
    empty = EmptyState(parent=host)
    empty.say("Nothing")
    assert not empty.isHidden() and empty.stands_in_for is None


def test_the_caption_and_the_note_wear_the_panel_names(host):
    assert caption("Estimate", host).objectName() == "InspectorCaption"
    remark = note("3 pages changed at the source", host)
    assert remark.objectName() == "InspectorNote" and remark.wordWrap()
