"""What a theme provider is: the contract every provider module fills, and the built-in one.

A provider is a record of facts and callables, the shape
:class:`dplanner.domain.agents.AgentHarness` set: an ``id`` the persisted choice carries, a
``label`` the settings page shows, ``refusal()`` — why it does not apply on this machine,
None when it does, asked once per build — ``groups()``, the themes it offers in the lists
the Theme menu shows them as, and for a provider that follows the desktop, ``current()``:
the desktop's theme now, None when it cannot be read just then. **Capabilities are derived,
never declared**: a provider follows the desktop exactly when it has a ``current``.

The built-in provider is the fallback every build has: the three house themes and every
theme Omarchy ships, on every platform. The provider modules (``modules/theme_omarchy/``,
``modules/theme_system/``) each export one from a Qt-free ``themes.py``; the composition
root's ``theme_providers()`` is the tuple, and the framework's ``ThemeService`` reads it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from dplanner.theme.omarchy import theme_from_colors
from dplanner.theme.omarchy_themes import OMARCHY_COLORS
from dplanner.theme.themes import DARK, LIGHT, SEPIA, Theme


@dataclass(frozen=True)
class ThemeGroup:
    title: str | None  # A child menu's name; None lists the themes flat.
    themes: tuple[Theme, ...]


def _no_refusal() -> str | None:
    return None


def _no_groups() -> tuple[ThemeGroup, ...]:
    return ()


@dataclass(frozen=True)
class ThemeProvider:
    id: str  # "omarchy" — what the persisted choice carries.
    label: str  # "Omarchy" — what the settings page says.
    # Why this provider does not apply on this machine, None when it does. Asked once per
    # build, before any theme is applied, never from an action state.
    refusal: Callable[[], str | None] = _no_refusal
    # The themes it offers, in the lists the Theme menu shows them as.
    groups: Callable[[], tuple[ThemeGroup, ...]] = _no_groups
    # The desktop's theme now, for a provider that follows one; None when it cannot be
    # read just then (Omarchy mid-switch), and the service keeps what it has.
    current: Callable[[], Theme | None] | None = None

    @property
    def follows(self) -> bool:
        return self.current is not None

    def desktop(self) -> Theme | None:
        """The desktop's theme now: None for a provider that follows none, or that cannot
        read it just then."""
        return self.current() if self.current is not None else None

    def themes(self) -> tuple[Theme, ...]:
        return tuple(theme for group in self.groups() for theme in group.themes)

    def theme(self, name: str) -> Theme | None:
        return next((theme for theme in self.themes() if theme.name == name), None)

    def capabilities(self) -> tuple[str, ...]:
        """The provider's abilities in words, for the settings page."""
        words = []
        if self.follows:
            words.append("follows the desktop")
        count = len(self.themes())
        if count:
            words.append(f"{count} theme{'s' if count != 1 else ''}")
        return tuple(words)


def provider_by_id(providers: Sequence[ThemeProvider], provider_id: str) -> ThemeProvider | None:
    return next((provider for provider in providers if provider.id == provider_id), None)


# Every theme Omarchy ships, on every platform: the generated table, mapped at import.
OMARCHY_THEMES: tuple[Theme, ...] = tuple(
    theme_from_colors(name, colors) for name, colors in OMARCHY_COLORS.items()
)

BUILTIN = ThemeProvider(
    id="builtin",
    label="Built-in",
    groups=lambda: (
        ThemeGroup(None, (DARK, LIGHT, SEPIA)),
        ThemeGroup("Omarchy", OMARCHY_THEMES),
    ),
)
