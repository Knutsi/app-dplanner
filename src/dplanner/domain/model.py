"""The plan model: a tree of tasks, plus the dependencies between them.

Two classes and one convention. :class:`Task` is dumb data — a node with fields and
children, mutated only through :class:`Plan`. :class:`Plan` is the aggregate: it owns the
tree, keeps an id index, and is the single place a change can happen, which is what makes
"every change emits exactly one signal" true rather than hopeful.

**Identity is the id, never the position.** ``uuid4().hex``, generated at creation and
written into the JSON. A task keeps its identity through renames, moves and reorders — which
is what lets an open tab, a selection, an undo command and *another task's dependency list*
all keep pointing at the right thing while the plan is rearranged underneath them.

**Every mutator takes an origin.** A view that edits passes itself, then ignores the signal
when ``origin is self`` — its widget already shows the change. Undo passes a token matching
no view, so every view applies it.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from dplanner.core.fsio import slugify
from dplanner.core.repository import Origin
from dplanner.core.signals import Signal

type TaskId = str

# Where a task is. Ordered from not-started to finished, because that order is meaningful:
# it is what a progress roll-up and a board's column order both read.
STATUSES: Final = ("todo", "blocked", "doing", "done")
DEFAULT_STATUS: Final = "todo"

# Fields that are a single value and change as a unit — edited through SetFieldCommand and
# announced through `field_changed`. Text-shaped fields have their own signals, because a
# positional edit is not a value replacement.
VALUE_FIELDS: Final = ("status", "assignee", "estimate_days", "start", "due")

# Names a task's folder can never take, because the format already uses them.
RESERVED_FOLDER_NAMES = frozenset({"modules"})


@dataclass(frozen=True)
class TextEdit:
    """One change to one task's description: what was removed, what was added, and where."""

    task_id: TaskId
    pos: int
    removed: str
    added: str

    def inverted(self) -> "TextEdit":
        return TextEdit(self.task_id, self.pos, removed=self.added, added=self.removed)


def now_stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Task:
    """A node in the plan. Dumb data — mutate through :class:`Plan` only."""

    def __init__(
        self,
        *,
        task_id: TaskId | None = None,
        title: str = "",
        description: str = "",
        notes: str = "",
        status: str = DEFAULT_STATUS,
        assignee: str = "",
        estimate_days: float | None = None,
        start: str = "",
        due: str = "",
        depends_on: list[TaskId] | None = None,
        folder_name: str = "",
        created: str = "",
    ) -> None:
        self.id: TaskId = task_id or uuid.uuid4().hex
        self.title = title
        self.description = description  # What the work is. Markdown.
        self.notes = notes  # Working notes, kept in their own file so diffs stay small.
        self.status = status
        self.assignee = assignee
        # Coerced, not just annotated. An int slipping in writes as `5` where a reloaded
        # float writes as `5.0` — which would make a plan's bytes depend on whether it had
        # been reopened since it was created, and every diff noisy for no reason.
        self.estimate_days = _as_estimate(estimate_days)  # None = not estimated, not zero.
        self.start = start  # ISO date, "" when unset.
        self.due = due
        # Ids of tasks that must finish first. Not derived from the tree: a task in one
        # phase routinely waits on one in another.
        self.depends_on: list[TaskId] = list(depends_on or [])
        # Frozen at creation and never following a retitle: identity is the id, the folder
        # name is presentation, and renaming a folder churns history for no benefit.
        self.folder_name = folder_name
        self.created = created or now_stamp()
        self.children: list[Task] = []
        self.parent: Task | None = None
        self.module_data: dict[str, dict[str, Any]] = {}

    def __repr__(self) -> str:
        return f"Task({self.title!r}, {self.status}, id={self.id[:8]})"

    def walk(self) -> Iterator["Task"]:
        """This task, then every descendant, depth first."""
        yield self
        for child in self.children:
            yield from child.walk()

    def has_children(self) -> bool:
        return bool(self.children)

    def is_done(self) -> bool:
        """A leaf is done when it says so; a phase is done when everything under it is.

        Derived rather than stored, so a phase cannot disagree with its contents — the
        classic way a plan starts lying to the person reading it.
        """
        if not self.children:
            return self.status == "done"
        return all(child.is_done() for child in self.children)

    def rolled_up_estimate(self) -> float:
        """This task's estimate, or the sum of its children's. Unestimated counts as zero,
        which is why :meth:`unestimated` exists to say how much of that is a guess."""
        if not self.children:
            return self.estimate_days or 0.0
        return sum(child.rolled_up_estimate() for child in self.children)

    def unestimated(self) -> int:
        """How many leaves under here carry no estimate."""
        leaves = [task for task in self.walk() if not task.children]
        return sum(1 for leaf in leaves if leaf.estimate_days is None)


