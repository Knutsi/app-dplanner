"""The Settings dialog on the frame: Close alone, a tree whose folders are headings, and
a page built once inside a scroller of its own."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.settings_registry import (
    SettingsSection,
    SettingsSectionRegistry,
    settings_page,
)
from dplanner.modules.settings.dialog import SettingsDialog


def page_factory(name):
    built = []

    def build(parent):
        page, _layout = settings_page(parent)
        page.setObjectName(name)
        built.append(page)
        return page

    build.built = built  # type: ignore[attr-defined]
    return build


@pytest.fixture
def dialog(app):
    registry = SettingsSectionRegistry()
    registry.register(SettingsSection("a.one", ("Appearance",), page_factory("PageOne")))
    registry.register(SettingsSection("b.two", ("Providers", "OpenAI"), page_factory("PageTwo")))
    registry.register(
        SettingsSection("b.three", ("Providers", "Anthropic"), page_factory("PageThree"))
    )
    registry.register(SettingsSection("c.four", ("Startup",), page_factory("PageFour")))
    made = SettingsDialog(registry)
    yield made
    made.deleteLater()


def test_close_alone_and_the_first_page_open(dialog):
    assert issubclass(SettingsDialog, DialogFrame) and dialog.primary() is None
    assert [b.text() for b in dialog.footer_buttons()] == ["Close"]
    page = dialog.current_page()
    assert page is not None and page.objectName() == "PageOne"


def test_a_page_is_built_once_inside_a_scroller_the_dialog_insets(dialog):
    dialog.show_section("b.two")
    shown = dialog._pane.currentWidget()
    assert isinstance(shown, QScrollArea)
    page = shown.widget()
    assert page is not None and page.objectName() == "PageTwo"
    column = page.layout()
    assert column is not None and column.contentsMargins().left() == 0  # No margin of its own.
    dialog.show_section("a.one")
    dialog.show_section("b.two")
    assert dialog._pane.currentWidget() is shown  # Built once, then reused.


def test_a_folder_is_a_heading_and_a_click_on_it_lands_on_its_first_page(dialog):
    folder = dialog._tree.topLevelItem(1)
    assert folder.text(0) == "Providers" and folder.data(0, Qt.ItemDataRole.UserRole) is None
    assert not (folder.flags() & Qt.ItemFlag.ItemIsSelectable)
    assert folder.font(0).bold()
    dialog._tree.setCurrentItem(folder)
    page = dialog.current_page()
    assert page is not None and page.objectName() == "PageTwo"


def test_the_arrows_step_over_a_heading_and_the_tree_has_focus_on_open(app, dialog):
    dialog.show()
    app.processEvents()
    try:
        assert dialog.focusWidget() is dialog._tree
        dialog.show_section("b.two")
        QTest.keyClick(dialog._tree, Qt.Key.Key_Up)
        page = dialog.current_page()
        assert page is not None and page.objectName() == "PageOne"
        QTest.keyClick(dialog._tree, Qt.Key.Key_Down)
        page = dialog.current_page()
        assert page is not None and page.objectName() == "PageTwo"
    finally:
        dialog.hide()
