"""Which theme is current: chosen from what the providers offer, or followed from the desktop.

The theme package stays a pure library (apply a given theme to an application); this
service owns *which* theme is current. A choice is persisted in ``QSettings`` under
``appearance/theme`` as ``"system"`` — follow the desktop — or ``"<provider>/<name>"``; a
bare name from before providers existed reads as the built-in's. **Absence means system**:
a fresh profile picks the right variant for its desktop by itself, and falls back to the
built-in default where no provider follows one. ``"system"`` names no provider on purpose —
it means *this machine's* desktop, served by the first following provider in the root's
order that applies here, so a profile keeps following when the desktop under it changes.
A choice naming nothing here resolves to the default for this run and is never written
back: a profile carried to another machine is still itself when it comes home.

Following is a poll: a ``QTimer`` at the workspace watcher's cadence re-reads the serving
provider's ``current()`` and applies it when it differs (never ``is`` — a provider rebuilds
its ``Theme`` on every read). One mechanism for every following provider: a file watch
would die with the directory Omarchy replaces, and Qt's ``colorSchemeChanged`` would hear
the application's own override. While following, ``apply_theme`` holds no override, so a
desktop provider reads the platform and never an echo; ``set_theme("system")`` clears the
override *before* asking, for the same reason.

Availability is asked once per build (``refusal()`` cached at construction) and never from
an action state; ``effective_choice`` is a field the service keeps, so a check mark costs a
comparison. The switched-off providers are a per-user preference (``user_config``).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QObject, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from dplanner.core.signals import Signal
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.window_watch import POLL_MS
from dplanner.theme import apply_theme
from dplanner.theme.providers import BUILTIN, ThemeProvider, provider_by_id
from dplanner.theme.themes import DEFAULT, Theme

SETTINGS_KEY = "appearance/theme"
SYSTEM = "system"
CONFIG_OWNER = "appearance"
OFF_KEY = "providers_off"


def choice_for(provider: ThemeProvider, theme: Theme) -> str:
    """The persisted spelling of one provider's theme."""
    return f"{provider.id}/{theme.name}"


DEFAULT_CHOICE = choice_for(BUILTIN, DEFAULT)  # What is honoured when nothing else can be.


def saved_choice() -> str:
    """The persisted choice; empty when this profile never chose."""
    return str(QSettings().value(SETTINGS_KEY, ""))


def providers_off() -> frozenset[str]:
    stored = get_global(CONFIG_OWNER, OFF_KEY, [])
    return frozenset(str(item) for item in stored) if isinstance(stored, list) else frozenset()


@dataclass(frozen=True)
class Resolved:
    theme: Theme
    following: ThemeProvider | None  # The provider serving "system", None for a fixed theme.
    choice: str  # What was honoured: SYSTEM or "<provider>/<name>" — the default's, standing in.


def resolve(choice: str, usable: Sequence[ThemeProvider]) -> Resolved:
    """What ``choice`` means over the providers that apply here and are switched on.

    Pure: nothing is applied and nothing is written. A following provider's ``current()``
    may answer None (Omarchy mid-switch); the default then stands in until the poll reads
    one, and the provider is still the one being followed.
    """
    if choice in ("", SYSTEM):
        following = next((provider for provider in usable if provider.follows), None)
        if following is None:
            return Resolved(DEFAULT, None, DEFAULT_CHOICE)
        theme = following.desktop()
        return Resolved(theme if theme is not None else DEFAULT, following, SYSTEM)
    provider_id, _, name = choice.rpartition("/")
    provider = provider_by_id(usable, provider_id or BUILTIN.id)
    theme = provider.theme(name) if provider is not None else None
    if provider is None or theme is None:
        return Resolved(DEFAULT, None, DEFAULT_CHOICE)
    return Resolved(theme, None, choice_for(provider, theme))


def usable_providers(providers: Sequence[ThemeProvider]) -> list[ThemeProvider]:
    """The providers that apply on this machine and are switched on — asked now."""
    off = providers_off()
    return [p for p in providers if p.id not in off and p.refusal() is None]


