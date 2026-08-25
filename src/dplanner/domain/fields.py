"""Bindable text fields: what a text widget needs to know about the plan.

Three methods per field — read it, turn an edit into a command, watch it — and
:class:`~dplanner.framework.text_binding.TextBinding` does the rest.

Note the asymmetry between the two below. A description is edited *positionally*, so a
keystroke costs one small splice and several open views of the same task stay in sync
without rebuilding. Notes are a whole-value field. Pick the first shape for anything long
enough that people type into it continuously.
"""

from collections.abc import Callable

from dplanner.domain.commands import Command, EditTextCommand, SetNotesCommand
from dplanner.domain.model import Plan, TaskId, TextEdit


class TaskDescriptionField:
    """A task's description, edited positionally."""

    def __init__(self, plan: Plan, task_id: TaskId) -> None:
        self._plan = plan
        self._task_id = task_id

    def read(self) -> str:
        return self._plan.task(self._task_id).description

    def command(self, pos: int, removed: str, added: str, origin: object) -> Command:
        return EditTextCommand(TextEdit(self._task_id, pos, removed, added), view_origin=origin)

    def connect(self, applied: Callable[[int, str, str, object], None]) -> Callable[[], None]:
        def on_edit(edit: TextEdit, origin: object) -> None:
            if edit.task_id == self._task_id:
                applied(edit.pos, edit.removed, edit.added, origin)

        return self._plan.text_edited.connect(on_edit)


class TaskNotesField:
    """A task's working notes, replaced wholesale."""

    def __init__(self, plan: Plan, task_id: TaskId) -> None:
        self._plan = plan
        self._task_id = task_id
        self._last = self.read()

    def read(self) -> str:
        return self._plan.task(self._task_id).notes

    def command(self, pos: int, removed: str, added: str, origin: object) -> Command:
        current = self.read()
        value = current[:pos] + added + current[pos + len(removed) :]
        return SetNotesCommand(self._task_id, value, view_origin=origin)

    def connect(self, applied: Callable[[int, str, str, object], None]) -> Callable[[], None]:
        def on_notes(task_id: TaskId, origin: object) -> None:
            if task_id != self._task_id:
                return
            # A whole-value change reported as one span over the old text: the binding
            # splices rather than resets, so the caret survives an edit made elsewhere.
            previous, self._last = self._last, self.read()
            applied(0, previous, self._last, origin)

        return self._plan.notes_edited.connect(on_notes)
