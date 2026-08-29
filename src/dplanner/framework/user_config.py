"""Namespaced per-user-machine storage for what modules and surfaces remember.

The framework's own bare ``QSettings()`` call sites (``session.py``, ``theme_service.py``,
``zoom.py``) stay as they are — each stores one window-level fact. This is different: any
module with a Global :class:`~dplanner.framework.settings_registry` section, and any
surface that remembers where the user left it, needs somewhere to put its values, and
without a shared convention each would invent its own key scheme. These functions are that
convention — still bare ``QSettings()`` per call, no injected service, just namespaced and
JSON-safe so a caller can store lists/dicts/bools without QSettings' variant quirks (e.g. a
one-element list collapsing to a bare string on read).

**Two scopes, because two different things are being kept.** A *preference* ("reopen my
tabs", "which model") is the user's, and follows them into every library they open: that is
:func:`get_global`. *Where the user left off* ("these folders were open, these tabs") is
only true of one library, and restoring library A's tabs into library B would be nonsense:
that is :func:`get_scoped`, under a scope :func:`library_scope` derives from the library's
path. Neither ever reaches the workspace — nothing here is committed.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

_GROUP = "modules"
_SCOPED_GROUP = "libraries"


def get_global(owner: str, key: str, default: Any = None) -> Any:
    """A preference of ``owner``'s, the same in whichever library is open."""
    return _read(f"{_GROUP}/{owner}/{key}", default)


def set_global(owner: str, key: str, value: Any) -> None:
    _write(f"{_GROUP}/{owner}/{key}", value)


def library_scope(library_path: Path) -> str:
    """A stable, key-safe name for one library's slice of this store.

    A digest rather than the path itself: a QSettings key is a ``/``-separated tree, so a
    path put in one whole would fan out into a directory's worth of empty groups.
    """
    resolved = Path(library_path).expanduser().resolve()
    return hashlib.sha256(str(resolved).encode()).hexdigest()[:16]


def get_scoped(scope: str, owner: str, key: str, default: Any = None) -> Any:
    """What ``owner`` remembers about one library. An empty ``scope`` remembers nothing —
    a surface built without one (a test's, say) reads and writes no preferences at all."""
    if not scope:
        return default
    return _read(f"{_SCOPED_GROUP}/{scope}/{owner}/{key}", default)


def set_scoped(scope: str, owner: str, key: str, value: Any) -> None:
    if scope:
        _write(f"{_SCOPED_GROUP}/{scope}/{owner}/{key}", value)


def _read(key: str, default: Any) -> Any:
    raw = QSettings().value(key)
    if raw is None:
        return default
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return default


def _write(key: str, value: Any) -> None:
    QSettings().setValue(key, json.dumps(value))
