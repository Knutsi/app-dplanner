"""The shared widget helpers: an empty state trades places with what it stands in for, the
caption and the note wear the panel's names, a form block joins its layout before it is
filled, and a plain button's glyph follows the theme."""

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from dplanner.framework.widgets import EmptyState, GlyphButton, block, caption, note, quiet
from dplanner.theme import apply_theme
from dplanner.theme.icons import refresh_icon
from dplanner.theme.themes import DARK, LIGHT
from dplanner.theme.tokens import CAPTION_GAP


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
    assert dialog.windowTitle() == "Delete Layout"
    asked = dialog.findChild(QLabel, "DialogQuestion")
    assert asked is not None and asked.text() == "Delete the layout “Wide”?"
    assert dialog.findChild(QPushButton, "PrimaryButton") is None
    names = [b.text() for b in dialog.footer_buttons()]
    assert names == ["Delete", "Cancel"]
    assert [b.isDefault() for b in dialog.footer_buttons()] == [False, True]
    monkeypatch.setattr(DialogFrame, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    assert confirm(None, "Delete Layout", "Delete it?") is True


def test_the_empty_state_line_is_a_point_smaller(host):
    empty = EmptyState("Nothing", host)
    assert empty.label.font().pointSizeF() == host.font().pointSizeF() - 1


def test_notice_is_a_frame_with_one_close_and_no_primary(app, monkeypatch):
    from PySide6.QtWidgets import QDialog, QPushButton

    from dplanner.framework.dialog import DialogFrame
    from dplanner.framework.widgets import notice

    seen = []

    def fake_exec(self):
        seen.append(self)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(DialogFrame, "exec", fake_exec)
    notice(None, "Move Plan", "The plan moved, but the checkout stayed where it was.")
    (dialog,) = seen
    assert dialog.windowTitle() == "Move Plan"
    said = dialog.findChild(QLabel, "DialogQuestion")
    assert said is not None and said.text().startswith("The plan moved") and said.wordWrap()
    assert dialog.findChild(QPushButton, "PrimaryButton") is None
    assert [b.text() for b in dialog.footer_buttons()] == ["Close"]
    assert dialog.footer_buttons()[0].isDefault()


def test_a_block_joins_its_layout_before_it_is_filled_and_stacks_at_the_caption_gap(host):
    """A parentless layout given widgets first leaves QWidgetItem wrappers alive on the
    Python side — the shape the boundary collector crashes on (CLAUDE.md)."""
    column = QVBoxLayout(host)
    head = caption("Model", host)
    field = QLabel("gpt", host)
    made = block(column, head, field)
    assert made.parent() is column or column.indexOf(made) >= 0
    assert made.spacing() == CAPTION_GAP
    assert made.indexOf(head) == 0 and made.indexOf(field) == 1


def test_a_glyph_button_re_inks_on_a_palette_change(themed):
    apply_theme(themed, DARK)
    button = GlyphButton("Refresh", refresh_icon, tip="Fetch the account's models")
    try:
        assert not button.icon().isNull() and button.toolTip() == "Fetch the account's models"
        before = button.icon().cacheKey()
        apply_theme(themed, LIGHT)
        # A theme change reaches a widget as a PaletteChange; the offscreen platform
        # delivers it on the next event round.
        themed.sendEvent(button, QEvent(QEvent.Type.PaletteChange))
        assert button.icon().cacheKey() != before
    finally:
        button.deleteLater()


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=("dark", "light"))
def test_a_quiet_verb_wears_the_footer_look_and_a_restyled_primary_still_the_accent(themed, theme):
    """The property rule gives a body verb the footer's ground and loses to a rule that
    names the widget — which is what a `#DialogBody QPushButton` rule could not do."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QPushButton

    apply_theme(themed, theme)
    host = QWidget()
    column = QVBoxLayout(host)
    verb = quiet(QPushButton("Keep it here", host))
    offer = quiet(QPushButton("Set up a plan repository…", host))
    offer.setObjectName("PrimaryButton")
    column.addWidget(verb)
    column.addWidget(offer)
    host.show()
    themed.processEvents()
    try:
        image = host.grab().toImage()

        def inside(button):
            return button.mapTo(host, QPoint(4, button.height() // 2))

        assert image.pixelColor(inside(verb)) == QColor(theme.bg_overlay)
        assert image.pixelColor(inside(offer)) == QColor(theme.accent)
        assert GlyphButton("Refresh", refresh_icon, host).property("quiet") is True
    finally:
        host.deleteLater()


def test_a_number_box_prints_a_number_the_way_a_person_writes_it(app):
    from dplanner.framework.widgets import NumberBox

    box = NumberBox()
    box.setDecimals(2)
    try:
        assert [box.textFromValue(value) for value in (0.25, 0.5, 3.0)] == ["0.25", "0.5", "3"]
    finally:
        box.deleteLater()


def test_a_wrapped_tooltip_is_rich_text_so_qt_wraps_it_at_all(app):
    from dplanner.framework.widgets import wrapped_tooltip

    # QTipLabel takes its word wrap from `mightBeRichText`, so a plain tooltip is laid on
    # one endless line: markup is not decoration here, it is the whole mechanism.
    found = wrapped_tooltip("a sentence long enough to need a second line")
    assert found.startswith("<div") and found.endswith("</div>")


def test_a_wrapped_tooltip_escapes_the_prose_it_carries(app):
    from dplanner.framework.widgets import wrapped_tooltip

    # The text is somebody's quoted passage; a stray `<` must not eat the rest of it.
    assert "&lt;b&gt;" in wrapped_tooltip("a <b> tag")
    assert "<br>" in wrapped_tooltip("one\ntwo")


def test_nothing_to_say_is_no_tooltip_rather_than_an_empty_box(app):
    from dplanner.framework.widgets import wrapped_tooltip

    assert wrapped_tooltip("") == "" and wrapped_tooltip("   \n ") == ""
