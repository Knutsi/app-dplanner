"""The preview a reference opens: the test somebody's body pointed at, read where you are.

A test body says *run this after T101*. Following that used to mean finding T101 in the
roster and picking it — which loses the test you were reading, and there is no back button
in a plan. So a reference opens **a modal over what you were reading**: glance at it, shut
it, and you are still where you were. That is the whole reason this is a dialog rather than
a jump, and it is why *Show in Tests* — the deliberate act of changing what you are working
on — is a button here rather than the only thing a click could mean.

**A reference inside the preview moves the preview.** A chain of references is a real thing
to follow, and a preview that dead-ends at the first one has the same defect it exists to
fix. So the body's references are linked here too, and **Back** walks the trail out. It
costs a list and one button, and without it the second reference is the one nobody follows.

It renders with :class:`~.view.TestHead` and :class:`~.view.TestBody`, the same two widgets
the Test panel is made of, so a test read here reads exactly as it does there — and it
edits nothing, so it needs no undo stack and writes nothing on the way out.
"""

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, NodeId, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.widgets import note
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import find_in_project, test_ids
from dplanner.modules.testing.view import TestBody, TestHead, test_images
from dplanner.theme.tokens import SECTION_GAP

# Framed (DESIGN.md's *Dialogs*): a preferred size, resizable, clamped to the screen's
# share. A test body is prose, and prose read in a 420 px column is read twice.
PREVIEW_SIZE = (560, 480)
HINT = "Referenced from the test you were reading."
OPEN_TEXT = "Show in Tests"
OPEN_TIP = "Pick this test in its project's Tests tab"


class TestPreview(DialogFrame):
    """One referenced test, and the way on to the ones it references."""

    def __init__(
        self,
        library: Library,
        project_id: NodeId,
        test_id: str,
        parent: QWidget | None = None,
        *,
        files: FilesFor | None = None,
    ) -> None:
        super().__init__("Test", parent, size=PREVIEW_SIZE)
        self.setObjectName("TestPreviewDialog")
        self._library = library
        self._project_id = project_id
        self._files = files
        self._trail: list[str] = []  # Where Back goes, newest last.
        self._test_id = ""
        self._step_id: StepId = ""
        # What the reader asked to open, read back by whoever showed the dialog.
        self.picked: tuple[StepId, str] | None = None

        self.body_layout.setSpacing(SECTION_GAP)
        self.head = TestHead(self.body)
        self.body_layout.addWidget(self.head)
        self.prose = TestBody(self.body)
        self.body_layout.addWidget(self.prose, 1)
        self.prose.reference.connect(self._follow)
        self.hint = note(HINT, self.body)
        self.hint.setWordWrap(True)
        self.body_layout.addWidget(self.hint)

        self.back = self.add_button("Back", self._back)
        self.add_dismiss("Close")
        self.open_verb = self.set_primary(OPEN_TEXT, self._open)
        self.open_verb.setToolTip(OPEN_TIP)
        self._show(test_id)

    # -- what it is showing --------------------------------------------------------------

    def _show(self, test_id: str) -> bool:
        """Render ``test_id``, or answer False and leave what is on screen alone.

        False is a test that went away between the render that linked it and the click —
        the only way to get here with an id the project does not have, since nothing links
        one it could not resolve.
        """
        project = self._library.project(self._project_id)
        found = find_in_project(project, test_id)
        if found is None:
            return False
        step, test = found
        self._test_id, self._step_id = test.id, step.id
        self.set_title(f"Test {test.id}")
        self.head.show_test(step, test, runs.latest(runs.read(project), test.id))
        # Its own references, minus itself: a body naming its own id is saying what it is,
        # and a link that reloads the page you are on teaches nothing.
        self.prose.show_body(
            test.body,
            image_src=test_images(self._files, step.id),
            known=test_ids(project) - {test.id},
        )
        self.back.setEnabled(bool(self._trail))
        return True

    def _follow(self, test_id: str) -> None:
        self._trail.append(self._test_id)
        if not self._show(test_id):
            self._trail.pop()

    def _back(self) -> None:
        if self._trail and not self._show(self._trail.pop()):
            self.back.setEnabled(bool(self._trail))

    def _open(self) -> None:
        self.picked = (self._step_id, self._test_id)
        self.accept()


def preview(
    library: Library,
    project_id: NodeId,
    test_id: str,
    parent: QWidget | None = None,
    *,
    files: FilesFor | None = None,
) -> tuple[StepId, str] | None:
    """Show ``test_id``, and answer the test the reader asked to open — None if they shut it.

    The one seam a host needs: a reference is clicked, a test is read, and at most one
    thing comes back out of it.
    """
    dialog = TestPreview(library, project_id, test_id, parent, files=files)
    try:
        dialog.exec()
        return dialog.picked
    finally:
        dialog.deleteLater()
