"""A conversation read in full: every message listed, and the picked one beside the list.

The Review tab lists what was said as headings and opening lines — enough to see where a
review stands, not to read a finding. This dialog is where one is read: the messages on the
left, who said each in its glyph, and the picked one's whole text on the right, rendered.
It reads the ledger and writes nothing, like every window surface of a review, and it
follows the ledger while it is open: the watcher adopts another process's write on a timer
of its own rather than a settle, so a reply an agent posts from a terminal arrives here as
a row even behind the modal.

It opens on any step that has asked a round — a review, or a collector that sent work back
upstream with the same verbs — because the ledger is the same on both.

The rows and the standing line are built here for the Review tab as well, so the tab's
quick look and the dialog name each message the same way.
"""

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.list_rows import DETAIL_ROLE, HOST_ROLE, TRAILING_ROLE, RichList
from dplanner.framework.markdown_view import MarkdownView
from dplanner.framework.signalling import Tone
from dplanner.framework.widgets import DOCUMENT_MARGIN, EmptyState, ink_of, note, well
from dplanner.modules.step_review.aspect import (
    APPROVED,
    ASKER,
    ENDED_STATES,
    ESCALATED,
    POSTED,
    REPLIED,
    Message,
    Round,
    last,
    messages,
    rounds,
    standing,
    with_party,
)
from dplanner.modules.step_review.aspect import MODULE_ID as ROUNDS_ID
from dplanner.planning.review import MODULE_ID, is_review, settings, subjects
from dplanner.theme.cards import title_font
from dplanner.theme.icons import review_icon, spark_icon
from dplanner.theme.tokens import CAPTION_GAP

NO_ROUNDS = "No rounds yet"
TITLE = "Review Conversation"
# Framed (DESIGN.md's *Dialogs*): a finding is prose, and the list beside it keeps its width.
DIALOG_SIZE = (880, 560)
LIST_MIN_W, LIST_MAX_W, LIST_WIDTH = 240, 360, 300

# Which message a row is — its party, round and kind, which survive a refill — and who said it.
KEY_ROLE = HOST_ROLE
SENDER_ROLE = HOST_ROLE + 1

KeyOf = Callable[[Step], str]


def ref(library: Library, step_id: StepId, key_of: KeyOf) -> str:
    """A step as the conversation names it: its key, or its title quoted."""
    if not library.has(step_id):
        return "a removed step"
    step = library.step(step_id)
    return key_of(step) or f"“{step.title}”"


def message_key(said: Message) -> str:
    return f"{said.round.party}/{said.round.number}/{said.kind}"


def heading(
    library: Library, asker: Step, said: Message, key_of: KeyOf, *, name_party: bool
) -> str:
    """``Round 2 · R8's findings`` — naming the party too when the asker talks to several."""
    sender = ref(library, asker.id if said.sender == ASKER else said.round.party, key_of)
    what = {
        POSTED: f"{sender}'s findings",
        REPLIED: f"{sender}'s reply",
        ESCALATED: "Handed to a person",
        APPROVED: "Approved",
    }[said.kind]
    with_whom = f" with {ref(library, said.round.party, key_of)}" if name_party else ""
    return f"Round {said.round.number}{with_whom} · {what}"


def when(stamp: str) -> str:
    """``27 Sep 14:02`` where this machine is — or the stamp as written, when unreadable."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%d %b %H:%M")
    except ValueError:
        return stamp


def sender_icon(sender: str, ink: QColor) -> QIcon:
    """The asker speaks in the review's glyph; the step answering in the agent's."""
    return review_icon(ink) if sender == ASKER else spark_icon(ink)


def message_rows(
    library: Library, asker: Step, key_of: KeyOf, ink: QColor
) -> list[QListWidgetItem]:
    """Every message ``asker``'s ledger holds, in the order it was said, as list rows."""
    held = rounds(asker)
    several = len({each.party for each in held}) > 1
    rows = []
    for said in messages(held):
        item = QListWidgetItem(heading(library, asker, said, key_of, name_party=several))
        text = said.text.strip()
        item.setData(DETAIL_ROLE, text.splitlines()[0] if text else "")
        item.setData(TRAILING_ROLE, when(said.at))
        item.setData(KEY_ROLE, message_key(said))
        item.setData(SENDER_ROLE, said.sender)
        item.setIcon(sender_icon(said.sender, ink))
        rows.append(item)
    return rows


