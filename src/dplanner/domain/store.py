"""The product on disk: one directory per node, nested exactly like the model.

This is the file that decides what a product *looks like* on disk, and its conventions are
what make a file-backed format survive being shared through version control:

**Ordering lives in the parent's list**, never in ``01-``/``02-`` filename prefixes.
Reordering two projects is a one-line JSON diff instead of a mass rename.

**A folder name is frozen at creation** and never follows a retitle. Editing a title
changes one JSON value; it does not move a directory and rewrite its history.

**Absence encodes the default.** An optional key is written only when it is not the
default, and an empty document is deleted rather than written blank — so a diff shows
exactly what actually changed, and an untouched node is visibly untouched.

**Container directories say what a level is.** ``projects/`` and ``steps/`` cost one
directory each and buy a reader the shape of the model at a glance — and, because children
never sit beside ``modules/``, there are no reserved folder names to trip over::

    <workspace>/
    ├── product.json
    ├── modules/
    └── projects/<slug>/
        ├── project.json
        ├── modules/
        └── steps/<slug>/
            ├── step.json
            └── modules/
                ├── estimation.json          structured data
                ├── step_description.md      prose
                └── step_description/        files this module owns

One naming rule covers all three: **``modules/<id>.json`` is a module's data,
``modules/<id>.md`` is its prose, and ``modules/<id>/`` is its files.** Every one of them is
round-tripped by name, so data belonging to a module this build does not have survives
untouched.

**Two writers, one folder.** DPlanner is meant to be driven by an agent while a window is
open on the same product, so "memory is authoritative and disk follows" is not the whole
story: a flush that rewrote a node from a model which never saw the agent's edit would erase
it silently, and ``_remove_orphans`` would delete a directory the agent had just created. So
the store remembers what the workspace looked like when it last read or wrote it, and
refuses to flush over anything that changed underneath — see :meth:`changed_underneath` and
:class:`StaleWorkspaceError`. That one check covers both directions: a second CLI run is
refused for the same reason and needs no lock of its own.

The store is passive: it serialises, it does not notify. Change notification lives on the
aggregate, where the change happened. What it implements for the framework is
:class:`~dplanner.core.repository.Persister` — one ``flush(marks)`` that writes exactly the
aspects that are dirty, in the order this format requires.
"""

import json
import shutil
from collections.abc import Callable, Iterable
from typing import Any

from dplanner.core.formats import FORMAT_KEY, UnsupportedFormatError
from dplanner.core.repository import DataOwner, DirtyMark
from dplanner.core.signals import Signal
from dplanner.core.storage.provider import StorageProvider
from dplanner.domain.migrations import FORMAT
from dplanner.domain.model import Node, NodeId, Product, Project, Step, unique_folder_name

PRODUCT_META = "product.json"
PROJECT_META = "project.json"
STEP_META = "step.json"
MODULES_DIR = "modules"
PROJECTS_DIR = "projects"
STEPS_DIR = "steps"

# Which container directory holds a node's children, and what a child's meta file is called.
CONTAINER = {"product": PROJECTS_DIR, "project": STEPS_DIR}
META_FILE = {"product": PRODUCT_META, "project": PROJECT_META, "step": STEP_META}


class StaleWorkspaceError(RuntimeError):
    """The workspace changed on disk since this store last read or wrote it.

    Not an error in the data and not a bug: somebody else — the CLI, an agent, a branch
    switch, a colleague's merge — wrote to the same folder. Whoever catches this decides
    what to do about it, and the only safe options are to reload or to be told.
    """


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
        # here reaches the store's record of what the workspace looks like.
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

    def write_bytes(self, name: str, data: bytes) -> None:
        self._storage.write_bytes(_join(self.directory, name), data)
        self._noted(_join(self.directory, name))

    def remove(self, name: str) -> None:
        """Delete one file, and any directory it leaves empty up to the area itself.

        "Writing nothing leaves nothing behind" is the same rule the JSON entries follow:
        an empty directory is invisible in a diff but not in a file browser, and a workspace
        that accumulates them stops looking like the plan it holds.
        """
        self._storage.delete(_join(self.directory, name))
        self._noted(_join(self.directory, name))
        parts = [part for part in name.split("/")[:-1] if part]
        while parts:
            self._storage.delete(_join(self.directory, *parts))  # Only when it is empty.
            parts.pop()
        self._storage.delete(self.directory)


