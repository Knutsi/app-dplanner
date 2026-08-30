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
