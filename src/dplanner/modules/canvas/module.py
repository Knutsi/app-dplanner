"""The canvas module: a project's step graph, open in a tab (``activity.py``).

Three seams keep this module from knowing about anything else in the application:

- **The panel beside the canvas is hosted, never known.** The composition root hands over a
  ``SidePanel`` — a name, a glyph and a way to build the widget — and this module stands it
  in a splitter (``framework/side_panel.py``) without learning whose it is.
- **The index opens projects through a callback** it is given, and never learns what an
  activity is.
- **The toolbar names verbs it does not own** — the app shell's undo pair, the order module's
  ``order.open`` — and reaches them through the registry alone. See ``toolbar.py``.

**The look is the module's** — the marks, the spotlight, the background under the graph and
whether gestures snap to its grid, one ``Look`` (``look.py``) — read from the per-user store
once and pushed to every open canvas when it changes: a way of looking at graphs, not a fact about
one project, so a tab opened later wears the same look and a second window would too.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget

from dplanner.core.signals import Signal as CoreSignal
from dplanner.domain.commands import Command
from dplanner.domain.model import Edge, Library, NodeId, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import follow_project_tabs
from dplanner.framework.context import ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.picker import PickerDialog
from dplanner.framework.side_panel import SidePanel
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.window import StatusHost
from dplanner.modules.canvas.activity import PROJECT_KIND, ProjectActivity
from dplanner.modules.canvas.clipboard.clip import PastePolicy
from dplanner.modules.canvas.clipboard.verbs import ClipboardVerbs, ClipboardWatch
from dplanner.modules.canvas.find import find_rows
from dplanner.modules.canvas.layouts.positions import DATA_FORMAT, footprints
from dplanner.modules.canvas.layouts.verbs import LayoutVerbs, set_wave_view, wave_view
from dplanner.modules.canvas.look import Look
from dplanner.modules.canvas.renderers import EdgeAccent, NodeAccent
from dplanner.modules.canvas.selection import EdgeRef
from dplanner.modules.canvas.stacks.verbs import StackVerbs
from dplanner.modules.canvas.step_verbs import StepVerbs
from dplanner.modules.canvas.view_verbs import CanvasVerbs

MODULE_ID = "project_editor"
# The per-user key the look is kept under — see look.py.
LOOK_KEY = "look"


def _no_accents(_project_id: str) -> dict[StepId, NodeAccent]:
    return {}


def _no_edge_accents(_project_id: str) -> Mapping[Edge, EdgeAccent]:
    return {}


def _no_strips(_project_id: str) -> frozenset[StepId]:
    return frozenset()


@dataclass(frozen=True)
class CanvasDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    undo: UndoService[Library]
    status: StatusHost
    parent: QWidget
    theme: ThemeService
    debounce: DebounceService
    # Where a step's attachments live, for a copy to carry them.
    files: FilesFor
    # How every step of a project should look beyond its text — muted, badged — in the
    # canvas's own vocabulary, so the editor never learns which aspects mean what. One call
    # per sync: the answer for a milestone comes from a schedule walk, and the walk is the
    # same for every step in the project.
    step_accents: Callable[[str], dict[StepId, NodeAccent]] = field(default=_no_accents)
    # Says an accent has changed for a reason the model cannot name. `step_accents` is
    # otherwise re-read whenever the project changes, which covers everything the plan
    # holds; what is wrong with a plan is *derived* from it, on a settle of its own, so it
    # lands after the change that caused it and has to say so itself.
    accents_changed: "CoreSignal[str] | None" = None
    # The same for the arrows, keyed (waiter, kind, source): which links auto-progress, and
    # which of those carry work that is being done right now. Absent means a plain arrow.
    edge_accents: Callable[[str], Mapping[Edge, EdgeAccent]] = field(default=_no_edge_accents)
    # Which of a project's cards wear a branch strip under the body, and so stand
    # ``STRIP_H`` taller — the same steps whose accent names one. The canvas sizes its cards
    # by it and every sort spaces by it, through ``positions.footprints``.
    strips: Callable[[str], frozenset[StepId]] = field(default=_no_strips)

    # A copied step carries its attachments: the file areas to read are the asset catalog's
    # sources, and what a copy may not carry is each owner's policy — see clipboard.py.
    file_modules: tuple[str, ...] = ()
    paste_policies: tuple[PastePolicy, ...] = ()
    # What the project tab hosts beside the canvas — see framework/side_panel.py. None
    # means this build has nothing to put there, and the toggle is hidden rather than greyed.
    side_panel: SidePanel | None = None


class CanvasModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: CanvasDeps) -> None:
        self._deps = deps
        self._look = Look.from_json(get_global(MODULE_ID, LOOK_KEY))
        self._verbs = StepVerbs(
            library=deps.library,
            undo=deps.undo,
            parent=deps.parent,
            current_project=self._current_project,
            new_position=self._new_step_position,
            placed=self._on_placed,
            created=self._on_created,
        )
        # The watcher is a child of the window, which is what disconnects it from the
        # process-global clipboard when this build is discarded.
        self._clipboard = ClipboardWatch(deps.parent, deps.context)
        self._clipboard_verbs = ClipboardVerbs(
            library=deps.library,
            undo=deps.undo,
            files=deps.files,
            file_modules=deps.file_modules,
            held=self._clipboard.count,
            current_project=self._current_project,
            new_position=self._new_step_position,
            placed=self._on_placed,
            policies=deps.paste_policies,
        )
        self._stack_verbs = StackVerbs(
            library=deps.library,
            undo=deps.undo,
            current_project=self._current_project,
            new_position=self._new_step_position,
            born=self._verbs.born,
            status=lambda text: deps.status.show_status(text, 4000),
        )
        self._layout_verbs = LayoutVerbs(
            library=deps.library,
            undo=deps.undo,
            parent=deps.parent,
            current_project=self._current_project,
            status=lambda text: deps.status.show_status(text, 4000),
            size_for=lambda project: footprints(deps.strips(project.id)),
            set_waves=self._set_waves,
        )
        self._canvas_verbs = CanvasVerbs(
            library=deps.library,
            current_project=self._current_project,
            select_step=self.reveal,
            select_steps=self._select_steps,
            select_edges=self._select_edges,
            set_mode=self._set_mode,
            frame=self._frame,
            find=self._find,
            look=lambda: self._look,
            set_look=self._set_look,
            side_panel=deps.side_panel,
        )

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        """Show a project in a tab. Handed to the index segment as a plain function."""
        self._deps.tabs.open(PROJECT_KIND, project_id, preview=preview)

    def create_step(
        self,
        project_id: NodeId,
        title: str,
        *,
        at: tuple[float, float] | None = None,
        carrying: Callable[[Step], Sequence[Command]] | None = None,
        label: str = "New Step",
        before: StepId | None = None,
    ) -> Step:
        """Give birth to a step the way New does — the seam the composition root places
        through, so a feature step born from the Specs tab is one undo step with its
        marker and its position like any other placed step, and a wait inserted in front
        of a step (``before``) joins that step's stack when it stands in one."""
        return self._verbs.create(
            project_id, title, at=at, carrying=carrying, label=label, before=before
        )

    def reveal(self, step_id: StepId) -> None:
        """Show the step's project and select it there.

        What the ``steps.reveal`` verb does, and how the Go movement verbs land: any view
        that lists steps reaches this through the registry without knowing what a canvas is.
        """
        if not self._deps.library.has(step_id):
            return
        project = self._deps.library.project_of(step_id)
        self.open(project.id)
        for activity in self._activities():
            if activity.project_id == project.id:
                activity.select_step(step_id)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> ProjectActivity:
            assert target is not None
            return ProjectActivity(
                deps, target, self._verbs, self._layout_verbs, self._stack_verbs, self._look
            )

        deps.tabs.register_factory(PROJECT_KIND, factory)
        self._verbs.register_into(deps.actions)
        self._stack_verbs.register_into(deps.actions)
        self._clipboard_verbs.register_into(deps.actions)
        self._canvas_verbs.register_into(deps.actions)
        self._layout_verbs.register_into(deps.actions)
        # A project that goes away takes its tab with it, and a rename reaches the tab.
        follow_project_tabs(deps.tabs, ProjectActivity, deps.library)

    # -- tabs ------------------------------------------------------------------------------------

    def _activities(self) -> list[ProjectActivity]:
        return [a for a in self._deps.tabs.activities() if isinstance(a, ProjectActivity)]

    def _current_activity(self) -> ProjectActivity | None:
        current = self._deps.tabs.current_activity()
        return current if isinstance(current, ProjectActivity) else None

    def _current_project(self) -> NodeId | None:
        current = self._current_activity()
        return current.project_id if current is not None else None

    def _new_step_position(self) -> tuple[float, float] | None:
        current = self._current_activity()
        return current.new_step_position() if current is not None else None

    def _on_placed(self, step_ids: list[StepId]) -> None:
        current = self._current_activity()
        if current is not None:
            current.note_placed(step_ids)

    def _on_created(self, step_id: StepId) -> None:
        current = self._current_activity()
        if current is not None:
            current.note_created(step_id)

    def _set_mode(self, name: str, on: bool) -> None:
        current = self._current_activity()
        if current is not None:
            current.set_mode(name, on)

    def _set_look(self, look: Look) -> None:
        """Change how every canvas looks, now and later, and let the toggles re-ask."""
        self._look = look
        set_global(MODULE_ID, LOOK_KEY, look.to_json())
        for activity in self._activities():
            activity.set_look(look)
        self._deps.context.refresh()

    def _set_waves(self, project_id: NodeId, on: bool) -> None:
        """Put a project in or out of Wave view for this user: remembered, shown by every tab
        on it, and re-asked by every toggle. Never the plan's — nothing here is written to
        it, so two people can look at one plan in two ways."""
        if wave_view(project_id) == on:
            return
        set_wave_view(project_id, on)
        for activity in self._activities():
            if activity.project_id == project_id:
                activity.show_waves(on)
        self._deps.context.refresh()

    def _select_steps(self, step_ids: list[StepId]) -> None:
        current = self._current_activity()
        if current is not None:
            current.select_steps(step_ids)

    def _select_edges(self, refs: list[EdgeRef]) -> None:
        current = self._current_activity()
        if current is not None:
            current.select_edges(refs)

    def _frame(self) -> None:
        current = self._current_activity()
        if current is not None:
            current.frame()

    def find_picker(self) -> PickerDialog | None:
        """The Find picker over the current canvas's project — built, not shown.

        Separate from :meth:`_find` so a test can read what the picker offers without a
        modal loop, the way ``menu_for`` opens a toolbar's dropdown without a click.
        """
        current = self._current_activity()
        if current is None or not self._deps.library.has(current.project_id):
            return None
        project = self._deps.library.project(current.project_id)
        ink = self._deps.parent.palette().color(QPalette.ColorRole.Text)
        rows = find_rows(project, self._deps.step_accents(project.id), ink)
        return PickerDialog(
            rows, self.reveal, self._deps.parent, placeholder="Find a step by name or key…"
        )

    def _find(self) -> None:
        picker = self.find_picker()
        if picker is not None:
            picker.exec()
