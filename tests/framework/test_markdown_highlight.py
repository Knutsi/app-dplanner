"""The markdown highlighter: structure visible, text untouched."""

import pytest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit

from dplanner.framework.markdown_highlight import MarkdownHighlighter


def formats_of(edit):
    """(start, length, weight) per format run in the first block."""
    block = edit.document().firstBlock()
    return [(r.start, r.length, r.format.fontWeight()) for r in block.layout().formats()]


@pytest.fixture
def highlighted(app):
    """Build an editor with the highlighter, and delete it in C++ order at teardown.

    Left to garbage collection, the document (and the highlighter parented to it) can be
    torn down after the wrapper the highlighter still points at — ``deleteLater`` plus one
    event-loop turn deletes the family in order instead.
    """
    edits = []

    def build(text):
        edit = QPlainTextEdit()
        MarkdownHighlighter(edit.document(), edit)
        edit.setPlainText(text)
        edits.append(edit)
        return edit

    yield build
    for edit in edits:
        edit.deleteLater()
    app.processEvents()


def test_a_heading_goes_bold_and_its_marker_fades(highlighted):
    edit = highlighted("## Setup")
    runs = formats_of(edit)
    assert any(weight == QFont.Weight.Bold for _s, _l, weight in runs)
    assert edit.toPlainText() == "## Setup"  # The text itself is never rewritten.


def test_a_list_marker_is_formatted_and_the_content_is_not(highlighted):
    edit = highlighted("- No flicker on render")
    runs = formats_of(edit)
    assert runs and runs[0][:2] == (0, 1)  # Exactly the "-".


def test_plain_prose_is_left_entirely_alone(highlighted):
    edit = highlighted("Open the list and look at it.")
    assert formats_of(edit) == []


def spans_of(edit, index=0):
    """(start, length, italic, monospace) per format run in block ``index``."""
    block = edit.document().findBlockByNumber(index)
    return [
        (r.start, r.length, r.format.fontItalic(), bool(r.format.fontFamilies()))
        for r in block.layout().formats()
    ]


def test_emphasis_leans_and_a_bold_pair_is_not_mistaken_for_it(highlighted):
    edit = highlighted("a *word* and **two words** here")
    leaning = [(s, length) for s, length, italic, _mono in spans_of(edit) if italic]
    assert leaning == [(2, 6)]  # Exactly "*word*", and nothing inside the bold pair.


def test_a_star_mid_word_leans_because_that_is_what_a_renderer_does_with_it(highlighted):
    """CommonMark opens emphasis on a single ``*`` mid-word — the thing that separates it
    from ``_``. The highlighter agreeing with the renderer is the whole point of it."""
    edit = highlighted("the a*b*c convention")
    assert [(s, length) for s, length, italic, _m in spans_of(edit) if italic] == [(5, 3)]


def test_a_fenced_block_is_monospace_to_its_closing_fence(highlighted):
    """The state a block leaves behind is the only way the next one knows it is inside
    something that opened three lines up — and getting it backwards makes *alternate*
    lines of an ordinary paragraph read as code, which is what this pins."""
    edit = highlighted("before\n```\ncode here\n```\nafter\nand more prose")
    monospace = [bool([run for run in spans_of(edit, n) if run[3]]) for n in range(6)]
    assert monospace == [False, True, True, True, False, False]
