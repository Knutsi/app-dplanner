"""The step panel's **Tests** tab, and the check step's **Covers** tab.

Two tabs, one file, because they are the same list seen from two sides: a step's own tests,
and the tests a check stands for. Neither is where a result is *recorded* — that happens in
a run, which is the Tests activity's world. Here you write tests and see how they last did,
which is the honest split: the step panel is for authoring.

**Why a card's buttons push commands directly.** Archive and Remove act on one test, and a
panel must not publish a selection — it follows the context, and writing to it would fight
the canvas for what the window is showing. So these are the panel's own controls, pushed
onto the undo stack the way the time report's focus spinbox is. The registry verbs live in
the Tests activity, where a row *is* a test and selecting one is the natural gesture.
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import Command, SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.framework.cards import CARD_PADDING, STACK_SPACING
from dplanner.framework.module_data_section import FIELD_GAP, PANEL_MARGIN
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import (
    MODULE_ID,
    Test,
    covered,
    find,
    next_test_id,
    read,
    replace,
    write,
)
from dplanner.modules.testing.view import StatusChip, outcome_line, word

BLOCK_GAP = 12
LANE_PADDING = 12
BODY_MIN_HEIGHT = 44
BODY_MAX_HEIGHT = 220
BODY_SLACK = 4  # So a full last line never sits against the frame.

TAB_NOTE = "How you would know this step works — kept after the work is done."
BODY_PLACEHOLDER = "1. Do this.\n2. This must be true."
# Neutral about *what* the step is: a release is a scope in exactly the same way a
# check is, and this tab appears on both.
COVERS_NOTE = "Every test this step waits on, directly or through other steps."


class TestBodyField:
    """One test's markdown body, described to the framework's text binding.

    The three-method contract in ``framework/text_binding.py``, over a record inside
    ``module_data`` rather than over a prose document — which is what buys the body the
    expand-to-a-modal editor without anybody copying text into a dialog and back.

    ``_last`` is the shadow copy a whole-entry write cannot carry: ``module_data_changed``
    says *that* the entry changed, never how, so the field reports a foreign edit as one
    replace of the whole body. Cheap and exact; the only cost is the cursor on a change
    somebody else made, and this file's own typing never takes that path.
    """

    def __init__(self, library: Library, step_id: StepId, test_id: str) -> None:
        self._library = library
        self._step_id = step_id
        self._test_id = test_id
        self._last = self.read()

    def read(self) -> str:
        if not self._library.has(self._step_id):
            return ""
        found = find(read(self._library.step(self._step_id)), self._test_id)
        return found.body if found else ""

    def command(self, pos: int, removed: str, added: str, origin: object) -> Command:
        body = self.read()
        spliced = body[:pos] + added + body[pos + len(removed) :]
        tests = read(self._library.step(self._step_id))
        found = find(tests, self._test_id)
        if found is None:  # The test went while the editor was open; write nothing.
            return SetModuleDataCommand(self._step_id, MODULE_ID, write(tests))
        changed = replace(tests, Test(found.id, found.title, spliced, found.archived))
        return SetModuleDataCommand(
            self._step_id,
            MODULE_ID,
            write(changed),
            view_origin=origin,
            # Labelled per test, so editing two of them never merges into one undo step.
            label=f"Edit Test {self._test_id}",
        )

    def connect(self, applied: Callable[[int, str, str, object], None]) -> Callable[[], None]:
        def on_data(node_id: NodeId, module_id: str, origin: object) -> None:
            if node_id != self._step_id or module_id != MODULE_ID:
                return
            previous, current = self._last, self.read()
            self._last = current
            if previous != current:
                applied(0, previous, current, origin)

        return self._library.module_data_changed.connect(on_data)


class _AutoHeight(QObject):
    """Grows a body editor with its content instead of letting it scroll inside its card.

    ``DESIGN.md`` forbids an inner scroller in a card: wheel events stop at it and the tab
    stops scrolling under the cursor. Past the cap the expand button is the way on, which is
    also the right answer on a narrow window.

    Both triggers are needed. The document changes height when the text does — and *also*
    when the card is resized, because a narrower editor rewraps the same words onto more
    lines, and nothing about the document itself changed to say so.
    """

    def __init__(self, edit: QPlainTextEdit) -> None:
        super().__init__(edit)
        self._edit = edit
        edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        edit.document().documentLayout().documentSizeChanged.connect(lambda _size: self.fit())
        edit.installEventFilter(self)
        self.fit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if watched is self._edit and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.fit()
        return super().eventFilter(watched, event)

    def fit(self) -> None:
        document = self._edit.document()
        # QPlainTextEdit's layout reports its height in *lines*, wrapping included.
        lines = document.documentLayout().documentSize().height()
        content = lines * self._edit.fontMetrics().lineSpacing() + document.documentMargin() * 2
        wanted = int(content) + self._edit.frameWidth() * 2 + BODY_SLACK
        self._edit.setFixedHeight(min(max(wanted, BODY_MIN_HEIGHT), BODY_MAX_HEIGHT))


class TestCard(QFrame):
    """One test: its name, how to verify it, and how it last did."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        step_id: StepId,
        test: Test,
    ) -> None:
        super().__init__()
        self.setObjectName("ToolCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._library = library
        self._undo = undo
        self._step_id = step_id
        self.test_id = test.id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(FIELD_GAP)

        header = QHBoxLayout()
        header.setSpacing(FIELD_GAP)
        self.title = QLineEdit(test.title, self)
        self.title.setPlaceholderText("What the test is called")
        self.title.editingFinished.connect(self._commit_title)
        header.addWidget(self.title, 1)
        self.chip = StatusChip(self)
        header.addWidget(self.chip)
        self.more = QToolButton(self)
        self.more.setText("⋯")
        self.more.setAutoRaise(True)
        self.more.setToolTip("What to do with this test")
        self.more.clicked.connect(self._open_menu)
        header.addWidget(self.more)
        layout.addLayout(header)

        self.body = ProseSection(
            lambda target: TestBodyField(library, step_id, target),
            undo,
            placeholder=BODY_PLACEHOLDER,
            margin=0,
            expand_title=f"Test — {test.title}" if test.title else "Test",
        )
        self.body.show_target(test.id)
        _AutoHeight(self.body.edit)
        layout.addWidget(self.body)

        self.note = QLabel(self)
        self.note.setObjectName("InspectorNote")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        self.refresh(test, None)

    def refresh(self, test: Test, outcome: runs.Outcome | None) -> None:
        """Re-read everything but the body, which its own binding keeps current."""
        if not self.title.hasFocus():
            self.title.setText(test.title)
        self.chip.show_status(outcome.result.status if outcome else "pending")
        parts = [
            part
            for part in (
                "Archived — out of new runs" if test.archived else "",
                outcome_line(outcome),
            )
            if part
        ]
        self.note.setText(" · ".join(parts))
        self.note.setVisible(bool(parts))

    def dispose(self) -> None:
        self.body.dispose()

    # -- the card's own controls ---------------------------------------------------------

    def _current(self) -> Test | None:
        if not self._library.has(self._step_id):
            return None
        return find(read(self._library.step(self._step_id)), self.test_id)

    def _commit_title(self) -> None:
        test = self._current()
        if test is None or test.title == self.title.text():
            return
        self._push(
            replace(
                read(self._library.step(self._step_id)),
                Test(test.id, self.title.text(), test.body, test.archived),
            ),
            "Rename Test",
        )

    def _open_menu(self) -> None:
        test = self._current()
        if test is None:
            return
        menu = QMenu(self)
        back = "Put Back on the Roster" if test.archived else "Archive"
        menu.addAction(back, self._toggle_archived)
        menu.addSeparator()
        menu.addAction("Remove Test…", self._remove)
        menu.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def _toggle_archived(self) -> None:
        test = self._current()
        if test is None:
            return
        tests = read(self._library.step(self._step_id))
        changed = Test(test.id, test.title, test.body, not test.archived)
        self._push(replace(tests, changed), "Archive Test" if changed.archived else "Restore Test")

    def _remove(self) -> None:
        test = self._current()
        if test is None:
            return
        question = (
            f"Remove the test {test.title or test.id!r}? Its results stay in the runs that "
            "recorded them, but the test itself is gone. Archive keeps it and its history."
        )
        if not confirm(self.window(), "Remove Test", question):
            return
        tests = [kept for kept in read(self._library.step(self._step_id)) if kept.id != test.id]
        self._push(tests, "Remove Test")

    def _push(self, tests: list[Test], label: str) -> None:
        self._undo.push(SetModuleDataCommand(self._step_id, MODULE_ID, write(tests), label=label))


class _TestListSection(QWidget):
    """The shared body of both tabs: a caption, a note, and a lane of test cards."""

    def __init__(self, library: Library, note: str) -> None:
        super().__init__()
        self._library = library
        self._target_id: str | None = None

        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        self.outer.setSpacing(FIELD_GAP)

        self.note = QLabel(note, self)
        self.note.setObjectName("InspectorNote")
        self.note.setWordWrap(True)
        self.outer.addWidget(self.note)

        self.area = QScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.outer.addWidget(self.area, 1)

        # A lane, so the cards read as wells on elevated ground rather than as one faint
        # border each on a tab page that is already $BG_BASE — DESIGN.md's Cards section.
        self.lane = QWidget()
        self.lane.setObjectName("ProgressionLane")
        self.lane_layout = QVBoxLayout(self.lane)
        self.lane_layout.setContentsMargins(LANE_PADDING, LANE_PADDING, LANE_PADDING, LANE_PADDING)
        self.lane_layout.setSpacing(STACK_SPACING)
        self.lane_layout.addStretch(1)
        self.area.setWidget(self.lane)

        self.empty = QLabel(self)
        self.empty.setObjectName("InspectorNote")
        self.empty.setWordWrap(True)
        self.empty.hide()
        self.outer.addWidget(self.empty)

    def say(self, message: str) -> None:
        """A surface with nothing to show says so in words; only a *panel* may vanish."""
        self.empty.setText(message)
        self.empty.setVisible(bool(message))
        self.area.setVisible(not message)

    def clear_cards(self) -> None:
        while self.lane_layout.count() > 1:
            item = self.lane_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                if isinstance(widget, TestCard):
                    widget.dispose()
                widget.setParent(None)

    def add_card(self, card: QWidget) -> None:
        self.lane_layout.insertWidget(self.lane_layout.count() - 1, card)


class TestsSection(_TestListSection):
    """The step's own tests, editable — the InspectorExtension the Tests tab renders."""

    def __init__(self, library: Library, undo: UndoService[Library]) -> None:
        super().__init__(library, TAB_NOTE)
        self._undo = undo
        self._cards: list[TestCard] = []

        self.add_button = QPushButton("+ Add test", self)
        self.add_button.clicked.connect(self._add)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.add_button)
        row.addStretch(1)
        self.outer.addLayout(row)

        self._unsubscribes = [
            library.module_data_changed.connect(self._on_module_data),
            library.structure_changed.connect(lambda *_a: self._refresh()),
        ]

    # -- the InspectorExtension contract -------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        # Always start from nothing: test ids are unique per project, so two projects can
        # both have a "t1" and a surviving card would be bound to the wrong step.
        self._drop_cards()
        self._target_id = target_id
        self._refresh()

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []
        self._drop_cards()

    def _drop_cards(self) -> None:
        self.clear_cards()
        self._cards = []

    # -- keeping up with the model -------------------------------------------------------

    def _step(self) -> Step | None:
        if self._target_id is None or not self._library.has(self._target_id):
            return None
        node = self._library.step(self._target_id)
        return node

    def _on_module_data(self, node_id: NodeId, module_id: str, _origin: object) -> None:
        if node_id == self._target_id and module_id == MODULE_ID:
            self._refresh()

    def _refresh(self) -> None:
        step = self._step()
        if step is None:
            self._drop_cards()
            self.add_button.setEnabled(False)
            self.say("No step selected.")
            return
        self.add_button.setEnabled(True)
        tests = read(step)
        self.say("" if tests else "No tests yet. Add one, or run `dplanner test add`.")
        outcomes = self._outcomes()
        # Compared against the cards themselves, never a second list kept alongside them:
        # the two could disagree, and the pairing below assumes they cannot.
        if [test.id for test in tests] != [card.test_id for card in self._cards]:
            # Only the *set* of tests rebuilds; a body edit must never destroy the editor
            # the keystroke came from, and a title edit is written back in place.
            self._drop_cards()
            self._cards = [TestCard(self._library, self._undo, step.id, test) for test in tests]
            for card in self._cards:
                self.add_card(card)
        for card, test in zip(self._cards, tests, strict=True):
            card.refresh(test, outcomes.get(test.id))

    def _outcomes(self) -> dict[str, runs.Outcome]:
        step = self._step()
        if step is None:
            return {}
        project = self._library.project_of(step.id)
        return runs.latest_results(runs.read(project))

    def _add(self) -> None:
        step = self._step()
        if step is None:
            return
        project = self._library.project_of(step.id)
        added = Test(id=next_test_id(project), title="")
        self._undo.push(
            SetModuleDataCommand(step.id, MODULE_ID, write([*read(step), added]), label="Add Test")
        )
        if self._cards:
            self._cards[-1].title.setFocus()


