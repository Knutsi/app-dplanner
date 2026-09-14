"""Tests in the running application: two tabs, an index folder, and the verbs.

**What lives here and what does not.** This module owns the Test aspect, the runs, and every
surface that shows either. It also owns the *Covers* tab that a check step gets, because
that tab is a list of tests — ``step_check`` contributes only the marker and its toggle, and
is handed to this module as a predicate.

**One open run per project.** Every result verb reads the project from the context and the
run from the project, so "mark this ok" is a pure function of what the user has in front of
them. Starting a run closes whatever was open, which is what makes that true.

**Disabled, never hidden.** A result verb with no run open is greyed and says so, naming the
verb that fixes it. A capability absent from the build is what HIDDEN is for, and none of
these are.
"""

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from dplanner.domain.commands import Command, CompositeCommand, SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.scope import ScopeKind, gatherers, kind_of, stops_for
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    selection_uri,
)
from dplanner.framework.debounce import DebounceService
from dplanner.framework.dialog import LinePrompt
from dplanner.framework.dictation import DictationService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.mime_files import Payload
from dplanner.framework.project_list_segment import LeadingRow, ProjectListSegment
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import notice
from dplanner.modules.testing import runs
from dplanner.modules.testing.activity import (
    ALL_TESTS_KIND,
    TESTS_KIND,
    AllTestsActivity,
    TestsActivity,
)
from dplanner.modules.testing.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    SourceFacts,
    Test,
    TestSource,
    covered,
    enabled,
    next_test_id,
    project_tests,
    read,
    write,
)
from dplanner.modules.testing.export import ExportDialog, gather, write_pack
from dplanner.modules.testing.pack import default_name
from dplanner.modules.testing.section import CoversSection, TestsSection
from dplanner.modules.testing.view import RESULT_ORDER, word
from dplanner.theme.icons import (
    beaker_icon,
    check_icon,
    close_icon,
    eraser_icon,
    export_icon,
    list_icon,
    play_icon,
    project_icon,
    skip_icon,
    stop_icon,
)

# What each result's verb wears on the strip and in the Step ▸ Test menu.
RESULT_GLYPHS = {
    "ok": check_icon,
    "failed": close_icon,
    "skipped": skip_icon,
    "pending": eraser_icon,
}
NO_RUN = "start a test run first (Project ▸ New Test Run)"


def _no_color(_step_id: str) -> str:
    """No colour map reaches this build; a heading is the secondary ink it always was."""
    return ""


def _bare_facts(_project_id: NodeId, source: TestSource) -> SourceFacts:
    """A source printed as the pointer it is — what a build with neither the spec module
    nor the notes module can honestly say about one."""
    return SourceFacts(label=source.words)


def _no_opening(_project_id: NodeId, _source: TestSource) -> None:
    """Nothing to open: the same build again. A source still reads; it just goes nowhere."""


@dataclass(frozen=True)
class TestsDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    debounce: DebounceService
    sections: InspectorSectionRegistry
    segments: IndexSegmentRegistry
    theme: ThemeService
    parent: QWidget  # confirm()'s and the run dialog's parent, as the delete verb's is.
    # Every kind of collector this build knows: a check, a feature, a milestone. Each says
    # what carries it and where its cone stops, so this module renders what any of them
    # gathers without learning that any of those aspects exist. Named by the composition
    # root, the one place allowed to know all three.
    scopes: tuple[ScopeKind, ...]
    # Which of those kinds is the *release* grain and which is the *feature* grain, by id.
    # The Tests tab filters its feature list by the first and files an exported pack under
    # the second, and neither may be guessed from a spelling: a module never learns another
    # module's id, so the composition root says which is which. Empty means this build has
    # no such kind, and the surfaces that read them simply offer less.
    release_kind: str = ""
    feature_kind: str = ""
    # The store's file areas — how a test body's images are attached and shown. They are
    # the *step's* files, the same ones `dplanner test attach` writes; None is a build
    # without file storage.
    files: FilesFor | None = None
    # Insert from Assets…: a modal picker over the step's project's catalog, composed by
    # the root. Node id in, picked payloads out; None is a build without the browser.
    pick_assets: Callable[[str], "list[Payload]"] | None = None
    # A milestone's own shade of the project's colour map, "" for anything else — what a
    # *Group by ▸ Milestone* heading is written in. Wired by the composition root; this
    # module never learns which map a project uses.
    milestone_color: Callable[[str], str] = field(default=_no_color)
    # Dictation into the editors; None is a build without a microphone.
    dictation: DictationService | None = None
    # What a test's source is *called* where it lives, and what it says. The record holds
    # a pointer and nothing else, so a document's name and a note's title are asked of
    # whoever owns them — composed by the root, which is the one place that may know both
    # the spec module and the notes module exist.
    source_facts: Callable[[NodeId, TestSource], SourceFacts] = field(default=_bare_facts)
    # Following one: the Specs tab on that document with the passage washed, or the notes
    # tab on that note. Composed by the root for the same reason.
    open_source: Callable[[NodeId, TestSource], None] = field(default=_no_opening)
    # Writing the picked tests out as a pack somebody can take away. None is a build
    # without the export dialog; the verb is then greyed with its reason rather than gone.
    export: "Callable[[NodeId, Sequence[str]], None] | None" = None


class TestsModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: TestsDeps) -> None:
        self._deps = deps

    # -- opening ---------------------------------------------------------------------------

    def open(self, project_id: NodeId, *, preview: bool = False, scope: StepId = "") -> None:
        activity = self._deps.tabs.open(TESTS_KIND, project_id, preview=preview)
        if scope and isinstance(activity, TestsActivity):
            activity.show_scope(scope)

    def open_all(self, *, preview: bool = False) -> None:
        self._deps.tabs.open(ALL_TESTS_KIND, preview=preview)

    # -- registration ----------------------------------------------------------------------

    def register(self) -> None:
        deps = self._deps
        deps.tabs.register_factory(TESTS_KIND, self._tests_factory)
        deps.tabs.register_factory(ALL_TESTS_KIND, self._all_factory)
        follow_entity_tabs(
            deps.tabs,
            TestsActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )
        deps.segments.register(
            IndexSegment(
                id="tests",
                label="Tests",
                order=20,  # Directly below Projects, which is 10.
                factory=self._segment,
                icon=list_icon,
            )
        )
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label="Tests",
                order=30,  # Between Ticket (20) and Agent (40).
                factory=lambda: TestsSection(
                    deps.library, deps.undo, deps.files, deps.pick_assets, deps.dictation
                ),
                shown_for=lambda step_id: (
                    self._step(step_id) is not None and enabled(deps.library.step(step_id or ""))
                ),
            )
        )
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.covers",
                label="Covers",
                order=35,  # Beside the Tests tab; a step can carry both.
                factory=lambda: CoversSection(
                    deps.library, deps.scopes, self._open_scope, debounce=deps.debounce
                ),
                shown_for=lambda step_id: (
                    self._step(step_id) is not None
                    and kind_of(deps.scopes, deps.library.step(step_id or "")) is not None
                ),
            )
        )
        for spec in self._action_specs():
            deps.actions.register(spec)

    def _tests_factory(self, target: str | None) -> TestsActivity:
        assert target is not None
        return TestsActivity(self._deps, target)

    def _all_factory(self, _target: str | None) -> AllTestsActivity:
        deps = self._deps
        return AllTestsActivity(
            deps.library, deps.context, self._open_details, deps.debounce, deps.source_facts
        )

    def _segment(self, root: QTreeWidgetItem) -> ProjectListSegment:
        """A row per project, under an *All Projects* row: tests are the one surface that is
        also cross-project, and the roll call has no project to sit under."""
        deps = self._deps
        return ProjectListSegment(
            root,
            deps.library,
            deps.context,
            deps.actions,
            deps.theme,
            key_prefix="tests",
            menu="Project",
            project_icon=project_icon,
            open_project=lambda project_id, preview: self.open(project_id, preview=preview),
            leading=LeadingRow(
                "All Projects", list_icon, lambda preview: self.open_all(preview=preview)
            ),
        )

    def _action_specs(self) -> list[ActionSpec]:
        return [
            aspect_toggle(
                id="test.toggle",
                label=SPEC.label,
                order=50,
                module_id=MODULE_ID,
                library=self._deps.library,
                undo=self._deps.undo,
                enabled=enabled,
                # The list is the marker: turning on adds one blank test to fill in,
                # exactly as Add Test does, unless the shelf has the old roster.
                fresh=lambda _step, project: write([Test(id=next_test_id(project), title="")]),
                icon=beaker_icon,
                tip="Give this step tests: what must keep passing once the work is done",
            ),
            ActionSpec(
                id="test.add",
                label="&Add Test",
                menu="Step",
                group="classify",
                submenu="Test",
                # The 300s: Test is the third child menu of the classify band, and a child
                # menu sits at its first entry's order. See dplanner/menus.py.
                order=310,
                tip="Another test on this step, with its own result in every run",
                state=self._on_a_step,
                run=self._add,
            ),
            ActionSpec(
                id="test.archive",
                label="Archive Test",
                menu="Step",
                group="classify",
                submenu="Test",
                order=320,
                tip="Take the selected tests off the roster; their history is kept",
                state=lambda context: self._archive_state(context, archived=True),
                run=lambda context: self._set_archived(context, archived=True),
            ),
            ActionSpec(
                id="test.unarchive",
                label="Put Test Back",
                menu="Step",
                group="classify",
                submenu="Test",
                order=330,
                tip="Put the selected tests back on the roster",
                state=lambda context: self._archive_state(context, archived=False),
                run=lambda context: self._set_archived(context, archived=False),
            ),
            *[
                ActionSpec(
                    id=f"test.result_{status}",
                    label=f"Mark {word(status)}" if status != "pending" else "Clear Result",
                    menu="Step",
                    group="test_result",
                    submenu="Test",
                    order=(index + 1) * 10,
                    tip=f"Record the selected tests as {word(status).lower()} in the open run",
                    icon=RESULT_GLYPHS[status],
                    state=self._result_state_for(status),
                    run=self._marker(status),
                )
                for index, status in enumerate(RESULT_ORDER)
            ],
            ActionSpec(
                id="tests.new_run",
                label="&New Test Run",
                menu="Project",
                group="tests",
                order=10,
                tip="Open a run over this project's tests — or over what its Tests tab is "
                "narrowed to; every one starts unrecorded",
                icon=play_icon,
                state=self._new_run_state,
                run=self._new_run,
            ),
            ActionSpec(
                id="tests.close_run",
                label="Close Test Run",
                menu="Project",
                group="tests",
                order=20,
                tip="Close the open run; anything unmarked stays unrecorded",
                icon=stop_icon,
                state=self._close_run_state,
                run=self._close_run,
            ),
            ActionSpec(
                id="test.open_origin",
                label="Open Origin Step",
                menu="Step",
                group="test_open",
                submenu="Test",
                order=10,
                tip="The step this test hangs off, in the step panel",
                state=self._origin_state,
                run=self._open_origin,
            ),
            ActionSpec(
                id="test.open_feature",
                label="Open Origin Feature",
                menu="Step",
                group="test_open",
                submenu="Test",
                order=20,
                tip="The feature this test's step flows into",
                state=self._feature_state,
                run=self._open_feature,
            ),
            ActionSpec(
                id="tests.export",
                label="Export &Tests…",
                menu="File",
                group="export",
                submenu="Export",
                order=40,  # After the report's HTML/PDF and the tables' workbook.
                tip="Write the picked tests out as markdown with their screenshots — a "
                "pack for whoever is going to run them",
                icon=export_icon,
                state=self._export_state,
                run=self._export,
            ),
            ActionSpec(
                id="tests.open",
                label="Show &Tests",
                menu="Project",
                group="open",
                order=50,
                tip="Every test this project keeps, and how each one last did",
                state=self._on_a_project,
                run=self._open_tests,
            ),
            ActionSpec(
                id="tests.open_step",
                label="Show &Tests",
                menu="Step",
                group="open",
                order=40,
                palette=False,  # The same verb's second seat, on the Step menu.
                state=self._on_a_project,
                run=self._open_tests,
            ),
        ]

    # -- reading the context ---------------------------------------------------------------

    def _step(self, step_id: str | None) -> Step | None:
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return self._deps.library.step(step_id)

    def _focused_step(self, context: Context) -> Step | None:
        return self._step(context.focus_entity("step"))

    def _focused_project(self, context: Context) -> Project | None:
        project_id = context.focus_entity("project")
        if project_id is not None and self._deps.library.has(project_id):
            return self._deps.library.project(project_id)
        step = self._focused_step(context)
        return None if step is None else self._deps.library.project_of(step.id)

    def _selected_tests(self, context: Context) -> list[tuple[Step, Test]]:
        wanted = set(context.selected_entities("test"))
        project = self._focused_project(context)
        if not wanted or project is None:
            return []
        return [pair for pair in project_tests(project, archived=True) if pair[1].id in wanted]

    def _open_run(self, context: Context) -> tuple[Project, runs.Run] | None:
        project = self._focused_project(context)
        if project is None:
            return None
        found = runs.open_run(runs.read(project))
        return None if found is None else (project, found)

    def _on_a_step(self, context: Context) -> ActionState:
        return DISABLED if self._focused_step(context) is None else ActionState()

    def _add(self, context: Context) -> None:
        step = self._focused_step(context)
        if step is None:
            return
        project = self._deps.library.project_of(step.id)
        added = Test(id=next_test_id(project), title="")
        self._deps.undo.push(
            SetModuleDataCommand(step.id, MODULE_ID, write([*read(step), added]), label="Add Test")
        )

    # -- archiving -------------------------------------------------------------------------

    def _archive_state(self, context: Context, *, archived: bool) -> ActionState:
        pairs = self._selected_tests(context)
        if not pairs:
            return ActionState(enabled=False, label=None)
        if not any(test.archived != archived for _step, test in pairs):
            word_for = "already archived" if archived else "already on the roster"
            label = "Archive Test" if archived else "Put Test Back"
            return ActionState(enabled=False, label=f"{label} — {word_for}")
        return ActionState()

    def _set_archived(self, context: Context, *, archived: bool) -> None:
        pairs = [pair for pair in self._selected_tests(context) if pair[1].archived != archived]
        if not pairs:
            return
        wanted = {test.id for _step, test in pairs}
        by_step: dict[StepId, list[Test]] = {}
        for step, _test in pairs:
            by_step.setdefault(
                step.id,
                [
                    dataclasses.replace(test, archived=archived) if test.id in wanted else test
                    for test in read(step)
                ],
            )
        self._push_many(by_step, "Archive Test" if archived else "Restore Test")

    def _push_many(self, by_step: dict[StepId, list[Test]], label: str) -> None:
        """One undo step, however many steps the selection spanned."""
        commands: list[Command] = [
            SetModuleDataCommand(step_id, MODULE_ID, write(tests), label=label)
            for step_id, tests in by_step.items()
        ]
        if not commands:
            return
        self._deps.undo.push(
            commands[0] if len(commands) == 1 else CompositeCommand(label, commands)
        )

    # -- results ---------------------------------------------------------------------------

    def _result_state_for(self, status: str) -> Callable[[Context], ActionState]:
        return lambda context: self._result_state(context, status)

    def _marker(self, status: str) -> Callable[[Context], None]:
        return lambda context: self._mark_from(context, status)

    def _result_state(self, context: Context, status: str) -> ActionState:
        label = f"Mark {word(status)}" if status != "pending" else "Clear Result"
        pairs = self._selected_tests(context)
        if not pairs:
            return ActionState(enabled=False, label=f"{label} — pick a test")
        found = self._open_run(context)
        if found is None:
            return ActionState(enabled=False, label=f"{label} — {NO_RUN}")
        _project, run = found
        count = sum(1 for _step, test in pairs if test.id in run.tests)
        if not count:
            return ActionState(
                enabled=False,
                label=f"{label} — not in the open run, which holds what it was opened over",
            )
        if count > 1:
            # The count says the verb is about to act on more than the eye is on.
            many = (
                f"Mark {count} Tests {word(status)}"
                if status != "pending"
                else f"Clear {count} Results"
            )
            return ActionState(label=many)
        return ActionState()

    def _mark_from(self, context: Context, status: str) -> None:
        found = self._open_run(context)
        if found is None:
            return
        project, run = found
        wanted = [test.id for _step, test in self._selected_tests(context) if test.id in run.tests]
        self.mark(project.id, run.id, wanted, status)

    def mark(self, project_id: NodeId, run_id: str, test_ids: list[str], status: str) -> None:
        """Record a result for several tests as one undo step — the table's buttons too."""
        project = self._deps.library.project(project_id)
        records = runs.read(project)
        run = runs.find(records, run_id)
        if run is None or not test_ids:
            return
        for test_id in test_ids:
            run = runs.marked(run, test_id, status)
        self._deps.undo.push(
            SetModuleDataCommand(
                project_id,
                MODULE_ID,
                runs.write(runs.replaced(records, run)),
                label=f"Mark {word(status)}",
            )
        )

    # -- runs ------------------------------------------------------------------------------

    def _new_run_state(self, context: Context) -> ActionState:
        project = self._focused_project(context)
        if project is None:
            return DISABLED
        if not project_tests(project):
            return ActionState(enabled=False, label="New Test Run — this project has no tests yet")
        return ActionState()

    def _new_run(self, context: Context) -> None:
        project = self._focused_project(context)
        if project is not None:
            self.start_run(project.id, self._narrowed_to(project.id))

    def _narrowed_to(self, project_id: NodeId) -> StepId:
        """The collector the project's Tests tab is narrowed to, or "": a run opened from its
        strip covers what the tab is showing."""
        return next(
            (
                activity.scope
                for activity in self._deps.tabs.activities()
                if isinstance(activity, TestsActivity) and activity.project_id == project_id
            ),
            "",
        )

    def start_run(self, project_id: NodeId, scope: StepId) -> None:
        """Ask for a name, then open a run over the scope. Closes whatever was open."""
        deps = self._deps
        project = deps.library.project(project_id)
        scoped = project.step(scope) if scope else None
        # Truncated where the collector's own kind stops, so a run opened from the strip
        # covers exactly the rows the tab is showing — the list on the left and the run
        # must never mean two different things by "this feature".
        pairs = (
            covered(
                deps.library,
                project,
                scope,
                stops_at=stops_for(deps.scopes, scoped),
            )
            if scoped is not None
            else project_tests(project)
        )
        if not pairs:
            return
        records = runs.read(project)
        suggestion = f"Run {runs.next_run_id(records)[1:]}"
        where = (scoped.title or "that step") if scoped else "every test"
        count = f"{len(pairs)} test{'' if len(pairs) == 1 else 's'}"
        label = LinePrompt.ask(
            deps.parent,
            "New Test Run",
            f"Name — a run over {where}, {count}, every one unrecorded",
            "Start",
            text=suggestion,
            validate=lambda typed: None if typed.strip() else "A run needs a name",
        )
        if label is None:
            return
        started = runs.started(
            records, [test.id for _step, test in pairs], label=label.strip(), scope=scope
        )
        deps.undo.push(
            SetModuleDataCommand(project_id, MODULE_ID, runs.write(started), label="Start Test Run")
        )

    def _close_run_state(self, context: Context) -> ActionState:
        if self._focused_project(context) is None:
            return DISABLED
        if self._open_run(context) is None:
            return ActionState(enabled=False, label="Close Test Run — no run is open")
        return ActionState()

    def _close_run(self, context: Context) -> None:
        found = self._open_run(context)
        if found is None:
            return
        project, run = found
        records = runs.read(project)
        self._deps.undo.push(
            SetModuleDataCommand(
                project.id,
                MODULE_ID,
                runs.write(runs.replaced(records, runs.closed(run))),
                label="Close Test Run",
            )
        )

    # -- navigation ------------------------------------------------------------------------

    def _on_a_project(self, context: Context) -> ActionState:
        return DISABLED if self._focused_project(context) is None else ActionState()

    def _open_tests(self, context: Context) -> None:
        project = self._focused_project(context)
        if project is not None:
            self.open(project.id)

    # -- where a test came from, and taking the tests away ---------------------------------

    def _origin_state(self, context: Context) -> ActionState:
        pairs = self._selected_tests(context)
        if not pairs:
            return ActionState(enabled=False, label="Open Origin Step — pick a test")
        return ActionState()

    def _open_origin(self, context: Context) -> None:
        pairs = self._selected_tests(context)
        if pairs:
            self._open_details(pairs[0][0].id)

    def _feature_of(self, context: Context) -> Step | None:
        """The feature the picked test's step flows into, or None.

        The first, when two features both wait on the step: the same case
        ``dplanner project lint`` names ``scope.shared``, and picking one of them is a
        better answer than a greyed verb on a step that plainly is in a feature.
        """
        pairs = self._selected_tests(context)
        if not pairs:
            return None
        step = pairs[0][0]
        project = self._deps.library.project_of(step.id)
        kind = next(
            (found for found in self._deps.scopes if found.id == self._deps.feature_kind), None
        )
        if kind is None:
            return None
        owners = gatherers(
            self._deps.library, project, carried_by=kind.carried_by, stops_at=kind.stops_at
        )
        return next(
            (
                found
                for owner in owners.get(step.id, ())
                if (found := project.step(owner)) is not None
            ),
            None,
        )

    def _feature_state(self, context: Context) -> ActionState:
        if not self._selected_tests(context):
            return ActionState(enabled=False, label="Open Origin Feature — pick a test")
        if self._feature_of(context) is None:
            return ActionState(
                enabled=False,
                label="Open Origin Feature — no feature gathers this test's step",
            )
        return ActionState()

    def _open_feature(self, context: Context) -> None:
        found = self._feature_of(context)
        if found is not None:
            self._open_details(found.id)

    def _export_state(self, context: Context) -> ActionState:
        project = self._focused_project(context)
        if project is None:
            return DISABLED
        if self._deps.export is None:
            return ActionState(enabled=False, label="Export Tests… — not in this build")
        if not project_tests(project):
            return ActionState(enabled=False, label="Export Tests… — this project has no tests")
        picked = len(self._selected_tests(context))
        if picked > 1:
            # The count says the verb is about to act on more than the eye is on — the
            # same courtesy the result verbs pay.
            return ActionState(label=f"Export {picked} Tests…")
        return ActionState()

    def _export(self, context: Context) -> None:
        project = self._focused_project(context)
        export = self._deps.export
        if project is None or export is None:
            return
        # Nothing picked means the whole roster: the dialog says which, and a reader who
        # picked nothing asked for the project rather than for an empty pack.
        export(project.id, [test.id for _step, test in self._selected_tests(context)])

    def export_tests(self, project_id: NodeId, wanted: Sequence[str]) -> Path | None:
        """Gather, ask, write, say — the whole gesture; answers where the pack landed.

        Public because it *is* the export: the verb above is handed it by the composition
        root as ``TestsDeps.export`` so a build without a window can leave it out, and a
        test can run the whole thing without a menu.
        """
        deps = self._deps
        project = deps.library.project(project_id)
        pack = gather(
            deps.library,
            project,
            wanted=wanted,
            scope=self._narrowed_to(project_id),
            scopes=deps.scopes,
            feature_kind=deps.feature_kind,
            facts_for=lambda source: deps.source_facts(project_id, source),
            files=deps.files,
        )
        dialog = ExportDialog(pack.note, default_name(pack.project), deps.parent)
        dialog.exec()
        chosen = dialog.chosen()
        dialog.deleteLater()
        if chosen is None:
            return None
        landed = write_pack(chosen.format.render(pack), chosen.path, zipped=chosen.zipped)
        # What a gesture came to after its dialog closed is a notice, never a message box.
        notice(deps.parent, "Export Tests", f"{len(pack.tests)} tests written to {landed}")
        return landed

    def _open_scope(self, step_id: StepId) -> None:
        project = self._deps.library.project_of(step_id)
        self.open(project.id, scope=step_id)

    def _open_details(self, step_id: StepId) -> None:
        """Double-clicking a test opens its step, here as everywhere else in the window.

        The roll call spans projects, so it cannot publish a selection the way a
        project-scoped tab does; the context is synthesised for exactly this row instead —
        the same thing the progression board does for a card's own verb.
        """
        if not self._deps.library.has(step_id):
            return
        self._deps.actions.run(
            "steps.details",
            Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)}),
        )
