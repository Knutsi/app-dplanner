"""The library on disk: a per-user list of project directories, each one self-contained.

The library file (see :mod:`dplanner.domain.library_file`) records *membership*: which
project directories this user is planning. Everything else lives in the project directory
itself, which sits inside a git repository and travels with it::

    <repository>/
    └── <project directory>/
        ├── project.dproj              id, title, summary, created, format, children
        ├── modules/
        └── steps/<slug>/
            ├── step.json              id, title, edges
            └── modules/
                ├── estimation.json          structured data
                ├── step_description.md      prose
                └── step_description/        files this module owns

The store is therefore **multi-root**: one storage provider per project directory, opened
through :func:`~dplanner.core.storage.locations.open_project_storage`. A project that
cannot be opened — folder gone, no meta file, not in a repository, written by a newer
build — becomes a :class:`ProjectProblem` row rather than sinking the whole library.

The conventions inside a project are what make a file-backed format survive being shared
through version control:

**Ordering lives in the parent's list**, never in ``01-``/``02-`` filename prefixes.
**A folder name is frozen at creation** and never follows a retitle. **Absence encodes the
default** — an optional key is written only when it is not the default, and an empty
document is deleted rather than written blank. **Container directories say what a level
is** — steps never sit beside ``modules/``. And one naming rule covers module storage:
**``modules/<id>.json`` is a module's data, ``modules/<id>.md`` is its prose, and
``modules/<id>/`` is its files** — every one round-tripped by name, so data belonging to a
module this build does not have survives untouched.

**Two writers, one folder — now per project.** An agent drives ``dplanner`` against a
directory a window has open, so the store remembers what each project looked like when it
last read or wrote it and refuses to flush over anything that changed underneath — but the
check is per project: an agent editing project B never blocks saving project A. The library
file gets the same treatment with its own stamp, because two instances can both add a
project. See :meth:`changed_underneath` and :class:`StaleWorkspaceError`.

The store is passive: it serialises, it does not notify. Change notification lives on the
aggregate, where the change happened. What it implements for the framework is
:class:`~dplanner.core.repository.Persister` — one ``flush(marks)`` that writes exactly the
aspects that are dirty, in the order this format requires. A structure mark on the *library
root* means the membership changed, and rewrites the library file.
"""

import json
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dplanner.core.formats import FORMAT_KEY, UnsupportedFormatError
from dplanner.core.repository import DataOwner, DirtyMark
from dplanner.core.signals import Signal
from dplanner.core.storage.locations import (
    find_repo_root,
    grouped_by_repo,
    open_project_storage,
    repo_group_for,
)
from dplanner.core.storage.provider import StorageError, StorageProvider
from dplanner.domain.library_file import read_library_file, write_library_file
from dplanner.domain.migrations import FORMAT
from dplanner.domain.model import (
    Library,
    Node,
    NodeId,
    Project,
    ProjectId,
    Step,
    unique_folder_name,
)

PROJECT_META = "project.dproj"
STEP_META = "step.json"
MODULES_DIR = "modules"
STEPS_DIR = "steps"

# Which container directory holds a node's children, and what a child's meta file is called.
CONTAINER = {"project": STEPS_DIR}
META_FILE = {"project": PROJECT_META, "step": STEP_META}


class StaleWorkspaceError(RuntimeError):
    """A project directory (or the library file) changed on disk since it was last seen.

    Not an error in the data and not a bug: somebody else — the CLI, an agent, a branch
    switch, a colleague's merge, another window — wrote to the same folder. Whoever catches
    this decides what to do about it, and the only safe options are to reload or to be told.
    """


@dataclass(frozen=True)
class ProjectProblem:
    """A library entry that could not be opened, and why. The panel shows these greyed."""

    path: Path
    reason: str


@dataclass
class _ProjectRecord:
    """One open project directory: its provider, and what the store knows about its disk."""

    directory: Path
    storage: StorageProvider
    # Node id → its directory, project-relative ("" is the project's own). This one dict is
    # what makes reorder, rename and undo-of-delete all the same operation from outside:
    # the model says where a node *should* live, this says where it *does*.
    dirs: dict[NodeId, str] = field(default_factory=dict)
    # What the directory looked like the last time this store read or wrote it. Size and
    # modification time per file — what every build tool uses for the same question.
    disk: dict[str, tuple[int, int]] = field(default_factory=dict)


