"""Appearance: View ▸ Theme, and Settings ▸ Appearance.

The Theme child menu renders what the providers offer: *System theme* first, greyed with
its reason where nothing on this machine follows the desktop; then each provider's groups —
an untitled group flat, a titled one a child menu of its own (``"Theme ▸ Omarchy"``), which
is how twenty-two Omarchy themes sit one level down rather than among the house themes.
Every entry is an ``ActionSpec`` rather than the rows of a ``DataMenuSpec``, on purpose: the
command palette lists a spec and never a data row, and *Tokyo Night* one keystroke away is
worth more than a list that refreshes while the window runs — a theme somebody adds to
``~/.config/omarchy/themes`` meanwhile appears at the next start. The check mark compares
the service's ``effective_choice``, a field, so a state callback costs two strings.

A provider that does not apply here, or that the person switched off, contributes no
entries: absent from this machine is the one case *hidden* is for.
"""

from dataclasses import dataclass

from dplanner.framework.action_registry import (
    PATH_SEPARATOR,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context, ContextService
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.theme_service import SYSTEM, ThemeService, choice_for
from dplanner.modules.appearance.settings_page import build_page
from dplanner.theme.providers import ThemeProvider
from dplanner.theme.themes import Theme

MODULE_ID = "appearance"
THEME_MENU = "Theme"
NO_DESKTOP = "System theme — no desktop theme to follow on this machine"


def theme_title(theme: Theme) -> str:
    """``tokyo-night`` reads *Tokyo Night* — Omarchy's own rule for a theme's name."""
    return theme.name.replace("-", " ").title()


@dataclass(frozen=True)
class AppearanceDeps:
    actions: ActionRegistry
    context: ContextService
    theme: ThemeService
    settings_sections: SettingsSectionRegistry


class AppearanceModule:
    id = MODULE_ID

    def __init__(self, deps: AppearanceDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        theme = deps.theme
        # A theme change, or a provider switched, is a context change: every check mark
        # and every entry's presence is restated.
        theme.changed.connect(lambda _theme: deps.context.refresh())
        theme.offer_changed.connect(deps.context.refresh)

        def system_state(_context: Context) -> ActionState:
            if theme.system_provider() is None:
                return ActionState(enabled=False, label=NO_DESKTOP)
            return ActionState(checked=theme.effective_choice == SYSTEM)

        deps.actions.register(
            ActionSpec(
                id=f"{MODULE_ID}.theme.system",
                label="&System theme",
                menu="View",
                group="theme_system",
                order=10,
                submenu=THEME_MENU,
                tip="Follow the desktop's theme as it changes",
                state=system_state,
                run=lambda _context: theme.set_theme(SYSTEM),
            )
        )
        for index, provider in enumerate(theme.providers):
            offset = 0
            for group in provider.groups():
                submenu = THEME_MENU
                if group.title is not None:
                    submenu = THEME_MENU + PATH_SEPARATOR + group.title
                for entry in group.themes:
                    self._register_theme(provider, entry, submenu, order=100 * index + offset)
                    offset += 1

        deps.settings_sections.register(
            SettingsSection(
                id=f"{MODULE_ID}.providers",
                category=("Appearance",),
                factory=lambda parent: build_page(parent, theme=theme),
            )
        )

    def _register_theme(
        self, provider: ThemeProvider, entry: Theme, submenu: str, order: int
    ) -> None:
        deps = self._deps
        theme = deps.theme
        choice = choice_for(provider, entry)
        title = theme_title(entry)

        def state(_context: Context) -> ActionState:
            if not theme.offered(provider):
                return ActionState(visible=False, enabled=False)
            return ActionState(checked=theme.effective_choice == choice)

        deps.actions.register(
            ActionSpec(
                id=f"{MODULE_ID}.theme.{provider.id}.{entry.name}",
                label=title,
                menu="View",
                group="theme",
                order=order,
                submenu=submenu,
                tip=f"Switch to the {title} theme",
                state=state,
                run=lambda _context: theme.set_theme(choice),
            )
        )
