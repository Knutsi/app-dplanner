"""The dynamic menu bar: one QAction per spec, restated on every context change.

QActions are created once and mutated (visible/enabled/text/checked) rather than the menus
being rebuilt, for two reasons: rebuilding tears down open menus and flickers, and a
QAction must stay alive for its shortcut to stay registered — a disabled action's shortcut
simply does not fire, which is exactly the wanted behaviour.

Group separators are pre-created the same way: one hidden separator QAction per group
boundary, shown only when the groups on both sides hold a visible action — so a fully
hidden group never leaves a dangling line, and menus still auto-hide when empty. A **child
menu is a container of the same kind**: one per title, holding the same group boundaries, so
two groups feeding one submenu get the rule between them instead of a second child menu
wearing the same name.

The one exception to create-once-and-mutate is a **data child menu** (`DataMenuSpec`): its
entries are data rather than verbs, so it is cleared and refilled every time it opens — the
pop-up presenters' rule, applied to the one container in the bar whose contents a registry
cannot say.
"""

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMenu

from dplanner.framework.action_registry import (
    PATH_SEPARATOR,
    ActionRegistry,
    ActionSpec,
    DataMenuSpec,
    SortKey,
    key_sequences,
)
from dplanner.framework.context import Context, ContextService


class DynamicMenuBar:
    """Owns the QMenus and QActions. Keep this object referenced for the app's lifetime:
    menu wrappers handed to Python by addMenu() are invalidated once the last Python
    reference is dropped."""

    def __init__(
        self, window: QMainWindow, registry: ActionRegistry, context: ContextService
    ) -> None:
        self._window = window
        self._registry = registry
        self._context = context
        self._actions: dict[str, QAction] = {}  # spec id → QAction
        self._menus: dict[str, QMenu] = {}
        # (menu, submenu path) → child QMenu, created on first matching spec; a nested
        # child's path is its titles joined by PATH_SEPARATOR, and a parent is always
        # created before its child. Keyed by path rather than by group: a submenu is one
        # child menu whatever feeds it.
        self._submenus: dict[tuple[str, str], QMenu] = {}
        self._data_menus: dict[str, tuple[DataMenuSpec, QMenu]] = {}  # spec id → its menu.
        self._keys: dict[QAction, SortKey] = {}  # Every action, separators included.
        self._menu_index = {name: index for index, name in enumerate(registry.menus.menus())}
        # Per container — a menu (title None) or one of its child menus — the separator
        # PRECEDING each group (group index ≥ 1).
        self._separators: dict[tuple[str, str | None], dict[int, QAction]] = {}

        bar = window.menuBar()
        # Belt and braces alongside AA_DontUseNativeMenuBar (set in dplanner.app before the
        # QApplication exists): the in-window menu bar is what the stylesheet can reach.
        bar.setNativeMenuBar(False)
        bar.setObjectName("MainMenuBar")
        for name in registry.menus.menus():
            menu = bar.addMenu(f"&{name}")
            menu.menuAction().setVisible(False)  # Hidden until something visible lands in it.
            self._menus[name] = menu
            self._add_separators((name, None), menu)

        for spec in registry.all_specs():
            self._add_spec(spec)
        for data in registry.data_menus():
            self._add_data_menu(data)
        registry.registered.connect(self._add_spec)
        registry.data_menu_registered.connect(self._add_data_menu)
        context.changed.connect(self.refresh)
        self.refresh(context.current())

    def action(self, action_id: str) -> QAction:
        return self._actions[action_id]

    def _add_spec(self, spec: ActionSpec) -> None:
        action = QAction(spec.label, self._window)
        if spec.shortcut is not None:
            action.setShortcuts(key_sequences(spec.shortcut))
        if spec.tip:
            action.setStatusTip(spec.tip)
        # Defensive: menu roles would relocate items into the macOS application menu if the
        # native menu bar were ever re-enabled. Pinning NoRole keeps placement predictable.
        action.setMenuRole(QAction.MenuRole.NoRole)
        # Through the registry, like every other presenter: one gate, one timed span.
        action.triggered.connect(
            lambda _checked=False, sid=spec.id: self._registry.run(sid, self._context.current())
        )

        menu = self._menus[spec.menu]
        key = self._registry.menus.sort_key(spec)
        if spec.submenu is not None:
            menu = self._submenu(spec, key)
        self._keys[action] = key
        before = next((a for a in menu.actions() if self._keys[a] > key), None)
        if before is None:
            menu.addAction(action)
        else:
            menu.insertAction(before, action)
        self._actions[spec.id] = action
        self._refresh_one(spec, action, self._context.current())
        self._refresh_decorations()

    def _submenu(self, spec: ActionSpec, key: SortKey) -> QMenu:
        """The child menu for a submenu spec, created at the first spec's sort position.

        Its position is that first spec's, and a later group feeding the same title lands
        inside it rather than beside it — which is what the parent's group bookkeeping
        reads, since only the menuAction it holds carries a group. A path nests: each
        level is created inside the one before it by the same rule, so ``"Theme ▸
        Omarchy"`` is a child menu inside the Theme child menu, at this spec's position
        among Theme's entries.
        """
        assert spec.submenu is not None
        parent = self._menus[spec.menu]
        path = ""
        for title in spec.submenu.split(PATH_SEPARATOR):
            path = title if not path else path + PATH_SEPARATOR + title
            lookup = (spec.menu, path)
            child = self._submenus.get(lookup)
            if child is None:
                child = QMenu(title, parent)
                self._keys[child.menuAction()] = key
                before = next((a for a in parent.actions() if self._keys[a] > key), None)
                if before is None:
                    parent.addMenu(child)
                else:
                    parent.insertMenu(before, child)
                self._submenus[lookup] = child
                self._add_separators(lookup, child)
            parent = child
        return parent

    def _add_data_menu(self, spec: DataMenuSpec) -> None:
        """A data child menu: inserted at its sort position, filled fresh on every open.

        Nothing in it is restated on a context change — its QActions exist only while it
        is open, so the fill reads the world at the moment the user looks, exactly as a
        pop-up presenter does. Its menuAction stays visible even when the list is empty:
        the *menu* is the capability, and an empty list is the fill's own story to tell
        with a disabled entry.
        """
        parent = self._menus[spec.menu]
        child = QMenu(spec.title, parent)
        key = self._registry.menus.sort_key(spec)
        self._keys[child.menuAction()] = key
        before = next((a for a in parent.actions() if self._keys[a] > key), None)
        if before is None:
            parent.addMenu(child)
        else:
            parent.insertMenu(before, child)
        child.aboutToShow.connect(lambda s=spec, c=child: self._fill_data(s, c))
        self._data_menus[spec.id] = (spec, child)
        self._refresh_decorations()

    def data_menu(self, spec_id: str) -> QMenu:
        """The data child menu as it would open right now — how a test asks what it offers."""
        spec, child = self._data_menus[spec_id]
        self._fill_data(spec, child)
        return child

    @staticmethod
    def _fill_data(spec: DataMenuSpec, child: QMenu) -> None:
        child.clear()
        spec.fill(child)

    def _add_separators(self, container: tuple[str, str | None], menu: QMenu) -> None:
        """One hidden separator per group boundary, inserted in sort order.

        The same treatment for a menu and for a child menu of it: both hold entries from
        the menu's groups, and both want the rule where the group changes.
        """
        menu_index = self._menu_index[container[0]]
        slots: dict[int, QAction] = {}
        for group_index in range(1, len(self._registry.menus.groups(container[0]))):
            separator = QAction(self._window)
            separator.setSeparator(True)
            separator.setVisible(False)
            # order -1 puts the separator ahead of every action in its group.
            key: SortKey = (menu_index, group_index, -1, "")
            self._keys[separator] = key
            before = next((a for a in menu.actions() if self._keys[a] > key), None)
            if before is None:
                menu.addAction(separator)
            else:
                menu.insertAction(before, separator)
            slots[group_index] = separator
        self._separators[container] = slots

    def refresh(self, context: Context) -> None:
        for spec_id, action in self._actions.items():
            self._refresh_one(self._registry.spec(spec_id), action, context)
        self._refresh_decorations()

    @staticmethod
    def _refresh_one(spec: ActionSpec, action: QAction, context: Context) -> None:
        state = spec.state(context)
        action.setVisible(state.visible)
        action.setEnabled(state.enabled)
        action.setText(state.label if state.label is not None else spec.label)
        if state.checked is not None:
            action.setCheckable(True)
            action.setChecked(state.checked)

    def _refresh_decorations(self) -> None:
        """Separator and menu visibility, derived from the actions' visibility."""
        # Child menus first: their menuAction's visibility feeds the group bookkeeping.
        # Deepest first — a child is always created after its parent, so reversed creation
        # order computes a nested child before the parent that reads it.
        for child in reversed(self._submenus.values()):
            child.menuAction().setVisible(
                any(a.isVisible() and not a.isSeparator() for a in child.actions())
            )
        for (name, title), separators in self._separators.items():
            menu = self._menus[name] if title is None else self._submenus[(name, title)]
            group_visible = [False] * len(self._registry.menus.groups(name))
            for action in menu.actions():
                if not action.isSeparator() and action.isVisible():
                    group_visible[self._keys[action][1]] = True
            # A separator shows only between visible groups: its own group must be
            # visible AND some earlier group too — never leading, never dangling.
            earlier = group_visible[0]
            for group_index, separator in separators.items():
                separator.setVisible(earlier and group_visible[group_index])
                earlier = earlier or group_visible[group_index]
            if title is None:
                menu.menuAction().setVisible(any(group_visible))
