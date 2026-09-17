"""What a test looks like on screen: its result's words and colour, and the test itself.

Shared by the step panel's Tests tab, the Tests table, the Test panel and the preview a
reference opens, so a failed test reads the same wherever it is shown. The colours are
**constant** ``QColor``s rather than theme fields — ``DESIGN.md``'s second deliberate
exception, the same stance the progression board takes: a status means one thing, and it
must mean it on all twenty-two themes.

:class:`TestHead` and :class:`TestBody` are the test *as it is read*: what it is called,
where it is filed, how it last did, and its body rendered. The Test panel puts its verb
strip between the two and the preview dialog puts nothing there, which is the whole
difference between them — writing it twice is what would let one grow a fact the other
lacks.
"""

from collections.abc import Iterable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from dplanner.core.markdown import ImageSource
from dplanner.core.markdown import render as markdown
from dplanner.core.signals import Signal
from dplanner.domain.model import Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.widgets import caption, note, well
from dplanner.modules.testing import references
from dplanner.modules.testing.aspect import MODULE_ID, Test, audience_words
from dplanner.modules.testing.filing import category_of
from dplanner.modules.testing.runs import Outcome
from dplanner.theme.cards import title_font
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP

# Semantic result colours, constant across themes (DESIGN.md deliberate exception #2).
OK_TINT = QColor(46, 160, 67)
FAILED_TINT = QColor(219, 68, 55)
SKIPPED_TINT = QColor(210, 153, 34)

TINTS = {"ok": OK_TINT, "failed": FAILED_TINT, "skipped": SKIPPED_TINT}
WORDS = {"ok": "Ok", "failed": "Failed", "skipped": "Skipped", "pending": "Not run"}
# The order results are offered in, wherever they are: the menus, the strip.
RESULT_ORDER = ("ok", "failed", "skipped", "pending")

# A failed row is the one you came for, so it is the only one tinted; a wall of green
# would shout at every reader who was not looking for it.
FAILED_ROW_TINT = QColor(219, 68, 55, 26)


def word(status: str) -> str:
    return WORDS.get(status, status)


def tint(status: str) -> QColor | None:
    """The colour for a status, or ``None`` for pending — which is an absence, not a state."""
    return TINTS.get(status)


def outcome_line(outcome: Outcome | None) -> str:
    """Where a result came from, in one secondary line: the run, and what was noted."""
    if outcome is None:
        return ""
    where = outcome.run.label or outcome.run.id
    note = f" — {outcome.result.note}" if outcome.result.note else ""
    return f"{where}{note}"


class StatusChip(QLabel):
    """A dot and a word. Not a filled pill: at card size a pill is louder than the title."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.show_status("pending")

    def show_status(self, status: str) -> None:
        colour = tint(status)
        if colour is None:
            self.setText(WORDS["pending"])
            # Pending has no colour of its own; it borrows the panel's secondary text.
            self.setObjectName("InspectorNote")
        else:
            self.setText(f"● {word(status)}")
            self.setObjectName("")
            self.setStyleSheet(f"color: {colour.name()};")
        self.style().unpolish(self)
        self.style().polish(self)


NO_BODY = "This test has no body yet — nobody can execute it. Show Step to write one."


class TestHead(QWidget):
    """What a test is called, where it is filed, and how it last did.

    ``DESIGN.md``'s *Facts under the thing they are about*: the id over the title, the
    filing under it, the result under that — so the Test panel and the preview read as the
    same block of lines in the same places.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(CAPTION_GAP)

        self.identity = caption("", self)
        column.addWidget(self.identity)
        self.title = QLabel(self)
        self.title.setFont(title_font(self.title.font()))
        self.title.setWordWrap(True)
        column.addWidget(self.title)
        self.filed = note("", self)
        self.filed.setWordWrap(True)
        column.addWidget(self.filed)

        where = QHBoxLayout()
        column.addLayout(where)  # Before it is filled: a parentless layout leaks its items.
        where.setSpacing(FIELD_GAP)
        self.chip = StatusChip(self)
        where.addWidget(self.chip)
        self.outcome = note("", self)
        self.outcome.setWordWrap(True)
        where.addWidget(self.outcome, 1)

    def show_test(self, step: Step, test: Test, outcome: Outcome | None) -> None:
        self.identity.setText(test.id)
        self.title.setText(test.title or "Untitled test")
        self.filed.setText(
            " · ".join(
                part
                for part in (
                    category_of(test),
                    test.sort_key,
                    audience_words(test),
                    step.title or "Untitled step",
                    "Archived" if test.archived else "",
                )
                if part
            )
        )
        self.chip.show_status(outcome.result.status if outcome else "pending")
        self.outcome.setText(outcome_line(outcome))


def test_images(files: FilesFor | None, step_id: StepId) -> ImageSource:
    """A body's pictures, as paths a browser can load.

    The images are the **step's** — ``dplanner test attach`` has always written them there
    — so a relative link is resolved against the step's own area rather than left as the
    link the editor stores, which nothing outside the plan directory could follow. One a
    build with no store cannot resolve is omitted rather than left broken.
    """

    def source(name: str) -> str | None:
        if "://" in name:
            return name or None
        if files is None or not step_id:
            return None
        found = files(step_id, MODULE_ID).absolute(name.split("/")[-1])
        return found.as_uri() if found.is_file() else None

    return source


class TestBody(QTextBrowser):
    """A test's markdown rendered read only, with its references to other tests linked.

    ``reference`` carries the id of a reference the reader clicked, which is the one thing
    a host has to answer for itself — a panel and a modal do it differently. Every other
    link is a link out of the application and opens in the browser, which is the same
    answer everywhere and so is given here.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TestBody")
        self.setFrameShape(QFrame.Shape.NoFrame)
        well(self)  # Read-only: content, never a field with an accent edge round it.
        self.setOpenLinks(False)
        self.reference: Signal[str] = Signal("testing.reference")
        self.anchorClicked.connect(self._on_anchor)

    def show_body(
        self,
        body: str,
        *,
        image_src: ImageSource | None = None,
        known: Iterable[str] = (),
    ) -> None:
        """``body`` as HTML. ``known`` is the ids a reference in it may name — the
        project's, and the caller's to narrow, since resolving them is a walk of it."""
        html = markdown(body, image_src=image_src)
        self.setHtml(references.link_tests(html, known) if html else f"<p>{NO_BODY}</p>")

    def _on_anchor(self, url: QUrl) -> None:
        found = references.linked_test(url.toString())
        if found:
            self.reference.emit(found)
        else:
            QDesktopServices.openUrl(url)
