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

**Grouping is one selector, and the category is one of its answers.** Filing by category,
by feature, by milestone or by check are four ways of asking the same question — *what is
this test one of?* — so they are four entries in one box rather than a second control
beside it. Category leads, and a project that has any categories opens on it: it is the
only grouping that is the tests' own vocabulary rather than the graph's, and it is the one
that makes a roster of two hundred readable. Its headings fold; the graph's do not, because
a feature's tests are already few and the reader asked to see them beside each other.

**And inside a group, the sort key is what makes the list ergonomic.** *Ergonomic order* on
the strip — on by default — orders each group by its tests' sort key, so the tests that
exercise one view are executed one after another instead of scattered down the page. It is
a *sort*, not a second layer of headings: the key shows as a column when any test carries
one, and a reader who wants the plan's own order unticks it. A project that uses no sort
keys is ordered exactly as it was either way.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.scope import ScopeKind, gatherers, kind_of
from dplanner.framework.action_menu import build_menu
from dplanner.framework.activity import ActivityBase, EntityActivity, follow_project
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.table import Selection
from dplanner.framework.toolbar import FilterButton, Toolbar
from dplanner.framework.widgets import EmptyState, captioned, note
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import (
    AUDIENCES,
    Test,
    audiences_of,
    covered,
    project_tests,
)
from dplanner.modules.testing.filing import (
    UNCATEGORISED,
    catalog,
    category_of,
    category_places,
    ergonomic_order,
)
from dplanner.modules.testing.table import Heading, Row, TestsTable
from dplanner.modules.testing.view import RESULT_ORDER, word
from dplanner.theme.cards import title_font
from dplanner.theme.icons import archive_icon, sort_icon
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.testing.module import TestsDeps

TESTS_KIND = "tests"
ALL_TESTS_KIND = "all_tests"

TAB_HINT = "Everything this project verifies, and how it last did."
ALL_HINT = "Every test in every project in this library, and how it last did."
ARCHIVED_TIP = "List the tests taken off the roster as well"
ERGONOMIC_TIP = (
    "Order each group by its tests' sort key, so a run stays in one place at a time — "
    "untick to read them in the plan's own order"
)
AUDIENCE_TIP = "Show only the tests written for these"
NO_MATCH = "No test here is written for those audiences. Clear the filter to see them all."
# Creation first, then what acts on the picked tests (DESIGN.md's *Tables*).
RUN_VERBS = ("tests.new_run", "tests.close_run", *(f"test.result_{s}" for s in RESULT_ORDER))
# The band after them: what acts on the *list* rather than on the tests picked in it.
LIST_VERBS = ("tests.categories", "tests.export")

ROSTER = "Latest results"
ALL_TESTS = "All tests"
NO_GROUPING = "Flat list"
# The grouping that is the tests' own vocabulary rather than the graph's. Not a `ScopeKind`
# id — those name steps that collect tests, and a category names nothing on the graph — so
# it is a word of its own in the same selector.
BY_CATEGORY = "category"
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
        # Built here so both tabs offer the same filter with the same words. It is added to
        # the strip by whoever wants it, in the order that tab reads best.
        self.audience = FilterButton(label="Audience")
        self.audience.face.setToolTip(AUDIENCE_TIP)
        for audience in AUDIENCES:
            self.audience.add_filter(audience.id, audience.label)
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

    def keep_for_audience(self, rows: list[Row]) -> list[Row]:
        """``rows`` narrowed to the picked audiences; all of them while none is picked."""
        wanted = set(self.audience.active())
        if not wanted:
            return rows
        return [row for row in rows if set(audiences_of(row.test)) & wanted]

    def lead_filtered(self, shown: int, total: int, answer: str, detail: str) -> None:
        """Lead with the answer, and say when the answer is only part of the roster.

        A widget among the verbs never folds into the strip's ``…`` — it hides when there is
        no room (``DESIGN.md``) — so on a narrow tab the filter can be applied with nothing
        left on screen saying so. This tab leads with a count, and a count that has silently
        lost rows is a wrong answer, so the line under it carries the narrowing.
        """
        narrowed = f"{shown} of {total} shown" if shown != total else ""
        self.lead(answer, " · ".join(part for part in (narrowed, detail) if part))


@dataclass(frozen=True)
class _Grouping:
    """How the rows are filed: where each one sorts, and the heading it lands under.

    Two functions rather than a map, because the category is a fact about a *test* and a
    collector is a fact about its *step* — one shape asked twice is what keeps the four
    entries in the Group by box from becoming two mechanisms.
    """

    place: Callable[[Step, Test], tuple[int, str]]
    heading: Callable[[Step, Test], Heading]


