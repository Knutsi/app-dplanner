"""Undoable changes to the plan.

A command is the *only* way a feature changes the plan. Not because indirection is virtuous,
but because a command is the unit undo works in: pushing one is what makes an action
reversible, and the alternative — a view mutating the model directly — is a change that
Ctrl+Z cannot see and no other view hears about.

Two conventions carry through all of them:

**Origin flips after the first redo.** ``push()`` runs ``redo()`` once, and that first run
carries the originating view's token so the widget that already shows the change ignores its
own echo. Every later redo, and every undo, passes ``UNDO_ORIGIN``, which matches no view.

**Coalescing is bounded.** Typing is one undo step per burst, and setting the same field
twice in a row is one step — but a burst ends at a pause and whenever the application seals
the top of the stack.
"""

import time
from typing import Protocol

from dplanner.domain.model import Plan, Task, TaskId, TextEdit

# A pause longer than this starts a new undo step.
MERGE_WINDOW_SECONDS = 1.0

# Passed by undo and redo. It matches no view binding, so every view applies the change.
UNDO_ORIGIN: object = object()

# What the Edit menu says for each field, so an undo entry names the change rather than
# the mechanism: "Undo Set Status", not "Undo Set Field".
FIELD_LABELS = {
    "status": "Set Status",
    "assignee": "Assign",
    "estimate_days": "Set Estimate",
    "start": "Set Start Date",
    "due": "Set Due Date",
}


class Command(Protocol):
    """One reversible change. See :mod:`dplanner.framework.undo`."""

    def text(self) -> str: ...

    def redo(self, plan: Plan) -> None: ...

    def undo(self, plan: Plan) -> None: ...

    def merge_with(self, other: "Command") -> bool: ...


