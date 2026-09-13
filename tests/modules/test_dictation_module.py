"""``modules/dictation``: the checklist rows, the action, and Settings ▸ Dictation over a
fake provider and the fake recorder."""

import sys
import time
from typing import Any

import pytest
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QPushButton, QWidget
from tests.framework.fake_recorder import wait_for
from tests.framework.test_dictation_service import HERE, QUIET, Batch, batch_provider, service

from dplanner.cli.checklist import GROUPS
from dplanner.domain.dictation import DictationProvider, Recorder
from dplanner.framework.signalling import StatusLine
from dplanner.modules.dictation import checks as dictation_checks
from dplanner.modules.dictation.checks import SETUP_ACTION
from dplanner.modules.dictation.module import SETTINGS_SECTION
from dplanner.modules.dictation.settings_page import AUTOMATIC, NOT_FOUND, build_page

FOUND = {"python-fake": "/usr/bin/x", "python-quiet": "/usr/bin/y", sys.executable: sys.executable}


def child(page: QWidget, kind: Any, name: str) -> Any:
    return next(w for w in page.findChildren(kind) if w.objectName() == name)


def caption_text(page: QWidget, holder: str) -> str:
    labels: list[QLabel] = child(page, QWidget, holder).findChildren(QLabel)
    return next(label.text() for label in labels if label.objectName() == "InspectorCaption")


# -- the checklist rows --------------------------------------------------------------------------


def test_the_provider_row_is_ok_when_any_provider_does_not_refuse():
    ready = batch_provider(provider_id="b")
    rows = dictation_checks.checks(
        providers=(batch_provider(refusal="not on PATH", provider_id="a"), ready), which=FOUND.get
    )
    provider_row = next(row for row in rows if row.id == "dictation.provider")

    reading = provider_row.probe()

    assert reading.ok and reading.detail == "Fake engine is ready"
    assert provider_row.group in GROUPS and not provider_row.required
    assert provider_row.remedy is not None
    assert (provider_row.remedy.action, provider_row.remedy.verb) == (SETUP_ACTION, "Set Up…")


def test_the_provider_row_advises_with_every_refusal_when_none_is_ready():
    rows = dictation_checks.checks(
        providers=(batch_provider(refusal="no key", provider_id="a"),), platform="darwin"
    )
    provider_row = next(row for row in rows if row.id == "dictation.provider")

    reading = provider_row.probe()

    assert not reading.ok and reading.detail == "Fake engine: no key"
    assert provider_row.remedy is not None and "Fn twice" in provider_row.remedy.words


def test_the_recorder_row_names_the_installed_recorder_or_the_ffmpeg_package():
    rows = dictation_checks.checks(providers=(), recorders=(QUIET, HERE), which=FOUND.get)
    recorder_row = next(row for row in rows if row.id == "dictation.recorder")
    assert recorder_row.probe() == recorder_row.probe()
    assert recorder_row.probe().ok and recorder_row.probe().detail == "Quiet recorder on PATH"

    missing = dictation_checks.checks(providers=(), recorders=(HERE,), which=lambda _n: None)
    row = next(one for one in missing if one.id == "dictation.recorder")
    assert not row.probe().ok and row.probe().detail == "none of python-fake on PATH"
    assert row.remedy is not None and row.remedy.packages[""] == "ffmpeg"


# -- the module in the real build ----------------------------------------------------------------


def test_set_up_dictation_is_registered_out_of_the_menus_and_opens_the_section(
    services, monkeypatch
):
    from dplanner.modules.settings.module import SettingsModule

    settings = next(m for m in services.modules if isinstance(m, SettingsModule))
    monkeypatch.setattr(settings.dialog, "show", lambda: None)
    spec = services.actions.spec(SETUP_ACTION)
    assert (spec.menu, spec.in_menus) == ("Tools", False)

    services.actions.run(SETUP_ACTION, services.context.current())

    current = settings.dialog._tree.currentItem()
    assert current is not None and current.text(0) == "Dictation"
    assert settings.dialog._pane.currentWidget() is settings.dialog._pages[SETTINGS_SECTION]


def test_the_real_build_lists_the_provider_pages_under_providers_and_the_key_actions(services):
    categories = {s.id: s.category for s in services.settings_sections.sections()}
    assert categories["llm.openai"] == ("Providers", "OpenAI")
    assert categories["llm.anthropic"] == ("Providers", "Anthropic")
    assert categories[SETTINGS_SECTION] == ("Dictation",)
    for action_id in ("openai.key", "anthropic.key"):
        assert not services.actions.spec(action_id).in_menus


def test_every_prose_editor_in_the_build_wears_a_microphone_greyed_with_the_build_reason(
    services, make_project
):
    from dplanner.framework.dictation import NO_PROVIDER
    from dplanner.framework.markdown_toolbar import MarkdownToolbar

    make_project("Discovery")
    strips = services.window.findChildren(MarkdownToolbar)
    assert strips, "no strip was built"
    for strip in strips:
        assert strip.dictation is not None
        assert not strip.dictation.action.isEnabled()
        assert NO_PROVIDER in strip.dictation.action.text()


# -- the settings page ---------------------------------------------------------------------------


