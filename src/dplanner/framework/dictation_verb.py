"""The microphone on the markdown strip: one verb, and where the words go.

:class:`DictationVerb` is the strip's face of :class:`~dplanner.framework.dictation.Dictation`.
It adds *Dictate* to a :class:`~dplanner.framework.toolbar.Toolbar` over one
:class:`~dplanner.framework.prose_edit.ProseEdit`, puts the same key on the editor at
``WidgetShortcut`` (the strip's rule: a key printed in a tooltip is never a key claimed from
the window), and turns what the state machine says into what the person sees — the verb
checked while the microphone is on, the editor wearing its ``dictating`` edge, the Spinner in
the glyph while the words are on their way, and the verb greyed with the reason in its own
words when nothing can happen.

**Where the words land is the design.** A batch transcript is typed at the caret as one
sealed insert, exactly as a dropped file's link is. A live session takes a cursor of its own
where the caret stood when it began and every delta lands there, so the person can read on
while speaking; an utterance's completed transcript replaces the deltas that led to it. The
whole session is **one undo step**: the verb holds an undo gesture open from the first word
to the stop, and nothing can be undone under it meanwhile.

**A dictation belongs to the document it was started over.** A host that re-binds its
editor to another step, or tears it down, calls :meth:`abandon` first, and whatever the run
still delivers is dropped.
"""

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import QToolTip

from dplanner.framework.dictation import Dictation, DictationService, State
from dplanner.framework.prose_edit import ProseEdit
from dplanner.framework.signalling import Spinner
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.undo import UndoService
from dplanner.theme.icons import microphone_icon

KEYS = "Ctrl+Shift+D"
WORDS = "Dictate"
GESTURE = "Dictation"
DICTATING = "dictating"  # The editor's dynamic property while the microphone is on.


class DictationVerb(QObject):
    def __init__(
        self,
        strip: Toolbar,
        edit: ProseEdit,
        service: DictationService,
        *,
        undo: UndoService[object] | None = None,
    ) -> None:
        super().__init__(strip)
        self._edit = edit
        self._undo = undo
        self._dictation = Dictation(service, self)
        self.action = strip.add_verb(WORDS, microphone_icon, self.toggle, keys=KEYS, checkable=True)
        shortcut = QShortcut(QKeySequence(KEYS), edit)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(self.toggle)
        self._spinner = Spinner(strip).attach(self.action)
        self._session: QTextCursor | None = None  # Where a live session's words land.
        self._utterance: QTextCursor | None = None  # Where the utterance in progress began.
        self._holding = False  # Whether the undo gesture is open.
        self._dictation.state_changed.connect(self._on_state)
        self._dictation.heard.connect(self._on_heard)
        self._dictation.refused.connect(self._on_refused)
        self._unsubscribe = service.config_changed.connect(self.refresh)
        self.refresh()

    @property
    def dictation(self) -> Dictation:
        return self._dictation

    def toggle(self) -> None:
        if self.action.isEnabled():
            self._dictation.toggle()

    def abandon(self) -> None:
        """Forget the clip and drop late words: the editor has moved on."""
        self._dictation.abandon()

    def dispose(self) -> None:
        self._unsubscribe()
        self.abandon()

    def refresh(self) -> None:
        """Re-ask whether dictation can start here, and say why not in the verb's words."""
        if self._dictation.active():
            return  # Mid-session: the face says what is happening, not what could.
        status = self._dictation.service.status()
        usable = status.ready and self._edit.isEnabled() and not self._edit.isReadOnly()
        self.action.setEnabled(usable)
        self.action.setText(WORDS if status.ready else f"{WORDS} — {status.message}")

    # -- what the state machine says -------------------------------------------------------

    def _on_state(self, state: State) -> None:
        listening = state in ("recording", "listening")
        working = state in ("transcribing", "finishing")
        # Checked first: the strip re-inks the glyph on toggled, and the spinner puts back
        # whatever icon it borrowed, so the order decides what the idle glyph comes back as.
        self.action.setChecked(listening)
        if working:
            self._spinner.start()
        else:
            self._spinner.stop()
        self._edit.setProperty(DICTATING, listening or working)
        style = self._edit.style()
        style.unpolish(self._edit)
        style.polish(self._edit)
        if state == "listening":
            self._session = QTextCursor(self._edit.textCursor())
            self._session.clearSelection()
            self._utterance = None
        elif state == "idle":
            self._release()
            self.refresh()

    def _on_heard(self, text: str, final: bool) -> None:
        session = self._session
        if session is None:  # Batch: the whole transcript, once, as one sealed insert.
            self._edit.insert_at_caret(text)
            return
        if not self._holding and self._undo is not None:
            self._holding = self._undo.begin_gesture()
        if self._utterance is None:
            self._utterance = QTextCursor(session)
            self._utterance.setKeepPositionOnInsert(True)
        if final:
            cursor = QTextCursor(self._edit.document())
            cursor.setPosition(self._utterance.position())
            cursor.setPosition(session.position(), QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(f"{text} " if text else "")
            session.setPosition(cursor.position())
            self._utterance = None
        else:
            session.insertText(text)
        self._edit.setTextCursor(session)

    def _on_refused(self, why: str) -> None:
        # The strip has no status line, and the editor is where the attention is.
        at = self._edit.mapToGlobal(self._edit.cursorRect().bottomLeft())
        QToolTip.showText(at, why, self._edit)

    def _release(self) -> None:
        if self._holding and self._undo is not None:
            self._undo.end_gesture(GESTURE)
        self._holding = False
        self._session = None
        self._utterance = None
