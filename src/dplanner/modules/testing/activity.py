"""The Tests tabs: one project's roster and runs, and the library-wide roll call.

**Two activities, one table.** The project tab can start a run and mark results; the
library one is a read-only roll call across every project, because a run belongs to a
project and a run spanning several would have nowhere honest to live.

**Lead with the answer.** The staffing matrix taught this: a grid of numbers with no
sentence over it makes every reader do the arithmetic. So the first thing on the page is
"38 of 42 passing" — or, in a run, how many are left to do.

**The strip is the registry's.** New Run, Close Run, the four results and Export are the
verbs the Project, Step and File menus hold, rendered as glyphs: greyed with the reason
until a run is open and a test is picked, worded with the count when several are. After a
divider comes the view — which run's results, how they are grouped, whether the archived
show.

**The Run selector is the mode.** The table shows either the latest result per test or one
run's results, and which of those is a dropdown rather than hidden state. Marking is
possible only in the open run, which is the same rule the verbs are gated on: a project has
at most one open run, so "mark this ok" never has to ask which.

**Three panes, and each answers a different question.** Which feature is being tested is
the standing list on the left (``collectors.py``) — it replaced a *scope* dropdown, because
a tester picks one over and over and a control they use every minute must not be one they
have to open first. What the tests are is the table. Where the picked one came from is the
pane under it (``sources.py``). The step a test hangs off is *not* a column here: the panel
a double-click opens says it, and the reader of a roster is after what is being proved.

**The right-click is the Test submenu and nothing else.** A table of tests offering Delete
Step, Link and Run Agent offers a page of verbs about something the reader did not click
on. ``build_menu``'s ``submenu`` filter renders the Step menu's *Test* child — the results,
the archive pair, and the two verbs that open where a test came from — so this is still a
menu rendered rather than a menu copied.
"""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.scope import gatherers, kind_of, stops_for
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
from dplanner.framework.widgets import EmptyState, captioned, note, wrapped_tooltip
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import (
    UNGATHERED,
    SourceFacts,
    Test,
    TestSource,
    covered,
    find,
    project_tests,
    read,
)
from dplanner.modules.testing.collectors import (
    PANE_WIDTH,
    CollectorPane,
    collectors,
    listed,
    milestones_of,
)
from dplanner.modules.testing.sources import SourcesPane, kind_words
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
RUN_VERBS = (
    "tests.new_run",
    "tests.close_run",
    *(f"test.result_{s}" for s in RESULT_ORDER),
    "tests.export",
)

