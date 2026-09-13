"""``framework/key_dialog.py``: refused until the key is tested, saved only once it worked."""

import time

import pytest

from dplanner.framework.key_dialog import ApiKeyDialog
from dplanner.framework.tasks import TaskService


def wait_for(app, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the probe never settled"
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def dialog_over(app):
    made: list[ApiKeyDialog] = []

    def make(probe, *, backend_problem=None, current=""):
        dialog = ApiKeyDialog(
            None,
            service="Acme",
            guide="1. Make a key.\n2. Paste it.",
            keys_url="https://acme.example/keys",
            placeholder="ak-…",
            tasks=TaskService(),
            probe=probe,
            open_url=opened.append,
            backend_problem=backend_problem,
            current=current,
        )
        made.append(dialog)
        return dialog

    opened: list[str] = []
    make.opened = opened  # type: ignore[attr-defined]
    yield make
    for dialog in made:
        dialog.deleteLater()


def test_the_primary_is_refused_until_a_pasted_key_has_been_tested(app, dialog_over):
    dialog = dialog_over(lambda key: f"{len(key)} models")
    assert not dialog.save.isEnabled() and dialog.status.words() == ""

    dialog.key.setText("ak-123")
    assert not dialog.save.isEnabled() and dialog.status.words() == "Test the key first"
    dialog.test()
    wait_for(app, lambda: dialog.passed)

    assert dialog.save.isEnabled()
    assert dialog.status.words() == "The key works — 6 models." and dialog.status.tone() == "ok"
    dialog.key.setText("ak-1234")  # An edit undoes the test.
    assert not dialog.passed and not dialog.save.isEnabled()


def test_a_probe_that_refuses_is_said_in_the_error_tone(app, dialog_over):
    def probe(_key):
        raise RuntimeError("401 invalid_api_key")

    dialog = dialog_over(probe)
    dialog.key.setText("ak-bad")
    dialog.test()
    wait_for(app, lambda: dialog.status.tone() == "error")

    assert not dialog.passed and not dialog.save.isEnabled()
    assert dialog.status.words() == "401 invalid_api_key"


def test_a_keychain_that_cannot_keep_the_key_refuses_up_front(dialog_over):
    dialog = dialog_over(lambda _key: "ok", backend_problem="no keychain here")
    assert not dialog.test_button.isEnabled() and not dialog.save.isEnabled()
    assert dialog.status.words() == "Cannot store a key on this machine: no keychain here"


def test_the_browser_button_opens_the_keys_page_and_the_current_key_is_shown(dialog_over):
    dialog = dialog_over(lambda _key: "ok", current="ak-old")
    assert dialog.value() == "ak-old"
    dialog.open_keys.click()
    assert dialog_over.opened == ["https://acme.example/keys"]


def test_the_vendor_action_saves_a_tested_key_and_announces_it(services, monkeypatch):
    import keyring

    from dplanner.modules.llm_openai import module as openai_module

    stored: dict[str, str] = {}
    monkeypatch.setattr(
        keyring, "set_password", lambda _s, user, value: stored.__setitem__(user, value)
    )
    monkeypatch.setattr(keyring, "get_password", lambda _s, user: stored.get(user))

    class Accepting:
        DialogCode = ApiKeyDialog.DialogCode
        passed = True

        def __init__(self, *_args, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return ApiKeyDialog.DialogCode.Accepted

        def value(self):
            return "sk-new"

        def deleteLater(self):  # noqa: N802 - the dialog's own name
            pass

    monkeypatch.setattr(openai_module, "ApiKeyDialog", Accepting)
    announced: list[str] = []
    services.llm.config_changed.connect(lambda: announced.append("changed"))

    services.actions.run("llm_openai.key", services.context.current())

    assert stored == {"llm_openai.api_key": "sk-new"} and announced == ["changed"]
