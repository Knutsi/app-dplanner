"""The application shell: the verbs every configuration of the application has.

Undo, redo, quit, full screen, about, the theme picker and the command palette — the things
that belong to the window itself rather than to any activity or any data. Nothing here
knows what the application is for, which is why this module ships with the template
unchanged.
"""

from dataclasses import dataclass
from typing import Any

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMainWindow, QMessageBox

from dplanner.framework.action_registry import ActionRegistry, ActionSpec, ActionState
from dplanner.framework.context import SCOPE_APP, Context, ContextService
from dplanner.framework.palette import CommandPalette
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
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
        # change re-asserts the app scope to force a refresh of the Undo/Redo labels. A
        # poke rather than a new signal: one refresh path is easier to reason about than two.
        def poke_context() -> None:
            deps.context.set_scope(SCOPE_APP, deps.context.current().scope(SCOPE_APP))

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
                id="appshell.close_tab",
                label="&Close Tab",
                menu="File",
                group="window",
                order=10,
                shortcut=QKeySequence.StandardKey.Close,
                tip="Close the current tab",
                run=lambda _context: deps.tabs.close_current(),
            )
        )
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
                group="panels",
                order=20,
                shortcut="Ctrl+Shift+P",
                tip="Search and run any available command",
                run=run_palette,
            )
        )
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
