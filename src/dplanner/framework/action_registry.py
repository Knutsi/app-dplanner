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
from typing import Protocol

from PySide6.QtGui import QColor, QIcon, QKeySequence
from PySide6.QtWidgets import QMenu

from dplanner.core.signals import Signal
from dplanner.core.telemetry import current
from dplanner.framework.context import Context


@dataclass(frozen=True)
class ActionState:
    visible: bool = True
    enabled: bool = True
    label: str | None = None  # None → the spec's default label.
    checked: bool | None = None  # None → not checkable.


# The common states, named so state callbacks read as intent.
ENABLED = ActionState()
DISABLED = ActionState(enabled=False)


def always_enabled(_context: Context) -> ActionState:
    return ENABLED


type SortKey = tuple[int, int, int, str]


class MenuPlacement(Protocol):
    """Where an entry sits in the bar — all that validation and ordering need to know.

    Both registrations satisfy it: an :class:`ActionSpec` and a :class:`DataMenuSpec` are
    placed by the same table and sorted by the same key, so the two kinds of entry can
    never disagree about where a group is.
    """

    @property
    def id(self) -> str: ...

    @property
    def menu(self) -> str: ...

    @property
    def group(self) -> str: ...

    @property
    def order(self) -> int: ...


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

    def validate(self, spec: MenuPlacement) -> None:
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

    def sort_key(self, spec: MenuPlacement) -> SortKey:
        """Menu-bar order: (menu, group, order, id) — total and stable across modules."""
        return (
            self._index[spec.menu],
            self._structure[spec.menu].index(spec.group),
            spec.order,
            spec.id,
        )


# Between the levels of a submenu path, and between the menus of the path the command
# palette prints under a verb. The same mark the documentation uses for one.
PATH_SEPARATOR = " ▸ "


@dataclass(frozen=True)
class ActionSpec:
    id: str  # "explorer.delete_items" — module-prefixed, globally unique.
    label: str  # Default menu text, may carry an & mnemonic.
    menu: str  # Top-level menu name without mnemonic: "File", "Edit", …
    group: str  # Named group within the menu, from dplanner.menus.MENU_STRUCTURE.
    order: int = 50  # Sort key inside the group; gaps of 10 leave room to interleave.
    # Actions sharing a (menu, submenu) title collapse into one child menu placed at the
    # first such action's sort position — whatever groups they come from, with a rule drawn
    # inside it where the group changes. None (the norm) stays a flat entry. A title holding
    # PATH_SEPARATOR nests: "Theme ▸ Omarchy" is a child menu inside the Theme child menu,
    # for a list too long to sit flat among its siblings.
    submenu: str | None = None
    # False keeps a spec out of the command palette: for a verb's second menu placement,
    # whose original already appears there under the same label.
    palette: bool = True
    # False keeps a spec out of the menu bar and every pop-up, for a verb whose seat in
    # the menus is a data child menu's own entries — Run Agent, whose child lists the
    # profiles it runs through. The spec still names its menu (and a submenu, the data
    # menu's title) so the palette can say where the verb lives, and it still runs from
    # the palette, a button or a data menu's `append_action`. It carries no shortcut:
    # only a QAction seated in the bar can fire one, and there is none.
    in_menus: bool = True
    # A tuple binds several equivalent keys (e.g. Ctrl++ and Ctrl+=, whichever the
    # keyboard layout can reach); the first one is what the palette displays.
    shortcut: QKeySequence.StandardKey | str | tuple[str, ...] | None = None
    # A glyph for the verb, painted in the ink the presenter hands over. The pop-up
    # presenters render it and the menu bar does not, on purpose: a pop-up is built fresh
    # every time it opens, while a menu bar's QActions outlive every theme change and a
    # colour copied onto one goes stale.
    icon: Callable[[QColor], QIcon] | None = None
    tip: str = ""
    state: Callable[[Context], ActionState] = field(default=always_enabled)
    run: Callable[[Context], None] = field(default=lambda _context: None)


@dataclass(frozen=True)
class DataMenuSpec:
    """A child menu whose entries are *data*, rebuilt every time it opens.

    A saved layout, a live agent run: rows that come and go while the application sits
    there, which registered specs cannot say. So the spec carries a ``fill`` instead of
    entries — the presenter clears the child menu and calls it on open, the way every
    pop-up is built fresh, so a row can never go stale. The fill owns the whole story,
    the empty one included: a data menu stays visible with nothing to list (the *menu*
    is the capability, and hidden means absent), so say so with a disabled entry. A
    fixed verb inside one renders through
    :func:`dplanner.framework.action_menu.append_action`, never as a copy.
    """

    id: str  # "agent_run.list" — module-prefixed, globally unique.
    menu: str
    group: str
    title: str  # The child menu's name in the bar.
    fill: Callable[[QMenu], None]
    order: int = 50


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
        self._data_menus: dict[str, DataMenuSpec] = {}
        self.registered: Signal[ActionSpec] = Signal()
        self.data_menu_registered: Signal[DataMenuSpec] = Signal()

    def register(self, spec: ActionSpec) -> None:
        if spec.id in self._specs:
            raise ValueError(f"action id {spec.id!r} already registered")
        self.menus.validate(spec)
        if not spec.in_menus and spec.shortcut is not None:
            raise ValueError(f"action {spec.id!r} is in no menu, so nothing fires its shortcut")
        self._specs[spec.id] = spec
        self.registered.emit(spec)

    def register_data_menu(self, spec: DataMenuSpec) -> None:
        if spec.id in self._data_menus:
            raise ValueError(f"data menu id {spec.id!r} already registered")
        self.menus.validate(spec)
        self._data_menus[spec.id] = spec
        self.data_menu_registered.emit(spec)

    def data_menus(self) -> list[DataMenuSpec]:
        return sorted(self._data_menus.values(), key=self.menus.sort_key)

    def data_menu(self, spec_id: str) -> DataMenuSpec:
        """One data child menu by id — for a button that drops it down somewhere else."""
        return self._data_menus[spec_id]

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
        """Run by id, honouring the state gate.

        The one path every presenter takes — menu bar, pop-ups, toolbar, palette, aspect
        bar, keymap and tests alike — which is what makes it the place an action is timed:
        the span is the verb's whole cost, every view's reaction to it included.
        """
        spec = self._specs[action_id]
        state = spec.state(context)
        if state.visible and state.enabled:
            with current().span("action", action_id):
                spec.run(context)