ROSTER = "Latest results"
NO_GROUPING = "Flat list"


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
    """The shared page: the caption, the answer, the strip, then the table and its panes.

    The two activities take different parts of it. The roll call is a table and nothing
    else — a feature list is one project's fact, and a source pane would have to resolve
    against whichever project each row came from. The project tab takes all three, parted
    by splitters: the seam belongs to the splitter and neither pane draws an edge of its
    own (``CLAUDE.md``'s *A seam belongs to the splitter*).
    """

    def __init__(
        self,
        caption: str,
        hint: str,
        *,
        selection: Selection,
        panes: bool = False,
        open_source: Callable[[TestSource], None] | None = None,
    ) -> None:
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
        self.empty = EmptyState(parent=self, stands_in_for=self.table)
        self.collectors: CollectorPane | None = None
        self.sources: SourcesPane | None = None
        if not panes:
            layout.addWidget(self.table, 1)
            layout.addWidget(self.empty, 1)
            return

        assert open_source is not None
        self.collectors = CollectorPane(self)
        rows = QWidget(self)
        rows_layout = QVBoxLayout(rows)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(0)
        rows_layout.addWidget(self.table, 1)
        rows_layout.addWidget(self.empty, 1)
        self.sources = SourcesPane(open_source, self)

        self.down = QSplitter(Qt.Orientation.Vertical, self)
        self.down.setChildrenCollapsible(False)
        self.down.addWidget(rows)
        self.down.addWidget(self.sources)
        self.down.setStretchFactor(0, 3)
        self.down.setStretchFactor(1, 1)

        self.across = QSplitter(Qt.Orientation.Horizontal, self)
        self.across.setChildrenCollapsible(False)
        self.across.addWidget(self.collectors)
        self.across.addWidget(self.down)
        self.across.setStretchFactor(0, 0)
        self.across.setStretchFactor(1, 1)
        self.across.setSizes([PANE_WIDTH, PANE_WIDTH * 3])
        layout.addWidget(self.across, 1)

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
        # What each source resolved to, for the length of one rebuild. See `_facts`.
        self._facts_memo: dict[tuple[str, str, str, int | None], SourceFacts] = {}

        self.page = _TestsPage(
            "Tests", TAB_HINT, selection="extended", panes=True, open_source=self._open_source
        )
        controls = self.page.controls
        for action_id in RUN_VERBS:
            controls.add_action(deps.actions, deps.context, action_id)
        controls.add_divider()
        self.run_box = _selector(self.page, "The latest result per test, or one run's")
        self.run_box.currentIndexChanged.connect(self._on_run)
        self.group_box = _selector(
            self.page, "Read the list flat, or filed under what collects each test"
        )
        self.group_box.currentIndexChanged.connect(self._on_group)
        for box in (self.run_box, self.group_box):
            controls.add_widget(box)
        self.archived = controls.add_verb(
            "Show archived", archive_icon, self._refresh, checkable=True, tip=ARCHIVED_TIP
        )

        self.collectors = self.page.collectors
        assert self.collectors is not None
        self.collectors.list.itemSelectionChanged.connect(self._on_collector)
        self.collectors.filter.changed.connect(self._refresh)
        self.sources = self.page.sources
        assert self.sources is not None

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
        """Open narrowed to one collector — what the Covers tab's button asks for.

        The funnel is cleared first: arriving at a feature a milestone filter has hidden
        would land the reader on an empty list and no way of telling why.
        """
        assert self.collectors is not None
        self._scope = step_id
        self.collectors.filter.clear()
        self._refresh()

    def _on_collector(self) -> None:
        assert self.collectors is not None
        self._scope = self.collectors.picked()
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
            pairs = self._covered(project, self._scope, archived=archived)
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
                source_words=self._source_words(test),
                source_tip=self._source_tip(test),
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

    # -- where a test came from ----------------------------------------------------------

    def _facts(self, source: TestSource) -> SourceFacts:
        """What one source is called and what it says, asked of whoever owns it — once.

        Memoised for the length of one rebuild, because resolving a spec source reads the
        project's spec index: asked per row, a roster of two hundred tests would read it
        two hundred times for an answer that cannot change while the table is being
        filled. Cleared at the top of every refresh, so a renamed document still shows
        under its new name on the next one.
        """
        key = (source.kind, source.ref, source.quote, source.page)
        found = self._facts_memo.get(key)
        if found is None:
            found = self._deps.source_facts(self.project_id, source)
            self._facts_memo[key] = found
        return found

    def _source_words(self, test: Test) -> tuple[str, ...]:
        return tuple(self._facts(source).label for source in test.sources)

    def _source_tip(self, test: Test) -> str:
        """The column's tooltip: every source of this test, with what each one says.

        Wrapped, because a quoted passage is a paragraph and Qt lays a plain tooltip on
        one line however long it is.
        """
        if not test.sources:
            return ""
        lines = []
        for source in test.sources:
            facts = self._facts(source)
            lines.append(f"{kind_words(source)} — {facts.label}")
            if facts.detail:
                lines.append(facts.detail.strip())
        return wrapped_tooltip("\n".join(lines))

    def _picked_test(self) -> Test | None:
        """The one test the sources pane is about: the first of the selection.

        The table selects several at a time — marking twelve tests is what a run is made
        of — and *where this came from* is a question about one. The first is the honest
        answer to "which of these", and a selection of one is by far the common case.
        """
        picked = self.page.table.selected_tests()
        if not picked or not self._library.has(self.project_id):
            return None
        return next(
            (
                found
                for step in self._project().steps
                if (found := find(read(step), picked[0])) is not None
            ),
            None,
        )

    def _show_sources(self) -> None:
        assert self.sources is not None
        self.sources.show_sources(self._picked_test(), self._facts)

    def _open_source(self, source: TestSource) -> None:
        self._deps.open_source(self.project_id, source)

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
        self._facts_memo.clear()
        self._sync_collectors(project)
        self._sync_runs()
        self._sync_grouping(project)
        rows = self._rows()
        self.page.table.show_rows(rows, show_step=False)
        run = self._current_run()
        self.page.lead(*headline([row.status for row in rows], run=run))
        self.page.say(self._nothing_to_show(project, rows))
        self._show_sources()
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
        return "Nothing here. Every test in this feature is archived, or it has none yet."

    def _sync_collectors(self, project: Project) -> None:
        """The left list, and the funnel over it. The pick is the tab's scope."""
        pane = self.collectors
        assert pane is not None
        release = self._deps.release_kind
        wanted = pane.show_filters(milestones_of(project, self._deps.scopes, release))
        found = collectors(self._library, project, self._deps.scopes, self._test_count, release)
        self._scope = pane.show_collectors(listed(found, wanted), self._scope)

    def _test_count(self, step_id: StepId) -> int:
        """How many live tests one collector stands for — the number on its row."""
        return len(self._covered(self._project(), step_id))

    def _covered(
        self, project: Project, step_id: StepId, *, archived: bool = False
    ) -> list[tuple[Step, Test]]:
        """The tests one collector *gathers* — its cone truncated where its kind stops.

        Truncated, not cumulative: a feature row means that feature's own work, which is
        what makes the count on the row and the rows in the table the same answer. What
        must pass to *ship* is the milestone's row, which stops one boundary further out.
        """
        step = project.step(step_id)
        return covered(
            self._library,
            project,
            step_id,
            archived=archived,
            stops_at=stops_for(self._deps.scopes, step) if step is not None else None,
        )

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
        self._show_sources()

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
        # The Step menu's *Test* child and nothing else: what a run recorded, the archive
        # pair, and the way back to where the test came from. The whole Step menu here
        # offered Delete Step and Run Agent over a row that is not a step.
        menu = build_menu(self._deps.actions, self._deps.context, "Step", table, submenu="Test")
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
        source_facts: Callable[[NodeId, TestSource], SourceFacts],
    ) -> None:
        super().__init__()
        self._library = library
        self._context = context
        self._open_step = open_step
        self._source_facts = source_facts
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
                        # Resolved per project, because a source's name lives wherever the
                        # source does and the roll call spans every project in the library.
                        source_words=tuple(
                            self._source_facts(project.id, source).label for source in test.sources
                        ),
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
