"""The Tests tabs: one project's roster and runs, and the library-wide roll call.

**Two activities, one table.** The project tab can start a run and mark results; the
library one is a read-only roll call across every project, because a run belongs to a
project and a run spanning several would have nowhere honest to live.

**Lead with the answer.** The staffing matrix taught this: a grid of numbers with no
sentence over it makes every reader do the arithmetic. So the first thing on the page is
"38 of 42 passing" — or, in a run, how many are left to do.

**The strip is the registry's.** New Run, Close Run and the four results are the verbs the
Project and Step menus hold, rendered as glyphs: greyed with the reason until a run is open
and a test is picked, worded with the count when several are. After a divider comes the
view — which tests, which run's results, how they are grouped, whether the archived show.

**The Run selector is the mode.** The table shows either the latest result per test or one
run's results, and which of those is a dropdown rather than hidden state. Marking is
possible only in the open run, which is the same rule the verbs are gated on: a project has
at most one open run, so "mark this ok" never has to ask which.
"""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.scope import gatherers, kind_of
from dplanner.framework.action_menu import build_menu
from dplanner.framework.activity import ActivityBase, EntityActivity, follow_project
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
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.table import Selection
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import EmptyState, captioned, note
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import covered, project_tests
from dplanner.modules.testing.table import Row, TestsTable
from dplanner.modules.testing.view import RESULT_ORDER, word
from dplanner.theme.cards import title_font
from dplanner.theme.icons import archive_icon
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.testing.module import TestsDeps

TESTS_KIND = "tests"
ALL_TESTS_KIND = "all_tests"

TAB_HINT = "Everything this project verifies, and how it last did."
ALL_HINT = "Every test in every project in this library, and how it last did."
ARCHIVED_TIP = "List the tests taken off the roster as well"
# Creation first, then what acts on the picked tests (DESIGN.md's *Tables*).
RUN_VERBS = ("tests.new_run", "tests.close_run", *(f"test.result_{s}" for s in RESULT_ORDER))

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


def _selector(parent: QWidget, tip: str) -> QComboBox:
    box = QComboBox(parent)
    box.setToolTip(tip)
    # As wide as what it says: a combo that elides its own entry makes the reader open it.
    box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    return box


class _TestsPage(QWidget):
    """The shared page: the caption, the answer, the strip, then the table."""

    def __init__(self, caption: str, hint: str, *, selection: Selection) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)

        head = QVBoxLayout()
        layout.addLayout(head)  # Before it is filled: a parentless layout leaks its items.
        head.setSpacing(CAPTION_GAP)
        head.addWidget(captioned(caption, self, hint=hint))
        self.answer = QLabel(self)
        self.answer.setFont(title_font(self.answer.font()))
        head.addWidget(self.answer)
        self.detail = note("", self)
        head.addWidget(self.detail)

        self.strip = QHBoxLayout()
        layout.addLayout(self.strip)
        self.strip.setSpacing(FIELD_GAP)
        self.controls = Toolbar(self)
        self.strip.addWidget(self.controls, 1)
        # Outside the strip, so folding the verbs into … can never take it.
        self.updating = UpdatingIndicator(self)
        self.strip.addWidget(self.updating)

        self.table = TestsTable(self, selection=selection)
        layout.addWidget(self.table, 1)
        self.empty = EmptyState(parent=self, stands_in_for=self.table)
        layout.addWidget(self.empty, 1)

    def say(self, message: str) -> None:
        """A tab cannot go off screen the way a panel does, so it says so in words."""
        self.empty.say(message)

    def lead(self, answer: str, detail: str) -> None:
        self.answer.setText(answer)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))