class EditTextCommand:
    """A positioned edit to a task's description, coalescing consecutive typing."""

    def __init__(self, edit: TextEdit, view_origin: object | None = None) -> None:
        self.edit = edit
        self._next_origin = view_origin
        self._at = time.monotonic()

    def text(self) -> str:
        return "Typing"

    def redo(self, plan: Plan) -> None:
        plan.apply_text_edit(self.edit, self._next_origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, plan: Plan) -> None:
        plan.apply_text_edit(self.edit.inverted(), UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        if not isinstance(other, EditTextCommand):
            return False
        mine, theirs = self.edit, other.edit
        if mine.task_id != theirs.task_id or time.monotonic() - self._at > MERGE_WINDOW_SECONDS:
            return False
        # Only the shapes a person actually produces by typing: adding at the end of what
        # was added, and backspacing into it.
        appending = (
            not mine.removed and not theirs.removed and theirs.pos == mine.pos + len(mine.added)
        )
        backspacing = not theirs.added and theirs.pos + len(theirs.removed) == mine.pos + len(
            mine.added
        )
        if appending:
            self.edit = TextEdit(mine.task_id, mine.pos, mine.removed, mine.added + theirs.added)
        elif backspacing and len(mine.added) >= len(theirs.removed):
            self.edit = TextEdit(
                mine.task_id, mine.pos, mine.removed, mine.added[: -len(theirs.removed)]
            )
        else:
            return False
        self._at = time.monotonic()
        return True


class SetTitleCommand:
    def __init__(self, task_id: TaskId, value: str, view_origin: object | None = None) -> None:
        self.task_id = task_id
        self.value = value
        self._before: str | None = None
        self._next_origin = view_origin

    def text(self) -> str:
        return "Rename"

    def redo(self, plan: Plan) -> None:
        if self._before is None:
            self._before = plan.task(self.task_id).title
        plan.set_title(self.task_id, self.value, self._next_origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, plan: Plan) -> None:
        assert self._before is not None
        plan.set_title(self.task_id, self._before, UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        if not isinstance(other, SetTitleCommand) or other.task_id != self.task_id:
            return False
        self.value = other.value
        return True


class SetNotesCommand:
    def __init__(self, task_id: TaskId, value: str, view_origin: object | None = None) -> None:
        self.task_id = task_id
        self.value = value
        self._before: str | None = None
        self._next_origin = view_origin

    def text(self) -> str:
        return "Edit Notes"

    def redo(self, plan: Plan) -> None:
        if self._before is None:
            self._before = plan.task(self.task_id).notes
        plan.set_notes(self.task_id, self.value, self._next_origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, plan: Plan) -> None:
        assert self._before is not None
        plan.set_notes(self.task_id, self._before, UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        if not isinstance(other, SetNotesCommand) or other.task_id != self.task_id:
            return False
        self.value = other.value
        return True


class SetFieldCommand:
    """One of the plan's value fields: status, assignee, estimate, start, due.

    One command for five fields rather than five near-identical classes — they are edited
    the same way, undone the same way, and differ only in what the menu calls them.
    """

    def __init__(
        self, task_id: TaskId, field: str, value: object, view_origin: object | None = None
    ) -> None:
        self.task_id = task_id
        self.field = field
        self.value = value
        self._before: object = None
        self._captured = False
        self._next_origin = view_origin

    def text(self) -> str:
        return FIELD_LABELS.get(self.field, "Set Field")

    def redo(self, plan: Plan) -> None:
        if not self._captured:
            self._before = getattr(plan.task(self.task_id), self.field)
            self._captured = True
        plan.set_field(self.task_id, self.field, self.value, self._next_origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, plan: Plan) -> None:
        plan.set_field(self.task_id, self.field, self._before, UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        # Two different fields never merge, however fast they were typed: undoing an
        # estimate should not silently undo a status change made a moment earlier.
        if (
            not isinstance(other, SetFieldCommand)
            or other.task_id != self.task_id
            or other.field != self.field
        ):
            return False
        self.value = other.value
        return True


class SetDependenciesCommand:
    def __init__(
        self, task_id: TaskId, depends_on: list[TaskId], view_origin: object | None = None
    ) -> None:
        self.task_id = task_id
        self.depends_on = list(depends_on)
        self._before: list[TaskId] | None = None
        self._next_origin = view_origin

    def text(self) -> str:
        return "Change Dependencies"

    def redo(self, plan: Plan) -> None:
        if self._before is None:
            self._before = list(plan.task(self.task_id).depends_on)
        plan.set_dependencies(self.task_id, self.depends_on, self._next_origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, plan: Plan) -> None:
        assert self._before is not None
        plan.set_dependencies(self.task_id, self._before, UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        return False


class AddTaskCommand:
    def __init__(self, parent_id: TaskId, task: Task, index: int | None = None) -> None:
        self.parent_id = parent_id
        self.task = task
        self.index = index

    def text(self) -> str:
        return "Add Task"

    def redo(self, plan: Plan) -> None:
        plan.add_task(self.parent_id, self.task, self.index)

    def undo(self, plan: Plan) -> None:
        _, self.index = plan.remove_task(self.task.id)

    def merge_with(self, other: Command) -> bool:
        return False


class RemoveTaskCommand:
    def __init__(self, task_id: TaskId) -> None:
        self.task_id = task_id
        self._task: Task | None = None
        self._parent_id = ""
        self._index = 0

    def text(self) -> str:
        return "Delete Task"

    def redo(self, plan: Plan) -> None:
        self._task = plan.task(self.task_id)
        self._parent_id, self._index = plan.remove_task(self.task_id)

    def undo(self, plan: Plan) -> None:
        assert self._task is not None
        plan.restore_task(self._parent_id, self._task, self._index)

    def merge_with(self, other: Command) -> bool:
        return False


class MoveTaskCommand:
    def __init__(self, task_id: TaskId, new_parent_id: TaskId, index: int) -> None:
        self.task_id = task_id
        self.new_parent_id = new_parent_id
        self.index = index
        self._old_parent_id = ""
        self._old_index = 0

    def text(self) -> str:
        return "Move Task"

    def redo(self, plan: Plan) -> None:
        task = plan.task(self.task_id)
        parent = task.parent
        assert parent is not None
        self._old_parent_id, self._old_index = parent.id, parent.children.index(task)
        plan.move_task(self.task_id, self.new_parent_id, self.index)

    def undo(self, plan: Plan) -> None:
        plan.move_task(self.task_id, self._old_parent_id, self._old_index)

    def merge_with(self, other: Command) -> bool:
        return False


class CompositeCommand:
    """Several commands as one undo step — "Delete 5 tasks" must undo as one gesture."""

    def __init__(self, label: str, commands: list[Command]) -> None:
        self.label = label
        self.commands = commands

    def text(self) -> str:
        return self.label

    def redo(self, plan: Plan) -> None:
        for command in self.commands:
            command.redo(plan)

    def undo(self, plan: Plan) -> None:
        for command in reversed(self.commands):
            command.undo(plan)

    def merge_with(self, other: Command) -> bool:
        return False
