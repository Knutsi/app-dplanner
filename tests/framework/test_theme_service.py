"""ThemeService: a choice resolved over the providers, followed from the desktop by a poll,
and persisted only when a person chose."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QSettings

from dplanner.framework.theme_service import (
    DEFAULT_CHOICE,
    SETTINGS_KEY,
    SYSTEM,
    ThemeService,
    providers_off,
    resolve,
)
from dplanner.theme import apply_theme
from dplanner.theme.providers import BUILTIN, ThemeGroup, ThemeProvider
from dplanner.theme.themes import DARK, DEFAULT, LIGHT, SEPIA, Theme

ROSE = replace(LIGHT, name="rose", bg_base="#fff0f5")
INK = replace(DARK, name="ink", bg_base="#000000")


def fixed(provider_id: str, *themes: Theme) -> ThemeProvider:
    return ThemeProvider(
        provider_id, provider_id.title(), groups=lambda: (ThemeGroup(None, themes),)
    )


def following(
    provider_id: str, readings: list[Theme | None], refusal: str | None = None
) -> ThemeProvider:
    """A desktop whose current theme is ``readings[0]`` — mutate the list to change it."""
    return ThemeProvider(
        provider_id, provider_id.title(), refusal=lambda: refusal, current=lambda: readings[0]
    )


@pytest.fixture(autouse=True)
def restore_theme(app):
    yield
    apply_theme(app, DEFAULT)


def window_color(app) -> str:
    return str(app.palette().window().color().name())


def outcome(choice: str, usable: list[ThemeProvider]) -> tuple[Theme, ThemeProvider | None, str]:
    resolved = resolve(choice, usable)
    return resolved.theme, resolved.following, resolved.choice


# -- resolving ---------------------------------------------------------------------------------


def test_resolve_reads_every_spelling_and_falls_back_to_the_default():
    assert outcome("", [BUILTIN]) == (
        DEFAULT,
        None,
        DEFAULT_CHOICE,
    )  # Absence is system; nothing follows.
    assert outcome(SYSTEM, [BUILTIN]) == (DEFAULT, None, DEFAULT_CHOICE)
    assert outcome("light", [BUILTIN]) == (LIGHT, None, "builtin/light")  # A legacy bare name.
    assert outcome("builtin/sepia", [BUILTIN]) == (SEPIA, None, "builtin/sepia")
    assert outcome("builtin/nonesuch", [BUILTIN]) == (DEFAULT, None, DEFAULT_CHOICE)
    assert outcome("omarchy/rose", [BUILTIN]) == (DEFAULT, None, DEFAULT_CHOICE)
    rose = fixed("omarchy", ROSE)
    assert outcome("omarchy/rose", [BUILTIN, rose]) == (ROSE, None, "omarchy/rose")


def test_system_is_served_by_the_first_following_provider_that_is_usable():
    first, second = following("first", [ROSE]), following("second", [INK])
    assert outcome(SYSTEM, [BUILTIN, first, second]) == (ROSE, first, SYSTEM)
    # Mid-switch the reading is None: the default stands in, the provider is still followed.
    blank = following("blank", [None])
    assert outcome(SYSTEM, [blank]) == (DEFAULT, blank, SYSTEM)


# -- choosing ----------------------------------------------------------------------------------


def test_set_theme_applies_persists_and_announces_once(app):
    service = ThemeService(app, (BUILTIN,))
    seen: list[Theme] = []
    service.changed.connect(seen.append)

    service.set_theme("light")
    assert window_color(app) == LIGHT.bg_base
    assert QSettings().value(SETTINGS_KEY) == "builtin/light"
    assert service.effective_choice == "builtin/light" and service.current is LIGHT
    service.set_theme("builtin/light")
    assert seen == [LIGHT]


def test_a_choice_the_machine_cannot_honour_is_kept_not_overwritten(app):
    """A profile carried from the Omarchy box to a Mac falls back for this run and is still
    itself when it comes home."""
    QSettings().setValue(SETTINGS_KEY, "omarchy/rose")
    service = ThemeService(app, (BUILTIN,))
    assert service.current is DEFAULT and service.effective_choice == DEFAULT_CHOICE
    assert service.choice == "omarchy/rose"
    assert QSettings().value(SETTINGS_KEY) == "omarchy/rose"


def test_a_legacy_bare_name_is_read_as_the_builtins(app):
    QSettings().setValue(SETTINGS_KEY, "sepia")
    service = ThemeService(app, (BUILTIN,))
    assert service.current is SEPIA and service.effective_choice == "builtin/sepia"


# -- following ---------------------------------------------------------------------------------


def test_absence_means_system_and_the_desktop_serves_it(app):
    readings: list[Theme | None] = [ROSE]
    service = ThemeService(app, (following("desk", readings), BUILTIN))
    assert service.follows and service.polling()
    assert service.current == ROSE and service.effective_choice == SYSTEM
    assert QSettings().value(SETTINGS_KEY, "") == ""  # Never chosen, never written.
    assert service.system_provider() is service.providers[0]


def test_the_poll_applies_a_changed_reading_and_ignores_none_or_the_same(app):
    readings: list[Theme | None] = [ROSE]
    service = ThemeService(app, (following("desk", readings), BUILTIN))
    service.set_theme(SYSTEM)
    seen: list[Theme] = []
    service.changed.connect(seen.append)

    readings[0] = INK
    service.check()
    assert window_color(app) == INK.bg_base and seen == [INK]
    readings[0] = None  # Omarchy between removing the theme directory and moving the next in.
    service.check()
    readings[0] = replace(INK)  # The same theme, rebuilt on read.
    service.check()
    assert seen == [INK]


def test_the_poll_runs_only_while_following(app):
    service = ThemeService(app, (following("desk", [ROSE]), BUILTIN))
    assert service.polling()
    service.set_theme("dark")
    assert not service.polling() and not service.follows
    service.set_theme(SYSTEM)
    assert service.polling() and service.effective_choice == SYSTEM


def test_following_holds_no_colour_scheme_override(app, monkeypatch):
    """The reading a desktop provider makes must be the platform's, not the application's
    own: ``set_theme("system")`` clears the override before it asks, and while following
    none is set again. Observed as calls: the headless platform theme answers ``Unknown``
    whatever is set, so Qt's own reading cannot be the witness here."""
    hints = app.styleHints()
    calls: list[str] = []
    monkeypatch.setattr(hints, "unsetColorScheme", lambda: calls.append("unset"))
    monkeypatch.setattr(hints, "setColorScheme", lambda scheme: calls.append(f"set {scheme.name}"))

    def read() -> Theme:
        calls.append("read")
        return DARK

    service = ThemeService(app, (ThemeProvider("desk", "Desk", current=read), BUILTIN))
    calls.clear()

    service.set_theme("light")
    assert calls == ["set Light"]
    calls.clear()
    service.set_theme(SYSTEM)
    assert calls == ["unset", "read", "unset"]


# -- switching a provider off ------------------------------------------------------------------


def test_a_switched_off_provider_is_skipped_and_the_choice_is_re_read(app):
    desk = following("desk", [ROSE])
    service = ThemeService(app, (desk, BUILTIN))
    assert service.offered(desk) and service.polling()

    service.set_enabled("desk", False)
    assert not service.enabled(desk) and not service.offered(desk)
    assert not service.follows
    assert service.current is DEFAULT and service.effective_choice == DEFAULT_CHOICE
    assert providers_off() == {"desk"}
    assert service.system_provider() is None

    service.set_enabled("desk", True)
    assert service.system_provider() is desk and service.current == ROSE


def test_a_refused_provider_is_never_served(app):
    away = following("away", [ROSE], refusal="Not on this machine")
    service = ThemeService(app, (away, BUILTIN))
    assert service.refusal(away) == "Not on this machine" and not service.offered(away)
    assert service.enabled(away)  # Switched on, just not here.
    assert service.system_provider() is None and service.current is DEFAULT
