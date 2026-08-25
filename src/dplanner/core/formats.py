"""Your workspace's format, and the chain that keeps old folders readable.

This is the *first* version axis (the second is per-module data — see
:mod:`dplanner.core.module_data`). It covers the layout of the workspace directory and the
keys in your own JSON files, and it is owned by :mod:`dplanner.domain`: the engine is here,
the chain is yours.

Three rules make the chain trustworthy, and all three are learned from a format that has
already been through seven versions:

1. **Never edit an existing migration.** A folder written by version 1 still walks the
   entire chain, and each step's output is the next step's input. Editing step 2 silently
   changes what step 3 receives from every old workspace on every machine.
2. **Append, always.** A new format is a new :class:`Migration` at the end of the tuple;
   ``current_version`` is derived from the chain, never written twice.
3. **Migrate once, at open, then save the whole workspace.** Never leave a half-migrated
   folder for a later partial autosave to finish — that is how a format ends up in a state
   no migration describes.

A folder written by something *newer* than this build is refused outright rather than
partially read, and never written to. See :class:`UnsupportedFormatError`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORMAT_KEY = "format"


class UnsupportedFormatError(ValueError):
    """This workspace's format cannot be read by this build."""

    def __init__(self, path: Path, found: object, oldest: int, newest: int) -> None:
        self.path = path
        self.found = found
        self.oldest = oldest
        self.newest = newest
        super().__init__(f"{path}: format {found!r} (this build reads {oldest} to {newest})")

    @property
    def is_newer(self) -> bool:
        """True when the workspace comes from a *newer* build — the reassuring case: the
        data is fine, the application is behind. Worth saying so, because the usual cause
        is a colleague's push or a branch switch, not corruption."""
        return isinstance(self.found, int) and self.found > self.newest


@dataclass(frozen=True)
class Migration[NodeT, RootT]:
    """One step of the chain: everything at ``version - 1`` becomes ``version``.

    Two optional hooks, because the two things a format change touches are different:
    ``node`` runs per node as it loads, with the raw dict it was built from and its
    directory, and can therefore reach data the model no longer has a field for; ``whole``
    runs once over the finished aggregate, for anything that needs to see the shape.
    """

    version: int
    note: str  # One line, shown in logs and in FORMAT.md's history table.
    node: Callable[[NodeT, dict[str, Any], Path], None] | None = None
    whole: Callable[[RootT], None] | None = None


class FormatHistory[NodeT, RootT]:
    """An ordered chain of migrations, and the questions a loader asks it."""

    def __init__(self, migrations: tuple[Migration[NodeT, RootT], ...], oldest_readable: int = 1):
        versions = [m.version for m in migrations]
        if versions != sorted(versions) or len(set(versions)) != len(versions):
            raise ValueError("migrations must be ordered and each version declared once")
        if migrations and migrations[0].version < 2:
            raise ValueError("the first migration takes format 1 to 2, so it is version 2")
        self.migrations = migrations
        self.oldest_readable = oldest_readable

    @property
    def current_version(self) -> int:
        """Derived from the chain, so adding a migration is the only edit a bump needs."""
        return self.migrations[-1].version if self.migrations else 1

    def read_version(self, meta: dict[str, Any], path: Path) -> int:
        """The format ``meta`` declares, or raise if this build cannot read it."""
        found = meta.get(FORMAT_KEY)
        if (
            not isinstance(found, int)
            or isinstance(found, bool)
            or found < self.oldest_readable
            or found > self.current_version
        ):
            raise UnsupportedFormatError(path, found, self.oldest_readable, self.current_version)
        return found

    def pending(self, found: int) -> tuple[Migration[NodeT, RootT], ...]:
        """Every migration newer than ``found``, in order."""
        return tuple(m for m in self.migrations if m.version > found)