def apply_saved_theme(app: QApplication, providers: Sequence[ThemeProvider]) -> None:
    """Startup: the saved choice over these providers, before any window exists.

    Asks each provider's ``refusal()`` here, before the first ``apply_theme`` — the one
    moment a desktop provider's reading is certainly the platform's own.
    """
    resolved = resolve(saved_choice(), usable_providers(providers))
    apply_theme(app, resolved.theme, follow_system=resolved.following is not None)


class ThemeService:
    def __init__(
        self,
        app: QApplication,
        providers: Sequence[ThemeProvider] = (BUILTIN,),
        *,
        parent: QObject | None = None,
    ) -> None:
        self._app = app
        self.providers: tuple[ThemeProvider, ...] = tuple(providers)
        # A provider reports once per build whether it applies on this machine.
        self._refusals = {provider.id: provider.refusal() for provider in self.providers}
        self._off = set(providers_off())
        self.choice = saved_choice() or SYSTEM
        self.changed: Signal[Theme] = Signal()
        self.offer_changed: Signal[()] = Signal()  # A provider switched on or off.
        resolved = resolve(self.choice, self._usable())
        self.current: Theme = resolved.theme
        self.effective_choice: str = resolved.choice
        self._following = resolved.following
        # Parented to the window, like the workspace watcher: a discarded build takes the
        # timer with it, so no tick ever runs against a build that is gone.
        self._poll = QTimer(parent)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self.check)
        self._sync_poll()

    # -- what is offered ---------------------------------------------------------------------

    def refusal(self, provider: ThemeProvider) -> str | None:
        """Why ``provider`` does not apply on this machine, as asked at build time."""
        return self._refusals[provider.id]

    def enabled(self, provider: ThemeProvider) -> bool:
        return provider.id not in self._off

    def offered(self, provider: ThemeProvider) -> bool:
        """Applies here and switched on: what the Theme menu lists."""
        return self.enabled(provider) and self.refusal(provider) is None

    def system_provider(self) -> ThemeProvider | None:
        """The provider "System theme" is served by, or None where nothing follows."""
        return next((provider for provider in self._usable() if provider.follows), None)

    @property
    def follows(self) -> bool:
        return self._following is not None

    def polling(self) -> bool:
        return self._poll.isActive()

    # -- choosing ----------------------------------------------------------------------------

    def set_theme(self, choice: str) -> None:
        """Pick by choice: ``"system"``, ``"<provider>/<name>"``, or a bare built-in name."""
        if choice == SYSTEM:
            # Cleared before the desktop is asked, or a desktop provider would read the
            # application's own override rather than the platform.
            self._clear_scheme_override()
        else:
            provider_id, _, name = choice.rpartition("/")
            choice = f"{provider_id or BUILTIN.id}/{name}"
        self.choice = choice
        QSettings().setValue(SETTINGS_KEY, choice)
        self._take(resolve(choice, self._usable()))

    def set_enabled(self, provider_id: str, on: bool) -> None:
        """Switch a provider on or off for this user; the choice is re-read over the rest."""
        if on:
            self._off.discard(provider_id)
        else:
            self._off.add(provider_id)
        set_global(CONFIG_OWNER, OFF_KEY, sorted(self._off))
        self._take(resolve(self.choice, self._usable()))
        self.offer_changed.emit()

    def check(self) -> None:
        """The poll: re-read the desktop's theme while following, apply it when it differs."""
        if self._following is None:
            return
        theme = self._following.desktop()
        if theme is None or theme == self.current:
            return
        self.current = theme
        apply_theme(self._app, theme, follow_system=True)
        self.changed.emit(theme)

    # -- mechanics ---------------------------------------------------------------------------

    def _usable(self) -> list[ThemeProvider]:
        return [provider for provider in self.providers if self.offered(provider)]

    def _take(self, resolved: Resolved) -> None:
        was_following = self._following is not None
        self._following = resolved.following
        self.effective_choice = resolved.choice
        self._sync_poll()
        follow = resolved.following is not None
        if resolved.theme == self.current and follow == was_following:
            return
        self.current = resolved.theme
        apply_theme(self._app, self.current, follow_system=follow)
        self.changed.emit(self.current)

    def _sync_poll(self) -> None:
        if self._following is not None:
            self._poll.start()
        else:
            self._poll.stop()

    def _clear_scheme_override(self) -> None:
        hints = self._app.styleHints()
        if hasattr(hints, "unsetColorScheme"):
            hints.unsetColorScheme()