class ModuleFileArea:
    """The directory one module owns beside its JSON, for content JSON cannot hold well.

    Markdown belongs in ``module_text`` — it is model state and it is undoable. This is for
    everything else a module needs to keep next to a node: images a description references,
    an attachment, a generated artefact. The store never writes into an area and never
    deletes one it did not create, so an area belonging to a module this build does not have
    is as safe as an unknown ``modules/*.json``.
    """

    def __init__(
        self, storage: StorageProvider, directory: str, noted: Callable[[str], None]
    ) -> None:
        self._storage = storage
        self.directory = directory
        # An area writes straight through the provider, so the store would otherwise see its
        # own asset as somebody else's edit and refuse the next flush. `noted` is how a write
        # here reaches the store's record of what the project looks like.
        self._noted = noted

    def names(self, subdirectory: str = "") -> list[str]:
        """The files directly in ``subdirectory`` of this area, sorted; directories omitted."""
        directory = _join(self.directory, subdirectory)
        return [
            name
            for name in self._storage.list_dir(directory)
            if not self._storage.is_dir(_join(directory, name))
        ]

    def read_bytes(self, name: str) -> bytes | None:
        return self._storage.read_bytes(_join(self.directory, name))

    def absolute(self, name: str) -> Path:
        """The file's place on the local disk — for handing to something outside the store."""
        return self._storage.root / _join(self.directory, name)

    def write_bytes(self, name: str, data: bytes) -> None:
        self._storage.write_bytes(_join(self.directory, name), data)
        self._noted(_join(self.directory, name))

    def remove(self, name: str) -> None:
        """Delete one file, and any directory it leaves empty up to the area itself.

        "Writing nothing leaves nothing behind" is the same rule the JSON entries follow:
        an empty directory is invisible in a diff but not in a file browser, and a project
        that accumulates them stops looking like the plan it holds.
        """
        self._storage.delete(_join(self.directory, name))
        self._noted(_join(self.directory, name))
        parts = [part for part in name.split("/")[:-1] if part]
        while parts:
            self._storage.delete(_join(self.directory, *parts))  # Only when it is empty.
            parts.pop()
        self._storage.delete(self.directory)


# The store's file lookup, handed to whoever needs a node's module files without
# holding the store: (node_id, module_id) -> the area. Raises KeyError for a node the
# store has never seen. One alias so five features do not spell it five ways.
FilesFor = Callable[[NodeId, str], ModuleFileArea]


