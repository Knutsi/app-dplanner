"""The step panel's **Tests** tab, and the check step's **Covers** tab.

Two tabs, one file, because they are the same list seen from two sides: a step's own tests,
and the tests a check stands for. Neither is where a result is *recorded* — that happens in
a run, which is the Tests activity's world. Here you write tests and see how they last did,
which is the honest split: the step panel is for authoring.

**A list beside one test, when there is room.** A stack of equal cards stops working at
the third test, so the tab is master-detail: a compact line per test (id, name, how it last
did) and an editor for the one selected. The split follows the width — side by side in the
step dialog and a wide panel, stacked in the 360 px dock — because a step under test easily
carries a dozen tests, and a tall list beside a tall editor is what makes that count usable.
The switch is automatic and resets the split; a user's own drag is respected until the
orientation changes under it.

**Why the controls push commands directly.** Add, Archive and Remove act on one test, and a
panel must not publish a selection — it follows the context, and writing to it would fight
the canvas for what the window is showing. So these are the panel's own controls, pushed
onto the undo stack the way the time report's focus spinbox is. The registry verbs live in
the Tests activity, where a row *is* a test and selecting one is the natural gesture.
"""

import dataclasses
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import Command, SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.scope import ScopeKind, cone, kind_of, leaders, stops_for
from dplanner.domain.store import FilesFor
from dplanner.framework.activity import follow_target
from dplanner.framework.cards import CARD_PADDING, STACK_SPACING
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.dictation import DictationService
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.mime_files import Payload
from dplanner.framework.module_data_section import FIELD_GAP, PANEL_MARGIN
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import (
    AUDIENCES,
    MODULE_ID,
    Test,
    audience_words,
    covered,
    find,
    next_test_id,
    read,
    replace,
    write,
)
from dplanner.modules.testing.filing import UNCATEGORISED, catalog, sort_keys
from dplanner.modules.testing.view import StatusChip, outcome_line, tint, word

BLOCK_GAP = 12
BUTTON_GAP = 8
LANE_PADDING = 12
LIST_MAX_HEIGHT = 220  # Stacked: past this the list scrolls rather than crowding the editor.
LIST_PANE_WIDTH = 250  # Side by side: room for an id, a name and a result on one line.
# The roster is three facts a reader compares down a column: which test, what it is called,
# how it last did — a table, in the pane above or beside the editor.
ROSTER_COLUMNS = (Column("Id"), Column("Test", resize="stretch"), Column("Result"))
TEST_ID_ROLE = HOST_ROLE
WIDE_THRESHOLD = 540  # Narrower than this and two columns would starve each other.
DETAIL_MIN_HEIGHT = 140

TAB_NOTE = "How you would know this step works — kept after the work is done."
SORT_KEY_TIP = (
    "What orders this test inside its category — the view it exercises, say. Tests sharing "
    "one are executed together in the Tests tab."
)
BODY_PLACEHOLDER = "1. Do this.\n2. This must be true."
# Neutral about *what* the step is: a check, a feature and a milestone are scopes in
# exactly the same way, and this tab appears on all three. Neutral about the *reading*
# too — the mode switch says whether this is what the step adds or everything behind it,
# so the note must not claim either.
COVERS_NOTE = "What this step stands for: the tests on the work behind it."
# The last group: tests on steps this collector owns that no sub-collector claimed.
DIRECT_GROUP = "Directly"


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
        changed = replace(tests, dataclasses.replace(found, body=spliced))
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
                widget.setParent(None)

    def add_card(self, card: QWidget) -> None:
        self.lane_layout.insertWidget(self.lane_layout.count() - 1, card)


