"""The Tests tabs: one project's roster and runs, and the library-wide roll call.

**Two activities, one table.** The project tab can start a run and mark results; the
library one is a read-only roll call across every project, because a run belongs to a
project and a run spanning several would have nowhere honest to live.

**Lead with the answer.** The staffing matrix taught this: a grid of numbers with no
sentence over it makes every reader do the arithmetic. So the first thing on the page is
"38 of 42 passing" — or, in a run, how many are left to do.

**The Run selector is the mode.** The table shows either the latest result per test or one
run's results, and which of those is a dropdown rather than hidden state. Marking is
possible only in the open run, which is the same rule the verbs are gated on: a project has
at most one open run, so "mark this ok" never has to ask which.
"""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.scope import gatherers, kind_of
from dplanner.framework.action_menu import build_menu
from dplanner.framework.activity import ActivityBase, EntityActivity
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.module_data_section import PANEL_MARGIN
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import covered, project_tests
from dplanner.modules.testing.table import Row, TestsTable
from dplanner.modules.testing.view import word
from dplanner.theme.icons import ICON_SIZE

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.testing.module import TestsDeps

TESTS_KIND = "tests"
ALL_TESTS_KIND = "all_tests"

CAPTION_GAP = 6
BLOCK_GAP = 12
CONTROL_GAP = 8
# Wide enough for a run's name and its (open) suffix; a combo that elides its own
# contents makes the reader open it to find out what it says.
SELECTOR_WIDTH = 180

TAB_NOTE = "Everything this project verifies, and how it last did."
ALL_NOTE = "Every test in every project in this library, and how it last did."

ROSTER = "Latest results"
ALL_TESTS = "All tests"
NO_GROUPING = "Flat list"
# A test on a step nothing collects: work that reaches no release. `dplanner project lint`
# reports the same steps as `scope.ungathered`, so the two surfaces say one thing.
UNGATHERED = "Not in any feature"


def headline(statuses: Sequence[str], *, run: runs.Run | None = None) -> tuple[str, str]:
    """The sentence and its footnote: what a reader came to find out, before the table."""
    counts = runs.tally(statuses)
    total = len(statuses)
    detail = ", ".join(
        f"{count} {word(status).lower()}" for status, count in counts.items() if count
    )
    if run is None:
        if not total:
            return "No tests yet", ""
        return f"{counts['ok']} of {total} passing", detail
    label = run.label or run.id
    if run.is_open and counts["pending"]:
        # Still going: what is left is the useful number, not the verdict it does not have.
        return f"{label} — {counts['pending']} to go", detail
    # Finished, open or closed: lead with what it found, because that is why anyone looks.
    failed = counts["failed"]
    verdict = f"{failed} failed" if failed else "all clear"
    return f"{label} — {verdict}", detail


def _control_bar(parent: QWidget) -> QToolBar:
    """A toolbar that overflows into its » menu instead of squeezing its contents."""
    bar = QToolBar(parent)
    bar.setObjectName("TestsToolBar")
    bar.setMovable(False)
    bar.setFloatable(False)
    bar.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    inner = bar.layout()
    if inner is not None:
        inner.setSpacing(CONTROL_GAP)
        inner.setContentsMargins(0, 0, 0, 0)
    return bar


