"""What the framework knows about your data — and no more.

Your model is yours. It lives in :mod:`dplanner.domain`, it is shaped like your problem,
and the framework has no opinion about it. But the framework still has to do four things
on your behalf: migrate module data before any module reads it, debounce writes, hand
features a reference to the data, and tear it down on close. This module is exactly that
much contract and nothing else.

Three small protocols:

- :class:`DataOwner` — a node that can carry per-module JSON. In Writer this is a segment;
  in a planner it is a task; in your application it is whatever the user thinks of as a
  thing with properties.
- :class:`Repository` — the aggregate the framework holds: it can list its owners, accept
  module data, report what is dirty, and flush.
- :class:`Persister` — the write half, kept separate so ``AutosaveService`` depends on the
  smallest possible surface.

**The dirty/flush seam.** Writer wires five model signals to six named ``store.save_*``
methods, which means its autosave cannot serve a second model. Here the repository emits
one ``dirty(owner_id, aspect)`` signal, the framework's ``AutosaveService`` only debounces
and batches it, and ``flush(marks)`` on your store decides what an *aspect* means and in
what order the writes happen. Your vocabulary, framework's timer.

A repository is constructed from a *source path* — a file or directory your domain package
interprets — rather than a storage provider, because a repository may span several
providers (DPlanner's spans one per project). What providers it opens underneath is its
own business.

Modules that need the real model types import :mod:`dplanner.domain` directly; the layering
rules allow that. This protocol exists so the *framework* never has to.
"""

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from dplanner.core.signals import Signal

# (owner id, aspect name). The aspect vocabulary belongs to your store: Writer uses
# "text"/"meta"/"structure"; a planner might use "fields"/"dependencies".
type DirtyMark = tuple[str, str]

# Passed to a mutator so a view can recognise — and ignore — the echo of its own edit.
# Identity is the whole mechanism: ``origin is self``. See framework/undo.py.
type Origin = object | None


@runtime_checkable
class DataOwner(Protocol):
    """A node that can carry per-module JSON. See ``FORMAT.md``."""

    id: str
    module_data: dict[str, dict[str, Any]]


class FileArea(Protocol):
    """The files one module keeps beside one owner — what an absorption may read and
    write (see :class:`~dplanner.core.module_data.ModuleDataFormat`). Names are
    area-relative; ``read_bytes`` answers None for a name the area does not hold."""

    def names(self, subdirectory: str = "") -> list[str]: ...

    def read_bytes(self, name: str) -> bytes | None: ...

    def write_bytes(self, name: str, data: bytes) -> None: ...

    def remove(self, name: str) -> None: ...


class Persister(Protocol):
    """The write half of a repository — all ``AutosaveService`` is allowed to see."""

    def flush(self, marks: set[DirtyMark]) -> None:
        """Write everything ``marks`` names, in whatever order this format requires.

        Called with the whole batch rather than one mark at a time, because ordering
        between aspects is a real constraint: a format with nested directories must
        create and move them before it deletes the emptied ones, or a pending move loses
        its subtree.
        """
        ...


class Repository[DocT](Protocol):
    """One session's data. Constructed by your ``domain`` package, over a source path.

    Generic in the aggregate it loads, so the framework can hand your real type back to the
    composition root without ever naming it.
    """

    # (owner id, aspect) — the framework debounces this and calls flush().
    dirty: Signal[str, str]

    def exists(self) -> bool:
        """Whether the source already holds data. False means seed it first."""
        ...

    def load(self) -> DocT:
        """Read the data, running any pending format migrations."""
        ...

    def owners(self) -> Iterable[DataOwner]:
        """Every node that can carry module data, for the migration pass at open."""
        ...

    def owner(self, owner_id: str) -> DataOwner | None: ...

    def set_module_data(self, owner_id: str, module_id: str, data: dict[str, Any]) -> None:
        """Replace one module's entry on one owner. An empty dict removes it."""
        ...

    def files(self, owner_id: str, module_id: str) -> FileArea:
        """The files ``module_id`` keeps beside ``owner_id`` — for an absorption that
        moves a module's files along with its data."""
        ...

    def flush(self, marks: set[DirtyMark]) -> None: ...

    def close(self) -> None:
        """Release anything held open. Called when this build is discarded."""
        ...


type RepositoryFactory[DocT] = Callable[[Path], Repository[DocT]]
