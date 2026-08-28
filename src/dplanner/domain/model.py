"""The model: a library of projects, each a graph of steps.

Three levels, and each is a different kind of thing:

**Library** is the account level — the projects a user is planning, listed in a per-user
library file. It is also the aggregate: the single place a change can happen, which is what
makes "every change emits exactly one signal" true rather than hopeful. It is in-memory
only — the library file records membership, each project directory records the rest, and no
node on disk stands for the library itself. A window holds one library; opening another
starts another instance.

**Project** is a unit of work with a beginning and an end — a directory inside a git
repository. **Step** is a node in that project's graph.

**Identity is the id, never the position.** ``uuid4().hex``, generated at creation and
written into the JSON. A node keeps its identity through renames and reorders — which is
what lets an open tab, a selection, an undo command and *another step's edge* all keep
pointing at the right thing while the plan is rearranged underneath them.

**Every mutator takes an origin.** A view that edits passes itself, then ignores the signal
when ``origin is self`` — its widget already shows the change. Undo passes a token matching
no view, so every view applies it.

**What the graph does not know.** A step's estimate, its ticket, its description: none of
them are fields here. They are :term:`aspects` — a module's entry in ``module_data`` (JSON)
or ``module_text`` (prose), namespaced by module id and versioned by the module that writes
them. The graph can therefore grow features without learning a single thing about them.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from dplanner.core.fsio import slugify
from dplanner.core.repository import Origin
from dplanner.core.signals import Signal

type NodeId = str
type ProjectId = str
type StepId = str

# Edge kind -> whether it orders the graph. An ordering kind cannot contain a cycle; a
# non-ordering one is just a link and may point anywhere inside the project.
#
# This vocabulary is the domain's, not a module's: `domain/` may not import `modules/`, and
# a kind that only some builds understood would make a shared workspace mean different
# things to different people. Adding one is an edit here. Kinds this build does not know
# are still loaded and saved back untouched — see `store.py`.
EDGE_KINDS: Final[dict[str, bool]] = {"requires": True, "relates": False}
DEFAULT_EDGE_KIND: Final = "requires"

# The editable single-value fields of each kind of node. One table rather than three
# mutators, three commands and three signals: they are edited the same way, undone the same
# way, and differ only in what the Edit menu calls them.
VALUE_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "project": ("title", "summary"),
    "step": ("title",),
}

FIELD_LABELS: Final[dict[str, str]] = {
    "title": "Rename",
    "summary": "Edit Summary",
}


def now_stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class TextEdit:
    """One change to one node's prose: whose, which document, and what changed where.

    ``key`` is the id of the module that owns the document. Prose is keyed rather than
    named as a field because a description belongs to the module that gives it meaning, not
    to the graph — and because a positional edit is what lets several open views of the same
    document stay in sync without any of them rebuilding.
    """

    node_id: NodeId
    key: str
    pos: int
    removed: str
    added: str

    def inverted(self) -> "TextEdit":
        return TextEdit(self.node_id, self.key, self.pos, removed=self.added, added=self.removed)


class Node:
    """What a project and a step have in common (the library root is one too, nominally).

    A project and a step can own module data, so both satisfy
    :class:`~dplanner.core.repository.DataOwner` and appear in ``repo.owners()``. The
    library root cannot — it has no directory — and is excluded from :meth:`Library.nodes`.
    """

    kind: str = ""

    def __init__(self, *, node_id: NodeId | None = None, folder_name: str = "", created: str = ""):
        self.id: NodeId = node_id or uuid.uuid4().hex
        # Frozen at creation and never following a retitle: identity is the id, the folder
        # name is presentation, and renaming a folder churns history for no benefit.
        self.folder_name = folder_name
        self.created = created or now_stamp()
        # Structured data a module owns, one entry per module id, opaque to this model.
        self.module_data: dict[str, dict[str, Any]] = {}
        # Prose a module owns, one document per module id. Edited positionally.
        self.module_text: dict[str, str] = {}

    def title_for_folder(self) -> str:
        raise NotImplementedError


class Step(Node):
    """A node in a project's graph. Dumb data — mutate through :class:`Library`."""

    kind = "step"

    def __init__(
        self,
        *,
        node_id: NodeId | None = None,
        title: str = "",
        edges: dict[str, list[StepId]] | None = None,
        folder_name: str = "",
        created: str = "",
    ) -> None:
        super().__init__(node_id=node_id, folder_name=folder_name, created=created)
        self.title = title
        # Incoming edges, keyed by kind: `edges["requires"]` is what this step waits on.
        # They live on the step that waits, so a step is self-contained — remove it and its
        # edges go with it — and so the direction cannot be read the wrong way round.
        self.edges: dict[str, list[StepId]] = {
            kind: list(targets) for kind, targets in (edges or {}).items() if targets
        }

    def __repr__(self) -> str:
        return f"Step({self.title!r}, id={self.id[:8]})"

    def title_for_folder(self) -> str:
        return self.title