class _TestsPage(QWidget):
    """The shared page: caption, the answer, then the table. Both activities host one."""

    def __init__(self, caption: str, note: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        title = QLabel(caption, self)
        title.setObjectName("InspectorCaption")
        layout.addWidget(title)

        subtitle = QLabel(note, self)
        subtitle.setObjectName("InspectorNote")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(BLOCK_GAP)

        self.answer = QLabel(self)
        answer_font = self.answer.font()
        answer_font.setPointSizeF(answer_font.pointSizeF() + 2.0)
        self.answer.setFont(answer_font)
        layout.addWidget(self.answer)

        self.detail = QLabel(self)
        self.detail.setObjectName("InspectorNote")
        layout.addWidget(self.detail)
        layout.addSpacing(BLOCK_GAP)

        # Two toolbars rather than a layout of widgets: a QToolBar too narrow for its
        # contents grows the » overflow button and puts the tail in a menu, where a plain
        # row simply overlaps. The split is so the primary action stays right-aligned —
        # the left bar takes the slack and is the one that ever needs to overflow.
        strip = QHBoxLayout()
        strip.setSpacing(CONTROL_GAP)
        self.controls = _control_bar(self)
        self.actions_bar = _control_bar(self)
        strip.addWidget(self.controls, 1)
        strip.addWidget(self.actions_bar)
        layout.addLayout(strip)
        layout.addSpacing(CONTROL_GAP)

        self.table = TestsTable(self)
        layout.addWidget(self.table, 1)

        self.empty = QLabel(self)
        self.empty.setObjectName("InspectorNote")
        self.empty.setWordWrap(True)
        self.empty.hide()
        layout.addWidget(self.empty)

    def say(self, message: str) -> None:
        """A tab cannot go off screen the way a panel does, so it says so in words."""
        self.empty.setText(message)
        self.empty.setVisible(bool(message))
        self.table.setVisible(not message)

    def lead(self, answer: str, detail: str) -> None:
        self.answer.setText(answer)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))