class TestsSection(QWidget):
    """The step's own tests: a list of them, and an editor for the one selected."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        files: FilesFor | None = None,
        pick_assets: Callable[[str], list[Payload]] | None = None,
        dictation: DictationService | None = None,
    ) -> None:
        super().__init__()
        self._library = library
        self._undo = undo
        self._step_id: str | None = None
        self._selected: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FIELD_GAP)

        self.note = QLabel(TAB_NOTE, self)
        self.note.setObjectName("InspectorNote")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addSpacing(FIELD_GAP)

        self.split = QSplitter(Qt.Orientation.Vertical, self)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(BLOCK_GAP)
        self._dragged = False
        self.split.splitterMoved.connect(self._on_dragged)

        # The roster pane: the list with its Add button underneath, so the pair travels
        # together whichever side of the splitter they end up on.
        roster = QWidget(self.split)
        roster_layout = QVBoxLayout(roster)
        roster_layout.setContentsMargins(0, 0, 0, 0)
        roster_layout.setSpacing(FIELD_GAP)
        self.roster = Table(ROSTER_COLUMNS, parent=roster)
        # One row under its header, so a step with one test still shows there is a list.
        self.roster.setMinimumHeight(self._rows_height(1))
        self.roster.itemSelectionChanged.connect(self._on_pick)
        roster_layout.addWidget(self.roster, 1)
        self.add_button = QPushButton("+ Add test", roster)
        self.add_button.clicked.connect(self._add)
        roster_layout.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.split.addWidget(roster)

        # The selected test's own verbs sit in the detail's header, beside what they act on.
        self.more = QToolButton(self)
        self.more.setText("⋯")
        self.more.setAutoRaise(True)
        self.more.setToolTip("What to do with this test")
        self.more.clicked.connect(self._open_menu)
        self.detail = _TestDetail(
            library,
            undo,
            self.split,
            corner=self.more,
            files=files,
            pick_assets=pick_assets,
            dictation=dictation,
        )
        self.detail.setMinimumHeight(DETAIL_MIN_HEIGHT)
        self.split.addWidget(self.detail)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        layout.addWidget(self.split, 1)

        self._unsubscribes = [
            library.module_data_changed.connect(self._on_module_data),
            library.structure_changed.connect(lambda *_a: self._refresh()),
        ]

    def _on_dragged(self, _pos: int, _index: int) -> None:
        self._dragged = True  # The user has said how they want it split; stop guessing.

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        wanted = (
            Qt.Orientation.Horizontal if self.width() >= WIDE_THRESHOLD else Qt.Orientation.Vertical
        )
        if wanted != self.split.orientation():
            self.split.setOrientation(wanted)
            self._dragged = False  # A new shape voids the old drag; guess afresh.
            self._apply_split()

    def _apply_split(self) -> None:
        if self._dragged:
            return
        if self.split.orientation() == Qt.Orientation.Horizontal:
            self.split.setSizes([LIST_PANE_WIDTH, max(self.width() - LIST_PANE_WIDTH, 1)])
        else:
            wanted = min(self._rows_height(self.roster.rowCount()) + LANE_PADDING, LIST_MAX_HEIGHT)
            # The Add button rides under the list, so the pane needs its height too.
            wanted += self.add_button.sizeHint().height() + FIELD_GAP
            self.split.setSizes([wanted, max(self.split.height() - wanted, DETAIL_MIN_HEIGHT)])

    def _rows_height(self, rows: int) -> int:
        """What ``rows`` rows of the roster take, its header included — never less than one."""
        header = self.roster.horizontalHeader().sizeHint().height()
        return header + max(rows, 1) * self.roster.row_height()

    # -- the InspectorExtension contract -------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id
        self._selected = ""  # Ids are unique per project, never across two of them.
        self._refresh()

    def focus_entity(self, kind: str, entity_id: str) -> bool:
        """Select one of this step's tests — what a jump from the coverage view lands on."""
        if kind != "test" or find(self._tests(), entity_id) is None:
            return False
        self._selected = entity_id
        self._refresh()
        return True

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []
        self.detail.dispose()

    # -- keeping up with the model -------------------------------------------------------

    def _step(self) -> Step | None:
        if self._step_id is None or not self._library.has(self._step_id):
            return None
        return self._library.step(self._step_id)

    def _tests(self) -> list[Test]:
        step = self._step()
        return [] if step is None else read(step)

    def _on_module_data(self, node_id: NodeId, module_id: str, _origin: object) -> None:
        if node_id == self._step_id and module_id == MODULE_ID:
            self._refresh()

    def _refresh(self) -> None:
        step = self._step()
        tests = self._tests()
        self.add_button.setEnabled(step is not None)
        if self._selected not in {test.id for test in tests}:
            self._selected = tests[0].id if tests else ""
        outcomes = self._outcomes()
        self._fill(tests, outcomes)
        self._apply_split()
        self.more.setEnabled(bool(self._selected))
        current = find(tests, self._selected) if self._selected else None
        self.detail.show_test(
            None if step is None or current is None else step.id,
            current,
            outcomes.get(current.id) if current else None,
        )

    def _fill(self, tests: list[Test], outcomes: dict[str, runs.Outcome]) -> None:
        # Rebuilt wholesale under blocked signals: a step's tests are never many, and a diff
        # is where list bugs live. Selection is restored by id, not by row.
        self.roster.blockSignals(True)
        self.roster.clear_rows()
        for test in tests:
            outcome = outcomes.get(test.id)
            status = outcome.result.status if outcome else "pending"
            row = self.roster.add_row(
                (
                    Cell(test.id, secondary=True),
                    # An archived test stays legible but reads as retired, as a done step does.
                    Cell(test.title or "Untitled test", secondary=test.archived),
                    # The result keeps its colour on a picked row: the ground is quiet.
                    Cell(word(status), ink=tint(status), secondary=status == "pending"),
                ),
                data={TEST_ID_ROLE: test.id},
            )
            if test.id == self._selected:
                self.roster.selectRow(row)
        self.roster.blockSignals(False)

    def _outcomes(self) -> dict[str, runs.Outcome]:
        step = self._step()
        if step is None:
            return {}
        return runs.latest_results(runs.read(self._library.project_of(step.id)))

    def _on_pick(self) -> None:
        picked = sorted({index.row() for index in self.roster.selectedIndexes()})
        item = self.roster.item(picked[0], 0) if picked else None
        self._selected = "" if item is None else str(item.data(TEST_ID_ROLE))
        self._refresh()

    # -- the tab's own controls ----------------------------------------------------------

    def _add(self) -> None:
        step = self._step()
        if step is None:
            return
        added = Test(id=next_test_id(self._library.project_of(step.id)), title="")
        self._selected = added.id
        self._undo.push(
            SetModuleDataCommand(step.id, MODULE_ID, write([*read(step), added]), label="Add Test")
        )
        self.detail.title.setFocus()

    def _open_menu(self) -> None:
        test = find(self._tests(), self._selected)
        if test is None:
            return
        menu = QMenu(self)
        menu.addAction(
            "Put Back on the Roster" if test.archived else "Archive", self._toggle_archived
        )
        menu.addSeparator()
        menu.addAction("Remove Test…", self._remove)
        menu.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def _toggle_archived(self) -> None:
        step, test = self._step(), find(self._tests(), self._selected)
        if step is None or test is None:
            return
        changed = dataclasses.replace(test, archived=not test.archived)
        self._push(
            step,
            replace(read(step), changed),
            "Archive Test" if changed.archived else "Restore Test",
        )

    def _remove(self) -> None:
        step, test = self._step(), find(self._tests(), self._selected)
        if step is None or test is None:
            return
        question = (
            f"Remove {test.id} ({test.title or 'untitled'})? Its results stay in the runs "
            "that recorded them, but the test itself is gone. Archiving keeps both."
        )
        if not confirm(self.window(), "Remove Test", question):
            return
        self._push(step, [kept for kept in read(step) if kept.id != test.id], "Remove Test")

    def _push(self, step: Step, tests: list[Test], label: str) -> None:
        self._undo.push(SetModuleDataCommand(step.id, MODULE_ID, write(tests), label=label))


