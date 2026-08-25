"""Versioned module data, and the migrations that keep it current.

Each ``modules/<module_id>.json`` is opaque to your store; its shape belongs to one module.
So its version does too: a ``"format"`` key inside the dict (absent = format 1), and a
:class:`ModuleDataFormat` declared beside the module's persistence code saying what the
current format is and how each older one becomes the next. The builder runs
:func:`migrate_module_data` once per open — after the workspace loads and before any module
registers, because modules read their data in ``register()`` — and persists what changed.

This is the *second* version axis. Your workspace format is one migration chain owned by
:mod:`dplanner.domain`; each module owns the history of its own JSON. Whoever owns a piece
of data owns its history, and neither axis has to know about the other.

A retired module's data is migrated the same way by whoever takes it over: the new owner's
package carries the old module's id and frozen migration chain (a :class:`Takeover`) — the
on-disk schema was always the contract between them, and no module imports another. Data
nobody declares (a future module, a plugin) is left exactly as found. See ``FORMAT.md``.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from dplanner.core.repository import DataOwner, Repository

logger = logging.getLogger(__name__)

FORMAT_KEY = "format"

# One step of a module's chain: format k → k+1. Pure — takes the dict, returns the dict.
type DataMigration = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ModuleDataFormat:
    module_id: str
    version: int = 1
    migrations: tuple[DataMigration, ...] = ()  # migrations[k] takes format k+1 to k+2.
    takeovers: tuple["Takeover", ...] = ()  # Retired modules whose data this one absorbs.

    def __post_init__(self) -> None:
        if len(self.migrations) != self.version - 1:
            raise ValueError(
                f"{self.module_id}: format {self.version} needs {self.version - 1} "
                f"migrations, got {len(self.migrations)}"
            )


@dataclass(frozen=True)
class Takeover:
    retired: ModuleDataFormat  # The old module's id and chain, kept by the new owner.
    # (retired data at retired.version, the owner's existing data or {}) → owner data.
    convert: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def data_version(data: dict[str, Any]) -> int:
    version = data.get(FORMAT_KEY, 1)
    return version if isinstance(version, int) and not isinstance(version, bool) else 1


def stamped(data: dict[str, Any], version: int) -> dict[str, Any]:
    """``data`` carrying its format — or ``{}`` when the format would be its only key,
    so "nothing to store" still leaves no file behind (``set_module_data`` removes an
    empty entry)."""
    if not any(key != FORMAT_KEY for key in data):
        return {}
    return {**data, FORMAT_KEY: version}


def migrate_module_data(repo: Repository[Any], formats: Sequence[ModuleDataFormat]) -> list[str]:
    """Bring every owner's declared module data to its current format.

    Returns the owner ids that changed, so the caller can persist exactly those. Entries
    newer than declared are left alone: the module's tolerant loader ignores what it cannot
    read, and an older build of the application must never overwrite a newer one's data —
    in a workspace shared through git that is the difference between "this feature looks
    empty until I update" and "my colleague's work is gone".
    """
    changed: list[str] = []
    for owner in repo.owners():
        touched = False
        for declared in formats:
            for takeover in declared.takeovers:
                touched |= _take_over(repo, owner, declared, takeover)
            touched |= _bring_current(repo, owner, declared)
        if touched:
            changed.append(owner.id)
    return changed


def _migrated(data: dict[str, Any], declared: ModuleDataFormat) -> dict[str, Any] | None:
    """``data`` at ``declared.version``, or None when it is already there or beyond."""
    version = data_version(data)
    if version >= declared.version:
        if version > declared.version:
            logger.warning(
                "%s data is format %d, newer than this build's %d; leaving it untouched",
                declared.module_id,
                version,
                declared.version,
            )
        return None
    for migration in declared.migrations[version - 1 :]:
        data = migration(data)
    return stamped(data, declared.version)


def _bring_current(repo: Repository[Any], owner: DataOwner, declared: ModuleDataFormat) -> bool:
    data = owner.module_data.get(declared.module_id)
    if data is None:
        return False
    migrated = _migrated(data, declared)
    if migrated is None:
        return False
    repo.set_module_data(owner.id, declared.module_id, migrated)
    return True


def _take_over(
    repo: Repository[Any], owner: DataOwner, successor: ModuleDataFormat, takeover: Takeover
) -> bool:
    retired = owner.module_data.get(takeover.retired.module_id)
    if retired is None:
        return False
    current = _migrated(retired, takeover.retired)
    if current is None and data_version(retired) > takeover.retired.version:
        return False  # Newer than the retired module ever wrote: not ours to touch.
    existing = owner.module_data.get(successor.module_id, {})
    converted = takeover.convert(current if current is not None else retired, existing)
    repo.set_module_data(owner.id, successor.module_id, stamped(converted, successor.version))
    repo.set_module_data(owner.id, takeover.retired.module_id, {})
    return True
