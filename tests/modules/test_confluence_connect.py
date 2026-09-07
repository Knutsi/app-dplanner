"""The Confluence module's Qt half over an injected secret store: the Connect dialog
proves the credentials before it lets them be stored, status reads a preference and
never the keychain, and the token is read only when a fetch needs it."""

import time
from dataclasses import dataclass, field

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from dplanner.domain.document_source import Snapshot, SourceStatus, SourceUnavailableError
from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.spec_confluence import module as module_mod
from dplanner.modules.spec_confluence.client import Credentials
from dplanner.modules.spec_confluence.connect import TOKENS_URL, ConnectDialog
from dplanner.modules.spec_confluence.module import (
    MODULE_ID,
    SpecConfluenceDeps,
    SpecConfluenceModule,
)

SITE = "https://acme.atlassian.net"
LOCATOR = {"site": SITE, "id": "12345", "type": "page"}


@dataclass
class FakeSecrets:
    stored: dict[tuple[str, str], str] = field(default_factory=dict)
    reads: int = 0
    trouble: str | None = None

    def get(self, module_id, key):
        self.reads += 1
        return self.stored.get((module_id, key))

    def set(self, module_id, key, value):
        self.stored[(module_id, key)] = value

    def delete(self, module_id, key):
        self.stored.pop((module_id, key), None)

    def problem(self):
        return self.trouble


def wait_for(app, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the worker never delivered"
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def secrets():
    return FakeSecrets()


@pytest.fixture
def opened_urls():
    return []


@pytest.fixture
def confluence(services, secrets, opened_urls):
    return SpecConfluenceModule(
        SpecConfluenceDeps(
            parent=services.window,
            tasks=services.tasks,
            settings_sections=services.settings_sections,
            secrets=secrets,
            open_url=opened_urls.append,
        )
    )


@pytest.fixture
def dialog(app, services, opened_urls):
    probes = []

    def probe(credentials):
        probes.append(credentials)
        if credentials.token == "bad":
            raise SourceUnavailableError("acme rejected the token", needs_reconnect=True)
        return "Auth Overview"

    made = ConnectDialog(
        services.window,
        SITE,
        tasks=services.tasks,
        probe=probe,
        open_url=opened_urls.append,
        backend_problem=None,
    )
    yield made, probes
    made.deleteLater()


# -- the dialog -----------------------------------------------------------------------------


def test_connect_is_disabled_until_a_test_passes_and_again_after_an_edit(app, dialog):
    made, probes = dialog
    assert not made.ok.isEnabled()
    made.test_button.click()
    assert "Both" in made.status.text() and probes == []
    made.email.setText("me@acme.example")
    made.token.setText("tok")
    made.test_button.click()
    wait_for(app, lambda: made.passed)
    assert made.ok.isEnabled() and "Auth Overview" in made.status.text()
    assert probes == [Credentials("me@acme.example", "tok")]
    made.token.setText("tok2")  # A change after the test: prove it again.
    assert not made.ok.isEnabled() and not made.passed


def test_a_failing_test_keeps_connect_disabled_and_says_why(app, dialog):
    made, _probes = dialog
    made.email.setText("me@acme.example")
    made.token.setText("bad")
    made.test_button.click()
    wait_for(app, lambda: made.test_button.isEnabled() and made.status.text() != "Testing…")
    assert made.status.text() == "acme rejected the token" and not made.ok.isEnabled()


def test_the_token_page_opens_through_the_seam(dialog, opened_urls):
    made, _probes = dialog
    made.open_tokens.click()
    assert opened_urls == [TOKENS_URL]


def test_a_keychain_problem_refuses_up_front(services):
    made = ConnectDialog(
        services.window,
        SITE,
        tasks=services.tasks,
        probe=lambda _c: "x",
        open_url=lambda _u: None,
        backend_problem="no keychain service is running",
    )
    try:
        assert "no keychain service" in made.status.text()
        assert not made.test_button.isEnabled() and not made.ok.isEnabled()
    finally:
        made.deleteLater()


# -- the module as a kind -----------------------------------------------------------------------


def test_status_reads_the_connected_sites_and_never_the_keychain(confluence, secrets):
    assert confluence.status(LOCATOR) == SourceStatus(False, "Not connected to acme.atlassian.net")
    assert not confluence.status({"site": "https://evil.example", "id": "1", "type": "page"}).ready
    set_global(MODULE_ID, module_mod.SITES_KEY, {SITE: "me@acme.example"})
    assert confluence.status(LOCATOR).ready
    assert secrets.reads == 0


def test_connect_stores_the_token_in_the_secret_store_and_the_email_in_settings(
    confluence, secrets, services, monkeypatch
):
    def accept(self):
        self.email.setText("me@acme.example")
        self.token.setText("tok")
        self._passed = True
        return ConnectDialog.DialogCode.Accepted

    monkeypatch.setattr(ConnectDialog, "exec", accept)
    changes = []
    confluence.config_changed.connect(lambda: changes.append(True))
    assert confluence.connect(services.window, LOCATOR)
    assert secrets.stored == {(MODULE_ID, "token:acme.atlassian.net"): "tok"}
    assert get_global(MODULE_ID, module_mod.SITES_KEY) == {SITE: "me@acme.example"}
    assert "tok" not in str(get_global(MODULE_ID, module_mod.SITES_KEY))
    assert changes == [True] and confluence.status(LOCATOR).ready
    assert confluence.sites() == {SITE: "me@acme.example"}

    confluence.forget(SITE)
    assert secrets.stored == {} and confluence.sites() == {} and changes == [True, True]


def test_a_cancelled_dialog_stores_nothing(confluence, secrets, services, monkeypatch):
    monkeypatch.setattr(ConnectDialog, "exec", lambda self: ConnectDialog.DialogCode.Rejected)
    assert not confluence.connect(services.window, LOCATOR)
    assert secrets.stored == {} and confluence.sites() == {}


def test_a_fetch_reads_the_token_only_then_and_refuses_without_one(
    confluence, secrets, monkeypatch
):
    seen = []

    def fake_fetch(client, locator, known, progress, cancelled):
        seen.append((client.site, client._credentials, dict(locator)))
        return Snapshot(documents=())

    monkeypatch.setattr(module_mod, "fetch", fake_fetch)
    with pytest.raises(SourceUnavailableError) as refused:
        confluence.fetch(LOCATOR, {}, lambda _f: None, lambda: False)
    assert refused.value.needs_reconnect and "no token" in str(refused.value)
    set_global(MODULE_ID, module_mod.SITES_KEY, {SITE: "me@acme.example"})
    secrets.stored[(MODULE_ID, "token:acme.atlassian.net")] = "tok"
    confluence.fetch(LOCATOR, {}, lambda _f: None, lambda: False)
    assert seen == [(SITE, Credentials("me@acme.example", "tok"), LOCATOR)]
    with pytest.raises(SourceUnavailableError):
        confluence.fetch(
            {"site": "https://evil.example", "id": "1", "type": "page"},
            {},
            lambda _f: None,
            lambda: False,
        )


def test_locate_asks_for_an_address_and_refuses_what_is_not_one(confluence, services, monkeypatch):
    answers = iter(
        [
            ("https://acme.atlassian.net/wiki/x/short", True),
            ("https://acme.atlassian.net/wiki/spaces/E/pages/7/Auth", True),
        ]
    )
    warnings = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: next(answers))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    assert confluence.locate(services.window) == (
        "Auth",
        {"site": SITE, "id": "7", "type": "page", "space": "E"},
    )
    assert len(warnings) == 1 and "short link" in warnings[0]
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    assert confluence.locate(services.window) is None


