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

**Milestone Colours is the odd one, and deliberately beside Theme rather than inside it.**
What it picks is the *project's* colour map — the one ``dplanner schedule palette`` and the
Time tab's picker already write, pushed through the same undoable command — so it is one
choice with three ways in rather than a fourth place a colour could come from, and the
published report can never disagree with the window. It is not a theme and must not read as
one, which is why it is a sibling child menu; and because it acts on a project it is greyed
with its reason when none is open, never hidden. ARCHITECTURE.md's *Colour is a place on one
map* has the reasoning.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

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
from dplanner.theme.icons import palette_strip_icon
from dplanner.theme.palettes import PALETTES, Palette
from dplanner.theme.providers import ThemeProvider
from dplanner.theme.themes import Theme

MODULE_ID = "appearance"
THEME_MENU = "Theme"
MILESTONE_MENU = "Milestone Colours"
NO_DESKTOP = "System theme — no desktop theme to follow on this machine"
NO_PROJECT = "Milestone colours — open a project to choose its colour map"


def theme_title(theme: Theme) -> str:
    """``tokyo-night`` reads *Tokyo Night* — Omarchy's own rule for a theme's name."""
    return theme.name.replace("-", " ").title()


def _no_palette(_project_id: str) -> str:
    """No colour map reaches this build; every entry is unchecked and harmless."""
    return ""


@dataclass(frozen=True)
class AppearanceDeps:
    actions: ActionRegistry
    context: ContextService
    theme: ThemeService
    settings_sections: SettingsSectionRegistry
    # The colour map a project's milestones are shaded from, and the undoable write that
    # changes it. Both from the composition root: which map a project uses is the time
    # estimates module's stored assumption, and this module never learns that.
    milestone_palette: Callable[[str], str] = field(default=_no_palette)
    set_milestone_palette: Callable[[str, str], None] = field(default=lambda _p, _m: None)
    # Told when a project's stored map changes under the window — a terminal's `schedule
    # palette`, the Time tab's picker, an undo — so the tick follows. None never subscribes.
    watch_palette: Callable[[Callable[[], None]], None] | None = None


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

        self._register_milestone_colors()

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

    def _register_milestone_colors(self) -> None:
        """*View ▸ Milestone Colours*: the project's colour map, one entry per map.

        One choice of several, so exactly one entry is ticked — the Theme menu's own shape.
        The strip icon is the picker's, painted fresh on every open like every pop-up glyph
        (a colour baked into a long-lived QAction goes stale on a theme change).
        """
        deps = self._deps
        if deps.watch_palette is not None:
            deps.watch_palette(deps.context.refresh)
        for order, found in enumerate(PALETTES, start=1):
            self._register_palette(found, order=10 * order)

    def _register_palette(self, found: Palette, order: int) -> None:
        deps = self._deps

        def state(context: Context) -> ActionState:
            project_id = context.focus_entity("project")
            if project_id is None:
                return ActionState(enabled=False, label=NO_PROJECT)
            return ActionState(checked=deps.milestone_palette(project_id) == found.id)

        def run(context: Context) -> None:
            project_id = context.focus_entity("project")
            if project_id is not None:
                deps.set_milestone_palette(project_id, found.id)

        deps.actions.register(
            ActionSpec(
                id=f"{MODULE_ID}.milestones.{found.id}",
                label=found.name,
                menu="View",
                group="milestone_colors",
                order=order,
                submenu=MILESTONE_MENU,
                tip=f"Shade this project's milestones along {found.name}",
                icon=lambda _ink, found=found: palette_strip_icon(found),  # type: ignore[misc]
                state=state,
                run=run,
            )
        )
