"""The markdown strip: what each verb does to a selection, and what it must never do.

The transforms are pure and are tested as such — a string in, a string and a selection
out. The widget tests are the three promises a strip over a caret makes: one splice per
press (so a bound host pushes one small command rather than the whole document), the
caret stays where the verb was aimed, and a key printed in a tooltip is not a key claimed
from the window.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from dplanner.framework.markdown_toolbar import (
    MarkdownToolbar,
    heading,
    line_prefix,
    link,
    table,
    wrap,
)
from dplanner.framework.prose_edit import ProseEdit


def applied(text: str, start: int, end: int, transform) -> tuple[str, str]:
    """The document after the splice, and what it leaves selected."""
    splice = transform(text, start, end)
    after = text[: splice.start] + splice.text + text[splice.end :]
    return after, after[splice.select[0] : splice.select[1]]


# -- wrapping a span ---------------------------------------------------------------------------


def test_a_selection_is_wrapped_and_stays_selected():
    after, chosen = applied("one two three", 4, 7, lambda t, s, e: wrap(t, s, e, "**"))
    assert after == "one **two** three"
    assert chosen == "two"  # A second press acts on the same words.


def test_wrapping_nothing_puts_the_caret_between_the_fences():
    after, chosen = applied("one ", 4, 4, lambda t, s, e: wrap(t, s, e, "**"))
    assert after == "one ****" and chosen == ""
    splice = wrap("one ", 4, 4, "**")
    assert splice.select == (6, 6)


@pytest.mark.parametrize(
    ("start", "end"),
    [(4, 11), (6, 9)],
    ids=["marks inside the selection", "selection between the marks"],
)
def test_wrapping_something_already_wrapped_unwraps_it(start, end):
    after, chosen = applied("one **two** three", start, end, lambda t, s, e: wrap(t, s, e, "**"))
    assert after == "one two three" and chosen == "two"


def test_inline_code_is_a_single_backtick():
    after, _ = applied("say hello now", 4, 9, lambda t, s, e: wrap(t, s, e, "`"))
    assert after == "say `hello` now"


# -- marking whole lines -----------------------------------------------------------------------


def test_a_marker_reaches_every_line_the_selection_touches():
    after, chosen = applied(
        "first\nsecond\nthird", 2, 8, lambda t, s, e: line_prefix(t, s, e, "- ")
    )
    assert after == "- first\n- second\nthird"
    assert chosen == "- first\n- second"


def test_a_line_that_already_carries_the_marker_loses_it():
    after, _ = applied("- first\n- second", 0, 10, lambda t, s, e: line_prefix(t, s, e, "- "))
    assert after == "first\nsecond"


def test_a_numbered_list_counts_down_the_run():
    after, _ = applied("a\nb\nc", 0, 5, lambda t, s, e: line_prefix(t, s, e, "1. "))
    assert after == "1. a\n2. b\n3. c"


def test_one_mark_to_a_line_replaces_another_rather_than_stacking():
    after, _ = applied("- a bullet", 2, 2, lambda t, s, e: heading(t, s, e, 2))
    assert after == "## a bullet"
    back, _ = applied("## a bullet", 3, 3, lambda t, s, e: line_prefix(t, s, e, "- "))
    assert back == "- a bullet"


def test_a_heading_at_the_same_level_toggles_off_and_another_level_replaces_it():
    same, _ = applied("## Auth", 3, 3, lambda t, s, e: heading(t, s, e, 2))
    assert same == "Auth"
    other, _ = applied("## Auth", 3, 3, lambda t, s, e: heading(t, s, e, 1))
    assert other == "# Auth"


def test_an_indent_survives_the_marker():
    after, _ = applied("    nested", 5, 5, lambda t, s, e: line_prefix(t, s, e, "- "))
    assert after == "    - nested"


def test_a_blank_line_inside_the_selection_is_left_alone():
    after, _ = applied("a\n\nb", 0, 4, lambda t, s, e: line_prefix(t, s, e, "> "))
    assert after == "> a\n\n> b"


# -- inserting ---------------------------------------------------------------------------------


def test_a_link_selects_its_address_so_the_next_thing_typed_is_the_address():
    after, chosen = applied("see the guide", 8, 13, link)
    assert after == "see the [guide](url)" and chosen == "url"


def test_a_table_lands_in_a_block_of_its_own_with_its_first_heading_selected():
    after, chosen = applied("A paragraph.", 12, 12, table)
    assert after.startswith("A paragraph.\n\n| Column | Column |")
    assert chosen == "Column"
    assert applied("", 0, 0, table)[0].startswith("| Column |")


# -- the strip over a real editor ---------------------------------------------------------------


@pytest.fixture
def edit(app):
    widget = ProseEdit()
    widget.setPlainText("one two three")
    yield widget
    widget.deleteLater()


@pytest.fixture
def bar(edit):
    widget = MarkdownToolbar(edit)
    yield widget
    widget.dispose()
    widget.deleteLater()


def select(edit, start, end):
    cursor = edit.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cursor)


def press(bar, words):
    action = next(a for a in bar.verbs() if a.text() == words)
    action.trigger()
    return action


def test_a_verb_is_one_splice_naming_only_what_moved(edit, bar):
    """Two operations inside an edit block collapse into one `contentsChange` naming the
    whole document, which a bound host would push as a command carrying it twice."""
    changes = []
    edit.document().contentsChange.connect(
        lambda pos, removed, added: changes.append((pos, removed, added))
    )
    select(edit, 4, 7)
    press(bar, "Bold")
    assert edit.toPlainText() == "one **two** three"
    assert changes == [(4, 3, 7)]


def test_pressing_a_verb_does_not_move_the_caret_away_from_it(edit, bar):
    """A focusable button would take focus on the press and the verb would land somewhere
    else — which is why every button on the strip is NoFocus."""
    from PySide6.QtWidgets import QToolButton

    buttons = bar.findChildren(QToolButton)
    assert len(buttons) > len(bar.verbs())  # Every verb, and the … button beside them.
    assert {button.focusPolicy() for button in buttons} == {Qt.FocusPolicy.NoFocus}
    select(edit, 4, 7)
    press(bar, "Italic")
    assert edit.textCursor().selectedText() == "two"


def test_a_key_is_printed_in_the_tooltip_and_never_claimed_from_the_window(bar):
    """A strip lives in a window, so a shortcut on its own action reaches every text field
    in that window. The key belongs to the editor, at WidgetShortcut."""
    bold = next(a for a in bar.verbs() if a.text() == "Bold")
    assert "Ctrl+B" in bold.toolTip()
    assert bold.shortcut().isEmpty()


def test_the_keys_reach_the_editor_and_nowhere_else(edit, bar):
    from PySide6.QtGui import QShortcut

    keyed = {s.key().toString(): s.context() for s in edit.findChildren(QShortcut)}
    assert keyed["Ctrl+B"] == Qt.ShortcutContext.WidgetShortcut
    assert set(keyed) == {"Ctrl+B", "Ctrl+I", "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+Shift+K"}


def test_a_read_only_editor_takes_no_marks(edit, bar):
    edit.setReadOnly(True)
    select(edit, 4, 7)
    press(bar, "Bold")
    assert edit.toPlainText() == "one two three"
