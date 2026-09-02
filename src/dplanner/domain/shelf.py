"""The shelf: where an aspect's data goes when the aspect is turned off.

Turning an aspect off used to delete what it held, after asking. That made every toggle a
small act of courage and every confirm dialog a line of chrome, and it was the wrong trade:
somebody switching a step from *milestone* to *feature* and back wants the label they had.
So the aspect's entry and its prose move to a per-node **shelf** —
``modules/shelf.json`` beside the step — and come back when it is turned on again.

The shelf is deliberately a *domain* concern and not a flag inside each module's entry.
With the entry genuinely absent (or, for the two aspects whose default is on, replaced by
their opt-out marker), every reader — a briefing, a lint, the canvas — already treats the
aspect as off; not one ``read()`` learns a new key. Absence still encodes the default; the
shelf only remembers what absence replaced. ``FORMAT.md`` has the on-disk rule.

Two builders are the whole vocabulary: :func:`turn_off` shelves and :func:`turn_on`
restores — or writes a fresh entry when nothing was shelved — and both surfaces use them.
A GUI toggle pushes the command; a CLI ``clear`` applies it.
"""

from collections.abc import Sequence
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, migrated, stamped
from dplanner.core.repository import Repository
from dplanner.domain.commands import UNDO_ORIGIN, Command, SetModuleDataCommand
from dplanner.domain.model import Library, Node, NodeId

SHELF_ID = "shelf"
DATA_FORMAT = ModuleDataFormat(SHELF_ID, 1)

ASPECTS_KEY = "aspects"


def _entries(node: Node) -> dict[str, dict[str, Any]]:
    """The shelf's entries, by module id — a copy, since a command rewrites the whole."""
    shelf = node.module_data.get(SHELF_ID, {})
    aspects = shelf.get(ASPECTS_KEY, {})
    return {module_id: dict(entry) for module_id, entry in aspects.items()}


