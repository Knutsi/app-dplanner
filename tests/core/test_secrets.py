"""The keychain wrapper's honesty probe: a surface about to store a secret can ask whether
this machine can keep one, and a plaintext backend is a problem, not a fallback."""

import keyring
import keyring.backends.fail

from dplanner.core import secrets


class _Plaintext:
    __module__ = "keyrings.alt.file"


class _Native:
    __module__ = "keyring.backends.macOS"


def test_the_failing_backend_is_a_problem_with_a_remedy(monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: keyring.backends.fail.Keyring())
    problem = secrets.backend_problem()
    assert problem is not None and "keychain" in problem


def test_a_plaintext_backend_is_a_problem_too(monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: _Plaintext())
    problem = secrets.backend_problem()
    assert problem is not None and "plain file" in problem


def test_a_native_backend_is_fine(monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: _Native())
    assert secrets.backend_problem() is None


def test_a_backend_that_cannot_even_be_asked_is_a_problem(monkeypatch):
    def boom():
        raise RuntimeError("no dbus")

    monkeypatch.setattr(keyring, "get_keyring", boom)
    problem = secrets.backend_problem()
    assert problem is not None and "RuntimeError" in problem