class _TestDetail(QWidget):
    """The selected test: what it is called, how to verify it, how it last did."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        parent: QWidget | None = None,
        corner: QWidget | None = None,
        files: FilesFor | None = None,
        pick_assets: Callable[[str], list[Payload]] | None = None,
        dictation: DictationService | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._undo = undo
        self._files = files
        self._pick_assets = pick_assets
        self._step_id: str | None = None
        self._test_id: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(FIELD_GAP)

        header = QHBoxLayout()
        header.setSpacing(FIELD_GAP)
        self.identity = QLabel(self)
        self.identity.setObjectName("InspectorCaption")
        header.addWidget(self.identity)
        self.title = QLineEdit(self)
        self.title.setPlaceholderText("What the test is called")
        self.title.editingFinished.connect(self._commit_title)
        header.addWidget(self.title, 1)
        self.chip = StatusChip(self)
        header.addWidget(self.chip)
        if corner is not None:
            header.addWidget(corner)
        layout.addLayout(header)

        # Who the test is for. Three independent toggles rather than the roster's fourth
        # column: this is the tightest surface in the application, and a test may be for
        # more than one reader. They say what is *stored*, so an unclassified test shows
        # three empty boxes and the note below says what it reads as instead — ticking
        # `Other` through `audiences_of` would render a box that could not be unticked.
        self.classification = QWidget(self)
        row = QHBoxLayout(self.classification)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(FIELD_GAP)
        caption = QLabel("Audience", self.classification)
        caption.setObjectName("InspectorCaption")
        row.addWidget(caption)
        self.audience_boxes: dict[str, QCheckBox] = {}
        for audience in AUDIENCES:
            box = QCheckBox(audience.label, self.classification)
            box.setToolTip(audience.meaning)
            box.toggled.connect(partial(self._commit_audience, audience.id))
            row.addWidget(box)
            self.audience_boxes[audience.id] = box
        row.addStretch(1)
        layout.addWidget(self.classification)

        # Where it is filed, on a row of its own: the audience row is already three boxes
        # wide, and this is the tightest surface in the application. The category is one
        # value out of a list the project keeps, so it is a picker; the sort key is free
        # text with the keys already in use offered as you type, because it has no
        # catalogue and never needed one. The category list is edited in Project ▸ Test
        # Categories…, never here — a panel that let you rename one would be renaming it
        # for every other test too.
        self.filing = QWidget(self)
        filing_row = QHBoxLayout(self.filing)
        filing_row.setContentsMargins(0, 0, 0, 0)
        filing_row.setSpacing(FIELD_GAP)
        category_caption = QLabel("Category", self.filing)
        category_caption.setObjectName("InspectorCaption")
        filing_row.addWidget(category_caption)
        self.category = QComboBox(self.filing)
        self.category.setToolTip("What this test is filed under in the Tests tab")
        self.category.currentIndexChanged.connect(self._commit_category)
        filing_row.addWidget(self.category, 1)
        sort_caption = QLabel("Sort key", self.filing)
        sort_caption.setObjectName("InspectorCaption")
        filing_row.addWidget(sort_caption)
        self.sort_key = QComboBox(self.filing)
        self.sort_key.setEditable(True)
        self.sort_key.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.sort_key.setToolTip(SORT_KEY_TIP)
        # An editable combo always has one; the `| None` is Qt's, not a real maybe.
        field = self.sort_key.lineEdit()
        assert field is not None
        self.sort_key_field: QLineEdit = field
        self.sort_key_field.setPlaceholderText("What orders it inside its category")
        self.sort_key_field.editingFinished.connect(self._commit_sort_key)
        self.sort_key.activated.connect(lambda _index: self._commit_sort_key())
        filing_row.addWidget(self.sort_key, 1)
        layout.addWidget(self.filing)

        # A plain expanding text well: the detail pane is not a card in a scrolling stack,
        # so the editor may simply take the room and scroll like any other document.
        # A test's images are the *step's*, not the test's: `dplanner test attach` has
        # always written them to the step's testing area, and one picture often proves two
        # tests. Hidden while empty — this pane is the tightest surface in the application,
        # and a paste, a drop or the editor's Insert Image… all reach an empty area anyway.
        self.body = ProseSection(
            self._field_for,
            undo,
            placeholder=BODY_PLACEHOLDER,
            margin=0,
            expand_title="Test",
            attach_title="Attach to Tests",
            hide_gallery_when_empty=True,
            dictation=dictation,
        )
        layout.addWidget(self.body, 1)
        # Enter in the title lands in the body, so naming and writing a test is one flow.
        self.title.returnPressed.connect(self.body.edit.setFocus)

        self.result = QLabel(self)
        self.result.setObjectName("InspectorNote")
        self.result.setWordWrap(True)
        layout.addWidget(self.result)

        self.empty = QLabel("No test selected. Add one, or pick one above.", self)
        self.empty.setObjectName("InspectorNote")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)

    def _field_for(self, target_id: str) -> TestBodyField | None:
        if self._step_id is None:
            return None
        return TestBodyField(self._library, self._step_id, target_id)

    def _retarget_assets(self, step_id: str | None) -> None:
        """Keyed by the step, every time — ``show_target`` cleared the area, and it is only
        told the test's id, which names no file area at all. The picker is aimed the same
        way: a picked image is copied beside the *step*, where every test's images live."""
        files = self._files
        if files is not None and step_id is not None:
            self.body.set_area(lambda: files(step_id, MODULE_ID))
        pick = self._pick_assets
        if pick is not None and step_id is not None:
            self.body.set_picker(lambda: pick(step_id))

    def show_test(
        self, step_id: str | None, test: Test | None, outcome: runs.Outcome | None
    ) -> None:
        self._step_id = step_id
        showing = step_id is not None and test is not None
        for widget in (
            self.identity,
            self.title,
            self.chip,
            self.classification,
            self.filing,
            self.body,
            self.result,
        ):
            widget.setVisible(showing)
        self.empty.setVisible(not showing)
        if not showing or test is None:
            self._test_id = ""
            self.body.show_target(None)
            return
        if test.id != self._test_id:
            # Re-bind only on a different test: rebinding under the user's own keystroke
            # would drop the cursor to the top of the document on every character.
            self._test_id = test.id
            self.body.show_target(test.id)
        self._retarget_assets(step_id)
        self.identity.setText(test.id)
        if not self.title.hasFocus():
            self.title.setText(test.title)
        self.chip.show_status(outcome.result.status if outcome else "pending")
        self._show_category(test)
        self._show_sort_key(test)
        for audience_id, box in self.audience_boxes.items():
            # Blocked, or setting the boxes to match the record would push a command back.
            box.blockSignals(True)
            box.setChecked(audience_id in test.audiences)
            box.blockSignals(False)
        self.result.setText(
            " · ".join(
                part
                for part in (
                    "Archived — out of new runs" if test.archived else "",
                    # The one place the fallback is spelled out, next to the boxes that do
                    # not show it. It is also what `project lint`'s `test.audience` asks.
                    "" if test.audiences else f"No audience set — reads as {audience_words(test)}",
                    outcome_line(outcome),
                )
                if part
            )
        )

    def _show_category(self, test: Test) -> None:
        """The picker's entries, and the one this test carries.

        Rebuilt rather than diffed: a project's categories are few, and the list can have
        gained one since the last look — the category editor's Save is exactly that.
        *Uncategorised* is the first entry and carries no name, so the picker can always
        say what an unfiled test is without the catalogue having to hold a word for it.
        """
        entries = [(UNCATEGORISED, "")]
        if self._step_id is not None and self._library.has(self._step_id):
            project = self._library.project_of(self._step_id)
            entries += [(entry.name, entry.name) for entry in catalog(project)]
        # A test filed under something the catalogue lost still shows it: the value is the
        # test's, and a picker that quietly moved it to Uncategorised would be an edit.
        if test.category and test.category not in [name for _label, name in entries]:
            entries.append((test.category, test.category))
        self.category.blockSignals(True)
        if [
            (self.category.itemText(i), self.category.itemData(i))
            for i in range(self.category.count())
        ] != entries:
            self.category.clear()
            for label, value in entries:
                self.category.addItem(label, value)
        found = self.category.findData(test.category)
        self.category.setCurrentIndex(found if found >= 0 else 0)
        self.category.blockSignals(False)

    def _show_sort_key(self, test: Test) -> None:
        """The keys already in use as completions, and this test's own in the field.

        An editable combo rather than a plain field: there is no catalogue to pick from,
        but there is a set already in use, and offering it is what stops the same view
        being spelled three ways down one project.
        """
        offered = []
        if self._step_id is not None and self._library.has(self._step_id):
            offered = sort_keys(self._library.project_of(self._step_id))
        self.sort_key.blockSignals(True)
        if [self.sort_key.itemText(i) for i in range(self.sort_key.count())] != offered:
            self.sort_key.clear()
            self.sort_key.addItems(offered)
        if not self.sort_key_field.hasFocus():
            self.sort_key.setEditText(test.sort_key)
        self.sort_key.blockSignals(False)

    def dispose(self) -> None:
        self.body.dispose()

    def _commit_sort_key(self) -> None:
        """One finished edit, one undoable command — ``_commit_category``'s rule."""
        if self._step_id is None or not self._library.has(self._step_id):
            return
        step = self._library.step(self._step_id)
        test = find(read(step), self._test_id)
        wanted = self.sort_key.currentText().strip()
        if test is None or test.sort_key == wanted:
            return
        changed = dataclasses.replace(test, sort_key=wanted)
        self._undo.push(
            SetModuleDataCommand(
                step.id,
                MODULE_ID,
                write(replace(read(step), changed)),
                label=f"Set Test {test.id} Sort Key",
            )
        )
        self._undo.break_coalescing()

    def _commit_category(self, _index: int) -> None:
        """One pick, one undoable command — ``_commit_audience``'s rule for a picker."""
        if self._step_id is None or not self._library.has(self._step_id):
            return
        step = self._library.step(self._step_id)
        test = find(read(step), self._test_id)
        wanted = str(self.category.currentData() or "")
        if test is None or test.category == wanted:
            return
        changed = dataclasses.replace(test, category=wanted)
        self._undo.push(
            SetModuleDataCommand(
                step.id,
                MODULE_ID,
                write(replace(read(step), changed)),
                label=f"Set Test {test.id} Category",
            )
        )
        # A pick is a finished gesture, as a click on an audience box is: the label is the
        # merge key, so without this two picks on one test would fold into one undo step.
        self._undo.break_coalescing()

    def _commit_audience(self, audience_id: str, on: bool) -> None:
        """One toggle, one undoable command.

        ``SetModuleDataCommand`` coalesces on ``(node, module, label)`` with no time
        window, so this owes two things: a label naming the *test*, like the title and the
        body have, so ticking a box on one test never folds into a box on another; and a
        seal afterwards, because a click is a finished gesture and the two boxes of one
        test would otherwise merge into a single step.
        """
        if self._step_id is None or not self._library.has(self._step_id):
            return
        step = self._library.step(self._step_id)
        test = find(read(step), self._test_id)
        if test is None or (audience_id in test.audiences) == on:
            return
        wanted = set(test.audiences) | {audience_id} if on else set(test.audiences) - {audience_id}
        changed = dataclasses.replace(
            test, audiences=tuple(a.id for a in AUDIENCES if a.id in wanted)
        )
        self._undo.push(
            SetModuleDataCommand(
                step.id,
                MODULE_ID,
                write(replace(read(step), changed)),
                label=f"Set Test {test.id} Audience",
            )
        )
        # A click is a finished gesture, so the next one starts its own step. The label
        # alone would not do it: it is the merge key, and both boxes of one test share it.
        self._undo.break_coalescing()

    def _commit_title(self) -> None:
        if self._step_id is None or not self._library.has(self._step_id):
            return
        step = self._library.step(self._step_id)
        test = find(read(step), self._test_id)
        if test is None or test.title == self.title.text():
            return
        changed = dataclasses.replace(test, title=self.title.text())
        self._undo.push(
            SetModuleDataCommand(
                step.id, MODULE_ID, write(replace(read(step), changed)), label="Rename Test"
            )
        )


