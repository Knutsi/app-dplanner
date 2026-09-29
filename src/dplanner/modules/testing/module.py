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
from dataclasses import dataclass, field
from dataclasses import replace as replace_fields
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QTreeWidgetItem, QWidget

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
from dplanner.framework.activity import follow_project_tabs
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import (
    Context,
    ContextService,
)
from dplanner.framework.debounce import DebounceService
from dplanner.framework.dialog import LinePrompt
from dplanner.framework.dictation import DictationService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.mime_files import Payload
from dplanner.framework.project_list_segment import LeadingRow, ProjectListSegment
from dplanner.framework.step_selection import focused_project
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.testing import export, runs
from dplanner.modules.testing.activity import (
    ALL_TESTS_KIND,
    SIDE_PANEL_ACTION,
    TESTS_KIND,
    AllTestsActivity,
    Shown,
    TestsActivity,
    reveal_test,
)
from dplanner.modules.testing.aspect import (
    AUDIENCES,
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
from dplanner.modules.testing.categories_dialog import CategoriesDialog
from dplanner.modules.testing.section import CoversSection, TestsSection
from dplanner.modules.testing.view import RESULT_ORDER, word
from dplanner.theme.icons import (
    beaker_icon,
    check_icon,
    close_icon,
    eraser_icon,
    external_icon,
    folder_icon,
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
SIDE_PANEL_KEY = "side_panel"


def _no_color(_step_id: str) -> str:
    """No colour map reaches this build; a heading is the secondary ink it always was."""
    return ""


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
    # Where an export is offered to land: the project's reporting location on this
    # machine, when it names one — the folder colleagues read reports from — else the
    # home directory. Wired by the composition root; this module never learns a role id.
    reporting_dir: Callable[[str], Path | None] = lambda _project_id: None
    # Dictation into the editors; None is a build without a microphone.
    dictation: DictationService | None = None
    # A wait is no work, so it has nothing to test: the Test toggle greys on one.
    works_nobody: Callable[[Step], str] = lambda _step: ""


class TestsModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: TestsDeps) -> None:
        self._deps = deps
        # Whether the Test panel stands beside the roster: one per-user answer for every
        # Tests tab, the graph's `Look.side_panel` arrangement. Off until a double-click
        # asks for it.
        self._side_panel = bool(get_global(MODULE_ID, SIDE_PANEL_KEY, False))

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
        follow_project_tabs(deps.tabs, TestsActivity, deps.library)
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
        return TestsActivity(self._deps, target, side_panel=self._side_panel)

    def _all_factory(self, _target: str | None) -> AllTestsActivity:
        return AllTestsActivity(self._deps, side_panel=self._side_panel)

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
                refusal=lambda step: (
                    f"{kind} has no work to test" if (kind := self._deps.works_nobody(step)) else ""
                ),
            ),
            ActionSpec(
                id="test.add",
                label="&Add Test",
                menu="Step",
                group="classify",
                submenu="Test",
                # In no menu, as Type is: a step's tests are added, filed and archived on its
                # Tests tab in Step Details, and recorded from the Tests strip and the Test
                # panel. The palette still finds each under *Step ▸ Test*.
                in_menus=False,
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
                in_menus=False,
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
                in_menus=False,
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
                    group="classify",
                    submenu="Test",
                    in_menus=False,
                    order=340 + index * 10,
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
                label="C&lose Test Run",
                menu="Project",
                group="tests",
                order=20,
                tip="Close the open run; anything unmarked stays unrecorded",
                icon=stop_icon,
                state=self._close_run_state,
                run=self._close_run,
            ),
            ActionSpec(
                id="tests.open",
                label="&Tests",
                menu="Go",
                group="views",
                order=50,
                tip="Every test this project keeps, and how each one last did",
                state=self._on_a_project,
                run=self._open_tests,
            ),
            ActionSpec(
                id="tests.open_step",
                label="&Tests",
                menu="Step",
                group="surfaces",
                submenu="Show in",
                order=40,
                palette=False,  # The same verb's second seat, in Step ▸ Show in.
                state=self._on_a_project,
                run=self._open_tests,
            ),
            ActionSpec(
                id="test.details",
                label="Te&st Details",
                menu="Step",
                group="surfaces",
                order=45,  # After Show in, whose Tests opens the list this came from.
                tip="Show the picked test in the Test panel beside the roster — what it "
                "checks, and the verbs to run it",
                icon=beaker_icon,
                state=self._one_test,
                run=self._show_test,
            ),
            ActionSpec(
                id=SIDE_PANEL_ACTION,
                label="Test &Panel",
                menu="Project",
                group="tests",
                order=40,  # After the roster's own verbs: a way of reading them.
                tip="Stand the Test panel beside the roster in every Tests tab",
                icon=beaker_icon,
                # A preference, never greyed: it is about how every Tests tab reads.
                state=lambda _context: ActionState(checked=self._side_panel),
                run=lambda _context: self._set_side_panel(not self._side_panel),
            ),
            ActionSpec(
                id="tests.categories",
                label="Test &Categories…",
                menu="Project",
                group="tests",
                order=30,
                tip="Rename, re-icon and reorganise what this project files its tests under",
                icon=folder_icon,
                state=self._on_a_project,
                run=self._edit_categories,
            ),
            # File ▸ Export ▸ Tests. It writes *what the Tests tab is showing* — the scope,
            # the audience filter and whether the archived are in — because "narrow it, then
            # export it" is one gesture and a second dialog asking the same questions again
            # is a form. With no tab open it is the project's whole roster.
            ActionSpec(
                id="tests.export",
                label="&Tests (Markdown or HTML)…",
                menu="File",
                group="export",
                submenu="Export",
                order=15,  # Between the order list (10) and the plan report (20).
                tip="Write the tests this project's Tests tab is showing to Markdown or HTML",
                icon=external_icon,
                state=self._export_state,
                run=self._export,
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
        return focused_project(context, self._deps.library)

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
                    replace_fields(test, archived=archived) if test.id in wanted else test
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
                runs.write(project, runs.replaced(records, run)),
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
            self.start_run(project.id, self._showing(project.id).scope)

    def _showing(self, project_id: NodeId) -> Shown:
        """What the project's Tests tab is narrowed to, or nothing when none is open.

        A run opened from its strip covers what the tab is showing, and so does an export
        — one reader for both, because the alternative is two near-copies of this walk
        that will one day disagree about what "showing" means.
        """
        return next(
            (
                activity.showing()
                for activity in self._deps.tabs.activities()
                if isinstance(activity, TestsActivity) and activity.project_id == project_id
            ),
            Shown(),
        )

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
            SetModuleDataCommand(
                project_id, MODULE_ID, runs.write(project, started), label="Start Test Run"
            )
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
                runs.write(project, runs.replaced(records, runs.closed(run))),
                label="Close Test Run",
            )
        )

    # -- one test, in the panel --------------------------------------------------------------

    def _one_test(self, context: Context) -> ActionState:
        """Exactly one test picked, with the step it hangs off.

        `selected_entity`'s rule, asked for the same pair the panel resolves the test in
        (`panel.py`), so the verb and the panel cannot disagree — and a test id on its own
        does not name a test, since ids are minted per project.
        """
        if context.selected_entity("test") is None or context.selected_entity("step") is None:
            return DISABLED
        return ActionState()

    def _show_test(self, context: Context) -> None:
        """Stand the Test panel beside the roster the picked test is in.

        The panel is already following the tab's own pick, so from a Tests tab this is only
        the *reveal* — which is what makes a double-click feel like opening something while
        a single click merely updates what is already open. From anywhere else it opens the
        project's Tests tab on the test first, since the panel lives there.
        """
        current = self._deps.tabs.current_activity()
        if not isinstance(current, TestsActivity | AllTestsActivity):
            step_id = context.selected_entity("step")
            test_id = context.selected_entity("test")
            if step_id is None or test_id is None:
                return
            reveal_test(self._deps, step_id, test_id)
        self._set_side_panel(True)

    def _set_side_panel(self, shown: bool) -> None:
        """Stand or take down the panel in every Tests tab, now and later, and let the
        toggle re-ask — the graph's `_set_look` arrangement."""
        self._side_panel = shown
        set_global(MODULE_ID, SIDE_PANEL_KEY, shown)
        for activity in self._deps.tabs.activities():
            if isinstance(activity, TestsActivity | AllTestsActivity):
                activity.set_side_panel(shown)
        self._deps.context.refresh()

    # -- categories ------------------------------------------------------------------------

    def _edit_categories(self, context: Context) -> None:
        project = self._focused_project(context)
        if project is None:
            return
        dialog = CategoriesDialog(
            self._deps.library, self._deps.undo, project.id, self._deps.parent
        )
        dialog.exec()
        dialog.deleteLater()

    # -- export ------------------------------------------------------------------------------

    def _export_state(self, context: Context) -> ActionState:
        project = self._focused_project(context)
        if project is None:
            return DISABLED
        if not project_tests(project, archived=True):
            return ActionState(enabled=False, label="Tests — this project has no tests yet")
        return ActionState()

    def _export(self, context: Context) -> None:
        project = self._focused_project(context)
        if project is None:
            return
        shown = self._showing(project.id)
        deps = self._deps
        scope = project.step(shown.scope) if shown.scope else None
        pairs = export.narrowed(
            deps.library,
            project,
            scope=shown.scope if scope is not None else "",
            audiences=shown.audiences,
            archived=shown.archived,
        )
        name = project.title or "Untitled project"
        filters = [
            f"{export.FORMAT_LABELS[kind]} (*{export.SUFFIXES[kind]})" for kind in export.FORMATS
        ]
        offered = deps.reporting_dir(project.id) or Path.home()
        chosen, picked = QFileDialog.getSaveFileName(
            deps.parent,
            "Export Tests",
            str(offered / f"{name} tests{export.SUFFIXES[export.FORMATS[0]]}"),
            ";;".join(filters),
        )
        if not chosen:
            return
        # The format is the *filter* the user picked, not a guess at the suffix they typed:
        # a name with no suffix at all is the common case, and the dropdown already said it.
        kind = export.FORMATS[filters.index(picked)] if picked in filters else export.FORMATS[0]
        path = Path(chosen)
        if path.suffix.lower() != export.suffix_for(kind):
            path = path.with_suffix(export.suffix_for(kind))
        audiences = [a.label for a in AUDIENCES if a.id in shown.audiences]
        path.write_text(
            export.render(
                export.Exported(
                    project=project,
                    pairs=pairs,
                    outcomes=runs.latest_results(runs.read(project)),
                    audiences=audiences,
                    archived=shown.archived,
                    scope=(scope.title or "Untitled step") if scope is not None else "",
                ),
                kind,
            ),
            encoding="utf-8",
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