@pytest.fixture
def page_over(app):
    pages: list[QWidget] = []

    def make(*providers, recorders=(HERE,), which=FOUND.get, platform="linux", ran=None):
        made = service(*providers, recorders=recorders, which=which, platform=platform)
        sink: list[str] = ran if ran is not None else []
        page = build_page(made, None, run_action=sink.append, platform=platform)
        pages.append(page)
        return page, made

    yield make
    for page in pages:
        page.deleteLater()


def test_picking_a_provider_prefills_its_default_and_stores_the_choice(page_over):
    first = batch_provider(provider_id="a", default="a --model x")
    second = DictationProvider(
        "b",
        "Other",
        "Model",
        "gpt-x",
        lambda _t: None,
        transcribe=Batch().transcribe,
        hint="A model.",
    )
    page, made = page_over(first, second)
    combo, edit = (
        child(page, QComboBox, "DictationProviderCombo"),
        child(page, QLineEdit, "DictationProviderEdit"),
    )

    assert combo.currentData() == "a" and edit.text() == "a --model x"
    assert caption_text(page, "DictationProviderCaption") == "Command"
    combo.setCurrentIndex(1)
    combo.activated.emit(1)

    assert made.choice() == (second, "gpt-x") and made.picked()
    assert edit.text() == "gpt-x" and caption_text(page, "DictationProviderCaption") == "Model"
    edit.setText("gpt-y")
    edit.editingFinished.emit()
    assert made.texts() == {"b": "gpt-y"}
    assert child(page, StatusLine, "DictationProviderStatus").tone() == "ok"


def test_a_refusing_provider_shows_the_reason_and_offers_its_setup_action(page_over):
    ran: list[str] = []
    provider = batch_provider(refusal="no API key", provider_id="api")
    provider = DictationProvider(
        provider.id,
        provider.label,
        "Model",
        "m",
        provider.refusal,
        transcribe=provider.transcribe,
        setup_action="openai.key",
        url="https://x.example",
    )
    page, _made = page_over(provider, ran=ran)

    status = child(page, StatusLine, "DictationProviderStatus")
    assert status.tone() == "error" and status.words() == "Fake engine: no API key"
    setup = child(page, QPushButton, "DictationSetupButton")
    assert not setup.isHidden()
    setup.click()
    assert ran == ["openai.key"]
    assert "https://x.example" in child(page, QLabel, "DictationProviderLink").text()


def test_automatic_names_the_first_installed_recorder_and_a_typed_command_is_custom(page_over):
    page, made = page_over(batch_provider(), recorders=(QUIET, HERE))
    combo = child(page, QComboBox, "DictationRecorderCombo")
    status = child(page, StatusLine, "DictationRecorderStatus")

    assert combo.currentText() == AUTOMATIC
    assert status.words() == "Recording with Quiet recorder, the first installed"
    assert caption_text(page, "DictationRecorderCaption") == "Command — Automatic"

    combo.setCurrentIndex(2)
    combo.activated.emit(2)
    assert made.recorder_command() == HERE.command
    assert status.words() == "Recording with Fake recorder"

    edit = child(page, QLineEdit, "DictationRecorderEdit")
    edit.setText("my-recorder --raw")
    edit.editingFinished.emit()
    assert combo.currentText() == "Custom"
    assert status.tone() == "error" and "my-recorder is not on PATH" in status.words()


def test_a_recorder_that_is_not_installed_says_so_in_its_row(page_over):
    missing = Recorder("gone", "Gone", "linux", "gone --raw", "gone")
    page, _made = page_over(batch_provider(), recorders=(HERE, missing))
    combo = child(page, QComboBox, "DictationRecorderCombo")
    assert combo.itemText(2) == f"Gone — {NOT_FOUND}"


def test_try_it_records_transcribes_and_says_what_it_heard(app, page_over):
    page, _made = page_over(batch_provider(Batch("hello there")))
    button, heard = (
        child(page, QPushButton, "DictationTryButton"),
        child(page, StatusLine, "DictationHeard"),
    )

    button.click()
    assert button.text() == "Stop" and heard.tone() == "busy"
    deadline = time.time() + 0.05
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    button.click()
    wait_for(app, lambda: heard.tone() == "ok", what="the trial")

    assert heard.words() == "Heard: hello there"
    assert button.text() == "Dictate a sentence"


def test_try_it_is_greyed_and_the_page_says_why_with_nothing_ready(page_over):
    page, _made = page_over(which=lambda _name: None)  # No providers at all.
    assert not child(page, QPushButton, "DictationTryButton").isEnabled()
    assert child(page, StatusLine, "DictationProviderStatus").tone() == "error"


@pytest.mark.parametrize(
    ("platform", "expected"), [("darwin", "Fn twice"), ("win32", "Win+H"), ("linux", None)]
)
def test_the_page_names_the_os_dictation_only_where_there_is_one(page_over, platform, expected):
    page, _made = page_over(batch_provider(), platform=platform, recorders=(HERE,))
    notes = [w.text() for w in page.findChildren(QLabel) if w.objectName() == "InspectorNote"]
    assert any(expected in text for text in notes) if expected else notes == []


def test_a_key_added_under_the_llm_service_reaches_every_microphone(services):
    """The builder bridges llm.config_changed to dictation: a key added under Settings ▸
    Providers is a change every microphone re-asks about."""
    seen: list[str] = []
    services.dictation.config_changed.connect(lambda: seen.append("re-read"))
    services.llm.config_changed.emit()
    assert seen == ["re-read"]
