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


def test_a_vault_this_session_cannot_reach_reads_as_no_secret(monkeypatch):
    """The Windows Credential Manager backend raises its own pywintypes.error — neither an
    OSError nor a KeyringError — when the logon session has no vault: a network logon
    such as SSH, WinError 1312. Every surface that asks for a secret has to get "none"
    rather than a traceback, because the checklist is the surface that reports exactly
    this."""
    import keyring

    from dplanner.core import secrets

    class BackendError(Exception):
        """pywintypes.error: neither an OSError nor a KeyringError."""

    def no_vault(*_args, **_kwargs):
        raise BackendError(1312, "CredRead", "A specified logon session does not exist")

    monkeypatch.setattr(keyring, "get_password", no_vault)
    monkeypatch.setattr(keyring, "set_password", no_vault)
    monkeypatch.setattr(keyring, "delete_password", no_vault)
    assert secrets.get_secret("llm", "openai") is None
    secrets.set_secret("llm", "openai", "sk-x")  # Kept nowhere, and says nothing.
    secrets.delete_secret("llm", "openai")
