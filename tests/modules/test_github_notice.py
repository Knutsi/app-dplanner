"""The missing-gh launch warning: once per process, dismissable for good."""

import pytest

from dplanner.modules.github import notice


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    monkeypatch.setattr(notice, "_warned_this_process", False)


def test_a_missing_gh_warns_once_per_process(app):
    box = notice.maybe_warn(None, installed=lambda: False)
    assert box is not None
    assert box.checkBox().isChecked()  # "Show next time" defaults to on.
    assert notice.maybe_warn(None, installed=lambda: False) is None
    box.done(0)


def test_unchecking_show_next_time_persists(app, monkeypatch):
    box = notice.maybe_warn(None, installed=lambda: False)
    assert box is not None
    box.checkBox().setChecked(False)
    box.done(0)
    assert notice.warn_enabled() is False
    # Even a fresh process (flag reset) honours the stored preference.
    monkeypatch.setattr(notice, "_warned_this_process", False)
    assert notice.maybe_warn(None, installed=lambda: False) is None


def test_an_installed_gh_stays_silent(app):
    assert notice.maybe_warn(None, installed=lambda: True) is None
    # Silence did not spend the once-per-process warning.
    box = notice.maybe_warn(None, installed=lambda: False)
    assert box is not None
    box.done(0)