class LibraryStore:
    """Loads and saves one :class:`Library` — the library file plus one provider per project.

    Note what a *project* goes through: a
    :class:`~dplanner.core.storage.provider.StorageProvider`, never a raw path. Everything
    below the meta level uses that interface, which is why the same store works whatever
    provider a project's directory supports.
    """

    def __init__(self, library_path: Path | str) -> None:
        self.library_path = Path(library_path).expanduser()
        self.library: Library | None = None
        self._records: dict[ProjectId, _ProjectRecord] = {}
        self._problems: list[ProjectProblem] = []
        # Library entries that failed to open keep their place in the file across rewrites:
        # a project this build cannot read is still the user's project.
        self._problem_paths: list[Path] = []
        # One provider per distinct git repository, cached because the sync feature
        # subscribes to their signals — rebuilt only when membership changes.
        self._groups: list[StorageProvider] | None = None
        self._library_stamp: tuple[int, int] | None = None
        self.dirty: Signal[str, str] = Signal()

    # -- opening -------------------------------------------------------------------------------

    def exists(self) -> bool:
        return self.library_path.is_file()

    def load(self) -> Library:
        """Read every project the library lists, running any pending format migrations.

        A migrated project is saved back immediately — migrate once, write once — and an
        entry that cannot be opened becomes a :class:`ProjectProblem` instead of a refusal:
        one bad row must not take every healthy project down with it.
        """
        library = Library()
        self._records.clear()
        self._problems.clear()
        self._problem_paths.clear()
        self._groups = None
        migrated: list[tuple[_ProjectRecord, Project]] = []
        for directory in read_library_file(self.library_path):
            try:
                project, record, pending = self._open_project(directory)
            except (StorageError, UnsupportedFormatError, OSError) as error:
                self._problems.append(ProjectProblem(directory, str(error)))
                self._problem_paths.append(directory)
                continue
            library.projects.append(project)
            self._records[project.id] = record
            if pending:
                migrated.append((record, project))
            else:
                self._remember_disk(record)
        library.reindex()
        self._adopt(library)
        for record, project in migrated:
            self._save_project(record, project)
        self._remember_library_stamp()
        return library

    def _open_project(
        self, directory: Path
    ) -> tuple[Project, _ProjectRecord, tuple[Any, ...]]:
        """Open one project directory, or raise ``StorageError`` saying why it cannot be."""
        directory = directory.expanduser()
        if not directory.is_dir():
            raise StorageError("the folder does not exist on this machine")
        if find_repo_root(directory) is None:
            raise StorageError("the folder is not inside a git repository")
        storage = open_project_storage(directory)
        if not storage.exists(PROJECT_META):
            raise StorageError(f"no {PROJECT_META} here — not a DPlanner project")
        raw = _read_json(storage, PROJECT_META)
        found = FORMAT.read_version(raw, storage.root / PROJECT_META)
        pending = FORMAT.pending(found)
        record = _ProjectRecord(directory=storage.root, storage=storage)
        project = self._load_project(record, raw, pending)
        for migration in pending:
            if migration.whole is not None:
                migration.whole(project)
        return project, record, pending

    def _load_project(
        self, record: _ProjectRecord, raw: dict[str, Any], pending: tuple[Any, ...]
    ) -> Project:
        project = Project(
            node_id=str(raw.get("id", "")) or None,
            title=str(raw.get("title", "")),
            summary=str(raw.get("summary", "")),
            folder_name=record.directory.name,
            created=str(raw.get("created", "")),
        )
        self._load_node_files(record, project, "", raw, pending)
        for folder in self._child_folders(record, raw, ""):
            project.steps.append(self._load_step(record, _join(STEPS_DIR, folder), pending))
        return project

    def _load_step(
        self, record: _ProjectRecord, directory: str, pending: tuple[Any, ...]
    ) -> Step:
        raw = _read_json(record.storage, _join(directory, STEP_META))
        step = Step(
            node_id=str(raw.get("id", "")) or None,
            title=str(raw.get("title", "")),
            # Tolerant on every field: a hand-edited project, or one written by a newer
            # build, must open rather than crash. Edge kinds this build does not know are
            # kept exactly as found, so a colleague's newer link survives a round trip here.
            edges=_read_edges(raw.get("edges")),
            folder_name=directory.rsplit("/", 1)[-1],
            created=str(raw.get("created", "")),
        )
        self._load_node_files(record, step, directory, raw, pending)
        return step

    def _load_node_files(
        self,
        record: _ProjectRecord,
        node: Node,
        directory: str,
        raw: dict[str, Any],
        pending: tuple[Any, ...],
    ) -> None:
        for migration in pending:
            if migration.node is not None:
                migration.node(node, raw, record.storage.root / directory)
        node.module_data, node.module_text = self._load_module_files(record, directory)
        record.dirs[node.id] = directory

    def _child_folders(
        self, record: _ProjectRecord, raw: dict[str, Any], directory: str
    ) -> list[str]:
        """The step folders of ``directory``, in the order the project recorded.

        Directories holding a step's meta file but missing from the list are appended
        rather than ignored: a folder someone created by hand, or that a merge resurrected,
        is data.
        """
        container = _join(directory, STEPS_DIR)
        listed = [name for name in raw.get("children", []) if isinstance(name, str)]
        present = [
            name
            for name in record.storage.list_dir(container)
            if record.storage.exists(_join(container, name, STEP_META))
        ]
        ordered = [name for name in listed if name in present]
        return ordered + [name for name in present if name not in listed]

    def _load_module_files(
        self, record: _ProjectRecord, directory: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Every ``modules/<id>.json`` and ``modules/<id>.md``, by filename.

        Entries this build knows nothing about are loaded and saved back untouched, so a
        project shared with a newer build never loses that build's data.
        """
        data: dict[str, dict[str, Any]] = {}
        text: dict[str, str] = {}
        for name in record.storage.list_dir(_join(directory, MODULES_DIR)):
            path = _join(directory, MODULES_DIR, name)
            if name.endswith(".json"):
                entry = _read_json(record.storage, path)
                if entry:
                    data[name.removesuffix(".json")] = entry
            elif name.endswith(".md"):
                document = record.storage.read_text(path)
                if document:
                    text[name.removesuffix(".md")] = document
        return data, text

    def _adopt(self, library: Library) -> None:
        """Hold this library and forward its dirty marks — one place, so load() and any
        later path cannot disagree about it."""
        self.library = library
        library.dirty.connect(self.dirty.emit)

    # -- membership ----------------------------------------------------------------------------

    def attach(self, directory: Path) -> Project:
        """Open a project directory and start tracking it. No model mutation here —
        the caller adds the returned project to the library, which marks the root
        structure dirty and gets the library file rewritten on the next flush."""
        project, record, pending = self._open_project(Path(directory))
        self._records[project.id] = record
        self._groups = None
        if pending:
            self._save_project(record, project)
        else:
            self._remember_disk(record)
        return project

    def detach(self, project_id: ProjectId) -> None:
        """Forget a project. Its files stay on disk — removal is from the library only."""
        self._records.pop(project_id, None)
        self._groups = None

    def project_dir(self, project_id: ProjectId) -> Path:
        return self._records[project_id].directory

    def problems(self) -> list[ProjectProblem]:
        return list(self._problems)

    def repo_groups(self) -> list[StorageProvider]:
        """One provider per distinct git repository, scoped to its projects' directories.

        Cached: the sync feature subscribes to these providers' signals, so their identity
        must be stable until membership actually changes (attach/detach invalidate).
        """
        if self._groups is None:
            self._groups = grouped_by_repo(
                [record.storage for record in self._records.values()]
            )
        return self._groups

    def repo_for(self, project_id: ProjectId) -> StorageProvider | None:
        """The repository group a project's directory belongs to, or None without one."""
        record = self._records.get(project_id)
        if record is None:
            return None
        return repo_group_for(record.storage, self.repo_groups())

    # -- the Repository face the framework uses ------------------------------------------------

    def owners(self) -> Iterable[DataOwner]:
        return [] if self.library is None else list(self.library.nodes())

    def owner(self, owner_id: str) -> DataOwner | None:
        if self.library is None or not self.library.has(owner_id):
            return None
        return self.library.node(owner_id)

    def set_module_data(self, owner_id: str, module_id: str, data: dict[str, Any]) -> None:
        assert self.library is not None
        self.library.set_module_data(owner_id, module_id, data)

    def files(self, node_id: NodeId, module_id: str) -> ModuleFileArea:
        """The directory ``module_id`` owns beside ``node_id``'s module data."""
        record = self._record_for(node_id)
        directory = _join(self._locate(record, node_id), MODULES_DIR, module_id)
        return ModuleFileArea(
            record.storage, directory, lambda path: self._note_written(record, path)
        )

    def _record_for(self, node_id: NodeId) -> _ProjectRecord:
        assert self.library is not None
        node = self.library.node(node_id)
        project = node if isinstance(node, Project) else self.library.project_of(node_id)
        return self._records[project.id]

    def _locate(self, record: _ProjectRecord, node_id: NodeId) -> str:
        """The node's directory, settled early for a node created since the last flush.

        ``dirs`` is normally filled at load and flush, but a file area can be asked for in
        the window between creating a node and the autosave that writes it. Settling the
        folder name here is safe because it is the same choice ``_sync_dir`` would make —
        that method keeps any name already on the node — and a folder name is frozen at
        creation anyway.
        """
        known = record.dirs.get(node_id)
        if known is not None:
            return known
        assert self.library is not None
        node = self.library.node(node_id)
        parent = self.library.parent_of(node_id)
        assert parent is not None, "a project's own directory is recorded when it is opened"
        container = _join(self._locate(record, parent.id), CONTAINER[parent.kind])
        if not node.folder_name:
            node.folder_name = unique_folder_name(
                node.title_for_folder(), set(record.storage.list_dir(container))
            )
        directory = _join(container, node.folder_name)
        record.dirs[node_id] = directory
        return directory

    def close(self) -> None:
        self.library = None

    # -- noticing another writer ---------------------------------------------------------------

    def changed_underneath(self) -> bool:
        """Whether any project — or the library file itself — differs from what was last seen.

        Deliberately coarse: this feeds the watcher, whose only move is a whole reload.
        The flush path checks per project instead, so one project's outside edit never
        blocks saving another.
        """
        if self._stat_library() != self._library_stamp:
            return True
        return any(
            self._snapshot(record) != record.disk for record in self._records.values()
        )

    def _snapshot(self, record: _ProjectRecord) -> dict[str, tuple[int, int]]:
        """Every file in the project directory, except git's own.

        A project directory is often the repository root itself (New Project's git-init
        flow makes exactly that), which would put `.git/` inside this walk — and git
        rewrites its own files constantly: a commit obviously, but even `git status`
        refreshes `.git/index`. Counting those as "another writer" made every Save read
        as an outside change and reload the application in a loop. Git's files are not
        plan content; pruning the directory also keeps the 1.5-second autosave cadence
        from walking a repository's whole object store.
        """
        root = record.storage.root
        if not root.is_dir():
            return {}
        found: dict[str, tuple[int, int]] = {}
        stack = [root]
        while stack:
            for entry in stack.pop().iterdir():
                if entry.name == ".git":
                    continue
                if entry.is_dir():
                    stack.append(entry)
                elif entry.is_file():
                    stat = entry.stat()
                    found[str(entry.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
        return found

    def _remember_disk(self, record: _ProjectRecord) -> None:
        record.disk = self._snapshot(record)

    def _note_written(self, record: _ProjectRecord, path: str) -> None:
        """Record one file this store just wrote or removed, without rescanning the tree."""
        full = record.storage.root / path
        if full.is_file():
            stat = full.stat()
            record.disk[path] = (stat.st_size, stat.st_mtime_ns)
        else:
            record.disk.pop(path, None)

    def _stat_library(self) -> tuple[int, int] | None:
        try:
            stat = self.library_path.stat()
        except OSError:
            return None
        return (stat.st_size, stat.st_mtime_ns)

    def _remember_library_stamp(self) -> None:
        self._library_stamp = self._stat_library()

    # -- writing -------------------------------------------------------------------------------

    def flush(self, marks: set[DirtyMark]) -> None:
        """Write exactly what ``marks`` names, partitioned by the project that owns it.

        Every project about to be written — and the library file, when membership changed —
        is checked for outside edits *before anything is written*, so a refused flush
        leaves the disk exactly as it was. A mark on the library root's structure means
        the membership changed and rewrites the library file; everything else belongs to
        one project and is written through that project's provider.
        """
        library = self.library
        if library is None:
            return
        rewrite_library = False
        per_project: dict[ProjectId, set[DirtyMark]] = {}
        for node_id, aspect in marks:
            if node_id == library.id:
                rewrite_library = rewrite_library or aspect == "structure"
                continue
            if not library.has(node_id):
                continue  # A mark for a node removed later in the same batch.
            node = library.node(node_id)
            project = node if isinstance(node, Project) else library.project_of(node_id)
            if project.id in self._records:
                per_project.setdefault(project.id, set()).add((node_id, aspect))

        if rewrite_library and self._stat_library() != self._library_stamp:
            raise StaleWorkspaceError(
                "the project library changed on disk since it was opened — "
                "reload before writing, or the other writer's work is lost"
            )
        for project_id in per_project:
            record = self._records[project_id]
            if self._snapshot(record) != record.disk:
                title = library.project(project_id).title or record.directory.name
                raise StaleWorkspaceError(
                    f"{title} ({record.directory}) changed on disk since it was opened — "
                    "reload before writing, or the other writer's work is lost"
                )

        if rewrite_library:
            self._write_library_file()
        for project_id, project_marks in per_project.items():
            self._flush_project(self._records[project_id], project_marks)

    def _write_library_file(self) -> None:
        assert self.library is not None
        # Model order first; entries that failed to open keep their place at the end —
        # a project this build cannot read is still the user's project.
        directories = [
            self._records[project.id].directory
            for project in self.library.projects
            if project.id in self._records
        ]
        write_library_file(self.library_path, directories + self._problem_paths)
        self._remember_library_stamp()

    def _flush_project(self, record: _ProjectRecord, marks: set[DirtyMark]) -> None:
        """One project's share of a flush.

        Structure is done in two passes on purpose. A single pass that synced and cleaned
        one parent at a time could delete a subtree that a pending move has not relocated
        yet — the directories must all exist in their new places before any old one is
        removed.
        """
        library = self.library
        assert library is not None
        structural = [node_id for node_id, aspect in marks if aspect == "structure"]
        for node_id in structural:
            if library.has(node_id):
                for child in _children(library.node(node_id)):
                    self._sync_dir(record, child)
        for node_id in structural:
            if library.has(node_id):
                self._remove_orphans(record, library.node(node_id))
                self._write_meta(record, library.node(node_id))
        for node_id, aspect in marks:
            if aspect == "structure" or not library.has(node_id):
                continue
            node = library.node(node_id)
            if aspect == "meta":
                self._write_meta(record, node)
            elif aspect == "module_text":
                self._write_module_text(record, node)
            elif aspect == "module_data":
                self._write_module_data(record, node)
        self._remember_disk(record)

    def _save_project(self, record: _ProjectRecord, project: Project) -> None:
        """Write one whole project — after a migration, so it is never left half-moved."""
        for node in _walk(project):
            self._write_meta(record, node)
            self._write_module_text(record, node)
            self._write_module_data(record, node)
        self._remember_disk(record)

    def _sync_dir(self, record: _ProjectRecord, node: Node) -> None:
        """Make the directory match where the model says this node lives.

        Three cases, and they are deliberately the same operation from outside: a node that
        was renamed into a fresh folder is moved, one that is new gets its subtree written,
        and one that was deleted and then undone is also "new" — its old directory is gone,
        so it is written again from memory. That last case is why this checks the disk
        rather than trusting ``dirs``: the recorded path can be right and the directory
        still not be there.
        """
        assert self.library is not None
        parent = self.library.parent_of(node.id)
        assert parent is not None
        container = _join(record.dirs[parent.id], CONTAINER[parent.kind])
        if not node.folder_name:
            node.folder_name = unique_folder_name(
                node.title_for_folder(), set(record.storage.list_dir(container))
            )
        target = _join(container, node.folder_name)
        current = record.dirs.get(node.id)

        if current is not None and current != target and record.storage.exists(current):
            (record.storage.root / target).parent.mkdir(parents=True, exist_ok=True)
            (record.storage.root / current).rename(record.storage.root / target)
            self._rebase(record, node, target)
            return

        self._rebase(record, node, target)
        if not record.storage.exists(_join(target, META_FILE[node.kind])):
            self._write_subtree(record, node)

    def _write_subtree(self, record: _ProjectRecord, node: Node) -> None:
        """Write a node and everything under it — for one that is not on disk at all."""
        for descendant in _walk(node):
            record.storage.make_dir(record.dirs[descendant.id])
            self._write_meta(record, descendant)
            self._write_module_text(record, descendant)
            self._write_module_data(record, descendant)

    def _rebase(self, record: _ProjectRecord, node: Node, new: str) -> None:
        record.dirs[node.id] = new
        for child in _children(node):
            self._rebase(record, child, _join(new, CONTAINER[node.kind], child.folder_name))

    def _remove_orphans(self, record: _ProjectRecord, parent: Node) -> None:
        """Delete directories under ``parent`` that no longer belong to any child."""
        container = _join(record.dirs[parent.id], CONTAINER[parent.kind])
        keep = {child.folder_name for child in _children(parent)}
        for name in record.storage.list_dir(container):
            path = _join(container, name)
            if name in keep or not record.storage.is_dir(path):
                continue
            if record.storage.exists(_join(path, STEP_META)):
                shutil.rmtree(record.storage.root / path, ignore_errors=True)
        record.storage.delete(container)  # Removes it only when it is empty.

    def _write_meta(self, record: _ProjectRecord, node: Node) -> None:
        directory = record.dirs[node.id]
        # Absence encodes the default: an untouched field is not written, so a diff shows
        # exactly the nodes whose plan actually changed.
        meta: dict[str, Any] = {"id": node.id, "created": node.created}
        if isinstance(node, Project):
            if node.title:
                meta["title"] = node.title
            if node.summary:
                meta["summary"] = node.summary
            # The format stamp is per project: each directory migrates on its own.
            meta[FORMAT_KEY] = FORMAT.current_version
        elif isinstance(node, Step):
            if node.title:
                meta["title"] = node.title
            if node.edges:
                meta["edges"] = {kind: list(t) for kind, t in sorted(node.edges.items()) if t}
        children = _children(node)
        if children:
            meta["children"] = [child.folder_name for child in children]
        _write_json(record.storage, _join(directory, META_FILE[node.kind]), meta)

    def _write_module_text(self, record: _ProjectRecord, node: Node) -> None:
        directory = _join(record.dirs[node.id], MODULES_DIR)
        wanted = {f"{module_id}.md" for module_id, body in node.module_text.items() if body}
        for name in record.storage.list_dir(directory):
            if name.endswith(".md") and name not in wanted:
                record.storage.delete(_join(directory, name))
        for module_id, body in node.module_text.items():
            if body:
                record.storage.write_text(_join(directory, f"{module_id}.md"), body)
        record.storage.delete(directory)  # Removes it only when it is empty.

    def _write_module_data(self, record: _ProjectRecord, node: Node) -> None:
        directory = _join(record.dirs[node.id], MODULES_DIR)
        wanted = {f"{module_id}.json" for module_id in node.module_data}
        for name in record.storage.list_dir(directory):
            if name.endswith(".json") and name not in wanted:
                record.storage.delete(_join(directory, name))
        for module_id, data in node.module_data.items():
            _write_json(record.storage, _join(directory, f"{module_id}.json"), data)
        record.storage.delete(directory)  # Removes it only when it is empty.


def _read_json(storage: StorageProvider, path: str) -> dict[str, Any]:
    raw = storage.read_text(path)
    if raw is None:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json(storage: StorageProvider, path: str, data: dict[str, Any]) -> None:
    storage.write_text(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _children(node: Node) -> list[Node]:
    if isinstance(node, Library):
        return list(node.projects)
    if isinstance(node, Project):
        return list(node.steps)
    return []


def _walk(node: Node) -> Iterable[Node]:
    yield node
    for child in _children(node):
        yield from _walk(child)


def _read_edges(raw: object) -> dict[str, list[str]]:
    """Edges as stored: a list of step ids per kind, unknown kinds included.

    Anything unreadable becomes no edge rather than a guess — but a *kind* this build does
    not know is kept, because refusing it would silently drop a colleague's link.
    """
    if not isinstance(raw, dict):
        return {}
    edges: dict[str, list[str]] = {}
    for kind, targets in raw.items():
        if isinstance(kind, str) and isinstance(targets, list):
            wanted = [target for target in targets if isinstance(target, str)]
            if wanted:
                edges[kind] = wanted
    return edges


def _join(*parts: str) -> str:
    return "/".join(part for part in parts if part)


__all__ = [
    "LibraryStore",
    "ModuleFileArea",
    "ProjectProblem",
    "StaleWorkspaceError",
    "UnsupportedFormatError",
]
