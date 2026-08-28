"""The shell's tab verbs: what View's Tabs submenu offers, and what each entry does.

Tested as pure functions of a constructed ``Context`` and through ``actions.run``, like every
other verb — which is the property that makes the tab bar's right-click menu correct for
free, since it is the same registry read through the same context.
"""

import pytest

CLOSE_TAB = "appshell.close_tab"
CLOSE_OTHERS = "appshell.close_other_tabs"
CLOSE_RIGHT = "appshell.close_tabs_right"
CLOSE_ALL = "appshell.close_all_tabs"


@pytest.fixture
def projects(make_project):
    return [make_project(title) for title in ("Discovery", "Build", "Ship")]


def open_all(services, projects):
    return [services.tabs.open("project", project.id) for project in projects]


def state(services, action_id):
    return services.actions.spec(action_id).state(services.context.current())


def run(services, action_id):
    services.actions.run(action_id, services.context.current())


def titles(services):
    return [activity.title for activity in services.tabs.activities()]


# -- what the menu offers ------------------------------------------------------------------


def test_the_tab_verbs_live_in_the_view_menus_tabs_submenu(services):
    """The placement the tab bar's right-click depends on: show_tab_menu asks build_menu for
    View's Tabs submenu, so a spec that drifts elsewhere silently leaves that popup."""
    for action_id in ("appshell.move_tab_right", "appshell.move_tab_left",
                      CLOSE_TAB, CLOSE_OTHERS, CLOSE_RIGHT, CLOSE_ALL):
        spec = services.actions.spec(action_id)
        assert (spec.menu, spec.group, spec.submenu) == ("View", "tabs", "Tabs")


def test_every_tab_verb_is_off_in_an_empty_window(services):
    """The Tabs submenu is honest about a window with nothing in it rather than offering
    four entries that do nothing."""
    for action_id in (CLOSE_TAB, CLOSE_OTHERS, CLOSE_RIGHT, CLOSE_ALL):
        assert not state(services, action_id).enabled


def test_one_tab_can_be_closed_and_nothing_else(services, projects):
    open_all(services, projects[:1])

    assert state(services, CLOSE_TAB).enabled
    assert state(services, CLOSE_ALL).enabled
    assert not state(services, CLOSE_OTHERS).enabled
    assert not state(services, CLOSE_RIGHT).enabled


# -- what the entries do -------------------------------------------------------------------


def test_close_other_tabs_keeps_the_one_you_are_on(services, projects):
    tabs = open_all(services, projects)
    services.tabs.focus(tabs[1])

    run(services, CLOSE_OTHERS)
    assert titles(services) == ["Build"]


def test_close_tabs_to_the_right_leaves_the_ones_before(services, projects):
    tabs = open_all(services, projects)
    services.tabs.focus(tabs[0])

    assert state(services, CLOSE_RIGHT).enabled
    run(services, CLOSE_RIGHT)
    assert titles(services) == ["Discovery"]


def test_close_tabs_to_the_right_means_this_group(services, projects):
    """ "Right" is a fact about one tab bar. A tab sent to the next group is to the right on
    screen and not in this bar, so it survives."""
    tabs = open_all(services, projects)
    services.tabs.focus(tabs[2])
    services.tabs.move_current_right()
    services.tabs.focus(tabs[0])

    run(services, CLOSE_RIGHT)
    assert sorted(titles(services)) == ["Discovery", "Ship"]


def test_close_all_tabs_empties_the_window(services, projects):
    open_all(services, projects)

    run(services, CLOSE_ALL)
    assert titles(services) == []
    assert services.tabs.current_activity() is None


def test_the_area_toggles_live_in_views_areas_group(services):
    """The placement and shortcuts the side-panel collapse depends on: View's own group
    ahead of the per-panel checkmarks, and the keys the palette renders."""
    from dplanner.framework.panels import PanelArea

    for action_id, shortcut in (
        ("appshell.toggle_left_panels", "Ctrl+B"),
        ("appshell.toggle_right_panels", "Ctrl+Alt+B"),
    ):
        spec = services.actions.spec(action_id)
        assert (spec.menu, spec.group, spec.shortcut) == ("View", "areas", shortcut)
    assert not services.window.is_area_collapsed(PanelArea.LEFT)


def test_toggling_an_area_flips_its_checkmark(services):
    toggle = "appshell.toggle_left_panels"
    assert state(services, toggle).checked

    run(services, toggle)
    assert not state(services, toggle).checked
    run(services, toggle)
    assert state(services, toggle).checked


def test_the_move_shortcut_yields_to_word_selection_in_a_text_editor(session, projects):
    """Ctrl+Shift+Right moves the tab — except in an editable field, where it must keep
    selecting the next word. Qt's text controls claim the key through ShortcutOverride, and
    this pins that down: a future shortcut that editors do *not* claim would eat a standard
    editing key application-wide, which is the trap CLAUDE.md's canvas-keymap rule is about.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPlainTextEdit

    services = session.services
    session.window.show()
    open_all(services, projects[:2])
    ctrl_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier

    QTest.keyClick(session.window, Qt.Key.Key_Right, ctrl_shift)
    assert services.tabs.group_count() == 2  # The shortcut fired: the window split.

    editor = QPlainTextEdit(session.window)
    editor.setPlainText("two words")
    editor.show()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_Right, ctrl_shift)
    assert services.tabs.group_count() == 2  # Unchanged: the editor claimed the key…
    assert editor.textCursor().selectedText()  # …and spent it on selecting a word.
