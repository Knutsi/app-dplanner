"""State signalling: what a surface says while it is not yet showing the truth.

Three widgets, one vocabulary (DESIGN.md's *Signalling*). A :class:`Spinner` turns a
three-quarter arc for as long as a piece of work runs, and there is exactly one such motion
in the application: in the glyph slot of the button whose verb started the work, or — as an
:class:`UpdatingIndicator` — on its own at the right end of a control strip, for the 300 to
500 ms in which a view still shows the picture the person has just changed. A
:class:`StatusLine` says where a piece of work stands, in a tone — busy, ok, error, or plain
information — as a glyph beside secondary text: the glyph carries the mood, the words carry
the fact. It lives where the answer will land: a dialog footer's status slot, the right end
of a page's control strip.

The indicator sits at the right end of a control strip's *layout*, outside the
``control_bar`` toolbar, so the » overflow can never swallow it; it keeps its room while
hidden so the strip does not reflow on every settle. It is a **turning arc and no words**:
the words would be the only prose on a strip of controls, they are four times the arc's
width, and every language would need its own. *Updating…* survives as the tooltip.
``modules/debug/design_example.py`` shows all three in place.
"""

import html
from collections.abc import Callable
from typing import Literal
from weakref import ref

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget
from shiboken6 import isValid

from dplanner.framework.debounce import Debounced
from dplanner.theme.icons import ICON_SIZE, spinner_frames
from dplanner.theme.tokens import SECONDARY_ALPHA
from dplanner.theme.tones import STATUS_TONES

SPIN_MS = 80  # A frame every 80 ms: one turn a second, calm rather than frantic.

Tone = Literal["info", "busy", "ok", "error"]
# A tone's entry in the theme's status vocabulary; information wears the label's own ink.
_TONE_KEYS: dict[str, str] = {"busy": "busy", "ok": "good", "error": "bad"}
GLYPH = "●"


class Spinner(QObject):
    """A turning arc in the glyph slot of the button whose work is running.

    Attach a button or a toolbar verb that carries a glyph; while the followed
    :class:`Debounced` owes a run (or between ``start()`` and ``stop()``) its glyph is the
    arc, stepped a frame at a time, and the glyph it had comes back when the work is done.
    The slot is always there, so nothing moves — which is why a button with no glyph is
    refused: a spinner that appears beside the words is a size jump, and a layout that
    jumps under the pointer is the one thing this must never do.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._targets: list[QAction | QAbstractButton] = []
        self._labels: list[QLabel] = []
        self._idle: dict[int, QIcon] = {}
        self._frames: list[QIcon] = []
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(SPIN_MS)
        self._timer.timeout.connect(self._advance)

    def attach(self, target: QAction | QAbstractButton | QLabel) -> "Spinner":
        """A button or verb whose glyph is borrowed, or a label that *is* the slot."""
        if isinstance(target, QLabel):
            # Nothing to borrow and nothing to put back: an idle label shows nothing, which
            # is why it is fixed to a glyph's size and keeps its room while hidden.
            self._labels.append(target)
            return self
        if target.icon().isNull():
            raise ValueError("a spinner turns in a glyph slot: give the button an idle glyph")
        self._targets.append(target)
        return self

    def follow(self, debounced: Debounced) -> Callable[[], None]:
        """Turn while ``debounced`` owes a run; returns the unsubscribe."""
        spinner = ref(self)

        def on_pending(pending: bool) -> None:
            live = spinner()
            if live is not None and isValid(live):
                live.start() if pending else live.stop()

        return debounced.pending_changed.connect(on_pending)

    def is_spinning(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        if self.is_spinning():
            return
        self._frames = spinner_frames(self._ink())  # Re-inked per run: the theme may have moved.
        self._frame = 0
        for target in self._targets:
            self._idle[id(target)] = target.icon()  # As inked now: put back exactly this.
        self._show()
        self._timer.start()

    def stop(self) -> None:
        if not self.is_spinning():
            return
        self._timer.stop()
        for target in self._targets:
            target.setIcon(self._idle.pop(id(target), target.icon()))
        for label in self._labels:
            label.clear()

    def _advance(self) -> None:
        self._frame = (self._frame + 1) % len(self._frames)
        self._show()

    def _show(self) -> None:
        frame = self._frames[self._frame]
        for target in self._targets:
            target.setIcon(frame)
        for label in self._labels:
            label.setPixmap(frame.pixmap(ICON_SIZE, ICON_SIZE))

    def _ink(self) -> QColor:
        parent = self.parent()
        palette = parent.palette() if isinstance(parent, QWidget) else QApplication.palette()
        ink = palette.color(QPalette.ColorRole.Text)
        ink.setAlpha(SECONDARY_ALPHA)
        return ink


class UpdatingIndicator(QLabel):
    """A turning arc while a rebuild is owed; nothing otherwise.

    The same arc a working button turns, standing on its own because a strip has no glyph
    slot to borrow. It keeps its room while hidden, so appearing and going costs the strip
    no reflow, and it is a square the size of a glyph — the words are the tooltip.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UpdatingIndicator")
        self.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.setToolTip("Updating…")
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self._spinner = Spinner(self).attach(self)
        self.hide()

    def follow(self, debounced: Debounced) -> Callable[[], None]:
        """Turn while ``debounced`` owes a run; returns the unsubscribe.

        The slot holds the indicator weakly: a plain-Python signal keeping a widget's bound
        method alive past its C++ side is the shape that crashes the collector, and the
        debouncer may well outlive the strip it once reported into.
        """
        indicator = ref(self)

        def show_pending(pending: bool) -> None:
            live = indicator()
            if live is None or not isValid(live):
                return
            live.setVisible(pending)
            live._spinner.start() if pending else live._spinner.stop()

        return debounced.pending_changed.connect(show_pending)

    def is_spinning(self) -> bool:
        return self._spinner.is_spinning()


class StatusLine(QLabel):
    """A glyph in a tone beside the words: where this piece of work stands."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusLine")
        self.setTextFormat(Qt.TextFormat.RichText)
        self._words = ""
        self._tone: Tone = "info"
        self.hide()

    def say(self, text: str, tone: Tone = "info") -> None:
        """Show ``text`` in ``tone``; an empty text hides the line."""
        self._words, self._tone = text, tone
        key = _TONE_KEYS.get(tone)
        glyph = GLYPH
        if key is not None:
            glyph = f'<span style="color:{STATUS_TONES[key].name()}">{GLYPH}</span>'
        self.setText(f"{glyph}&nbsp;{html.escape(text)}")
        self.setVisible(bool(text))

    def clear(self) -> None:
        self.say("")

    def words(self) -> str:
        return self._words

    def tone(self) -> Tone:
        return self._tone
