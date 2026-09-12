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


def test_confirm_is_a_frame_whose_default_never_discards(app, monkeypatch):
    from PySide6.QtWidgets import QDialog, QPushButton

    from dplanner.framework.dialog import DialogFrame
    from dplanner.framework.widgets import confirm

    seen = []

    def fake_exec(self):
        seen.append(self)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(DialogFrame, "exec", fake_exec)
    assert confirm(None, "Delete Layout", "Delete the layout “Wide”?", verb="Delete") is False
    (dialog,) = seen
    assert dialog.title_label.text() == "Delete Layout"
    assert dialog.lead_label.text() == "Delete the layout “Wide”?"
    assert dialog.findChild(QPushButton, "PrimaryButton") is None
    names = [b.text() for b in dialog.footer_buttons()]
    assert names == ["Delete", "Cancel"]
    assert [b.isDefault() for b in dialog.footer_buttons()] == [False, True]
    monkeypatch.setattr(DialogFrame, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    assert confirm(None, "Delete Layout", "Delete it?") is True
