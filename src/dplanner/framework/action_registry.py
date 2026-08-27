"""Actions: the application's verb vocabulary, evaluated against the context.

An :class:`ActionSpec` is declarative — where it lives in the menus, what it is called by
default — plus two callbacks: ``state(context)`` decides visibility, enablement and the
current label ("Delete 5 Items"), and ``run(context)`` performs it.

Both callbacks are pure functions of the context, and that is the design, not a detail. It
means the same spec is correct in the menu bar, the command palette, a toolbar and a
right-click menu without any of them coordinating, and it means a test can evaluate an
action by constructing a :class:`Context` — no widgets, no window, no application.

Modules register specs. They never create a QAction: each presenter builds its own widgets
from this one source of truth, which is why a new action appears in four places at once.

The menu table itself lives in :mod:`dplanner.menus`, because which menus exist is
application vocabulary. It is passed in at construction and validated at registration.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtGui import QKeySequence

from dplanner.core.signals import Signal
from dplanner.framework.context import Context


@dataclass(frozen=True)
class ActionState:
    visible: bool = True
    enabled: bool = True
    label: str | None = None  # None → the spec's default label.
    checked: bool | None = None  # None → not checkable.


# The common states, named so state callbacks read as intent.
ENABLED = ActionState()
HIDDEN = ActionState(visible=False, enabled=False)
DISABLED = ActionState(enabled=False)


def always_enabled(_context: Context) -> ActionState:
    return ENABLED


type SortKey = tuple[int, int, int, str]


class MenuStructure:
    """Top-level menus in bar order, each holding named groups in menu order.

    A separator renders between adjacent groups that both hold a visible action, so a
    module places an action in a group and never thinks about separators or about what
    other modules put nearby. That is the whole reason groups exist: ordering across
    modules needs no hand-coordinated global numbering, because ``order`` only ranks
    actions *inside* one group.
    """

    def __init__(self, structure: dict[str, tuple[str, ...]]) -> None:
        self._structure = dict(structure)
        self._index = {name: index for index, name in enumerate(self._structure)}

    def menus(self) -> tuple[str, ...]:
        return tuple(self._structure)

    def groups(self, menu: str) -> tuple[str, ...]:
        return self._structure[menu]

    def items(self) -> list[tuple[str, tuple[str, ...]]]:
        return list(self._structure.items())

    def validate(self, spec: "ActionSpec") -> None:
        """Raise if a spec names a menu or group that does not exist.

        At registration, not at render time: a typo should fail at startup naming the
        offending action id, not put a menu item somewhere nobody looks.
        """
        groups = self._structure.get(spec.menu)
        if groups is None:
            raise ValueError(f"action {spec.id!r} names unknown menu {spec.menu!r}")
        if spec.group not in groups:
            raise ValueError(
                f"action {spec.id!r} names unknown group {spec.group!r} in menu"
                f" {spec.menu!r} (groups: {', '.join(groups)})"
            )

    def sort_key(self, spec: "ActionSpec") -> SortKey:
        """Menu-bar order: (menu, group, order, id) — total and stable across modules."""
        return (
            self._index[spec.menu],
            self._structure[spec.menu].index(spec.group),
            spec.order,
            spec.id,
        )


@dataclass(frozen=True)
class ActionSpec:
    id: str  # "explorer.delete_items" — module-prefixed, globally unique.
    label: str  # Default menu text, may carry an & mnemonic.
    menu: str  # Top-level menu name without mnemonic: "File", "Edit", …
    group: str  # Named group within the menu, from dplanner.menus.MENU_STRUCTURE.
    order: int = 50  # Sort key inside the group; gaps of 10 leave room to interleave.
    # Actions sharing a (menu, group, submenu) title collapse into one child menu placed
    # at the first such action's sort position. None (the norm) stays a flat entry.
    submenu: str | None = None
    # False keeps a spec out of the command palette: for a verb's second menu placement,
    # whose original already appears there under the same label.
    palette: bool = True
    # A tuple binds several equivalent keys (e.g. Ctrl++ and Ctrl+=, whichever the
    # keyboard layout can reach); the first one is what the palette displays.
    shortcut: QKeySequence.StandardKey | str | tuple[str, ...] | None = None
    tip: str = ""
    state: Callable[[Context], ActionState] = field(default=always_enabled)
    run: Callable[[Context], None] = field(default=lambda _context: None)


def key_sequences(
    shortcut: QKeySequence.StandardKey | str | tuple[str, ...] | None,
) -> list[QKeySequence]:
    """Every key sequence a spec's shortcut binds, ready for QAction.setShortcuts."""
    if shortcut is None:
        return []
    if isinstance(shortcut, QKeySequence.StandardKey):
        return list(QKeySequence.keyBindings(shortcut))  # All platform bindings.
    if isinstance(shortcut, str):
        return [QKeySequence(shortcut)]
    return [QKeySequence(s) for s in shortcut]


class ActionRegistry:
    def __init__(self, menus: MenuStructure) -> None:
        self.menus = menus
        self._specs: dict[str, ActionSpec] = {}
        self.registered: Signal[ActionSpec] = Signal()

    def register(self, spec: ActionSpec) -> None:
        if spec.id in self._specs:
            raise ValueError(f"action id {spec.id!r} already registered")
        self.menus.validate(spec)
        self._specs[spec.id] = spec
        self.registered.emit(spec)

    def spec(self, action_id: str) -> ActionSpec:
        return self._specs[action_id]

    def all_specs(self) -> list[ActionSpec]:
        return sorted(self._specs.values(), key=self.menus.sort_key)

    def runnable(self, context: Context) -> list[tuple[ActionSpec, ActionState]]:
        """Specs the palette may offer right now: visible and enabled in ``context``."""
        result = []
        for spec in self.all_specs():
            state = spec.state(context)
            if state.visible and state.enabled:
                result.append((spec, state))
        return result

    def run(self, action_id: str, context: Context) -> None:
        """Run by id, honouring the state gate — the programmatic path used by tests."""
        spec = self._specs[action_id]
        state = spec.state(context)
        if state.visible and state.enabled:
            spec.run(context)
