"""API keys and other per-user secrets, in the OS credential store — never on disk.

The only secrets an application built this way should hold are third-party API keys.
``QSettings`` (used for everything else global) writes plaintext to an ``.ini``/``.plist``
file, which is fine for a theme name but not a credential — ``keyring`` puts the value in
the platform's native store (macOS Keychain, libsecret on Linux, Credential Manager on
Windows) instead.

A machine with no usable keyring backend (common in minimal/headless environments) must
not crash the app — every call is caught and degrades to "no secret stored" rather than
raising, so a missing backend behaves like an unconfigured provider, not a broken one.
A surface that is about to *store* a secret asks :func:`backend_problem` first, so it can
refuse with the remedy instead of storing nowhere silently; a plaintext backend
(``keyrings.alt``) counts as a problem, never as a fallback.

This lives in ``core/`` rather than ``framework/`` for :mod:`~dplanner.core.config_dir`'s
reason: nothing here touches Qt, and the headless surfaces must be able to ask. ``cli/``
may not import ``framework/`` at all, and neither may a module's Qt-free half — so the
checklist could not otherwise say whether this machine can keep a credential.
"""

import contextlib
import sys

import keyring
import keyring.errors

from dplanner.identity import APP_ID

_SERVICE = APP_ID

# Backends that keep the value in a plain file. keyring never picks one unless it is
# installed and preferred, but a credential must not land in one even then.
_PLAINTEXT_BACKENDS = ("keyrings.alt",)


def _username(module_id: str, key: str) -> str:
    return f"{module_id}.{key}"


# What a backend raises when the vault is not there for *this* session — and it is not one
# type. keyring wraps most failures in KeyringError, but the Windows Credential Manager
# backend lets its own through: a network logon (an SSH session, a service) has no
# credential vault, CredRead answers WinError 1312 "a specified logon session does not
# exist", and pywin32-ctypes raises that as pywintypes.error, which is not an OSError and
# not a KeyringError. Naming every backend's type here would mean importing every backend.
# This is the one seam the application asks a vault through, and its contract is that an
# unreachable vault reads as no secret and nothing kept — so any failure is unavailable.
# The checklist, whose job is to report exactly this, crashed reporting it on Windows.
_UNAVAILABLE = (keyring.errors.KeyringError, Exception)


def get_secret(module_id: str, key: str) -> str | None:
    try:
        return keyring.get_password(_SERVICE, _username(module_id, key))
    except _UNAVAILABLE:
        return None


def set_secret(module_id: str, key: str, value: str) -> None:
    with contextlib.suppress(*_UNAVAILABLE):
        keyring.set_password(_SERVICE, _username(module_id, key), value)


def delete_secret(module_id: str, key: str) -> None:
    with contextlib.suppress(*_UNAVAILABLE):
        keyring.delete_password(_SERVICE, _username(module_id, key))


def backend_problem() -> str | None:
    """Why a secret could not be kept safely on this machine — None when it can be.

    Probes the backend keyring chose rather than storing a probe value: a store is what
    raises a keychain prompt, and a surface asking whether it *may* store should not.
    """
    try:
        backend = keyring.get_keyring()
    except Exception as error:  # keyring's own errors, or a backend's import failing.
        return f"the OS keychain could not be reached ({type(error).__name__})"
    module = type(backend).__module__
    if module.startswith("keyring.backends.fail") or module.startswith("keyring.backends.null"):
        return _NO_BACKEND
    if any(module.startswith(name) for name in _PLAINTEXT_BACKENDS):
        return "the only keychain available would keep the value in a plain file"
    return None


_NO_BACKEND = (
    "no keychain service is running — install and unlock GNOME Keyring or KWallet, then try again"
    if sys.platform.startswith("linux")
    else "no OS keychain is available on this machine"
)