class CoversSection(_TestListSection):
    """What a check stands for: every test behind it, read-only, with its last result."""

    def __init__(self, library: Library, open_in_tests: Callable[[StepId], None]) -> None:
        super().__init__(library, COVERS_NOTE)
        self._open_in_tests = open_in_tests

        self.summary = QLabel(self)
        self.summary.setObjectName("InspectorNote")
        self.open_button = QPushButton("Open in Tests", self)
        self.open_button.clicked.connect(self._open)
        row = QHBoxLayout()
        row.addWidget(self.summary, 1)
        row.addWidget(self.open_button)
        self.outer.addLayout(row)

        self._unsubscribes = [
            library.module_data_changed.connect(lambda *_a: self._refresh()),
            library.edges_changed.connect(lambda *_a: self._refresh()),
            library.structure_changed.connect(lambda *_a: self._refresh()),
            library.field_changed.connect(lambda *_a: self._refresh()),
        ]

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._target_id = target_id
        self._refresh()

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []
        self.clear_cards()

    def _refresh(self) -> None:
        if self._target_id is None or not self._library.has(self._target_id):
            self.clear_cards()
            self.say("No step selected.")
            self.summary.setText("")
            self.open_button.setEnabled(False)
            return
        project = self._library.project_of(self._target_id)
        pairs = covered(self._library, project, self._target_id)
        outcomes = runs.latest_results(runs.read(project))
        self.clear_cards()
        for step, test in pairs:
            self.add_card(_CoveredRow(step.title, test.title, outcomes.get(test.id)))
        self.say(
            ""
            if pairs
            else "Nothing yet. This step covers the tests on the steps it waits on — "
            "link it to work that carries tests."
        )
        self.open_button.setEnabled(bool(pairs))
        self.summary.setText(self._headline(pairs, outcomes))

    def _headline(self, pairs: list[tuple[Step, Test]], outcomes: dict[str, runs.Outcome]) -> str:
        if not pairs:
            return ""
        statuses = [
            outcomes[test.id].result.status if test.id in outcomes else "pending"
            for _step, test in pairs
        ]
        counts = runs.tally(statuses)
        parts = [f"{count} {word(status).lower()}" for status, count in counts.items() if count]
        total = f"{len(pairs)} test{'' if len(pairs) == 1 else 's'}"
        return f"{total} · {', '.join(parts)}"

    def _open(self) -> None:
        if self._target_id is not None:
            self._open_in_tests(self._target_id)


class _CoveredRow(QFrame):
    """One covered test, read-only: what it is, which step it belongs to, how it last did."""

    def __init__(self, step_title: str, test_title: str, outcome: runs.Outcome | None) -> None:
        super().__init__()
        self.setObjectName("ToolCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(FIELD_GAP)

        names = QVBoxLayout()
        names.setSpacing(4)  # DESIGN.md: a rich row's lines sit 4 px apart.
        primary = QLabel(test_title or "Untitled test", self)
        primary.setWordWrap(True)
        names.addWidget(primary)
        secondary = QLabel(step_title or "Untitled step", self)
        secondary.setObjectName("InspectorNote")
        secondary.setWordWrap(True)
        names.addWidget(secondary)
        layout.addLayout(names, 1)

        chip = StatusChip(self)
        chip.show_status(outcome.result.status if outcome else "pending")
        layout.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
