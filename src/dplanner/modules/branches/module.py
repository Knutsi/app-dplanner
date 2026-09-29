"""Branch stretches, in the running application: two Type toggles, a Details block, and the
two verbs a right-click on the picked steps offers.

*Put on a Branch…* brackets the pick between a cut and a landing, asking only for the
branch's name — pre-filled from the pick. *Remove Branch…* takes the whole bracket away
again, and asks first: it is never partial, so every step on the branch goes back, not only
the ones picked. Step ▸ Type ▸ Branch cut and Landing mark the ends one at a time.

**No state walks the graph per keystroke.** Whether a pick could go on a branch, which
branch a picked step is on, and whether a landing has a cut to close each take a walk over
the project, and an action state runs on every announce — so each project's answers are
read once and forgotten when a link, a step or an aspect changes, as the stack verbs do.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from PySide6.QtWidgets import QWidget

from dplanner.core.fsio import slugify
from dplanner.domain.branches import Reading, Stretch
from dplanner.domain.commands import Command
from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.ordering import upstream
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import Context
from dplanner.framework.dialog import LinePrompt
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.step_selection import chosen_steps
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.branches.aspect import (
    CUT_FORMAT,
    CUT_ID,
    CUT_SPEC,
    LAND_FORMAT,
    LAND_ID,
    LAND_SPEC,
    branch_of,
    is_cut,
    is_land,
    name_problem,
    reading,
    write_cut,
    write_land,
)
from dplanner.modules.branches.edits import put_command, put_refusal, remove_command, stretch_picked
from dplanner.modules.branches.section import CutSection
from dplanner.theme.icons import branch_icon


@dataclass(frozen=True)
class BranchesDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    details: InspectorSectionRegistry
    is_done: Callable[[Step], bool]
    is_agent: Callable[[Step], bool]
    # Why a pick would put part of a stack on a branch — a stack is the graph editor's.
    stacked_apart: Callable[[Project, set[StepId]], str]
    # The stretch's two ends, dressed as every other module has them: the cut with no
    # estimate, the landing an agent step — the root's word, shared with the CLI.
    born: Callable[[Project, str], tuple[Step, Step]]
    # Where the two new cards stand beside the pick, as commands that ride with their
    # births — the graph editor's seats. None is a build with no canvas.
    seats: Callable[[Sequence[StepId], Step, Step], Sequence[Command]] | None = None
    key_of: Callable[[Step], str] = field(default=lambda step: step.title)
    parent: QWidget | None = None  # What the two dialogs open over.


@dataclass
class _Memo:
    """One project's answers, as last read — forgotten whenever the graph moves."""

    reading: Reading
    put: dict[tuple[StepId, ...], str] = field(default_factory=dict)
    picked: dict[tuple[StepId, ...], tuple[Stretch | None, str]] = field(default_factory=dict)
    open_cut: dict[StepId, StepId | None] = field(default_factory=dict)


