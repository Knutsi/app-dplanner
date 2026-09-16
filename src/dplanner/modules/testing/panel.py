"""The Test panel: one test, big enough to run from.

**It is for executing, where the step panel's Tests tab is for authoring.** That is the
whole reason it exists rather than being a third tab over there. Somebody working down a
roster wants the test's steps rendered as steps, the four results under their thumb, and a
way to get to the next one without going back to the table and finding their place — none
of which an editor gives you, and all of which an editor is worse for having.

So the body is **rendered markdown, read only**: a numbered list is a numbered list here,
not `1.` and a full stop. *Show Step* is the door back to the editor, which is also where a
test's pictures are attached.

**It is a panel, not a modal**, for the reason every panel is: a modal over a table is a
thing you open and shut twenty times in a run, and each time it takes the list away. This
stays beside the list, follows the selection, and a double-click on a row is what puts it on
screen (``test.details`` — see ``module.py``).

**Next and Previous move the *table's* selection, never the panel's own.** A panel may not
publish a selection (``section.py``'s rule; ``ARCHITECTURE.md``'s *Where a panel goes*), so
these ask the Tests tab to pick the next row and then simply follow the context like any
other change. With no Tests tab open for the project there is nothing to walk, and both are
greyed saying so — which is also honest: "next" has no meaning without a list.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.markdown import render as markdown
from dplanner.domain.model import Library, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import Context, ContextService
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import caption, note
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import MODULE_ID, Test, audience_words, project_tests
from dplanner.modules.testing.filing import category_of
from dplanner.modules.testing.view import RESULT_ORDER, StatusChip, outcome_line
from dplanner.theme.cards import title_font
from dplanner.theme.icons import chevron_left_icon, chevron_right_icon, step_icon
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP

PANEL_ID = "testing.test"
# The result verbs, as the strip renders them: the same ids the Step ▸ Test menu holds, so
# a result recorded here and one recorded from the table are one verb with one state gate.
RESULT_VERBS = tuple(f"test.result_{status}" for status in RESULT_ORDER)
NOTHING = "No test picked. Double-click one in a Tests tab."
NO_LIST = "open the project's Tests tab to step through them"
NO_BODY = "This test has no body yet — nobody can execute it. Show Step to write one."


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
    ) -> None:
        super().__init__()
        self._library = library
        self._actions = actions
        self._context = context
        self._walk = walk
        self._files = files
        self._test_id = ""
        self._step_id: StepId = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)

        head = QVBoxLayout()
        layout.addLayout(head)  # Before it is filled: a parentless layout leaks its items.
        head.setSpacing(CAPTION_GAP)
        self.identity = caption("", self)
        head.addWidget(self.identity)
        self.title = QLabel(self)
        self.title.setFont(title_font(self.title.font()))
        self.title.setWordWrap(True)
        head.addWidget(self.title)
        self.filed = note("", self)
        self.filed.setWordWrap(True)
        head.addWidget(self.filed)

        where = QHBoxLayout()
        layout.addLayout(where)
        where.setSpacing(FIELD_GAP)
        self.chip = StatusChip(self)
        where.addWidget(self.chip)
        self.outcome = note("", self)
        self.outcome.setWordWrap(True)
        where.addWidget(self.outcome, 1)

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

        self.body = QTextBrowser(self)
        self.body.setObjectName("TestBody")
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        self.body.setOpenLinks(False)
        self.body.anchorClicked.connect(QDesktopServices.openUrl)
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
        """
        self._test_id = context.selected_entity("test") or ""
        self._refresh()
        return bool(self._found())

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.controls.dispose()

    # -- what it is showing ------------------------------------------------------------------

    def _found(self) -> tuple[Step, Test] | None:
        """The picked test and its step, or None. Walked rather than cached: a test moves
        step only by being cut and pasted, and the walk is what every other reader does."""
        if not self._test_id:
            return None
        for project in self._library.projects:
            for step, test in project_tests(project, archived=True):
                if test.id == self._test_id:
                    return step, test
        return None

    def _refresh(self) -> None:
        self._show(self._found())

    def _show(self, found: tuple[Step, Test] | None) -> None:
        showing = found is not None
        for widget in (self.identity, self.title, self.filed, self.chip, self.outcome, self.body):
            widget.setVisible(showing)
        self.controls.setVisible(showing)
        self.empty.setVisible(not showing)
        if found is None:
            self._step_id = ""
            self._sync_walk()
            return
        step, test = found
        self._step_id = step.id
        outcome = runs.latest(runs.read(self._library.project_of(step.id)), test.id)
        self.identity.setText(test.id)
        self.title.setText(test.title or "Untitled test")
        self.filed.setText(
            " · ".join(
                part
                for part in (
                    category_of(test),
                    test.sort_key,
                    audience_words(test),
                    step.title or "Untitled step",
                    "Archived" if test.archived else "",
                )
                if part
            )
        )
        self.chip.show_status(outcome.result.status if outcome else "pending")
        self.outcome.setText(outcome_line(outcome))
        self.body.setHtml(markdown(test.body, image_src=self._image) or f"<p>{NO_BODY}</p>")
        self._sync_walk()

    def _image(self, source: str) -> str | None:
        """A body's picture, as a path this browser can load.

        The images are the *step's* — `dplanner test attach` has always written them there
        — so they are resolved against the step's own area rather than left as the relative
        link the editor stores, which nothing outside the plan directory could follow.
        """
        files = self._files
        if files is None or not self._step_id or "://" in source:
            return source or None
        name = source.split("/")[-1]
        found = files(self._step_id, MODULE_ID).absolute(name)
        return found.as_uri() if found.is_file() else None

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
