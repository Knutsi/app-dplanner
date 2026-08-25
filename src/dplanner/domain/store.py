"""The plan on disk: one directory per task, nested exactly like the plan.

This is the file that decides what a plan *looks like* on disk, and its three conventions
are what make a file-backed format survive being shared through version control:

**Ordering lives in the parent's ``children`` list**, never in ``01-``/``02-`` filename
prefixes. Reordering two tasks is a one-line JSON diff instead of a mass rename.

**A folder name is frozen at creation** and never follows a retitle. Editing a title
changes one JSON value; it does not move a directory and rewrite its history.

**Absence encodes the default.** An optional key is written only when it is not the
default, and an empty ``text.md`` is deleted rather than written blank — so a diff shows
exactly what actually changed, and an untouched task is visibly untouched.

The store is passive: it serialises, it does not notify. Change notification lives on the
aggregate, where the change happened. What the store implements for the framework is
:class:`~dplanner.core.repository.Persister` — one ``flush(marks)`` that writes exactly the
aspects that are dirty, in the order this format requires.
"""

import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dplanner.core.formats import FORMAT_KEY, UnsupportedFormatError
from dplanner.core.repository import DataOwner, DirtyMark
from dplanner.core.signals import Signal
from dplanner.core.storage.provider import StorageProvider
from dplanner.domain.migrations import FORMAT
from dplanner.domain.model import (
    DEFAULT_STATUS,
    Plan,
    Task,
    TaskId,
    unique_folder_name,
)

ROOT_META = "plan.json"
TASK_META = "task.json"
TEXT_FILE = "description.md"
NOTES_FILE = "notes.md"
MODULES_DIR = "modules"


