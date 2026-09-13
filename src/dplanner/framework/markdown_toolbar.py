"""A strip of markdown verbs over a :class:`~dplanner.framework.prose_edit.ProseEdit`.

Every prose document in this application is markdown kept as plain text
(:mod:`.markdown_highlight` has the reason), which leaves the marks themselves to be
typed. Most of them are two characters and nobody minds; `**` around a phrase already
selected, a `- ` down eleven lines, a table's pipes and dashes are the ones people stop
writing rather than type. So the marks become verbs, and the verbs become a strip.

**A verb is one splice, and that is not a detail.** Qt reports a `contentsChange` per
edit *block*: two operations inside one `beginEditBlock` collapse into a single signal
that names the whole document, so a :class:`~dplanner.framework.text_binding.TextBinding`
host would push an `EditTextCommand` carrying the document twice for a bold. One
contiguous replacement instead reports exactly the span that moved. Every verb here is
therefore a pure :class:`Splice` — start, end, the text that replaces them, and where the
selection lands — computed from the document's text and applied in one `insertText`.

**Where the selection lands is the design.** A verb leaves selected whatever a second
press of the same verb would act on: Bold leaves the bolded words, Heading 2 leaves the
lines, Link leaves `url` so the next thing you type is the address. With nothing selected
a wrap puts the caret between its fences, so Ctrl+B and then typing works the way it does
everywhere else.

**The strip never takes focus.** `Toolbar` gives every button `NoFocus` already; without
it a press would move the caret out from under the verb it was aimed at. For the same
reason the keys are `QShortcut`s on the *editor* at `WidgetShortcut` and never
`QAction` shortcuts on the strip, which is `CLAUDE.md`'s rule about a bare key on a
menu-bar action reaching every field in the window.

**Dense, not banded.** DESIGN.md maps a tool palette to `Toolbar.add_group`, and a banded
strip's square buttons put these twelve verbs at roughly 450 px — so in the 360 px dock
every prose editor lives in, *Insert* would fold into the `…` on every surface in the
application. Dense seats them in about 330 px. It is the aspect bar's argument with the
same numbers: a strip that answers a question about the thing on screen stops answering
it when it folds, and a formatting palette that is never all there is not a palette.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import QWidget

from dplanner.framework.dictation import DictationService
from dplanner.framework.dictation_verb import DictationVerb
from dplanner.framework.prose_edit import ProseEdit
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.undo import UndoService
from dplanner.theme.icons import (
    bold_icon,
    bullet_list_icon,
    code_icon,
    heading_icon,
    image_icon,
    italic_icon,
    link_icon,
    list_icon,
    quote_icon,
    table_icon,
)

# A line's existing block mark, so a verb can replace one with another rather than stack
# them: a heading, a bullet, a number, a quote. The indent is kept — a list nests.
_BLOCK = re.compile(r"^(\s*)(#{1,6} |[-*+] |\d{1,9}[.)] |> )?")
_HEADING = re.compile(r"^(\s*)(#{1,6}) ")

TABLE = "| Column | Column |\n| --- | --- |\n|  |  |"
LINK_PLACEHOLDER = "url"


@dataclass(frozen=True)
class Splice:
    """One contiguous replacement, in document offsets, and what it leaves selected."""

    start: int
    end: int
    text: str
    select: tuple[int, int]


def wrap(text: str, start: int, end: int, fence: str) -> Splice:
    """Put ``fence`` either side of ``text[start:end]``, or take it away again.

    Already fenced counts both ways round — the marks inside the selection, and the
    selection sitting between marks it does not include — because both are what a second
    press means and neither is what a person would call "not bold yet".
    """
    chosen = text[start:end]
    width = len(fence)
    if chosen.startswith(fence) and chosen.endswith(fence) and len(chosen) >= 2 * width:
        bare = chosen[width:-width]
        return Splice(start, end, bare, (start, start + len(bare)))
    if text[start - width : start] == fence and text[end : end + width] == fence:
        return Splice(
            start - width, end + width, chosen, (start - width, start - width + len(chosen))
        )
    fenced = f"{fence}{chosen}{fence}"
    if not chosen:
        # Nothing selected: the caret goes between the fences, ready to be typed into.
        return Splice(start, end, fenced, (start + width, start + width))
    return Splice(start, end, fenced, (start + width, start + width + len(chosen)))


def line_prefix(text: str, start: int, end: int, marker: str) -> Splice:
    """Put ``marker`` at the head of every line the selection touches, or take it away.

    One mark to a line: a heading replaces a bullet rather than sitting in front of it,
    and a line that already carries exactly this marker loses it — that is the toggle.
    A numbered list counts down the run; the indent in front of any of them is kept.
    """
    first = text.rfind("\n", 0, start) + 1
    last = text.find("\n", end)
    if last < 0:
        last = len(text)
    lines = text[first:last].split("\n")
    numbered = marker.endswith(". ") and marker[:-2].isdigit()
    already = all(_marked(line, marker) for line in lines if line.strip())
    out = []
    for index, line in enumerate(lines):
        if not line.strip():
            out.append(line)
            continue
        indent, existing = _BLOCK.match(line).groups()  # type: ignore[union-attr]  # Always matches.
        body = line[len(indent) + len(existing or "") :]
        if already:
            out.append(indent + body)
        elif numbered:
            out.append(f"{indent}{index + 1}. {body}")
        else:
            out.append(indent + marker + body)
    replaced = "\n".join(out)
    return Splice(first, last, replaced, (first, first + len(replaced)))


def heading(text: str, start: int, end: int, level: int) -> Splice:
    """The lines the selection touches as a level-``level`` heading, or as body text when
    they already are one — the same toggle a list marker has, with the level as identity."""
    return line_prefix(text, start, end, "#" * level + " ")


def link(text: str, start: int, end: int) -> Splice:
    """``[selection](url)``, with ``url`` selected — typing the address is what comes next,
    and a dialog asking for it is more ceremony than the two brackets it saves."""
    chosen = text[start:end]
    made = f"[{chosen}]({LINK_PLACEHOLDER})"
    at = start + len(chosen) + 3
    return Splice(start, end, made, (at, at + len(LINK_PLACEHOLDER)))


def table(text: str, start: int, end: int) -> Splice:
    """A two-column skeleton in a block of its own, with the first heading selected."""
    before = "" if start == 0 or text[:start].endswith("\n\n") else _gap(text, start)
    made = before + TABLE
    at = start + len(before) + 2
    return Splice(start, end, made, (at, at + len("Column")))


def _gap(text: str, start: int) -> str:
    """The newlines a block needs in front of it here — none at the top of a document,
    one when the line is already empty, two in the middle of a paragraph."""
    return "\n" if text[:start].endswith("\n") else "\n\n"


def _marked(line: str, marker: str) -> bool:
    if marker.endswith(". ") and marker[:-2].isdigit():
        return bool(re.match(r"^\s*\d{1,9}[.)] ", line))
    if marker.startswith("#"):
        found = _HEADING.match(line)
        return bool(found) and found.group(2) == marker.strip()  # type: ignore[union-attr]
    return line.lstrip().startswith(marker)


# Every verb the strip carries: its words, its glyph, the key its tooltip prints, and
# what it does to the text. `None` for a transform means a verb that inserts rather than
# marks — the picture and the table have no selection to act on.
type Transform = Callable[[str, int, int], Splice]


def _verbs() -> Sequence[tuple[str, Any, str, Transform | None]]:
    return (
        ("Bold", bold_icon, "Ctrl+B", lambda t, s, e: wrap(t, s, e, "**")),
        ("Italic", italic_icon, "Ctrl+I", lambda t, s, e: wrap(t, s, e, "*")),
        ("Code", code_icon, "", lambda t, s, e: wrap(t, s, e, "`")),
        ("", None, "", None),  # a divider
        ("Heading 1", heading_icon(1), "Ctrl+1", lambda t, s, e: heading(t, s, e, 1)),
        ("Heading 2", heading_icon(2), "Ctrl+2", lambda t, s, e: heading(t, s, e, 2)),
        ("Heading 3", heading_icon(3), "Ctrl+3", lambda t, s, e: heading(t, s, e, 3)),
        ("Bullet list", bullet_list_icon, "", lambda t, s, e: line_prefix(t, s, e, "- ")),
        ("Numbered list", list_icon, "", lambda t, s, e: line_prefix(t, s, e, "1. ")),
        ("Quote", quote_icon, "", lambda t, s, e: line_prefix(t, s, e, "> ")),
        ("", None, "", None),  # a divider
        ("Link", link_icon, "Ctrl+Shift+K", link),
        ("Table", table_icon, "", table),
    )


class MarkdownToolbar(Toolbar):
    """The markdown marks as glyphs, over one editor's selection."""

    def __init__(
        self,
        edit: ProseEdit,
        *,
        undo: UndoService[Any] | None = None,
        dictation: DictationService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, dense=True)
        self._edit = edit
        self._undo = undo
        # Dictate leads the strip — speech in place of typing is the one verb here that is
        # not a mark — and it arrives with the strip the way the strip arrives with the
        # editor: a host hands the service over and every prose editor has a microphone.
        # None (a build with no service, a test) leaves the strip as it was. Seated first
        # so that a dock too narrow for every verb folds the picture, which the editor's
        # own menu also offers, before the one verb nothing else offers.
        self.dictation: DictationVerb | None = None
        if dictation is not None:
            self.dictation = DictationVerb(self, edit, dictation, undo=undo)
            self.add_divider()
        for words, icon, keys, transform in _verbs():
            if transform is None:
                self.add_divider()
                continue
            self.add_verb(words, icon, _run(self, transform), keys=keys)
            if keys:
                # On the editor and at WidgetShortcut, never on the action: a strip lives
                # in a window, and a key claimed there reaches every field in it.
                shortcut = QShortcut(QKeySequence(keys), edit)
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
                shortcut.activated.connect(_run(self, transform))
        # Insert Image… is the editor's own — it attaches the file and types the link —
        # so the strip offers the gesture rather than a transform of its own.
        self.image = self.add_verb("Insert image…", image_icon, edit.insert_image_from_file)

    def abandon_dictation(self) -> None:
        """Forget a dictation in progress: the editor is about to show another document."""
        if self.dictation is not None:
            self.dictation.abandon()

    def apply(self, transform: Transform) -> None:
        """Run one verb over the editor's selection as a single splice."""
        if self._edit.isReadOnly():
            return
        cursor = self._edit.textCursor()
        text = self._edit.toPlainText()
        splice = transform(text, cursor.selectionStart(), cursor.selectionEnd())
        # A mark is not a keystroke: without sealing, the host's EditTextCommand merges it
        # into the sentence being typed and one Ctrl+Z takes both. Sealed after as well,
        # so the next keystroke starts its own step rather than growing this one.
        self._break_coalescing()
        cursor.setPosition(splice.start)
        cursor.setPosition(splice.end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(splice.text)
        cursor.setPosition(splice.select[0])
        cursor.setPosition(splice.select[1], QTextCursor.MoveMode.KeepAnchor)
        self._edit.setTextCursor(cursor)
        self._break_coalescing()

    def _break_coalescing(self) -> None:
        if self._undo is not None:
            self._undo.break_coalescing()


def _run(bar: MarkdownToolbar, transform: Transform) -> Callable[[], None]:
    return lambda: bar.apply(transform)