@dataclass(frozen=True)
class Shown:
    """What one project's Tests tab is narrowed to right now.

    A run opened from the strip covers what the tab is showing, and so does an export —
    which is the whole reason the audience filter is worth reading back rather than asking
    for again in a dialog. *Ergonomic order* is deliberately not here: an export is a run
    sheet whichever way the tab is being read, so it always orders by sort key.
    """

    scope: StepId = ""
    audiences: tuple[str, ...] = ()
    archived: bool = False


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
        # Whether the reader has picked a grouping themselves. Until they have, the tab
        # opens on the category once the project has one — and a project that gains its
        # first category while the tab is open files itself, which is the gesture the
        # category editor's Save *is*. After a pick, their answer stands.
        self._picked_group = False
        # The runs the tab has already seen: a run opened since the last look is the one to
        # show, since marking in it is what the person just asked for.
        self._runs_seen: set[str] | None = None

        self.page = _TestsPage("Tests", TAB_HINT, selection="extended")
        controls = self.page.controls
        for action_id in RUN_VERBS:
            controls.add_action(deps.actions, deps.context, action_id)
        controls.add_divider()
        # What acts on the list rather than on the tests picked in it: how it is filed,
        # and writing it out.
        for action_id in LIST_VERBS:
            controls.add_action(deps.actions, deps.context, action_id)
        controls.add_divider()
        self.scope_box = _selector(
            self.page, "Which tests to show: all of them, or one collector's"
        )
        self.scope_box.currentIndexChanged.connect(self._on_scope)
        # Beside the scope box: both narrow *which tests*, where the run box picks which
        # results and the group box says how they are filed.
        controls.add_widget(self.page.audience)
        self.run_box = _selector(self.page, "The latest result per test, or one run's")
        self.run_box.currentIndexChanged.connect(self._on_run)
        self.group_box = _selector(
            self.page, "Read the list flat, or filed under what collects each test"
        )
        self.group_box.currentIndexChanged.connect(self._on_group)
        for box in (self.scope_box, self.run_box, self.group_box):
            controls.add_widget(box)
        self.ergonomic = controls.add_verb(
            "Ergonomic order", sort_icon, self._refresh, checkable=True, tip=ERGONOMIC_TIP
        )
        # On by default: the sort key exists to make a run sequence, and a key that only
        # sometimes sorts is one nobody can rely on halfway down a list.
        self.ergonomic.setChecked(True)
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
            self.page.audience.changed.connect(self._refresh_soon.trigger),
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

    def ordered_tests(self) -> list[str]:
        """The test ids this tab is showing, in the order it is showing them.

        What *next* means for the Test panel: the reader's own scope, filter and ordering,
        rather than the project's list, which would land them somewhere they are not.
        """
        table = self.page.table
        return [
            found for row in range(table.rowCount()) if (found := table.test_at(row)) is not None
        ]

    def pick_test(self, test_id: str) -> None:
        """Select one row, and publish it — the panel's Next, arriving the ordinary way.

        The table is what owns the selection here, so stepping through is a *table*
        gesture the panel asks for; the panel never publishes (``panel.py``).
        """
        self.page.table.select_tests([test_id])
        self._on_selection()

    def showing(self) -> Shown:
        """Everything the tab is narrowed to — what a run and an export are both cut to."""
        return Shown(
            scope=self._scope,
            audiences=tuple(self.page.audience.active()),
            archived=self.archived.isChecked(),
        )

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
        self._picked_group = True
        self._refresh()

    # -- internals -----------------------------------------------------------------------

    def _project(self) -> Project:
        return self._library.project(self.project_id)

    def _records(self) -> list[runs.Run]:
        return runs.read(self._project())

    def _current_run(self) -> runs.Run | None:
        return runs.find(self._records(), self._run_id) if self._run_id else None

    def _pairs(self, project: Project) -> list[tuple[Step, Test]]:
        """The tests this tab covers, before the audience filter: the scope's, the open
        run's if one is being read, and the archived only while they are asked for."""
        archived = self.archived.isChecked()
        if self._scope and project.step(self._scope) is not None:
            pairs = covered(self._library, project, self._scope, archived=archived)
        else:
            pairs = project_tests(project, archived=archived)
        run = self._current_run()
        return pairs if run is None else [pair for pair in pairs if pair[1].id in run.tests]

    def _rows(self) -> list[Row]:
        project = self._project()
        pairs = self._pairs(project)
        run = self._current_run()
        outcomes = runs.latest_results(self._records())
        filing = self._grouping(project)
        rows = [
            Row(
                test=test,
                step=step,
                status=(
                    run.result(test.id).status
                    if run is not None
                    else (outcomes[test.id].result.status if test.id in outcomes else "pending")
                ),
                heading=Heading() if filing is None else filing.heading(step, test),
            )
            for step, test in pairs
        ]
        ergonomic = self.ergonomic.isChecked()
        if filing is None and not ergonomic:
            return rows

        def where(row: Row) -> tuple[object, ...]:
            group = filing.place(row.step, row.test) if filing is not None else ()
            return (*group, *ergonomic_order(row.test)) if ergonomic else group

        # Stable, so rows the key cannot part keep the project order they arrived in.
        return sorted(rows, key=where)

    def _grouping(self, project: Project) -> "_Grouping | None":
        """How the rows are filed right now, or None while the list is read flat."""
        if self._group == BY_CATEGORY:
            return self._by_category(project)
        kind = next((found for found in self._deps.scopes if found.id == self._group), None)
        return None if kind is None else self._by_collector(project, kind)

    def _by_category(self, project: Project) -> "_Grouping":
        """Filed under what each test says it is — the tests' own vocabulary.

        Per *test*, where every other grouping is per step: a step's three tests may be
        three different kinds of thing, which is most of why the category exists. The
        catalogue's order is the headings' order, and *Uncategorised* is always last.
        """
        entries = catalog(project)
        known = {entry.name.casefold(): entry for entry in entries}
        places = category_places(entries)
        last = len(places)

        def place(_step: Step, test: Test) -> tuple[int, str]:
            name = category_of(test)
            if name == UNCATEGORISED:
                return last + 1, ""
            return places.get(name.casefold(), last), name.casefold()

        def heading(_step: Step, test: Test) -> Heading:
            name = category_of(test)
            found = known.get(name.casefold())
            # Keyed by the category's own words, so what the reader folded shut survives a
            # rebuild — and so folding *Smoke* here folds the same group next time.
            return Heading(name, key=name, glyph=found.icon if found else "")

        return _Grouping(place, heading)

    def _by_collector(self, project: Project, kind: ScopeKind) -> "_Grouping":
        """Filed under what collects each test's step — a feature, a milestone, a check.

        A step two features both wait on is filed under *both at once*, as one joint
        heading, rather than duplicated into each: a test listed twice would be marked
        twice and counted twice. ``dplanner project lint`` reports the same steps as
        ``scope.shared`` so the ambiguity is nameable rather than merely visible.
        """
        owners = gatherers(
            self._library, project, carried_by=kind.carried_by, stops_at=kind.stops_at
        )
        places = {step.id: index for index, step in enumerate(project.steps)}
        last = len(places)
        found: dict[StepId, tuple[int, Heading]] = {}
        for step in project.steps:
            held = [project.step(owner) for owner in owners.get(step.id, ())]
            named = [owner for owner in held if owner is not None]
            if not named:
                found[step.id] = (last, Heading(UNGATHERED))
                continue
            # The kind is named once, however many owners there are: "Feature: Import and
            # Search", not the label twice.
            names = " and ".join(owner.title or "Untitled step" for owner in named)
            # A joint heading takes the first owner's colour — the same one it sorts by, so
            # the heading a reader sees is the milestone the group is filed under.
            found[step.id] = (
                places[named[0].id],
                Heading(f"{kind.label}: {names}", ink=self._deps.milestone_color(named[0].id)),
            )
        return _Grouping(
            lambda step, _test: (found[step.id][0], ""),
            lambda step, _test: found[step.id][1],
        )

    def _scope_steps(self, project: Project) -> list[Step]:
        return [step for step in project.steps if kind_of(self._deps.scopes, step) is not None]

    def _refresh(self) -> None:
        if not self._library.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        project = self._project()
        self._sync_scopes(project)
        self._sync_runs()
        self._sync_grouping(project)
        gathered = self._rows()
        rows = self.page.keep_for_audience(gathered)
        self.page.table.show_rows(rows, show_category=self._group != BY_CATEGORY)
        run = self._current_run()
        self.page.lead_filtered(
            len(rows), len(gathered), *headline([row.status for row in rows], run=run)
        )
        self.page.say(self._nothing_to_show(project, gathered, rows))
        # A run opening or closing changes what the strip's verbs can do without changing
        # the selection, and a strip the registry feeds restates when the context is heard.
        self._deps.context.refresh()

    def _nothing_to_show(
        self, project: Project, gathered: Sequence[Row], rows: Sequence[Row]
    ) -> str:
        if rows:
            return ""
        if gathered:
            return NO_MATCH  # The scope holds tests; the audience filter is what emptied it.
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
        # A plan with nothing to narrow to shows no control at all — the same rule the
        # grouping box keeps, and room the strip would rather give the verbs.
        self.page.controls.set_shown(self.scope_box, len(entries) > 1)

    def _scope_kind_label(self, step: Step) -> str:
        kind = kind_of(self._deps.scopes, step)
        return kind.label if kind is not None else ""

    def _sync_grouping(self, project: Project) -> None:
        """Only kinds this project actually has: a selector offering nothing teaches nothing.

        Category leads the list and is the default *while the project has any* — filing by
        what a test is beats a flat roster, and a project with no categories yet would
        otherwise open on one heading saying *Uncategorised*, which teaches nothing either.
        """
        filed = bool(catalog(project))
        entries = (
            [(NO_GROUPING, "")]
            + ([("By category", BY_CATEGORY)] if filed else [])
            + [
                (f"By {kind.label.lower()}", kind.id)
                for kind in self._deps.scopes
                if any(kind.carried_by(step) for step in project.steps)
            ]
        )
        if not self._group and not self._picked_group and filed:
            self._group = BY_CATEGORY
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
        # And a project with no runs yet has no mode to be in: *Latest results* alone is
        # the only reading there is.
        self.page.controls.set_shown(self.run_box, len(entries) > 1)

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
        """Double-clicking a row here opens the **test**, not its step.

        The one deliberate exception to *double-clicking a step anywhere runs
        `steps.details`* (``CLAUDE.md``), and the reason is that in this table a row **is**
        a test: its step is a column. The Test panel's *Show Step* is the door to the step,
        one click away. ``ARCHITECTURE.md``'s *A test is run from a panel* has the rest.
        """
        table = self.page.table
        if table.test_at(row) is None:
            return
        if table.test_at(row) not in table.selected_tests():
            table.selectRow(row)
        # Published unconditionally, even when the row was already picked: the verb is
        # gated on *one* test being current, and a selection made while this pane was in
        # the background never reached the context (`publish_selection`).
        self._on_selection()
        self._deps.actions.run("test.details", self._deps.context.current())

    def _on_context_menu(self, position: QPoint) -> None:
        """Make what is under the cursor current, then render the Step menu over it.

        On a category heading that means picking the whole group: a heading names a set of
        tests, so *Test ▸ Category ▸ …* over it refiles the category — which is the gesture
        the editor's rename is not, and the one a reader reaches for first.
        """
        table = self.page.table
        row = table.rowAt(position.y())
        under = table.tests_under(row)
        if under:
            table.select_tests(under)
            self._on_selection()
        elif table.test_at(row) is None:
            return
        elif table.test_at(row) not in table.selected_tests():
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
        open_test: Callable[[str], None],
        debounce: DebounceService,
    ) -> None:
        super().__init__()
        self._library = library
        self._context = context
        self._open_test = open_test
        self.uri = activity_uri(ALL_TESTS_KIND)
        self.title = "Tests — All Projects"

        self.page = _TestsPage("Tests", ALL_HINT, selection="single")
        self.page.controls.add_widget(self.page.audience)
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
        self._unsubscribes.append(self.page.audience.changed.connect(self._refresh_soon.trigger))
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
                        status=outcome.result.status if outcome else "pending",
                    )
                )
        shown = self.page.keep_for_audience(rows)
        # Never grouped by category: the roll call spans projects, and two projects' *Smoke*
        # are two categories that happen to share a word. The column says which is which.
        self.page.table.show_rows(shown, show_project=True)
        self.page.lead_filtered(len(shown), len(rows), *headline([row.status for row in shown]))
        self.page.say(self._nothing_to_show(rows, shown))

    def _nothing_to_show(self, rows: Sequence[Row], shown: Sequence[Row]) -> str:
        if shown:
            return ""
        if rows:
            return NO_MATCH
        return (
            "No tests in this library yet. Open a project and mark a step with Step ▸ Type ▸ Test."
        )

    def _on_activated(self, row: int, _column: int) -> None:
        """The same gesture as the project tab's: a row is a test, so it opens the test.

        The roll call publishes no selection of its own — it spans projects — so the verb
        is handed a constructed context naming exactly this row, which is the documented
        way to run a verb on something the user did not select (``CLAUDE.md``).
        """
        test_id = self.page.table.test_at(row)
        if test_id is not None:
            self._open_test(test_id)