def reink(rows: QListWidget) -> None:
    """Paint each row's glyph again in the list's ink — a glyph keeps the colour it was
    painted in, so a list that outlives a theme change owes this on ``PaletteChange``."""
    ink = ink_of(rows)
    for index in range(rows.count()):
        item = rows.item(index)
        item.setIcon(sender_icon(str(item.data(SENDER_ROLE)), ink))


def where_it_stands(library: Library, asker: Step, key_of: KeyOf) -> tuple[str, Tone]:
    """Where the conversation stands, in a sentence and its tone: a review's with its one
    subject, a collector's with whichever source it talked to last."""
    if is_review(asker):
        reviewed = subjects(library, asker)
        if not reviewed:
            return "Reviews nothing yet — link it after the step it reviews", "warn"
        if len(reviewed) > 1:
            keys = ", ".join(ref(library, each.id, key_of) for each in reviewed)
            return f"Reviews {keys} at once — a review takes one step", "warn"
        party = reviewed[0].id
        held = last(asker, party)
    else:
        asked = rounds(asker)
        if not asked:
            return "", "info"
        held = asked[-1]
        party = held.party
    text = standing(held, ref(library, asker.id, key_of), ref(library, party, key_of))
    if held is None or held.state not in ENDED_STATES:
        cap = settings(asker).max_rounds
        text += f" — {len(with_party(asker, party))} of {cap} rounds"
    text = text[0].upper() + text[1:]
    if held is not None and held.state == APPROVED:
        return text, "ok"
    if held is not None and held.state == ESCALATED:
        return text, "warn"
    return text, "info"


