"""The application shell: the verbs every configuration of the application has.

Undo, redo, quit, full screen, about, the theme picker and the command palette — the things
that belong to the window itself rather than to any activity or any data. Nothing here
knows what the application is for, which is why this module ships with the template
unchanged.
"""

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QPoint
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMainWindow, QMessageBox

from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context, ContextService
from dplanner.framework.palette import CommandPalette
from dplanner.framework.panels import PanelArea, PanelRegistry, PanelSpec
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.window import PanelHost
from dplanner.framework.zoom import ZoomService
from dplanner.identity import APP_NAME, APP_VERSION
from dplanner.theme.themes import OMARCHY_THEMES


@dataclass(frozen=True)
class AppShellDeps:
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    theme: ThemeService
    undo: UndoService[Any]
    zoom: ZoomService
    panels: PanelRegistry
    chrome: PanelHost  # Which anchored panels the user has switched on.
    # The shell owns the window-level verbs (quit, full screen, dialog parenting) —
    # but plain QMainWindow API suffices, so no dependency on the concrete MainWindow.
    window: QMainWindow


class AppShellModule:
    id = "appshell"

    def __init__(self, deps: AppShellDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        window = deps.window
        undo = deps.undo

        # The registry re-evaluates action states on context changes only, so an undo-stack
        # change re-emits the context to force a refresh of the Undo/Redo labels. A
        # poke rather than a new signal: one refresh path is easier to reason about than two.
        def poke_context() -> None:
            deps.context.refresh()

        undo.changed.connect(poke_context)

        def undo_state(_context: Context) -> ActionState:
            if undo.can_undo():
                return ActionState(label=f"&Undo {undo.undo_text()}")
            return ActionState(enabled=False, label="&Undo")

        def redo_state(_context: Context) -> ActionState:
            if undo.can_redo():
                return ActionState(label=f"&Redo {undo.redo_text()}")
            return ActionState(enabled=False, label="&Redo")

        deps.actions.register(
            ActionSpec(
                id="appshell.undo",
                label="&Undo",
                menu="Edit",
                group="history",
                order=10,
                shortcut=QKeySequence.StandardKey.Undo,
                tip="Undo the last change",
                state=undo_state,
                run=lambda _context: undo.undo(),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="appshell.redo",
                label="&Redo",
                menu="Edit",
                group="history",
                order=20,
                shortcut=QKeySequence.StandardKey.Redo,
                tip="Redo the last undone change",
                state=redo_state,
                run=lambda _context: undo.redo(),
            )
        )

        def run_quit(_context: Context) -> None:
            # close(), not QApplication.quit(): closing runs the window's close hooks (the
            # final autosave flush); the application exits when its last window closes.
            window.close()

        def run_toggle_full_screen(_context: Context) -> None:
            if window.isFullScreen():
                window.showNormal()
            else:
                window.showFullScreen()

        def run_about(_context: Context) -> None:
            QMessageBox.about(
                window,
                f"About {APP_NAME}",
                f"<b>{APP_NAME}</b> {APP_VERSION}",
            )

        def run_palette(_context: Context) -> None:
            CommandPalette(deps.actions, deps.context, window).exec()

        deps.actions.register(
            ActionSpec(
                id="appshell.quit",
                label="&Quit",
                menu="File",
                group="window",
                order=30,
                shortcut=QKeySequence.StandardKey.Quit,
                tip=f"Exit {APP_NAME}",
                run=run_quit,
            )
        )

        # -- View's Tabs submenu, which the tab bar's right-click also renders -------------
        # Moving a tab is what splits the window: the group appears to receive it and
        # disappears when the last tab leaves, so there is no split mode and never an empty
        # pane. Every state here depends on the tab host rather than on the context graph,
        # which is what poke_context() below is for — the same shape as Undo's label.
        # One group for all six: the submenu collapse keys on (menu, group, submenu), so a
        # second group would open a second "Tabs" child menu. The move verbs come first by
        # order alone; the move/close separator is the price of the fold.
        def close_all(activities: list[Any]) -> None:
            # A list, not the live one: closing mutates what activities() returns.
            for activity in activities:
                deps.tabs.close_activity(activity)

        def others() -> list[Any]:
            current = deps.tabs.current_activity()
            return [a for a in deps.tabs.activities() if a is not current]

        deps.actions.register(
            ActionSpec(
                id="appshell.move_tab_right",
                label="Move Tab &Right",
                menu="View",
                group="tabs",
                submenu="Tabs",
                order=10,
                # Arrows first — reachable on any laptop — with the browsers' move-tab keys
                # as a synonym. No AltGr anywhere, so layout-proof. Text editors keep
                # word-selection: an editable field claims these via ShortcutOverride, which
                # test_appshell's word-selection test pins down.
                shortcut=("Ctrl+Shift+Right", "Ctrl+Shift+PgDown"),
                tip="Put this tab in the group to its right, making one if there is room",
                state=lambda _context: ENABLED if deps.tabs.can_move_right() else DISABLED,
                run=lambda _context: deps.tabs.move_current_right(),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="appshell.move_tab_left",
                label="Move Tab &Left",
                menu="View",
                group="tabs",
                submenu="Tabs",
                order=20,
                shortcut=("Ctrl+Shift+Left", "Ctrl+Shift+PgUp"),
                tip="Put this tab back in the group to its left",
                state=lambda _context: ENABLED if deps.tabs.can_move_left() else DISABLED,
                run=lambda _context: deps.tabs.move_current_left(),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="appshell.close_tab",
                label="&Close Tab",
                menu="View",
                group="tabs",
                submenu="Tabs",
                order=30,
                shortcut=QKeySequence.StandardKey.Close,
                tip="Close the current tab",
                state=lambda _context: (
                    ENABLED if deps.tabs.current_activity() is not None else DISABLED
                ),
                run=lambda _context: deps.tabs.close_current(),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="appshell.close_other_tabs",
                label="Close &Other Tabs",
                menu="View",
                group="tabs",
                submenu="Tabs",
                order=40,
                tip="Close every tab but this one, in every group",
                state=lambda _context: ENABLED if others() else DISABLED,
                run=lambda _context: close_all(others()),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="appshell.close_tabs_right",
                label="Close Tabs to the &Right",
                menu="View",
                group="tabs",
                submenu="Tabs",
                order=50,
                tip="Close the tabs after this one in its own group",
                state=lambda _context: ENABLED if deps.tabs.after_current() else DISABLED,
                run=lambda _context: close_all(deps.tabs.after_current()),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="appshell.close_all_tabs",
                label="Close &All Tabs",
                menu="View",
                group="tabs",
                submenu="Tabs",
                order=60,
                tip="Empty the window",
                state=lambda _context: ENABLED if deps.tabs.activities() else DISABLED,
                run=lambda _context: close_all(deps.tabs.activities()),
            )
        )
        # What a tab can do depends on how many tabs and groups there are, which no signal
        # reports; every activity change is also every moment one could have changed.
        deps.tabs.activity_changed.connect(lambda _activity: poke_context())

        # The tab bar has made the tab current by the time this arrives, so the menu is built
        # from the same context every other presenter reads.
        def show_tab_menu(at: QPoint) -> None:
            build_menu(deps.actions, deps.context, "View", window, submenu="Tabs").exec(at)

        deps.tabs.tab_menu_requested.connect(show_tab_menu)

        deps.actions.register(
            ActionSpec(
                id="appshell.toggle_full_screen",
                label="Toggle &Full Screen",
                menu="View",
                group="window",
                order=10,
                shortcut=QKeySequence.StandardKey.FullScreen,
                tip="Enter or leave full screen",
                run=run_toggle_full_screen,
            )
        )
        # -- editor text size -------------------------------------------------------------
        deps.actions.register(
            ActionSpec(
                id="appshell.text_larger",
                label="Larger &Text",
                menu="View",
                group="zoom",
                order=10,
                # Ctrl++ is the reachable key on layouts where = needs Shift (e.g.
                # Norwegian); Ctrl+= is the habitual binding on US-style layouts.
                shortcut=("Ctrl++", "Ctrl+="),
                tip="Increase the text size",
                run=lambda _context: deps.zoom.change(+1),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="appshell.text_smaller",
                label="Smaller Te&xt",
                menu="View",
                group="zoom",
                order=20,
                shortcut="Ctrl+-",
                tip="Decrease the text size",
                run=lambda _context: deps.zoom.change(-1),
            )
        )

        # -- themes -----------------------------------------------------------------------
        # The house themes stay flat, checkable entries; the rest live in an "Other"
        # submenu so the View menu stays scannable. All appear flat in the command palette,
        # and the checkmark shows state in every presentation.
        deps.theme.changed.connect(lambda _theme: poke_context())

        def register_theme(theme_name: str, order: int, submenu: str | None = None) -> None:
            def theme_state(_context: Context, name: str = theme_name) -> ActionState:
                return ActionState(checked=deps.theme.current.name == name)

            def run_theme(_context: Context, name: str = theme_name) -> None:
                deps.theme.set_theme(name)

            title = theme_name.replace("-", " ").title()
            deps.actions.register(
                ActionSpec(
                    id=f"appshell.theme_{theme_name}",
                    label=f"Theme: {title}" if submenu else f"Theme: &{title}",
                    menu="View",
                    group="theme",
                    order=order,
                    submenu=submenu,
                    tip=f"Switch to the {title} theme",
                    state=theme_state,
                    run=run_theme,
                )
            )

        for offset, theme_name in enumerate(("dark", "light", "sepia")):
            register_theme(theme_name, order=10 * (offset + 1))
        for offset, theme in enumerate(OMARCHY_THEMES):
            register_theme(theme.name, order=100 + offset, submenu="Other")

        deps.actions.register(
            ActionSpec(
                id="appshell.command_palette",
                label="&Command Palette…",
                menu="View",
                group="palette",
                order=20,
                shortcut="Ctrl+Shift+P",
                tip="Search and run any available command",
                run=run_palette,
            )
        )

        # -- panels -----------------------------------------------------------------------
        # The whole-side switches first: one keystroke folds a side away and brings it back,
        # with every panel's own on/off untouched underneath.
        def register_area_toggle(area: PanelArea, label: str, shortcut: str, order: int) -> None:
            def area_state(_context: Context) -> ActionState:
                return ActionState(checked=not deps.chrome.is_area_collapsed(area))

            def run_area(_context: Context) -> None:
                deps.chrome.set_area_collapsed(area, not deps.chrome.is_area_collapsed(area))

            deps.actions.register(
                ActionSpec(
                    id=f"appshell.toggle_{area.value}_panels",
                    label=label,
                    menu="View",
                    group="areas",
                    order=order,
                    shortcut=shortcut,
                    tip=f"Show or hide every panel on the {area.value} side",
                    state=area_state,
                    run=run_area,
                )
            )

        register_area_toggle(PanelArea.LEFT, "Left Side Panel", "Ctrl+B", 10)
        register_area_toggle(PanelArea.RIGHT, "Right Side Panel", "Ctrl+Alt+B", 20)
        # BOTTOM has no registered panels yet; Ctrl+J is reserved for its toggle when one exists.
        # Collapse also flips when a gesture reveals a panel, so the checkmarks re-read here.
        deps.chrome.areas_changed.connect(lambda _area: poke_context())

        # One checkable entry per anchored panel. Both halves are needed: the framework's own
        # index panel is registered before any module runs, and every module's panel arrives
        # after this line.
        def register_panel_toggle(spec: PanelSpec) -> None:
            def panel_state(_context: Context, panel_id: str = spec.id) -> ActionState:
                return ActionState(checked=deps.chrome.is_panel_visible(panel_id))

            def run_panel(_context: Context, panel_id: str = spec.id) -> None:
                deps.chrome.set_panel_visible(panel_id, not deps.chrome.is_panel_visible(panel_id))

            deps.actions.register(
                ActionSpec(
                    id=f"appshell.panel_{spec.id}",
                    label=spec.title,
                    menu="View",
                    group="panels",
                    # After the task centre: that is a thing to open, these are what the
                    # window is currently made of. One order for all of them, so the
                    # registry's (order, id) tie-break lists them alphabetically — a
                    # panel's own `order` is its position in an area and means nothing here.
                    order=100,
                    tip=f"Show or hide the {spec.title} panel",
                    state=panel_state,
                    run=run_panel,
                )
            )

        for spec in deps.panels.panels():
            register_panel_toggle(spec)
        deps.panels.registered.connect(register_panel_toggle)
        # A panel hidden from its own header menu has to reach the checkmark too.
        deps.chrome.panels_changed.connect(lambda _panel_id: poke_context())

        deps.actions.register(
            ActionSpec(
                id="appshell.about",
                label="&About Writer",
                menu="Help",
                group="about",
                order=10,
                tip="About this application",
                run=run_about,
            )
        )