class Project(Node):
    """A unit of work: a title, a summary, and the graph of steps that delivers it."""

    kind = "project"

    def __init__(
        self,
        *,
        node_id: NodeId | None = None,
        title: str = "",
        summary: str = "",
        folder_name: str = "",
        created: str = "",
    ) -> None:
        super().__init__(node_id=node_id, folder_name=folder_name, created=created)
        self.title = title
        self.summary = summary
        self.steps: list[Step] = []

    def __repr__(self) -> str:
        return f"Project({self.title!r}, {len(self.steps)} steps, id={self.id[:8]})"

    def title_for_folder(self) -> str:
        return self.title

    def step(self, step_id: StepId) -> Step | None:
        return next((step for step in self.steps if step.id == step_id), None)


class Library(Node):
    """The aggregate: the open library's projects, and every way to change any of them.

    Not persisted as a node: the library file lists project directories, each project
    directory holds its own data, and this object exists only to be the one place a change
    can happen — the flat index and the signals live here.
    """

    kind = "library"

    def __init__(self, *, node_id: NodeId | None = None) -> None:
        super().__init__(node_id=node_id)
        self.projects: list[Project] = []

        # One flat index across all three kinds, because the framework's repository face
        # (`owner(id)`, `set_module_data(id, ...)`) is flat over ids and does not know this
        # model has levels. Ids are unique across kinds by construction — they are uuids.
        self._nodes: dict[NodeId, Node] = {self.id: self}
        self._parent: dict[NodeId, NodeId] = {}

        # One signal per kind of change, each carrying the origin that caused it.
        self.field_changed: Signal[NodeId, str, Origin] = Signal()
        self.text_edited: Signal[TextEdit, Origin] = Signal()
        self.edges_changed: Signal[StepId, Origin] = Signal()
        # The changed parent's id, and who changed it. Every signal here carries an origin,
        # with no exception: a view that adds a node is as entitled to recognise its own echo
        # as one that renames it, and a convention with one hole is one nobody can rely on.
        self.structure_changed: Signal[NodeId, Origin] = Signal()
        self.module_data_changed: Signal[NodeId, str, Origin] = Signal()
        # (owner id, aspect) — the framework's autosave debounces this.
        self.dirty: Signal[str, str] = Signal()

    def __repr__(self) -> str:
        return f"Library({len(self.projects)} projects)"

    # -- lookup --------------------------------------------------------------------------------

    def reindex(self) -> None:
        self._nodes = {self.id: self}
        self._parent = {}
        for project in self.projects:
            self._nodes[project.id] = project
            self._parent[project.id] = self.id
            for step in project.steps:
                self._nodes[step.id] = step
                self._parent[step.id] = project.id

    def has(self, node_id: NodeId) -> bool:
        return node_id in self._nodes

    def node(self, node_id: NodeId) -> Node:
        return self._nodes[node_id]

    def nodes(self) -> Iterator[Node]:
        """Every project, then its steps — parents before children.

        The library root is deliberately absent: it has no directory and can carry no
        module data, so nothing downstream (the migration pass, the flush) should see it.
        """
        for project in self.projects:
            yield project
            yield from project.steps

    def project(self, project_id: ProjectId) -> Project:
        node = self._nodes[project_id]
        if not isinstance(node, Project):
            raise KeyError(f"{project_id} is not a project")
        return node

    def step(self, step_id: StepId) -> Step:
        node = self._nodes[step_id]
        if not isinstance(node, Step):
            raise KeyError(f"{step_id} is not a step")
        return node

    def parent_of(self, node_id: NodeId) -> Node | None:
        parent_id = self._parent.get(node_id)
        return None if parent_id is None else self._nodes[parent_id]

    def project_of(self, step_id: StepId) -> Project:
        """The project a step belongs to. Edges never cross one, so this always answers."""
        parent = self.parent_of(step_id)
        if not isinstance(parent, Project):
            raise KeyError(f"{step_id} is not a step in this library")
        return parent

    # -- fields --------------------------------------------------------------------------------

    def set_field(self, node_id: NodeId, field: str, value: object, origin: Origin = None) -> None:
        """Set one of :data:`VALUE_FIELDS` on any node.

        One mutator rather than six, because the commands, the panels and the undo labels
        all treat them identically — only the label differs, and that is a lookup.
        """
        node = self._nodes[node_id]
        if field not in VALUE_FIELDS[node.kind]:
            raise ValueError(f"{field!r} is not an editable field of a {node.kind}")
        if getattr(node, field) == value:
            return
        setattr(node, field, value)
        self.dirty.emit(node_id, "meta")
        self.field_changed.emit(node_id, field, origin)

    # -- prose ---------------------------------------------------------------------------------

    def text(self, node_id: NodeId, key: str) -> str:
        return self._nodes[node_id].module_text.get(key, "")

    def apply_text_edit(self, edit: TextEdit, origin: Origin = None) -> None:
        """Apply a positioned edit to one module's prose, refusing one that does not match.

        The check is not defensive noise: a binding whose view has drifted out of sync would
        otherwise write plausible nonsense that no later read could detect.
        """
        node = self._nodes[edit.node_id]
        current = node.module_text.get(edit.key, "")
        actual = current[edit.pos : edit.pos + len(edit.removed)]
        if actual != edit.removed:
            raise ValueError(
                f"stale TextEdit for {edit.node_id}/{edit.key}: expected {edit.removed!r} "
                f"at {edit.pos}, found {actual!r}"
            )
        updated = current[: edit.pos] + edit.added + current[edit.pos + len(edit.removed) :]
        if updated:
            node.module_text[edit.key] = updated
        else:
            node.module_text.pop(edit.key, None)
        self.dirty.emit(edit.node_id, "module_text")
        self.text_edited.emit(edit, origin)

    def set_text(self, node_id: NodeId, key: str, text: str, origin: Origin = None) -> None:
        """Replace one document wholesale, reported as one positioned edit over the old."""
        current = self.text(node_id, key)
        if current == text:
            return
        self.apply_text_edit(TextEdit(node_id, key, 0, current, text), origin)

    # -- edges ---------------------------------------------------------------------------------

    def link_refusal(self, step_id: StepId, kind: str, target: StepId) -> str | None:
        """Why ``step_id`` cannot wait on ``target``, or None when it can.

        Four refusals, and each is a graph that would otherwise be quietly unsatisfiable: an
        unknown kind, a step pointing at itself, a target that does not exist or lives in
        another project, and — for an ordering kind — a chain that leads back here.

        This is a question as well as an answer. :meth:`set_edges` asks it before it writes,
        and a view dragging a link asks it under the cursor so it can refuse *before* the
        drop rather than with a dialog afterwards. One implementation, so the live feedback
        and the write can never disagree about what is legal.
        """
        if kind not in EDGE_KINDS:
            return f"{kind!r} is not an edge kind: {', '.join(sorted(EDGE_KINDS))}"
        if target == step_id:
            return "a step cannot depend on itself"
        project = self.project_of(step_id)
        if project.step(target) is None:
            return f"no such step in {project.title!r}: {target}"
        if EDGE_KINDS[kind] and self._reaches(target, step_id, kind):
            return f"{self.step(target).title!r} already waits on this step — that is a cycle"
        return None

    def set_edges(
        self, step_id: StepId, kind: str, targets: list[StepId], origin: Origin = None
    ) -> None:
        """Replace one kind of incoming edge, refusing anything that cannot be true.

        The refusals are :meth:`link_refusal`'s; catching them at the model means everything
        above it never has to.
        """
        if kind not in EDGE_KINDS:
            # Checked here as well as in link_refusal: clearing an unknown kind passes no
            # targets, so the loop below would never look at it.
            raise ValueError(f"{kind!r} is not an edge kind: {', '.join(sorted(EDGE_KINDS))}")
        step = self.step(step_id)
        wanted = list(dict.fromkeys(targets))  # De-duplicate, keep the given order.
        for target in wanted:
            refusal = self.link_refusal(step_id, kind, target)
            if refusal is not None:
                raise ValueError(refusal)
        if step.edges.get(kind, []) == wanted:
            return
        if wanted:
            step.edges[kind] = wanted
        else:
            step.edges.pop(kind, None)
        self.dirty.emit(step_id, "meta")
        self.edges_changed.emit(step_id, origin)

    def _reaches(self, start: StepId, target: StepId, kind: str) -> bool:
        """Whether ``start`` waits, directly or through others, on ``target``."""
        seen: set[StepId] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in seen or current not in self._nodes:
                continue
            seen.add(current)
            node = self._nodes[current]
            if isinstance(node, Step):
                stack.extend(node.edges.get(kind, []))
        return False

    def requires(self, step_id: StepId) -> list[Step]:
        """The steps this one waits on. Ids that no longer resolve are skipped."""
        step = self.step(step_id)
        found: list[Step] = []
        for target in step.edges.get("requires", []):
            node = self._nodes.get(target)
            if isinstance(node, Step):
                found.append(node)
        return found

    def dependents(self, step_id: StepId) -> list[Step]:
        """The steps in the same project that wait on this one."""
        project = self.project_of(step_id)
        return [step for step in project.steps if step_id in step.edges.get("requires", [])]

    # -- structure -----------------------------------------------------------------------------

    def add_child(
        self, parent_id: NodeId, child: Node, index: int | None = None, origin: Origin = None
    ) -> NodeId:
        """Add a project to the library, or a step to a project."""
        children = self._children_of(parent_id, type(child))
        if not child.folder_name:
            child.folder_name = unique_folder_name(
                child.title_for_folder(), {sibling.folder_name for sibling in children}
            )
        children.insert(len(children) if index is None else index, child)
        self.reindex()
        self.dirty.emit(parent_id, "structure")
        self.structure_changed.emit(parent_id, origin)
        return child.id

    def remove_child(self, node_id: NodeId, origin: Origin = None) -> tuple[NodeId, int]:
        """Detach a project or a step; returns where it was, so undo can put it back.

        Edges pointing at a removed step are left alone on purpose. Undo has to restore the
        graph exactly, and silently rewriting other steps' edge lists would make
        delete-then-undo lossy. :meth:`requires` already skips ids it cannot resolve.
        """
        node = self._nodes[node_id]
        parent = self.parent_of(node_id)
        if parent is None:
            raise ValueError("the library itself cannot be removed")
        children = self._children_of(parent.id, type(node))
        index = children.index(node)
        children.remove(node)
        self.reindex()
        self.dirty.emit(parent.id, "structure")
        self.structure_changed.emit(parent.id, origin)
        return parent.id, index

    def restore_child(
        self, parent_id: NodeId, child: Node, index: int, origin: Origin = None
    ) -> None:
        """Put a removed project or step back exactly where it was."""
        self.add_child(parent_id, child, index, origin)

    def _children_of(self, parent_id: NodeId, child_type: type) -> list[Any]:
        parent = self._nodes[parent_id]
        if isinstance(parent, Library) and child_type is Project:
            return parent.projects
        if isinstance(parent, Project) and child_type is Step:
            return parent.steps
        raise ValueError(f"a {parent.kind} does not hold a {child_type.__name__.lower()}")

    # -- module data ---------------------------------------------------------------------------

    def set_module_data(
        self, node_id: NodeId, module_id: str, data: dict[str, Any], origin: Origin = None
    ) -> None:
        """Replace one module's entry. An empty dict removes it, and the file with it.

        Takes an ``origin`` like every other mutator here. An aspect editor is a view of this
        data, so without one it would hear the echo of its own write and reload the field the
        user is still typing in.
        """
        node = self._nodes[node_id]
        if data:
            node.module_data[module_id] = data
        else:
            node.module_data.pop(module_id, None)
        self.dirty.emit(node_id, "module_data")
        self.module_data_changed.emit(node_id, module_id, origin)


def unique_folder_name(title: str, taken: set[str]) -> str:
    """A slug for ``title`` that no sibling is using."""
    base = slugify(title, fallback="untitled")
    if base not in taken:
        return base
    for suffix in range(2, 1000):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:6]}"