class ProductStore:
    """Loads and saves one :class:`Product` through a storage provider.

    Note what it takes: a :class:`~dplanner.core.storage.provider.StorageProvider`, not a
    path. Everything below goes through that interface, which is why the same store works
    against a plain folder, a git checkout and a GitHub clone without knowing which it has.
    """

    def __init__(self, storage: StorageProvider) -> None:
        self.storage = storage
        self.product: Product | None = None
        # Node id → its directory, workspace-relative. This one dict is what makes reorder,
        # rename and undo-of-delete all the same operation from outside: the model says
        # where a node *should* live, this says where it *does*.
        self._dirs: dict[NodeId, str] = {}
        # What the workspace looked like the last time this store read or wrote it. Size and
        # modification time per file, which is what every build tool uses to answer the same
        # question, and cheap enough to recompute on each 1.5-second autosave.
        self._disk: dict[str, tuple[int, int]] = {}
        self.dirty: Signal[str, str] = Signal()

    # -- opening -------------------------------------------------------------------------------

    def exists(self) -> bool:
        return self.storage.exists(PRODUCT_META)

    def load(self) -> Product:
        """Read the workspace, running any pending format migrations, then save it back.

        The save at the end is not optional: a migration that ran but was never persisted
        would run again on the next open, against data a later autosave may already have
        partly rewritten. Migrate once, write once.
        """
        raw = self._read_json(PRODUCT_META)
        found = FORMAT.read_version(raw, self.storage.root / PRODUCT_META)
        pending = FORMAT.pending(found)

        product = Product(
            node_id=str(raw.get("id", "")) or None,
            name=str(raw.get("name", "")),
            repository=str(raw.get("repository", "")),
            checkout=str(raw.get("checkout", "")),
            created=str(raw.get("created", "")),
        )
        self._load_node_files(product, "", raw, pending)
        for folder in self._child_folders(raw, "", "product"):
            product.projects.append(self._load_project(_join(PROJECTS_DIR, folder), pending))
        product.reindex()
        for migration in pending:
            if migration.whole is not None:
                migration.whole(product)
        self._adopt(product)
        if pending:
            self.save_all(product)
        else:
            self._remember_disk()
        return product

    def _load_project(self, directory: str, pending: tuple[Any, ...]) -> Project:
        raw = self._read_json(_join(directory, PROJECT_META))
        project = Project(
            node_id=str(raw.get("id", "")) or None,
            title=str(raw.get("title", "")),
            summary=str(raw.get("summary", "")),
            folder_name=directory.rsplit("/", 1)[-1],
            created=str(raw.get("created", "")),
        )
        self._load_node_files(project, directory, raw, pending)
        for folder in self._child_folders(raw, directory, "project"):
            project.steps.append(self._load_step(_join(directory, STEPS_DIR, folder), pending))
        return project

    def _load_step(self, directory: str, pending: tuple[Any, ...]) -> Step:
        raw = self._read_json(_join(directory, STEP_META))
        step = Step(
            node_id=str(raw.get("id", "")) or None,
            title=str(raw.get("title", "")),
            # Tolerant on every field: a hand-edited product, or one written by a newer
            # build, must open rather than crash. Edge kinds this build does not know are
            # kept exactly as found, so a colleague's newer link survives a round trip here.
            edges=_read_edges(raw.get("edges")),
            folder_name=directory.rsplit("/", 1)[-1],
            created=str(raw.get("created", "")),
        )
        self._load_node_files(step, directory, raw, pending)
        return step

    def _load_node_files(
        self, node: Node, directory: str, raw: dict[str, Any], pending: tuple[Any, ...]
    ) -> None:
        for migration in pending:
            if migration.node is not None:
                migration.node(node, raw, self.storage.root / directory)
        node.module_data, node.module_text = self._load_module_files(directory)
        self._dirs[node.id] = directory

    def _child_folders(self, raw: dict[str, Any], directory: str, kind: str) -> list[str]:
        """The child folders of ``directory``, in the order the parent recorded.

        Directories holding a child's meta file but missing from the list are appended
        rather than ignored: a folder someone created by hand, or that a merge resurrected,
        is data.
        """
        container = _join(directory, CONTAINER[kind])
        child_meta = META_FILE["project" if kind == "product" else "step"]
        listed = [name for name in raw.get("children", []) if isinstance(name, str)]
        present = [
            name
            for name in self.storage.list_dir(container)
            if self.storage.exists(_join(container, name, child_meta))
        ]
        ordered = [name for name in listed if name in present]
        return ordered + [name for name in present if name not in listed]

    def _load_module_files(self, directory: str) -> tuple[dict[str, Any], dict[str, str]]:
        """Every ``modules/<id>.json`` and ``modules/<id>.md``, by filename.

        Entries this build knows nothing about are loaded and saved back untouched, so a
        workspace shared with a newer build never loses that build's data.
        """
        data: dict[str, dict[str, Any]] = {}
        text: dict[str, str] = {}
        for name in self.storage.list_dir(_join(directory, MODULES_DIR)):
            path = _join(directory, MODULES_DIR, name)
            if name.endswith(".json"):
                entry = self._read_json(path)
                if entry:
                    data[name.removesuffix(".json")] = entry
            elif name.endswith(".md"):
                document = self.storage.read_text(path)
                if document:
                    text[name.removesuffix(".md")] = document
        return data, text

    def _read_json(self, path: str) -> dict[str, Any]:
        raw = self.storage.read_text(path)
        if raw is None:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write_json(self, path: str, data: dict[str, Any]) -> None:
        self.storage.write_text(
            path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )

    def _adopt(self, product: Product) -> None:
        """Hold this product and forward its dirty marks — one place, so create() and
        load() cannot disagree about it."""
        self.product = product
        product.dirty.connect(self.dirty.emit)

    # -- the Repository face the framework uses ------------------------------------------------

    def owners(self) -> Iterable[DataOwner]:
        return [] if self.product is None else list(self.product.nodes())

    def owner(self, owner_id: str) -> DataOwner | None:
        if self.product is None or not self.product.has(owner_id):
            return None
        return self.product.node(owner_id)

    def set_module_data(self, owner_id: str, module_id: str, data: dict[str, Any]) -> None:
        assert self.product is not None
        self.product.set_module_data(owner_id, module_id, data)

    def files(self, node_id: NodeId, module_id: str) -> ModuleFileArea:
        """The directory ``module_id`` owns beside ``node_id``'s module data."""
        directory = _join(self._dirs[node_id], MODULES_DIR, module_id)
        return ModuleFileArea(self.storage, directory, self._note_written)

    def close(self) -> None:
        self.product = None

    # -- noticing another writer ---------------------------------------------------------------

    def changed_underneath(self) -> bool:
        """Whether anything in the workspace differs from what this store last saw."""
        return self._snapshot() != self._disk

    def _snapshot(self) -> dict[str, tuple[int, int]]:
        root = self.storage.root
        if not root.is_dir():
            return {}
        found: dict[str, tuple[int, int]] = {}
        for path in root.rglob("*"):
            if path.is_file():
                stat = path.stat()
                found[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
        return found

    def _remember_disk(self) -> None:
        self._disk = self._snapshot()

    def _note_written(self, path: str) -> None:
        """Record one file this store just wrote or removed, without rescanning the tree."""
        full = self.storage.root / path
        if full.is_file():
            stat = full.stat()
            self._disk[str(full.relative_to(self.storage.root))] = (stat.st_size, stat.st_mtime_ns)
        else:
            self._disk.pop(path, None)

    # -- writing -------------------------------------------------------------------------------

    def flush(self, marks: set[DirtyMark]) -> None:
        """Write exactly what ``marks`` names.

        Structure is done in two passes on purpose. A single pass that synced and cleaned
        one parent at a time could delete a subtree that a pending move has not relocated
        yet — the directories must all exist in their new places before any old one is
        removed.

        Both passes go **parent first**. ``marks`` is a set, so its order is arbitrary, and
        one flush routinely carries a new project and the steps added inside it: syncing the
        steps first would look for a directory the project has not been given yet.
        """
        product = self.product
        if product is None:
            return
        if self.changed_underneath():
            raise StaleWorkspaceError(
                f"{self.storage.label} changed on disk since it was opened — "
                "reload before writing, or the other writer's work is lost"
            )
        depth = {node.id: index for index, node in enumerate(product.nodes())}
        structural = sorted(
            (node_id for node_id, aspect in marks if aspect == "structure"),
            key=lambda node_id: depth.get(node_id, -1),
        )
        for node_id in structural:
            if product.has(node_id):
                for child in _children(product.node(node_id)):
                    self._sync_dir(product, child)
        for node_id in structural:
            if product.has(node_id):
                self._remove_orphans(product.node(node_id))
                self._write_meta(product.node(node_id))
        for node_id, aspect in marks:
            if aspect == "structure" or not product.has(node_id):
                continue
            node = product.node(node_id)
            if aspect == "meta":
                self._write_meta(node)
            elif aspect == "module_text":
                self._write_module_text(node)
            elif aspect == "module_data":
                self._write_module_data(node)
        self._remember_disk()

    def create(self, product: Product) -> None:
        """Write a brand-new workspace. The product sits at the workspace root itself."""
        self._dirs[product.id] = ""
        self._adopt(product)
        self.save_all(product)

    def save_all(self, product: Product) -> None:
        """Write the whole workspace. Used after a migration and when creating one."""
        for node in product.nodes():
            if node is not product:
                self._sync_dir(product, node)
        for node in product.nodes():
            self._write_meta(node)
            self._write_module_text(node)
            self._write_module_data(node)
        self._remember_disk()

    def _sync_dir(self, product: Product, node: Node) -> None:
        """Make the directory match where the model says this node lives.

        Three cases, and they are deliberately the same operation from outside: a node that
        was renamed into a fresh folder is moved, one that is new gets its subtree written,
        and one that was deleted and then undone is also "new" — its old directory is gone,
        so it is written again from memory. That last case is why this checks the disk
        rather than trusting ``_dirs``: the recorded path can be right and the directory
        still not be there.
        """
        parent = product.parent_of(node.id)
        assert parent is not None
        container = _join(self._dirs[parent.id], CONTAINER[parent.kind])
        if not node.folder_name:
            node.folder_name = unique_folder_name(
                node.title_for_folder(), set(self.storage.list_dir(container))
            )
        target = _join(container, node.folder_name)
        current = self._dirs.get(node.id)

        if current is not None and current != target and self.storage.exists(current):
            (self.storage.root / target).parent.mkdir(parents=True, exist_ok=True)
            (self.storage.root / current).rename(self.storage.root / target)
            self._rebase(node, target)
            return

        self._rebase(node, target)
        if not self.storage.exists(_join(target, META_FILE[node.kind])):
            self._write_subtree(node)

    def _write_subtree(self, node: Node) -> None:
        """Write a node and everything under it — for one that is not on disk at all."""
        for descendant in _walk(node):
            self.storage.make_dir(self._dirs[descendant.id])
            self._write_meta(descendant)
            self._write_module_text(descendant)
            self._write_module_data(descendant)

    def _rebase(self, node: Node, new: str) -> None:
        self._dirs[node.id] = new
        for child in _children(node):
            self._rebase(child, _join(new, CONTAINER[node.kind], child.folder_name))

    def _remove_orphans(self, parent: Node) -> None:
        """Delete directories under ``parent`` that no longer belong to any child."""
        container = _join(self._dirs[parent.id], CONTAINER[parent.kind])
        keep = {child.folder_name for child in _children(parent)}
        child_meta = META_FILE["project" if parent.kind == "product" else "step"]
        for name in self.storage.list_dir(container):
            path = _join(container, name)
            if name in keep or not self.storage.is_dir(path):
                continue
            if self.storage.exists(_join(path, child_meta)):
                shutil.rmtree(self.storage.root / path, ignore_errors=True)
        self.storage.delete(container)  # Removes it only when it is empty.

    def _write_meta(self, node: Node) -> None:
        directory = self._dirs[node.id]
        # Absence encodes the default: an untouched field is not written, so a diff shows
        # exactly the nodes whose plan actually changed.
        meta: dict[str, Any] = {"id": node.id, "created": node.created}
        if isinstance(node, Product):
            if node.name:
                meta["name"] = node.name
            if node.repository:
                meta["repository"] = node.repository
            if node.checkout:
                meta["checkout"] = node.checkout
            meta[FORMAT_KEY] = FORMAT.current_version
        elif isinstance(node, Project):
            if node.title:
                meta["title"] = node.title
            if node.summary:
                meta["summary"] = node.summary
        elif isinstance(node, Step):
            if node.title:
                meta["title"] = node.title
            if node.edges:
                meta["edges"] = {kind: list(t) for kind, t in sorted(node.edges.items()) if t}
        children = _children(node)
        if children:
            meta["children"] = [child.folder_name for child in children]
        self._write_json(_join(directory, META_FILE[node.kind]), meta)

    def _write_module_text(self, node: Node) -> None:
        directory = _join(self._dirs[node.id], MODULES_DIR)
        wanted = {f"{module_id}.md" for module_id, body in node.module_text.items() if body}
        for name in self.storage.list_dir(directory):
            if name.endswith(".md") and name not in wanted:
                self.storage.delete(_join(directory, name))
        for module_id, body in node.module_text.items():
            if body:
                self.storage.write_text(_join(directory, f"{module_id}.md"), body)
        self.storage.delete(directory)  # Removes it only when it is empty.

    def _write_module_data(self, node: Node) -> None:
        directory = _join(self._dirs[node.id], MODULES_DIR)
        wanted = {f"{module_id}.json" for module_id in node.module_data}
        for name in self.storage.list_dir(directory):
            if name.endswith(".json") and name not in wanted:
                self.storage.delete(_join(directory, name))
        for module_id, data in node.module_data.items():
            self._write_json(_join(directory, f"{module_id}.json"), data)
        self.storage.delete(directory)  # Removes it only when it is empty.


def _children(node: Node) -> list[Node]:
    if isinstance(node, Product):
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
    "ModuleFileArea",
    "ProductStore",
    "StaleWorkspaceError",
    "UnsupportedFormatError",
]
