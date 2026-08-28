"""Namespaced global (per-user-machine) preference storage for module-contributed settings.

The framework's own bare ``QSettings()`` call sites (``session.py``,
``theme_service.py``, ``zoom.py``) stay as they are — each stores one window-level fact.
This is different: any module with a Global :class:`~dplanner.framework.settings_registry`
section needs somewhere to put its values, and without a shared convention every module
would invent its own key scheme. These two functions are that convention — still bare
``QSettings()`` per call, no injected service, just namespaced and JSON-safe so a
section's factory can store lists/dicts/bools without QSettings' variant quirks (e.g. a
one-element list collapsing to a bare string on read).
"""

import json
from typing import Any

from PySide6.QtCore import QSettings

_GROUP = "modules"


def _key(module_id: str, key: str) -> str:
    return f"{_GROUP}/{module_id}/{key}"


def get_global(module_id: str, key: str, default: Any = None) -> Any:
    raw = QSettings().value(_key(module_id, key))
    if raw is None:
        return default
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return default


def set_global(module_id: str, key: str, value: Any) -> None:
    QSettings().setValue(_key(module_id, key), json.dumps(value))
