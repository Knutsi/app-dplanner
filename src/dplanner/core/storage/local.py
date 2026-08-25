"""A plain directory: the provider with no history.

The simplest thing that satisfies :class:`~dplanner.core.storage.provider.StorageProvider`,
and the base every other provider builds on — git and GitHub inherit the file operations
from here and add history on top, so the read/write path is identical in all three and is
tested once.

It satisfies neither ``VersionedStorage`` nor ``RemoteStorage``, which is the point: an
application opened on a plain folder shows no Save action, no branch label and no sync
status, because none of those would mean anything. Nothing has to check a flag.
"""

from pathlib import Path, PurePosixPath

from dplanner.core.fsio import write_atomic
from dplanner.core.storage.provider import StoragePath


class LocalStorage:
    """Files under one directory, created on first use."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def label(self) -> str:
        home = Path.home()
        # A path under $HOME reads better as ~/… — workspace labels end up in window
        # titles and menus, where an absolute path is mostly noise.
        if self._root.is_relative_to(home):
            return f"~/{self._root.relative_to(home)}"
        return str(self._root)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.label!r})"

    # -- paths ---------------------------------------------------------------------------------

    def _resolve(self, path: StoragePath) -> Path:
        """A workspace-relative path as a real one, refusing anything that escapes the root."""
        relative = PurePosixPath(str(path))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"path must stay inside the workspace: {path!r}")
        return self._root.joinpath(*relative.parts)

    # -- reading -------------------------------------------------------------------------------

    def exists(self, path: StoragePath) -> bool:
        return self._resolve(path).exists()

    def is_dir(self, path: StoragePath) -> bool:
        return self._resolve(path).is_dir()

    def read_text(self, path: StoragePath) -> str | None:
        target = self._resolve(path)
        if not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def read_bytes(self, path: StoragePath) -> bytes | None:
        target = self._resolve(path)
        if not target.is_file():
            return None
        return target.read_bytes()

    def list_dir(self, path: StoragePath = "") -> list[str]:
        target = self._resolve(path)
        if not target.is_dir():
            return []
        return sorted(entry.name for entry in target.iterdir())

    # -- writing -------------------------------------------------------------------------------

    def write_text(self, path: StoragePath, text: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(target, text)

    def write_bytes(self, path: StoragePath, data: bytes) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_bytes(data)
        tmp.replace(target)

    def delete(self, path: StoragePath) -> None:
        target = self._resolve(path)
        if target.is_dir():
            # Only empty directories: removing a tree is a decision the repository makes
            # explicitly, file by file, so a bug here can never take a workspace with it.
            if not any(target.iterdir()):
                target.rmdir()
            return
        target.unlink(missing_ok=True)

    def make_dir(self, path: StoragePath) -> None:
        self._resolve(path).mkdir(parents=True, exist_ok=True)