class TestsActivity(EntityActivity):
    """One project's tests: the roster, the runs, and the marking."""

    def __init__(self, deps: "TestsDeps", project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._library = deps.library
        self.project_id = project_id
        self._scope: StepId = ""
        self._run_id: str = ""
        self._group: str = ""
        # The runs the tab has already seen: a run opened since the last look is the one to
        # show, since marking in it is what the person just asked for.
        self._runs_seen: set[str] | None = None

        self.page = _TestsPage("Tests", TAB_HINT, selection="extended")
        controls = self.page.controls
        for action_id in RUN_VERBS:
            controls.add_action(deps.actions, deps.context, action_id)
        controls.add_divider()
        self.scope_box = _selector(
            self.page, "Which tests to show: all of them, or one collector's"
        )
        self.scope_box.currentIndexChanged.connect(self._on_scope)
        self.run_box = _selector(self.page, "The latest result per test, or one run's")
        self.run_box.currentIndexChanged.connect(self._on_run)
        self.group_box = _selector(
            self.page, "Read the list flat, or filed under what collects each test"
        )
        self.group_box.currentIndexChanged.connect(self._on_group)
        for box in (self.scope_box, self.run_box, self.group_box):
            controls.add_widget(box)
        self.archived = controls.add_verb(
            "Show archived", archive_icon, self._refresh, checkable=True, tip=ARCHIVED_TIP
        )

        table = self.page.table
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_context_menu)
        table.itemSelectionChanged.connect(self._on_selection)
        table.cellActivated.connect(self._on_activated)

        library = self._library
        # After a quiet spell, not per signal: the table is rebuilt row by row.
        self._refresh_soon = Debounced(self._refresh, parent=self.page, service=deps.debounce)
        self.updating = self.page.updating
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            # This project only, and no prose: tests are records, titles are fields.
            follow_project(
                library,
                self.project_id,
                self._refresh_soon.trigger,
                signals=(
                    library.structure_changed,
                    library.edges_changed,
                    library.field_changed,
                    library.module_data_changed,
                ),
            ),
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

    @property
    def scope(self) -> StepId:
        """The collector the tab is narrowed to, or "" — what a run opened from here covers."""
        return self._scope

    def on_activated(self) -> None:
        super().on_activated()
        self._on_selection()

    def close(self) -> None:
        self._refresh_soon.cancel()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.page.controls.dispose()

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
                group_color=groups[step.id][2] if groups else "",
            )
            for step, test in pairs
        ]
        if not groups:
            return rows
        # Stable, so within a group the rows keep the project order they arrived in. The
        # sort key is where the collector sits in that same order, which is why an
        # ungathered row sorts last rather than alphabetically among the named ones.
        return sorted(rows, key=lambda row: groups[row.step.id][0])

    def _groups(self, project: Project) -> dict[StepId, tuple[int, str, str]]:
        """Each step's heading, where it sorts and what colour it is written in — empty
        when nothing is being grouped.

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
        found: dict[StepId, tuple[int, str, str]] = {}
        for step in project.steps:
            held = [project.step(owner) for owner in owners.get(step.id, ())]
            named = [owner for owner in held if owner is not None]
            if not named:
                found[step.id] = (last, UNGATHERED, "")
                continue
            # The kind is named once, however many owners there are: "Feature: Import and
            # Search", not the label twice.
            names = " and ".join(owner.title or "Untitled step" for owner in named)
            title = f"{kind.label}: {names}"
            # A joint heading takes the first owner's colour — the same one it sorts by, so
            # the heading a reader sees is the milestone the group is filed under.
            found[step.id] = (
                places[named[0].id],
                title,
                self._deps.milestone_color(named[0].id),
            )
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
        # A run opening or closing changes what the strip's verbs can do without changing
        # the selection, and a strip the registry feeds restates when the context is heard.
        self._deps.context.refresh()

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
        self.page.controls.set_shown(self.group_box, len(entries) > 1)

    def _sync_runs(self) -> None:
        records = self._records()
        opened = runs.open_run(records)
        if self._runs_seen is not None and opened is not None and opened.id not in self._runs_seen:
            self._run_id = opened.id
        self._runs_seen = {run.id for run in records}
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

    # -- context ------------------------------------------------------------------------

    def _on_selection(self) -> None:
        table = self.page.table
        steps = dict.fromkeys(table.selected_steps())
        tests = table.selected_tests()
        nodes = tuple(ContextNode(selection_uri("step", step_id)) for step_id in steps) + tuple(
            ContextNode(selection_uri("test", test_id)) for test_id in tests
        )
        self.publish_selection(nodes)

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
        self,
        library: Library,
        context: ContextService,
        open_step: Callable[[StepId], None],
        debounce: DebounceService,
    ) -> None:
        super().__init__()
        self._library = library
        self._context = context
        self._open_step = open_step
        self.uri = activity_uri(ALL_TESTS_KIND)
        self.title = "Tests — All Projects"

        self.page = _TestsPage("Tests", ALL_HINT, selection="single")
        self.archived = self.page.controls.add_verb(
            "Show archived", archive_icon, self._refresh, checkable=True, tip=ARCHIVED_TIP
        )
        self.page.table.cellActivated.connect(self._on_activated)
        self.widget = self.page

        # After a quiet spell: the roll call walks every project's tests and hears the whole
        # library, so a burst of edits anywhere is one rebuild rather than one per signal.
        self._refresh_soon = Debounced(self._refresh, parent=self.page, service=debounce)
        self.updating = self.page.updating
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            signal.connect(lambda *_a: self._refresh_soon.trigger())
            for signal in (
                library.structure_changed,
                library.field_changed,
                library.module_data_changed,
            )
        ]
        self._refresh()

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))

    def close(self) -> None:
        self._refresh_soon.cancel()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.page.controls.dispose()

    def _refresh(self) -> None:
        rows: list[Row] = []
        archived = self.archived.isChecked()
        for project in self._library.projects:
            outcomes = runs.latest_results(runs.read(project))
            for step, test in project_tests(project, archived=archived):
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
