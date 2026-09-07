"""Markdown structure, visible while the source stays plain text.

Every prose document in this application — a description, a note, a test body — is
markdown on disk, and the editors over them are ``QPlainTextEdit``s bound positionally
through :class:`TextBinding`. A rich-text editor (``setMarkdown``/``toMarkdown``) would
break that binding: it edits a *document tree* and writes back a normalised serialisation,
so a keystroke is no longer one small splice. A syntax highlighter is the middle way — the
text is exactly what is on disk, headings and lists just *look* like what they are.

Deliberately calm: weight and the palette's own ink at two strengths, no rainbow. A heading
is bold, structure markers (``#``, ``-``, ``1.``, ``>``) are the secondary ink so the eye
reads the content past them, and inline code is monospace. Colours are read from the
widget's palette at highlight time, so a theme change only needs :meth:`rehighlight` —
the hook every stored colour owes (`CLAUDE.md`'s palette rule).
"""

import re

from PySide6.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import QWidget

# The ~63 % secondary ink, as everywhere a painter has only the palette.
SECONDARY_ALPHA = 160

_HEADING = re.compile(r"^(#{1,6})\s+\S")
_LIST_MARKER = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+\S")
_QUOTE = re.compile(r"^(\s*>+)\s?")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_CODE = re.compile(r"`([^`\n]+)`")


class MarkdownHighlighter(QSyntaxHighlighter):
    """Headings, list markers, quotes, bold and inline code, in the palette's own ink."""

    def __init__(self, document: QTextDocument, palette_of: QWidget) -> None:
        super().__init__(document)
        # The palette is read through the widget on every pass rather than copied out,
        # so a rehighlight after a theme change needs no re-wiring here.
        self._palette_of = palette_of

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        secondary = QTextCharFormat()
        faded = self._palette_of.palette().text().color()
        faded.setAlpha(SECONDARY_ALPHA)
        secondary.setForeground(faded)

        bold = QTextCharFormat()
        bold.setFontWeight(QFont.Weight.Bold)

        if match := _HEADING.match(text):
            self.setFormat(0, len(text), bold)
            self.setFormat(0, len(match.group(1)), secondary)
        elif match := _LIST_MARKER.match(text):
            start = len(match.group(1))
            self.setFormat(start, len(match.group(2)), secondary)
        elif match := _QUOTE.match(text):
            self.setFormat(0, len(match.group(1)), secondary)

        for match in _BOLD.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), bold)
        for match in _CODE.finditer(text):
            code = QTextCharFormat()
            code.setFontFamilies(["monospace"])
            code.setForeground(faded)
            self.setFormat(match.start(), match.end() - match.start(), code)