class BranchesModule:
    id = CUT_ID
    data_format = CUT_FORMAT

    def __init__(self, deps: BranchesDeps) -> None:
        self._deps = deps
        self._memos: dict[NodeId, _Memo] = {}

    def register(self) -> None:
        deps = self._deps
        library = deps.library
        library.structure_changed.connect(lambda *_args: self._memos.clear())
        library.edges_changed.connect(lambda *_args: self._memos.clear())
        library.module_data_changed.connect(lambda *_args: self._memos.clear())
        deps.details.register(
            InspectorSection(
                id=f"{CUT_ID}.details",
                label="Branch",
                order=13,  # After a wait's hold (12): the other kind nobody works.
                hint="The feature branch this cut starts: the steps after it work on it.",
                factory=lambda: CutSection(library, deps.undo),
                shown_for=lambda step_id: (
                    step_id is not None and library.has(step_id) and is_cut(library.step(step_id))
                ),
            )
        )
        deps.actions.register(
            aspect_toggle(
                id="cut.toggle",
                label=CUT_SPEC.label,
                order=66,  # A kind nobody works, beside Wait (65).
                module_id=CUT_ID,
                library=library,
                undo=deps.undo,
                enabled=is_cut,
                fresh=lambda step, _project: write_cut(
                    f"feature/{slugify(step.title) or 'branch'}"
                ),
                icon=branch_icon,
                tip="Make this step the cut a feature branch starts from: the steps after it"
                " work on that branch",
            )
        )
        deps.actions.register(
            aspect_toggle(
                id="land.toggle",
                label=LAND_SPEC.label,
                order=68,
                module_id=LAND_ID,
                library=library,
                undo=deps.undo,
                enabled=is_land,
                fresh=lambda step, _project: write_land(self._open_cut(step)),
                tip="Make this agent step the landing that merges a cut's branch back as a PR",
                refusal=self._land_refusal,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="branch.put",
                label="Put on a &Branch…",
                menu="Step",
                group="branch",
                order=10,
                icon=branch_icon,
                tip="Put the picked steps on a feature branch: a cut before them, a landing"
                " after, and the links from outside moved onto the two",
                state=self._can_put,
                run=self._put,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="branch.remove",
                label="Remove Bra&nch…",
                menu="Step",
                group="branch",
                order=20,
                tip="Take the branch off every step on it: its cut and landing go, and the"
                " links close over them",
                state=self._can_remove,
                run=self._remove,
            )
        )

    # -- readings ---------------------------------------------------------------------------

    def _memo(self, project: Project) -> _Memo:
        memo = self._memos.get(project.id)
        if memo is None:
            memo = self._memos[project.id] = _Memo(reading(project, self._deps.is_done))
        return memo

    def reading_of(self, project: Project) -> Reading:
        """The project's stretches as last read — what the window's briefing and Run Agent
        ask on every announce, so it is the one reading and never a walk of its own."""
        return self._memo(project).reading

    def _open_cut(self, step: Step) -> StepId | None:
        """The one cut upstream of ``step`` that no landing closes yet, else None."""
        library = self._deps.library
        project = library.project_of(step.id)
        memo = self._memo(project)
        if step.id not in memo.open_cut:
            open_cuts = {cut.id for cut in memo.reading.stray_cuts}
            found = [s.id for s in upstream(library, project, step.id) if s.id in open_cuts]
            memo.open_cut[step.id] = found[0] if len(found) == 1 else None
        return memo.open_cut[step.id]

    def _land_refusal(self, step: Step) -> str:
        if is_land(step):
            return ""  # Carried already: turning it off is always allowed.
        if not self._deps.is_agent(step):
            return "mark the step as an agent step first"
        if self._open_cut(step) is None:
            return "one open branch cut must be upstream of it"
        return ""

    # -- Put on a Branch --------------------------------------------------------------------

    def _put_refusal(self, chosen: Sequence[StepId]) -> str:
        library = self._deps.library
        memo = self._memo(library.project_of(chosen[0]))
        key = tuple(sorted(chosen))
        if key not in memo.put:
            memo.put[key] = put_refusal(library, chosen, self.reading_of, self._deps.stacked_apart)
        return memo.put[key]

    def _can_put(self, context: Context) -> ActionState:
        chosen = chosen_steps(context, self._deps.library)
        if not chosen:
            return DISABLED
        refusal = self._put_refusal(chosen)
        return (
            ENABLED
            if not refusal
            else ActionState(enabled=False, label=f"Put on a Branch — {refusal}")
        )

    def _put(self, context: Context) -> None:
        deps = self._deps
        chosen = chosen_steps(context, deps.library)
        if not chosen or self._put_refusal(chosen):
            return
        project = deps.library.project_of(chosen[0])
        taken = [s.branch for s in self.reading_of(project).stretches if not s.landed]
        taken += [branch_of(cut) for cut in self.reading_of(project).stray_cuts]
        name = LinePrompt.ask(
            deps.parent,
            "Put on a Branch",
            "Branch",
            "Put on Branch",
            text=_suggested(deps.library, chosen),
            validate=lambda text: name_problem(text, taken),
        )
        if name is None:
            return
        cut, land = deps.born(project, name)
        seats = deps.seats(chosen, cut, land) if deps.seats is not None else ()
        deps.undo.push(put_command(deps.library, chosen, cut, land, carrying=seats))

    # -- Remove Branch ----------------------------------------------------------------------

    def _picked(self, chosen: Sequence[StepId]) -> tuple[Stretch | None, str]:
        memo = self._memo(self._deps.library.project_of(chosen[0]))
        key = tuple(sorted(chosen))
        if key not in memo.picked:
            memo.picked[key] = stretch_picked(memo.reading, chosen)
        return memo.picked[key]

    def _can_remove(self, context: Context) -> ActionState:
        chosen = chosen_steps(context, self._deps.library)
        if not chosen:
            return DISABLED
        stretch, why = self._picked(chosen)
        if stretch is None:
            return ActionState(enabled=False, label=f"Remove Branch — {why}")
        return ActionState(label=f"Remove Bra&nch {stretch.branch}…")

    def _remove(self, context: Context) -> None:
        deps = self._deps
        chosen = chosen_steps(context, deps.library)
        if not chosen:
            return
        stretch, _why = self._picked(chosen)
        if stretch is None:
            return
        count = len(stretch.members)
        steps = f"all {count} steps on it go" if count != 1 else "the step on it goes"
        question = (
            f"Remove the branch {stretch.branch}? Its cut {deps.key_of(stretch.cut)} and"
            f" landing {deps.key_of(stretch.land)} are deleted, and {steps} back where they"
            " were — not only the ones you picked."
        )
        if confirm(deps.parent, "Remove Branch", question, verb="Remove Branch"):
            deps.undo.push(remove_command(deps.library, stretch))


class LandingModule:
    """The landing's aspect id and format; the cut's module registers for both."""

    id = LAND_ID
    data_format = LAND_FORMAT

    def register(self) -> None:
        return None


def _suggested(library: Library, chosen: Sequence[StepId]) -> str:
    """A branch named for what the pick delivers: its first step's title, slugged."""
    title = library.step(chosen[0]).title
    return f"feature/{slugify(title) or 'branch'}"