class ConversationDialog(DialogFrame):
    """One step's conversation: the messages beside the one being read."""

    def __init__(
        self,
        library: Library,
        step_id: StepId,
        key_of: KeyOf,
        parent: QWidget | None = None,
        *,
        at: str | None = None,
    ) -> None:
        super().__init__(TITLE, parent, size=DIALOG_SIZE)
        self.setObjectName("ConversationDialog")
        self._library = library
        self._step_id = step_id
        self._key_of = key_of
        self._shown: dict[str, Message] = {}  # Each row's message, by its key.
        # What the text pane holds, so a refill that leaves it alone keeps the reader's place.
        self._on_screen: tuple[str, str, str] | None = None
        self.set_title(f"{TITLE} — {ref(library, step_id, key_of)}")

        self.split = QSplitter(Qt.Orientation.Horizontal, self.body)
        self.split.setChildrenCollapsible(False)
        # Built into the splitter before the text: the frame focuses the first field it
        # finds, and the list is where the keyboard starts here.
        self.messages = RichList(self.split)
        self.messages.setMinimumWidth(LIST_MIN_W)
        self.messages.setMaximumWidth(LIST_MAX_W)
        self.messages.currentItemChanged.connect(lambda _now, _was: self._show_picked())

        # The text's own document margin is the inset from the seam, and the head above it
        # takes the same, so the heading, its time and the text share one left edge.
        pane = QWidget(self.split)
        column = QVBoxLayout(pane)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        head = QVBoxLayout()
        column.addLayout(head)  # Before it is filled: a parentless layout leaks its items.
        head.setContentsMargins(DOCUMENT_MARGIN, 0, DOCUMENT_MARGIN, 0)
        head.setSpacing(CAPTION_GAP)
        self.heading = QLabel(pane)
        self.heading.setFont(title_font(self.heading.font()))
        self.heading.setWordWrap(True)
        head.addWidget(self.heading)
        self.said_when = note("", pane)
        head.addWidget(self.said_when)
        self.text = MarkdownView(pane)
        self.text.setFrameShape(QFrame.Shape.NoFrame)
        well(self.text)  # Read-only: content, never a field with an accent edge round it.
        column.addWidget(self.text, 1)

        self.split.addWidget(self.messages)
        self.split.addWidget(pane)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([LIST_WIDTH, DIALOG_SIZE[0] - LIST_WIDTH])
        self.body_layout.addWidget(self.split, 1)
        self.empty = EmptyState(NO_ROUNDS, self.body, stands_in_for=self.split)
        self.body_layout.addWidget(self.empty, 1)

        self.add_dismiss("Close")  # It edits nothing: Close, and nothing else.

        self._unsubscribes = [
            library.module_data_changed.connect(self._on_module_data),
            library.edges_changed.connect(lambda step, _origin: self._on_edges(step)),
            library.structure_changed.connect(lambda _parent, _origin: self._on_structure()),
        ]
        self._fill(at)

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- what the tests read ---------------------------------------------------------------

    def rows(self) -> list[tuple[str, str, str]]:
        """Each message as listed: its heading, the line under it, and who said it."""
        return [
            (
                self.messages.item(index).text(),
                str(self.messages.item(index).data(DETAIL_ROLE)),
                str(self.messages.item(index).data(SENDER_ROLE)),
            )
            for index in range(self.messages.count())
        ]

    def picked(self) -> int:
        return self.messages.currentRow()

    def shown_text(self) -> str:
        return self.text.toPlainText()

    # -- internals -------------------------------------------------------------------------

    def _step(self) -> Step | None:
        return self._library.step(self._step_id) if self._library.has(self._step_id) else None

    def _fill(self, at: str | None = None) -> None:
        """List the ledger again, keeping the reader on the message they were reading —
        or on ``at`` — and on the newest when neither is listed."""
        step = self._step()
        if step is None:
            return
        current = self.messages.currentItem()
        keep = at or (str(current.data(KEY_ROLE)) if current is not None else None)
        self._shown = {message_key(said): said for said in messages(rounds(step))}
        rows = message_rows(self._library, step, self._key_of, ink_of(self.messages))
        self.messages.blockSignals(True)  # One render below, not one per row.
        try:
            self.messages.clear()
            for item in rows:
                self.messages.addItem(item)
            keys = [str(item.data(KEY_ROLE)) for item in rows]
            self.messages.setCurrentRow(keys.index(keep) if keep in keys else len(keys) - 1)
        finally:
            self.messages.blockSignals(False)
        self.empty.say("" if rows else NO_ROUNDS)
        self._say_where()
        self._show_picked()

    def _say_where(self) -> None:
        step = self._step()
        if step is not None:
            self.status.say(*where_it_stands(self._library, step, self._key_of))

    def _show_picked(self) -> None:
        item = self.messages.currentItem()
        said = self._shown.get(str(item.data(KEY_ROLE))) if item is not None else None
        step = self._step()
        if item is None or said is None or step is None:
            self._on_screen = None
            self.heading.clear()
            self.said_when.clear()
            self.text.clear()
            return
        showing = (message_key(said), said.text, said.at)
        if showing == self._on_screen:
            return  # Another stamp landed; re-rendering would scroll the reader to the top.
        self._on_screen = showing
        self.heading.setText(item.text())
        self.said_when.setText(when(said.at))
        text = said.text.strip()
        if text:
            self.text.show_markdown(text)
        else:
            self.text.show_text(self._outcome(step, said.round))
        self.messages.scrollToItem(item)

    def _outcome(self, step: Step, held: Round) -> str:
        """What a message with no words amounts to — an approval says who approved whom."""
        sentence = standing(
            held,
            ref(self._library, step.id, self._key_of),
            ref(self._library, held.party, self._key_of),
        )
        return f"{sentence[0].upper()}{sentence[1:]}."

    def _on_module_data(self, node_id: NodeId, module_id: str, _origin: object) -> None:
        if node_id != self._step_id:
            return
        if module_id == ROUNDS_ID:
            self._fill()
        elif module_id == MODULE_ID:  # The cap moved, or the step stopped being a review.
            self._say_where()

    def _on_edges(self, step_id: StepId) -> None:
        if step_id == self._step_id:
            self._say_where()

    def _on_structure(self) -> None:
        if not self._library.has(self._step_id):
            self.reject()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            reink(self.messages)
        super().changeEvent(event)


def open_conversation(
    library: Library,
    step_id: StepId,
    key_of: KeyOf,
    parent: QWidget | None = None,
    *,
    at: str | None = None,
) -> None:
    """Read ``step_id``'s conversation, on the message ``at`` names or the newest."""
    dialog = ConversationDialog(library, step_id, key_of, parent, at=at)
    try:
        dialog.exec()
    finally:
        dialog.dispose()
        dialog.deleteLater()
