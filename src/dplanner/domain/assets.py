"""Content-addressed files in a module's file area.

Shared by every aspect that keeps files beside a node — descriptions with images, handoffs
with reference material. Files are named by the hash of their content, so attaching the same
file twice is a no-op and a rename upstream never churns a link. The suffix is kept because
a browser and a person both use it to tell what the file is.

An asset add is not undoable, and that is the honest trade: undoing a paste would leave
prose pointing at a file that had gone. An orphaned blob is recoverable; a dangling link
is not.
"""

import hashlib
from pathlib import PurePosixPath

from dplanner.domain.store import ModuleFileArea

ASSETS_DIR = "assets"


def asset_name(data: bytes, filename: str) -> str:
    """``assets/<hash><suffix>`` — the path to reference from prose in the same module."""
    suffix = PurePosixPath(filename).suffix.lower()
    return f"{ASSETS_DIR}/{hashlib.sha256(data).hexdigest()[:16]}{suffix}"


def attach(area: ModuleFileArea, data: bytes, filename: str) -> str:
    """Put a file in the module's area; returns the path to link to."""
    name = asset_name(data, filename)
    area.write_bytes(name, data)
    return name


def assets(area: ModuleFileArea) -> list[str]:
    """Every asset the area holds, sorted, as area-relative paths."""
    return sorted(f"{ASSETS_DIR}/{name}" for name in area.names(ASSETS_DIR))
