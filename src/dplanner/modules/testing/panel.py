"""The Test panel: one test, big enough to run from.

**It is for executing, where the step panel's Tests tab is for authoring.** That is the
whole reason it exists rather than being a third tab over there. Somebody working down a
roster wants the test's steps rendered as steps, the four results under their thumb, and a
way to get to the next one without going back to the table and finding their place — none
of which an editor gives you, and all of which an editor is worse for having.

So the body is **rendered markdown, read only**: a numbered list is a numbered list here,
not `1.` and a full stop. *Show Step* is the door back to the editor, which is also where a
test's pictures are attached.

**A reference to another test is a link, and it opens a preview rather than moving.** A
body that says *run this after T101* is pointing somewhere, and picking T101 in the table
would lose the test being read with nothing to go back to. So a click opens
``preview_dialog.py`` over this panel, and *Show in Tests* there is the deliberate move —
made through the host, so this panel still publishes no selection of its own.
:mod:`.references` says what counts as a reference; the ids it may resolve are asked for
only when the body says something shaped like one, because this refreshes on every model
change and the answer is a walk of the project.

**It is a panel, not a modal**, for the reason every panel is: a modal over a table is a
thing you open and shut twenty times in a run, and each time it takes the list away. This
stays beside the list, follows the selection, and a double-click on a row is what puts it on
screen (``test.details`` — see ``module.py``).

**Next and Previous move the *table's* selection, never the panel's own.** A panel may not
publish a selection (``section.py``'s rule; ``ARCHITECTURE.md``'s *Where a panel goes*), so
these ask the Tests tab to pick the next row and then simply follow the context like any
other change. With no Tests tab open for the project there is nothing to walk, and both are
greyed saying so — which is also honest: "next" has no meaning without a list.

**A test is named with the step it hangs off, and that pair is what this resolves.** A test
id is minted per *project* (``aspect.py``), so ``T101`` names a different test in every
project in the library and there is no such thing as looking one up on its own — which is
exactly what this panel used to do, and why it showed the first project's ``T101`` whatever
the reader had picked. Every view that picks a test publishes its step beside it, and
``test.details`` is greyed without both.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from dplanner.domain.model import Library, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import Context, ContextService
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import note
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import Test, find, read, test_ids
from dplanner.modules.testing.preview_dialog import preview
from dplanner.modules.testing.references import mentions
from dplanner.modules.testing.view import (
    RESULT_ORDER,
    TestBody,
    TestHead,
    test_images,
)
from dplanner.theme.icons import chevron_left_icon, chevron_right_icon, step_icon
from dplanner.theme.tokens import PANEL_MARGIN, SECTION_GAP

PANEL_ID = "testing.test"
# The result verbs, as the strip renders them: the same ids the Step ▸ Test menu holds, so
# a result recorded here and one recorded from the table are one verb with one state gate.
RESULT_VERBS = tuple(f"test.result_{status}" for status in RESULT_ORDER)
NOTHING = "No test picked. Double-click one in a Tests tab."
NO_LIST = "open the project's Tests tab to step through them"


@dataclass(frozen=True)
class Walk:
    """How the panel steps through a list it does not own.

    ``go`` is handed the test to move from and which way; it answers whether it moved. The
    module implements it by asking the project's Tests tab for its rows and telling it to
    pick the neighbour, so the *table* publishes the selection and the panel follows.
    """

    go: Callable[[str, int], bool]
    can: Callable[[str, int], bool]


class TestPanel(QWidget):
    """One test, its result verbs, and the way to the next one."""

    def __init__(
        self,
        library: Library,
        actions: ActionRegistry,
        context: ContextService,
        *,
        walk: Walk | None = None,
        files: FilesFor | None = None,
        open_test: Callable[[StepId, str], None] | None = None,
    ) -> None:
        super().__init__()
        self._library = library
        self._actions = actions
        self._context = context
        self._walk = walk
        self._files = files
        self._open_test = open_test
        # The pair the context named: a test id alone does not identify a test.
        self._test_id = ""
        self._step_id: StepId = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)

        self.head = TestHead(self)
        layout.addWidget(self.head)

        # Dense: these are read and aimed at as **one set** — mark it, go to the next — and
        # at the verb strip's metrics the last of them folds into a `…` menu in the 360 px
        # dock this panel lives in, which is the one thing a run must not have to do.
        self.controls = Toolbar(self, dense=True)
        layout.addWidget(self.controls)
        for action_id in RESULT_VERBS:
            self.controls.add_action(actions, context, action_id)
        self.controls.add_divider()
        self.step_verb = self.controls.add_verb(
            "Show Step", step_icon, self._show_step, tip="Open the step this test belongs to"
        )
        self.controls.add_divider()
        self.previous_verb = self.controls.add_verb(
            "Previous Test", chevron_left_icon, lambda: self._step_through(-1)
        )
        self.next_verb = self.controls.add_verb(
            "Next Test", chevron_right_icon, lambda: self._step_through(1)
        )

        self.body = TestBody(self)
        self.body.reference.connect(self._preview)
        layout.addWidget(self.body, 1)

        self.empty = note(NOTHING, self)
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)

        self._unsubscribes = [
            library.module_data_changed.connect(lambda *_a: self._refresh()),
            library.structure_changed.connect(lambda *_a: self._refresh()),
        ]
        self._show(None)

    # -- the ContextPanel contract ---------------------------------------------------------

    def show_context(self, context: Context) -> bool:
        """One picked test is something to run; none or several is not.

        Several is deliberately nothing: the result verbs already act on the whole picked
        set from the table, and a panel showing one of four picked tests would be lying
        about what Mark Ok is going to do.

        The step comes out of the same selection, because a test id alone does not name a
        test — see the module docstring.
        """
        self._test_id = context.selected_entity("test") or ""
        self._step_id = context.selected_entity("step") or ""
        self._refresh()
        return bool(self._found())

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.controls.dispose()

    # -- what it is showing ------------------------------------------------------------------

    def _found(self) -> tuple[Step, Test] | None:
        """The picked test, read out of the step the selection named it with, or None.

        Read rather than cached, so an edit to the test lands here on the next signal; and
        looked up in that one step rather than walked across the library, because an id is
        only unique inside its project (the module docstring). Archived tests included:
        a test taken off the roster is still one somebody can open.
        """
        if not self._test_id or not self._library.has(self._step_id):
            return None
        step = self._library.step(self._step_id)
        test = find(read(step), self._test_id)
        return None if test is None else (step, test)

    def _refresh(self) -> None:
        self._show(self._found())

    def _show(self, found: tuple[Step, Test] | None) -> None:
        showing = found is not None
        for widget in (self.head, self.body):
            widget.setVisible(showing)
        self.controls.setVisible(showing)
        self.empty.setVisible(not showing)
        if found is None:
            self._sync_walk()
            return
        step, test = found
        project = self._library.project_of(step.id)
        self.head.show_test(step, test, runs.latest(runs.read(project), test.id))
        # The ids a reference may name, asked for only when the body says something shaped
        # like one: this refreshes on every model change, and resolving them is a walk of
        # the whole project, which most bodies would pay for nothing.
        known = test_ids(project) - {test.id} if mentions(test.body) else ()
        self.body.show_body(test.body, image_src=test_images(self._files, step.id), known=known)
        self._sync_walk()

    def _preview(self, test_id: str) -> None:
        """A reference in the body, read where the reader is — see ``preview_dialog.py``.

        The test is looked up inside *this* project, because that is the only place its id
        means anything; *Show in Tests* is what turns a glance into a move, and it goes
        through the host so this panel still publishes no selection of its own.
        """
        if not self._library.has(self._step_id):
            return
        project = self._library.project_of(self._step_id)
        picked = preview(self._library, project.id, test_id, self, files=self._files)
        if picked is not None and self._open_test is not None:
            self._open_test(*picked)

    # -- stepping through ---------------------------------------------------------------------

    def _sync_walk(self) -> None:
        """Whether there is a next one, and — when there is not — why not, in the tooltip.

        Through ``Toolbar.set_tip``, never ``action.setToolTip``: the strip composes that
        string from the words and the standing explanation, and would compose it again
        over anything written straight onto the action.
        """
        for verb, offset in ((self.previous_verb, -1), (self.next_verb, 1)):
            walk = self._walk
            can = bool(self._test_id) and walk is not None and walk.can(self._test_id, offset)
            verb.setEnabled(can)
            self.controls.set_tip(verb, "" if can else NO_LIST)

    def _step_through(self, offset: int) -> None:
        if self._walk is not None and self._test_id:
            self._walk.go(self._test_id, offset)

    def _show_step(self) -> None:
        """The door back to the editor. A constructed context, because the user picked a
        *test* and this verb wants the step it hangs off (``CLAUDE.md``'s rule for a verb
        acting on a selection nobody made)."""
        from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

        if self._step_id:
            self._actions.run(
                "steps.details",
                Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", self._step_id)),)}),
            )
