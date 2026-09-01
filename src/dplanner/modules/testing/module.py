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

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QTreeWidgetItem, QWidget

from dplanner.domain.commands import Command, CompositeCommand, SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.scope import ScopeKind, kind_of
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    selection_uri,
)
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.project_list_segment import LeadingRow, ProjectListSegment
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
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
    Test,
    covered,
    enabled,
    next_test_id,
    project_tests,
    read,
    write,
)
from dplanner.modules.testing.section import CoversSection, TestsSection
from dplanner.modules.testing.view import word
from dplanner.theme.icons import list_icon, project_icon

RESULT_ORDER = ("ok", "failed", "skipped", "pending")
NO_RUN = "start a test run first (Project ▸ New Test Run)"


@dataclass(frozen=True)
class TestsDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    sections: InspectorSectionRegistry
    segments: IndexSegmentRegistry
    theme: ThemeService
    parent: QWidget  # confirm()'s and the run dialog's parent, as the delete verb's is.
    # Every kind of collector this build knows: a check, a feature, a milestone. Each says
    # what carries it and where its cone stops, so this module renders what any of them
    # gathers without learning that any of those aspects exist. Named by the composition
    # root, the one place allowed to know all three.
    scopes: tuple[ScopeKind, ...]
    # The store's file areas — how a test body's images are attached and shown. They are
    # the *step's* files, the same ones `dplanner test attach` writes; None is a build
    # without file storage.
    files: FilesFor | None = None


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
                factory=lambda: TestsSection(deps.library, deps.undo, deps.files),
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
                factory=lambda: CoversSection(deps.library, deps.scopes, self._open_scope),
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
        # The two verbs the tab hosts buttons for arrive as functions, not as a back
        # reference: the module holds the Deps the activity is handed, so a field on them
        # pointing here would be a cycle for no gain.
        return TestsActivity(self._deps, target, mark=self.mark, start_run=self.start_run)

    def _all_factory(self, _target: str | None) -> AllTestsActivity:
        return AllTestsActivity(self._deps.library, self._deps.context, self._open_details)

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
            ActionSpec(
                id="test.toggle",
                label=SPEC.label,
                menu="Step",
                group="classify",
                submenu="Type",
                order=50,
                tip="Give this step tests: what must keep passing once the work is done",
                state=self._toggle_state,
                run=self._toggle,
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
                tip="Open a run over this project's tests; every one starts unrecorded",
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
                state=self._close_run_state,
                run=self._close_run,
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

    # -- the Type toggle -------------------------------------------------------------------

    def _toggle_state(self, context: Context) -> ActionState:
        step = self._focused_step(context)
        if step is None:
            return DISABLED
        return ActionState(checked=enabled(step))

    def _toggle(self, context: Context) -> None:
        step = self._focused_step(context)
        if step is None:
            return
        tests = read(step)
        if not tests:
            self._add(context)
            return
        count = f"{len(tests)} test{'' if len(tests) == 1 else 's'}"
        question = (
            f"Remove all {count} from {step.title or 'this step'!r}? The tests are not kept; "
            "archiving one keeps it and its results instead."
        )
        if not confirm(self._deps.parent, "Clear Tests", question):
            return
        self._deps.undo.push(SetModuleDataCommand(step.id, MODULE_ID, {}, label="Clear Tests"))

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
                    Test(test.id, test.title, test.body, archived) if test.id in wanted else test
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
            return ActionState(enabled=False, label=None)
        found = self._open_run(context)
        if found is None:
            return ActionState(enabled=False, label=f"{label} — {NO_RUN}")
        _project, run = found
        if not any(test.id in run.tests for _step, test in pairs):
            return ActionState(
                enabled=False,
                label=f"{label} — not in the open run, which holds what it was opened over",
            )
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
            self.start_run(project.id, "")

    def start_run(self, project_id: NodeId, scope: StepId) -> None:
        """Ask for a name, then open a run over the scope. Closes whatever was open."""
        deps = self._deps
        project = deps.library.project(project_id)
        pairs = (
            covered(deps.library, project, scope)
            if scope and project.step(scope) is not None
            else project_tests(project)
        )
        if not pairs:
            return
        records = runs.read(project)
        suggestion = f"Run {runs.next_run_id(records)[1:]}"
        scoped = project.step(scope) if scope else None
        where = (scoped.title or "that step") if scoped else "every test"
        label, accepted = QInputDialog.getText(
            deps.parent,
            "New Test Run",
            f"A run over {where} — {len(pairs)} test{'' if len(pairs) == 1 else 's'}, all "
            "starting unrecorded.\n\nWhat should it be called?",
            text=suggestion,
        )
        if not accepted:
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
