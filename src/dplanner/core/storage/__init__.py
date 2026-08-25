"""Where the bytes live.

One workspace, one provider. The provider owns files and (optionally) their history; it
never knows what the files mean — that is the repository's job, one layer up.

Import the protocols from :mod:`dplanner.core.storage.provider` and open a provider through
:func:`dplanner.core.storage.locations.open_storage`. The concrete classes are deliberately
harder to reach: rule 7 in ``tests/test_architecture.py`` forbids importing them anywhere
except inside this package and the composition root, so a feature can never quietly pin
itself to git.
"""

from dplanner.core.storage.locations import (
    StorageLocation,
    describe_location,
    open_storage,
    parse_location,
)
from dplanner.core.storage.provider import (
    RemoteStorage,
    Revision,
    StorageError,
    StoragePath,
    StorageProvider,
    VersionedStorage,
)

__all__ = [
    "RemoteStorage",
    "Revision",
    "StorageError",
    "StorageLocation",
    "StoragePath",
    "StorageProvider",
    "VersionedStorage",
    "describe_location",
    "open_storage",
    "parse_location",
]