def _shelf(entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The shelf entry for these entries — ``{}`` when empty, so the file goes with it."""
    return stamped({ASPECTS_KEY: entries}, DATA_FORMAT.version) if entries else {}


def shelved(node: Node, module_id: str) -> tuple[dict[str, Any], str] | None:
    """What the shelf holds for a module: ``(data, text)``, or None when nothing."""
    entry = _entries(node).get(module_id)
    if entry is None:
        return None
    return dict(entry.get("data", {})), str(entry.get("text", ""))


def shelved_text(node: Node, module_id: str) -> str:
    kept = shelved(node, module_id)
    return kept[1] if kept is not None else ""


class ShelveCommand:
    """Turn an aspect off, keeping what it held.

    The entry and the prose move to the shelf, ``leaving`` takes the entry's place — ``{}``
    for a marker aspect, the opt-out marker for one whose default is on — and the prose is
    emptied. Nothing is shelved for an aspect that held nothing, so a bare marker toggled
    off leaves no shelf behind. One command, so one undo restores all three stores.
    """

    def __init__(
        self,
        node_id: NodeId,
        module_id: str,
        leaving: dict[str, Any],
        view_origin: object | None = None,
        label: str = "",
    ) -> None:
        self.node_id = node_id
        self.module_id = module_id
        self.leaving = dict(leaving)
        self.label = label
        self._before: tuple[dict[str, Any], str, dict[str, Any]] | None = None
        self._next_origin = view_origin

    def text(self) -> str:
        return self.label or "Turn Off"

    def redo(self, library: Library) -> None:
        node = library.node(self.node_id)
        data = dict(node.module_data.get(self.module_id, {}))
        prose = node.module_text.get(self.module_id, "")
        shelf = dict(node.module_data.get(SHELF_ID, {}))
        if self._before is None:
            self._before = (data, prose, shelf)
        entries = _entries(node)
        if data or prose:
            entries[self.module_id] = {"data": data, **({"text": prose} if prose else {})}
        origin = self._next_origin
        library.set_module_data(self.node_id, SHELF_ID, _shelf(entries), origin)
        library.set_module_data(self.node_id, self.module_id, self.leaving, origin)
        library.set_text(self.node_id, self.module_id, "", origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, library: Library) -> None:
        assert self._before is not None
        data, prose, shelf = self._before
        library.set_module_data(self.node_id, SHELF_ID, shelf, UNDO_ORIGIN)
        library.set_module_data(self.node_id, self.module_id, data, UNDO_ORIGIN)
        library.set_text(self.node_id, self.module_id, prose, UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        return False


class UnshelveCommand:
    """Turn an aspect back on with what the shelf kept for it.

    The shelved data replaces whatever the entry holds now — the opt-out marker, usually —
    and the prose comes back; the shelf forgets the module. Undo puts all three back.
    """

    def __init__(
        self,
        node_id: NodeId,
        module_id: str,
        view_origin: object | None = None,
        label: str = "",
    ) -> None:
        self.node_id = node_id
        self.module_id = module_id
        self.label = label
        self._before: tuple[dict[str, Any], str, dict[str, Any]] | None = None
        self._next_origin = view_origin

    def text(self) -> str:
        return self.label or "Turn On"

    def redo(self, library: Library) -> None:
        node = library.node(self.node_id)
        if self._before is None:
            self._before = (
                dict(node.module_data.get(self.module_id, {})),
                node.module_text.get(self.module_id, ""),
                dict(node.module_data.get(SHELF_ID, {})),
            )
        entries = _entries(node)
        kept = entries.pop(self.module_id, {})
        origin = self._next_origin
        library.set_module_data(self.node_id, SHELF_ID, _shelf(entries), origin)
        library.set_module_data(self.node_id, self.module_id, dict(kept.get("data", {})), origin)
        library.set_text(self.node_id, self.module_id, str(kept.get("text", "")), origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, library: Library) -> None:
        assert self._before is not None
        data, prose, shelf = self._before
        library.set_module_data(self.node_id, SHELF_ID, shelf, UNDO_ORIGIN)
        library.set_module_data(self.node_id, self.module_id, data, UNDO_ORIGIN)
        library.set_text(self.node_id, self.module_id, prose, UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        return False


def turn_off(
    node_id: NodeId,
    module_id: str,
    *,
    leaving: dict[str, Any] | None = None,
    label: str = "",
    view_origin: object | None = None,
) -> Command:
    """The command that turns an aspect off: shelve it, and leave ``leaving`` behind."""
    return ShelveCommand(node_id, module_id, leaving or {}, view_origin, label)


def turn_on(
    node: Node,
    module_id: str,
    *,
    fresh: dict[str, Any],
    label: str = "",
    view_origin: object | None = None,
) -> Command:
    """The command that turns an aspect on: what the shelf kept, else ``fresh``."""
    if shelved(node, module_id) is not None:
        return UnshelveCommand(node.id, module_id, view_origin, label)
    return SetModuleDataCommand(node.id, module_id, fresh, view_origin, label)


def migrate_shelved(repo: Repository[Any], formats: Sequence[ModuleDataFormat]) -> list[str]:
    """Bring every shelved entry to its module's current format.

    Shelved data is a module's data at the version it was shelved, and it may sit there
    across a build that bumps the format — so the migration pass reaches into the shelf
    exactly as it reaches the live entries, or turning the aspect on would hand the module
    a shape it no longer reads. Returns the owner ids that changed, like the live pass.
    """
    declared = {fmt.module_id: fmt for fmt in formats}
    changed: list[str] = []
    for owner in repo.owners():
        shelf = owner.module_data.get(SHELF_ID)
        if not shelf:
            continue
        entries = {
            module_id: dict(entry) for module_id, entry in shelf.get(ASPECTS_KEY, {}).items()
        }
        touched = False
        for module_id, entry in entries.items():
            fmt = declared.get(module_id)
            if fmt is None:
                continue
            current = migrated(entry.get("data", {}), fmt)
            if current is not None:
                entry["data"] = current
                touched = True
        if touched:
            repo.set_module_data(owner.id, SHELF_ID, _shelf(entries))
            changed.append(owner.id)
    return changed