class TestsActivity(EntityActivity):
    """One project's tests: the roster, the runs, and the marking."""

    def __init__(
        self,
        deps: "TestsDeps",
        project_id: NodeId,
        *,
        mark: Callable[[NodeId, str, list[str], str], None],
        start_run: Callable[[NodeId, StepId], None],
    ) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._mark_tests = mark
        self._start_a_run = start_run
        self._library = deps.library
        self.project_id = project_id
        self._scope: StepId = ""
        self._run_id: str = ""
        self._group: str = ""

        self.page = _TestsPage("Tests", TAB_NOTE)
        self.scope_box = QComboBox(self.page)
        self.scope_box.setToolTip("Which tests to show: all of them, or one check's")
        self.scope_box.setMinimumWidth(SELECTOR_WIDTH)
        self.scope_box.currentIndexChanged.connect(self._on_scope)
        self.run_box = QComboBox(self.page)
        self.run_box.setToolTip("The latest result per test, or one run's")
        self.run_box.setMinimumWidth(SELECTOR_WIDTH)
        self.run_box.currentIndexChanged.connect(self._on_run)
        self.group_box = QComboBox(self.page)
        self.group_box.setToolTip("Read the list flat, or filed under what collects each test")
        self.group_box.setMinimumWidth(SELECTOR_WIDTH)
        self.group_box.currentIndexChanged.connect(self._on_group)
        self.archived = QCheckBox("Show archived", self.page)
        self.archived.toggled.connect(lambda _on: self._refresh())

        self.mark_buttons = [
            self._mark_button(status) for status in ("ok", "failed", "skipped", "pending")
        ]
        self.new_run = QPushButton("New Run…", self.page)
        self.new_run.setObjectName("PrimaryButton")
        self.new_run.clicked.connect(self._start_run)

        # No "Scope" / "Run" captions: a caption and its combo would have to overflow as
        # one, and the entries say what they are anyway ("All tests", "Check: …"). The
        # tooltips carry the long form. Filters live on the left bar, which is the one
        # allowed to overflow; the primary action stays on the right, always reachable.
        # A toolbar overflows from its right end, so the order is most-used first. While a
        # run is open, marking is what the user is here to do and the filters are the ones
        # that may go into the » menu; with no run open the marking controls are not on
        # screen at all, so the filters lead. The run's identity is never lost to the menu:
        # the headline above already names it.
        controls = self.page.controls
        self.marking_note = QLabel("Record as", controls)
        self.marking_note.setObjectName("InspectorNote")
        self._marking_actions = [controls.addWidget(self.marking_note)]
        self._marking_actions += [controls.addWidget(button) for button in self.mark_buttons]
        self._marking_separator = controls.addSeparator()
        controls.addWidget(self.scope_box)
        controls.addWidget(self.run_box)
        # Held, because a toolbar wraps a widget in an action and it is the *action* that
        # carries visibility — setting it on the combo alone leaves an empty slot behind.
        self.group_action = controls.addWidget(self.group_box)
        controls.addWidget(self.archived)
        self.page.actions_bar.addWidget(self.new_run)

        table = self.page.table
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_context_menu)
        table.itemSelectionChanged.connect(self._on_selection)
        table.cellActivated.connect(self._on_activated)

        self._unsubscribes = [
            self._library.structure_changed.connect(lambda *_a: self._refresh()),
            self._library.edges_changed.connect(lambda *_a: self._refresh()),
            self._library.field_changed.connect(lambda *_a: self._refresh()),
            self._library.module_data_changed.connect(lambda *_a: self._refresh()),
        ]
        self._refresh()

    # -- the activity contract -----------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(TESTS_KIND, self.project_id)

    @property
    def title(self) -> str:
        return f"{self._project().title or 'Untitled project'} — Tests"

    @property
    def widget(self) -> QWidget:
        return self.page

    def on_activated(self) -> None:
        super().on_activated()
        self._on_selection()

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    def show_scope(self, step_id: StepId) -> None:
        """Open scoped to one check or release — what the Covers tab's button asks for."""
        self._scope = step_id
        self._refresh()

    def _on_scope(self, _index: int) -> None:
        self._scope = str(self.scope_box.currentData() or "")
        self._refresh()

    def _on_run(self, _index: int) -> None:
        self._run_id = str(self.run_box.currentData() or "")
        self._refresh()

    def _on_group(self, _index: int) -> None:
        self._group = str(self.group_box.currentData() or "")
        self._refresh()

    # -- internals -----------------------------------------------------------------------

    def _project(self) -> Project:
        return self._library.project(self.project_id)

    def _records(self) -> list[runs.Run]:
        return runs.read(self._project())

    def _current_run(self) -> runs.Run | None:
        return runs.find(self._records(), self._run_id) if self._run_id else None

    def _rows(self) -> list[Row]:
        project = self._project()
        archived = self.archived.isChecked()
        if self._scope and project.step(self._scope) is not None:
            pairs = covered(self._library, project, self._scope, archived=archived)
        else:
            pairs = project_tests(project, archived=archived)
        records = self._records()
        run = self._current_run()
        outcomes = runs.latest_results(records)
        scopes = self._scope_titles(project, records)
        if run is not None:
            pairs = [pair for pair in pairs if pair[1].id in run.tests]
        groups = self._groups(project)
        rows = [
            Row(
                test=test,
                step=step,
                covered_by=scopes.get(test.id, ()),
                outcome=outcomes.get(test.id),
                status=(
                    run.result(test.id).status
                    if run is not None
                    else (outcomes[test.id].result.status if test.id in outcomes else "pending")
                ),
                group=groups[step.id][1] if groups else "",
            )
            for step, test in pairs
        ]
        if not groups:
            return rows
        # Stable, so within a group the rows keep the project order they arrived in. The
        # sort key is where the collector sits in that same order, which is why an
        # ungathered row sorts last rather than alphabetically among the named ones.
        return sorted(rows, key=lambda row: groups[row.step.id][0])

    def _groups(self, project: Project) -> dict[StepId, tuple[int, str]]:
        """Each step's heading, and where it sorts — empty when nothing is being grouped.

        A step two features both wait on is filed under *both at once*, as one joint
        heading, rather than duplicated into each: a test listed twice would be marked
        twice and counted twice. ``dplanner project lint`` reports the same steps as
        ``scope.shared`` so the ambiguity is nameable rather than merely visible.
        """
        kind = next((found for found in self._deps.scopes if found.id == self._group), None)
        if kind is None:
            return {}
        owners = gatherers(
            self._library, project, carried_by=kind.carried_by, stops_at=kind.stops_at
        )
        places = {step.id: index for index, step in enumerate(project.steps)}
        last = len(places)
        found: dict[StepId, tuple[int, str]] = {}
        for step in project.steps:
            held = [project.step(owner) for owner in owners.get(step.id, ())]
            named = [owner for owner in held if owner is not None]
            if not named:
                found[step.id] = (last, UNGATHERED)
                continue
            # The kind is named once, however many owners there are: "Feature: Import and
            # Search", not the label twice.
            names = " and ".join(owner.title or "Untitled step" for owner in named)
            title = f"{kind.label}: {names}"
            found[step.id] = (places[named[0].id], title)
        return found

    def _scope_titles(
        self, project: Project, _records: Sequence[runs.Run]
    ) -> dict[str, tuple[str, ...]]:
        """Which checks and releases each test sits behind — the *Covered by* column."""
        found: dict[str, list[str]] = {}
        for step in self._scope_steps(project):
            for _owner, test in covered(self._library, project, step.id, archived=True):
                found.setdefault(test.id, []).append(step.title or "Untitled step")
        return {test_id: tuple(titles) for test_id, titles in found.items()}

    def _scope_steps(self, project: Project) -> list[Step]:
        return [step for step in project.steps if kind_of(self._deps.scopes, step) is not None]

    def _refresh(self) -> None:
        if not self._library.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        project = self._project()
        self._sync_scopes(project)
        self._sync_runs()
        self._sync_grouping(project)
        rows = self._rows()
        self.page.table.show_rows(rows)
        run = self._current_run()
        self.page.lead(*headline([row.status for row in rows], run=run))
        self.page.say(self._nothing_to_show(project, rows))
        self._sync_buttons(run)

    def _nothing_to_show(self, project: Project, rows: Sequence[Row]) -> str:
        if rows:
            return ""
        if not project_tests(project, archived=True):
            return (
                "No tests yet. Add one from a step's Tests tab — mark the step with "
                "Step ▸ Type ▸ Test — or run `dplanner test add <step> '<title>'`."
            )
        if self._current_run() is not None:
            return "This run holds no tests in the current scope."
        return "Nothing in this scope. Every test here is archived, or the scope is empty."

    def _sync_scopes(self, project: Project) -> None:
        entries = [(ALL_TESTS, "")] + [
            (f"{self._scope_kind_label(step)}: {step.title or 'Untitled step'}", step.id)
            for step in self._scope_steps(project)
        ]
        self._reload(self.scope_box, entries, self._scope)
        self._scope = str(self.scope_box.currentData() or "")

    def _scope_kind_label(self, step: Step) -> str:
        kind = kind_of(self._deps.scopes, step)
        return kind.label if kind is not None else ""

    def _sync_grouping(self, project: Project) -> None:
        """Only kinds this project actually has: a selector offering nothing teaches nothing."""
        entries = [(NO_GROUPING, "")] + [
            (f"By {kind.label.lower()}", kind.id)
            for kind in self._deps.scopes
            if any(kind.carried_by(step) for step in project.steps)
        ]
        self._reload(self.group_box, entries, self._group)
        self._group = str(self.group_box.currentData() or "")
        # A project with nothing to group by shows no control at all, rather than one with
        # a single entry — DESIGN.md's rule that an empty box is worse than no box.
        self.group_action.setVisible(len(entries) > 1)

    def _sync_runs(self) -> None:
        records = self._records()
        entries = [(ROSTER, "")] + [
            (f"{run.label or run.id}{' (open)' if run.is_open else ''}", run.id)
            for run in reversed(records)
        ]
        self._reload(self.run_box, entries, self._run_id)
        self._run_id = str(self.run_box.currentData() or "")

    def _reload(self, box: QComboBox, entries: list[tuple[str, str]], keep: str) -> None:
        if [(box.itemText(i), box.itemData(i)) for i in range(box.count())] == entries:
            return
        box.blockSignals(True)
        box.clear()
        for label, value in entries:
            box.addItem(label, value)
        index = box.findData(keep)
        box.setCurrentIndex(index if index >= 0 else 0)
        box.blockSignals(False)

    def _sync_buttons(self, run: runs.Run | None) -> None:
        # Marking belongs to the open run and nowhere else: a closed run is a record, and
        # the roster is every run at once. The row goes off screen rather than greying.
        markable = run is not None and run.is_open
        self._marking_separator.setVisible(markable)
        for action in self._marking_actions:
            action.setVisible(markable)
        picked = bool(self.page.table.selected_tests())
        self.marking_note.setText("Record as" if picked else "Select a test, then")
        for button in self.mark_buttons:
            button.setEnabled(markable and picked)
        self.new_run.setEnabled(bool(project_tests(self._project())))
        self.new_run.setToolTip(
            "Open a run over the current scope; every test in it starts unrecorded"
            if self.new_run.isEnabled()
            else "This project has no tests yet"
        )

    def _mark_button(self, status: str) -> QPushButton:
        label = "Clear" if status == "pending" else word(status)
        button = QPushButton(label, self.page.controls)
        button.setObjectName("ToolbarButton")
        button.setToolTip(f"Record the selected tests as {word(status).lower()}")
        button.clicked.connect(lambda _checked=False, s=status: self._mark(s))
        return button

    def _mark(self, status: str) -> None:
        run = self._current_run()
        selected = self.page.table.selected_tests()
        if run is None or not run.is_open or not selected:
            return
        self._mark_tests(self.project_id, run.id, selected, status)

    def _start_run(self) -> None:
        self._start_a_run(self.project_id, self._scope)
        self._run_id = ""  # The new run becomes the open one; _sync_runs picks it up.
        records = self._records()
        opened = runs.open_run(records)
        if opened is not None:
            self._run_id = opened.id
        self._refresh()

    # -- context ------------------------------------------------------------------------

    def _on_selection(self) -> None:
        table = self.page.table
        steps = dict.fromkeys(table.selected_steps())
        tests = table.selected_tests()
        nodes = tuple(ContextNode(selection_uri("step", step_id)) for step_id in steps) + tuple(
            ContextNode(selection_uri("test", test_id)) for test_id in tests
        )
        self.publish_selection(nodes)
        self._sync_buttons(self._current_run())

    def _on_activated(self, row: int, _column: int) -> None:
        step_id = self.page.table.step_at(row)
        if step_id is None:
            return
        self._deps.actions.run(
            "steps.details",
            Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)}),
        )

    def _on_context_menu(self, position: QPoint) -> None:
        table = self.page.table
        row = table.rowAt(position.y())
        if table.test_at(row) is None:
            return
        if table.test_at(row) not in table.selected_tests():
            table.selectRow(row)
        menu = build_menu(self._deps.actions, self._deps.context, "Step", table)
        menu.exec(table.viewport().mapToGlobal(position))


