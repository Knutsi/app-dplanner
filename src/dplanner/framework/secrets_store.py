"""API keys and other per-user secrets, in the OS credential store — never on disk.

The only secrets an application built this way should hold are third-party API keys.
``QSettings`` (used for everything else global) writes plaintext to an ``.ini``/``.plist``
file, which is fine for a theme name but not a credential — ``keyring`` puts the value in
the platform's native store (macOS Keychain, libsecret on Linux, Credential Manager on
Windows) instead.

A machine with no usable keyring backend (common in minimal/headless environments) must
not crash the app — every call is caught and degrades to "no secret stored" rather than
raising, so a missing backend behaves like an unconfigured provider, not a broken one.
"""

import contextlib

import keyring
import keyring.errors

from dplanner.identity import APP_ID

_SERVICE = APP_ID


def _username(module_id: str, key: str) -> str:
    return f"{module_id}.{key}"


def get_secret(module_id: str, key: str) -> str | None:
    try:
        return keyring.get_password(_SERVICE, _username(module_id, key))
    except keyring.errors.KeyringError:
        return None


def set_secret(module_id: str, key: str, value: str) -> None:
    with contextlib.suppress(keyring.errors.KeyringError):
        keyring.set_password(_SERVICE, _username(module_id, key), value)


def delete_secret(module_id: str, key: str) -> None:
    with contextlib.suppress(keyring.errors.KeyringError):
        keyring.delete_password(_SERVICE, _username(module_id, key))