def test_open_url_names_the_page_or_the_folder(confluence):
    assert confluence.open_url(LOCATOR) == f"{SITE}/wiki/pages/viewpage.action?pageId=12345"
    folder = {"site": SITE, "id": "5", "type": "folder", "space": "ENG"}
    assert confluence.open_url(folder).endswith("/spaces/ENG/folder/5")
    assert confluence.open_url({"site": "https://evil.example", "id": "5", "type": "page"}) == ""


def test_the_settings_page_lists_sites_and_forgets_one(confluence, services, secrets):
    from PySide6.QtWidgets import QPushButton

    from dplanner.modules.spec_confluence.settings_page import build_page

    set_global(MODULE_ID, module_mod.SITES_KEY, {SITE: "me@acme.example"})
    secrets.stored[(MODULE_ID, "token:acme.atlassian.net")] = "tok"
    page = build_page(
        None, sites=confluence.sites, reconnect=lambda *_a: False, forget=confluence.forget
    )
    try:
        forget = next(b for b in page.findChildren(QPushButton) if b.objectName() == "forgetSite")
        forget.click()
        assert confluence.sites() == {} and secrets.stored == {}
        assert not any(
            b.objectName() == "forgetSite" for b in page.findChildren(QPushButton) if b.isVisible()
        )
    finally:
        page.deleteLater()


def test_the_real_build_registers_the_kind_and_its_settings(services):
    assert any(section.id == MODULE_ID for section in services.settings_sections.sections())
    assert (
        services.actions.spec("spec.add_source.confluence").label == "&Confluence Page or Folder…"
    )
