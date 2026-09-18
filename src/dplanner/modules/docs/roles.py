"""The location role the docs module acts on: where a project's documentation goes.

A ``docs`` row names a repository and a folder in it — usually ``docs/`` inside the code —
and is worked in: a document written there is a change somebody commits, so it needs a
checkout the person owns. Qt-free: the composition root gathers every module's
``roles.py`` into one registry.
"""

from dplanner.domain.locations import LocationRole

ROLE = LocationRole(
    id="docs",
    label="Docs",
    summary="Where the project's documentation is written — a folder in a repository.",
    writes=True,
    default_path="docs",
)
