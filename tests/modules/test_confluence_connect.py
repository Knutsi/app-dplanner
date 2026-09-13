"""The Confluence module's Qt half over an injected secret store: the Connect dialog
proves the credentials before it lets them be stored, status reads a preference and
never the keychain, and the token is read only when a fetch needs it."""

import time
from dataclasses import dataclass, field

import pytest

from dplanner.domain.document_source import Snapshot, SourceStatus, SourceUnavailableError
from dplanner.framework.dialog import LinePrompt
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
    assert "Both" in made.status.words() and probes == []
    made.email.setText("me@acme.example")
    made.token.setText("tok")
    made.test_button.click()
    wait_for(app, lambda: made.passed)
    assert made.ok.isEnabled() and "Auth Overview" in made.status.words()
    assert made.status.tone() == "ok"
    assert probes == [Credentials("me@acme.example", "tok")]
    made.token.setText("tok2")  # A change after the test: prove it again.
    assert not made.ok.isEnabled() and not made.passed
    assert made.status.words() == "Test the connection first"


def test_a_failing_test_keeps_connect_disabled_and_says_why(app, dialog):
    made, _probes = dialog
    made.email.setText("me@acme.example")
    made.token.setText("bad")
    made.test_button.click()
    wait_for(app, lambda: made.test_button.isEnabled() and made.status.tone() != "busy")
    assert made.status.words() == "acme rejected the token" and not made.ok.isEnabled()
    assert made.status.tone() == "error"


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
        assert "no keychain service" in made.status.words()
        assert not made.test_button.isEnabled() and not made.ok.isEnabled()
    finally:
        made.deleteLater()


# -- the two kinds over one module --------------------------------------------------------------


def test_status_reads_the_connected_sites_and_never_the_keychain(confluence, secrets):
    page = confluence.page
    assert page.status(LOCATOR) == SourceStatus(False, "Not connected to acme.atlassian.net")
    assert not page.status({"site": "https://evil.example", "id": "1", "type": "page"}).ready
    set_global(MODULE_ID, module_mod.SITES_KEY, {SITE: "me@acme.example"})
    assert page.status(LOCATOR).ready
    assert secrets.reads == 0


def test_a_kind_is_not_ready_for_the_other_kinds_locator(confluence):
    set_global(MODULE_ID, module_mod.SITES_KEY, {SITE: "me@acme.example"})
    refused = confluence.folder.status(LOCATOR)
    assert not refused.ready and refused.message.endswith("not a Confluence folder")
    assert confluence.page.status(LOCATOR).ready


def test_one_connection_serves_both_kinds(confluence):
    """A site is connected, not a kind: both share the module's one config_changed."""
    heard = []
    confluence.page.config_changed.connect(lambda: heard.append("page"))
    confluence.folder.config_changed.connect(lambda: heard.append("folder"))
    confluence.forget(SITE)
    assert heard == ["page", "folder"]
    assert confluence.page.id == "confluence_page" and confluence.folder.id == "confluence_folder"


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
    assert confluence.page.connect(services.window, LOCATOR)
    assert secrets.stored == {(MODULE_ID, "token:acme.atlassian.net"): "tok"}
    assert get_global(MODULE_ID, module_mod.SITES_KEY) == {SITE: "me@acme.example"}
    assert "tok" not in str(get_global(MODULE_ID, module_mod.SITES_KEY))
    assert changes == [True] and confluence.page.status(LOCATOR).ready
    assert confluence.sites() == {SITE: "me@acme.example"}

    confluence.forget(SITE)
    assert secrets.stored == {} and confluence.sites() == {} and changes == [True, True]


def test_a_cancelled_dialog_stores_nothing(confluence, secrets, services, monkeypatch):
    monkeypatch.setattr(ConnectDialog, "exec", lambda self: ConnectDialog.DialogCode.Rejected)
    assert not confluence.page.connect(services.window, LOCATOR)
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
        confluence.page.fetch(LOCATOR, {}, lambda _f: None, lambda: False)
    assert refused.value.needs_reconnect and "no token" in str(refused.value)
    set_global(MODULE_ID, module_mod.SITES_KEY, {SITE: "me@acme.example"})
    secrets.stored[(MODULE_ID, "token:acme.atlassian.net")] = "tok"
    confluence.page.fetch(LOCATOR, {}, lambda _f: None, lambda: False)
    assert seen == [(SITE, Credentials("me@acme.example", "tok"), LOCATOR)]
    with pytest.raises(SourceUnavailableError):
        confluence.page.fetch(
            {"site": "https://evil.example", "id": "1", "type": "page"},
            {},
            lambda _f: None,
            lambda: False,
        )


def test_locate_asks_for_an_address_on_the_frame_and_refuses_what_is_not_one(
    confluence, services, monkeypatch
):
    """The prompt refuses as the address is typed, under the field — never after the fact."""
    typed: list[str] = []

    def answer(self):
        prompts.append(self)
        self.field.setText(typed.pop(0))
        return LinePrompt.DialogCode.Accepted

    prompts: list[LinePrompt] = []
    monkeypatch.setattr(LinePrompt, "exec", answer)

    def refused() -> bool:
        primary = prompts[-1].primary()
        return primary is not None and not primary.isEnabled()

    typed.append("https://acme.atlassian.net/wiki/x/short")
    assert confluence.page.locate(services.window) is None
    assert "short link" in prompts[-1].problem.words()
    assert refused()

    typed.append("https://acme.atlassian.net/wiki/spaces/E/pages/7/Auth")
    assert confluence.page.locate(services.window) == (
        "Auth",
        {"site": SITE, "id": "7", "type": "page", "space": "E"},
    )
    assert prompts[-1].problem.words() == "" and not refused()

    typed.append("https://acme.atlassian.net/wiki/spaces/E/pages/7/Auth")
    assert confluence.folder.locate(services.window) is None
    assert "Confluence Page" in prompts[-1].problem.words()

    monkeypatch.setattr(LinePrompt, "exec", lambda self: LinePrompt.DialogCode.Rejected)
    assert confluence.page.locate(services.window) is None


def test_each_kind_opens_its_own_address(confluence):
    assert confluence.page.open_url(LOCATOR) == f"{SITE}/wiki/pages/viewpage.action?pageId=12345"
    folder = {"site": SITE, "id": "5", "type": "folder", "space": "ENG"}
    assert confluence.folder.open_url(folder).endswith("/spaces/ENG/folder/5")
    assert confluence.page.open_url(folder) == ""
    assert (
        confluence.page.open_url({"site": "https://evil.example", "id": "5", "type": "page"}) == ""
    )


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


def test_the_real_build_registers_both_kinds_and_the_settings(services):
    assert any(section.id == MODULE_ID for section in services.settings_sections.sections())
    assert services.actions.spec("spec.add_source.confluence_page").label == "&Confluence Page…"
    assert services.actions.spec("spec.add_source.confluence_folder").label == "Confluence F&older…"