class Plan:
    """The aggregate: one tree of tasks, its index, and every way to change it."""

    def __init__(self, root: Task, *, title: str = "") -> None:
        self.root = root
        self.title = title or root.title
        self._by_id: dict[TaskId, Task] = {}
        self._reindex()

        # One signal per kind of change, each carrying the origin that caused it.
        self.title_changed: Signal[TaskId, Origin] = Signal()
        self.field_changed: Signal[TaskId, str, Origin] = Signal()  # status, assignee, …
        self.text_edited: Signal[TextEdit, Origin] = Signal()  # the description
        self.notes_edited: Signal[TaskId, Origin] = Signal()
        self.dependencies_changed: Signal[TaskId, Origin] = Signal()
        self.structure_changed: Signal[TaskId] = Signal()  # The changed parent's id.
        self.module_data_changed: Signal[TaskId, str] = Signal()
        # (owner id, aspect) — the framework's autosave debounces this.
        self.dirty: Signal[str, str] = Signal()

    # -- lookup --------------------------------------------------------------------------------

    def _reindex(self) -> None:
        self._by_id = {}
        for task in self.root.walk():
            self._by_id[task.id] = task
            for child in task.children:
                child.parent = task

    def task(self, task_id: TaskId) -> Task:
        return self._by_id[task_id]

    def has(self, task_id: TaskId) -> bool:
        return task_id in self._by_id

    def tasks(self) -> Iterator[Task]:
        return self.root.walk()

    # -- fields --------------------------------------------------------------------------------

    def set_title(self, task_id: TaskId, title: str, origin: Origin = None) -> None:
        task = self.task(task_id)
        if task.title == title:
            return
        task.title = title
        if task is self.root:
            self.title = title
        self.dirty.emit(task_id, "meta")
        self.title_changed.emit(task_id, origin)

    def set_field(self, task_id: TaskId, field: str, value: object, origin: Origin = None) -> None:
        """Set one of :data:`VALUE_FIELDS`. One mutator rather than five, because the
        commands, the property panel and the undo labels all treat them identically."""
        if field not in VALUE_FIELDS:
            raise ValueError(f"{field!r} is not an editable value field")
        task = self.task(task_id)
        if field == "status" and value not in STATUSES:
            raise ValueError(f"{value!r} is not a status")
        if field == "estimate_days":
            value = _as_estimate(value)
        if getattr(task, field) == value:
            return
        setattr(task, field, value)
        self.dirty.emit(task_id, "meta")
        self.field_changed.emit(task_id, field, origin)

    def apply_text_edit(self, edit: TextEdit, origin: Origin = None) -> None:
        """Apply a positioned edit to a description, refusing one that does not match.

        The check is not defensive noise: a binding whose view has drifted out of sync would
        otherwise write plausible nonsense that no later read could detect.
        """
        task = self.task(edit.task_id)
        actual = task.description[edit.pos : edit.pos + len(edit.removed)]
        if actual != edit.removed:
            raise ValueError(
                f"stale TextEdit for task {edit.task_id}: expected {edit.removed!r} "
                f"at {edit.pos}, found {actual!r}"
            )
        task.description = (
            task.description[: edit.pos]
            + edit.added
            + task.description[edit.pos + len(edit.removed) :]
        )
        self.dirty.emit(edit.task_id, "description")
        self.text_edited.emit(edit, origin)

    def set_description(self, task_id: TaskId, text: str, origin: Origin = None) -> None:
        task = self.task(task_id)
        if task.description == text:
            return
        self.apply_text_edit(TextEdit(task_id, 0, task.description, text), origin)

    def set_notes(self, task_id: TaskId, notes: str, origin: Origin = None) -> None:
        task = self.task(task_id)
        if task.notes == notes:
            return
        task.notes = notes
        self.dirty.emit(task_id, "notes")
        self.notes_edited.emit(task_id, origin)

    # -- dependencies --------------------------------------------------------------------------

    def set_dependencies(
        self, task_id: TaskId, depends_on: list[TaskId], origin: Origin = None
    ) -> None:
        """Replace what a task waits on, refusing anything that cannot be true.

        Three refusals, and each is a plan that would otherwise be quietly unsatisfiable: a
        task waiting on itself, on something that does not exist, or on a chain that leads
        back to it. Catching a cycle here means the scheduler above never has to.
        """
        task = self.task(task_id)
        wanted = list(dict.fromkeys(depends_on))  # De-duplicate, keep the given order.
        for other_id in wanted:
            if other_id == task_id:
                raise ValueError("a task cannot depend on itself")
            if other_id not in self._by_id:
                raise ValueError(f"no such task: {other_id}")
            if self._reaches(other_id, task_id):
                raise ValueError(
                    f"{self.task(other_id).title!r} already waits on this task — that is a cycle"
                )
        if task.depends_on == wanted:
            return
        task.depends_on = wanted
        self.dirty.emit(task_id, "meta")
        self.dependencies_changed.emit(task_id, origin)

    def _reaches(self, start: TaskId, target: TaskId) -> bool:
        """Whether ``start`` waits, directly or through others, on ``target``."""
        seen: set[TaskId] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in seen or current not in self._by_id:
                continue
            seen.add(current)
            stack.extend(self.task(current).depends_on)
        return False

    def blockers(self, task_id: TaskId) -> list[Task]:
        """The tasks this one is still waiting on — dependencies that are not done."""
        task = self.task(task_id)
        return [
            self.task(other)
            for other in task.depends_on
            if other in self._by_id and not self.task(other).is_done()
        ]

    # -- structure -----------------------------------------------------------------------------

    def add_task(self, parent_id: TaskId, task: Task, index: int | None = None) -> TaskId:
        parent = self.task(parent_id)
        if not task.folder_name:
            task.folder_name = unique_folder_name(task.title, self.taken_names(parent))
        task.parent = parent
        parent.children.insert(len(parent.children) if index is None else index, task)
        for node in task.walk():
            self._by_id[node.id] = node
        self.dirty.emit(parent_id, "structure")
        self.structure_changed.emit(parent_id)
        return task.id

    def remove_task(self, task_id: TaskId) -> tuple[TaskId, int]:
        """Detach a task and its subtree; returns where it was, so undo can put it back.

        Dependencies pointing at the removed subtree are left alone on purpose. Undo has to
        restore the plan exactly, and silently rewriting other tasks' dependency lists would
        make delete-then-undo lossy. :meth:`blockers` already skips ids it cannot resolve.
        """
        task = self.task(task_id)
        parent = task.parent
        if parent is None:
            raise ValueError("the project root cannot be removed")
        index = parent.children.index(task)
        parent.children.remove(task)
        task.parent = None
        for node in task.walk():
            del self._by_id[node.id]
        self.dirty.emit(parent.id, "structure")
        self.structure_changed.emit(parent.id)
        return parent.id, index

    def restore_task(self, parent_id: TaskId, task: Task, index: int) -> None:
        """Put a removed subtree back exactly where it was. The inverse of remove_task."""
        self.add_task(parent_id, task, index)

    def move_task(self, task_id: TaskId, new_parent_id: TaskId, index: int) -> None:
        task = self.task(task_id)
        old_parent = task.parent
        if old_parent is None:
            raise ValueError("the project root cannot be moved")
        new_parent = self.task(new_parent_id)
        if any(node is new_parent for node in task.walk()):
            raise ValueError("a task cannot be moved inside itself")
        old_parent.children.remove(task)
        new_parent.children.insert(index, task)
        task.parent = new_parent
        self.dirty.emit(old_parent.id, "structure")
        self.structure_changed.emit(old_parent.id)
        if new_parent is not old_parent:
            self.dirty.emit(new_parent.id, "structure")
            self.structure_changed.emit(new_parent.id)

    def taken_names(self, parent: Task) -> set[str]:
        return {child.folder_name for child in parent.children} | set(RESERVED_FOLDER_NAMES)

    # -- module data ---------------------------------------------------------------------------

    def set_module_data(self, task_id: TaskId, module_id: str, data: dict[str, Any]) -> None:
        """Replace one module's entry. An empty dict removes it, and the file with it."""
        task = self.task(task_id)
        if data:
            task.module_data[module_id] = data
        else:
            task.module_data.pop(module_id, None)
        self.dirty.emit(task_id, "module_data")
        self.module_data_changed.emit(task_id, module_id)


def _as_estimate(value: object) -> float | None:
    """An estimate in days, or None. Anything unreadable becomes None rather than zero:
    "we have not estimated this" and "this is free" are different claims."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def unique_folder_name(title: str, taken: set[str]) -> str:
    """A slug for ``title`` that no sibling is using."""
    base = slugify(title, fallback="task")
    if base not in taken:
        return base
    for suffix in range(2, 1000):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:6]}"
