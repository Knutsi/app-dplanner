"""The toolbar primitive: verbs as glyphs with their words in tooltips, what no longer fits
folded into a … menu as glyph and words, a widget hidden rather than listed, one height."""

import pytest
from PySide6.QtWidgets import QComboBox, QWidget

from dplanner.framework.toolbar import MORE, Toolbar
from dplanner.theme.icons import plus_icon, refresh_icon, trash_icon


@pytest.fixture
def host(app):
    widget = QWidget()
    yield widget
    widget.deleteLater()


def strip(host, app):
    bar = Toolbar(host)
    ran: list[str] = []
    bar.add_verb("Add Step", plus_icon, lambda: ran.append("add"), shortcut="Ctrl+N")
    bar.add_verb("Delete", trash_icon, lambda: ran.append("delete"))
    bar.add_divider()
    combo = QComboBox()
    combo.addItems(["All steps", "Milestones"])
    bar.add_widget(combo)
    bar.add_divider()
    bar.add_verb("Refresh", refresh_icon, lambda: ran.append("refresh"))
    bar.add_verb("Empty", refresh_icon, lambda: ran.append("empty"), checkable=True)
    host.resize(900, 60)
    host.show()
    app.processEvents()
    return bar, combo, ran


def test_a_verb_is_a_glyph_whose_words_and_shortcut_are_its_tooltip(host, app):
    bar, _combo, ran = strip(host, app)
    add, delete, *_ = bar.verbs()
    assert not add.icon().isNull() and add.text() == "Add Step"
    assert add.toolTip().startswith("Add Step") and "N" in add.toolTip()
    assert delete.toolTip() == "Delete"
    delete.setText("Delete 3 Steps")
    assert delete.toolTip() == "Delete 3 Steps"
    add.trigger()
    assert ran == ["add"]


def test_everything_fits_on_a_wide_strip_and_the_more_button_is_hidden(host, app):
    bar, combo, _ran = strip(host, app)
    bar.resize(800, bar.height())
    assert bar.hidden_items() == [] and bar._more.isHidden()
    assert not combo.isHidden()


def test_a_narrow_strip_folds_the_trailing_verbs_into_the_more_menu(host, app):
    bar, combo, ran = strip(host, app)
    bar.resize(120, bar.height())
    app.processEvents()
    assert not bar._more.isHidden() and bar._more.text() == MORE
    hidden = [item.action.text() for item in bar.hidden_items() if item.action is not None]
    assert "Empty" in hidden and "Refresh" in hidden
    assert combo.isHidden()  # A widget never enters the menu; it hides.
    bar._fill_more()
    listed = [action.text() for action in bar._menu.actions() if not action.isSeparator()]
    assert listed == hidden and all(
        not a.icon().isNull() for a in bar._menu.actions() if not a.isSeparator()
    )
    bar._menu.actions()[-1].trigger()
    assert ran == ["empty"]
    bar.resize(800, bar.height())
    app.processEvents()
    assert bar.hidden_items() == [] and not combo.isHidden()


def test_a_divider_never_ends_what_is_shown(host, app):
    bar, _combo, _ran = strip(host, app)
    bar.resize(200, bar.height())
    app.processEvents()
    shown = [item for item in bar._items if not item.widget.isHidden()]
    assert shown and not shown[-1].divider and not shown[0].divider


def test_a_checkable_verb_toggles_and_the_strip_asks_for_only_the_more_button(host, app):
    bar, _combo, _ran = strip(host, app)
    empty = bar.verbs()[-1]
    empty.trigger()
    assert empty.isChecked()
    assert bar.minimumSizeHint().width() == bar._more.sizeHint().width()


def test_every_control_on_a_strip_is_one_height(themed, app):
    from dplanner.theme import apply_theme
    from dplanner.theme.themes import DARK

    apply_theme(themed, DARK)
    host = QWidget()
    bar = Toolbar(host)
    bar.add_verb("Add Step", plus_icon, lambda: None)
    combo = QComboBox()
    combo.addItems(["All steps"])
    bar.add_widget(combo)
    host.resize(600, 60)
    host.show()
    app.processEvents()
    try:
        from dplanner.theme.tokens import CONTROL_HEIGHT

        button = bar._items[0].widget
        assert button.height() == combo.height() == CONTROL_HEIGHT
        assert bar._more.minimumHeight() == bar._more.maximumHeight() == CONTROL_HEIGHT
    finally:
        host.deleteLater()
