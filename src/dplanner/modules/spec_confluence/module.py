"""The Confluence module's Qt half: it owns *two* of the spec module's document source
kinds — a Confluence page and a Confluence folder — and registers Settings ▸ Confluence.

A kind is a :class:`~dplanner.modules.spec_confluence.source.ContentType` and the
Protocol's methods over this module's doors; the client, the credential, the Connect
dialog and the settings page are the module's and are shared by both, because connecting
to a site serves whichever of the two a source is. One ``config_changed`` for the same
reason.

Credentials are the person's, per site, per machine: the email in ``user_config``
(which is also the fact that a site is *connected* — what ``status`` reads, on every
context change, without a keychain round trip), the token in the OS keychain through the
secret store the composition root hands in. The token is read only inside ``fetch``,
``check`` and the Connect dialog's probe, and it is handed to the client as a value;
nothing in ``client.py`` or ``source.py`` knows where it came from.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QWidget

from dplanner.core.signals import Signal
from dplanner.domain.document_source import (
    Freshness,
    Locator,
    Snapshot,
    SourceStatus,
    SourceUnavailableError,
)
from dplanner.framework.dialog import LinePrompt
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.tasks import TaskService
from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.spec_confluence.client import ConfluenceClient, Credentials
from dplanner.modules.spec_confluence.connect import ConnectDialog
from dplanner.modules.spec_confluence.settings_page import build_page
from dplanner.modules.spec_confluence.source import (
    FOLDER,
    PAGE,
    ContentType,
    check,
    fetch,
    folder_url,
    page_url,
    parse_url,
    probe_access,
    valid_locator,
)
from dplanner.theme.icons import layers_icon

MODULE_ID = "spec_confluence"
SITES_KEY = "sites"  # user_config: {site origin: email} — the connected sites.


class SecretStore(Protocol):
    """The keychain, as four callables — wired from ``core/secrets`` by the
    composition root, handed as a dict by a test, so no test ever touches a real one."""

    def get(self, module_id: str, key: str) -> str | None: ...
    def set(self, module_id: str, key: str, value: str) -> None: ...
    def delete(self, module_id: str, key: str) -> None: ...
    def problem(self) -> str | None: ...


@dataclass(frozen=True)
class SpecConfluenceDeps:
    parent: QWidget
    tasks: TaskService
    settings_sections: SettingsSectionRegistry
    secrets: SecretStore
    open_url: Callable[[str], None]


class ConfluenceKind:
    """One of the two Confluence source kinds — satisfies
    :class:`dplanner.modules.spec.source_kind.DocumentSourceKind`.

    Constructed twice by the module, which is what holds the credential and the client; a
    kind adds its content type to every call and nothing else.
    """

    name = "Confluence"  # The prose noun: "from Confluence", "Refresh Confluence".

    def __init__(self, module: "SpecConfluenceModule", content: ContentType) -> None:
        self._module = module
        self._content = content
        self.id = content.kind_id
        self.label = content.label
        self.config_changed = module.config_changed

    @staticmethod
    def icon(color: str | QColor) -> QIcon:
        return layers_icon(color)

    def locate(self, parent: QWidget) -> tuple[str, Locator] | None:
        content = self._content
        text = LinePrompt.ask(
            parent,
            content.title,
            content.caption,
            "Add",
            placeholder=content.placeholder,
            validate=lambda value: _refusal(value, content.type),
        )
        if text is None:
            return None
        try:
            return parse_url(text, content.type)
        except ValueError:  # The prompt refuses what cannot be read; this is belt.
            return None

    def status(self, locator: Locator) -> SourceStatus:
        valid = self._valid(locator)
        if valid is None:
            return SourceStatus(False, f"this source's address is not a Confluence {self._noun}")
        if valid["site"] in self._module.sites():
            return SourceStatus(True)
        return SourceStatus(False, f"Not connected to {_host(valid['site'])}", connectable=True)

    def connect(self, parent: QWidget, locator: Locator) -> bool:
        valid = self._valid(locator)
        if valid is None:
            return False
        return self._module.connect_site(
            parent, valid["site"], lambda creds: self._module.probe(valid, creds)
        )

    def open_url(self, locator: Locator) -> str:
        valid = self._valid(locator)
        if valid is None:
            return ""
        if valid["type"] == FOLDER.type:
            return folder_url(valid["site"], valid["id"], valid.get("space", ""))
        return page_url(valid["site"], valid["id"])

    def fetch(
        self,
        locator: Locator,
        known: Mapping[str, str],
        progress: Callable[[float], None],
        cancelled: Callable[[], bool],
    ) -> Snapshot:
        valid = self._demand(locator)
        return fetch(self._module.client(valid["site"]), valid, known, progress, cancelled)

    def check(self, locator: Locator, known: Mapping[str, str]) -> Freshness:
        valid = self._demand(locator)
        return check(self._module.client(valid["site"]), valid, known)

    # -- internals -----------------------------------------------------------------------------

    @property
    def _noun(self) -> str:
        return self._content.noun

    def _valid(self, locator: Locator) -> Locator | None:
        return valid_locator(locator, self._content.type)

    def _demand(self, locator: Locator) -> Locator:
        valid = self._valid(locator)
        if valid is None:
            raise SourceUnavailableError(f"this source's address is not a Confluence {self._noun}")
        return valid


class SpecConfluenceModule:
    """The credential, the client and the settings page — and the two kinds over them."""

    id = MODULE_ID

    def __init__(self, deps: SpecConfluenceDeps) -> None:
        self._deps = deps
        self.config_changed: Signal[()] = Signal("spec_confluence.config_changed")
        self.page = ConfluenceKind(self, PAGE)
        self.folder = ConfluenceKind(self, FOLDER)

    def register(self) -> None:
        self._deps.settings_sections.register(
            SettingsSection(
                id=MODULE_ID,
                category=("Confluence",),
                factory=lambda parent: build_page(
                    parent, sites=self.sites, reconnect=self._reconnect, forget=self.forget
                ),
            )
        )

    # -- the person's sites ----------------------------------------------------------------

    def sites(self) -> dict[str, str]:
        """Connected sites → the account email — the rows Settings ▸ Confluence shows."""
        value = get_global(MODULE_ID, SITES_KEY, {})
        if not isinstance(value, dict):
            return {}
        return {str(site): str(email) for site, email in value.items()}

    def forget(self, site: str) -> None:
        self._deps.secrets.delete(MODULE_ID, _token_key(site))
        remaining = self.sites()
        remaining.pop(site, None)
        set_global(MODULE_ID, SITES_KEY, remaining)
        self.config_changed.emit()

    def _reconnect(self, parent: QWidget, site: str) -> bool:
        return self.connect_site(parent, site, lambda creds: self._probe_site(site, creds))

    def connect_site(self, parent: QWidget, site: str, probe: Callable[[Credentials], str]) -> bool:
        dialog = ConnectDialog(
            parent,
            site,
            tasks=self._deps.tasks,
            probe=probe,
            open_url=self._deps.open_url,
            backend_problem=self._deps.secrets.problem(),
            email=self.sites().get(site, ""),
        )
        try:
            accepted = dialog.exec() == ConnectDialog.DialogCode.Accepted and dialog.passed
            if not accepted:
                return False
            credentials = dialog.credentials()
        finally:
            dialog.deleteLater()
        self._deps.secrets.set(MODULE_ID, _token_key(site), credentials.token)
        set_global(MODULE_ID, SITES_KEY, {**self.sites(), site: credentials.email})
        self.config_changed.emit()
        return True

    # -- the client, built where the token is read -------------------------------------------

    def client(self, site: str, credentials: Credentials | None = None) -> ConfluenceClient:
        if credentials is None:
            email = self.sites().get(site, "")
            token = self._deps.secrets.get(MODULE_ID, _token_key(site))
            if not email or not token:
                raise SourceUnavailableError(
                    f"no token is stored for {_host(site)} on this computer", needs_reconnect=True
                )
            credentials = Credentials(email=email, token=token)
        return ConfluenceClient(site, credentials)

    def probe(self, locator: Locator, credentials: Credentials) -> str:
        """What the credentials can read at ``locator`` — the Connect dialog's probe."""
        return probe_access(self.client(locator["site"], credentials), locator)

    def _probe_site(self, site: str, credentials: Credentials) -> str:
        return self.client(site, credentials).ping()


def _refusal(text: str, expected: str) -> str | None:
    """Why this address cannot be read as ``expected``, or None — the prompt's validator,
    so the reason appears under the field as it is typed."""
    try:
        parse_url(text, expected)
    except ValueError as error:
        return str(error)
    return None


def _token_key(site: str) -> str:
    return f"token:{_host(site)}"


def _host(site: str) -> str:
    return urlsplit(site).hostname or site
