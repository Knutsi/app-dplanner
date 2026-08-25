"""The dynamic menu bar: one QAction per spec, restated on every context change.

QActions are created once and mutated (visible/enabled/text/checked) rather than the menus
being rebuilt, for two reasons: rebuilding tears down open menus and flickers, and a
QAction must stay alive for its shortcut to stay registered — a disabled action's shortcut
simply does not fire, which is exactly the wanted behaviour.

Group separators are pre-created the same way: one hidden separator QAction per group
boundary, shown only when the groups on both sides hold a visible action — so a fully
hidden group never leaves a dangling line, and menus still auto-hide when empty.
"""

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMenu

from dplanner.framework.action_registry import (
    ActionRegistry,
    ActionSpec,
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
        # (menu, group, submenu title) → child QMenu, created on first matching spec.
        self._submenus: dict[tuple[str, str, str], QMenu] = {}
        self._keys: dict[QAction, SortKey] = {}  # Every action, separators included.
        # Per menu: the separator PRECEDING each group (group index ≥ 1).
        self._separators: dict[str, dict[int, QAction]] = {}

        bar = window.menuBar()
        # Belt and braces alongside AA_DontUseNativeMenuBar (set in dplanner.app before the
        # QApplication exists): the in-window menu bar is what the stylesheet can reach.
        bar.setNativeMenuBar(False)
        bar.setObjectName("MainMenuBar")
        for menu_index, (name, groups) in enumerate(registry.menus.items()):
            menu = bar.addMenu(f"&{name}")
            menu.menuAction().setVisible(False)  # Hidden until something visible lands in it.
            self._menus[name] = menu
            self._separators[name] = {}
            for group_index in range(1, len(groups)):
                separator = QAction(self._window)
                separator.setSeparator(True)
                separator.setVisible(False)
                menu.addAction(separator)
                # order -1 puts the separator ahead of every action in its group.
                self._keys[separator] = (menu_index, group_index, -1, "")
                self._separators[name][group_index] = separator

        for spec in registry.all_specs():
            self._add_spec(spec)
        registry.registered.connect(self._add_spec)
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
        action.triggered.connect(lambda _checked=False, s=spec: s.run(self._context.current()))

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
        """The child menu for a submenu spec, created at the first spec's sort position."""
        assert spec.submenu is not None
        lookup = (spec.menu, spec.group, spec.submenu)
        child = self._submenus.get(lookup)
        if child is None:
            parent = self._menus[spec.menu]
            child = QMenu(spec.submenu, parent)
            self._keys[child.menuAction()] = key
            before = next((a for a in parent.actions() if self._keys[a] > key), None)
            if before is None:
                parent.addMenu(child)
            else:
                parent.insertMenu(before, child)
            self._submenus[lookup] = child
        return child

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
        for child in self._submenus.values():
            child.menuAction().setVisible(any(a.isVisible() for a in child.actions()))
        for name, menu in self._menus.items():
            group_visible = [False] * len(self._registry.menus.groups(name))
            for action in menu.actions():
                if not action.isSeparator() and action.isVisible():
                    group_visible[self._keys[action][1]] = True
            # A separator shows only between visible groups: its own group must be
            # visible AND some earlier group too — never leading, never dangling.
            earlier = group_visible[0]
            for group_index, separator in self._separators[name].items():
                separator.setVisible(earlier and group_visible[group_index])
                earlier = earlier or group_visible[group_index]
            menu.menuAction().setVisible(any(group_visible))