class AllTestsActivity(ActivityBase):
    """Every test in the library, read-only — one roll call across the projects.

    A singleton activity: there is no node standing for the library, so this has no target
    and no entity to follow. Deliberately read-only for now; a run belongs to a project.
    """

    def __init__(
        self, library: Library, context: ContextService, open_step: Callable[[StepId], None]
    ) -> None:
        super().__init__()
        self._library = library
        self._context = context
        self._open_step = open_step
        self.uri = activity_uri(ALL_TESTS_KIND)
        self.title = "Tests — All Projects"

        self.page = _TestsPage("Tests", ALL_NOTE)
        self.page.table.setSelectionMode(self.page.table.SelectionMode.SingleSelection)
        self.page.table.cellActivated.connect(self._on_activated)
        self.widget = self.page

        self._unsubscribes = [
            library.structure_changed.connect(lambda *_a: self._refresh()),
            library.field_changed.connect(lambda *_a: self._refresh()),
            library.module_data_changed.connect(lambda *_a: self._refresh()),
        ]
        self._refresh()

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    def _refresh(self) -> None:
        rows: list[Row] = []
        for project in self._library.projects:
            outcomes = runs.latest_results(runs.read(project))
            for step, test in project_tests(project):
                outcome = outcomes.get(test.id)
                rows.append(
                    Row(
                        test=test,
                        step=step,
                        project=project.title or "Untitled project",
                        outcome=outcome,
                        status=outcome.result.status if outcome else "pending",
                    )
                )
        self.page.table.show_rows(rows, show_project=True)
        self.page.lead(*headline([row.status for row in rows]))
        self.page.say(
            ""
            if rows
            else "No tests in this library yet. Open a project and mark a step with "
            "Step ▸ Type ▸ Test."
        )

    def _on_activated(self, row: int, _column: int) -> None:
        step_id = self.page.table.step_at(row)
        if step_id is not None:
            self._open_step(step_id)