class CoversSection(_TestListSection):
    """What a collector stands for: the tests behind it, read-only, with their last results.

    A check, a feature and a milestone are one derivation asked with a different stopping
    rule, so this is one tab for all three. What differs is where its cone stops: a
    milestone gathers the features behind it and not the ones an earlier milestone already
    took, and each of those features becomes a group heading here.

    The **mode** matters only when there is something to stop at, so the switch appears
    exactly when the truncated walk found a boundary — which is never for a check, and not
    for the first milestone in a project either. A control with one outcome is noise.
    """

    ADDS = "What it adds"
    EVERYTHING = "Everything behind it"

    def __init__(
        self,
        library: Library,
        scopes: tuple[ScopeKind, ...],
        open_in_tests: Callable[[StepId], None],
        *,
        debounce: DebounceService | None = None,
    ) -> None:
        super().__init__(library, COVERS_NOTE)

        self._scopes = scopes
        self._open_in_tests = open_in_tests

        self.mode_bar = QWidget(self)
        mode_row = QHBoxLayout(self.mode_bar)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(BUTTON_GAP)
        self.mode = QButtonGroup(self)
        self.mode.setExclusive(True)
        for index, label in enumerate((self.ADDS, self.EVERYTHING)):
            button = QToolButton(self.mode_bar)
            button.setObjectName("ToolbarButton")
            button.setText(label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.mode.addButton(button, index)
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        self.mode.button(0).setChecked(True)
        self.mode.idClicked.connect(lambda _id: self._refresh())
        self.mode_bar.hide()
        # Above the lane, under the note: it says which reading is on screen, so it has to
        # be read before the list rather than found under it. The base class has already
        # laid out note, lane, empty-message, so this goes in at the note's heel.
        self.outer.insertWidget(1, self.mode_bar)

        self.summary = QLabel(self)
        self.summary.setObjectName("InspectorNote")
        self.open_button = QPushButton("Open in Tests", self)
        self.open_button.clicked.connect(self._open)
        row = QHBoxLayout()
        row.addWidget(self.summary, 1)
        row.addWidget(self.open_button)
        self.outer.addLayout(row)

        # After a quiet spell, not per signal: the lane is rebuilt from a cone walk.
        self._refresh_soon = Debounced(self._refresh, parent=self, service=debounce)
        self._unsubscribes = [
            # What a collector gathers is read off its own project; no prose is involved.
            follow_target(
                library,
                lambda: self._target_id,
                self._refresh_soon.trigger,
                signals=(
                    library.module_data_changed,
                    library.edges_changed,
                    library.structure_changed,
                    library.field_changed,
                ),
            ),
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
            self.mode_bar.hide()
            self.say("No step selected.")
            self.summary.setText("")
            self.open_button.setEnabled(False)
            return
        project = self._library.project_of(self._target_id)
        kind = kind_of(self._scopes, self._library.step(self._target_id))
        stops_at = kind.stops_at if kind is not None else None

        # The truncated walk is computed whichever mode is showing: its boundaries are what
        # say whether there is a second reading to offer at all, and the cumulative walk has
        # none by construction.
        own = cone(self._library, project, self._target_id, stops_at=stops_at)
        self.mode_bar.setVisible(bool(own.boundaries))
        cumulative = bool(own.boundaries) and self.mode.checkedId() == 1
        walked = own if not cumulative else cone(self._library, project, self._target_id)

        outcomes = runs.latest_results(runs.read(project))
        groups = [
            (self._group_title(leader), self._gathered(project, leader))
            for leader in (leaders(self._scopes, kind, walked.steps) if kind else [])
        ]
        claimed = {test.id for _title, held in groups for _step, test in held}
        direct = [
            (step, test)
            for step, test in covered(
                self._library,
                project,
                self._target_id,
                stops_at=None if cumulative else stops_at,
            )
            if test.id not in claimed
        ]

        self.clear_cards()
        for title, held in groups:
            self.add_card(_GroupHeader(title, self._tally(held, outcomes)))
            for step, test in held:
                self.add_card(_CoveredRow(step.title, test, outcomes.get(test.id)))
        if groups and direct:
            self.add_card(_GroupHeader(DIRECT_GROUP, self._tally(direct, outcomes)))
        for step, test in direct:
            self.add_card(_CoveredRow(step.title, test, outcomes.get(test.id)))

        everything = [pair for _title, held in groups for pair in held] + direct
        self.say(
            ""
            if everything
            else "Nothing yet. This step covers the tests on the steps it waits on — "
            "link it to work that carries tests."
        )
        self.open_button.setEnabled(bool(everything))
        self.summary.setText(self._headline(everything, outcomes))

    def _gathered(self, project: Project, leader: Step) -> list[tuple[Step, Test]]:
        """One group's contents, by that collector's own stopping rule — one level deep."""
        return covered(self._library, project, leader.id, stops_at=stops_for(self._scopes, leader))

    def _group_title(self, leader: Step) -> str:
        kind = kind_of(self._scopes, leader)
        name = leader.title or "Untitled step"
        return f"{kind.label}: {name}" if kind is not None else name

    def _tally(self, pairs: list[tuple[Step, Test]], outcomes: dict[str, runs.Outcome]) -> str:
        total = f"{len(pairs)} test{'' if len(pairs) == 1 else 's'}"
        return self._headline(pairs, outcomes) or total

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


class _GroupHeader(QWidget):
    """What the cards under it belong to: a collector's name, and how its tests last did.

    Drawn only when the walk found a boundary — a check, or a milestone with nothing
    before it, renders the flat list this tab has always shown.
    """

    def __init__(self, title: str, tally: str) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, FIELD_GAP, 0, 0)
        layout.setSpacing(FIELD_GAP)
        caption = QLabel(title, self)
        caption.setObjectName("InspectorCaption")
        caption.setWordWrap(True)
        layout.addWidget(caption, 1)
        count = QLabel(tally, self)
        count.setObjectName("InspectorNote")
        layout.addWidget(count, 0, Qt.AlignmentFlag.AlignTop)


class _CoveredRow(QFrame):
    """One covered test, read-only: what it is, who it is for, which step, how it last did."""

    def __init__(self, step_title: str, test: Test, outcome: runs.Outcome | None) -> None:
        super().__init__()
        self.setObjectName("ToolCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(FIELD_GAP)

        names = QVBoxLayout()
        names.setSpacing(4)  # DESIGN.md: a rich row's lines sit 4 px apart.
        primary = QLabel(test.title or "Untitled test", self)
        primary.setWordWrap(True)
        names.addWidget(primary)
        # The audience rides on the line that already names the step: this row is a glance
        # at what a collector stands for, and who each test is for is part of that.
        secondary = QLabel(f"{step_title or 'Untitled step'} · {audience_words(test)}", self)
        secondary.setObjectName("InspectorNote")
        secondary.setWordWrap(True)
        names.addWidget(secondary)
        layout.addLayout(names, 1)

        chip = StatusChip(self)
        chip.show_status(outcome.result.status if outcome else "pending")
        layout.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
