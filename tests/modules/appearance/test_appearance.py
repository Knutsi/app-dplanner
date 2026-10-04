"""Appearance: the Theme child menu says what the providers offer, the settings page says
which apply here, and a window over a desktop of its own follows it."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QCheckBox, QLabel, QWidget

from dplanner.app import new_session
from dplanner.framework.list_rows import DETAIL_ROLE
from dplanner.framework.palette import CommandPalette
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.appearance.module import NO_DESKTOP
from dplanner.modules.appearance.settings_page import build_page
from dplanner.modules.theme_omarchy.themes import omarchy_provider
from dplanner.theme import apply_theme
from dplanner.theme.providers import BUILTIN, OMARCHY_THEMES, ThemeProvider
from dplanner.theme.themes import DARK, DEFAULT, Theme

TOKYO_NIGHT = """\
mode = "dark"
accent = "#7aa2f7"
selection = "#292e42"
background = "#1a1b26"
foreground = "#a9b1d6"
bright_foreground = "#c0caf5"
blue = "#7aa2f7"
magenta = "#ad8ee6"
"""

LATTE = """\
mode = "light"
accent = "#1e66f5"
selection = "#ccd0da"
background = "#eff1f5"
foreground = "#4c4f69"
bright_foreground = "#4c4f69"
blue = "#1e66f5"
magenta = "#ea76cb"
"""


def stage(directory: Path, text: str) -> None:
    directory.mkdir(parents=True)
    (directory / "colors.toml").write_text(text, encoding="utf-8")


def entries(menu):
    """The menu's shape: visible separators as "|", child menus as (title, [entries])."""
    rendered: list[object] = []
    for action in menu.actions():
        if not action.isVisible():
            continue
        if action.isSeparator():
            rendered.append("|")
        elif action.menu() is not None:
            rendered.append((action.text(), entries(action.menu())))
        else:
            rendered.append(action.text())
    return rendered


def theme_menu(services):
    view = next(a.menu() for a in services.window.menuBar().actions() if a.text() == "&View")
    return next(a.menu() for a in view.actions() if a.text() == "Theme")


def action(services, action_id: str):
    return services.window.dynamic_menubar.action(action_id)


def child[W: QWidget](parent: QWidget, kind: type[W], name: str) -> W:
    found = parent.findChild(kind, name)
    assert found is not None, name
    return found


@pytest.fixture(autouse=True)
def restore_theme(app):
    yield
    apply_theme(app, DEFAULT)


# -- the built-in alone: a test build -----------------------------------------------------------


def test_the_theme_menu_offers_system_first_then_every_providers_themes(services):
    shape = entries(theme_menu(services))
    assert shape[:5] == [NO_DESKTOP, "|", "Dark", "Light", "Sepia"]
    title, omarchy = shape[5]
    assert title == "Omarchy" and len(omarchy) == len(OMARCHY_THEMES)
    assert omarchy[0] == "Catppuccin" and "Tokyo Night" in omarchy
    assert not action(services, "appearance.theme.system").isEnabled()
    assert action(services, "appearance.theme.builtin.dark").isChecked()


def test_a_picked_theme_is_checked_and_the_palette_says_where_it_lives(services):
    services.actions.run("appearance.theme.builtin.tokyo-night", services.context.current())
    assert services.theme.current.name == "tokyo-night"
    assert action(services, "appearance.theme.builtin.tokyo-night").isChecked()
    assert not action(services, "appearance.theme.builtin.dark").isChecked()

    parent = QWidget()  # Kept alive: the palette is parented to it and dies with it.
    palette = CommandPalette(services.actions, services.context, parent)
    palette._refilter("tokyo")
    row = palette.list.item(0)
    assert row.text() == "Tokyo Night" and row.data(DETAIL_ROLE) == "View ▸ Theme ▸ Omarchy"


# -- a window over an Omarchy desktop ----------------------------------------------------------


@pytest.fixture
def desktop(tmp_path):
    state = tmp_path / "state"
    stage(state / "theme", TOKYO_NIGHT)
    (state / "theme.name").write_text("tokyo-night\n", encoding="utf-8")
    own = tmp_path / "own"
    stage(own / "aether", LATTE)
    return state, own


@pytest.fixture
def omarchy_session(app, library_file, desktop):
    """The whole application, built the way ``main`` builds it, over a desktop of its own."""
    state, own = desktop
    session = new_session((BUILTIN, omarchy_provider(state, own)))
    assert session.open_initial(library_file)
    assert session.services is not None
    session.services.debounce.set_immediate(True)
    yield session
    session.close()


def test_system_theme_is_served_and_the_persons_themes_are_listed(omarchy_session):
    services = omarchy_session.services
    shape = entries(theme_menu(services))
    assert shape[0] == "&System theme" and shape[-1] == ("Your Omarchy themes", ["Aether"])
    assert services.theme.follows and services.theme.current.name == "tokyo-night"
    assert action(services, "appearance.theme.system").isChecked()
    assert not action(services, "appearance.theme.builtin.dark").isChecked()


def test_a_desktop_switch_repaints_the_running_window(app, omarchy_session, desktop):
    """T101, headless: what ``omarchy-theme-set`` leaves behind, read at the next poll."""
    state, _own = desktop
    services = omarchy_session.services
    seen: list[Theme] = []
    services.theme.changed.connect(seen.append)

    (state / "theme" / "colors.toml").write_text(LATTE, encoding="utf-8")
    (state / "theme.name").write_text("catppuccin-latte\n", encoding="utf-8")
    services.theme.check()

    assert [theme.name for theme in seen] == ["catppuccin-latte"]
    assert app.palette().window().color().name() == "#eff1f5"
    assert action(services, "appearance.theme.system").isChecked()


def test_switching_a_provider_off_takes_its_entries_out_of_the_menu(omarchy_session):
    services = omarchy_session.services
    services.theme.set_enabled("omarchy", False)
    shape = entries(theme_menu(services))
    assert shape[0] == NO_DESKTOP
    assert not any(
        isinstance(entry, tuple) and entry[0] == "Your Omarchy themes" for entry in shape
    )
    assert services.theme.current is DEFAULT
    assert action(services, "appearance.theme.builtin.dark").isChecked()


# -- the settings page -------------------------------------------------------------------------


def test_the_settings_page_lists_every_provider_with_its_reason(app, desktop):
    state, own = desktop
    away = ThemeProvider(
        "away", "Elsewhere", refusal=lambda: "Not on this machine", current=lambda: DARK
    )
    theme = ThemeService(app, (BUILTIN, omarchy_provider(state, own), away))
    page = build_page(None, theme=theme)

    def note(provider_id: str) -> str:
        block = child(page, QWidget, f"ThemeProvider_{provider_id}")
        return child(block, QLabel, "InspectorNote").text()

    assert page.findChild(QCheckBox, "ThemeProviderBox_builtin") is None  # A line, not a box.
    assert note("builtin") == f"{len(BUILTIN.themes())} themes, always on"
    omarchy = child(page, QCheckBox, "ThemeProviderBox_omarchy")
    assert omarchy.isEnabled() and omarchy.isChecked()
    assert note("omarchy") == "follows the desktop, 1 theme"
    elsewhere = child(page, QCheckBox, "ThemeProviderBox_away")
    assert not elsewhere.isEnabled() and not elsewhere.isChecked()
    assert note("away") == "Not on this machine"

    omarchy.setChecked(False)
    assert not theme.enabled(theme.providers[1]) and theme.current is DEFAULT
    page.deleteLater()