class PlanStore:
    """Loads and saves one :class:`Plan` through a storage provider.

    Note what it takes: a :class:`~dplanner.core.storage.provider.StorageProvider`, not a
    path. Everything below goes through that interface, which is why the same store works
    against a plain folder, a git checkout and a GitHub clone without knowing which it has.
    """

    def __init__(self, storage: StorageProvider) -> None:
        self.storage = storage
        self.plan: Plan | None = None
        # Task id → its directory, workspace-relative. This one dict is what makes
        # reorder, reparent, rename and undo-of-delete all the same operation from
        # outside: the tree says where an task *should* live, this says where it *does*.
        self._dirs: dict[TaskId, str] = {}
        self.dirty: Signal[str, str] = Signal()

    # -- opening -------------------------------------------------------------------------------

    def exists(self) -> bool:
        return self.storage.exists(ROOT_META)

    def load(self) -> Plan:
        """Read the workspace, running any pending format migrations, then save it back.

        The save at the end is not optional: a migration that ran but was never persisted
        would run again on the next open, against data a later autosave may already have
        partly rewritten. Migrate once, write once.
        """
        raw = self._read_json(ROOT_META)
        found = FORMAT.read_version(raw, self.storage.root / ROOT_META)
        pending = FORMAT.pending(found)

        root = self._load_task(raw, "", pending)
        plan = Plan(root, title=str(raw.get("title", root.title)))
        for migration in pending:
            if migration.whole is not None:
                migration.whole(plan)
        self._adopt(plan)
        if pending:
            self.save_all(plan)
        return plan

    def _adopt(self, plan: Plan) -> None:
        """Hold this plan and forward its dirty marks — one place, so create() and
        load() cannot disagree about it."""
        self.plan = plan
        plan.dirty.connect(self.dirty.emit)

    def _load_task(self, meta: dict[str, Any], directory: str, pending: tuple[Any, ...]) -> Task:
        raw_estimate = meta.get("estimate_days")
        task = Task(
            task_id=str(meta.get("id", "")) or None,
            title=str(meta.get("title", "")),
            description=self.storage.read_text(_join(directory, TEXT_FILE)) or "",
            notes=self.storage.read_text(_join(directory, NOTES_FILE)) or "",
            # Tolerant on every field: a hand-edited plan, or one written by a newer build,
            # must open rather than crash. An unreadable value falls back to its default.
            status=str(meta.get("status", DEFAULT_STATUS)),
            assignee=str(meta.get("assignee", "")),
            estimate_days=float(raw_estimate) if isinstance(raw_estimate, int | float) else None,
            start=str(meta.get("start", "")),
            due=str(meta.get("due", "")),
            depends_on=[str(dep) for dep in meta.get("depends_on", []) if isinstance(dep, str)],
            folder_name=directory.rsplit("/", 1)[-1],
            created=str(meta.get("created", "")),
        )
        for migration in pending:
            if migration.node is not None:
                migration.node(task, meta, self.storage.root / directory)
        task.module_data = self._load_module_data(directory)
        self._dirs[task.id] = directory

        listed = [str(name) for name in meta.get("children", []) if isinstance(name, str)]
        # Directories that hold a task.json but are not listed are adopted rather than
        # ignored: a folder someone created by hand, or that a merge resurrected, is data.
        present = [
            name
            for name in self.storage.list_dir(directory)
            if name != MODULES_DIR and self.storage.exists(_join(directory, name, TASK_META))
        ]
        for name in listed + [n for n in present if n not in listed]:
            child_dir = _join(directory, name)
            if not self.storage.exists(_join(child_dir, TASK_META)):
                continue
            child_meta = self._read_json(_join(child_dir, TASK_META))
            child = self._load_task(child_meta, child_dir, pending)
            child.parent = task
            task.children.append(child)
        return task

    def _load_module_data(self, directory: str) -> dict[str, dict[str, Any]]:
        """Every ``modules/*.json``, by filename. Entries this build knows nothing about
        are loaded and saved back untouched, so a workspace shared with a newer build
        never loses that build's data."""
        data: dict[str, dict[str, Any]] = {}
        for name in self.storage.list_dir(_join(directory, MODULES_DIR)):
            if not name.endswith(".json"):
                continue
            entry = self._read_json(_join(directory, MODULES_DIR, name))
            if entry:
                data[name.removesuffix(".json")] = entry
        return data

    def _read_json(self, path: str) -> dict[str, Any]:
        text = self.storage.read_text(path)
        if text is None:
            return {}
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write_json(self, path: str, data: dict[str, Any]) -> None:
        self.storage.write_text(
            path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )

    # -- the Repository face the framework uses ------------------------------------------------

    def owners(self) -> Iterable[DataOwner]:
        return [] if self.plan is None else list(self.plan.tasks())

    def owner(self, owner_id: str) -> DataOwner | None:
        if self.plan is None or not self.plan.has(owner_id):
            return None
        return self.plan.task(owner_id)

    def set_module_data(self, owner_id: str, module_id: str, data: dict[str, Any]) -> None:
        assert self.plan is not None
        self.plan.set_module_data(owner_id, module_id, data)

    def close(self) -> None:
        self.plan = None

    # -- writing -------------------------------------------------------------------------------

    def flush(self, marks: set[DirtyMark]) -> None:
        """Write exactly what ``marks`` names.

        Structure is done in two passes on purpose. A single pass that synced and cleaned
        one task at a time could delete a subtree that a pending move has not relocated
        yet — the directories must all exist in their new places before any old one is
        removed.
        """
        plan = self.plan
        if plan is None:
            return
        structural = [task_id for task_id, aspect in marks if aspect == "structure"]
        for task_id in structural:
            if plan.has(task_id):
                for child in plan.task(task_id).children:
                    self._sync_dir(child)
        for task_id in structural:
            if plan.has(task_id):
                self._remove_orphans(plan.task(task_id))
                self._write_meta(plan.task(task_id))
        for task_id, aspect in marks:
            if aspect == "structure" or not plan.has(task_id):
                continue
            task = plan.task(task_id)
            if aspect == "meta":
                self._write_meta(task)
            elif aspect == "description":
                self._write_optional(_join(self._dirs[task.id], TEXT_FILE), task.description)
            elif aspect == "notes":
                self._write_optional(_join(self._dirs[task.id], NOTES_FILE), task.notes)
            elif aspect == "module_data":
                self._write_module_data(task)

    def create(self, plan: Plan) -> None:
        """Write a brand-new workspace. The root sits at the workspace root itself."""
        self._dirs[plan.root.id] = ""
        self._adopt(plan)
        self.save_all(plan)

    def save_all(self, plan: Plan) -> None:
        """Write the whole workspace. Used after a migration and when creating one."""
        for task in plan.tasks():
            if task is not plan.root:
                self._sync_dir(task)
        for task in plan.tasks():
            self._write_meta(task)
            self._write_optional(_join(self._dirs[task.id], TEXT_FILE), task.description)
            self._write_optional(_join(self._dirs[task.id], NOTES_FILE), task.notes)
            self._write_module_data(task)

    def _sync_dir(self, task: Task) -> None:
        """Make the directory match where the tree says this task lives.

        Three cases, and they are deliberately the same operation from outside: an task
        that moved is renamed, one that is new gets its subtree written, and one that was
        deleted and then undone is also "new" — its old directory is gone, so it is written
        again from memory. That last case is why this checks the disk rather than trusting
        ``_dirs``: the recorded path can be right and the directory still not be there.
        """
        parent = task.parent
        assert parent is not None
        parent_dir = self._dirs[parent.id]
        if not task.folder_name:
            task.folder_name = _unique(task.title, self.storage.list_dir(parent_dir))
        target = _join(parent_dir, task.folder_name)
        current = self._dirs.get(task.id)

        if current is not None and current != target and self.storage.exists(current):
            (self.storage.root / target).parent.mkdir(parents=True, exist_ok=True)
            (self.storage.root / current).rename(self.storage.root / target)
            self._rebase(task, current, target)
            return

        self._rebase(task, current, target)
        if not self.storage.exists(_join(target, TASK_META)):
            self._write_subtree(task)

    def _write_subtree(self, task: Task) -> None:
        """Write an task and everything under it — for one that is not on disk at all."""
        for node in task.walk():
            self.storage.make_dir(self._dirs[node.id])
            self._write_meta(node)
            self._write_optional(_join(self._dirs[node.id], TEXT_FILE), node.description)
            self._write_optional(_join(self._dirs[node.id], NOTES_FILE), node.notes)
            self._write_module_data(node)

    def _rebase(self, task: Task, old: str | None, new: str) -> None:
        self._dirs[task.id] = new
        for child in task.children:
            child_old = self._dirs.get(child.id)
            self._rebase(child, child_old, _join(new, child.folder_name))

    def _remove_orphans(self, parent: Task) -> None:
        """Delete directories under ``parent`` that no longer belong to any child."""
        keep = {child.folder_name for child in parent.children} | {MODULES_DIR}
        parent_dir = self._dirs[parent.id]
        for name in self.storage.list_dir(parent_dir):
            path = _join(parent_dir, name)
            if name in keep or not self.storage.is_dir(path):
                continue
            if self.storage.exists(_join(path, TASK_META)):
                _rmtree(self.storage.root / path)

    def _write_meta(self, task: Task) -> None:
        directory = self._dirs[task.id]
        is_root = task.parent is None
        # Absence encodes the default: an untouched field is not written, so a diff shows
        # exactly the tasks whose plan actually changed.
        meta: dict[str, Any] = {"id": task.id, "created": task.created}
        if task.title:
            meta["title"] = task.title
        if task.status != DEFAULT_STATUS:
            meta["status"] = task.status
        if task.assignee:
            meta["assignee"] = task.assignee
        if task.estimate_days is not None:
            meta["estimate_days"] = task.estimate_days
        if task.start:
            meta["start"] = task.start
        if task.due:
            meta["due"] = task.due
        if task.depends_on:
            meta["depends_on"] = list(task.depends_on)
        if task.children:
            meta["children"] = [child.folder_name for child in task.children]
        if is_root:
            meta[FORMAT_KEY] = FORMAT.current_version
        self._write_json(_join(directory, ROOT_META if is_root else TASK_META), meta)

    def _write_optional(self, path: str, text: str) -> None:
        """Write the file, or remove it when the value is empty.

        An empty file and an absent one mean the same thing to the loader, but only one of
        them is invisible in a diff and in a file browser.
        """
        if text:
            self.storage.write_text(path, text)
        else:
            self.storage.delete(path)

    def _write_module_data(self, task: Task) -> None:
        directory = _join(self._dirs[task.id], MODULES_DIR)
        wanted = {f"{module_id}.json" for module_id in task.module_data}
        for name in self.storage.list_dir(directory):
            if name.endswith(".json") and name not in wanted:
                self.storage.delete(_join(directory, name))
        for module_id, data in task.module_data.items():
            self._write_json(_join(directory, f"{module_id}.json"), data)
        if not wanted:
            self.storage.delete(directory)  # Removes it only when it is empty.


def _join(*parts: str) -> str:
    return "/".join(part for part in parts if part)


def _unique(title: str, taken: list[str]) -> str:
    return unique_folder_name(title, set(taken))


def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


__all__ = ["PlanStore", "UnsupportedFormatError"]
